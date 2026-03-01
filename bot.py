"""
Main bot entry point.
Runs aiogram bot + aiohttp webhook server in the same asyncio event loop.
"""

import asyncio
import json
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiohttp import web

import config
import database as db
from xui_api import xui
from keyboards import (
    main_menu,
    plans_keyboard,
    payment_method_keyboard,
    confirm_paid_keyboard,
    support_keyboard,
    subscribe_keyboard,
    referral_keyboard,
    admin_keyboard,
)
from logger import get_logger
from middlewares import SubscriptionMiddleware, set_bot as middleware_set_bot
import payments.cryptobot as cryptobot
import payments.lava as lava
import payments.paymaster as paymaster
import payments.yoomoney as yoomoney
from webhook import create_app, set_bot as webhook_set_bot
import scheduler
from admin import register_admin_handlers

log = get_logger("bot")

# ── State tracking (simple in-memory, per user) ───────────────────────────────
# { telegram_id: {"plan_key": "30", "awaiting_payment": True} }
user_state: dict[int, dict] = {}


# ── Bot & Dispatcher ─────────────────────────────────────────────────────────

bot: Bot = None
dp = Dispatcher()

# Middleware будут зарегистрированы после создания bot в main()


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    telegram_id = message.from_user.id
    username = message.from_user.username

    # Проверяем реферера (если есть в start parameter)
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        try:
            referrer_id = int(message.text.split()[1])
            if referrer_id != telegram_id:  # Не сам на себя
                existing_referrer = db.get_referrer_id(telegram_id)
                if not existing_referrer:  # Ещё нет реферера
                    db.add_referral(referrer_id, telegram_id)
                    log.info(f"Referral added: referrer={referrer_id} referred={telegram_id}")
        except (ValueError, IndexError):
            pass

    user = db.register_user(telegram_id, username)

    # Проверяем подписку через БД
    is_subscribed = db.is_user_subscribed(telegram_id)

    # Формируем сообщение для главного меню
    greeting = _get_main_menu_message(user, message, is_subscribed)

    # Админ-меню для админов
    if telegram_id in config.ADMIN_IDS:
        await message.answer(greeting, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(greeting, reply_markup=main_menu(), parse_mode=ParseMode.HTML)

    log.info(f"User /start: tgid={telegram_id} username={username}")


# ── /menu ─────────────────────────────────────────────────────────────────────

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    """Команда /menu - главное меню с информацией о статусе."""
    telegram_id = message.from_user.id
    user = db.get_user(telegram_id)
    
    # Проверяем подписку через БД
    is_subscribed = db.is_user_subscribed(telegram_id)
    
    greeting = _get_main_menu_message(user, message, is_subscribed)
    
    if telegram_id in config.ADMIN_IDS:
        await message.answer(greeting, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(greeting, reply_markup=main_menu(), parse_mode=ParseMode.HTML)
    
    log.info(f"User /menu: tgid={telegram_id}")


# ── Кнопка "☰ Меню" ───────────────────────────────────────────────────────────

@dp.message(F.text == "☰ Меню")
async def show_main_menu(message: Message):
    """Кнопка 'Меню' - показывает главное меню с информацией."""
    telegram_id = message.from_user.id
    user = db.get_user(telegram_id)
    
    # Проверяем подписку через БД
    is_subscribed = db.is_user_subscribed(telegram_id)
    
    greeting = _get_main_menu_message(user, message, is_subscribed)
    
    if telegram_id in config.ADMIN_IDS:
        await message.answer(greeting, reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(greeting, reply_markup=main_menu(), parse_mode=ParseMode.HTML)


# ── Check subscription callback ───────────────────────────────────────────────

@dp.callback_query(F.data == "check_subscribe")
async def cb_check_subscribe(call: CallbackQuery):
    """Проверка подписки после нажатия кнопки."""
    telegram_id = call.from_user.id

    try:
        member = await bot.get_chat_member(config.CHANNEL_ID, telegram_id)
        if member.status in ["member", "administrator", "creator"]:
            db.set_user_subscribed(telegram_id, True)
            await call.answer("✅ Спасибо за подписку!", show_alert=True)
            await call.message.edit_text("✅ Подписка подтверждена!\n\nТеперь вы можете пользоваться всеми функциями бота.")
            return
    except Exception as e:
        log.warning(f"Subscription check error: {e}")

    await call.answer("❌ Вы ещё не подписались. Пожалуйста, подпишитесь на канал.", show_alert=True)


# ── Тарифы ────────────────────────────────────────────────────────────────────

@dp.message(F.text == "💳 Тарифы и оплата")
async def show_plans(message: Message):
    log.info(f"show_plans called: tg={message.from_user.id} username={message.from_user.username}")
    lines = ["<b>💳 Тарифы и оплата:</b>\n"]
    for key, plan in config.PLANS.items():
        if key == "free":
            lines.append(f"🎁 {plan['label']} — 0 ₽")
        else:
            lines.append(f"• {plan['label']}")
    lines.append("\nВыберите тариф:")
    log.info(f"Sending plans keyboard to: tg={message.from_user.id}")
    await message.answer("\n".join(lines), reply_markup=plans_keyboard(), parse_mode=ParseMode.HTML)


# ── /pay ──────────────────────────────────────────────────────────────────────

@dp.message(Command("pay"))
async def cmd_pay(message: Message):
    """Команда /pay - открыть тарифы и оплату."""
    await show_plans(message)


@dp.callback_query(F.data.startswith("plan:"))
async def cb_plan_selected(call: CallbackQuery):
    log.info(f"cb_plan_selected called: tg={call.from_user.id} data={call.data}")
    plan_key = call.data.split(":")[1]
    plan = config.PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф")
        return

    user_state[call.from_user.id] = {"plan_key": plan_key, "awaiting_payment": False}
    
    if plan_key == "free":
        await call.message.edit_text(
            f"<b>🎁 Бесплатный тариф</b>\n\n"
            f"Вы получите 30 дней доступа бесплатно!\n\n"
            f"⚠️ Акция доступна только один раз.\n\n"
            f"Активировать?",
            reply_markup=payment_method_keyboard(plan_key),
            parse_mode=ParseMode.HTML,
        )
    else:
        await call.message.edit_text(
            f"<b>Тариф: {plan['label']}</b>\n\n"
            f"Выберите способ оплаты:",
            reply_markup=payment_method_keyboard(plan_key),
            parse_mode=ParseMode.HTML,
        )
    await call.answer()


@dp.callback_query(F.data == "back:plans")
async def cb_back_plans(call: CallbackQuery):
    await call.message.edit_text("Выберите тариф:", reply_markup=plans_keyboard())
    await call.answer()


# ── Бесплатный тариф ──────────────────────────────────────────────────────────

@dp.message(F.text == "🎁 Бесплатно")
async def free_tariff(message: Message):
    telegram_id = message.from_user.id
    user = db.get_user(telegram_id)

    # Проверяем, не использовал ли уже триал
    if db.has_user_used_trial(telegram_id):
        await message.answer(
            "❌ Вы уже использовали бесплатный период.\n\n"
            "Выберите платный тариф или пригласите друзей!"
        )
        return
    
    # Проверяем, есть ли уже активная подписка
    if user and user["active"]:
        await message.answer(
            "✅ У вас уже есть активная подписка.\n\n"
            "Бесплатный период можно использовать только один раз."
        )
        return
    
    await show_plans(message)


@dp.callback_query(F.data.startswith("pay:"))
async def cb_pay_method(call: CallbackQuery):
    _, method, plan_key = call.data.split(":")
    plan = config.PLANS.get(plan_key)
    if not plan:
        await call.answer("Неверный тариф")
        return

    telegram_id = call.from_user.id
    user = db.get_user(telegram_id)
    if not user:
        db.register_user(telegram_id, call.from_user.username)

    # Бесплатный тариф
    if method == "free" or plan_key == "free":
        await _activate_free(call, plan, plan_key)
        return

    # Разрешаем продление даже если подписка активна
    # if user and user["active"] == 1:
    #     await call.answer("✅ У вас уже активная подписка!", show_alert=True)
    #     return

    if method == "crypto":
        await _pay_crypto(call, plan, plan_key)
    elif method == "paymaster":
        await _pay_paymaster(call, plan, plan_key)
    elif method == "lava":
        await _pay_lava(call, plan, plan_key)
    elif method == "yoomoney":
        await _pay_yoomoney(call, plan, plan_key)
    elif method == "manual":
        await _pay_manual(call, plan, plan_key)


async def _activate_free(call: CallbackQuery, plan: dict, plan_key: str):
    """Активация бесплатного тарифа."""
    telegram_id = call.from_user.id
    
    # Проверяем подписку
    if config.CHANNEL_ID and config.CHANNEL_ID != 0:
        try:
            member = await bot.get_chat_member(config.CHANNEL_ID, telegram_id)
            if member.status not in ["member", "administrator", "creator"]:
                await call.answer("❌ Сначала подпишитесь на канал!", show_alert=True)
                return
        except Exception:
            await call.answer("❌ Ошибка проверки подписки", show_alert=True)
            return
    
    # Проверяем, не использовал ли уже триал
    if db.has_user_used_trial(telegram_id):
        await call.answer("❌ Вы уже использовали бесплатный период!", show_alert=True)
        return
    
    user = db.get_user(telegram_id)
    client_uuid = user["uuid"] or xui.generate_uuid()
    email = f"tg{telegram_id}"
    payment_id = f"free_{telegram_id}_{int(datetime.utcnow().timestamp())}"
    
    # Добавляем в 3x-ui
    if not xui.client_exists(client_uuid):
        success = xui.add_client(client_uuid, email, plan["days"])
        if not success:
            await call.message.edit_text("❌ Ошибка активации. Попробуйте позже.")
            await call.answer()
            return
    
    # Активируем пользователя
    db.activate_user(telegram_id, client_uuid, plan["days"], payment_id)
    db.set_trial_used(telegram_id)
    db.log_payment(payment_id, telegram_id, 0, "success", "free")
    
    # Рефереру начисляем бонус
    referrer_id = db.get_referrer_id(telegram_id)
    if referrer_id:
        referrer_bonus = config.REFERRAL_BONUS_DAYS
        db.activate_user(referrer_id, db.get_user(referrer_id)["uuid"] or xui.generate_uuid(), referrer_bonus, f"ref_bonus_{telegram_id}")
        log.info(f"Referral bonus: referrer={referrer_id} days={referrer_bonus}")

    conn_link = xui.get_client_config_link(client_uuid, f"VPN_{telegram_id}")

    # Сообщение 1: Информация об активации
    text = (
        f"✅ <b>Бесплатный тариф активирован!</b>\n\n"
        f"🎁 Вы получили 30 дней доступа.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📲 <b>Приложения для подключения:</b>\n\n"
        f"<b>Android:</b>\n"
        f"• <a href='https://github.com/2dust/v2rayNG/releases'>v2rayNG</a> (GitHub)\n"
        f"• <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box'>V2Box</a> (Google Play)\n"
        f"• <a href='https://play.google.com/store/apps/details?id=app.hiddify.com'>Hiddify</a> (Google Play)\n\n"
        f"<b>iOS:</b>\n"
        f"• <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a> (App Store)\n"
        f"• <a href='https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532'>Hiddify</a> (App Store)\n\n"
        f"<b>Windows / Mac / Linux:</b>\n"
        f"• <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a> (GitHub)\n"
        f"• <a href='https://github.com/2dust/v2rayN/releases'>v2rayN</a> (GitHub, Windows)"
    )

    await call.message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
    # Сообщение 2: Ключ подключения (отдельным сообщением, только ключ для удобного копирования)
    if conn_link:
        await call.message.answer(conn_link)
    
    await call.answer()
    log.info(f"Free tariff activated: tgid={telegram_id}")


async def _pay_crypto(call: CallbackQuery, plan: dict, plan_key: str):
    if not config.CRYPTOBOT_TOKEN:
        await call.answer("Крипто-оплата не настроена", show_alert=True)
        return

    telegram_id = call.from_user.id
    payload = f"tgid:{telegram_id}:plan:{plan_key}"
    invoice = cryptobot.create_invoice(
        amount=plan["price_usdt"],
        asset="USDT",
        description=plan["label"],
        payload=payload,
    )
    if not invoice:
        await call.message.edit_text("❌ Ошибка создания счёта. Попробуйте позже.")
        await call.answer()
        return

    await call.message.edit_text(
        f"🪙 <b>Оплата криптовалютой</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Сумма: <b>{plan['price_usdt']} USDT</b>\n\n"
        f"Нажмите кнопку ниже для оплаты через CryptoBot.\n"
        f"После оплаты доступ выдаётся <b>автоматически</b>.",
        reply_markup=_invoice_kb(invoice["pay_url"]),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()
    log.info(f"CryptoBot invoice shown: tgid={telegram_id} plan={plan_key}")


async def _pay_lava(call: CallbackQuery, plan: dict, plan_key: str):
    if not config.LAVA_SHOP_ID:
        await call.answer("Оплата через Lava не настроена", show_alert=True)
        return

    telegram_id = call.from_user.id
    order_id = lava.make_order_id(telegram_id, plan_key)
    invoice = lava.create_invoice(
        amount=plan["price_rub"],
        order_id=order_id,
        comment=plan["label"],
        hook_url=f"http://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/webhook/lava",
    )
    if not invoice:
        await call.message.edit_text("❌ Ошибка создания счёта Lava. Попробуйте позже.")
        await call.answer()
        return

    pay_url = invoice.get("url") or invoice.get("payUrl") or ""
    await call.message.edit_text(
        f"💳 <b>Оплата картой / СБП (Lava)</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Сумма: <b>{plan['price_rub']} ₽</b>\n\n"
        f"Нажмите кнопку ниже для оплаты.\n"
        f"Доступ выдаётся <b>автоматически</b> после оплаты.",
        reply_markup=_invoice_kb(pay_url),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()
    log.info(f"Lava invoice shown: tgid={telegram_id} plan={plan_key} order_id={order_id}")


async def _pay_paymaster(call: CallbackQuery, plan: dict, plan_key: str):
    if not config.PAYMASTER_TOKEN:
        await call.answer("Оплата через Paymaster не настроена", show_alert=True)
        return

    telegram_id = call.from_user.id
    order_id = paymaster.make_order_id(telegram_id, plan_key)
    invoice = paymaster.create_invoice(
        amount=plan["price_rub"],
        order_id=order_id,
        comment=plan["label"],
        hook_url=f"http://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/webhook/paymaster",
    )
    if not invoice:
        await call.message.edit_text("❌ Ошибка создания счёта Paymaster. Попробуйте позже.")
        await call.answer()
        return

    pay_url = invoice.get("pay_url", "")
    is_test = "TEST" in config.PAYMASTER_TOKEN
    test_label = " [ТЕСТ]" if is_test else ""

    await call.message.edit_text(
        f"💳 <b>Оплата картой / СБП (Paymaster){test_label}</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Сумма: <b>{plan['price_rub']} ₽</b>\n\n"
        f"Нажмите кнопку ниже для оплаты.\n"
        f"Доступ выдаётся <b>автоматически</b> после оплаты.",
        reply_markup=_invoice_kb(pay_url),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()
    log.info(f"Paymaster invoice shown: tgid={telegram_id} plan={plan_key} order_id={order_id} test={is_test}")


async def _pay_manual(call: CallbackQuery, plan: dict, plan_key: str):
    """Manual bank transfer — user clicks 'I paid' and waits for admin/webhook confirmation."""
    user_state[call.from_user.id] = {"plan_key": plan_key, "awaiting_payment": True}
    await call.message.edit_text(
        f"💳 <b>Перевод на карту</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Сумма: <b>{plan['price_rub']} ₽</b>\n\n"
        f"Реквизиты для оплаты:\n"
        f"🏦 <b>Карта: <code>{config.MANUAL_PAYMENT_PHONE}</code></b>\n\n"
        f"💳 <b>ЮMoney:</b>\n"
        f"<code>{config.YOUMONEY_URL}</code>\n\n"
        f"1. Переведите сумму по карте или через ЮMoney\n"
        f"2. Нажмите кнопку «✅ Я оплатил»\n"
        f"3. Доступ будет выдан в течение нескольких минут\n\n"
        f"⚠️ В комментарии к платежу укажите: <code>{call.from_user.id}</code>",
        reply_markup=confirm_paid_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


async def _pay_yoomoney(call: CallbackQuery, plan: dict, plan_key: str):
    """YooMoney payment — cards + SBP."""
    if not config.YOUMONEY_API_KEY:
        await call.answer("Оплата через ЮMoney не настроена", show_alert=True)
        return

    telegram_id = call.from_user.id
    order_id = yoomoney.make_order_id(telegram_id, plan_key)
    invoice = yoomoney.create_invoice(
        amount=plan["price_rub"],
        order_id=order_id,
        comment=plan["label"],
        webhook_url=f"http://{config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}/webhook/yoomoney",
    )
    if not invoice:
        await call.message.edit_text("❌ Ошибка создания счёта ЮMoney. Попробуйте позже.")
        await call.answer()
        return

    pay_url = invoice.get("pay_url", "")
    await call.message.edit_text(
        f"💳 <b>Оплата через ЮMoney</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Сумма: <b>{plan['price_rub']} ₽</b>\n\n"
        f"Нажмите кнопку ниже для оплаты.\n"
        f"Доступ выдаётся <b>автоматически</b> после оплаты.",
        reply_markup=_invoice_kb(pay_url),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()
    log.info(f"YooMoney invoice shown: tgid={telegram_id} plan={plan_key} order_id={order_id}")


@dp.callback_query(F.data == "paid:confirm")
async def cb_paid_confirm(call: CallbackQuery):
    telegram_id = call.from_user.id
    state = user_state.get(telegram_id, {})
    plan_key = state.get("plan_key", "30")
    plan = config.PLANS.get(plan_key)

    await call.message.edit_text(
        "⏳ <b>Ваша заявка принята!</b>\n\n"
        "Ожидайте подтверждения платежа.\n"
        "Обычно это занимает 1-5 минут.\n\n"
        "При вопросах — обратитесь в поддержку."
    )
    await call.answer()
    
    # Уведомляем админа
    username = call.from_user.username or f"tg{telegram_id}"
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Новая оплата!</b>\n\n"
                f"👤 Пользователь: @{username} (<code>{telegram_id}</code>)\n"
                f"📦 Тариф: {plan['label']}\n"
                f"💵 Сумма: {plan['price_rub']} ₽\n\n"
                f"🏦 Перевод на карту: {config.MANUAL_PAYMENT_PHONE}\n"
                f"💳 ЮMoney: {config.YOUMONEY_URL}\n\n"
                f"Для выдачи доступа:\n"
                f"<code>/grant {telegram_id} {plan_key} manual_{telegram_id}_{int(datetime.utcnow().timestamp())}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.error(f"Failed to notify admin {admin_id}: {e}")
    
    log.info(f"User confirmed manual payment: tgid={telegram_id} plan={plan_key}")


# ── Рефералы ──────────────────────────────────────────────────────────────────

@dp.message(F.text == "👥 Рефералы")
async def show_referrals(message: Message):
    telegram_id = message.from_user.id
    referrals_count = db.get_referrals_count(telegram_id)
    referrals_list = db.get_referrals_list(telegram_id)

    # Генерируем реферальную ссылку
    referral_link = f"https://t.me/{(await bot.get_me()).username}?start={telegram_id}"

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте бонусы!\n\n"
        f"🎁 Ваша ссылка:\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 Статистика:\n"
        f"• Приглашено: <b>{referrals_count}</b>\n"
        f"• Бонус за каждого: <b>{config.REFERRAL_BONUS_DAYS} дн.</b>\n\n"
    )
    
    if referrals_list:
        text += "<b>Ваши рефералы:</b>\n"
        for ref in referrals_list[:10]:
            username = ref["username"] or f"tg{ref['telegram_id']}"
            text += f"• @{username} ({ref['referred_at'][:10]})\n"
        if len(referrals_list) > 10:
            text += f"... и ещё {len(referrals_list) - 10}\n"
    
    await message.answer(text, reply_markup=referral_keyboard(referral_link), parse_mode=ParseMode.HTML)


# ── Статус ────────────────────────────────────────────────────────────────────

@dp.message(F.text == "📊 Статус")
async def show_status(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Вы не зарегистрированы. Нажмите /start")
        return

    if user["active"]:
        sub_end = user["subscription_end"] or "?"
        days_left = _days_left(sub_end)
        text = (
            f"✅ <b>Подписка активна</b>\n\n"
            f"📅 До: <b>{sub_end}</b>\n"
            f"⏳ Осталось: <b>{days_left} дн.</b>"
        )
    else:
        text = "❌ <b>Подписка неактивна</b>\n\nНажмите 💳 Тарифы и оплата чтобы получить доступ."

    await message.answer(text, parse_mode=ParseMode.HTML)


# ── /status ───────────────────────────────────────────────────────────────────

@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Команда /status - показать статус подписки."""
    await show_status(message)


# ── Мой ключ ──────────────────────────────────────────────────────────────────

@dp.message(F.text == "🔑 Мой ключ")
async def show_key(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user["active"]:
        await message.answer("❌ У вас нет активной подписки.\nНажмите 💳 Тарифы и оплата.")
        return

    client_uuid = user["uuid"]
    if not client_uuid:
        await message.answer("⚠️ UUID не найден. Обратитесь в поддержку.")
        return

    conn_link = xui.get_client_config_link(client_uuid, f"VPN_{message.from_user.id}")
    
    # Сообщение 1: Приложения для подключения
    text = (
        f"📲 <b>Приложения для подключения:</b>\n\n"
        f"<b>Android:</b>\n"
        f"• <a href='https://github.com/2dust/v2rayNG/releases'>v2rayNG</a> (GitHub)\n"
        f"• <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box'>V2Box</a> (Google Play)\n"
        f"• <a href='https://play.google.com/store/apps/details?id=app.hiddify.com'>Hiddify</a> (Google Play)\n\n"
        f"<b>iOS:</b>\n"
        f"• <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a> (App Store)\n"
        f"• <a href='https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532'>Hiddify</a> (App Store)\n\n"
        f"<b>Windows / Mac / Linux:</b>\n"
        f"• <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a> (GitHub)\n"
        f"• <a href='https://github.com/2dust/v2rayN/releases'>v2rayN</a> (GitHub, Windows)\n"
        f"• <a href='https://github.com/MatsuriDayo/nekoray/releases'>Nekoray</a> (GitHub)"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    
    # Сообщение 2: Ключ подключения (отдельным сообщением, только ключ для удобного копирования)
    if conn_link:
        await message.answer(conn_link)
    else:
        await message.answer(
            f"🔑 Ваш UUID: {client_uuid}\n\nНастройте клиент вручную или обратитесь в поддержку."
        )


# ── /key ──────────────────────────────────────────────────────────────────────

@dp.message(Command("key"))
async def cmd_key(message: Message):
    """Команда /key - показать ключ подключения."""
    await show_key(message)


# ── Статистика трафика ────────────────────────────────────────────────────────

@dp.message(F.text == "📊 Статистика")
async def show_traffic_stats(message: Message):
    telegram_id = message.from_user.id
    user = db.get_user(telegram_id)

    if not user or not user["active"]:
        await message.answer("❌ У вас нет активной подписки.")
        return
    
    client_uuid = user["uuid"]
    if not client_uuid:
        await message.answer("⚠️ Данные не найдены.")
        return
    
    # Получаем статистику из XUI
    traffic = xui.get_client_traffic(client_uuid)
    
    if not traffic:
        await message.answer("⚠️ Не удалось получить статистику.\nПопробуйте позже.")
        return
    
    # Форматируем вывод
    upload_gb = traffic["upload_gb"]
    download_gb = traffic["download_gb"]
    total_gb = traffic["total_gb"]
    limit_gb = traffic["limit_gb"]
    remaining_gb = traffic["remaining_gb"]
    
    # Прогрузка в %
    if isinstance(limit_gb, (int, float)) and limit_gb > 0:
        usage_percent = (total_gb / limit_gb) * 100
        progress_bar = _progress_bar(usage_percent)
    else:
        usage_percent = 0
        progress_bar = "♾️ Безлимит"
    
    text = (
        f"📊 <b>Статистика трафика</b>\n\n"
        f"📤 Загружено: <b>{upload_gb:.2f} ГБ</b>\n"
        f"📥 Скачано: <b>{download_gb:.2f} ГБ</b>\n"
        f"📈 Всего: <b>{total_gb:.2f} ГБ</b>\n\n"
        f"📉 Лимит: <b>{limit_gb} ГБ</b>\n"
        f"⏳ Осталось: <b>{remaining_gb:.2f} ГБ</b>\n\n"
        f"{progress_bar}"
    )
    
    await message.answer(text, parse_mode=ParseMode.HTML)


def _progress_bar(percent: float) -> str:
    """Создать визуальный прогресс-бар."""
    filled = int(percent / 5)
    bar = "█" * filled + "░" * (20 - filled)
    return f"<code>[{bar}] {percent:.1f}%</code>"


# ── Канал ─────────────────────────────────────────────────────────────────────

@dp.message(F.text == "📢 Канал")
async def show_channel(message: Message):
    """Кнопка 'Канал' - перейти в канал."""
    channel = config.CHANNEL_USERNAME or "@shadowlink_top"
    # Отправляем сообщение с кнопкой для перехода
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Перейти в канал", url=f"https://t.me/{channel.lstrip('@')}")],
    ])
    await message.answer(
        f"📢 <b>Наш канал ShadowLink</b>\n\n"
        f"Подписывайтесь на новости и обновления:\n"
        f"{channel}\n\n"
        f"Нажмите кнопку ниже для перехода:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


# ── О сервисе ──────────────────────────────────────────────────────────────────

@dp.message(F.text == "ℹ️ О сервисе")
async def show_about(message: Message):
    """Кнопка 'О сервисе' - информация о ShadowLink."""
    channel = config.CHANNEL_USERNAME or "@shadowlink_top"
    text = (
        f"🌐 <b>ShadowLink — ваш приватный канал в свободный интернет</b>\n\n"
        f"Мы предоставляем быстрый и надёжный VPN-доступ через современные протоколы.\n\n"
        f"✔️ <b>Без логов</b> — мы не храним историю ваших подключений\n"
        f"✔️ <b>Высокая скорость</b> — оптимизированные серверы для максимальной скорости\n"
        f"✔️ <b>Работает даже при ограничениях</b> — обход блокировок провайдеров\n"
        f"✔️ <b>Подключение за 30 секунд</b> — простая настройка в любом приложении\n\n"
        f"📢 <b>Наш канал:</b> {channel}\n\n"
        f"🔒 <b>Технология:</b> VLESS + Reality — современный протокол для безопасного интернета.\n\n"
        f"<b>Выберите действие в меню:</b>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ── Поддержка ─────────────────────────────────────────────────────────────────

@dp.message(F.text == "❓ Поддержка")
async def show_support(message: Message):
    await message.answer(
        "📩 <b>Поддержка</b>\n\nЕсли у вас возникли вопросы — напишите нам:",
        reply_markup=support_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# ── /support ──────────────────────────────────────────────────────────────────

@dp.message(Command("support"))
async def cmd_support(message: Message):
    """Команда /support - показать контакты поддержки."""
    await show_support(message)


# ── Admin команды ─────────────────────────────────────────────────────────────

@dp.message(Command("grant"))
async def cmd_grant(message: Message):
    """Admin: /grant <telegram_id> <plan_key> <payment_id>"""
    if message.from_user.id not in config.ADMIN_IDS:
        return

    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Usage: /grant <telegram_id> <plan_key> <payment_id>")
        return

    _, tgid_str, plan_key, payment_id = parts
    telegram_id = int(tgid_str)
    plan = config.PLANS.get(plan_key)
    if not plan:
        await message.answer(f"Unknown plan: {plan_key}")
        return

    if db.is_payment_processed(payment_id):
        await message.answer("Payment already processed (anti-duplicate)")
        return

    user = db.get_user(telegram_id)
    if not user:
        db.register_user(telegram_id, None)
        user = db.get_user(telegram_id)

    client_uuid = user["uuid"] or xui.generate_uuid()
    email = f"tg{telegram_id}"
    xui.add_client(client_uuid, email, plan["days"])
    db.activate_user(telegram_id, client_uuid, plan["days"], payment_id)
    db.log_payment(payment_id, telegram_id, 0, "admin_grant", "admin")

    # Получаем ключ подключения
    conn_link = xui.get_client_config_link(client_uuid, f"VPN_{telegram_id}")

    # Отправляем пользователю ключ
    if conn_link:
        try:
            # Сообщение 1: Информация
            await bot.send_message(
                telegram_id,
                f"✅ <b>Оплата подтверждена! Доступ выдан.</b>\n\n"
                f"📦 Тариф: {plan['label']}\n"
                f"⏳ Действует: {plan['days']} дн.\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📲 <b>Приложения для подключения:</b>\n\n"
                f"<b>Android:</b>\n"
                f"• <a href='https://github.com/2dust/v2rayNG/releases'>v2rayNG</a> (GitHub)\n"
                f"• <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box'>V2Box</a> (Google Play)\n"
                f"• <a href='https://play.google.com/store/apps/details?id=app.hiddify.com'>Hiddify</a> (Google Play)\n\n"
                f"<b>iOS:</b>\n"
                f"• <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a> (App Store)\n"
                f"• <a href='https://apps.apple.com/us/app/hiddify-proxy-vpn/id6596777532'>Hiddify</a> (App Store)\n\n"
                f"<b>Windows / Mac / Linux:</b>\n"
                f"• <a href='https://github.com/hiddify/hiddify-next/releases'>Hiddify</a> (GitHub)\n"
                f"• <a href='https://github.com/2dust/v2rayN/releases'>v2rayN</a> (GitHub, Windows)\n"
                f"• <a href='https://github.com/MatsuriDayo/nekoray/releases'>Nekoray</a> (GitHub)",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            
            # Сообщение 2: Ключ подключения (отдельным сообщением, только ключ для удобного копирования)
            await bot.send_message(telegram_id, conn_link)
        except Exception as e:
            log.error(f"Failed to send key to user {telegram_id}: {e}")
            await bot.send_message(telegram_id, "✅ Доступ выдан! Напишите /key чтобы получить ключ.")

    await message.answer(f"✅ Granted: tgid={telegram_id} plan={plan_key}")
    log.info(f"Admin grant: tgid={telegram_id} plan={plan_key} payment_id={payment_id}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _name(message: Message) -> str:
    return message.from_user.first_name or message.from_user.username or "друг"


def _days_left(sub_end: str) -> int:
    try:
        end = date.fromisoformat(sub_end)
        delta = (end - date.today()).days
        return max(0, delta)
    except Exception:
        return 0


def _get_main_menu_message(user: dict, message: Message, is_subscribed: bool = False) -> str:
    """Формирует сообщение для главного меню с информацией о статусе и ключом."""
    telegram_id = message.from_user.id
    username = message.from_user.username or f"tg{telegram_id}"
    channel = config.CHANNEL_USERNAME or "@shadowlink_top"
    
    # Проверяем подписку через БД если не передано
    if not is_subscribed and db.is_user_subscribed(telegram_id):
        is_subscribed = True
    
    if user and user["active"]:
        sub_end = user["subscription_end"] or "?"
        days_left = _days_left(sub_end)
        sub_status = f"✅ Подписан" if is_subscribed else f"❌ Не подписан"
        
        # Получаем ключ подключения
        conn_link = ""
        client_uuid = user["uuid"] if user else None
        if client_uuid:
            from xui_api import xui
            conn_link = xui.get_client_config_link(client_uuid, f"VPN_{telegram_id}")
        
        if conn_link:
            key_text = (
                f"\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔑 <b>Ваш ключ:</b>\n"
                f"<code>{conn_link}</code>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
        else:
            key_text = "\n🔑 Ключ будет доступен после активации подписки.\n"
        
        text = (
            f"👋 <b>Добро пожаловать, {username}!</b>\n\n"
            f"🌐 <b>ShadowLink — ваш приватный канал в свободный интернет</b>\n\n"
            f"✅ <b>Подписка активна</b>\n"
            f"📅 До: <b>{sub_end}</b>\n"
            f"⏳ Осталось: <b>{days_left} дн.</b>\n\n"
            f"📢 <b>Канал:</b> {channel}\n"
            f"{sub_status}{key_text}\n"
            f"<b>Выберите действие:</b>"
        )
    else:
        sub_status = "✅ Подписан" if is_subscribed else "❌ Не подписан"
        text = (
            f"👋 <b>Добро пожаловать, {username}!</b>\n\n"
            f"🌐 <b>ShadowLink — ваш приватный канал в свободный интернет</b>\n\n"
            f"✔️ <b>Без логов</b>\n"
            f"✔️ <b>Высокая скорость</b>\n"
            f"✔️ <b>Работает даже при ограничениях</b>\n"
            f"✔️ <b>Подключение за 30 секунд</b>\n\n"
            f"🎁 <b>Акция:</b> 1 месяц бесплатно за подписку на канал!\n\n"
            f"📢 <b>Канал:</b> {channel}\n"
            f"{sub_status}\n\n"
            f"❌ <b>Подписка не активна</b>\n\n"
            f"<b>Выберите действие:</b>"
        )
    
    return text


def _invoice_kb(pay_url: str):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back:plans")],
    ])


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config.validate()
    db.init_db()

    global bot
    bot = Bot(token=config.BOT_TOKEN)

    # Inject bot into webhook, scheduler, and middlewares
    webhook_set_bot(bot)
    middleware_set_bot(bot)
    scheduler.start(bot)

    # Login to 3x-ui
    if not xui.login():
        log.warning("Initial 3x-ui login failed — will retry on first API call")

    # Register admin handlers
    register_admin_handlers(dp)

    # Register middlewares (after bot is created!)
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Start aiohttp webhook server alongside aiogram
    webhook_app = create_app()
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBHOOK_HOST, config.WEBHOOK_PORT)
    await site.start()
    log.info(f"Webhook server started on {config.WEBHOOK_HOST}:{config.WEBHOOK_PORT}")

    log.info("Bot started, polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.stop()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
