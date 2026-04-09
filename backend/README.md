# Backend (FastAPI + PostgreSQL)

API предоставляет:
- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/categories/tree`
- `POST /api/parser/run`
- `GET /api/parser/jobs/{job_id}`
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

По умолчанию API доступен на `http://localhost:8000`.

Если R2 настроен, после парсинга CSV загружается в bucket, локальный файл удаляется,
а `GET /api/parser/jobs/{job_id}/download` выдает redirect на временную ссылку скачивания.
