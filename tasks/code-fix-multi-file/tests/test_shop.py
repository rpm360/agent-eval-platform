import sys
sys.path.insert(0, "/workspace")

from shop.cart import Cart
from shop.pricing import apply_discount


def test_apply_discount():
    assert apply_discount(100.0, 25) == 75.0
    assert apply_discount(50.0, 0) == 50.0


def test_cart_total_uses_quantity():
    c = Cart()
    c.add("apple", 1.50, 4)
    c.add("bread", 3.00, 1)
    assert c.total() == 9.00


def test_cart_total_with_discount():
    c = Cart()
    c.add("apple", 1.50, 4)
    c.add("bread", 3.00, 1)
    assert c.total(10) == 8.10
