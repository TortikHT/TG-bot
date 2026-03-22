import os
import sys
import json
import logging
import asyncio
import httpx
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from datetime import datetime, timedelta

# ===== Файловое хранилище =====
DATA_DIR = "data"
ORDERS_PATH = os.path.join(DATA_DIR, "orders.json")
STATS_PATH = os.path.join(DATA_DIR, "user_stats.json")

def load_json(filepath, default=None):
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def save_json(filepath, data):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def persist_orders():
    save_json(ORDERS_PATH, [asdict(o) for o in orders])

def persist_stats():
    save_json(STATS_PATH, {str(k): asdict(v) for k, v in user_stats.items()})

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== Загрузка настроек =====
load_dotenv()

def _int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = _int_env('ADMIN_ID', 0)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'TortiKht')
PRICE_PER_SLIDE = _int_env('PRICE_PER_SLIDE', 25)
DISCOUNT_PERCENT = _int_env('DISCOUNT_PERCENT', 10)
DISCOUNT_FROM_SLIDES = _int_env('DISCOUNT_FROM_SLIDES', 10)
HF_TOKEN = os.getenv('HF_TOKEN', '').strip() or None
HF_MODEL = os.getenv('HF_MODEL', 'Qwen/Qwen2.5-3B-Instruct')

# ===== Hugging Face Inference (HTTP; httpx идёт с python-telegram-bot) =====
def hf_generate_sync(prompt: str) -> str:
    if not HF_TOKEN:
        raise ValueError("HF_TOKEN не задан в .env")
    url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 2048,
            "return_full_text": False,
        },
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers=headers, json=payload)
        if r.status_code == 503:
            raise RuntimeError("Модель на стороне HF загружается — подожди минуту и повтори.")
        r.raise_for_status()
        data = r.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))
    if isinstance(data, list) and data and isinstance(data[0], dict):
        text = data[0].get("generated_text")
        if text is not None:
            return str(text).strip()
    if isinstance(data, dict) and "generated_text" in data:
        return str(data["generated_text"]).strip()
    raise RuntimeError(f"Неожиданный ответ API: {str(data)[:500]}")

async def hf_generate_async(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, hf_generate_sync, prompt)

# ===== Константы =====
URGENT_SURCHARGE_PERCENT = 30
NIGHT_START = 0
NIGHT_END = 10
MAX_SLIDES = 100
MIN_SLIDES = 5
MIN_TOPIC_LEN = 3
MIN_DEADLINE_LEN = 3
MINUTES_PER_5_SLIDES = 15

# ===== Статусы заказов =====
STATUS_NEW = 'новый'
STATUS_WAITING_PAYMENT = 'ожидает_оплату'
STATUS_PAID = 'оплачен'
STATUS_WAITING_FILE = 'ожидает_файл'
STATUS_DONE = 'завершён'
STATUS_CANCELLED = 'отменён'
STATUS_PAYMENT_REJECTED = 'оплата_отклонена'

@dataclass
class Order:
    id: int
    user_id: int
    username: str
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
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%d.%m.%Y %H:%M"))
    paid_at: Optional[str] = None
    completed_at: Optional[str] = None

@dataclass
class UserStats:
    user_id: int
    username: str
    total_orders: int = 0
    total_spent: int = 0
    cancelled_orders: int = 0
    completed_orders: int = 0

orders: List[Order] = [Order(**d) for d in load_json(ORDERS_PATH, default=[])]
sessions: Dict[int, dict] = {}
admin_upload: Dict[int, int] = {}
user_stats: Dict[int, UserStats] = {int(k): UserStats(**v) for k, v in load_json(STATS_PATH, default={}).items()}
blocked_users: List[int] = []

