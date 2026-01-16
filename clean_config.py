#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Скрипт для очистки categories_config.txt от дублей
"""

# Загружаем список дублей
with open('duplicate_ids.txt', 'r', encoding='utf-8') as f:
    duplicate_ids = set(int(line.strip()) for line in f if line.strip())

print(f"Zagruzheno dubley: {len(duplicate_ids)}")

# Загружаем текущий конфиг
with open('categories_config.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Парсим категории
categories = []
current_section = None

for line in lines:
    line_stripped = line.strip()
    if not line_stripped:
        continue
    
    # Заголовки секций
    if line_stripped.startswith('#') and '═' in line:
        continue
    elif line_stripped.startswith('#') and any(emoji in line_stripped for emoji in ['🏗️', '🔧', '⚡', '🚿', '🌳', '🎨', '📦']):
        current_section = line_stripped.split(' ', 1)[1] if ' ' in line_stripped else 'OTHER'
        continue
    elif line_stripped.startswith('#'):
        continue
    else:
        # Формат: code = name
        if '=' in line_stripped:
            parts = line_stripped.split('=', 1)
            try:
                code = int(parts[0].strip())
                name = parts[1].strip()
                categories.append({
                    'code': code,
                    'name': name,
                    'section': current_section or 'OTHER',
                    'is_duplicate': code in duplicate_ids
                })
            except ValueError:
                continue

# Статистика
total = len(categories)
duplicates = sum(1 for c in categories if c['is_duplicate'])
clean = total - duplicates

print(f"\n{'='*70}")
print(f"STATISTIKA:")
print(f"{'='*70}")
print(f"Vsego kategoriy: {total}")
print(f"Dubli (budut udaleny): {duplicates}")
print(f"Chistykh kategoriy (ostavlyaem): {clean}")
print(f"{'='*70}")

# Создаем чистый конфиг
clean_categories = [c for c in categories if not c['is_duplicate']]

# Сохраняем
with open('categories_config_clean.txt', 'w', encoding='utf-8') as f:
    f.write("# CLEAN CONFIG - bez dubley\n")
    f.write("# Tolko kornevye kategorii, deti zagruzhayutsya cherez API\n")
    f.write("# Obnovleno avtomaticheski - udaleno 148 dubliruushikhsya kategoriy\n\n")
    
    # Группируем по секциям
    by_section = {}
    for cat in clean_categories:
        section = cat['section']
        if section not in by_section:
            by_section[section] = []
        by_section[section].append(cat)
    
    for section, cats in sorted(by_section.items()):
        f.write(f"\n# ═══════════════════════════════════════════════════════════════\n")
        f.write(f"# {section}\n")
        f.write(f"# ═══════════════════════════════════════════════════════════════\n")
        for cat in cats:
            f.write(f"{cat['code']} = {cat['name']}\n")

print(f"\nChistyy konfig sokhranyen v: categories_config_clean.txt")
print(f"Kategoriy v novom konfigye: {len(clean_categories)}\n")
