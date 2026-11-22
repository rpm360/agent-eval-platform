"""Pricing helpers."""


def apply_discount(price: float, percent: float) -> float:
    """Return price after applying a percentage discount (e.g. 10 -> 10% off)."""
    return round(price * percent / 100, 2)
