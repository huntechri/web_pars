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
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


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
    def __init__(self, log_callback=None, progress_callback=None, cookies_raw=None, headers_raw=None):
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.base_url = "https://api.petrovich.ru/catalog/v5/sections"
        self.stop_requested = False
        
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
        
        # Подготовка сессии requests (для ТУРБО режима)
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        for k, v in self.cookies_raw.items():
            self.session.cookies.set(k, v)
        
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
            except Exception:
                pass
            time.sleep(1)
        
        # 2. Если упало - пробуем старый добрый curl.exe
        startupinfo = None
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW

        cmd = [
            'curl.exe', '--noproxy', '*', '-s', '-L',
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
        except:
            pass
            
        return None

    def get_category_structure(self, section_id):
        url = f"{self.base_url}/{section_id}?city_code=msk&client_id=pet_site"
        data = self.fetch_api(url)
        if data and 'data' in data:
            return data['data'].get('section', {})
        return None

    def parse_category_products(self, section_code, category_path, max_products=None):
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
        all_products.extend(self._process_raw_list(page_products, category_path))
        
        if total_count <= limit or (max_products and len(all_products) >= max_products):
            return all_products[:max_products] if max_products else all_products

        # Шаг 2: Вычисляем оставшиеся страницы
        target_total = total_count
        if max_products: target_total = min(total_count, max_products)
        
        offsets = range(limit, target_total, limit)
        total_pages = len(offsets) + 1
        
        self.log(f"    [TURBO] Fetching {len(offsets)} pages in parallel...")
        
        # Шаг 3: Параллельная загрузка страниц (8 потоков оптимально)
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for off in offsets:
                url = f"{self.base_url}/{section_code}/products?limit={limit}&offset={off}&sort=popularity_desc&city_code=msk&client_id=pet_site"
                futures.append(executor.submit(self.fetch_api, url))
            
            done = 1
            for future in as_completed(futures):
                if self.stop_requested: 
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                p_data = future.result()
                done += 1
                if p_data:
                    raw_list = p_data.get('data', {}).get('products', []) or []
                    all_products.extend(self._process_raw_list(raw_list, category_path))
                
                if done % 5 == 0 or done == total_pages:
                    self.log(f"    - Progress: {done}/{total_pages} pages")

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

    def run(self, selected_categories=None, max_products_per_cat=None, selected_columns=None, use_deep_parsing=True, parallel=True):
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
        self.log(f"Metod: Parallel Pages (8 threads per cat + 5 threads global)")
        self.log(f"{'='*70}\n")
        
        all_results = []
        products_collected = 0
        
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
                return self.parse_category_products(cat_id, cat_path, max_products_per_cat)
            except Exception as e:
                self.log(f"Error cat {cat_id}: {e}")
            return []

        # Глобальный параллелизм по категориям
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_one_cat, cinfo) for cinfo in cats_to_parse]
            completed = 0
            for future in as_completed(futures):
                if self.stop_requested:
                    self.log("\n[STOP] Parsing interrupted by user.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                category_items = future.result()
                all_results.extend(category_items)
                products_collected += len(category_items)
                completed += 1
                if self.progress_callback:
                    self.progress_callback(
                        {
                            'progress_percent': completed / len(cats_to_parse),
                            'categories_done': completed,
                            'categories_total': len(cats_to_parse),
                            'products_collected': products_collected,
                        }
                    )
        
        # --- ФИНАЛЬНАЯ ДЕДУПЛИКАЦИЯ ПО АРТИКУЛУ ---
        total_before = len(all_results)
        unique_results = []
        seen_articles = set()
        
        for item in all_results:
            art = item.get('article')
            if art not in seen_articles:
                unique_results.append(item)
                seen_articles.add(art)
        
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
