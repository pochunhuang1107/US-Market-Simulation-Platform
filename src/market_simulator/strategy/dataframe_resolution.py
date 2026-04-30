from __future__ import annotations

import pandas as pd


def infer_tradable_symbol(bundle) -> str | None:
    if "symbol" not in bundle.tradable.columns or bundle.tradable.empty:
        return None
    symbol = bundle.tradable.iloc[0]["symbol"]
    return str(symbol) if pd.notna(symbol) else None


def _same_symbol(left: str | None, right: str | None) -> bool:
    return bool(left and right and left.upper() == right.upper())


def _reference_key(references: dict[str, pd.DataFrame], symbol: str) -> str | None:
    if symbol in references:
        return symbol

    wanted = symbol.upper()
    for key in references:
        if key.upper() == wanted:
            return key
    return None


def resolve_market_data_target(bundle, symbol: str | None, tradable_symbol: str | None):
    effective_tradable_symbol = tradable_symbol or infer_tradable_symbol(bundle)
    target = symbol or effective_tradable_symbol
    if target is None or _same_symbol(target, effective_tradable_symbol):
        return None, bundle.tradable

    key = _reference_key(bundle.references, target)
    if key is not None:
        return key, bundle.references[key]

    raise ValueError(f"Missing market data for reference symbol {target}")


def resolve_market_dataframe(bundle, symbol: str | None, tradable_symbol: str | None):
    return resolve_market_data_target(bundle, symbol, tradable_symbol)[1]


def tradable_row_date(bundle, index: int) -> pd.Timestamp:
    return pd.Timestamp(bundle.tradable.iloc[index]["date"])


def row_position_for_date(df: pd.DataFrame, date: pd.Timestamp) -> int | None:
    if "date" not in df.columns:
        return None

    matches = pd.to_datetime(df["date"]) == pd.Timestamp(date)
    positions = matches[matches].index
    if len(positions) == 0:
        return None

    return int(df.index.get_loc(positions[0]))
