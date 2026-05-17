#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой CLI-парсер материалов из каталога Петрович.

Скрипт самодостаточный: использует стандартную библиотеку и curl_cffi.
Куки/заголовки берутся из .env проекта:
  APP_PARSER_COOKIES={...}
  APP_PARSER_HEADERS={...}
"""

import argparse
import ast
import csv
import html
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

try:
    from curl_cffi.requests import Session
    from curl_cffi.requests.exceptions import RequestException
except ImportError:
    print("Установите curl_cffi: pip install curl_cffi", file=sys.stderr)
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATEGORIES_TREE_FILE = PROJECT_ROOT / "categories_full_tree.json"
ENV_FILE = PROJECT_ROOT / ".env"

API_BASE_URL = "https://api.petrovich.ru/catalog/v5/sections"
API_PRODUCTS_URL = "https://api.petrovich.ru/catalog/v5/products"
DEFAULT_SUPPLIER = "Петрович"
DEFAULT_CITY_CODE = "msk"
DEFAULT_CLIENT_ID = "pet_site"
PAGE_LIMIT = 50
MAX_CATEGORY_WORKERS = 8
MAX_PAGE_WORKERS = 10
SLEEP_BETWEEN_REQUESTS = 0.15
DEFAULT_REQUEST_TIMEOUT = 30
DETAIL_REQUEST_TIMEOUT = 10

CSV_COLUMNS = [
    "Код",
    "Название",
    "Ед. изм.",
    "Цена",
    "Валюта",
    "Категория",
    "Подкатегория",
    "Поставщик",
    "Синонимы",
    "Ключевые слова",
    "Описание",
    "Ссылка на изображение",
]

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Origin": "https://moscow.petrovich.ru",
    "Referer": "https://moscow.petrovich.ru/catalog/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    ),
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class PetrovichMaterialParser:
    """Парсер товаров Петрович с параллельными категориями и страницами."""

    def __init__(self, project_root: Path = PROJECT_ROOT) -> None:
        self.project_root = project_root
        self.cookies, env_headers = self._load_env_auth(project_root / ".env")
        self.headers = dict(DEFAULT_HEADERS)
        self.headers.update(env_headers)
        self.categories, self.total_tree_categories = self._load_categories_tree(
            project_root / CATEGORIES_TREE_FILE.name
        )

        # Session небезопасно шарить между потоками, поэтому у каждого
        # потока своя curl_cffi-сессия с одинаковыми куками/заголовками.
        self._thread_local = threading.local()
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0
        self._progress_lock = threading.Lock()
        self._completed_categories = 0

    def log(self, message: str) -> None:
        print(message, flush=True)

    # ---------- Загрузка настроек ----------

    def _load_env_file(self, path: Path) -> Dict[str, str]:
        values: Dict[str, str] = {}
        if not path.exists():
            return values

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            values[key] = value
        return values

    def _parse_dict(self, raw: Optional[str], name: str) -> Dict[str, str]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(raw)
            except Exception as exc:
                self.log(f"[WARN] Не удалось разобрать {name}: {exc}")
                return {}

        if not isinstance(parsed, dict):
            self.log(f"[WARN] {name} должен быть JSON-объектом")
            return {}
        return {str(k): str(v) for k, v in parsed.items() if k is not None and v is not None}

    def _load_env_auth(self, path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
        # Переменные окружения имеют приоритет над .env.
        file_values = self._load_env_file(path)
        cookies_raw = os.getenv("APP_PARSER_COOKIES") or file_values.get("APP_PARSER_COOKIES")
        headers_raw = os.getenv("APP_PARSER_HEADERS") or file_values.get("APP_PARSER_HEADERS")
        cookies = self._parse_dict(cookies_raw, "APP_PARSER_COOKIES")
        headers = self._parse_dict(headers_raw, "APP_PARSER_HEADERS")
        self.log(f"[OK] Загружено cookies: {len(cookies)}, headers: {len(headers)}")
        return cookies, headers

    def _load_categories_tree(self, path: Path) -> Tuple[List[Dict[str, Any]], int]:
        """Загрузить дерево категорий и собрать все категории, где есть товары."""
        categories: List[Dict[str, Any]] = []
        total_nodes = 0

        if not path.exists():
            self.log(f"[WARN] Файл дерева категорий не найден: {path}")
            return categories, total_nodes

        try:
            raw_tree = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.log(f"[ERR] Не удалось прочитать дерево категорий {path}: {exc}")
            return categories, total_nodes

        def iter_roots(tree: Any) -> Iterable[Tuple[Dict[str, Any], List[str]]]:
            if isinstance(tree, list):
                for node in tree:
                    if isinstance(node, dict):
                        yield node, []
            elif isinstance(tree, dict):
                for key, value in tree.items():
                    # Файл может быть вида {"ВСЕ КАТЕГОРИИ": [...]} или {"Категория": {...}}.
                    # Искусственный контейнер не добавляем в breadcrumbs, реальные узлы берём из title.
                    if isinstance(value, list):
                        for node in value:
                            if isinstance(node, dict):
                                yield node, []
                    elif isinstance(value, dict):
                        yield value, []
                    elif isinstance(value, (int, str)) and isinstance(tree, dict):
                        # На случай если сам tree уже является узлом категории.
                        break
                if "code" in tree and "title" in tree:
                    yield tree, []

        def walk(node: Dict[str, Any], path_parts: List[str]) -> None:
            nonlocal total_nodes
            total_nodes += 1

            title = str(node.get("title") or node.get("name") or node.get("code") or "").strip()
            current_path = path_parts + ([title] if title else [])
            children = node.get("children") or []
            product_qty_raw = node.get("product_qty") or 0
            try:
                product_qty = int(product_qty_raw)
            except (TypeError, ValueError):
                product_qty = 0

            code = str(node.get("code") or "").strip()
            if code and product_qty > 0:
                categories.append(
                    {
                        "code": code,
                        "name": title or code,
                        "title": title or code,
                        "parent": current_path[-2] if len(current_path) >= 2 else "",
                        "product_qty": product_qty,
                        "category_path": current_path,
                    }
                )

            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        walk(child, current_path)

        seen_roots = set()
        for root, root_path in iter_roots(raw_tree):
            root_key = id(root)
            if root_key in seen_roots:
                continue
            seen_roots.add(root_key)
            walk(root, root_path)

        self.log(
            f"[OK] В дереве категорий: {total_nodes}; категорий с товарами: {len(categories)}"
        )
        return categories, total_nodes

    # ---------- HTTP ----------

    def _session(self) -> Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = Session(impersonate="chrome131")
            session.headers.update(self.headers)
            for key, value in self.cookies.items():
                session.cookies.set(key, value)
            self._thread_local.session = session
        return session

    def _respect_rate_limit(self) -> None:
        # Глобальная мягкая задержка между стартами запросов.
        with self._request_lock:
            now = time.monotonic()
            wait = SLEEP_BETWEEN_REQUESTS - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def _retry_after_seconds(self, raw_value: Optional[str]) -> int:
        if not raw_value:
            return 15
        try:
            return max(1, min(int(float(raw_value)), 120))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw_value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                wait = (retry_at - datetime.now(timezone.utc)).total_seconds()
                return max(1, min(int(wait), 120))
            except (TypeError, ValueError, OverflowError):
                return 15

    def fetch_json(self, url: str, retry: int = 3, timeout: int = DEFAULT_REQUEST_TIMEOUT) -> Optional[Dict[str, Any]]:
        last_error = ""
        for attempt in range(1, retry + 1):
            try:
                self._respect_rate_limit()
                response = self._session().get(url, timeout=timeout)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                    self.log(f"[RATE] 429 Too Many Requests. Ждём {retry_after}с: {url}")
                    time.sleep(retry_after)
                    continue

                if response.status_code == 416:
                    return {"data": {"products": [], "total": 0}}

                preview = response.text[:180].replace("\n", " ")
                last_error = f"HTTP {response.status_code}: {preview}"
                if response.status_code in (401, 403, 406):
                    self.log(
                        f"[AUTH] Сессия/куки, вероятно, протухли (HTTP {response.status_code}). "
                        f"URL: {url}"
                    )
                    return None
                self.log(f"[HTTP] {last_error} (попытка {attempt}/{retry})")

            except RequestException as exc:
                last_error = str(exc)
                self.log(f"[ERR] Ошибка запроса (попытка {attempt}/{retry}): {exc}")
            except ValueError as exc:
                last_error = f"Некорректный JSON: {exc}"
                self.log(f"[ERR] {last_error}")
                return None

            time.sleep(min(3.0, 0.5 * attempt))

        self.log(f"[ERR] Запрос не удался после {retry} попыток: {last_error}")
        return None

    def build_products_url(self, section_code: str, offset: int) -> str:
        params = {
            "limit": PAGE_LIMIT,
            "offset": offset,
            "sort": "popularity_desc",
            "city_code": DEFAULT_CITY_CODE,
            "client_id": DEFAULT_CLIENT_ID,
        }
        return f"{API_BASE_URL}/{section_code}/products?{urlencode(params)}"

    def build_product_detail_url(self, product_code: str) -> str:
        params = {
            "city_code": DEFAULT_CITY_CODE,
            "client_id": DEFAULT_CLIENT_ID,
        }
        return f"{API_PRODUCTS_URL}/{product_code}?{urlencode(params)}"

    # ---------- Извлечение товара ----------

    def _property_values(self, prop: Dict[str, Any]) -> List[str]:
        raw_values = prop.get("value")
        if raw_values is None:
            return []
        if not isinstance(raw_values, list):
            raw_values = [raw_values]

        values: List[str] = []
        for value in raw_values:
            if isinstance(value, dict):
                title = value.get("title") or value.get("name") or value.get("value") or value.get("slug")
                if title:
                    values.append(str(title))
            elif value is not None:
                values.append(str(value))
        return [v.strip() for v in values if v and v.strip()]

    def _get_prop(self, properties: Iterable[Dict[str, Any]], slug: str) -> str:
        for prop in properties or []:
            if prop.get("slug") == slug:
                return ", ".join(self._property_values(prop))
        return ""

    def _extract_price(self, product: Dict[str, Any]) -> str:
        price = product.get("price") or {}
        value = price.get("retail") or price.get("gold") or ""
        if value == "":
            return ""
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return str(value)

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", value or "", flags=re.I)
        text = re.sub(r"</\s*(?:p|div|li|h[1-6])\s*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return html.unescape(text).strip()

    def _description_text_value(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("description", "text", "title", "value"):
                if value.get(key):
                    return self._description_text_value(value.get(key))
            return ""
        if isinstance(value, list):
            return "\n".join(
                part for part in (self._description_text_value(item) for item in value) if part
            )
        return self._as_csv_text(value)

    def _extract_detail_description(self, product: Dict[str, Any], generated_description: str) -> str:
        description = self._description_text_value(product.get("description_no_html"))
        if not description:
            html_description = self._description_text_value(product.get("description"))
            description = self._strip_html(html_description) if html_description else ""
        if not description:
            description = generated_description

        extended = self._description_text_value(product.get("extended_description_no_html"))
        if extended:
            description = f"{description}\n{extended}" if description else extended
        return description

    def _extract_supplier(self, product: Dict[str, Any]) -> str:
        supplier = product.get("supplier") or {}
        if isinstance(supplier, dict):
            title = str(supplier.get("title") or "").strip()
            if title:
                return title
        return DEFAULT_SUPPLIER

    def fetch_product_detail(self, product_code: str) -> Dict[str, Any]:
        """Fetch optional product detail data.

        The detail endpoint is frequently blocked by Qrator (403). Treat any
        non-200/timeout/invalid payload as a soft miss: the list item already
        has enough data to save a CSV row.
        """
        if not product_code:
            return {}
        detail_data = self.fetch_json(
            self.build_product_detail_url(product_code),
            retry=1,
            timeout=DETAIL_REQUEST_TIMEOUT,
        )
        if not detail_data:
            return {}
        product = (detail_data.get("data") or {}).get("product") or {}
        return product if isinstance(product, dict) else {}

    def _extract_weight(self, product: Dict[str, Any], properties: List[Dict[str, Any]]) -> str:
        weight = product.get("weight")
        if weight not in (None, ""):
            return str(weight).replace(",", ".")
        prop_weight = self._get_prop(properties, "ves")
        if not prop_weight:
            return ""
        match = re.search(r"\d+(?:[\.,]\d+)?", prop_weight.replace(" ", ""))
        return match.group(0).replace(",", ".") if match else prop_weight

    def _extract_levels(self, product: Dict[str, Any], fallback_category: Optional[Dict[str, Any]]) -> Dict[str, str]:
        titles: List[str] = []
        breadcrumbs = product.get("breadcrumbs") or []
        if isinstance(breadcrumbs, list):
            for crumb in breadcrumbs:
                if isinstance(crumb, dict) and crumb.get("title"):
                    title = str(crumb["title"]).strip()
                    if title and title.lower() != "главная":
                        titles.append(title)

        if not titles and fallback_category:
            category_path = fallback_category.get("category_path") or []
            if isinstance(category_path, list):
                titles.extend(str(part).strip() for part in category_path if str(part).strip())
            else:
                if fallback_category.get("parent"):
                    titles.append(str(fallback_category["parent"]))
                if fallback_category.get("name"):
                    titles.append(str(fallback_category["name"]))

        levels = {f"level{i}": "" for i in range(1, 7)}
        for index, title in enumerate(titles[:6], start=1):
            levels[f"level{index}"] = title
        return levels

    def _extract_image(self, product: Dict[str, Any]) -> str:
        images = product.get("images") or []
        if not isinstance(images, list) or not images:
            return ""
        first = images[0]
        image = first.get("url") if isinstance(first, dict) else str(first)
        if image.startswith("//"):
            image = "https:" + image
        return image

    def _extract_dimensions(self, name: str, properties: List[Dict[str, Any]]) -> str:
        dimension_slugs = {"razmer", "razmery", "gabarity", "dlina", "shirina", "vysota", "tolshchina"}
        dimension_title_parts = ("размер", "габарит", "длина", "ширина", "высота", "толщина")

        for prop in properties or []:
            title = str(prop.get("title") or "").strip().lower()
            slug = str(prop.get("slug") or "").strip().lower()
            if slug in dimension_slugs or any(part in title for part in dimension_title_parts):
                values = ", ".join(self._property_values(prop))
                if values:
                    return values

        match = re.search(
            r"\b\d+(?:[\.,]\d+)?\s*[xх×]\s*\d+(?:[\.,]\d+)?"
            r"(?:\s*[xх×]\s*\d+(?:[\.,]\d+)?)?\s*(?:мм|см|м)\b",
            name or "",
            flags=re.I,
        )
        return re.sub(r"\s+", " ", match.group(0)).replace("x", "×").replace("х", "×") if match else ""

    def _make_description(self, name: str, properties: List[Dict[str, Any]]) -> str:
        key_title_parts = (
            "бренд",
            "марка",
            "тип",
            "материал",
            "цвет",
            "назначение",
            "влагостойкость",
            "страна",
            "производитель",
            "форма",
            "покрытие",
            "класс",
            "сорт",
        )
        key_slugs = {
            "brand",
            "brend",
            "marka",
            "tip",
            "material",
            "cvet",
            "tsvet",
            "naznachenie",
            "vlagostoykost",
            "strana",
            "strana_proizvoditel",
            "proizvoditel",
        }
        dimension_title_parts = ("размер", "габарит", "длина", "ширина", "высота", "толщина")

        sentences: List[str] = []
        clean_name = re.sub(r"\s+", " ", name or "").strip(" .")
        if clean_name:
            sentences.append(clean_name + ".")

        seen_titles = set()
        for prop in properties or []:
            raw_title = str(prop.get("title") or prop.get("slug") or "").strip()
            title = raw_title.lower()
            slug = str(prop.get("slug") or "").strip().lower()
            values = ", ".join(self._property_values(prop))
            if not raw_title or not values:
                continue
            if slug in key_slugs or any(part in title for part in key_title_parts):
                display_title = raw_title[:1].upper() + raw_title[1:]
                key = display_title.lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    sentences.append(f"{display_title}: {values}.")

        dimensions = self._extract_dimensions(name, properties)
        if dimensions and not any(any(part in sentence.lower() for part in dimension_title_parts) for sentence in sentences[1:]):
            sentences.append(f"Размеры: {dimensions}.")

        return " ".join(sentences) if sentences else ""

    def _split_words(self, text: str) -> List[str]:
        return [w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text or "") if len(w) > 1]

    def _make_keywords(self, name: str, properties: List[Dict[str, Any]], levels: Dict[str, str]) -> str:
        values: List[str] = []
        for prop in properties or []:
            values.extend(self._property_values(prop))
        values.extend(self._split_words(name))
        values.extend(v for v in levels.values() if v)

        seen = set()
        result: List[str] = []
        for value in values:
            normalized = str(value).strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return ", ".join(result)

    def _make_aliases(self, name: str) -> str:
        aliases: List[str] = []
        clean = re.sub(r"\([^)]*\)", " ", name or "")
        clean = re.sub(r"\b\d+(?:[\.,]\d+)?\s*(?:мм|см|м|кг|г|л|м2|м3|шт|упак)\b", " ", clean, flags=re.I)
        clean = re.sub(r"\s+", " ", clean).strip(" ,;-")
        if clean and clean != name:
            aliases.append(clean)

        words = clean.split()
        if len(words) >= 3:
            aliases.append(" ".join(words[:3]))
        elif clean:
            aliases.append(clean)

        # Уникальные алиасы без повтора полного названия.
        result: List[str] = []
        seen = {name.strip().lower()} if name else set()
        for alias in aliases:
            key = alias.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(alias.strip())
        return ", ".join(result)

    def _as_csv_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    def process_product(self, product: Dict[str, Any], fallback_category: Optional[Dict[str, Any]]) -> Dict[str, str]:
        properties = product.get("properties") or []
        if not isinstance(properties, list):
            properties = []

        code = str(product.get("code") or product.get("vendor_code") or product.get("article") or "").strip()
        detail_product = self.fetch_product_detail(code)
        has_detail = bool(detail_product)
        if has_detail:
            merged_product = dict(product)
            merged_product.update(detail_product)
            product = merged_product
            properties = product.get("properties") or properties
            if not isinstance(properties, list):
                properties = []

        title = str(product.get("title") or "").strip()
        levels = self._extract_levels(product, fallback_category)
        generated_description = self._make_description(title, properties)

        subcategory = " > ".join(
            levels.get(f"level{i}", "") for i in range(2, 7) if levels.get(f"level{i}", "")
        )

        return {
            "Код": code,
            "Название": title,
            "Ед. изм.": str(product.get("unit_title") or ""),
            "Цена": self._extract_price(product),
            "Валюта": "₽",
            "Категория": levels.get("level1", ""),
            "Подкатегория": subcategory,
            "Поставщик": self._extract_supplier(product) if has_detail else DEFAULT_SUPPLIER,
            "Синонимы": self._as_csv_text(product.get("aliases")) or self._make_aliases(title),
            "Ключевые слова": self._as_csv_text(product.get("keywords")) or self._make_keywords(title, properties, levels),
            "Описание": self._extract_detail_description(product, generated_description),
            "Ссылка на изображение": self._extract_image(product),
        }

    # ---------- Парсинг ----------

    def _log_category_progress(self, prefix: str, category: Dict[str, Any], collected_count: int) -> None:
        self.log(
            f"{prefix}: {category.get('name', '')} "
            f"(товаров: {category.get('product_qty', '?')}) — собрано {collected_count}"
        )

    def parse_category_products(
        self,
        category: Dict[str, Any],
        max_products_per_cat: Optional[int] = None,
        category_index: Optional[int] = None,
        category_total: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        code = category["code"]
        prefix = (
            f"Категория {category_index}/{category_total}"
            if category_index is not None and category_total is not None
            else "Категория"
        )
        self._log_category_progress(prefix, category, 0)

        first_data = self.fetch_json(self.build_products_url(code, 0), retry=3)
        if not first_data or first_data.get("data") is None:
            self.log(f"[WARN] Нет данных по категории {code}")
            self._log_category_progress(prefix, category, 0)
            return []

        data = first_data.get("data") or {}
        total = int(data.get("total") or 0)
        raw_first = data.get("products") or []
        if not isinstance(raw_first, list):
            raw_first = []

        first_batch = raw_first[:max_products_per_cat] if max_products_per_cat else raw_first
        collected = [self.process_product(product, category) for product in first_batch]
        self.log(f"    найдено на первой странице: {len(raw_first)}, total={total}")

        if max_products_per_cat and len(collected) >= max_products_per_cat:
            result = collected[:max_products_per_cat]
            self._log_category_progress(prefix, category, len(result))
            return result
        if len(raw_first) < PAGE_LIMIT:
            result = collected[:max_products_per_cat] if max_products_per_cat else collected
            self._log_category_progress(prefix, category, len(result))
            return result

        def fetch_page(offset: int) -> Tuple[int, List[Dict[str, Any]]]:
            page_data = self.fetch_json(self.build_products_url(code, offset), retry=3)
            if not page_data or page_data.get("data") is None:
                return offset, []
            products = page_data.get("data", {}).get("products") or []
            return offset, products if isinstance(products, list) else []

        if total <= 0 and max_products_per_cat is None:
            offset = PAGE_LIMIT
            while True:
                offset, raw_products = fetch_page(offset)
                if not raw_products:
                    self.log(f"    offset={offset}: пусто/конец")
                    break
                if max_products_per_cat:
                    remaining = max_products_per_cat - len(collected)
                    raw_products = raw_products[:remaining]
                collected.extend(self.process_product(product, category) for product in raw_products)
                self.log(f"    offset={offset}: +{len(raw_products)} (всего {len(collected)})")
                if max_products_per_cat and len(collected) >= max_products_per_cat:
                    break
                if len(raw_products) < PAGE_LIMIT:
                    break
                offset += PAGE_LIMIT
            self._log_category_progress(prefix, category, len(collected))
            return collected

        target_total = total if total > 0 else max_products_per_cat or len(collected)
        if max_products_per_cat:
            target_total = min(target_total, max_products_per_cat)
        offsets = list(range(PAGE_LIMIT, target_total, PAGE_LIMIT))

        with ThreadPoolExecutor(max_workers=MAX_PAGE_WORKERS) as executor:
            futures = [executor.submit(fetch_page, offset) for offset in offsets]
            for future in as_completed(futures):
                offset, raw_products = future.result()
                if not raw_products:
                    self.log(f"    offset={offset}: пусто/ошибка")
                    continue
                if max_products_per_cat:
                    remaining = max_products_per_cat - len(collected)
                    raw_products = raw_products[:remaining]
                collected.extend(self.process_product(product, category) for product in raw_products)
                self.log(f"    offset={offset}: +{len(raw_products)} (всего {len(collected)})")
                if max_products_per_cat and len(collected) >= max_products_per_cat:
                    break

        result = collected[:max_products_per_cat] if max_products_per_cat else collected
        self._log_category_progress(prefix, category, len(result))
        return result

    def run(
        self,
        selected_category_codes: Optional[List[str]] = None,
        max_products_per_cat: Optional[int] = None,
        resume_from: int = 0,
    ) -> List[Dict[str, str]]:
        if selected_category_codes:
            known = {cat["code"]: cat for cat in self.categories}
            categories = [
                known.get(str(code), {"code": str(code), "name": str(code), "parent": "", "category_path": [str(code)]})
                for code in selected_category_codes
            ]
            start_index = 1
            if resume_from:
                self.log("[WARN] --resume-from игнорируется при явном --categories")
        else:
            skipped = max(0, resume_from)
            categories = self.categories[skipped:]
            start_index = skipped + 1
            if skipped:
                self.log(f"[RESUME] Пропущено категорий: {skipped}; старт с категории {start_index}")

        if not categories:
            self.log("[WARN] Список категорий пуст")
            return []

        self.log(
            f"[START] Категорий к обработке: {len(categories)} из {len(self.categories)}, "
            f"стартовый номер: {start_index}, воркеров категорий: {MAX_CATEGORY_WORKERS}, "
            f"воркеров страниц: {MAX_PAGE_WORKERS}"
        )

        all_items: List[Dict[str, str]] = []
        category_total = len(self.categories) if not selected_category_codes else len(categories)
        with ThreadPoolExecutor(max_workers=MAX_CATEGORY_WORKERS) as executor:
            futures = [
                executor.submit(self.parse_category_products, category, max_products_per_cat, index, category_total)
                for index, category in enumerate(categories, start=start_index)
            ]
            for future in as_completed(futures):
                try:
                    all_items.extend(future.result())
                except Exception as exc:
                    self.log(f"[ERR] Ошибка обработки категории: {exc}")

        return self.deduplicate_and_sort(all_items)

    def deduplicate_and_sort(self, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        unique: List[Dict[str, str]] = []
        seen_codes = set()
        for item in items:
            code = str(item.get("Код") or "").strip()
            if code and code in seen_codes:
                continue
            if code:
                seen_codes.add(code)
            unique.append(item)

        unique.sort(
            key=lambda item: (
                str(item.get("Категория", "")).lower(),
                str(item.get("Подкатегория", "")).lower(),
                str(item.get("Название", "")).lower(),
            )
        )
        self.log(f"[DEDUP] Было: {len(items)}, уникальных: {len(unique)}")
        return unique

    def save_csv(
        self,
        items: List[Dict[str, str]],
        output_name: Optional[str] = None,
        append: bool = False,
    ) -> Path:
        if output_name:
            output_path = Path(output_name)
            if not output_path.is_absolute():
                output_path = self.project_root / output_path
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.project_root / f"directory_materials_enriched_{timestamp}.csv"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        append_to_existing = append and output_path.exists() and output_path.stat().st_size > 0
        mode = "a" if append_to_existing else "w"
        with output_path.open(mode, newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS, extrasaction="ignore", quoting=csv.QUOTE_ALL)
            if not append_to_existing:
                writer.writeheader()
            writer.writerows(items)

        action = "дополнен" if append_to_existing else "сохранён"
        self.log(f"[OK] CSV {action}: {output_path} (новых строк: {len(items)})")
        return output_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Парсер материалов каталога Петрович в CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--categories", nargs="*", help="Список ID категорий через пробел")
    parser.add_argument("--max-products-per-cat", type=int, default=None, help="Лимит товаров на категорию")
    parser.add_argument("--resume-from", type=int, default=0, metavar="N", help="Пропустить первые N категорий и начать с N+1")
    parser.add_argument("--output", default=None, help="Имя выходного CSV-файла")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    parser = PetrovichMaterialParser(PROJECT_ROOT)
    items = parser.run(args.categories, args.max_products_per_cat, args.resume_from)
    parser.save_csv(items, args.output, append=args.resume_from > 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
