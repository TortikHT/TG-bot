# storage.py
# Назначение: всё что связано с чтением/записью данных на диск
# Импортируется services.py, handlers.py, admin.py

import json
import os
from dataclasses import asdict
from typing import Dict, List

from models import Order, UserStats
from config import (
    DATA_DIR, ORDERS_PATH,
    STATS_PATH, BLOCKED_PATH
)


# ===== Низкоуровневые JSON-утилиты =====

def load_json(filepath: str, default=None):
    """
    Загружает JSON из файла.
    Возвращает default если файл не существует или повреждён.
    """
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def save_json(filepath: str, data):
    """Сохраняет данные в JSON, создавая папки при необходимости."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===== Загрузка данных при старте =====

def load_orders() -> List[Order]:
    """Загружает список заказов из orders.json."""
    raw = load_json(ORDERS_PATH, default=[])
    result = []
    for d in raw:
        try:
            result.append(Order(**d))
        except Exception:
            continue
    return result


def load_user_stats() -> Dict[int, UserStats]:
    """Загружает статистику пользователей из user_stats.json."""
    raw = load_json(STATS_PATH, default={})
    result = {}
    for k, v in raw.items():
        try:
            result[int(k)] = UserStats(**v)
        except Exception:
            continue
    return result


def load_blocked_users() -> List[int]:
    """
    Загружает список заблокированных пользователей.
    ФИКС: blocked_users теперь персистентны между перезапусками.
    """
    return load_json(BLOCKED_PATH, default=[])


# ===== Сохранение данных =====

def persist_orders(orders: List[Order]):
    """Сохраняет все заказы на диск."""
    save_json(ORDERS_PATH, [asdict(o) for o in orders])


def persist_stats(user_stats: Dict[int, UserStats]):
    """Сохраняет статистику пользователей на диск."""
    save_json(STATS_PATH, {str(k): asdict(v) for k, v in user_stats.items()})


def persist_blocked(blocked_users: List[int]):
    """
    Сохраняет список заблокированных пользователей.
    ФИКС: теперь блокировки не сбрасываются после перезапуска.
    """
    save_json(BLOCKED_PATH, blocked_users)


# ===== Генерация нового ID заказа =====

def next_order_id(orders: List[Order]) -> int:
    """
    Генерирует следующий уникальный ID заказа.
    ФИКС: раньше использовался len(orders)+1 — баг при отмене/удалении.
    Теперь берём max(id) + 1, что гарантирует уникальность.
    """
    if not orders:
        return 1
    return max(o.id for o in orders) + 1