# ===== Вспомогательные функции =====
def calculate_price(slides: int, urgent: bool = False) -> dict:
    base = slides * PRICE_PER_SLIDE
    discount = int(base * DISCOUNT_PERCENT // 100) if slides >= DISCOUNT_FROM_SLIDES else 0
    final = base - discount
    if urgent:
        final = int(final * (1 + URGENT_SURCHARGE_PERCENT / 100))
    return {'base': base, 'discount': discount, 'final': final}

def estimate_ready_time(slides: int) -> tuple:
    minutes = ((slides - 1) // 5 + 1) * MINUTES_PER_5_SLIDES
    ready_at = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    return minutes, ready_at

def is_night_now() -> bool:
    hour = datetime.now().hour
    return NIGHT_START <= hour < NIGHT_END

def get_status_emoji(status: str) -> str:
    emojis = {
        STATUS_NEW: '🆕',
        STATUS_WAITING_PAYMENT: '💳',
        STATUS_PAID: '✅',
        STATUS_WAITING_FILE: '📎',
        STATUS_DONE: '🎉',
        STATUS_CANCELLED: '❌',
        STATUS_PAYMENT_REJECTED: '🚫',
    }
    return emojis.get(status, '📦')

def get_or_create_stats(user_id: int, username: str) -> UserStats:
    if user_id not in user_stats:
        user_stats[user_id] = UserStats(user_id=user_id, username=username)
        persist_stats()
    return user_stats[user_id]

def update_stats_on_complete(order: Order):
    stats = user_stats.get(order.user_id)
    if stats:
        stats.completed_orders += 1
        stats.total_spent += order.final
        persist_stats()

def update_stats_on_cancel(order: Order):
    stats = user_stats.get(order.user_id)
    if stats:
        stats.cancelled_orders += 1
        persist_stats()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def is_blocked(user_id: int) -> bool:
    return user_id in blocked_users

def get_total_revenue() -> int:
    return sum(o.final for o in orders if o.status == STATUS_DONE)

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ['📦 Заказать презентацию'],
            ['📄 Мои заказы', '💰 Прайс'],
            ['❌ Отменить заказ', '📊 Моя статистика'],
            ['🤖 ИИ план презентации'],
            ['ℹ️ О боте', '📞 Связь с нами'],
        ],
        resize_keyboard=True
    )

def urgent_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ['🚨 Сделать СРОЧНЫМ (+30%)'],
            ['❌ Отмена']
        ],
        resize_keyboard=True
    )

def cancel_menu(user_orders) -> ReplyKeyboardMarkup:
    buttons = []
    for o in user_orders:
        buttons.append([f'🗑 Отменить заказ #{o.id} — {o.topic}'])
    buttons.append(['🔙 Назад'])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def payment_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [['✅ Я оплатил'], ['❌ Отменить заказ']],
        resize_keyboard=True
    )

def format_order(o: Order) -> str:
    discount_text = f'{DISCOUNT_PERCENT}% (-{o.discount} ₽)' if o.discount else 'нет'
    remind_text = 'да' if o.remind else 'нет'
    urgent_text = '⚡ СРОЧНЫЙ (+30%)' if o.urgent else '📦 Обычный'
    status_emoji = get_status_emoji(o.status)
    paid_text = f'\n💳 Оплачено: {o.paid_at}' if o.paid_at else ''
    completed_text = f'\n✅ Завершено: {o.completed_at}' if o.completed_at else ''
    return (
        f'📋 ID заказа: {o.id}\n'
        f'👤 Пользователь: @{o.username}\n'
        f'📌 Тема: {o.topic}\n'
        f'📊 Слайды: {o.slides}\n'
        f'📅 Дедлайн: {o.deadline}\n'
        f'📝 Пожелания: {o.notes}\n'
        f'💵 Цена без скидки: {o.base} ₽\n'
        f'🎁 Скидка: {discount_text}\n'
        f'💰 Итого: {o.final} ₽\n'
        f'🔔 Напоминание: {remind_text}\n'
        f'🚨 Тип заказа: {urgent_text}\n'
        f'📦 Статус: {status_emoji} {o.status}\n'
        f'🕐 Создан: {o.created_at}'
        f'{paid_text}'
        f'{completed_text}'
    )

def format_order_short(o: Order) -> str:
    urgent_icon = "⚡" if o.urgent else ""
    status_emoji = get_status_emoji(o.status)
    return (
        f'ID {o.id} {urgent_icon}: {o.topic}\n'
        f'   {o.slides} слайдов | {o.final} ₽\n'
        f'   Дедлайн: {o.deadline}\n'
        f'   Статус: {status_emoji} {o.status}\n'
        f'   Создан: {o.created_at}'
    )

# ===== Команды для пользователей =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)
    if is_blocked(user_id):
        return await update.message.reply_text("❌ Вы заблокированы и не можете использовать этого бота.")
    get_or_create_stats(user_id, username)
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

