#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import json
import csv
import argparse
import sys
import time
import re
import io
import os
import ast
import shutil
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from curl_cffi.requests import Session as CffiSession
    _CFFI_AVAILABLE = True
except ImportError:
    import requests
    _CFFI_AVAILABLE = False


DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def ensure_config_exists(filename):
    """ Ensure config file exists in CWD, copy from bundle if needed """
    if not os.path.exists(filename):
        bundled_path = resource_path(filename)
        if os.path.exists(bundled_path) and bundled_path != os.path.abspath(filename):
            try:
                shutil.copy2(bundled_path, filename)
                return True
            except Exception:
                pass
    return os.path.exists(filename)

class CurlParser:
    def __init__(
        self,
        log_callback=None,
        progress_callback=None,
        cookies_raw=None,
        headers_raw=None,
        max_category_workers=3,
        retry_base_delay_seconds=0.35,
        rate_limit_wait_cap_seconds=15,
    ):
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.base_url = "https://api.petrovich.ru/catalog/v5/sections"
        self.stop_requested = False
        self.max_category_workers = max(1, int(max_category_workers or 1))
        self.retry_base_delay_seconds = max(0.1, float(retry_base_delay_seconds or 0.35))
        self.rate_limit_wait_cap_seconds = max(1, int(rate_limit_wait_cap_seconds or 15))
        
        # Загрузка настроек
        self.cookies_raw, self.headers_from_cook = self.load_cookies_and_headers(
            cookies_raw=cookies_raw,
            headers_raw=headers_raw,
        )
        
        self.user_agent = self.headers_from_cook.get('User-Agent', DEFAULT_USER_AGENT)
        
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
            'Origin': 'https://moscow.petrovich.ru',
            'Referer': 'https://moscow.petrovich.ru/catalog/',
            'User-Agent': self.user_agent,
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }
        self.headers.update(self.headers_from_cook)
        if 'User-Agent' not in self.headers:
            self.headers['User-Agent'] = self.user_agent
        
        # Подготовка сессии (curl_cffi имитирует Chrome TLS, иначе fallback на requests)
        if _CFFI_AVAILABLE:
            self.session = CffiSession(impersonate='chrome131')
            self.session.headers.update(self.headers)
            for k, v in self.cookies_raw.items():
                self.session.cookies.set(k, v)
            self.log("INFO: Using curl_cffi (Chrome TLS impersonation)")
        else:
            import requests as _requests
            self.session = _requests.Session()
            self.session.headers.update(self.headers)
            for k, v in self.cookies_raw.items():
                self.session.cookies.set(k, v)
            self.log("WARN: curl_cffi not available, using requests (may hit 403)")

        self.categories = self.load_categories()
        self.cookie_string = '; '.join([f"{k}={v}" for k, v in self.cookies_raw.items()])

        self.log(f"DONE: Loaded {len(self.cookies_raw)} cookies")
        self.log(f"DONE: Loaded {len(self.categories)} categories")
        self.log(f"INFO: TURBO MODE (Parallel Pagination + Requests Session) ENABLED\n")

    def log(self, message, end='\n'):
        if self.log_callback:
            self.log_callback(f"{message}{end}")
        else:
            print(message, end=end, flush=True)

    def _normalize_headers_or_cookies(self, data):
        if isinstance(data, str):
            raw = data.strip()
            if not raw:
                return {}
            try:
                data = json.loads(raw)
            except Exception:
                try:
                    data = ast.literal_eval(raw)
                except Exception:
                    return {}

        if not isinstance(data, dict):
            return {}
        normalized = {}
        for k, v in data.items():
            if k is None or v is None:
                continue
            normalized[str(k)] = str(v)
        return normalized

    def _load_json_env_dict(self, env_name):
        raw = os.getenv(env_name, '').strip()
        if not raw:
            return {}
        parsed = self._normalize_headers_or_cookies(raw)
        if parsed:
            return parsed
        self.log(f"WARN: failed to parse {env_name}; expected JSON object or Python dict literal")
        return {}

    def load_cookies_and_headers(self, cookies_raw=None, headers_raw=None):
        # 1) Явно переданные значения (из backend settings)
        normalized_cookies = self._normalize_headers_or_cookies(cookies_raw)
        normalized_headers = self._normalize_headers_or_cookies(headers_raw)
        if normalized_cookies or normalized_headers:
            return normalized_cookies, normalized_headers

        # 2) ENV-переменные
        env_cookies = self._load_json_env_dict('APP_PARSER_COOKIES')
        env_headers = self._load_json_env_dict('APP_PARSER_HEADERS')
        if env_cookies or env_headers:
            return env_cookies, env_headers

        # 3) Fallback на Cook для обратной совместимости
        try:
            ensure_config_exists('Cook')
            namespace = {}
            with open('Cook', 'r', encoding='utf-8') as f:
                exec(f.read(), namespace)
            return (
                self._normalize_headers_or_cookies(namespace.get('cookies', {})),
                self._normalize_headers_or_cookies(namespace.get('headers', {})),
            )
        except Exception as e:
            self.log(f"WARN: unable to load cookies/headers from Cook: {e}")
            return {}, {}

    def load_categories(self):
        categories = []
        current_parent = "Прочее"
        try:
            ensure_config_exists('categories_config.txt')
            with open('categories_config.txt', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('#'):
                        clean = line.replace('#', '').strip()
                        match = re.search(r'([А-ЯЁ\s]{3,})', clean)
                        if match:
                            potential_parent = match.group(1).strip()
                            if len(potential_parent) > 2: current_parent = potential_parent
                        continue
                    if '=' in line:
                        code, name = line.split('=', 1)
                        if code.strip().isdigit():
                            categories.append({
                                'code': code.strip(), 
                                'name': name.strip(),
                                'parent': current_parent
                            })
        except Exception as e:
            self.log(f"ERROR reading categories_config: {e}")
        return categories

    def fetch_api(self, url, retry=3):
        """Умный метод: сначала пробует быстрый requests, потом надежный curl"""
        if self.stop_requested: return None
        # 1. Пробуем через requests (уже с сессией и куками)
        for attempt in range(retry):
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
                # Логируем статус, чтобы понять причину сбоя
                self.log(f"      [HTTP] status={resp.status_code} attempt={attempt+1}/{retry} url={url[:80]}")
                if resp.status_code == 429:
                    # Уважаем Retry-After от сервера (или ждём 10 с по умолчанию)
                    retry_after = int(resp.headers.get('Retry-After', 10))
                    retry_after = min(retry_after, self.rate_limit_wait_cap_seconds)
                    self.log(f"      [RATE LIMIT] Waiting {retry_after}s before retry...")
                    time.sleep(retry_after)
                    continue
                if resp.status_code in (403, 401):
                    self.log(f"      [AUTH] Cookies/session may be expired (status={resp.status_code})")
                    # Нет смысла крутить повторные запросы при невалидной сессии.
                    break
            except Exception as exc:
                self.log(f"      [ERR] requests exception attempt={attempt+1}/{retry}: {exc}")
            if attempt + 1 < retry:
                time.sleep(self.retry_base_delay_seconds * (attempt + 1))
        
        # 2. Если упало - пробуем старый добрый curl.exe
        startupinfo = None
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW

        curl_bin = 'curl.exe' if sys.platform == 'win32' else 'curl'
        cmd = [
            curl_bin, '--noproxy', '*', '-s', '-L',
            '--connect-timeout', '15',
        ]

        if self.cookie_string:
            cmd.extend(['-H', f'Cookie: {self.cookie_string}'])

        for hk, hv in self.headers.items():
            if str(hk).lower() == 'cookie':
                continue
            cmd.extend(['-H', f'{hk}: {hv}'])

        cmd.append(url)
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=creationflags)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            if result.returncode != 0:
                self.log(f"      [CURL ERR] returncode={result.returncode} stderr={result.stderr.strip()[:120]}")
            elif result.stdout.strip():
                # curl вернул 0, но JSON невалидный — логируем начало ответа
                self.log(f"      [CURL JSON ERR] response_start={result.stdout.strip()[:120]}")
        except Exception as exc:
            self.log(f"      [CURL EXC] {exc}")
            
        return None

    def get_category_structure(self, section_id):
        url = f"{self.base_url}/{section_id}?city_code=msk&client_id=pet_site"
        data = self.fetch_api(url)
        if data and 'data' in data:
            return data['data'].get('section', {})
        return None

    def parse_category_products(self, section_code, category_path, max_products=None, progress_hook=None):
        """Парсинг товаров из конкретной категории с ПАРАЛЛЕЛЬНОЙ ПАГИНАЦИЕЙ"""
        all_products = []
        limit = 50
        
        # Шаг 1: Первая страница (узнаем общее количество)
        first_url = f"{self.base_url}/{section_code}/products?limit={limit}&offset=0&sort=popularity_desc&city_code=msk&client_id=pet_site"
        first_data = self.fetch_api(first_url)
        
        if not first_data or not first_data.get('data'):
            self.log(f"    [!] No data found for {section_code}")
            return []
            
        total_count = first_data.get('data', {}).get('total', 0)
        page_products = first_data.get('data', {}).get('products', []) or []
        
        self.log(f"    [INFO] Total products: {total_count}")
        first_processed = self._process_raw_list(page_products, category_path)
        all_products.extend(first_processed)
        if progress_hook and first_processed:
            progress_hook(len(first_processed))
        
        if max_products and len(all_products) >= max_products:
            return all_products[:max_products] if max_products else all_products

        # В некоторых разделах API отдает некорректный `total` (например 0),
        # поэтому ориентируемся на фактический размер первой страницы.
        # Если первая страница неполная (< limit), значит дальше страниц нет.
        if len(page_products) < limit:
            return all_products[:max_products] if max_products else all_products

        # Шаг 2: Надежная последовательная пагинация.
        # Важно: не доверяем total безусловно, т.к. API иногда возвращает заниженное значение.
        self.log("    [SAFE] Fetching next pages until empty page...")

        off = limit
        page_idx = 2
        max_pages_guard = 1000
        failed_offsets = []

        while page_idx <= max_pages_guard:
            if self.stop_requested:
                break
            if max_products and len(all_products) >= max_products:
                break

            url = f"{self.base_url}/{section_code}/products?limit={limit}&offset={off}&sort=popularity_desc&city_code=msk&client_id=pet_site"
            p_data = None
            for attempt in range(1, 6):
                p_data = self.fetch_api(url, retry=1)
                if p_data and p_data.get('data') is not None:
                    break
                time.sleep(min(3.0, 0.5 * attempt))

            if not p_data or p_data.get('data') is None:
                self.log(f"    [WARN] Page fetch failed: offset={off} (все 5 попыток исчерпаны)")
                failed_offsets.append(off)
                # В первом проходе не обрываем весь парсинг из-за одной проблемной страницы.
                off += limit
                page_idx += 1
                continue

            raw_list = p_data.get('data', {}).get('products', []) or []
            if not raw_list:
                self.log(f"    [INFO] Reached last page at offset={off}")
                break

            processed = self._process_raw_list(raw_list, category_path)
            all_products.extend(processed)
            if progress_hook and processed:
                progress_hook(len(processed))

            if page_idx % 5 == 0:
                self.log(f"    - Progress: page={page_idx}, collected={len(all_products)}")

            # Страница неполная — это хвост, дальше данных нет. Не тратим запрос на пустую страницу.
            if len(raw_list) < limit:
                self.log(f"    [INFO] Partial page ({len(raw_list)}/{limit}) at offset={off} — pagination complete")
                break

            # Если API заявил total и мы его уже перекрыли — тоже стоп.
            if total_count > 0 and len(all_products) >= total_count:
                self.log(f"    [INFO] Collected {len(all_products)}/{total_count} — reached total, stopping")
                break

            off += limit
            page_idx += 1

        # Шаг 3: Добор упавших страниц с усиленными ретраями.
        if failed_offsets and not self.stop_requested:
            self.log(f"    [RETRY] Re-fetching failed pages: {len(failed_offsets)}")
            unrecovered_offsets = []
            for failed_off in sorted(set(failed_offsets)):
                if self.stop_requested:
                    break
                if max_products and len(all_products) >= max_products:
                    break

                retry_url = f"{self.base_url}/{section_code}/products?limit={limit}&offset={failed_off}&sort=popularity_desc&city_code=msk&client_id=pet_site"
                retry_data = self.fetch_api(retry_url, retry=8)
                if not retry_data or retry_data.get('data') is None:
                    unrecovered_offsets.append(failed_off)
                    continue

                retry_raw = retry_data.get('data', {}).get('products', []) or []
                if retry_raw:
                    processed = self._process_raw_list(retry_raw, category_path)
                    all_products.extend(processed)
                    if progress_hook and processed:
                        progress_hook(len(processed))

            if unrecovered_offsets:
                preview = ", ".join(str(x) for x in unrecovered_offsets[:10])
                if len(unrecovered_offsets) > 10:
                    preview += ", ..."
                raise RuntimeError(f"Failed to fetch category pages (offsets): {preview}")

        return all_products[:max_products] if max_products else all_products

    def _process_raw_list(self, raw_list, category_path):
        processed = []
        if not raw_list:
            return processed
        for p in raw_list:
            try:
                props = p.get('properties', [])
                prices = p.get('price', {})
                price_val = prices.get('retail') or prices.get('gold') or 0
                
                # Парсинг веса в число с точкой
                weight_raw = self._get_prop(props, 'ves')
                weight_val = ""
                if weight_raw:
                    # Извлекаем число (может быть "10 кг" или "0.5")
                    match = re.search(r"(\d+[\.,]\d+)|\d+", weight_raw.replace(' ', ''))
                    if match:
                        weight_val = match.group().replace(',', '.')
                
                images = p.get('images', [])
                img_url = ''
                if images and isinstance(images, list) and len(images) > 0:
                    first = images[0]
                    img_url = first.get('url', '') if isinstance(first, dict) else str(first)
                    if img_url.startswith('//'): img_url = 'https:' + img_url
                
                item = {
                    'article': p.get('vendor_code', '') or p.get('code', ''),
                    'name': p.get('title', ''),
                    'price': self.format_price(price_val),
                    'unit': p.get('unit_title') or '',
                    'brand': self._get_prop(props, 'brend'),
                    'weight': weight_val,
                    'supplier': 'Петрович',
                    'image': img_url,
                    'url': f"https://moscow.petrovich.ru/product/{p.get('code', '')}/"
                }
                for i, name in enumerate(category_path[:4], 1): item[f'level{i}'] = name
                for i in range(len(category_path) + 1, 5): item[f'level{i}'] = ''
                processed.append(item)
            except: continue
        return processed

    def _get_prop(self, props, slug):
        if not props: return ''
        for pr in props:
            if pr.get('slug') == slug:
                vals = pr.get('value', [])
                if vals: 
                    return vals[0].get('title', str(vals[0])) if isinstance(vals[0], dict) else str(vals[0])
        return ''

    def format_price(self, val):
        try:
            return "{:.2f}".format(float(val))
        except: return "0.00"

    def save_to_csv(self, items, filename, selected_columns=None):
        if items is None:
            items = []
        
        full_header_map = {
            'article': 'Артикул',
            'name': 'Наименование',
            'unit': 'Единица измерения',
            'price': 'Цена',
            'brand': 'Поставщик',
            'weight': 'Вес (кг)',
            'level1': 'Категория LV1',
            'level2': 'Категория LV2',
            'level3': 'Категория LV3',
            'level4': 'Категория LV4',
            'image': 'URL изображения',
            'url': 'Ссылка на товар', # Оставляем возможность вывести ссылку, если пользователь захочет
            'supplier': 'Источник'    # Петрович
        }

        # Не ограничиваем выгрузку: всегда пишем полный набор колонок.
        fieldnames = list(full_header_map.keys())
        header_row = {k: full_header_map[k] for k in fieldnames}
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', extrasaction='ignore')
            writer.writerow(header_row)
            writer.writerows(items)
        self.log(f"ГОТОВО: Сохранено в {filename} (rows: {len(items)})")

    def run(self, selected_categories=None, max_products_per_cat=None, selected_columns=None, use_deep_parsing=True, parallel=True, return_items=False):
        # selected_categories может быть списком ID или списком объектов {'id': ..., 'path': [...]}
        input_cats = selected_categories if selected_categories else [c['code'] for c in self.categories]
        
        cats_to_parse = []
        for item in input_cats:
            if isinstance(item, dict):
                cats_to_parse.append(item)
            else:
                cats_to_parse.append({'id': item, 'path': None})
        
        self.log(f"\n{'='*70}")
        self.log(f"ZAPUSK TURBO-PARSINGA PETROVICH")
        self.log(f"{'='*70}")
        self.log(f"Kategoriy: {len(cats_to_parse)}")
        self.log(f"Metod: Safe pagination + {self.max_category_workers} threads global")
        self.log(f"{'='*70}\n")
        
        all_results = []
        products_collected = 0
        completed = 0
        progress_state_lock = threading.Lock()

        def emit_progress(products_delta=0, completed_delta=0):
            nonlocal products_collected, completed
            with progress_state_lock:
                products_collected += int(products_delta)
                completed += int(completed_delta)
                if self.progress_callback:
                    self.progress_callback(
                        {
                            'progress_percent': (completed / len(cats_to_parse)) if cats_to_parse else 1,
                            'categories_done': completed,
                            'categories_total': len(cats_to_parse),
                            'products_collected': products_collected,
                        }
                    )

        emit_progress(products_delta=0, completed_delta=0)
        
        def process_one_cat(cat_info):
            cat_id = cat_info.get('id')
            cat_path = cat_info.get('path')
            
            try:
                # Если путь не передан, пытаемся узнать название категории
                if not cat_path:
                    struct = self.get_category_structure(cat_id)
                    if not struct: return []
                    name = struct.get('title', 'Unknown')
                    cat_path = [name]
                
                display_name = " -> ".join(cat_path) if cat_path else str(cat_id)
                self.log(f"\n[#] CATEGORY: {display_name} (ID: {cat_id})")
                
                # Запускаем парсинг товаров
                return self.parse_category_products(
                    cat_id,
                    cat_path,
                    max_products_per_cat,
                    progress_hook=lambda added: emit_progress(products_delta=added, completed_delta=0),
                )
            except Exception as e:
                self.log(f"Error cat {cat_id}: {e}")
            return []

        # Глобальный параллелизм по категориям.
        # На публичных облаках (Render и т.п.) меньшее число воркеров обычно даёт
        # лучшую итоговую скорость за счёт меньшего количества 429.
        with ThreadPoolExecutor(max_workers=self.max_category_workers) as executor:
            futures = [executor.submit(process_one_cat, cinfo) for cinfo in cats_to_parse]
            for future in as_completed(futures):
                if self.stop_requested:
                    self.log("\n[STOP] Parsing interrupted by user.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                category_items = future.result()
                all_results.extend(category_items)
                emit_progress(products_delta=0, completed_delta=1)
        
        # --- ФИНАЛЬНАЯ ДЕДУПЛИКАЦИЯ (БЕЗ ПОТЕРИ ВАЛИДНЫХ ПОЗИЦИЙ) ---
        total_before = len(all_results)
        unique_results = []
        seen_keys = set()
        
        for item in all_results:
            # Приоритетно используем URL (наиболее стабильный и уникальный ключ товара).
            # Фоллбэки нужны для редких кейсов, где URL/артикул отсутствуют.
            key = (
                str(item.get('url') or '').strip().lower()
                or str(item.get('article') or '').strip().lower()
                or '|'.join([
                    str(item.get('name') or '').strip().lower(),
                    str(item.get('price') or '').strip(),
                    str(item.get('unit') or '').strip().lower(),
                    str(item.get('level1') or '').strip().lower(),
                    str(item.get('level2') or '').strip().lower(),
                    str(item.get('level3') or '').strip().lower(),
                    str(item.get('level4') or '').strip().lower(),
                ])
            )

            if key not in seen_keys:
                unique_results.append(item)
                seen_keys.add(key)
        
        all_results = unique_results
        total_after = len(all_results)
        
        self.log(f"\n[DEDUPLICATION] Deleted {total_before - total_after} duplicates.")
        self.log(f"[DEDUPLICATION] Unique products kept: {total_after}")
        
        # --- ИЕРАРХИЧЕСКАЯ СОРТИРОВКА (L1 -> L2 -> L3 -> L4 -> Название) ---
        self.log("[SORTING] Ordering products by category hierarchy and name...")
        all_results.sort(key=lambda x: (
            str(x.get('level1', '')).lower(),
            str(x.get('level2', '')).lower(),
            str(x.get('level3', '')).lower(),
            str(x.get('level4', '')).lower(),
            str(x.get('name', '')).lower()
        ))
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        file = f'petrovich_turbo_{ts}.csv'
        self.save_to_csv(all_results, file, selected_columns=selected_columns)
        self.log(f"\n[OK] TOTAL COLLECTED (UNIQUE): {len(all_results)}")
        if return_items:
            return file, all_results
        return file

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CLI-парсер каталога Петрович (без GUI).')
    parser.add_argument('--categories', nargs='*', help='Список ID категорий через пробел.')
    parser.add_argument('--max-products-per-cat', type=int, default=None, help='Лимит товаров на категорию.')
    parser.add_argument(
        '--columns',
        nargs='*',
        default=['article', 'name', 'unit', 'price', 'brand', 'weight', 'level1', 'level2', 'level3', 'level4', 'image', 'url', 'supplier'],
        help='Параметр оставлен для совместимости и игнорируется (выводятся все колонки).'
    )
    args = parser.parse_args()
