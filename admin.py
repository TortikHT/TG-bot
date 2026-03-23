# admin.py
# Назначение: все команды администратора
# Импортируется main.py

import logging
from datetime import datetime
from typing import Dict, List

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    ADMIN_ID, STATUS_WAITING_PAYMENT,
    STATUS_PAID, STATUS_WAITING_FILE,
    STATUS_DONE, STATUS_CANCELLED,
)
from models import Order, UserStats
from storage import (
    persist_orders, persist_stats, persist_blocked
)
from services import (
    is_admin, get_total_revenue,
    format_order, format_order_short,
    update_stats_on_complete
)
from menu import main_menu

logger = logging.getLogger(__name__)


async def admin_orders(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order]
):
    """Показывает все заказы."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    if not orders:
        return await update.message.reply_text("📭 Заказов пока нет.")

    active = [o for o in orders if o.status not in [STATUS_DONE, STATUS_CANCELLED]]
    done = [o for o in orders if o.status == STATUS_DONE]
    cancelled = [o for o in orders if o.status == STATUS_CANCELLED]

    msg = (
        f"📦 Все заказы:\n\n"
        f"📊 Всего: {len(orders)}\n"
        f"🔄 Активных: {len(active)}\n"
        f"✅ Завершённых: {len(done)}\n"
        f"❌ Отменённых: {len(cancelled)}\n"
        f"💰 Выручка: {get_total_revenue(orders)} ₽\n\n"
        + "─" * 25 + "\n\n"
    )
    for o in orders:
        msg += format_order_short(o) + "\n\n"

    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i + 4000])


async def admin_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    user_stats: Dict[int, UserStats]
):
    """Статистика бота для администратора."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")

    total = len(orders)
    waiting_payment = len([o for o in orders if o.status == STATUS_WAITING_PAYMENT])
    paid = len([o for o in orders if o.status == STATUS_PAID])
    in_progress = len([o for o in orders if o.status == STATUS_WAITING_FILE])
    done = len([o for o in orders if o.status == STATUS_DONE])
    cancelled = len([o for o in orders if o.status == STATUS_CANCELLED])
    revenue = get_total_revenue(orders)
    total_slides = sum(o.slides for o in orders if o.status == STATUS_DONE)

    msg = (
        "📊 Статистика бота:\n\n"
        f"📦 Всего заказов: {total}\n"
        f"💳 Ожидают оплаты: {waiting_payment}\n"
        f"✅ Оплачено: {paid}\n"
        f"🔄 В работе: {in_progress}\n"
        f"🎉 Завершено: {done}\n"
        f"❌ Отменено: {cancelled}\n\n"
        f"💰 Общая выручка: {revenue} ₽\n"
        f"📊 Слайдов сделано: {total_slides}\n"
        f"👥 Пользователей: {len(user_stats)}\n"
    )
    await update.message.reply_text(msg)


async def admin_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order]
):
    """Показывает заказы, ожидающие оплаты."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")

    pending = [o for o in orders if o.status == STATUS_WAITING_PAYMENT]
    if not pending:
        return await update.message.reply_text("✅ Нет заказов ожидающих оплаты.")

    msg = f"💳 Ожидают оплаты ({len(pending)} шт.):\n\n"
    for o in pending:
        msg += (
            f"{format_order(o)}\n\n"
            f"✅ Подтвердить: /confirm {o.id}\n"
            f"❌ Отклонить: /reject {o.id}\n\n"
            + "─" * 25 + "\n\n"
        )
    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i + 4000])


async def admin_paid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order]
):
    """Показывает оплаченные заказы в работе."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")

    paid_orders = [o for o in orders if o.status == STATUS_PAID]
    if not paid_orders:
        return await update.message.reply_text("📭 Нет оплаченных заказов в работе.")

    msg = f"✅ Оплаченные заказы ({len(paid_orders)} шт.):\n\n"
    for o in paid_orders:
        msg += (
            f"{format_order(o)}\n\n"
            f"📎 Отправить файл: /send {o.id}\n\n"
            + "─" * 25 + "\n\n"
        )
    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i + 4000])


async def confirm_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order]
):
    """Подтверждает оплату заказа."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /confirm <id>")

    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")
    if order.status != STATUS_WAITING_PAYMENT:
        return await update.message.reply_text(
            f"❌ Заказ #{order_id} не ожидает оплаты.\n"
            f"Текущий статус: {order.status}"
        )

    order.status = STATUS_PAID
    order.paid_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    persist_orders(orders)

    await update.message.reply_text(
        f"✅ Оплата заказа #{order_id} подтверждена!\n\n"
        f"📎 Отправить файл: /send {order_id}"
    )
    await context.bot.send_message(
        order.user_id,
        f"✅ Оплата подтверждена!\n\n"
        f"📋 Заказ #{order.id} принят в работу.\n"
        f"📌 Тема: {order.topic}\n"
        f"📊 Слайдов: {order.slides}\n\n"
        f"Скоро пришлю готовую презентацию! 🎉"
    )


async def reject_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order]
):
    """Отклоняет оплату заказа."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /reject <id>")

    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")

    order.status = "оплата_отклонена"
    persist_orders(orders)

    await update.message.reply_text(f"❌ Оплата заказа #{order_id} отклонена.")
    await context.bot.send_message(
        order.user_id,
        f"❌ Оплата по заказу #{order.id} не подтверждена.\n\n"
        "Проверь перевод и реквизиты, затем попробуй снова "
        "или напиши администратору."
    )