async def about_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📞 Связь с нами:\n\n"
        f"По вопросам оплаты и заказов напиши @{ADMIN_USERNAME}\n\n"
        "⏰ Время работы:\n"
        "• Обычные заказы: 10:00 – 00:00\n"
        "• Срочные заказы: круглосуточно\n\n"
        "📋 По вопросам заказов указывай ID заказа."
    )
    await update.message.reply_text(text, reply_markup=main_menu())

async def price_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    examples = []
    for slides in [5, 10, 15, 20, 30, 50]:
        price = calculate_price(slides)
        urgent_price = calculate_price(slides, urgent=True)
        if price['discount'] > 0:
            examples.append(
                f"• {slides} слайдов = {price['final']} ₽ "
                f"(скидка {price['discount']} ₽) | срочно: {urgent_price['final']} ₽"
            )
        else:
            examples.append(
                f"• {slides} слайдов = {price['final']} ₽ | срочно: {urgent_price['final']} ₽"
            )
    text = (
        "💰 Прайс:\n\n"
        f"• {PRICE_PER_SLIDE} ₽ за 1 слайд\n"
        f"• Минимум {MIN_SLIDES} слайдов\n"
        f"• Скидка {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов\n"
        f"• Срочный заказ (00:00–10:00): +{URGENT_SURCHARGE_PERCENT}%\n\n"
        "📊 Примеры расчёта:\n"
        + "\n".join(examples)
    )
    await update.message.reply_text(text, reply_markup=main_menu())

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)
    get_or_create_stats(user_id, username)
    user_orders = [o for o in orders if o.user_id == user_id]
    waiting_payment = len([o for o in user_orders if o.status == STATUS_WAITING_PAYMENT])
    paid = len([o for o in user_orders if o.status == STATUS_PAID])
    in_progress = len([o for o in user_orders if o.status == STATUS_WAITING_FILE])
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

# ===== Оформление заказа =====
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    urgent = sessions.get(user_id, {}).get('urgent', False)
    sessions[user_id] = {"step": "topic", "urgent": urgent}
    prefix = "⚡ СРОЧНЫЙ заказ\n\n" if urgent else ""
    await update.message.reply_text(
        f"{prefix}📌 Шаг 1/5\n\nВведи тему презентации:\n\n"
        "Например: История России, Маркетинг для стартапов",
        reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
    )

async def ai_plan_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        logger.warning("ai_plan_start: нет сообщения в update (например, не личный чат)")
        return
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    if is_blocked(user_id):
        return await msg.reply_text("❌ Вы заблокированы и не можете использовать этого бота.")
    if not HF_TOKEN:
        return await msg.reply_text(
            "❌ ИИ не настроен. Создай токен на huggingface.co/settings/tokens и добавь в .env:\n"
            "HF_TOKEN=твой_токен\n"
            "Опционально: HF_MODEL=Qwen/Qwen2.5-3B-Instruct",
            reply_markup=main_menu(),
        )
    sessions[user_id] = {"step": "ai_plan"}
    return await msg.reply_text(
        "🤖 Опиши тему презентации одним сообщением (можно указать желаемое число слайдов).\n\n"
        "Я сгенерирую примерную структуру слайдов через Hugging Face.\n\n"
        "Например: «История Древней Греции, 12 слайдов»",
        reply_markup=ReplyKeyboardMarkup([['🔙 Назад']], resize_keyboard=True),
    )

