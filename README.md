# Inventory Render Control

Отдельный Telegram Control Bot для управления основным Inventory Bot на Render.

## Кнопки

- 🟢 Запустить Inventory → Render API `POST /v1/services/{serviceId}/resume`
- 🔴 Остановить Inventory → Render API `POST /v1/services/{serviceId}/suspend`
- 🔄 Перезапустить → Render API `POST /v1/services/{serviceId}/restart`
- 📊 Статус → Render API `GET /v1/services/{serviceId}`

## Почему отдельный сервис

Основной Inventory Bot не может запустить сам себя после `suspend`, потому что его процесс уже остановлен.
Control Bot находится в отдельном Render Web Service и вызывает Render API снаружи.

## Создание Telegram Control Bot

1. Открой @BotFather.
2. `/newbot`.
3. Создай отдельного бота, например `Inventory Render Control`.
4. Скопируй новый Telegram token.

## GitHub

Создай НОВЫЙ репозиторий, например:

`inventory-render-control`

Загрузи туда содержимое этой папки.

## Render

Создай новый Web Service из нового GitHub-репозитория.

Можно использовать `render.yaml` или вручную:

- Runtime: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Health Check Path: `/health`

## Environment Variables

Обязательные:

- `BOT_TOKEN` — токен отдельного Control Bot.
- `RENDER_API_KEY` — Render API key.
- `TARGET_SERVICE_ID` — Service ID основного Inventory Bot.
- `BASE_WEB_URL` — публичный URL Control Bot после создания на Render.
- `ADMIN_IDS` — Telegram ID администраторов через запятую.

Опционально:

- `TARGET_SERVICE_NAME=Inventory Bot`

### Первый запуск

Есть небольшой куриный-яичный момент с `BASE_WEB_URL`:

1. Создай Control Bot Web Service на Render.
2. Render выдаст URL вида `https://inventory-render-control.onrender.com`.
3. Добавь этот URL в `BASE_WEB_URL`.
4. Сделай Manual Deploy / Restart один раз.
5. В Telegram открой Control Bot и нажми `/start`.

После этого webhook будет установлен автоматически.

## Бесплатный Render

Control Bot использует webhook, поэтому ему не нужен постоянный polling.
Если бесплатный Web Service уснул, первый запрос Telegram может ждать cold start.
После пробуждения следующие команды выполняются быстрее.

`drop_pending_updates=False`, поэтому Control Bot не просит Telegram намеренно выбрасывать накопившиеся обновления при старте.

## Безопасность

Никогда не коммить:

- BOT_TOKEN
- RENDER_API_KEY

Они должны находиться в Render Environment Variables.

Доступ к командам разрешён только ID из `ADMIN_IDS`.

## Проверка

Открой:

`https://YOUR-CONTROL-BOT.onrender.com/health`

Ожидается:

```json
{"status":"ok","telegram":"webhook"}
```

После `/start` в Telegram появится inline-панель управления.
