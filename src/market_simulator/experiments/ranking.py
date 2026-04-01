from __future__ import annotations

import pandas as pd


def rank_results(df: pd.DataFrame, primary: str, secondary: str) -> pd.DataFrame:
    return df.sort_values(
        by=[primary, secondary],
        ascending=[False, True],
    ).reset_index(drop=True)