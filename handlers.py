# handlers.py
# Назначение: все обработчики сообщений пользователя (FSM-шаги)
# Импортируется main.py

import logging
from datetime import datetime
from typing import Dict, List

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    ADMIN_ID, ADMIN_USERNAME,
    PRICE_PER_SLIDE, DISCOUNT_PERCENT,
    DISCOUNT_FROM_SLIDES, URGENT_SURCHARGE_PERCENT,
    MIN_SLIDES, MAX_SLIDES,
    MIN_TOPIC_LEN, MIN_DEADLINE_LEN,
    STATUS_NEW, STATUS_WAITING_PAYMENT,
    STATUS_DONE, STATUS_CANCELLED,
)
from models import Order, UserStats
from storage import (
    persist_orders, persist_stats,
    persist_blocked, next_order_id
)
from services import (
    calculate_price, estimate_ready_time,
    is_night_now, get_or_create_stats,
    update_stats_on_cancel, format_order,
    is_admin
)
from menu import (
    main_menu, urgent_menu, cancel_menu,
    payment_menu, confirm_menu, cancel_only_menu,
    cancel_confirm_menu, notes_menu, remind_menu
)

logger = logging.getLogger(__name__)


# ===== /start =====

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    sessions: Dict,
    user_stats: Dict[int, UserStats],
    blocked_users: List[int]
):
    """Обработчик команды /start."""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)

    if user_id in blocked_users:
        return await update.message.reply_text(
            "❌ Вы заблокированы и не можете использовать этого бота."
        )

    get_or_create_stats(user_id, username, user_stats)
    persist_stats(user_stats)

    text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Я бот для быстрого заказа презентаций.\n\n"
        f"💰 Цена: {PRICE_PER_SLIDE} ₽ за слайд\n"
        f"🎁 Скидка: {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов\n"
        f"⚡ Срочный заказ (00:00–10:00): +{URGENT_SURCHARGE_PERCENT}%\n\n"
        "📋 Как это работает:\n"
        "1. Оформляешь заказ\n"
        "2. Получаешь детали оплаты\n"
        "3. Подтверждаешь оплату\n"
        "4. Получаешь готовую презентацию\n\n"
        "Выбери действие 👇"
    )
    await update.message.reply_text(text, reply_markup=main_menu())


# ===== О боте =====

async def about_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о боте."""
    text = (
        "ℹ️ О боте:\n\n"
        "Я помогаю быстро заказать профессиональную презентацию.\n\n"
        "📌 Что я умею:\n"
        "• Принимать заказы на презентации\n"
        "• Рассчитывать стоимость автоматически\n"
        "• Давать скидку от 10 слайдов\n"
        "• Принимать срочные заказы\n"
        "• Отправлять готовые файлы прямо в чат\n\n"
        "⏱ Время выполнения:\n"
        "• Каждые 5 слайдов = 15 минут\n"
        "• 10 слайдов ≈ 30 минут\n"
        "• 20 слайдов ≈ 1 час\n\n"
        "💎 Качество:\n"
        "• Профессиональный дизайн\n"
        "• Форматы PDF и PPTX\n"
        "• Правки включены в стоимость\n"
    )
    await update.message.reply_text(text, reply_markup=main_menu())


# ===== Связь =====

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Контактная информация."""
    text = (
        "📞 Связь с нами:\n\n"
        f"По вопросам оплаты и заказов напиши @{ADMIN_USERNAME}\n\n"
        "⏰ Время работы:\n"
        "• Обычные заказы: 10:00 – 00:00\n"
        "• Срочные заказы: круглосуточно\n\n"
        "📋 По вопросам заказов указывай ID заказа."
    )
    await update.message.reply_text(text, reply_markup=main_menu())


# ===== Прайс =====

