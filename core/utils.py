"""
Shared utility functions used across all apps.
"""
import uuid
import hashlib
from datetime import datetime
from django.utils import timezone


def generate_order_number(prefix: str = "ORD") -> str:
    """Generate a unique order number: ORD-20240101-A1B2C3"""
    date_str = timezone.now().strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{date_str}-{unique}"


def generate_sku(name: str, category: str = "") -> str:
    """Auto-generate a SKU from product name and category."""
    base = f"{category[:3]}{name[:4]}".upper().replace(" ", "")
    unique = uuid.uuid4().hex[:4].upper()
    return f"{base}-{unique}"


def mask_sensitive(value: str, visible_chars: int = 4) -> str:
    """Mask all but last N chars. e.g. ****1234"""
    if not value or len(value) <= visible_chars:
        return value
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """Returns percentage change between two values."""
    if old_value == 0:
        return 100.0 if new_value > 0 else 0.0
    return round(((new_value - old_value) / old_value) * 100, 2)


def slugify_unique(text: str) -> str:
    """Create a slug from text + short UUID suffix to ensure uniqueness."""
    from django.utils.text import slugify
    base_slug = slugify(text)
    unique = uuid.uuid4().hex[:6]
    return f"{base_slug}-{unique}"


def parse_date_range(request) -> tuple:
    """
    Extract date_from and date_to from request query params.
    Returns (datetime, datetime) tuple. Defaults to last 30 days.
    """
    from datetime import timedelta
    date_from_str = request.query_params.get("date_from")
    date_to_str = request.query_params.get("date_to")

    date_to = timezone.now()
    date_from = date_to - timedelta(days=30)

    if date_from_str:
        try:
            date_from = timezone.datetime.fromisoformat(date_from_str)
            if timezone.is_naive(date_from):
                date_from = timezone.make_aware(date_from)
        except ValueError:
            pass

    if date_to_str:
        try:
            date_to = timezone.datetime.fromisoformat(date_to_str)
            if timezone.is_naive(date_to):
                date_to = timezone.make_aware(date_to)
        except ValueError:
            pass

    return date_from, date_to
