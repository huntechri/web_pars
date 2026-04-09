# Backend (FastAPI + PostgreSQL)

API предоставляет:
- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/categories/tree`
- `POST /api/parser/run`
- `GET /api/parser/jobs`
- `GET /api/parser/jobs/{job_id}`
- `GET /api/parser/jobs/{job_id}/progress`
- `GET /api/parser/jobs/{job_id}/results?limit=50&offset=0`
- `GET /api/parser/jobs/{job_id}/download`

## Запуск

1. Запустите PostgreSQL: `docker compose up -d db`
2. Скопируйте `.env.example` в `.env` и при необходимости измените значения
	- `APP_PARSER_COOKIES` — JSON-объект cookies, например `{"u__geoCityCode":"msk"}`
	- `APP_PARSER_HEADERS` — JSON-объект headers, например `{"User-Agent":"Mozilla/..."}`
	- Для выгрузки CSV в Cloudflare R2:
	  - `APP_STORAGE_BUCKET`
	  - `APP_STORAGE_ENDPOINT_URL` (например `https://<account_id>.eu.r2.cloudflarestorage.com`)
	  - `APP_STORAGE_ACCESS_KEY_ID`
	  - `APP_STORAGE_SECRET_ACCESS_KEY`
	  - `APP_STORAGE_REGION=auto`
	  - `APP_STORAGE_PRESIGN_EXPIRE_SECONDS=3600`
3. Установите зависимости: `pip install -r backend/requirements.txt`
4. Запустите API: `python backend/run_api.py`

## Обход антибота (Variti / TLS fingerprint)

АPI Петровича защищён Varити, который блокирует `requests` по JA3 TLS-отпечатку (HTTP 403).
Бэкенд использует **`curl_cffi`** с `impersonate='chrome131'` для имитации Chrome TLS handshake.

**Признак протухших кук:** в логах появляется `[AUTH] Cookies/session may be expired (status=403)`.
Обновите `APP_PARSER_COOKIES` в `.env` и перезапустите сервер.

## Миграции БД

- SQL-миграции лежат в папке [backend/migrations](backend/migrations)
- На старте API автоматически применяются новые `*.sql` файлы (один раз)
- История примененных миграций хранится в таблице `schema_migrations`

По умолчанию API доступен на `http://localhost:8000`.

Если R2 настроен, после парсинга CSV загружается в bucket, локальный файл удаляется,
а `GET /api/parser/jobs/{job_id}/download` выдает redirect на временную ссылку скачивания.


## Запуск

1. Запустите PostgreSQL: `docker compose up -d db`
2. Скопируйте `.env.example` в `.env` и при необходимости измените значения
	- `APP_PARSER_COOKIES` — JSON-объект cookies, например `{"u__geoCityCode":"msk"}`
	- `APP_PARSER_HEADERS` — JSON-объект headers, например `{"User-Agent":"Mozilla/..."}`
	- Для выгрузки CSV в Cloudflare R2:
	  - `APP_STORAGE_BUCKET`
	  - `APP_STORAGE_ENDPOINT_URL` (например `https://<account_id>.eu.r2.cloudflarestorage.com`)
	  - `APP_STORAGE_ACCESS_KEY_ID`
	  - `APP_STORAGE_SECRET_ACCESS_KEY`
	  - `APP_STORAGE_REGION=auto`
	  - `APP_STORAGE_PRESIGN_EXPIRE_SECONDS=3600`
3. Установите зависимости: `pip install -r backend/requirements.txt`
4. Запустите API: `python backend/run_api.py`

## Миграции БД

- SQL-миграции лежат в папке [backend/migrations](backend/migrations)
- На старте API автоматически применяются новые `*.sql` файлы (один раз)
- История примененных миграций хранится в таблице `schema_migrations`

По умолчанию API доступен на `http://localhost:8000`.

Если R2 настроен, после парсинга CSV загружается в bucket, локальный файл удаляется,
а `GET /api/parser/jobs/{job_id}/download` выдает redirect на временную ссылку скачивания.
