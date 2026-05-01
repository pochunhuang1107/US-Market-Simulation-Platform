from __future__ import annotations

import numpy as np
import pandas as pd

def compute_sma(series, window):
    return series.rolling(window=window, min_periods=window).mean()

def compute_ema(series, window):
    return series.ewm(span=window, adjust=False, min_periods=window).mean()

def compute_rsi(close, window=14):
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_realized_volatility(close, window):
    daily_returns = close.pct_change()
    return daily_returns.rolling(window=window, min_periods=window).std() * np.sqrt(252)

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": macd, "macd_signal": sig, "macd_hist": macd - sig})

def compute_kd(high, low, close, window=9):
    ll = low.rolling(window=window, min_periods=window).min()
    hh = high.rolling(window=window, min_periods=window).max()
    rsv = (close - ll) / (hh - ll) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False, min_periods=window).mean()
    d = k.ewm(alpha=1 / 3, adjust=False, min_periods=window).mean()
    return pd.DataFrame({"k": k, "d": d})