# admin.py (продолжение)

async def send_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    admin_upload: Dict[int, int]
):
    """Инициирует отправку файла клиенту."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /send <id>")

    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")
    if order.status == STATUS_CANCELLED:
        return await update.message.reply_text(f"❌ Заказ #{order_id} отменён!")
    if order.status == STATUS_DONE:
        return await update.message.reply_text(f"✅ Заказ #{order_id} уже завершён!")
    if order.status == STATUS_WAITING_PAYMENT:
        return await update.message.reply_text(
            f"⏳ Заказ #{order_id} ещё не оплачен!\n"
            f"Сначала: /confirm {order_id}"
        )

    admin_upload[update.effective_user.id] = order_id
    order.status = STATUS_WAITING_FILE
    persist_orders(orders)

    await update.message.reply_text(
        f"📎 Пришли файл для заказа #{order_id}\n\n"
        f"📌 Тема: {order.topic}\n"
        f"📊 Слайдов: {order.slides}\n"
        f"💰 Сумма: {order.final} ₽\n"
        f"👤 Пользователь: @{order.username}\n\n"
        "Форматы: PDF или PPTX"
    )


async def handle_doc(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    user_stats: Dict[int, UserStats],
    admin_upload: Dict[int, int]
):
    """Обрабатывает документ от админа и отправляет клиенту."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    order_id = admin_upload.get(user_id)
    if not order_id:
        return await update.message.reply_text(
            "❌ Сначала выбери заказ через /send <id>"
        )

    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        admin_upload.pop(user_id, None)
        return await update.message.reply_text("❌ Заказ не найден.")

    # Отправляем файл клиенту
    await context.bot.send_document(
        chat_id=order.user_id,
        document=update.message.document.file_id,
        caption=(
            f"✅ Твоя презентация готова!\n\n"
            f"📋 ID заказа: {order.id}\n"
            f"📌 Тема: {order.topic}\n"
            f"📊 Слайдов: {order.slides}\n"
            f"💰 Оплачено: {order.final} ₽\n\n"
            "Спасибо за заказ! 🎉\n"
            "Буду рад видеть тебя снова! 😊"
        )
    )

    # Завершаем заказ
    order.status = STATUS_DONE
    order.completed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    persist_orders(orders)
    update_stats_on_complete(order, user_stats)
    persist_stats(user_stats)
    admin_upload.pop(user_id, None)

    await update.message.reply_text(
        f"✅ Файл отправлен!\n"
        f"Заказ #{order.id} закрыт. ✅\n\n"
        f"👤 Клиент: @{order.username}\n"
        f"💰 Сумма: {order.final} ₽"
    )


async def admin_block(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    blocked_users: List[int]
):
    """Блокирует пользователя."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /block <user_id>")

    if target_id == ADMIN_ID:
        return await update.message.reply_text("❌ Нельзя заблокировать администратора!")
    if target_id in blocked_users:
        return await update.message.reply_text(
            f"⚠️ Пользователь {target_id} уже заблокирован."
        )

    blocked_users.append(target_id)
    persist_blocked(blocked_users)
    await update.message.reply_text(f"✅ Пользователь {target_id} заблокирован.")


async def admin_unblock(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    blocked_users: List[int]
):
    """Разблокирует пользователя."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /unblock <user_id>")

    if target_id not in blocked_users:
        return await update.message.reply_text(
            f"⚠️ Пользователь {target_id} не заблокирован."
        )

    blocked_users.remove(target_id)
    persist_blocked(blocked_users)
    await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован.")


async def admin_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    blocked_users: List[int]
):
    """Рассылка сообщения всем пользователям."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    if not context.args:
        return await update.message.reply_text("❌ Используй: /broadcast <текст>")

    message = " ".join(context.args)
    unique_users = list(set(o.user_id for o in orders))

    if not unique_users:
        return await update.message.reply_text("📭 Нет пользователей для рассылки.")

    sent = 0
    failed = 0
    for uid in unique_users:
        if uid in blocked_users:
            continue
        try:
            await context.bot.send_message(
                uid,
                f"📢 Сообщение от администратора:\n\n{message}"
            )
            sent += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки для {uid}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ Рассылка завершена!\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}"
    )


async def admin_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Справка по командам администратора."""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")

    text = (
        "🛠 Команды администратора:\n\n"
        "📦 Заказы:\n"
        "/orders — все заказы\n"
        "/pending — ожидают оплаты\n"
        "/paid — оплаченные в работе\n"
        "/stats — статистика бота\n\n"
        "💳 Оплата:\n"
        "/confirm <id> — подтвердить оплату\n"
        "/reject <id> — отклонить оплату\n\n"
        "📎 Отправка:\n"
        "/send <id> — отправить файл клиенту\n\n"
        "👥 Пользователи:\n"
        "/block <user_id> — заблокировать\n"
        "/unblock <user_id> — разблокировать\n"
        "/broadcast <текст> — рассылка всем\n"
    )
    await update.message.reply_text(text)