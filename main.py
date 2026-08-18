import asyncio
import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "").strip()
TARGET_SERVICE_ID = os.getenv("TARGET_SERVICE_ID", "").strip()
BASE_WEB_URL = os.getenv("BASE_WEB_URL", "").strip().rstrip("/")
TARGET_SERVICE_NAME = os.getenv("TARGET_SERVICE_NAME", "Inventory Bot").strip()

DEFAULT_ADMINS = "502438855,785245733,6311609684,177536138,8103344174"
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", DEFAULT_ADMINS).split(",")
    if x.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not RENDER_API_KEY:
    raise RuntimeError("RENDER_API_KEY is required")
if not TARGET_SERVICE_ID:
    raise RuntimeError("TARGET_SERVICE_ID is required")
if not BASE_WEB_URL:
    raise RuntimeError("BASE_WEB_URL is required")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
app = FastAPI(title="Inventory Render Control", version="1.0.0")

RENDER_BASE = "https://api.render.com/v1"
ACTION_LOCK = asyncio.Lock()


def render_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def control_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Запустить Inventory",
                    callback_data="render:resume",
                ),
                InlineKeyboardButton(
                    text="🔴 Остановить Inventory",
                    callback_data="render:suspend",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Перезапустить",
                    callback_data="render:restart",
                ),
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="render:status",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="♻️ Обновить меню",
                    callback_data="render:menu",
                ),
            ],
        ]
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def find_bool(obj: Any, key: str) -> bool | None:
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], bool):
            return obj[key]
        for value in obj.values():
            found = find_bool(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_bool(value, key)
            if found is not None:
                return found
    return None


def find_text(obj: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = find_text(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_text(value, keys)
            if found:
                return found
    return None


async def render_request(
    method: str,
    path: str,
    *,
    timeout: float = 35.0,
) -> tuple[int, Any]:
    url = f"{RENDER_BASE}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method,
            url,
            headers=render_headers(),
        )

    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text

    return response.status_code, payload


async def get_service_status() -> tuple[bool, str]:
    status, payload = await render_request(
        "GET",
        f"/services/{TARGET_SERVICE_ID}",
    )

    if status != 200:
        return False, (
            f"❌ Render API: HTTP {status}\n"
            f"{str(payload)[:800]}"
        )

    suspended = find_bool(payload, "suspended")
    name = find_text(payload, ("name",)) or TARGET_SERVICE_NAME
    service_type = find_text(payload, ("type", "serviceType")) or "service"
    updated = find_text(payload, ("updatedAt", "updated_at"))

    if suspended is True:
        state = "🔴 ОСТАНОВЛЕН"
    elif suspended is False:
        state = "🟢 ЗАПУЩЕН"
    else:
        state = "🟡 Статус suspend не указан API"

    text = (
        f"📊 <b>{name}</b>\n\n"
        f"Состояние: <b>{state}</b>\n"
        f"Тип: <code>{service_type}</code>\n"
        f"Service ID: <code>{TARGET_SERVICE_ID}</code>"
    )
    if updated:
        text += f"\nRender updatedAt: <code>{updated}</code>"

    return True, text


async def do_action(action: str) -> tuple[bool, str]:
    if action == "resume":
        endpoint = f"/services/{TARGET_SERVICE_ID}/resume"
        expected = {200, 202}
        waiting_text = "🟢 Команда запуска принята Render."
    elif action == "suspend":
        endpoint = f"/services/{TARGET_SERVICE_ID}/suspend"
        expected = {200, 202}
        waiting_text = "🔴 Команда остановки принята Render."
    elif action == "restart":
        endpoint = f"/services/{TARGET_SERVICE_ID}/restart"
        expected = {200, 202}
        waiting_text = "🔄 Команда перезапуска принята Render."
    else:
        return False, "Неизвестная команда."

    status, payload = await render_request("POST", endpoint)

    if status in expected:
        return True, (
            f"{waiting_text}\n\n"
            f"HTTP {status}\n"
            "Состояние можно проверить кнопкой «📊 Статус»."
        )

    if status == 429:
        return False, (
            "⏳ Render ограничил частоту запросов (HTTP 429).\n"
            "Подожди немного и повтори."
        )

    if status == 401:
        return False, (
            "🔐 Render отклонил API key (HTTP 401).\n"
            "Проверь RENDER_API_KEY в Environment."
        )

    if status == 403:
        return False, (
            "⛔ У API key нет доступа к этому сервису (HTTP 403).\n"
            "Проверь TARGET_SERVICE_ID и права ключа."
        )

    if status == 404:
        return False, (
            "🔎 Render не нашёл TARGET_SERVICE_ID (HTTP 404).\n"
            f"Сейчас указан: {TARGET_SERVICE_ID}"
        )

    return False, (
        f"❌ Render API вернул HTTP {status}\n"
        f"{str(payload)[:1000]}"
    )


@dp.message(CommandStart())
async def start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        logging.warning(
            "Unauthorized /start from user_id=%s",
            message.from_user.id,
        )
        return

    await message.answer(
        "🎛 <b>INVENTORY RENDER CONTROL</b>\n\n"
        f"Целевой сервис: <b>{TARGET_SERVICE_NAME}</b>\n\n"
        "Этот бот работает отдельно от Inventory Bot, "
        "поэтому может запустить его даже после полного Suspend.",
        parse_mode="HTML",
        reply_markup=control_keyboard(),
    )


@dp.callback_query(F.data == "render:menu")
async def refresh_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🎛 <b>INVENTORY RENDER CONTROL</b>\n\n"
        f"Целевой сервис: <b>{TARGET_SERVICE_NAME}</b>\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=control_keyboard(),
    )


@dp.callback_query(F.data == "render:status")
async def status_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.answer("Проверяю Render…")

    try:
        _, text = await get_service_status()
    except Exception as exc:
        logging.exception("Render status error")
        text = f"❌ Ошибка связи с Render:\n{exc}"

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=control_keyboard(),
    )


