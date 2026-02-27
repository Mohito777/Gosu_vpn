"""
Админ-панель для управления VPN-сервисом.
Команды: /admin, /stats, /broadcast, /user, /promo
"""

import asyncio
from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.filters import Command
import database as db
import config
from keyboards import (
    admin_keyboard,
    admin_inline_keyboard,
    back_keyboard,
)
from logger import get_logger

log = get_logger("admin")


# ── Admin filter ──────────────────────────────────────────────────────────────

class AdminFilter:
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in config.ADMIN_IDS


# ── /admin command ────────────────────────────────────────────────────────────

async def cmd_admin(message: Message):
    """Открыть админ-меню."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    text = (
        "🔧 <b>Админ-панель</b>\n\n"
        "Выберите действие:"
    )
    await message.answer(text, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)


# ── Statistics ────────────────────────────────────────────────────────────────

async def cmd_stats(message: Message):
    """Показать статистику."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    stats = db.get_stats()
    text = (
        "📊 <b>Статистика VPN-сервиса</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"✅ Активных подписок: <b>{stats['active_users']}</b>\n"
        f"📢 Подписано на канал: <b>{stats['subscribed_users']}</b>\n"
        f"🎁 Использовали триал: <b>{stats['trial_used']}</b>\n"
        f"💰 Общий доход: <b>{stats['total_revenue']:.2f} ₽</b>\n"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


async def show_admin_stats(call: CallbackQuery):
    """Показать статистику (inline)."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return
    
    stats = db.get_stats()
    text = (
        "📊 <b>Статистика VPN-сервиса</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"✅ Активных подписок: <b>{stats['active_users']}</b>\n"
        f"📢 Подписано на канал: <b>{stats['subscribed_users']}</b>\n"
        f"🎁 Использовали триал: <b>{stats['trial_used']}</b>\n"
        f"💰 Общий доход: <b>{stats['total_revenue']:.2f} ₽</b>\n"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_inline_keyboard())
    await call.answer()


# ── Users management ──────────────────────────────────────────────────────────

async def show_users_list(call: CallbackQuery):
    """Показать список пользователей."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return

    users = db.get_all_users()
    text = "👥 <b>Пользователи</b>\n\n"

    for user in users[:50]:  # Показываем первые 50
        status = "✅" if user["active"] else "❌"
        username = user["username"] or f"tg{user['telegram_id']}"
        text += f"{status} <code>{user['telegram_id']}</code> — @{username}\n"

    if len(users) > 50:
        text += f"\n... и ещё {len(users) - 50} пользователей"

    await call.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard()
    )
    await call.answer()


async def cmd_user(message: Message):
    """Информация о пользователе: /user <telegram_id>"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /user <telegram_id>")
        return
    
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("Неверный telegram_id")
        return
    
    user = db.get_user(telegram_id)
    if not user:
        await message.answer("Пользователь не найден")
        return
    
    referrals_count = db.get_referrals_count(telegram_id)
    
    text = (
        f"👤 <b>Информация о пользователе</b>\n\n"
        f"ID: <code>{user['telegram_id']}</code>\n"
        f"Username: @{user['username'] or 'нет'}\n"
        f"Активен: {'✅' if user['active'] else '❌'}\n"
        f"Подписка до: {user['subscription_end'] or '—'}\n"
        f"Триал использован: {'✅' if user['trial_used'] else '❌'}\n"
        f"Подписан на канал: {'✅' if user['subscribed_channel'] else '❌'}\n"
        f"Рефералов: {referrals_count}\n"
        f"UUID: <code>{user['uuid'] or '—'}</code>\n"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


# ── Mailing / Broadcast ───────────────────────────────────────────────────────

async def show_mailing_form(call: CallbackQuery):
    """Показать форму рассылки."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return
    
    text = (
        "📩 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем активным пользователям.\n\n"
        "⚠️ Внимание: сообщение будет отправлено всем активным пользователям!"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())
    await call.answer()


