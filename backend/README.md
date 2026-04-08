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
3. Установите зависимости: `pip install -r backend/requirements.txt`
4. Запустите API: `python backend/run_api.py`

По умолчанию API доступен на `http://localhost:8000`.
