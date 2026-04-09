# Полный деплой Petrovich Parser на Render

Ниже — рабочая схема **полного деплоя**: PostgreSQL + Backend API + Frontend.
В текущем `render.yaml` БД уже объявлена и автоматически привязывается к API через `fromDatabase`.

## Как работает парсер в текущей архитектуре

- Парсер запускается через `POST /api/parser/run`.
- Бэкенд создаёт запись задачи в БД и стартует парсинг в фоне (Python thread внутри web-процесса).
- Статус и прогресс читаются через `/api/parser/jobs/{job_id}` и `/api/parser/jobs/{job_id}/progress`.
- Результаты пишутся в таблицу `parse_results` и в CSV:
  - либо локально во временный файл,
  - либо в object storage (рекомендуется: Cloudflare R2).

> Важно: отдельный worker сейчас не используется — парсинг идёт внутри API-сервиса.

---

## Что уже есть в репозитории

В `render.yaml` уже описаны **два web-сервиса**:

1. `petrovich-parser-api` (FastAPI)
2. `petrovich-parser-frontend` (Next.js)

Это позволяет поднять весь проект через Render Blueprint.

---

## Вариант A (рекомендуется): деплой через Blueprint

## 1) База данных

По умолчанию Blueprint создаст БД `petrovich-parser-db` из `render.yaml` и подставит её URL в `APP_DATABASE_URL` автоматически.

Если вы хотите использовать **уже существующую** БД на Render:
1. после создания сервисов откройте `petrovich-parser-api` -> Environment;
2. вручную переопределите `APP_DATABASE_URL` на URL вашей существующей БД.

## 2) Создать Blueprint из репозитория

1. Render -> **New** -> **Blueprint**
2. Выберите ваш GitHub-репозиторий
3. Render прочитает `render.yaml` и предложит создать 2 сервиса

## 3) Заполнить переменные окружения

### Для `petrovich-parser-api`

Обязательные:
- `APP_DATABASE_URL` = ставится автоматически из `petrovich-parser-db` (или задаётся вручную для вашей текущей БД)
- `APP_JWT_SECRET` = длинный случайный секрет
- `APP_ADMIN_PASSWORD` = пароль админа
- `APP_FRONTEND_ORIGIN` = URL фронтенда (например, `https://petrovich-parser-frontend.onrender.com`)

Для парсера Петровича:
- `APP_PARSER_COOKIES` = JSON с cookies
- `APP_PARSER_HEADERS` = JSON с headers (опционально)

Для надёжного хранения выгрузок (рекомендуется):
- `APP_STORAGE_BUCKET`
- `APP_STORAGE_ENDPOINT_URL`
- `APP_STORAGE_ACCESS_KEY_ID`
- `APP_STORAGE_SECRET_ACCESS_KEY`
- `APP_STORAGE_REGION=auto`

### Для `petrovich-parser-frontend`

Обязательная:
- `NEXT_PUBLIC_API_BASE_URL` = внешний URL API (например, `https://petrovich-parser-api.onrender.com`)

## 4) Проверка после деплоя

1. API health:
   - `GET https://<api>.onrender.com/health`
   - Ожидается `{ "status": "ok", ... }`
2. Frontend:
   - открыть `https://<frontend>.onrender.com`
3. Логин админом
4. Запустить парсинг и проверить прогресс/скачивание

---

## Вариант B: если у вас уже есть только PostgreSQL на Render

Создайте отдельно:
1. **Web Service** для backend (из этого репо)
2. **Web Service** для frontend (root directory = `frontend`)

И задайте те же env-переменные, что выше.

### Почему у вас виден только `petrovich-parser-api`

Если вы изначально создали только один Web Service (API), то при обычном `git push`
Render **не создаёт автоматически** второй сервис из `render.yaml`.

Чтобы появился фронтенд, нужно сделать одно из двух:

1. **Через Blueprint (рекомендуется)**
   - Render -> New -> Blueprint -> выбрать этот репозиторий
   - применить план, в котором будет `petrovich-parser-frontend`

2. **Вручную создать frontend-сервис**
   - Render -> New -> Web Service -> этот же репозиторий
   - Name: `petrovich-parser-frontend`
   - Runtime: Node
   - Root Directory: `frontend`
   - Build Command: `npm ci && npm run build`
   - Start Command: `npm run start -- -H 0.0.0.0 -p $PORT`
   - Env: `NEXT_PUBLIC_API_BASE_URL=https://petrovich-parser-api.onrender.com`

---

## Важные нюансы для Render

1. **Эфемерный диск Render**
   - локальные CSV могут исчезать после рестарта/передеплоя.
   - для продакшена лучше обязательно включить R2/S3 (`APP_STORAGE_*`).

2. **Куки Петровича и антибот**
   - при 403 нужно обновлять `APP_PARSER_COOKIES`.
   - в логах это видно как: `[AUTH] Cookies/session may be expired (status=403)`.

3. **`postgres://` vs `postgresql+psycopg2://`**
   - backend сам конвертирует `postgres://...` в формат SQLAlchemy.

4. **Если API «засыпает» на free/starter**
   - первая загрузка после простоя может быть медленной.

5. **Ошибка `connection to server at \"localhost\" ... refused`**
   - это означает, что `APP_DATABASE_URL` не задан и backend взял дефолт `localhost`.
   - проверьте, что переменная `APP_DATABASE_URL` реально заполнена в Render у сервиса API.

6. **Парсинг на Render сильно медленнее, чем локально**
   - это нормально при частых `429`/`403` от API Петровича (антибот + rate limit).
   - стартовые безопасные настройки для Render:
     - `APP_PARSER_MAX_CATEGORY_WORKERS=3`
     - `APP_PARSER_RETRY_BASE_DELAY_SECONDS=0.35`
     - `APP_PARSER_RATE_LIMIT_WAIT_CAP_SECONDS=15`
   - если видите в логах много `RATE LIMIT`, снизьте `APP_PARSER_MAX_CATEGORY_WORKERS` до `2`.
   - если парсите большие выборки, задавайте лимит товаров на категорию в UI.

---

## Минимальный чек-лист «полный прод»

- [ ] Render PostgreSQL подключён к API (`APP_DATABASE_URL`)
- [ ] Деплоится backend `petrovich-parser-api`
- [ ] Деплоится frontend `petrovich-parser-frontend`
- [ ] На фронте задан `NEXT_PUBLIC_API_BASE_URL`
- [ ] На API заданы `APP_PARSER_COOKIES` (и при необходимости `APP_PARSER_HEADERS`)
- [ ] Настроено object storage (`APP_STORAGE_*`) для сохранности CSV
- [ ] `/health` отвечает, логин работает, парсинг стартует и скачивание доступно
