`/workspace/moving_average.py` contains:

```python
def moving_average(values, window):
    result = []
    for i in range(len(values) - window):
        result.append(sum(values[i:i + window]) / window)
    return result
```

Users report that the output is missing a value. Write a short technical explanation to
`/workspace/EXPLANATION.md` covering: (1) the root cause, (2) the exact fix, and (3) at least
one edge case the function still does not handle.
