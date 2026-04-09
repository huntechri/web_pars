# Petrovich Parser: Web MVP

Парсер каталога [moscow.petrovich.ru](https://moscow.petrovich.ru/catalog/) с веб-интерфейсом.
Позволяет выбирать категории, запускать парсинг, отслеживать прогресс и скачивать результат в CSV.

## Архитектура

| Компонент | Технология | Адрес по умолчанию |
|-----------|------------|-------------------|
| Frontend | Next.js | `http://localhost:3000` |
| Backend | FastAPI + uvicorn | `http://localhost:8000` |
| Database | PostgreSQL | внешняя (Render.com и др.) |

**Основные возможности:**
- JWT-авторизация
- Дерево категорий с выбором и сворачиванием
- Запуск задач парсинга и мониторинг прогресса
- Скачивание CSV / выгрузка в Cloudflare R2

## Обход антибота (Variti / TLS fingerprint)

API Петровича защищён антиботом **Variti**, который блокирует запросы по TLS-отпечатку (JA3).
Стандартный `requests` возвращает **403**. Парсер использует **`curl_cffi`** с имперсонацией `chrome131`,
что обходит защиту без прокси.

**Признак протухших кук:** в логах появляется `[AUTH] Cookies/session may be expired (status=403)`.

Как обновить куки:
1. Открой [moscow.petrovich.ru/catalog](https://moscow.petrovich.ru/catalog/) в браузере
2. DevTools → Network → любой запрос к `api.petrovich.ru` → вкладка Headers → скопируй `Cookie:`
3. Обнови `APP_PARSER_COOKIES` в `backend/.env`
4. Перезапусти бэкенд

> **Важно:** куки привязаны к IP-адресу. Браузер, с которого скопированы куки, и сервер бэкенда должны работать с **одного и того же внешнего IP**.

---

## Быстрый старт

### Требования

- Python 3.10+
- Node.js 18+
- Внешняя PostgreSQL БД (Render.com, Supabase, Neon и др.)

### 1) Backend

```powershell
pip install -r backend/requirements.txt
copy backend\.env.example backend\.env
# Отредактируй backend/.env: задай строку подключения к БД, куки, пароль
python backend/run_api.py
```

API: `http://localhost:8000`  
Swagger UI: `http://localhost:8000/docs`  
При старте автоматически применяются SQL-миграции из `backend/migrations/`.

Переменные в `backend/.env`:

| Переменная | Описание |
|------------|----------|
| `APP_DATABASE_URL` | Строка подключения PostgreSQL |
| `APP_JWT_SECRET` | Секрет для подписи токенов (замени!) |
| `APP_ADMIN_USERNAME` | Логин для входа в интерфейс |
| `APP_ADMIN_PASSWORD` | Пароль для входа в интерфейс |
| `APP_FRONTEND_ORIGIN` | Origin фронтенда (для CORS) |
| `APP_PARSER_COOKIES` | JSON-объект кук от браузера |
| `APP_STORAGE_BUCKET` | Имя Cloudflare R2 bucket (опционально) |
| `APP_STORAGE_ENDPOINT_URL` | Endpoint R2 |
| `APP_STORAGE_ACCESS_KEY_ID` | Access Key R2 |
| `APP_STORAGE_SECRET_ACCESS_KEY` | Secret Key R2 |

### 2) Frontend

```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Интерфейс: `http://localhost:3000`

---

## Запуск с другого устройства (локальная сеть / удалённо)

Эта инструкция позволяет открыть веб-интерфейс с **любого устройства** в сети —
ноутбука, планшета, другого ПК — без изменения кода.

### Шаг 1 — Клонируй репозиторий

```bash
git clone https://github.com/huntechri/web_pars.git
cd web_pars
```

### Шаг 2 — Установи зависимости

```bash
# Python
pip install -r backend/requirements.txt

# Node.js
cd frontend && npm install && cd ..
```

### Шаг 3 — Узнай IP сервера

На машине, где будет работать бэкенд:

```powershell
# Windows
ipconfig
# Ищи "IPv4-адрес", например: 192.168.1.105
```

```bash
# Linux / macOS
ip a
# или
hostname -I
```

Запиши IP — он нужен в шагах 4 и 5.

### Шаг 5 — Настрой backend/.env

```powershell
copy backend\.env.example backend\.env
```

Ключевые параметры для сетевого запуска:

```env
# Строка подключения к PostgreSQL (Render, Supabase и др.)
APP_DATABASE_URL=postgresql+psycopg2://user:password@host/dbname

# Секрет JWT — замени на случайную строку!
APP_JWT_SECRET=your-random-secret-here

# Логин/пароль для входа через браузер
APP_ADMIN_USERNAME=admin
APP_ADMIN_PASSWORD=your-password

# CORS: адрес, по которому браузер открывает фронтенд
# Пример для локальной сети:
APP_FRONTEND_ORIGIN=http://192.168.1.105:3000
# Пример для домена:
# APP_FRONTEND_ORIGIN=https://your-domain.com

# Куки от браузера (см. раздел "Обход антибота")
APP_PARSER_COOKIES={"your_cookie_key": "value"}
```

> **`APP_FRONTEND_ORIGIN`** — это адрес, по которому браузер клиента **открывает фронтенд**.
> Если заходишь с `http://192.168.1.105:3000` — именно это и укажи.
> Неверное значение → ошибка **CORS** в браузере.

### Шаг 6 — Настрой frontend/.env.local

```bash
cd frontend
cp .env.local.example .env.local   # Linux/macOS
# или
copy .env.local.example .env.local  # Windows
```

Открой `frontend/.env.local` и укажи адрес бэкенда:

```env
# IP (или домен) машины, где запущен python backend/run_api.py
NEXT_PUBLIC_API_BASE_URL=http://192.168.1.105:8000
```

Если фронтенд и бэкенд на **разных машинах** — укажи IP машины с бэкендом.  
Если на **одной машине** — `localhost` не подойдёт клиентам; используй реальный IP.

### Шаг 7 — Запусти бэкенд

```bash
python backend/run_api.py
```

Бэкенд слушает на `0.0.0.0:8000` — доступен со всех сетевых интерфейсов.

### Шаг 8 — Запусти фронтенд

```bash
cd frontend

# Для production (рекомендуется):
npm run build
npm run start   # слушает на 0.0.0.0:3000

# Для разработки:
npm run dev
```

### Шаг 8 — Открой в браузере на другом устройстве

```
http://192.168.1.105:3000
```

Замени `192.168.1.105` на реальный IP сервера.

---

### Проверка связи

С клиентского устройства:

```bash
# Бэкенд отвечает?
curl http://192.168.1.105:8000/api/auth/me
# Ожидаем: {"detail":"Not authenticated"}

# Фронтенд отвечает?
curl -I http://192.168.1.105:3000
# Ожидаем: HTTP/1.1 200 OK
```

---

### Доступ через интернет (вне локальной сети)

#### Вариант A — ngrok (быстро, для тестов)

```bash
# Установи: https://ngrok.com/download
ngrok http 8000   # туннель бэкенда — запомни https://xxxx.ngrok-free.app
ngrok http 3000   # туннель фронтенда — в отдельном терминале
```

- `backend/.env` → `APP_FRONTEND_ORIGIN=https://<адрес фронт-туннеля>`
- `frontend/.env.local` → `NEXT_PUBLIC_API_BASE_URL=https://<адрес бэк-туннеля>`

После изменения `.env.local` пересобери фронтенд: `npm run build && npm run start`.

#### Вариант B — Cloudflare Tunnel (бесплатно, стабильный)

```bash
# Установи: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
cloudflared tunnel --url http://localhost:8000
```

---

### Открытие портов (Windows Firewall)

Если с других устройств нет подключения — открой порты:

```powershell
netsh advfirewall firewall add rule name="Petrovich Backend" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="Petrovich Frontend" dir=in action=allow protocol=TCP localport=3000
```

---

## Основные API

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/auth/login` | Получить JWT-токен |
| `GET` | `/api/auth/me` | Проверить токен |
| `GET` | `/api/categories/tree` | Дерево категорий |
| `POST` | `/api/categories/refresh` | Обновить категории из источника |
| `POST` | `/api/parser/run` | Запустить задачу парсинга |
| `GET` | `/api/parser/jobs` | Список всех задач |
| `GET` | `/api/parser/jobs/{job_id}` | Статус задачи |
| `GET` | `/api/parser/jobs/{job_id}/progress` | Прогресс задачи |
| `GET` | `/api/parser/jobs/{job_id}/results` | Результаты (с пагинацией) |
| `GET` | `/api/parser/jobs/{job_id}/download` | Скачать CSV |

Swagger UI: `http://localhost:8000/docs`

## Зависимости

| Пакет | Зачем |
|-------|-------|
| `curl_cffi` | Chrome TLS impersonation — обход Variti антибота |
| `fastapi` + `uvicorn` | REST API |
| `sqlalchemy` + `psycopg2` | PostgreSQL ORM |
| `boto3` | Cloudflare R2 (S3-совместимый) |
| `next` | Фронтенд |