@dp.callback_query(F.data.in_({
    "render:resume",
    "render:suspend",
    "render:restart",
}))
async def action_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    action_name = {
        "resume": "Запускаю Inventory…",
        "suspend": "Останавливаю Inventory…",
        "restart": "Перезапускаю Inventory…",
    }[action]

    # Answer immediately. This matters after a free Render cold start:
    # Telegram's spinner should not wait for the Render API call.
    await callback.answer(action_name)

    if ACTION_LOCK.locked():
        await callback.message.answer(
            "⏳ Уже выполняется другая команда Render. "
            "Дождись её завершения."
        )
        return

    async with ACTION_LOCK:
        try:
            ok, text = await do_action(action)
        except Exception as exc:
            logging.exception("Render action failed: %s", action)
            ok = False
            text = f"❌ Ошибка связи с Render:\n{exc}"

    prefix = "✅" if ok else "⚠️"
    await callback.message.answer(
        f"{prefix} {text}",
        reply_markup=control_keyboard(),
    )


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "inventory-render-control",
        "target_service_id": TARGET_SERVICE_ID,
    }


@app.get("/health")
async def health():
    return JSONResponse(
        {
            "status": "ok",
            "telegram": "webhook",
        }
    )


@app.post("/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()

    # Logging only metadata, never token/API key.
    if "callback_query" in payload:
        callback = payload.get("callback_query") or {}
        user = callback.get("from") or {}
        logging.info(
            "Telegram callback user_id=%s data=%s",
            user.get("id"),
            callback.get("data"),
        )

    update = Update.model_validate(payload)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.on_event("startup")
async def startup():
    webhook_url = f"{BASE_WEB_URL}/webhook"
    allowed_updates = dp.resolve_used_update_types()
    if "callback_query" not in allowed_updates:
        allowed_updates.append("callback_query")
    if "message" not in allowed_updates:
        allowed_updates.append("message")

    # Keep pending updates: a free instance may have been asleep.
    await bot.set_webhook(
        webhook_url,
        allowed_updates=allowed_updates,
        drop_pending_updates=False,
    )

    me = await bot.get_me()
    logging.info(
        "Control Bot started as @%s; webhook=%s",
        me.username,
        webhook_url,
    )


@app.on_event("shutdown")
async def shutdown():
    await bot.session.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
