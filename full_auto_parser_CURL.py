#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import json
import csv
import sys
import time
import re
import io
import os
import shutil
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    def __init__(self, log_callback=None, progress_callback=None):
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.base_url = "https://api.petrovich.ru/catalog/v5/sections"
        self.stop_requested = False
        
        # Загрузка настроек
        self.cookies_raw, self.headers_from_cook = self.load_cookies_and_headers()
        
        self.user_agent = self.headers_from_cook.get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')
        
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

    def load_cookies_and_headers(self):
        try:
            ensure_config_exists('Cook')
            namespace = {}
            with open('Cook', 'r', encoding='utf-8') as f:
                exec(f.read(), namespace)
            return namespace.get('cookies', {}), namespace.get('headers', {})
        except Exception as e:
            self.log(f"ОШИБКА чтения файла Cook: {e}")
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
            '-H', f'Cookie: {self.cookie_string}',
            '-H', f'User-Agent: {self.user_agent}',
            url
        ]
        
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
        page_products = first_data.get('data', {}).get('products', [])
        
        self.log(f"    [INFO] Total products: {total_count}")
        all_products.extend(self._process_raw_list(page_products, category_path))
        
        if total_count <= limit or (max_products and len(all_products) >= max_products):
            return all_products

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
                    raw_list = p_data.get('data', {}).get('products', [])
                    all_products.extend(self._process_raw_list(raw_list, category_path))
                
                if done % 5 == 0 or done == total_pages:
                    self.log(f"    - Progress: {done}/{total_pages} pages")

        return all_products[:max_products] if max_products else all_products

    def _process_raw_list(self, raw_list, category_path):
        processed = []
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
        if not items: return
        
        full_header_map = {
            'level1': 'category1', 'level2': 'category2', 'level3': 'category3', 'level4': 'category4',
            'article': 'sku', 'name': 'name', 'price': 'price', 'unit': 'unit',
            'brand': 'supplers', 'weight': 'weight', 'supplier': 'supplier', 'image': 'image', 'url': 'product_url'
        }
        
        fieldnames = []
        header_row = {}
        for i, ck in enumerate(selected_columns):
            if ck in full_header_map:
                fieldnames.append(ck)
                header_row[ck] = full_header_map[ck]
            else:
                dk = f"__empty_{i}__"
                fieldnames.append(dk); header_row[dk] = ""
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', extrasaction='ignore')
            writer.writerow(header_row)
            writer.writerows(items)
        self.log(f"ГОТОВО: Сохранено в {filename}")

    def run(self, selected_categories=None, max_products_per_cat=None, selected_columns=None, use_deep_parsing=True, parallel=True):
        cats_to_parse = selected_categories if selected_categories else [c['code'] for c in self.categories]
        
        self.log(f"\n{'='*70}")
        self.log(f"ZAPUSK TURBO-PARSINGA PETROVICH")
        self.log(f"{'='*70}")
        self.log(f"Kategoriy: {len(cats_to_parse)}")
        self.log(f"Metod: Parallel Pages (8 threads per cat + 5 threads global)")
        self.log(f"{'='*70}\n")
        
        all_results = []
        
        def process_one_cat(cat_id):
            try:
                struct = self.get_category_structure(cat_id)
                if not struct: return []
                name = struct.get('title', 'Unknown')
                self.log(f"\n[#] CATEGORY: {name} (ID: {cat_id})")
                
                if struct.get('product_qty', 0) > 0:
                    return self.parse_category_products(cat_id, [name], max_products_per_cat)
            except Exception as e:
                self.log(f"Error cat {cat_id}: {e}")
            return []

        # Глобальный параллелизм по категориям
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_one_cat, cid) for cid in cats_to_parse]
            completed = 0
            for future in as_completed(futures):
                if self.stop_requested:
                    self.log("\n[STOP] Parsing interrupted by user.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                all_results.extend(future.result())
                completed += 1
                if self.progress_callback: self.progress_callback(completed / len(cats_to_parse))
        
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
    p = CurlParser()
    p.run(selected_columns=['article', 'name', 'price'])
