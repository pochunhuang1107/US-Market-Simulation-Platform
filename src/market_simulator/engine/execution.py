def transaction_cost(notional, cost_bps):
    return notional * (cost_bps / 10000.0)
