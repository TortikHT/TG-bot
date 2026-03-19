import os
from dataclasses import dataclass
from typing import Dict, List
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from datetime import datetime, timedelta

# ===== Загрузка настроек =====
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
PRICE_PER_SLIDE = int(os.getenv('PRICE_PER_SLIDE', 25))
DISCOUNT_PERCENT = int(os.getenv('DISCOUNT_PERCENT', 10))
DISCOUNT_FROM_SLIDES = int(os.getenv('DISCOUNT_FROM_SLIDES', 10))

# ===== Ночной режим и срочность =====
URGENT_SURCHARGE_PERCENT = 30  # Наценка за срочность +30%
NIGHT_START = 0                # 00:00
NIGHT_END = 10                 # 10:00

# ===== Хранилище данных =====
@dataclass
class Order:
    id: int
    user_id: int
    topic: str
    slides: int
    deadline: str
    notes: str
    base: int
    discount: int
    final: int
    status: str
    remind: bool
    urgent: bool = False

orders: List[Order] = []
sessions: Dict[int, dict] = {}
admin_upload: Dict[int, int] = {}

# ===== Вспомогательные функции =====
def is_night_now() -> bool:
    """Проверяет, ночное ли сейчас время (00:00 - 10:00)"""
    hour = datetime.now().hour
    return NIGHT_START <= hour < NIGHT_END

