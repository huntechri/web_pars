#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Скрипт для генерации полного дерева категорий Петрович
Сохраняет в JSON файл все уровни вложенности для быстрой загрузки в GUI
"""

import json
from full_auto_parser_CURL import CurlParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

def fetch_child_recursive(parser, child_code, level, max_level):
    """Параллельная обработка дочерней категории"""
    return fetch_full_category_tree(parser, child_code, level, max_level)

def fetch_full_category_tree(parser, category_id, level=1, max_level=3):
    """Рекурсивно получить полное дерево категории С ПАРАЛЛЕЛИЗМОМ"""
    
    # Получаем структуру категории
    structure = parser.get_category_structure(category_id)
    if not structure:
        return None
    
    # Базовая информация
    result = {
        'code': structure.get('code'),
        'title': structure.get('title'),
        'product_qty': structure.get('product_qty', 0),
        'children': []
    }
    
    # Если есть дети и не достигли максимального уровня
    children = structure.get('children', [])
    if children and level < max_level:
        # ПАРАЛЛЕЛЬНАЯ загрузка детей (ускорение!)
        if len(children) > 3:  # Если детей много - параллелим
            with ThreadPoolExecutor(max_workers=10) as executor:
                child_codes = [c.get('code') for c in children if c.get('code')]
                futures = [executor.submit(fetch_child_recursive, parser, code, level + 1, max_level) for code in child_codes]
                
                for future in as_completed(futures):
                    full_child = future.result()
                    if full_child:
                        result['children'].append(full_child)
        else:
            # Если детей мало - последовательно
            for child in children:
                child_code = child.get('code')
                if child_code:
                    full_child = fetch_full_category_tree(parser, child_code, level + 1, max_level)
                    if full_child:
                        result['children'].append(full_child)
    elif children:
        # Последний уровень - добавляем как есть
        for child in children:
            result['children'].append({
                'code': child.get('code'),
                'title': child.get('title'),
                'product_qty': child.get('product_qty', 0),
                'children': []
            })
    
    # --- СОРТИРОВКА ДЕТЕЙ ПО АЛФАВИТУ ---
    if result['children']:
        result['children'].sort(key=lambda x: str(x.get('title', '')).lower())
    
    return result

def fetch_category_wrapper(args):
    """Обертка для параллельной загрузки"""
    parser, cat, idx, total = args
    print(f"\n[{idx}/{total}] {cat['name']} (ID: {cat['code']})")
    
    try:
        full_cat = fetch_full_category_tree(parser, cat['code'], level=1, max_level=3)
        if full_cat:
            print(f"[OK] Gotovo: {cat['name']}")
            return full_cat
    except Exception as e:
        print(f"[ERROR] {cat['name']}: {e}")
    
    return None

def build_full_tree():
    """Построить полное дерево всех категорий С ПАРАЛЛЕЛЬНОЙ ЗАГРУЗКОЙ"""
    print("="*70)
    print("POSTROYENIYE DEREVA KATEGORIY (PARALLEL)")
    print("="*70)
    
    parser = CurlParser()
    
    # Получаем все категории из конфига
    categories_by_parent = {}
    for cat in parser.categories:
        parent = cat.get('parent', 'OTHER')
        if parent not in categories_by_parent:
            categories_by_parent[parent] = []
        categories_by_parent[parent].append(cat)
    
    # Строим полное дерево
    full_tree = {}
    total_cats = sum(len(cats) for cats in categories_by_parent.values())
    
    print(f"\nVsego kategoriy: {total_cats}")
    print("TURBO MODE: 20 parallelnyh potokov!\n")
    
    start_time = time.time()
    
    for parent_name, cats in sorted(categories_by_parent.items()):
        print(f"\n{'='*70}")
        print(f"GRUPPA: {parent_name} ({len(cats)} kategoriy)")
        print(f"{'='*70}")
        
        full_tree[parent_name] = []
        
        # Сортируем входные категории группы
        sorted_cats = sorted(cats, key=lambda x: str(x.get('name', '')).lower())
        
        # Подготовка аргументов для параллельной загрузки
        tasks = []
        for idx, cat in enumerate(sorted_cats, 1):
            tasks.append((parser, cat, idx, len(cats)))
        
        # Параллельная загрузка (до 20 одновременно - ТУРБО!)
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(fetch_category_wrapper, task) for task in tasks]
            
            for future in as_completed(futures):
                result = future.result()
                if result:
                    full_tree[parent_name].append(result)
        
        # Финальная сортировка результатов в группе
        full_tree[parent_name].sort(key=lambda x: str(x.get('title', '')).lower())
    
    elapsed = time.time() - start_time
    
    # Сохраняем в JSON
    output_file = 'categories_full_tree.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(full_tree, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*70}")
    print(f"DEREVO SOHRANENO V: {output_file}")
    print(f"Vremya: {int(elapsed // 60)} min {int(elapsed % 60)} sec")
    print(f"{'='*70}")
    print("\nTeper GUI budet zagruzhatsya mgnovenno!")
    print("API budet ispolzovatsya TOLKO dlya parsinga tovarov.")

if __name__ == '__main__':
    build_full_tree()