async def process_mailing_message(message: Message):
    """Обработка сообщения для рассылки."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    # Проверяем, ожидает ли админ сообщение для рассылки
    # (в реальном проекте нужно использовать FSM)
    text = message.text or message.html_text
    
    users = db.get_all_active_users()
    success_count = 0
    failed_count = 0
    
    status_message = await message.answer(f"📩 Отправка рассылки... 0/{len(users)}")
    
    for user in users:
        try:
            await message.bot.send_message(
                user["telegram_id"],
                f"📢 <b>Сообщение от администрации</b>\n\n{text}",
                parse_mode=ParseMode.HTML,
            )
            success_count += 1
        except Exception as e:
            log.error(f"Mailing failed for {user['telegram_id']}: {e}")
            failed_count += 1
        
        # Обновляем статус каждые 10 сообщений
        if (success_count + failed_count) % 10 == 0:
            await status_message.edit_text(
                f"📩 Отправка рассылки... {success_count + failed_count}/{len(users)}"
            )
        await asyncio.sleep(0.1)  # Anti-spam
    
    # Логируем рассылку
    db.log_mailing(message.from_user.id, text, success_count, failed_count)
    
    await status_message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Успешно: {success_count}\n"
        f"Ошибка: {failed_count}"
    )


# ── Promo codes ───────────────────────────────────────────────────────────────

async def show_promocodes_list(call: CallbackQuery):
    """Показать список промокодов."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return
    
    promo_codes = db.get_all_promo_codes()
    
    if not promo_codes:
        text = "🎁 Промокоды не созданы"
    else:
        text = "🎁 <b>Промокоды</b>\n\n"
        for pc in promo_codes:
            status = "✅" if pc["active"] else "❌"
            uses = f"{pc['used_count']}/{pc['max_uses']}" if pc['max_uses'] else f"{pc['used_count']}/∞"
            text += f"{status} <code>{pc['code']}</code> — +{pc['bonus_days']} дн. ({uses})\n"
    
    text += "\n\nСоздать: /promo create CODE DAYS [MAX_USES]"
    text += "\nУдалить: /promo delete CODE"
    
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_inline_keyboard())
    await call.answer()


async def cmd_promo(message: Message):
    """Управление промокодами: /promo create CODE DAYS [MAX_USES]"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) < 4:
        await message.answer(
            "Использование:\n"
            "/promo create CODE DAYS [MAX_USES]\n"
            "/promo delete CODE"
        )
        return
    
    action = parts[1]
    
    if action == "create":
        code = parts[2]
        try:
            days = int(parts[3])
            max_uses = int(parts[4]) if len(parts) > 4 else None
        except ValueError:
            await message.answer("DAYS и MAX_USES должны быть числами")
            return
        
        success = db.create_promo_code(code, days, max_uses, message.from_user.id)
        if success:
            max_str = f" (макс. {max_uses} раз)" if max_uses else ""
            await message.answer(f"✅ Промокод создан: <code>{code}</code> (+{days} дн.{max_str})", parse_mode=ParseMode.HTML)
        else:
            await message.answer("❌ Промокод с таким кодом уже существует")
    
    elif action == "delete":
        code = parts[2]
        success = db.deactivate_promo_code(code)
        if success:
            await message.answer(f"✅ Промокод deactivated: <code>{code}</code>", parse_mode=ParseMode.HTML)
        else:
            await message.answer("❌ Промокод не найден")
    
    else:
        await message.answer("Неизвестная команда. Используйте /promo create или /promo delete")


# ── Settings ──────────────────────────────────────────────────────────────────

async def show_settings(call: CallbackQuery):
    """Показать настройки."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return
    
    channel = db.get_channel_username()
    trial_days = db.get_trial_days()
    
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"📢 Канал: <code>{channel}</code>\n"
        f"🎁 Триал: <code>{trial_days} дн.</code>\n\n"
        "Изменить:\n"
        "/set_channel @username\n"
        "/set_trial_days N"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_inline_keyboard())
    await call.answer()