async def cancel_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_orders = [
        o for o in orders
        if o.user_id == user_id and o.status not in [STATUS_DONE, STATUS_CANCELLED]
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or str(user_id)
    text = update.message.text.strip()
    session = sessions.get(user_id)

    if is_blocked(user_id):
        return await update.message.reply_text("❌ Вы заблокированы и не можете использовать этого бота.")

    # Главное меню
    if text == '📦 Заказать презентацию':
        if is_night_now():
            sessions[user_id] = {"step": "urgent_choice"}
            return await update.message.reply_text(
                "🌙 Сейчас ночное время (00:00 – 10:00)\n\n"
                "В это время я не принимаю обычные заказы.\n\n"
                f"Срочный заказ с наценкой +{URGENT_SURCHARGE_PERCENT}%.\n\n"
                "Выбери вариант:",
                reply_markup=urgent_menu()
            )
        return await order_start(update, context)

    if text == '📄 Мои заказы':
        user_orders = [o for o in orders if o.user_id == user_id]
        if not user_orders:
            return await update.message.reply_text("У тебя пока нет заказов. 📭", reply_markup=main_menu())
        msg = f"📄 Твои заказы ({len(user_orders)} шт.):\n\n"
        for o in user_orders:
            msg += format_order(o) + "\n\n" + "─" * 25 + "\n\n"
        for i in range(0, len(msg), 4000):
            await update.message.reply_text(msg[i:i+4000])
        return

    if text == '💰 Прайс':
        return await price_info(update, context)

    if text == '❌ Отменить заказ':
        return await cancel_order_start(update, context)

    if text == '📊 Моя статистика':
        return await my_stats(update, context)

    if text == 'ℹ️ О боте':
        return await about_bot(update, context)

    if text == '📞 Связь с нами':
        return await contact_us(update, context)

    if text == '🤖 ИИ план презентации':
        return await ai_plan_start(update, context)

    if text in ['🔙 Назад', '❌ Отмена']:
        sessions.pop(user_id, None)
        return await update.message.reply_text("Возвращаюсь в главное меню 👇", reply_markup=main_menu())

    if not session:
        return await update.message.reply_text("Используй меню 👇", reply_markup=main_menu())

    step = session.get('step', '')

    if step == 'ai_plan':
        if len(text) < MIN_TOPIC_LEN:
            return await update.message.reply_text(
                "❌ Опиши тему подробнее (минимум 3 символа).",
                reply_markup=ReplyKeyboardMarkup([['🔙 Назад']], resize_keyboard=True),
            )
        await update.message.reply_text("⏳ Генерирую план через Hugging Face…")
        prompt = (
            "Ты помощник по презентациям. На русском языке составь структуру презентации: "
            "нумерованный список слайдов; для каждого слайда — заголовок и 2–4 коротких пункта, что на нём показать. "
            "Без вступления и заключения, только структура. Тема:\n"
            + text
        )
        try:
            out = await hf_generate_async(prompt)
        except Exception as e:
            logger.exception("HF Inference: %s", e)
            sessions.pop(user_id, None)
            return await update.message.reply_text(
                "❌ Не удалось получить ответ от ИИ. Проверь HF_TOKEN, модель HF_MODEL и квоту на Hugging Face.",
                reply_markup=main_menu(),
            )
        sessions.pop(user_id, None)
        for i in range(0, len(out), 4000):
            await update.message.reply_text(out[i : i + 4000])
        return await update.message.reply_text(
            "Если нужно оформление под ключ — закажи презентацию в меню 👇",
            reply_markup=main_menu(),
        )

    # Выбор заказа для отмены
    if step == 'cancel_choose':
        if text.startswith('🗑 Отменить заказ #'):
            try:
                order_id = int(text.split('#')[1].split('—')[0].strip())
            except (ValueError, IndexError):
                return await update.message.reply_text("❌ Ошибка. Попробуй снова.", reply_markup=main_menu())
            order = next((o for o in orders if o.id == order_id and o.user_id == user_id), None)
            if not order:
                sessions.pop(user_id, None)
                return await update.message.reply_text("❌ Заказ не найден.", reply_markup=main_menu())
            session['cancel_order_id'] = order_id
            session['step'] = 'cancel_confirm'
            return await update.message.reply_text(
                f"⚠️ Ты уверен, что хочешь отменить?\n\n"
                f"{format_order(order)}\n\n"
                "⚠️ Отменённый заказ нельзя восстановить!",
                reply_markup=ReplyKeyboardMarkup([['✅ Да, отменить'], ['❌ Нет, оставить']], resize_keyboard=True)
            )
        else:
            return await update.message.reply_text("Выбери заказ из списка 👇")

    # Подтверждение отмены
    if step == 'cancel_confirm':
        order_id = session.get('cancel_order_id')
        order = next((o for o in orders if o.id == order_id and o.user_id == user_id), None)
        if text == '✅ Да, отменить':
            if order:
                order.status = STATUS_CANCELLED
                persist_orders()
                update_stats_on_cancel(order)
            sessions.pop(user_id, None)
            await update.message.reply_text(f"✅ Заказ #{order_id} отменён!", reply_markup=main_menu())
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ Заказ #{order_id} отменён пользователем!\n\n"
                f"👤 @{username} (ID: {user_id})\n\n"
                f"{format_order(order) if order else 'Заказ не найден'}"
            )
        elif text == '❌ Нет, оставить':
            sessions.pop(user_id, None)
            await update.message.reply_text("👍 Заказ остался активным.", reply_markup=main_menu())
        else:
            await update.message.reply_text(
                "Выбери вариант из кнопок.",
                reply_markup=ReplyKeyboardMarkup([['✅ Да, отменить'], ['❌ Нет, оставить']], resize_keyboard=True)
            )
        return

    # Срочный заказ ночью
    if step == 'urgent_choice':
        if text == '🚨 Сделать СРОЧНЫМ (+30%)':
            sessions[user_id]['urgent'] = True
            sessions[user_id]['step'] = 'topic'
            return await update.message.reply_text(
                f"⚡ Срочный заказ! (+{URGENT_SURCHARGE_PERCENT}%)\n\n"
                "📌 Шаг 1/5\nВведи тему презентации:",
                reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
            )
        else:
            sessions.pop(user_id, None)
            return await update.message.reply_text("Оформление отменено.", reply_markup=main_menu())

    # Шаг 1 — тема
    if step == 'topic':
        if len(text) < MIN_TOPIC_LEN:
            return await update.message.reply_text("❌ Тема слишком короткая. Минимум 3 символа.")
        if len(text) > 200:
            return await update.message.reply_text("❌ Тема слишком длинная. Максимум 200 символов.")
        session['topic'] = text
        session['step'] = 'slides'
        return await update.message.reply_text(
            f"📊 Шаг 2/5\n\nСколько слайдов нужно? (от {MIN_SLIDES} до {MAX_SLIDES})\n\n"
            "Примеры:\n"
            "• 5 слайдов — краткая\n"
            "• 10-15 слайдов — стандартная\n"
            "• 20+ слайдов — подробная",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )

    # Шаг 2 — количество слайдов
    if step == 'slides':
        if not text.isdigit():
            return await update.message.reply_text("❌ Введи только число. Например: 10")
        slides = int(text)
        if not MIN_SLIDES <= slides <= MAX_SLIDES:
            return await update.message.reply_text(f"❌ Введи число от {MIN_SLIDES} до {MAX_SLIDES}.")
        session['slides'] = slides
        urgent = session.get('urgent', False)
        price = calculate_price(slides, urgent)
        minutes, ready_at = estimate_ready_time(slides)
        session.update(price)
        session['step'] = 'deadline'
        urgent_text = f"\n⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%" if urgent else ""
        return await update.message.reply_text(
            f"✅ Отлично! {slides} слайдов\n\n"
            f"💰 Расчёт стоимости:\n"
            f"   Базовая цена: {price['base']} ₽\n"
            f"   Скидка: {price['discount']} ₽"
            f"{urgent_text}\n"
            f"   Итого: {price['final']} ₽\n\n"
            f"⏱ Готовность примерно через {minutes} мин (к {ready_at})\n\n"
            "📅 Шаг 3/5\n\nУкажи дедлайн:\nНапример: 20.05.2025 или «до пятницы»",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )

    # Шаг 3 — дедлайн
    if step == 'deadline':
        if len(text) < MIN_DEADLINE_LEN:
            return await update.message.reply_text(
                "❌ Укажи дедлайн подробнее.\nНапример: 20.05.2025 или «до пятницы»"
            )
        session['deadline'] = text
        session['step'] = 'notes'
        return await update.message.reply_text(
            "📝 Шаг 4/5\n\nЕсть ли пожелания к презентации?\n\n"
            "Например:\n"
            "• Больше картинок, минимум текста\n"
            "• Деловой стиль, синие тона\n"
            "• Много графиков и диаграмм\n\n"
            "Если нет — напиши «нет»",
            reply_markup=ReplyKeyboardMarkup([['Нет пожеланий'], ['❌ Отмена']], resize_keyboard=True)
        )

    # Шаг 4 — пожелания
    if step == 'notes':
        if text == 'Нет пожеланий':
            text = 'нет'
        session['notes'] = text
        session['step'] = 'remind'
        return await update.message.reply_text(
            "🔔 Шаг 5/5\n\nХочешь напоминание за 1 день до дедлайна?\n\nНапиши «да» или «нет»",
            reply_markup=ReplyKeyboardMarkup([['✅ Да'], ['❌ Нет']], resize_keyboard=True)
        )

    # Шаг 5 — напоминание
    if step == 'remind':
        if text.lower() not in ['да', 'нет', '✅ да', '❌ нет']:
            return await update.message.reply_text("Напиши «да» или «нет» 👇")
        session['remind'] = text.lower() in ['да', '✅ да']
        session['step'] = 'confirm'
        urgent = session.get('urgent', False)
        preview = Order(
            id=len(orders) + 1,
            user_id=user_id,
            username=username,
            topic=session['topic'],
            slides=session['slides'],
            deadline=session['deadline'],
            notes=session['notes'],
            base=session['base'],
            discount=session['discount'],
            final=session['final'],
            status=STATUS_NEW,
            remind=session['remind'],
            urgent=urgent
        )
        return await update.message.reply_text(
            "🔍 Проверь свой заказ:\n\n"
            + format_order(preview)
            + "\n\n✅ Всё верно? Подтверди заказ:",
            reply_markup=ReplyKeyboardMarkup(
                [['✅ Да, всё верно'], ['❌ Нет, начать заново']], resize_keyboard=True
            )
        )

    # Подтверждение заказа
    if step == 'confirm':
        if text in ['✅ Да, всё верно', 'да']:
            urgent = session.get('urgent', False)
            new_order = Order(
                id=len(orders) + 1,
                user_id=user_id,
                username=username,
                topic=session['topic'],
                slides=session['slides'],
                deadline=session['deadline'],
                notes=session['notes'],
                base=session['base'],
                discount=session['discount'],
                final=session['final'],
                status=STATUS_WAITING_PAYMENT,
                remind=session['remind'],
                urgent=urgent
            )
            orders.append(new_order)
            persist_orders()
            stats = get_or_create_stats(user_id, username)
            stats.total_orders += 1
            persist_stats()
            sessions.pop(user_id, None)

            await update.message.reply_text(
                f"✅ Заказ #{new_order.id} создан!\n\n"
                f"💰 К оплате: {new_order.final} ₽\n\n"
                f"❗ Чтобы оплатить заказ, напишите @{ADMIN_USERNAME} 👈\n"
                f"В сообщении укажите номер заказа и дождитесь реквизитов.\n\n"
                "После оплаты вернитесь сюда и нажмите «✅ Я оплатил»",
                reply_markup=payment_menu()
            )
            sessions[user_id] = {'step': 'waiting_payment', 'order_id': new_order.id}
            await context.bot.send_message(
                ADMIN_ID,
                f"📥 Новый заказ #{new_order.id} ожидает оплаты!\n\n"
                f"👤 @{username} (ID: {user_id})\n\n"
                f"{format_order(new_order)}"
            )
        elif text in ['❌ Нет, начать заново', 'нет']:
            sessions.pop(user_id, None)
            await update.message.reply_text("❌ Заказ отменён. Начни заново 👇", reply_markup=main_menu())
        else:
            await update.message.reply_text(
                "Выбери вариант из кнопок 👇",
                reply_markup=ReplyKeyboardMarkup(
                    [['✅ Да, всё верно'], ['❌ Нет, начать заново']], resize_keyboard=True
                )
            )
        return

    # Ожидание оплаты
    if step == 'waiting_payment':
        order_id = session.get('order_id')
        if text == '✅ Я оплатил':
            order = next((o for o in orders if o.id == order_id), None)
            if not order:
                return await update.message.reply_text("❌ Заказ не найден.", reply_markup=main_menu())
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
        elif text == '❌ Отменить заказ':
            order = next((o for o in orders if o.id == order_id), None)
            if order:
                order.status = STATUS_CANCELLED
                persist_orders()
                update_stats_on_cancel(order)
            sessions.pop(user_id, None)
            await update.message.reply_text(f"✅ Заказ #{order_id} отменён.", reply_markup=main_menu())
        else:
            await update.message.reply_text(
                f"⏳ Заказ #{order_id} ожидает оплаты.\n\n"
                f"❗ Для получения реквизитов напишите @{ADMIN_USERNAME}\n"
                "После оплаты нажмите «✅ Я оплатил»",
                reply_markup=payment_menu()
            )
        return

    await update.message.reply_text("Используй меню 👇", reply_markup=main_menu())

