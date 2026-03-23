# services.py
# Назначение: вся бизнес-логика — расчёт цен, статистика,
#             форматирование заказов, вспомогательные функции
# Импортируется handlers.py и admin.py

from datetime import datetime, timedelta
from typing import Dict

from config import (
    PRICE_PER_SLIDE, DISCOUNT_PERCENT, DISCOUNT_FROM_SLIDES,
    URGENT_SURCHARGE_PERCENT, MINUTES_PER_5_SLIDES,
    NIGHT_START, NIGHT_END, ADMIN_ID,
    STATUS_NEW, STATUS_WAITING_PAYMENT, STATUS_PAID,
    STATUS_WAITING_FILE, STATUS_DONE,
    STATUS_CANCELLED, STATUS_PAYMENT_REJECTED,
)
from models import Order, UserStats


# ===== Расчёт цены =====

def calculate_price(slides: int, urgent: bool = False) -> dict:
    """
    Рассчитывает стоимость заказа.

    Args:
        slides: количество слайдов
        urgent: срочный заказ (наценка URGENT_SURCHARGE_PERCENT%)

    Returns:
        dict с ключами base, discount, final
    """
    base = slides * PRICE_PER_SLIDE
    discount = int(base * DISCOUNT_PERCENT // 100) if slides >= DISCOUNT_FROM_SLIDES else 0
    final = base - discount
    if urgent:
        final = int(final * (1 + URGENT_SURCHARGE_PERCENT / 100))
    return {"base": base, "discount": discount, "final": final}


# ===== Расчёт времени =====

def estimate_ready_time(slides: int) -> tuple:
    """
    Оценивает время готовности презентации.

    Returns:
        (minutes: int, ready_at: str) — минуты и время готовности
    """
    minutes = ((slides - 1) // 5 + 1) * MINUTES_PER_5_SLIDES
    ready_at = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    return minutes, ready_at


# ===== Ночное время =====

def is_night_now() -> bool:
    """Проверяет, является ли текущее время ночным (00:00–10:00)."""
    hour = datetime.now().hour
    return NIGHT_START <= hour < NIGHT_END


# ===== Эмодзи статусов =====

def get_status_emoji(status: str) -> str:
    """Возвращает эмодзи для статуса заказа."""
    emojis = {
        STATUS_NEW: "🆕",
        STATUS_WAITING_PAYMENT: "💳",
        STATUS_PAID: "✅",
        STATUS_WAITING_FILE: "📎",
        STATUS_DONE: "🎉",
        STATUS_CANCELLED: "❌",
        STATUS_PAYMENT_REJECTED: "🚫",
    }
    return emojis.get(status, "📦")


# ===== Статистика пользователей =====

def get_or_create_stats(
    user_id: int,
    username: str,
    user_stats: Dict[int, UserStats]
) -> UserStats:
    """Возвращает статистику пользователя, создаёт если не существует."""
    if user_id not in user_stats:
        user_stats[user_id] = UserStats(user_id=user_id, username=username)
    return user_stats[user_id]


def update_stats_on_complete(
    order: Order,
    user_stats: Dict[int, UserStats]
):
    """Обновляет статистику при завершении заказа."""
    stats = user_stats.get(order.user_id)
    if stats:
        stats.completed_orders += 1
        stats.total_spent += order.final


def update_stats_on_cancel(
    order: Order,
    user_stats: Dict[int, UserStats]
):
    """Обновляет статистику при отмене заказа."""
    stats = user_stats.get(order.user_id)
    if stats:
        stats.cancelled_orders += 1


# ===== Проверки =====

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id == ADMIN_ID


def get_total_revenue(orders) -> int:
    """Считает общую выручку по завершённым заказам."""
    return sum(o.final for o in orders if o.status == STATUS_DONE)


# ===== Форматирование заказов =====

def format_order(o: Order) -> str:
    """Полное форматирование заказа для вывода."""
    discount_text = (
        f"{DISCOUNT_PERCENT}% (-{o.discount} ₽)" if o.discount else "нет"
    )
    remind_text = "да" if o.remind else "нет"
    urgent_text = f"⚡ СРОЧНЫЙ (+{URGENT_SURCHARGE_PERCENT}%)" if o.urgent else "📦 Обычный"
    status_emoji = get_status_emoji(o.status)
    paid_text = f"\n💳 Оплачено: {o.paid_at}" if o.paid_at else ""
    completed_text = f"\n✅ Завершено: {o.completed_at}" if o.completed_at else ""
    return (
        f"📋 ID заказа: {o.id}\n"
        f"👤 Пользователь: @{o.username}\n"
        f"📌 Тема: {o.topic}\n"
        f"📊 Слайды: {o.slides}\n"
        f"📅 Дедлайн: {o.deadline}\n"
        f"📝 Пожелания: {o.notes}\n"
        f"💵 Цена без скидки: {o.base} ₽\n"
        f"🎁 Скидка: {discount_text}\n"
        f"💰 Итого: {o.final} ₽\n"
        f"🔔 Напоминание: {remind_text}\n"
        f"🚨 Тип заказа: {urgent_text}\n"
        f"📦 Статус: {status_emoji} {o.status}\n"
        f"🕐 Создан: {o.created_at}"
        f"{paid_text}"
        f"{completed_text}"
    )


def format_order_short(o: Order) -> str:
    """Краткое форматирование заказа для списков."""
    urgent_icon = "⚡" if o.urgent else ""
    status_emoji = get_status_emoji(o.status)
    return (
        f"ID {o.id} {urgent_icon}: {o.topic}\n"
        f"   {o.slides} слайдов | {o.final} ₽\n"
        f"   Дедлайн: {o.deadline}\n"
        f"   Статус: {status_emoji} {o.status}\n"
        f"   Создан: {o.created_at}"
    )