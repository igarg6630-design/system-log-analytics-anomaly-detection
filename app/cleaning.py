"""Pandas cleaning: types, levels, missing values, message normalisation."""
from typing import Dict, List, Tuple

import pandas as pd

LEVEL_MAP = {
    "WARN": "WARNING",
    "ERR": "ERROR",
    "SEVERE": "ERROR",
    "FATAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "TRACE": "DEBUG",
}
VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def clean_logs(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """NOTE: duplicates yahan drop nahi karte. Logs mein same second mein
    identical lines legit hoti hain (aur spike ka asli signal wahi hai).
    Double-upload ko upload-level sha256 check se rokte hain."""
    report = {"input_rows": int(len(df))}
    df = df.copy()

    raw_ts = df["ts"].astype(str).str.replace(",", ".", regex=False)
    parsed = pd.to_datetime(raw_ts, errors="coerce")  # fast path: ek hi format
    miss = parsed.isna()
    if miss.any():  # mixed formats (pandas pehle row ka format maan leta hai) -> retry
        parsed[miss] = pd.to_datetime(raw_ts[miss], errors="coerce", format="mixed")
    df["ts"] = parsed
    report["bad_timestamps_dropped"] = int(df["ts"].isna().sum())
    df = df.dropna(subset=["ts"])

    df["level"] = df["level"].astype(str).str.upper().replace(LEVEL_MAP)
    report["unknown_levels"] = int((~df["level"].isin(VALID_LEVELS)).sum())
    df.loc[~df["level"].isin(VALID_LEVELS), "level"] = "UNKNOWN"

    df["service"] = df["service"].fillna("unknown").astype(str).str.strip()
    df["message"] = df["message"].fillna("").astype(str).str.strip()
    # numbers/IPs hata kar group-able key (top errors ke liye)
    df["message_key"] = (
        df["message"].str.replace(r"\d+", "#", regex=True).str.slice(0, 120)
    )

    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    report["output_rows"] = int(len(df))
    return df, report


def to_records(df: pd.DataFrame) -> List[dict]:
    """DataFrame -> list of plain dicts (Mongo/JSON friendly)."""
    out = []
    for r in df.itertuples(index=False):
        out.append(
            {
                "ts": r.ts.to_pydatetime(),
                "level": r.level,
                "service": r.service,
                "message": r.message,
                "message_key": r.message_key,
                "ip": None if pd.isna(r.ip) else r.ip,
                "status": None if pd.isna(r.status) else int(r.status),
            }
        )
    return out