async def price_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о ценах с примерами."""
    examples = []
    for slides in [5, 10, 15, 20, 30, 50]:
        price = calculate_price(slides)
        urgent_price = calculate_price(slides, urgent=True)
        if price["discount"] > 0:
            examples.append(
                f"• {slides} слайдов = {price['final']} ₽ "
                f"(скидка {price['discount']} ₽) | срочно: {urgent_price['final']} ₽"
            )
        else:
            examples.append(
                f"• {slides} слайдов = {price['final']} ₽ "
                f"| срочно: {urgent_price['final']} ₽"
            )
    text = (
        "💰 Прайс:\n\n"
        f"• {PRICE_PER_SLIDE} ₽ за 1 слайд\n"
        f"• Минимум {MIN_SLIDES} слайдов\n"
        f"• Скидка {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов\n"
        f"• Срочный заказ (00:00–10:00): +{URGENT_SURCHARGE_PERCENT}%\n\n"
        "📊 Примеры расчёта:\n" + "\n".join(examples)
    )
    await update.message.reply_text(text, reply_markup=main_menu())


# ===== Статистика пользователя =====

async def my_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    user_stats: Dict[int, UserStats]
):
    """Личная статистика пользователя."""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)

    get_or_create_stats(user_id, username, user_stats)
    user_orders = [o for o in orders if o.user_id == user_id]

    waiting_payment = len([o for o in user_orders if o.status == STATUS_WAITING_PAYMENT])
    paid = len([o for o in user_orders if o.status == "оплачен"])
    in_progress = len([o for o in user_orders if o.status == "ожидает_файл"])
    completed = len([o for o in user_orders if o.status == STATUS_DONE])
    cancelled = len([o for o in user_orders if o.status == STATUS_CANCELLED])
    total_spent = sum(o.final for o in user_orders if o.status == STATUS_DONE)
    total_slides = sum(o.slides for o in user_orders if o.status == STATUS_DONE)

    text = (
        f"📊 Твоя статистика:\n\n"
        f"👤 Пользователь: @{username}\n\n"
        f"📦 Всего заказов: {len(user_orders)}\n"
        f"💳 Ожидают оплаты: {waiting_payment}\n"
        f"✅ Оплачены: {paid}\n"
        f"🔄 В работе: {in_progress}\n"
        f"🎉 Завершены: {completed}\n"
        f"❌ Отменены: {cancelled}\n\n"
        f"💰 Потрачено всего: {total_spent} ₽\n"
        f"📊 Слайдов заказано: {total_slides}\n"
    )

    if completed >= 3:
        text += "\n🏆 Ты постоянный клиент! Спасибо за доверие! 🎉"
    elif completed >= 1:
        text += "\n😊 Спасибо за заказ! Ждём тебя снова!"

    await update.message.reply_text(text, reply_markup=main_menu())


# ===== Отмена заказа =====

async def cancel_order_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    sessions: Dict,
):
    """Начало процесса отмены заказа."""
    user_id = update.effective_user.id
    user_orders = [
        o for o in orders
        if o.user_id == user_id
        and o.status not in [STATUS_DONE, STATUS_CANCELLED]
    ]
    if not user_orders:
        return await update.message.reply_text(
            "📭 У тебя нет активных заказов для отмены.",
            reply_markup=main_menu()
        )
    sessions[user_id] = {"step": "cancel_choose"}
    await update.message.reply_text(
        "🗑 Выбери заказ для отмены:\n\n"
        "⚠️ Отменённый заказ нельзя восстановить!",
        reply_markup=cancel_menu(user_orders)
    )


# ===== Главный обработчик текста =====

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    sessions: Dict,
    user_stats: Dict[int, UserStats],
    blocked_users: List[int],
    admin_upload: Dict[int, int]
):
    """
    Главный роутер текстовых сообщений.
    Обрабатывает главное меню и все FSM-шаги заказа.
    """
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str

    # handlers.py (продолжение — после handle_text определения)

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: List[Order],
    sessions: Dict,
    user_stats: Dict[int, UserStats],
    blocked_users: List[int],
    admin_upload: Dict[int, int]
):
    """
    Главный роутер текстовых сообщений.
    Обрабатывает главное меню и все FSM-шаги заказа.
    """
    # Защита от пустого сообщения
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)
    text = update.message.text.strip()
    session = sessions.get(user_id)

    # Проверка блокировки
    if user_id in blocked_users:
        return await update.message.reply_text(
            "❌ Вы заблокированы и не можете использовать этого бота."
        )

    # ===== ГЛАВНОЕ МЕНЮ =====

    if text == "📦 Заказать презентацию":
        if is_night_now():
            sessions[user_id] = {"step": "urgent_choice"}
            return await update.message.reply_text(
                "🌙 Сейчас ночное время (00:00 – 10:00)\n\n"
                "В это время я не принимаю обычные заказы.\n\n"
                f"Срочный заказ с наценкой +{URGENT_SURCHARGE_PERCENT}%.\n\n"
                "Выбери вариант:",
                reply_markup=urgent_menu()
            )
        sessions[user_id] = {"step": "topic", "urgent": False}
        return await update.message.reply_text(
            "📌 Шаг 1/5\n\nВведи тему презентации:\n\n"
            "Например: История России, Маркетинг для стартапов",
            reply_markup=cancel_only_menu()
        )

    if text == "📄 Мои заказы":
        user_orders = [o for o in orders if o.user_id == user_id]
        if not user_orders:
            return await update.message.reply_text(
                "У тебя пока нет заказов. 📭",
                reply_markup=main_menu()
            )
        msg = f"📄 Твои заказы ({len(user_orders)} шт.):\n\n"
        for o in user_orders:
            msg += format_order(o) + "\n\n" + "─" * 25 + "\n\n"
        for i in range(0, len(msg), 4000):
            await update.message.reply_text(msg[i:i + 4000])
        return

    if text == "💰 Прайс":
        return await price_info(update, context)

    if text == "❌ Отменить заказ":
        return await cancel_order_start(update, context, orders, sessions)

    if text == "📊 Моя статистика":
        return await my_stats(update, context, orders, user_stats)

    if text == "ℹ️ О боте":
        return await about_bot(update, context)

    if text == "📞 Связь с нами":
        return await contact_us(update, context)

    if text in ["🔙 Назад", "❌ Отмена"]:
        sessions.pop(user_id, None)
        return await update.message.reply_text(
            "Возвращаюсь в главное меню 👇",
            reply_markup=main_menu()
        )

    # Если нет активной сессии — подсказка
    if not session:
        return await update.message.reply_text(
            "Используй меню 👇",
            reply_markup=main_menu()
        )

    step = session.get("step", "")

    # ===== СРОЧНЫЙ ЗАКАЗ НОЧЬЮ =====

    if step == "urgent_choice":
        if text == "🚨 Сделать СРОЧНЫМ (+30%)":
            sessions[user_id] = {"step": "topic", "urgent": True}
            return await update.message.reply_text(
                f"⚡ Срочный заказ! (+{URGENT_SURCHARGE_PERCENT}%)\n\n"
                "📌 Шаг 1/5\nВведи тему презентации:",
                reply_markup=cancel_only_menu()
            )
        sessions.pop(user_id, None)
        return await update.message.reply_text(
            "Оформление отменено.",
            reply_markup=main_menu()
        )

    # ===== ШАГ 1 — ТЕМА =====

    if step == "topic":
        if len(text) < MIN_TOPIC_LEN:
            return await update.message.reply_text(
                "❌ Тема слишком короткая. Минимум 3 символа.",
                reply_markup=cancel_only_menu()
            )
        if len(text) > 200:
            return await update.message.reply_text(
                "❌ Тема слишком длинная. Максимум 200 символов.",
                reply_markup=cancel_only_menu()
            )
        session["topic"] = text
        session["step"] = "slides"
        return await update.message.reply_text(
            f"📊 Шаг 2/5\n\nСколько слайдов нужно? "
            f"(от {MIN_SLIDES} до {MAX_SLIDES})\n\n"
            "Примеры:\n"
            "• 5 слайдов — краткая\n"
            "• 10-15 слайдов — стандартная\n"
            "• 20+ слайдов — подробная",
            reply_markup=cancel_only_menu()
        )

    # ===== ШАГ 2 — СЛАЙДЫ =====

    if step == "slides":
        if not text.isdigit():
            return await update.message.reply_text(
                "❌ Введи только число. Например: 10",
                reply_markup=cancel_only_menu()
            )
        slides = int(text)
        if not MIN_SLIDES <= slides <= MAX_SLIDES:
            return await update.message.reply_text(
                f"❌ Введи число от {MIN_SLIDES} до {MAX_SLIDES}.",
                reply_markup=cancel_only_menu()
            )
        session["slides"] = slides
        urgent = session.get("urgent", False)
        price = calculate_price(slides, urgent)
        minutes, ready_at = estimate_ready_time(slides)
        session.update(price)
        session["step"] = "deadline"
        urgent_text = f"\n⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%" if urgent else ""
        return await update.message.reply_text(
            f"✅ Отлично! {slides} слайдов\n\n"
            f"💰 Расчёт стоимости:\n"
            f"   Базовая цена: {price['base']} ₽\n"
            f"   Скидка: {price['discount']} ₽"
            f"{urgent_text}\n"
            f"   Итого: {price['final']} ₽\n\n"
            f"⏱ Готовность примерно через {minutes} мин (к {ready_at})\n\n"
            "📅 Шаг 3/5\n\nУкажи дедлайн:\n"
            "Например: 20.05.2025 или «до пятницы»",
            reply_markup=cancel_only_menu()
        )

    # ===== ШАГ 3 — ДЕДЛАЙН =====

    if step == "deadline":
        if len(text) < MIN_DEADLINE_LEN:
            return await update.message.reply_text(
                "❌ Укажи дедлайн подробнее.\n"
                "Например: 20.05.2025 или «до пятницы»",
                reply_markup=cancel_only_menu()
            )
        session["deadline"] = text
        session["step"] = "notes"
        return await update.message.reply_text(
            "📝 Шаг 4/5\n\nЕсть ли пожелания к презентации?\n\n"
            "Например:\n"
            "• Больше картинок, минимум текста\n"
            "• Деловой стиль, синие тона\n"
            "• Много графиков и диаграмм\n\n"
            "Если нет — нажми кнопку ниже",
            reply_markup=notes_menu()
        )

    # ===== ШАГ 4 — ПОЖЕЛАНИЯ =====

    if step == "notes":
        if text == "Нет пожеланий":
            text = "нет"
        session["notes"] = text
        session["step"] = "remind"
        return await update.message.reply_text(
            "🔔 Шаг 5/5\n\n"
            "Хочешь напоминание за 1 день до дедлайна?",
            reply_markup=remind_menu()
        )

    # ===== ШАГ 5 — НАПОМИНАНИЕ =====

    if step == "remind":
        if text.lower() not in ["да", "нет", "✅ да", "❌ нет"]:
            return await update.message.reply_text(
                "Нажми одну из кнопок 👇",
                reply_markup=remind_menu()
            )
        session["remind"] = text.lower() in ["да", "✅ да"]
        session["step"] = "confirm"
        urgent = session.get("urgent", False)

        # Превью заказа
        preview = Order(
            id=next_order_id(orders),
            user_id=user_id,
            username=username,
            topic=session["topic"],
            slides=session["slides"],
            deadline=session["deadline"],
            notes=session["notes"],
            base=session["base"],
            discount=session["discount"],
            final=session["final"],
            status=STATUS_NEW,
            remind=session["remind"],
            urgent=urgent
        )
        return await update.message.reply_text(
            "🔍 Проверь свой заказ:\n\n"
            + format_order(preview)
            + "\n\n✅ Всё верно? Подтверди заказ:",
            reply_markup=confirm_menu()
        )

    # ===== ПОДТВЕРЖДЕНИЕ ЗАКАЗА =====

    if step == "confirm":
        if text == "✅ Да, всё верно":
            urgent = session.get("urgent", False)
            new_order = Order(
                id=next_order_id(orders),
                user_id=user_id,
                username=username,
                topic=session["topic"],
                slides=session["slides"],
                deadline=session["deadline"],
                notes=session["notes"],
                base=session["base"],
                discount=session["discount"],
                final=session["final"],
                status=STATUS_WAITING_PAYMENT,
                remind=session["remind"],
                urgent=urgent
            )
            orders.append(new_order)
            persist_orders(orders)

            # Обновляем статистику
            stats = get_or_create_stats(user_id, username, user_stats)
            stats.total_orders += 1
            persist_stats(user_stats)
            sessions.pop(user_id, None)

            await update.message.reply_text(
                f"✅ Заказ #{new_order.id} создан!\n\n"
                f"💰 К оплате: {new_order.final} ₽\n\n"
                f"❗ Для оплаты напиши @{ADMIN_USERNAME} 👈\n"
                f"Укажи номер заказа #{new_order.id} и жди реквизитов.\n\n"
                "После оплаты вернись и нажми «✅ Я оплатил»",
                reply_markup=payment_menu()
            )
            sessions[user_id] = {
                "step": "waiting_payment",
                "order_id": new_order.id
            }
            # Уведомление админу
            await context.bot.send_message(
                ADMIN_ID,
                f"📥 Новый заказ #{new_order.id} ожидает оплаты!\n\n"
                f"👤 @{username} (ID: {user_id})\n\n"
                f"{format_order(new_order)}"
            )

        elif text == "❌ Нет, начать заново":
            sessions.pop(user_id, None)
            await update.message.reply_text(
                "❌ Заказ отменён. Начни заново 👇",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "Выбери вариант из кнопок 👇",
                reply_markup=confirm_menu()
            )
        return

    # ===== ОЖИДАНИЕ ОПЛАТЫ =====

    if step == "waiting_payment":
        order_id = session.get("order_id")
        order = next((o for o in orders if o.id == order_id), None)

        if text == "✅ Я оплатил":
            if not order:
                return await update.message.reply_text(
                    "❌ Заказ не найден.",
                    reply_markup=main_menu()
                )
            sessions.pop(user_id, None)
            await update.message.reply_text(
                "⏳ Ожидай подтверждения оплаты от администратора.\n"
                "Обычно это занимает несколько минут. 😊",
                reply_markup=main_menu()
            )
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 Пользователь сообщил об оплате!\n\n"
                f"👤 @{username} (ID: {user_id})\n\n"
                f"{format_order(order)}\n\n"
                f"✅ Подтвердить: /confirm {order_id}\n"
                f"❌ Отклонить: /reject {order_id}"
            )

        elif text == "❌ Отменить заказ":
            if order:
                order.status = STATUS_CANCELLED
                persist_orders(orders)
                update_stats_on_cancel(order, user_stats)
                persist_stats(user_stats)
            sessions.pop(user_id, None)
            await update.message.reply_text(
                f"✅ Заказ #{order_id} отменён.",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                f"⏳ Заказ #{order_id} ожидает оплаты.\n\n"
                f"❗ Для реквизитов напиши @{ADMIN_USERNAME}\n"
                "После оплаты нажми «✅ Я оплатил»",
                reply_markup=payment_menu()
            )
        return

    # ===== ВЫБОР ЗАКАЗА ДЛЯ ОТМЕНЫ =====

    if step == "cancel_choose":
        if text.startswith("🗑 Отменить заказ #"):
            try:
                order_id = int(text.split("#")[1].split("—")[0].strip())
            except (ValueError, IndexError):
                return await update.message.reply_text(
                    "❌ Ошибка. Попробуй снова.",
                    reply_markup=main_menu()
                )
            order = next(
                (o for o in orders if o.id == order_id and o.user_id == user_id),
                None
            )
            if not order:
                sessions.pop(user_id, None)
                return await update.message.reply_text(
                    "❌ Заказ не найден.",
                    reply_markup=main_menu()
                )
            session["cancel_order_id"] = order_id
            session["step"] = "cancel_confirm"
            return await update.message.reply_text(
                f"⚠️ Ты уверен, что хочешь отменить?\n\n"
                f"{format_order(order)}\n\n"
                "⚠️ Отменённый заказ нельзя восстановить!",
                reply_markup=cancel_confirm_menu()
            )
        if text == "🔙 Назад":
            sessions.pop(user_id, None)
            return await update.message.reply_text(
                "Возвращаюсь в меню 👇",
                reply_markup=main_menu()
            )
        return await update.message.reply_text("Выбери заказ из списка 👇")

    # ===== ПОДТВЕРЖДЕНИЕ ОТМЕНЫ =====

    if step == "cancel_confirm":
        order_id = session.get("cancel_order_id")
        order = next(
            (o for o in orders if o.id == order_id and o.user_id == user_id),
            None
        )
        if text == "✅ Да, отменить":
            if order:
                order.status = STATUS_CANCELLED
                persist_orders(orders)
                update_stats_on_cancel(order, user_stats)
                persist_stats(user_stats)
            sessions.pop(user_id, None)
            await update.message.reply_text(
                f"✅ Заказ #{order_id} отменён!",
                reply_markup=main_menu()
            )
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ Заказ #{order_id} отменён пользователем!\n\n"
                f"👤 @{username} (ID: {user_id})\n\n"
                f"{format_order(order) if order else 'Заказ не найден'}"
            )
        elif text == "❌ Нет, оставить":
            sessions.pop(user_id, None)
            await update.message.reply_text(
                "👍 Заказ остался активным.",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "Выбери вариант из кнопок.",
                reply_markup=cancel_confirm_menu()
            )
        return

    # Fallback
    await update.message.reply_text(
        "Используй меню 👇",
        reply_markup=main_menu()
    )