def normalize_weights(strategies):
    total = sum(s.weight for s in strategies)
    if total == 0:
        raise ValueError("Total weight cannot be zero")

    for s in strategies:
        s.weight = s.weight / total

    return strategies