async def cmd_set_channel(message: Message):
    """Установить канал: /set_channel @username"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /set_channel @username")
        return
    
    username = parts[1]
    if not username.startswith("@"):
        username = "@" + username
    
    db.set_channel_username(username)
    await message.answer(f"✅ Канал установлен: <code>{username}</code>", parse_mode=ParseMode.HTML)


async def cmd_set_trial_days(message: Message):
    """Установить длительность триала: /set_trial_days N"""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /set_trial_days N")
        return
    
    try:
        days = int(parts[1])
    except ValueError:
        await message.answer("N должно быть числом")
        return
    
    db.set_trial_days(days)
    await message.answer(f"✅ Триал установлен: <code>{days} дн.</code>", parse_mode=ParseMode.HTML)


# ── Back button ───────────────────────────────────────────────────────────────

async def cb_back_main(call: CallbackQuery):
    """Кнопка 'Назад' в главное меню."""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("⛔️ Доступ запрещён", show_alert=True)
        return
    
    text = "🔧 <b>Админ-панель</b>\n\nВыберите действие:"
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
    await call.answer()


# ── Register handlers ─────────────────────────────────────────────────────────

def register_admin_handlers(dp):
    """Регистрация админ-хендлеров."""
    from aiogram.filters import Command
    from aiogram import F

    # Команды
    dp.message(Command("admin"))(cmd_admin)
    dp.message(Command("stats"))(cmd_stats)
    dp.message(Command("user"))(cmd_user)
    dp.message(Command("promo"))(cmd_promo)
    dp.message(Command("set_channel"))(cmd_set_channel)
    dp.message(Command("set_trial_days"))(cmd_set_trial_days)

    # Callbacks
    dp.callback_query(F.data == "admin_stats")(show_admin_stats)
    dp.callback_query(F.data == "admin_users")(show_users_list)
    dp.callback_query(F.data == "admin_mailing")(show_mailing_form)
    dp.callback_query(F.data == "admin_promocodes")(show_promocodes_list)
    dp.callback_query(F.data == "admin_settings")(show_settings)
    dp.callback_query(F.data == "back:main")(cb_back_main)

    # Кнопки админ-меню
    dp.message(F.text == "📊 Статистика")(cmd_stats)
    dp.message(F.text == "👥 Пользователи")(show_users_list_from_menu)
    dp.message(F.text == "📩 Рассылка")(show_mailing_from_menu)
    dp.message(F.text == "🎁 Промокоды")(show_promocodes_from_menu)
    dp.message(F.text == "⚙️ Настройки")(show_settings_from_menu)
    dp.message(F.text == "🔙 Главное меню")(cmd_admin)

    # Рассылка (ловим все сообщения от админов после команды /broadcast)
    # В реальном проекте нужно использовать FSM


# ── Menu button handlers ──────────────────────────────────────────────────────

async def show_users_list_from_menu(message: Message):
    """Показать список пользователей из меню."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    users = db.get_all_users()
    text = "👥 <b>Пользователи</b>\n\n"

    for user in users[:50]:
        status = "✅" if user["active"] else "❌"
        username = user["username"] or f"tg{user['telegram_id']}"
        text += f"{status} <code>{user['telegram_id']}</code> — @{username}\n"

    if len(users) > 50:
        text += f"\n... и ещё {len(users) - 50} пользователей"

    await message.answer(text, parse_mode=ParseMode.HTML)


async def show_mailing_from_menu(message: Message):
    """Рассылка из меню."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    await message.answer(
        "📩 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем активным пользователям.\n\n"
        "⚠️ Будет отправлено всем активным пользователям!"
    )


async def show_promocodes_from_menu(message: Message):
    """Промокоды из меню."""
    if message.from_user.id not in config.ADMIN_IDS:
        return
    
    promo_codes = db.get_all_promo_codes()

    if not promo_codes:
        text = "🎁 Промокоды не созданы"
    else:
        text = "🎁 <b>Промокоды</b>\n\n"
        for pc in promo_codes:
            status = "✅" if pc["active"] else "❌"
            uses = f"{pc['used_count']}/{pc['max_uses']}" if pc['max_uses'] else f"{pc['used_count']}/∞"
            text += f"{status} <code>{pc['code']}</code> — +{pc['bonus_days']} дн. ({uses})\n"

    text += "\n\nСоздать: /promo create CODE DAYS [MAX_USES]"
    await message.answer(text, parse_mode=ParseMode.HTML)


async def show_settings_from_menu(message: Message):
    """Настройки из меню."""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    channel = db.get_channel_username()
    trial_days = db.get_trial_days()

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"📢 Канал: <code>{channel}</code>\n"
        f"🎁 Триал: <code>{trial_days} дн.</code>\n\n"
        "Изменить:\n"
        "/set_channel @username\n"
        "/set_trial_days N"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)
