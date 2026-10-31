"""Raw log lines -> pandas DataFrame.

Supported format (flexible):
2026-10-27 10:15:32 [ERROR] auth-service: Database timeout ip=10.0.0.5 status=500
- timestamp: 'YYYY-MM-DD HH:MM:SS' (T separator aur .ms / ,ms bhi chalega)
- level: [ERROR] ya ERROR
- service: ek token, uske baad ':'
"""
import re
from typing import Iterable, Tuple

import pandas as pd

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+"
    r"\[?(?P<level>[A-Za-z]+)\]?\s+"
    r"(?P<service>[\w\-.]+):\s*(?P<message>.*)$"
)
IP_RE = r"\b((?:\d{1,3}\.){3}\d{1,3})\b"
STATUS_RE = r"(?i)\bstatus[=: ]\s*(\d{3})\b"

COLUMNS = ["ts", "level", "service", "message"]


def parse_lines(lines: Iterable[str]) -> Tuple[pd.DataFrame, int]:
    """Returns (dataframe, unparsed_line_count)."""
    rows, unparsed = [], 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if m:
            rows.append(m.groupdict())
        else:
            unparsed += 1

    df = pd.DataFrame(rows, columns=COLUMNS, dtype=object)
    if df.empty:
        df["ip"] = pd.Series(dtype=object)
        df["status"] = pd.Series(dtype="float64")
        return df, unparsed

    df["ip"] = df["message"].str.extract(IP_RE)[0]
    df["status"] = pd.to_numeric(df["message"].str.extract(STATUS_RE)[0], errors="coerce")
    return df, unparsed
