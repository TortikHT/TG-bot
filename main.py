# main.py
# Назначение: точка запуска бота, инициализация данных,
#             регистрация всех хендлеров через partial()
# Запуск: python main.py

import sys
import os
import logging
from functools import partial

from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, filters
)

from config import (
    BOT_TOKEN, ADMIN_ID, ADMIN_USERNAME,
    PRICE_PER_SLIDE, DISCOUNT_PERCENT,
    DISCOUNT_FROM_SLIDES, URGENT_SURCHARGE_PERCENT,
    NIGHT_START, NIGHT_END, DATA_DIR
)
from storage import (
    load_orders, load_user_stats, load_blocked_users
)
from handlers import (
    start, handle_text, about_bot,
    contact_us, price_info, my_stats,
    cancel_order_start
)
from admin import (
    admin_orders, admin_stats, admin_pending,
    admin_paid, confirm_payment, reject_payment,
    send_command, handle_doc, admin_block,
    admin_unblock, admin_broadcast, admin_help
)

# ===== Логирование =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    # ===== Кодировка для Windows =====
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    # ===== Проверка обязательных переменных =====
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")
    if not ADMIN_ID:
        raise ValueError("❌ ADMIN_ID не найден в .env")

    # ===== Создаём папку data =====
    os.makedirs(DATA_DIR, exist_ok=True)

    # ===== Загружаем данные =====
    # Все данные хранятся здесь и передаются в хендлеры через partial()
    orders = load_orders()
    user_stats = load_user_stats()
    blocked_users = load_blocked_users()
    sessions = {}        # FSM-сессии пользователей (только в памяти)
    admin_upload = {}    # Текущие загрузки файлов от админа (только в памяти)

    # ===== Строим приложение =====
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(60.0)
        .pool_timeout(10.0)
        .get_updates_connect_timeout(60.0)
        .get_updates_read_timeout(60.0)
        .get_updates_write_timeout(60.0)
        .get_updates_pool_timeout(10.0)
        .job_queue(None)
        .build()
    )

    # ===== Регистрируем хендлеры =====
    # partial() — передаём данные в хендлеры без глобальных переменных

    # Пользовательские команды
    app.add_handler(CommandHandler(
        "start",
        partial(start,
                orders=orders,
                sessions=sessions,
                user_stats=user_stats,
                blocked_users=blocked_users)
    ))

    # Текстовые сообщения — главный роутер
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        partial(handle_text,
                orders=orders,
                sessions=sessions,
                user_stats=user_stats,
                blocked_users=blocked_users,
                admin_upload=admin_upload)
    ))

    # Документы от админа
    app.add_handler(MessageHandler(
        filters.Document.ALL,
        partial(handle_doc,
                orders=orders,
                user_stats=user_stats,
                admin_upload=admin_upload)
    ))

    # Команды администратора
    app.add_handler(CommandHandler(
        "orders",
        partial(admin_orders, orders=orders)
    ))
    app.add_handler(CommandHandler(
        "stats",
        partial(admin_stats, orders=orders, user_stats=user_stats)
    ))
    app.add_handler(CommandHandler(
        "pending",
        partial(admin_pending, orders=orders)
    ))
    app.add_handler(CommandHandler(
        "paid",
        partial(admin_paid, orders=orders)
    ))
    app.add_handler(CommandHandler(
        "confirm",
        partial(confirm_payment, orders=orders)
    ))
    app.add_handler(CommandHandler(
        "reject",
        partial(reject_payment, orders=orders)
    ))
    app.add_handler(CommandHandler(
        "send",
        partial(send_command, orders=orders, admin_upload=admin_upload)
    ))
    app.add_handler(CommandHandler(
        "block",
        partial(admin_block, blocked_users=blocked_users)
    ))
    app.add_handler(CommandHandler(
        "unblock",
        partial(admin_unblock, blocked_users=blocked_users)
    ))
    app.add_handler(CommandHandler(
        "broadcast",
        partial(admin_broadcast, orders=orders, blocked_users=blocked_users)
    ))
    app.add_handler(CommandHandler("adminhelp", admin_help))

    # ===== Запуск =====
    print("✅ Бот запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"💰 Цена за слайд: {PRICE_PER_SLIDE} ₽")
    print(f"🎁 Скидка: {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов")
    print(f"🌙 Ночной режим: с {NIGHT_START}:00 до {NIGHT_END}:00")
    print(f"⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%")
    print(f"‼️ Все оплаты через @{ADMIN_USERNAME}")

    app.run_polling(
        bootstrap_retries=-1,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()