#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Скрипт для поиска дублирующихся категорий
"""

import json

# Загружаем текущее дерево
with open('categories_full_tree.json', 'r', encoding='utf-8') as f:
    tree = json.load(f)

# Собираем ВСЕ ID из дерева
def collect_all_ids(node, parent_id=None):
    """Рекурсивно собирает все ID с информацией о родителях"""
    results = []
    
    node_id = node.get('code')
    if node_id:
        results.append({
            'id': node_id,
            'title': node.get('title'),
            'parent_id': parent_id,
            'is_child': parent_id is not None
        })
    
    # Рекурсивно обходим детей
    for child in node.get('children', []):
        results.extend(collect_all_ids(child, node_id))
    
    return results

# Собираем все ID
all_categories = []
for group_name, categories in tree.items():
    for cat in categories:
        all_categories.extend(collect_all_ids(cat))

# Найдем ID которые появляются и как родители и как дети
child_ids = set()
root_ids = set()

for cat in all_categories:
    if cat['is_child']:
        child_ids.add(cat['id'])
    else:
        root_ids.add(cat['id'])

# ID которые есть в обоих множествах - это дубли!
duplicate_ids = child_ids & root_ids

print(f"\n{'='*70}")
print(f"ANALIZ KATEGORIY")
print(f"{'='*70}")
print(f"Vsego kategoriy v dereve: {len(all_categories)}")
print(f"Kornevykh kategoriy (L1): {len(root_ids)}")
print(f"Dochernikh kategoriy (L2+): {len(child_ids)}")
print(f"DUBLEY (est i tam i tam): {len(duplicate_ids)}")

if duplicate_ids:
    print(f"\n{'='*70}")
    print(f"SPISOK DUBLEY:")
    print(f"{'='*70}")
    
    for cat in all_categories:
        if cat['id'] in duplicate_ids and not cat['is_child']:
            print(f"{cat['id']}: {cat['title']}")

# Сохраняем список дублей
with open('duplicate_ids.txt', 'w', encoding='utf-8') as f:
    for dup_id in sorted(duplicate_ids):
        f.write(f"{dup_id}\n")

print(f"\n{'='*70}")
print(f"Spisok ID dubley sokhranyen v: duplicate_ids.txt")
print(f"{'='*70}")