# ===== Команды администратора =====
async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"💰 Выручка: {get_total_revenue()} ₽\n\n"
        "─" * 25 + "\n\n"
    )
    for o in orders:
        msg += format_order_short(o) + "\n\n"
    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i+4000])

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    total = len(orders)
    waiting_payment = len([o for o in orders if o.status == STATUS_WAITING_PAYMENT])
    paid = len([o for o in orders if o.status == STATUS_PAID])
    in_progress = len([o for o in orders if o.status == STATUS_WAITING_FILE])
    done = len([o for o in orders if o.status == STATUS_DONE])
    cancelled = len([o for o in orders if o.status == STATUS_CANCELLED])
    revenue = get_total_revenue()
    active_users = len(user_stats)
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
        f"👥 Пользователей: {active_users}\n"
    )
    await update.message.reply_text(msg)

async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "─" * 25 + "\n\n"
        )
    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i+4000])

async def admin_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    paid_orders = [o for o in orders if o.status == STATUS_PAID]
    if not paid_orders:
        return await update.message.reply_text("📭 Нет оплаченных заказов в работе.")
    msg = f"✅ Оплаченные заказы ({len(paid_orders)} шт.):\n\n"
    for o in paid_orders:
        msg += (
            f"{format_order(o)}\n\n"
            f"📎 Отправить свой файл: /send {o.id}\n\n"
            "─" * 25 + "\n\n"
        )
    for i in range(0, len(msg), 4000):
        await update.message.reply_text(msg[i:i+4000])

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            f"❌ Заказ #{order_id} не ожидает оплаты.\nТекущий статус: {order.status}"
        )
    order.status = STATUS_PAID
    order.paid_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    persist_orders()
    await update.message.reply_text(
        f"✅ Оплата заказа #{order_id} подтверждена!\n\n"
        f"📎 Отправить свой файл: /send {order_id}"
    )
    await context.bot.send_message(
        order.user_id,
        f"✅ Оплата подтверждена!\n\n"
        f"📋 Заказ #{order.id} принят в работу.\n"
        f"📌 Тема: {order.topic}\n"
        f"📊 Слайдов: {order.slides}\n\n"
        f"Скоро пришлю готовую презентацию! 🎉"
    )

