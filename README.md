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

## Важно про ядро

Ключевая логика парсинга остается Python-логикой в [parser/full_auto_parser_CURL.py](parser/full_auto_parser_CURL.py).  
Web-слой только управляет запуском и выдачей результата.
