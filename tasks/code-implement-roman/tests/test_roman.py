import sys
sys.path.insert(0, "/workspace")

import pytest
from roman import from_roman, to_roman

CASES = {1: "I", 4: "IV", 9: "IX", 14: "XIV", 40: "XL", 90: "XC", 400: "CD",
         1994: "MCMXCIV", 2026: "MMXXVI", 3999: "MMMCMXCIX"}


def test_to_roman():
    for n, s in CASES.items():
        assert to_roman(n) == s


def test_from_roman():
    for n, s in CASES.items():
        assert from_roman(s) == n


def test_round_trip():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n


def test_out_of_range():
    for bad in (0, -1, 4000):
        with pytest.raises(ValueError):
            to_roman(bad)


def test_invalid_numeral():
    for bad in ("", "ABC", "IIII", "VX"):
        with pytest.raises(ValueError):
            from_roman(bad)
