`/workspace/temperature.py` defines `celsius_to_fahrenheit(c)`.

Add input validation without changing correct results:

- Raise `TypeError` if `c` is not an `int` or `float` (note: `bool` must also be rejected).
- Raise `ValueError` if `c` is below absolute zero (-273.15 °C). Exactly -273.15 is allowed.
