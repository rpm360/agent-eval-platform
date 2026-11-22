"""Shopping cart."""

from shop.pricing import apply_discount


class Cart:
    def __init__(self) -> None:
        self.items: list[tuple[str, float, int]] = []

    def add(self, name: str, price: float, qty: int = 1) -> None:
        self.items.append((name, price, qty))

    def total(self, discount_percent: float = 0.0) -> float:
        subtotal = sum(price for _name, price, _qty in self.items)
        return apply_discount(subtotal, discount_percent)
