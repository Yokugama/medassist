# MedAssist AI v2 — Полная документация

## Структура проекта

```
medweb/
├── backend/
│   ├── main.py           # FastAPI: авторизация, SQLite, Admin API
│   └── requirements.txt
└── frontend/
    ├── index.html        # Страница входа / регистрации
    ├── app.html          # Дашборд пользователя (чат, статистика, история)
    └── admin.html        # Панель администратора
```

## Быстрый старт

### 1. Установи зависимости
```bash
cd backend
pip install -r requirements.txt
```

### 2. Запусти сервер
```bash
uvicorn main:app --reload --port 8080
```

### 3. Открой браузер
```
http://localhost:8080
```

По умолчанию создаётся аккаунт администратора:
- Логин: `admin`
- Пароль: `admin123`

## Роли пользователей

| Роль  | Доступ                                              |
|-------|-----------------------------------------------------|
| user  | Чат с моделью, своя статистика, своя история        |
| admin | Всё выше + управление пользователями, настройка туннеля Kaggle, все запросы системы |

## Страницы

### `/` — Вход / Регистрация
- Вкладки «Вход» и «Регистрация»
- После входа автоматический редирект: admin → `/admin.html`, user → `/app.html`
- Сессия хранится в cookie + localStorage

### `/app.html` — Дашборд пользователя
- **Чат** — отправка симптомов, ответ с отделением и рекомендацией
- **Статистика** — метрики, бар-чарт, донат только по своим запросам
- **История** — фильтры, поиск, экспорт CSV, копирование ответа

### `/admin.html` — Панель администратора
- **Дашборд** — метрики всех пользователей + последние запросы системы
- **Пользователи** — блокировка / разблокировка / назначение admin / удаление
- **Все запросы** — история всех пользователей
- **Туннель Kaggle** — изменение URL, проверка соединения, инструкция

## API эндпоинты

### Auth
| Метод | URL                  | Описание                    |
|-------|----------------------|-----------------------------|
| POST  | /api/auth/register   | Регистрация                 |
| POST  | /api/auth/login      | Вход                        |
| POST  | /api/auth/logout     | Выход                       |
| GET   | /api/auth/me         | Текущий пользователь        |

### User
| Метод  | URL             | Описание                        |
|--------|-----------------|---------------------------------|
| POST   | /api/query      | Отправить запрос пациента       |
| GET    | /api/stats      | Статистика текущего пользователя|
| GET    | /api/history    | История текущего пользователя   |
| DELETE | /api/history    | Очистить свою историю           |
| GET    | /api/health     | Проверка соединения             |

### Admin (только role=admin)
| Метод  | URL                       | Описание                         |
|--------|---------------------------|----------------------------------|
| GET    | /api/admin/stats          | Статистика всей системы          |
| GET    | /api/admin/users          | Список пользователей             |
| PATCH  | /api/admin/users/{id}     | Изменить роль / заблокировать    |
| DELETE | /api/admin/users/{id}     | Удалить пользователя             |
| GET    | /api/admin/queries        | Все запросы системы              |
| GET    | /api/admin/settings       | Текущие настройки                |
| POST   | /api/admin/tunnel         | Сохранить URL туннеля            |
| POST   | /api/admin/tunnel/test    | Проверить соединение с Kaggle    |

## Подключение модели Kaggle

Добавьте в конец вашего Kaggle notebook:

```python
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn, threading, re

api = FastAPI()

class Q(BaseModel):
    query: str

@api.post("/query")
async def query(req: Q):
    result = assistant.process_query(req.query)
    blocked = result.startswith("🛑")
    dept = None
    if not blocked:
        m = re.search(r'Отделение:\s*(.+)', result)
        if m: dept = m.group(1).strip()
    return {"response": result, "department": dept, "blocked": blocked}

threading.Thread(
    target=lambda: uvicorn.run(api, host="0.0.0.0", port=8000),
    daemon=True
).start()

import subprocess, urllib.request
ip = urllib.request.urlopen('https://ipv4.icanhazip.com').read().decode().strip()
print(f"Пароль туннеля: {ip}")
subprocess.Popen(["npx", "localtunnel", "--port", "8000"])
```

Затем скопируйте URL туннеля в Панель администратора → Туннель Kaggle.

# medassist
