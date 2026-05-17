# Petrovich Material Parser

CLI-скрипт для парсинга материалов из каталога Петровича в CSV.

## Установка

```bash
pip install -r requirements.txt
```

## Куки

1. Скопируйте пример окружения:

   ```bash
   cp .env.example .env
   ```

2. Откройте сайт Петровича в браузере.
3. DevTools → Network → любой запрос к `api.petrovich.ru` → Headers → скопируйте значение `Cookie`.
4. Вставьте куки в `.env` в переменную `APP_PARSER_COOKIES` как JSON-объект.

Пример:

```env
APP_PARSER_COOKIES={"cookie_name":"cookie_value"}
```

## Запуск

```bash
python3 parser/material_parser.py
```

## Флаги

- `--categories` — список ID категорий через пробел.
- `--max-products-per-cat` — лимит товаров на одну категорию.
- `--resume-from` — пропустить первые `N` категорий и начать со следующей.
- `--output` — имя выходного CSV-файла.

Примеры:

```bash
python3 parser/material_parser.py --categories 123 456 --max-products-per-cat 100
python3 parser/material_parser.py --resume-from 20 --output materials.csv
```

## Выход

Скрипт сохраняет CSV с русскими колонками: код, название, единица измерения, цена, валюта, категории, поставщик, синонимы, ключевые слова, описание и ссылка на изображение.

Для работы нужны:

- `parser/material_parser.py` — основной скрипт;
- `categories_full_tree.json` — дерево категорий;
- `categories_config.txt` — конфиг категорий для обратной совместимости;
- `.env` — локальные куки, не коммитится в репозиторий.
