import sys
sys.path.insert(0, "/workspace")

import pytest
from temperature import celsius_to_fahrenheit


def test_valid_values():
    assert celsius_to_fahrenheit(0) == 32
    assert celsius_to_fahrenheit(100) == 212
    assert abs(celsius_to_fahrenheit(-40.0) - (-40.0)) < 1e-9
    assert abs(celsius_to_fahrenheit(-273.15) - (-459.67)) < 1e-6


def test_type_errors():
    for bad in ("10", None, [1], True, False):
        with pytest.raises(TypeError):
            celsius_to_fahrenheit(bad)


def test_below_absolute_zero():
    with pytest.raises(ValueError):
        celsius_to_fahrenheit(-300)
    with pytest.raises(ValueError):
        celsius_to_fahrenheit(-273.16)
