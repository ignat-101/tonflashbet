# 🚀 Инструкция по запуску TON FlashBet на Render

---

## Шаг 1 — Подготовь репозиторий на GitHub

1. Создай аккаунт на [github.com](https://github.com) если нет.
2. Создай новый репозиторий: кнопка **New** → введи имя `tonflashbet` → **Create repository**.
3. Загрузи все файлы проекта:
   ```bash
   cd tonflashbet
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/ТВОЙ_НИКНЕЙМ/tonflashbet.git
   git push -u origin main
   ```

---

## Шаг 2 — Создай сервис на Render

1. Зайди на [render.com](https://render.com) → **Sign Up** (можно через GitHub).
2. На дашборде нажми **New +** → **Web Service**.
3. Выбери **Connect a repository** → подключи GitHub аккаунт → выбери `tonflashbet`.
4. Заполни поля:

   | Поле | Значение |
   |---|---|
   | **Name** | `tonflashbet` |
   | **Region** | Frankfurt (EU) или любой |
   | **Branch** | `main` |
   | **Root Directory** | *(оставь пустым)* |
   | **Runtime** | `Python 3` |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn --chdir backend app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
   | **Instance Type** | `Free` (для старта) |

---

## Шаг 3 — Добавь переменные окружения

В разделе **Environment** добавь:

| Key | Value | Описание |
|---|---|---|
| `BOT_TOKEN` | `123456:ABC...` | Токен от @BotFather |
| `ADMIN_IDS` | `12345678,87654321` | Telegram ID администраторов (через запятую) |

> ⚠️ Никогда не коммить токены в GitHub!

---

## Шаг 4 — Деплой

1. Нажми **Create Web Service**.
2. Render автоматически соберёт и запустит проект (2-3 минуты).
3. Ты получишь ссылку вида: `https://tonflashbet.onrender.com`

---

## Шаг 5 — Настрой Telegram бота

1. Напиши [@BotFather](https://t.me/BotFather) в Telegram.
2. Создай бота: `/newbot` → введи имя и @username.
3. Скопируй токен и добавь в переменные Render (шаг 3).
4. Настрой Mini App: `/newapp` → выбери своего бота → введи URL сервиса:
   ```
   https://tonflashbet.onrender.com
   ```
5. BotFather выдаст ссылку на мини-апп: `https://t.me/your_bot/app`

---

## Шаг 6 — Получи свой Telegram ID (для ADMIN_IDS)

Напиши боту [@userinfobot](https://t.me/userinfobot) — он ответит твоим ID.

---

## Шаг 7 — Проверка

Открой в браузере: `https://tonflashbet.onrender.com/health`

Должно вернуть:
```json
{"status": "ok", "timestamp": "..."}
```

---

## Структура проекта

```
tonflashbet/
├── backend/
│   └── app.py          # Flask-сервер + вся бизнес-логика
├── tma/
│   └── index.html      # Telegram Mini App (фронтенд)
├── requirements.txt    # Python зависимости
├── render.yaml         # Конфиг Render (опционально)
└── docs/
    └── RENDER_DEPLOY.md
```

---

## Кошелёк казны

Все комиссии (5%) направляются на TON-кошелёк:
```
UQCfdyrb0Fj8lA32OfizTwGY829tTzihsEYl1FrpBzeVKdi0
```

---

## Полезные команды для разработки

```bash
# Локальный запуск
cd tonflashbet
pip install -r requirements.txt
python backend/app.py

# Сервер запустится на http://localhost:5000
```

---

## 🔑 Admin-панель

- Войди в TMA под своим Telegram аккаунтом (ID должен быть в `ADMIN_IDS`)
- Появится вкладка **Admin 👑**
- Там можно одобрять/отклонять ставки, запускать голосование, завершать рынки

---

## Обновление кода

```bash
git add .
git commit -m "Update"
git push
```
Render автоматически передеплоит сервис.
