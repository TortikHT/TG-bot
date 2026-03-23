# models.py
# Назначение: dataclass-модели данных Order и UserStats
# Импортируется storage.py, services.py, handlers.py, admin.py

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Order:
    """Модель заказа на презентацию."""
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
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%d.%m.%Y %H:%M")
    )
    paid_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class UserStats:
    """Модель статистики пользователя."""
    user_id: int
    username: str
    total_orders: int = 0
    total_spent: int = 0
    cancelled_orders: int = 0
    completed_orders: int = 0