async def reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /reject <id>")
    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")
    order.status = STATUS_PAYMENT_REJECTED
    persist_orders()
    await update.message.reply_text(f"❌ Оплата заказа #{order_id} отклонена.")
    await context.bot.send_message(
        order.user_id,
        f"❌ Оплата по заказу #{order.id} не подтверждена.\n\n"
        "Проверь перевод и реквизиты, затем попробуй снова или напиши администратору."
    )

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        order_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /send <id>\nПример: /send 3")
    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        return await update.message.reply_text("❌ Заказ не найден.")
    if order.status == STATUS_CANCELLED:
        return await update.message.reply_text(f"❌ Заказ #{order_id} отменён!")
    if order.status == STATUS_DONE:
        return await update.message.reply_text(f"✅ Заказ #{order_id} уже завершён!")
    if order.status == STATUS_WAITING_PAYMENT:
        return await update.message.reply_text(
            f"⏳ Заказ #{order_id} ещё не оплачен! Сначала: /confirm {order_id}"
        )
    admin_upload[update.effective_user.id] = order_id
    order.status = STATUS_WAITING_FILE
    persist_orders()
    await update.message.reply_text(
        f"📎 Пришли файл для заказа #{order_id}\n\n"
        f"📌 Тема: {order.topic}\n"
        f"📊 Слайдов: {order.slides}\n"
        f"💰 Сумма: {order.final} ₽\n"
        f"👤 Пользователь: @{order.username}\n\n"
        "Форматы: PDF или PPTX"
    )

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    order_id = admin_upload.get(user_id)
    if not order_id:
        return await update.message.reply_text("❌ Сначала выбери заказ через /send <id>")
    order = next((o for o in orders if o.id == order_id), None)
    if not order:
        admin_upload.pop(user_id, None)
        return await update.message.reply_text("❌ Заказ не найден.")
    await context.bot.send_document(
        chat_id=order.user_id,
        document=update.message.document.file_id,
        caption=(
            f"✅ Твоя презентация готова!\n\n"
            f"📋 ID заказа: {order.id}\n"
            f"📌 Тема: {order.topic}\n"
            f"📊 Слайдов: {order.slides}\n"
            f"💰 Оплачено: {order.final} ₽\n\n"
            "Спасибо за заказ! 🎉\nБуду рад видеть тебя снова! 😊"
        )
    )
    order.status = STATUS_DONE
    order.completed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    persist_orders()
    update_stats_on_complete(order)
    admin_upload.pop(user_id, None)
    await update.message.reply_text(
        f"✅ Файл отправлен!\nЗаказ #{order.id} закрыт. ✅\n\n"
        f"👤 Клиент: @{order.username}\n"
        f"💰 Сумма: {order.final} ₽"
    )

