# config.py
# Назначение: все константы и переменные окружения
# Импортируется всеми модулями бота

import os
from dotenv import load_dotenv

load_dotenv()

# ===== Вспомогательная функция =====
def _int_env(name: str, default: int = 0) -> int:
    """Безопасно читает int из переменных окружения."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())

# ===== Telegram =====
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = _int_env("ADMIN_ID", 0)
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")

# ===== Цены =====
PRICE_PER_SLIDE: int = _int_env("PRICE_PER_SLIDE", 25)
DISCOUNT_PERCENT: int = _int_env("DISCOUNT_PERCENT", 10)
DISCOUNT_FROM_SLIDES: int = _int_env("DISCOUNT_FROM_SLIDES", 10)

# ===== Заказы =====
URGENT_SURCHARGE_PERCENT: int = 30
NIGHT_START: int = 0
NIGHT_END: int = 10
MAX_SLIDES: int = 100
MIN_SLIDES: int = 5
MIN_TOPIC_LEN: int = 3
MIN_DEADLINE_LEN: int = 3
MINUTES_PER_5_SLIDES: int = 15

# ===== Статусы заказов =====
STATUS_NEW = "новый"
STATUS_WAITING_PAYMENT = "ожидает_оплату"
STATUS_PAID = "оплачен"
STATUS_WAITING_FILE = "ожидает_файл"
STATUS_DONE = "завершён"
STATUS_CANCELLED = "отменён"
STATUS_PAYMENT_REJECTED = "оплата_отклонена"

# ===== Пути к файлам хранилища =====
DATA_DIR = "data"
ORDERS_PATH = "data/orders.json"
STATS_PATH = "data/user_stats.json"
BLOCKED_PATH = "data/blocked_users.json"