# Deploy на Render (FastAPI + PostgreSQL)

## 1) Создать PostgreSQL на Render

1. New + -> PostgreSQL
2. Запомнить Internal Database URL
3. После создания скопировать URL

## 2) Создать Web Service

1. New + -> Web Service (из GitHub-репозитория)
2. Render обнаружит [render.yaml](render.yaml)
3. В env задайте:
   - `APP_DATABASE_URL` = ваш Internal Database URL
   - `APP_JWT_SECRET` = случайная длинная строка
   - `APP_ADMIN_PASSWORD` = надежный пароль
   - `APP_FRONTEND_ORIGIN` = URL фронтенда (например, `https://your-frontend.onrender.com`)
  - `APP_PARSER_COOKIES` = JSON-объект cookies (опционально)
  - `APP_PARSER_HEADERS` = JSON-объект headers (опционально)

## 3) Важно про URL БД

Если Render даст URL вида `postgres://...`, backend автоматически преобразует его в SQLAlchemy-формат `postgresql+psycopg2://...`.

## 4) Проверка

- `GET /health` должен вернуть `{ "status": "ok" }`
- Затем проверить логин:
  - `POST /api/auth/login`

## 5) Frontend

Для Next.js на Render/Vercel задайте:
- `NEXT_PUBLIC_API_BASE_URL=https://<ваш-api>.onrender.com`