async def admin_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /block <user_id>")
    if target_id == ADMIN_ID:
        return await update.message.reply_text("❌ Нельзя заблокировать администратора!")
    if target_id in blocked_users:
        return await update.message.reply_text(f"⚠️ Пользователь {target_id} уже заблокирован.")
    blocked_users.append(target_id)
    await update.message.reply_text(f"✅ Пользователь {target_id} заблокирован.")

async def admin_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    try:
        target_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("❌ Используй: /unblock <user_id>")
    if target_id not in blocked_users:
        return await update.message.reply_text(f"⚠️ Пользователь {target_id} не заблокирован.")
    blocked_users.remove(target_id)
    await update.message.reply_text(f"✅ Пользователь {target_id} разблокирован.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Нет прав.")
    if not context.args:
        return await update.message.reply_text("❌ Используй: /broadcast <текст>")
    message = ' '.join(context.args)
    unique_users = list(set(o.user_id for o in orders))
    if not unique_users:
        return await update.message.reply_text("📭 Нет пользователей для рассылки.")
    sent = 0
    failed = 0
    for uid in unique_users:
        if uid in blocked_users:
            continue
        try:
            await context.bot.send_message(uid, f"📢 Сообщение от администратора:\n\n{message}")
            sent += 1
        except Exception as e:
            logger.error(f"Ошибка рассылки для {uid}: {e}")
            failed += 1
    await update.message.reply_text(
        f"✅ Рассылка завершена!\n\n📤 Отправлено: {sent}\n❌ Ошибок: {failed}"
    )

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "/send <id> — отправить свой файл клиенту\n\n"
        "👥 Пользователи:\n"
        "/block <user_id> — заблокировать\n"
        "/unblock <user_id> — разблокировать\n"
        "/broadcast <текст> — рассылка всем\n"
    )
    await update.message.reply_text(text)

