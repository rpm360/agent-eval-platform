def moving_average(values, window):
    result = []
    for i in range(len(values) - window):
        result.append(sum(values[i:i + window]) / window)
    return result
