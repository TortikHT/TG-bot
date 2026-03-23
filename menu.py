# menu.py
# Назначение: все клавиатуры ReplyKeyboardMarkup
# Импортируется handlers.py и admin.py

from typing import List
from telegram import ReplyKeyboardMarkup

from models import Order


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню пользователя."""
    return ReplyKeyboardMarkup(
        [
            ["📦 Заказать презентацию"],
            ["📄 Мои заказы", "💰 Прайс"],
            ["❌ Отменить заказ", "📊 Моя статистика"],
            ["ℹ️ О боте", "📞 Связь с нами"],
        ],
        resize_keyboard=True
    )


def urgent_menu() -> ReplyKeyboardMarkup:
    """Меню выбора срочного заказа (ночное время)."""
    return ReplyKeyboardMarkup(
        [
            ["🚨 Сделать СРОЧНЫМ (+30%)"],
            ["❌ Отмена"]
        ],
        resize_keyboard=True
    )


def cancel_menu(user_orders: List[Order]) -> ReplyKeyboardMarkup:
    """Меню выбора заказа для отмены."""
    buttons = []
    for o in user_orders:
        buttons.append([f"🗑 Отменить заказ #{o.id} — {o.topic}"])
    buttons.append(["🔙 Назад"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def payment_menu() -> ReplyKeyboardMarkup:
    """Меню ожидания оплаты."""
    return ReplyKeyboardMarkup(
        [
            ["✅ Я оплатил"],
            ["❌ Отменить заказ"]
        ],
        resize_keyboard=True
    )


def confirm_menu() -> ReplyKeyboardMarkup:
    """Меню подтверждения заказа."""
    return ReplyKeyboardMarkup(
        [
            ["✅ Да, всё верно"],
            ["❌ Нет, начать заново"]
        ],
        resize_keyboard=True
    )


def yes_no_menu() -> ReplyKeyboardMarkup:
    """Универсальное меню Да/Нет."""
    return ReplyKeyboardMarkup(
        [["✅ Да", "❌ Нет"]],
        resize_keyboard=True
    )


def cancel_only_menu() -> ReplyKeyboardMarkup:
    """Меню с единственной кнопкой отмены (во время ввода)."""
    return ReplyKeyboardMarkup(
        [["❌ Отмена"]],
        resize_keyboard=True
    )


def cancel_confirm_menu() -> ReplyKeyboardMarkup:
    """Меню подтверждения отмены заказа."""
    return ReplyKeyboardMarkup(
        [
            ["✅ Да, отменить"],
            ["❌ Нет, оставить"]
        ],
        resize_keyboard=True
    )


def notes_menu() -> ReplyKeyboardMarkup:
    """Меню шага пожеланий — быстрый ответ 'нет пожеланий'."""
    return ReplyKeyboardMarkup(
        [
            ["Нет пожеланий"],
            ["❌ Отмена"]
        ],
        resize_keyboard=True
    )


def remind_menu() -> ReplyKeyboardMarkup:
    """Меню выбора напоминания."""
    return ReplyKeyboardMarkup(
        [
            ["✅ Да"],
            ["❌ Нет"]
        ],
        resize_keyboard=True
    )