def calculate_price(slides: int, urgent: bool = False) -> dict:
    """Считает цену с учётом скидки и срочности"""
    base = slides * PRICE_PER_SLIDE
    discount = int(base * DISCOUNT_PERCENT // 100) if slides >= DISCOUNT_FROM_SLIDES else 0
    final = base - discount
    if urgent:
        final = int(final * (1 + URGENT_SURCHARGE_PERCENT / 100))
    return {'base': base, 'discount': discount, 'final': final}

def estimate_ready_time(slides: int) -> tuple:
    """Считает время готовности: каждые 5 слайдов = 15 минут"""
    minutes = ((slides - 1) // 5 + 1) * 15
    ready_at = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    return minutes, ready_at

def format_order(o: Order) -> str:
    """Форматирует заказ в красивый текст"""
    discount_text = f'{DISCOUNT_PERCENT}% (-{o.discount} ₽)' if o.discount else 'нет'
    remind_text = 'да' if o.remind else 'нет'
    urgent_text = '⚡ СРОЧНЫЙ (+30%)' if o.urgent else '📦 Обычный'
    return (
        f'📋 ID заказа: {o.id}\n'
        f'📌 Тема: {o.topic}\n'
        f'📊 Слайды: {o.slides}\n'
        f'📅 Дедлайн: {o.deadline}\n'
        f'📝 Пожелания: {o.notes}\n'
        f'💵 Цена без скидки: {o.base} ₽\n'
        f'🎁 Скидка: {discount_text}\n'
        f'💰 Итого: {o.final} ₽\n'
        f'🔔 Напоминание: {remind_text}\n'
        f'🚨 Тип заказа: {urgent_text}\n'
        f'📦 Статус: {o.status}'
    )

def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню с кнопками"""
    return ReplyKeyboardMarkup(
        [
            ['📦 Заказать презентацию'],
            ['📄 Мои заказы'],
            ['❌ Отменить заказ'],
            ['💰 Прайс'],
        ],
        resize_keyboard=True
    )

def urgent_menu() -> ReplyKeyboardMarkup:
    """Меню выбора срочного заказа"""
    return ReplyKeyboardMarkup(
        [
            ['🚨 Сделать СРОЧНЫМ (+30%)'],
            ['❌ Отмена']
        ],
        resize_keyboard=True
    )

def cancel_menu(user_orders) -> ReplyKeyboardMarkup:
    """Меню выбора заказа для отмены"""
    buttons = []
    for o in user_orders:
        buttons.append([f'🗑 Отменить заказ #{o.id} — {o.topic}'])
    buttons.append(['🔙 Назад'])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id == ADMIN_ID

# ===== Команды для всех =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск бота"""
    text = (
        "Привет! 👋 Я бот для быстрого заказа презентаций.\n\n"
        f"💰 Цена: {PRICE_PER_SLIDE} ₽ за слайд\n"
        f"🎁 Скидка: {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов\n"
        f"⚡ Срочный заказ (00:00–10:00): +{URGENT_SURCHARGE_PERCENT}%\n\n"
        "Выбери действие 👇"
    )
    await update.message.reply_text(text, reply_markup=main_menu())

async def price_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о ценах"""
    text = (
        "💰 Прайс:\n\n"
        f"• {PRICE_PER_SLIDE} ₽ за 1 слайд\n"
        f"• Скидка {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов\n"
        f"• Срочный заказ (00:00–10:00): +{URGENT_SURCHARGE_PERCENT}%\n\n"
        "Примеры:\n"
        f"• 5 слайдов = {5 * PRICE_PER_SLIDE} ₽\n"
        f"• 10 слайдов = {int(10 * PRICE_PER_SLIDE * (1 - DISCOUNT_PERCENT / 100))} ₽ "
        f"(со скидкой {DISCOUNT_PERCENT}%)\n"
        f"• 20 слайдов = {int(20 * PRICE_PER_SLIDE * (1 - DISCOUNT_PERCENT / 100))} ₽ "
        f"(со скидкой {DISCOUNT_PERCENT}%)\n\n"
        f"⚡ Срочный заказ: цена увеличивается на {URGENT_SURCHARGE_PERCENT}%\n"
        f"   Например, 10 слайдов срочно = "
        f"{int(int(10 * PRICE_PER_SLIDE * (1 - DISCOUNT_PERCENT / 100)) * (1 + URGENT_SURCHARGE_PERCENT / 100))} ₽\n"
    )
    await update.message.reply_text(text, reply_markup=main_menu())

# ===== Оформление заказа (пошагово) =====
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало оформления заказа"""
    user_id = update.effective_user.id
    urgent = sessions.get(user_id, {}).get('urgent', False)
    sessions[user_id] = {"step": "topic", "urgent": urgent}
    prefix = "⚡ СРОЧНЫЙ заказ\n\n" if urgent else ""
    await update.message.reply_text(
        f"{prefix}📌 Шаг 1/5\nВведи тему презентации:"
    )

# ===== Отмена заказа =====
async def cancel_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса отмены заказа"""
    user_id = update.effective_user.id

    # Только активные заказы (не завершённые и не отменённые)
    user_orders = [
        o for o in orders
        if o.user_id == user_id and o.status not in ['завершён', 'отменён']
    ]

    if not user_orders:
        return await update.message.reply_text(
            "📭 У тебя нет активных заказов для отмены.\n\n"
            "Все заказы уже завершены или отменены.",
            reply_markup=main_menu()
        )

    sessions[user_id] = {"step": "cancel_choose"}
    await update.message.reply_text(
        "🗑 Выбери заказ, который хочешь отменить:\n\n"
        "⚠️ Отменённый заказ нельзя восстановить!",
        reply_markup=cancel_menu(user_orders)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = sessions.get(user_id)

    # ===== Главное меню =====
    if text == '📦 Заказать презентацию':
        if is_night_now():
            sessions[user_id] = {"step": "urgent_choice"}
            return await update.message.reply_text(
                "🌙 Сейчас ночное время (00:00 – 10:00)\n\n"
                "В это время я не принимаю обычные заказы.\n\n"
                "Если нужно срочно — оформи срочный заказ с наценкой "
                f"+{URGENT_SURCHARGE_PERCENT}% к стоимости.\n\n"
                "Выбери вариант:",
                reply_markup=urgent_menu()
            )
        return await order_start(update, context)

    if text == '📄 Мои заказы':
        user_orders = [o for o in orders if o.user_id == user_id]
        if not user_orders:
            return await update.message.reply_text(
                "У тебя пока нет заказов. 📭",
                reply_markup=main_menu()
            )
        msg = "📄 Твои заказы:\n\n"
        for o in user_orders:
            msg += format_order(o) + "\n\n" + "─" * 20 + "\n\n"
        return await update.message.reply_text(msg[:4000], reply_markup=main_menu())

    if text == '💰 Прайс':
        return await price_info(update, context)

    if text == '❌ Отменить заказ':
        return await cancel_order_start(update, context)

    if text == '🔙 Назад':
        sessions.pop(user_id, None)
        return await update.message.reply_text(
            "Возвращаюсь в главное меню 👇",
            reply_markup=main_menu()
        )

    # ===== Если нет активной сессии =====
    if not session:
        return await update.message.reply_text(
            "Используй меню 👇",
            reply_markup=main_menu()
        )

    step = session.get('step', '')

    # ===== Выбор заказа для отмены =====
    if step == 'cancel_choose':
        if text.startswith('🗑 Отменить заказ #'):
            try:
                order_id = int(text.split('#')[1].split('—')[0].strip())
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

            session['cancel_order_id'] = order_id
            session['step'] = 'cancel_confirm'

            return await update.message.reply_text(
                f"⚠️ Ты уверен, что хочешь отменить этот заказ?\n\n"
                f"{format_order(order)}\n\n"
                "⚠️ Отменённый заказ нельзя восстановить!\n\n"
                "Подтверди отмену:",
                reply_markup=ReplyKeyboardMarkup(
                    [['✅ Да, отменить'], ['❌ Нет, оставить']],
                    resize_keyboard=True
                )
            )
        else:
            return await update.message.reply_text(
                "Выбери заказ из списка 👇"
            )

    # ===== Подтверждение отмены заказа =====
    if step == 'cancel_confirm':
        order_id = session.get('cancel_order_id')
        order = next(
            (o for o in orders if o.id == order_id and o.user_id == user_id),
            None
        )

        if text == '✅ Да, отменить':
            if order:
                order.status = 'отменён'

            sessions.pop(user_id, None)

            await update.message.reply_text(
                f"✅ Заказ #{order_id} успешно отменён!\n\n"
                "Если понадобится — оформи новый заказ. 😊",
                reply_markup=main_menu()
            )

            # Уведомляем администратора об отмене
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ Заказ #{order_id} был отменён пользователем!\n\n"
                f"{format_order(order) if order else 'Заказ не найден'}"
            )

        elif text == '❌ Нет, оставить':
            sessions.pop(user_id, None)
            await update.message.reply_text(
                "👍 Хорошо! Заказ остался активным.\n\n"
                "Возвращаюсь в главное меню 👇",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "Пожалуйста, выбери вариант из кнопок.",
                reply_markup=ReplyKeyboardMarkup(
                    [['✅ Да, отменить'], ['❌ Нет, оставить']],
                    resize_keyboard=True
                )
            )
        return

    # ===== Выбор срочного заказа ночью =====
    if step == 'urgent_choice':
        if text == '🚨 Сделать СРОЧНЫМ (+30%)':
            sessions[user_id]['urgent'] = True
            sessions[user_id]['step'] = 'topic'
            return await update.message.reply_text(
                f"⚡ Срочный заказ выбран! (+{URGENT_SURCHARGE_PERCENT}%)\n\n"
                "📌 Шаг 1/5\nВведи тему презентации:"
            )
        else:
            sessions.pop(user_id, None)
            return await update.message.reply_text(
                "Оформление отменено. Возвращаюсь в меню.",
                reply_markup=main_menu()
            )

    # ===== Шаги оформления заказа =====
    match step:
        case 'topic':
            if len(text) < 3:
                return await update.message.reply_text(
                    "❌ Тема слишком короткая. Попробуй ещё раз:"
                )
            session['topic'] = text
            session['step'] = 'slides'
            return await update.message.reply_text(
                "📊 Шаг 2/5\nСколько слайдов нужно? (от 1 до 100)"
            )

        case 'slides':
            if not text.isdigit():
                return await update.message.reply_text(
                    "❌ Введи только число. Например: 10"
                )
            slides = int(text)
            if not 1 <= slides <= 100:
                return await update.message.reply_text(
                    "❌ Введи число от 1 до 100."
                )
            session['slides'] = slides
            urgent = session.get('urgent', False)
            price = calculate_price(slides, urgent)
            minutes, ready_at = estimate_ready_time(slides)
            session.update(price)
            session['step'] = 'deadline'
            urgent_text = (
                f"\n⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%"
                if urgent else ""
            )
            return await update.message.reply_text(
                f"💰 Цена: {price['final']} ₽\n"
                f"   Базовая: {price['base']} ₽\n"
                f"   Скидка: {price['discount']} ₽"
                f"{urgent_text}\n\n"
                f"⏱ Ориентировочно готово через {minutes} мин (к {ready_at})\n\n"
                "📅 Шаг 3/5\n"
                "Укажи дедлайн:\n"
                "Например: 20.05.2025 или «до пятницы»"
            )

        case 'deadline':
            if len(text) < 3:
                return await update.message.reply_text(
                    "❌ Укажи дедлайн подробнее. Например: 20.05.2025"
                )
            session['deadline'] = text
            session['step'] = 'notes'
            return await update.message.reply_text(
                "📝 Шаг 4/5\n"
                "Есть ли пожелания?\n"
                "Например: больше картинок, минимум текста, деловой стиль\n\n"
                "Если нет — напиши «нет»"
            )

        case 'notes':
            session['notes'] = text
            session['step'] = 'remind'
            return await update.message.reply_text(
                "🔔 Шаг 5/5\n"
                "Хочешь напоминание за 1 день до дедлайна?\n\n"
                "Напиши да или нет"
            )

        case 'remind':
            session['remind'] = text.lower() == 'да'
            session['step'] = 'confirm'
            urgent = session.get('urgent', False)

            preview = Order(
                id=len(orders) + 1,
                user_id=user_id,
                topic=session['topic'],
                slides=session['slides'],
                deadline=session['deadline'],
                notes=session['notes'],
                base=session['base'],
                discount=session['discount'],
                final=session['final'],
                status='новый',
                remind=session['remind'],
                urgent=urgent
            )
            return await update.message.reply_text(
                "🔍 Проверь свой заказ:\n\n"
                + format_order(preview)
                + "\n\n✅ Всё верно? Напиши да или нет",
                reply_markup=main_menu()
            )

        case 'confirm':
            if text.lower() == 'да':
                urgent = session.get('urgent', False)
                new_order = Order(
                    id=len(orders) + 1,
                    user_id=user_id,
                    topic=session['topic'],
                    slides=session['slides'],
                    deadline=session['deadline'],
                    notes=session['notes'],
                    base=session['base'],
                    discount=session['discount'],
                    final=session['final'],
                    status='новый',
                    remind=session['remind'],
                    urgent=urgent
                )
                orders.append(new_order)
                sessions.pop(user_id, None)

                urgent_text = "⚡ Срочный заказ принят!\n" if urgent else ""
                await update.message.reply_text(
                    f"✅ Заказ успешно оформлен!\n\n"
                    f"{urgent_text}"
                    f"💰 К оплате: {new_order.final} ₽\n\n"
                    "📬 Заказ дошёл до меня и уже в работе!\n"
                    "Я сообщу тебе, когда всё будет готово. 🎉",
                    reply_markup=main_menu()
                )

                minutes, ready_at = estimate_ready_time(new_order.slides)
                await update.message.reply_text(
                    f"⏱ Ожидай готовность примерно через {minutes} минут (к {ready_at})!"
                )

                # Уведомление администратору о новом заказе
                await context.bot.send_message(
                    ADMIN_ID,
                    f"📥 Новый заказ!\n\n"
                    f"{format_order(new_order)}\n\n"
                    f"👤 User ID: {user_id}"
                )

            elif text.lower() == 'нет':
                sessions.pop(user_id, None)
                await update.message.reply_text(
                    "❌ Заказ отменён. Если хочешь — начни заново.",
                    reply_markup=main_menu()
                )
            else:
                await update.message.reply_text(
                    "Напиши да или нет."
                )

# ===== Команды администратора =====
async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/orders — все заказы (только админ)"""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    if not orders:
        return await update.message.reply_text("📭 Заказов пока нет.")
    msg = "📦 Все заказы:\n\n"
    for o in orders:
        urgent_icon = "⚡" if o.urgent else ""
        cancelled_icon = "❌" if o.status == 'отменён' else ""
        done_icon = "✅" if o.status == 'завершён' else ""
        msg += (
            f"ID {o.id}: {o.topic} {urgent_icon}{cancelled_icon}{done_icon}\n"
            f"   {o.slides} слайдов | {o.final} ₽ | {o.status}\n"
            f"   Дедлайн: {o.deadline}\n\n"
        )
    await update.message.reply_text(msg[:4000])

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/send <id> — отправить файл пользователю (только админ)"""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text(
            "❌ Используй: /send <id>\nПример: /send 3"
        )
    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")
    if order.status == 'отменён':
        return await update.message.reply_text(
            f"❌ Заказ #{order_id} был отменён пользователем!\n"
            "Нельзя отправить файл по отменённому заказу."
        )
    if order.status == 'завершён':
        return await update.message.reply_text(
            f"✅ Заказ #{order_id} уже завершён!"
        )
    admin_upload[update.effective_user.id] = order_id
    order.status = "ожидает_файл"
    await update.message.reply_text(
        f"📎 Пришли файл презентации для заказа ID {order_id}\n"
        f"📌 Тема: {order.topic}\n"
        f"📊 Слайдов: {order.slides}\n"
        f"💰 Сумма: {order.final} ₽\n\n"
        "Форматы: PDF или PPTX"
    )

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка файла от администратора"""
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

    # Отправляем файл пользователю
    await context.bot.send_document(
        chat_id=order.user_id,
        document=update.message.document.file_id,
        caption=(
            f"✅ Твоя презентация готова!\n\n"
            f"📋 ID заказа: {order.id}\n"
            f"📌 Тема: {order.topic}\n"
            f"📊 Слайдов: {order.slides}\n"
            f"💰 Оплата: {order.final} ₽\n\n"
            "Спасибо за заказ! 🎉"
        )
    )
    order.status = "завершён"
    admin_upload.pop(user_id, None)
    await update.message.reply_text(
        f"✅ Файл успешно отправлен!\n"
        f"Заказ ID {order.id} закрыт. ✅"
    )

async def admin_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reminders — напоминания на завтра (только админ)"""
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    today = datetime.now().date()
    reminders = []
    for o in orders:
        if not o.remind:
            continue
        if o.status in ['завершён', 'отменён']:
            continue
        try:
            deadline = datetime.strptime(o.deadline, "%d.%m.%Y").date()
        except ValueError:
            continue
        if (deadline - today).days == 1:
            reminders.append(
                f"📌 ID {o.id}: {o.topic}\n"
                f"   Дедлайн: {o.deadline}\n"
                f"   Пользователь: {o.user_id}\n"
                f"   Статус: {o.status}"
            )
    if not reminders:
        return await update.message.reply_text(
            "✅ Нет напоминаний на завтра."
        )
    msg = "🔔 Напоминания на завтра:\n\n" + "\n\n".join(reminders)
    await update.message.reply_text(msg)

# ===== Запуск бота =====
def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")
    if not ADMIN_ID:
        raise ValueError("❌ ADMIN_ID не найден в .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды для всех
    app.add_handler(CommandHandler("start", start))

    # Команды для администратора
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("reminders", admin_reminders))

    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))

    print("✅ Бот запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"💰 Цена за слайд: {PRICE_PER_SLIDE} ₽")
    print(f"🎁 Скидка: {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов")
    print(f"🌙 Ночной режим: с {NIGHT_START}:00 до {NIGHT_END}:00")
    print(f"⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%")
    app.run_polling()

if __name__ == "__main__":
    main()