# Petrovich Parser: Web MVP

Минимальная веб-архитектура с сохранением рабочего Python-ядра парсера.

## Что уже сделано

- Ядро парсинга сохранено в [parser/full_auto_parser_CURL.py](parser/full_auto_parser_CURL.py)
- Скрипт генерации дерева категорий в [parser/build_full_categories_tree.py](parser/build_full_categories_tree.py)
- Бэкенд на FastAPI в [backend](backend)
- Фронтенд на Next.js в [frontend](frontend)
- База данных — PostgreSQL (через [docker-compose.yml](docker-compose.yml))

## Архитектура

- Frontend (Next.js):
	- логин
	- выбор категорий (включая дочерние)
	- запуск задачи парсинга
	- скачивание CSV
- Backend (FastAPI):
	- JWT-авторизация
	- API категорий
	- API запуска задач
	- API статуса задачи
	- API скачивания результата
	- выгрузка CSV в Cloudflare R2 (S3 API)
- DB (PostgreSQL):
	- `users`
	- `parse_jobs`

## Быстрый старт

### 1) PostgreSQL

```powershell
docker compose up -d db
```

### 2) Backend

```powershell
pip install -r backend/requirements.txt
copy backend/.env.example backend/.env
python backend/run_api.py
```

В [backend/.env.example](backend/.env.example) можно задать:
- `APP_PARSER_COOKIES` (JSON-объект cookies)
- `APP_PARSER_HEADERS` (JSON-объект headers)
- `APP_STORAGE_BUCKET` (имя R2 bucket)
- `APP_STORAGE_ENDPOINT_URL` (например `https://<account_id>.eu.r2.cloudflarestorage.com`)
- `APP_STORAGE_ACCESS_KEY_ID`
- `APP_STORAGE_SECRET_ACCESS_KEY`
- `APP_STORAGE_REGION` (обычно `auto`)
- `APP_STORAGE_PRESIGN_EXPIRE_SECONDS` (время жизни временной ссылки на скачивание)

API: http://localhost:8000

### 3) Frontend

```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Web: http://localhost:3000

## Основные API

- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/categories/tree`
- `POST /api/parser/run`
- `GET /api/parser/jobs/{job_id}`
- `GET /api/parser/jobs/{job_id}/download`

## Хранение CSV

- После завершения парсинга CSV загружается в Cloudflare R2 (если заполнены `APP_STORAGE_*`).
- Локальный файл после успешной загрузки удаляется.
- Ключи в R2 формируются по датам:
	- `exports/YYYY/MM/DD/{job_id}/petrovich_turbo_YYYYMMDD_HHMMSS.csv`
- Если object storage выключен, используется локальный fallback (поведение как раньше).

## Важно про ядро

Ключевая логика парсинга остается Python-логикой в [parser/full_auto_parser_CURL.py](parser/full_auto_parser_CURL.py).  
Web-слой только управляет запуском и выдачей результата.