# ===== Запуск бота =====
def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    os.makedirs(DATA_DIR, exist_ok=True)
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")
    if not ADMIN_ID:
        raise ValueError("❌ ADMIN_ID не найден в .env")

    # Telegram по умолчанию ждёт 5 с — на медленном интернете или при блокировках падает TimedOut
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ai", ai_plan_start))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("pending", admin_pending))
    app.add_handler(CommandHandler("paid", admin_paid))
    app.add_handler(CommandHandler("confirm", confirm_payment))
    app.add_handler(CommandHandler("reject", reject_payment))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("block", admin_block))
    app.add_handler(CommandHandler("unblock", admin_unblock))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("adminhelp", admin_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))

    print("✅ Бот запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print(f"💰 Цена за слайд: {PRICE_PER_SLIDE} ₽")
    print(f"🎁 Скидка: {DISCOUNT_PERCENT}% от {DISCOUNT_FROM_SLIDES} слайдов")
    print(f"🌙 Ночной режим: с {NIGHT_START}:00 до {NIGHT_END}:00")
    print(f"⚡ Срочная наценка: +{URGENT_SURCHARGE_PERCENT}%")
    print(f"‼️ Все оплаты через @{ADMIN_USERNAME}")
    # bootstrap_retries < 0 — повторять подключение к api.telegram.org при сбоях сети
    app.run_polling(bootstrap_retries=-1, drop_pending_updates=True)

if __name__ == "__main__":
    main()
