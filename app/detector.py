from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

ERROR_LEVELS = {"ERROR", "CRITICAL"}
FAILED_AUTH_RE = r"(?i)failed login|authentication failed|invalid password|unauthorized"


@dataclass
class DetectionConfig:
    freq: str = "1min"
    window: int = 60              # baseline window (kitne bins)
    z_threshold: float = 3.5
    min_errors: int = 10          # isse kam errors/min kabhi alert nahi
    min_traffic: int = 200        # isse kam requests/min par traffic alert nahi
    use_isolation_forest: bool = True
    contamination: float = 0.01
    bruteforce_threshold: int = 20
    bruteforce_window: str = "5min"


# ---------- feature frame ----------
def build_frame(df: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
    d = df.set_index("ts")
    total = d.resample(freq).size()
    errors = d[d["level"].isin(ERROR_LEVELS)].resample(freq).size().reindex(total.index, fill_value=0)
    warnings = d[d["level"] == "WARNING"].resample(freq).size().reindex(total.index, fill_value=0)
    frame = pd.DataFrame(
        {
            "total": total,
            "errors": errors,
            "warnings": warnings,
            "unique_ips": d.resample(freq)["ip"].nunique(),
            "unique_services": d.resample(freq)["service"].nunique(),
        }
    ).fillna(0)
    frame["error_ratio"] = np.where(frame["total"] > 0, frame["errors"] / frame["total"], 0.0)
    return frame


# ---------- statistical ----------
def _baseline_z(series: pd.Series, window: int, min_periods: int = 10):
    base = series.shift(1)  # current point baseline se bahar
    mean = base.rolling(window, min_periods=min_periods).mean()
    std = base.rolling(window, min_periods=min_periods).std()
    # shuru ke bins (jab history kam ho) ke liye global robust fallback
    gmed = float(series.median())
    gstd = max(1.4826 * float(np.median(np.abs(series - gmed))), 1.0)
    mean = mean.fillna(gmed)
    std = std.fillna(gstd).clip(lower=1.0)  # flat series par divide-by-zero se bachao
    return mean, (series - mean) / std


def _iforest_flags(frame: pd.DataFrame, cfg: DetectionConfig) -> pd.Series:
    if len(frame) < 30:
        return pd.Series(False, index=frame.index)
    cols = ["errors", "total", "error_ratio", "unique_ips", "unique_services"]
    X = StandardScaler().fit_transform(frame[cols].to_numpy(dtype=float))
    model = IsolationForest(n_estimators=200, contamination=cfg.contamination, random_state=42)
    pred = model.fit_predict(X)
    return pd.Series((pred == -1) & (frame["errors"].to_numpy() >= cfg.min_errors), index=frame.index)


def _severity(z: float) -> str:
    if z >= 10:
        return "critical"
    if z >= 6:
        return "high"
    if z >= 4:
        return "medium"
    return "low"


def _context(df: pd.DataFrame, start, end, metric: str) -> Dict:
    w = df[(df["ts"] >= start) & (df["ts"] < end)]
    if metric == "errors":
        w = w[w["level"].isin(ERROR_LEVELS)]
    if w.empty:
        return {}
    msgs = w["message_key"].value_counts().head(3)
    return {
        "top_service": str(w["service"].value_counts().index[0]),
        "affected_services": [str(s) for s in w["service"].value_counts().head(5).index],
        "top_messages": [{"message": str(k), "count": int(v)} for k, v in msgs.items()],
        "unique_ips": int(w["ip"].nunique()),
    }


def detect_anomalies(df: pd.DataFrame, cfg: DetectionConfig = None) -> List[Dict]:
    cfg = cfg or DetectionConfig()
    if df.empty:
        return []
    frame = build_frame(df, cfg.freq)
    step = pd.Timedelta(cfg.freq)

    cand: Dict[tuple, Dict] = {}  # (metric, ts) -> info
    z_cache = {}
    for metric, col, floor in (("errors", "errors", cfg.min_errors), ("traffic", "total", cfg.min_traffic)):
        mean, z = _baseline_z(frame[col], cfg.window)
        z_cache[metric] = (mean, z)
        mask = (z > cfg.z_threshold) & (frame[col] >= floor)
        for ts in frame.index[mask]:
            cand[(metric, ts)] = {"methods": {"zscore"}}

    if cfg.use_isolation_forest:
        for ts in frame.index[_iforest_flags(frame, cfg)]:
            cand.setdefault(("errors", ts), {"methods": set()})["methods"].add("isolation_forest")

    alerts: List[Dict] = []
    for metric in ("errors", "traffic"):
        col = "errors" if metric == "errors" else "total"
        mean, z = z_cache[metric]
        keys = sorted(ts for (m, ts) in cand if m == metric)
        groups, cur = [], []
        for ts in keys:  # lagatar aane wale bins ko ek incident banao
            if cur and ts - cur[-1] > step:
                groups.append(cur)
                cur = []
            cur.append(ts)
        if cur:
            groups.append(cur)

        for g in groups:
            methods = set().union(*(cand[(metric, t)]["methods"] for t in g))
            peak = float(frame.loc[g, col].max())
            base = float(mean.loc[g].mean())
            zmax = float(z.loc[g].max())
            start, end = g[0], g[-1] + step
            ctx = _context(df, start, end, metric)
            label = "errors/min" if metric == "errors" else "requests/min"
            alerts.append(
                {
                    "alert_type": "spike",
                    "metric": metric,
                    "window_start": start.to_pydatetime(),
                    "window_end": end.to_pydatetime(),
                    "observed": peak,
                    "baseline": round(base, 2),
                    "score": round(zmax, 2),
                    "severity": _severity(zmax),
                    "method": "+".join(sorted(methods)),
                    "summary": (
                        f"{int(peak)} {label} (normal ~{base:.1f}, z={zmax:.1f}); "
                        f"{len(g)} min window, service: {ctx.get('top_service', '?')}"
                    ),
                    "details": ctx,
                }
            )
    alerts.sort(key=lambda a: a["window_start"])
    return alerts


# ---------- brute force ----------
def detect_bruteforce(df: pd.DataFrame, cfg: DetectionConfig = None) -> List[Dict]:
    """Per-IP sliding window (bin boundary par attack split nahi hota)."""
    cfg = cfg or DetectionConfig()
    if df.empty:
        return []
    failed = df["status"].isin([401, 403]) | df["message"].str.contains(FAILED_AUTH_RE, regex=True, na=False)
    sub = df[failed & df["ip"].notna()]
    if sub.empty:
        return []
    wdelta = pd.Timedelta(cfg.bruteforce_window)
    bins = max(int(wdelta / pd.Timedelta("1min")), 1)
    counts = sub["ip"].value_counts()
    alerts = []
    for ip in counts[counts >= cfg.bruteforce_threshold].index:
        per_min = sub[sub["ip"] == ip].set_index("ts").resample("1min").size()
        roll = per_min.rolling(bins, min_periods=1).sum()
        hit = roll[roll >= cfg.bruteforce_threshold]
        if hit.empty:
            continue
        # lagatar hit bins ko ek incident banao
        groups, cur = [], [hit.index[0]]
        for ts in hit.index[1:]:
            if ts - cur[-1] > pd.Timedelta("1min"):
                groups.append(cur)
                cur = []
            cur.append(ts)
        groups.append(cur)
        for g in groups:
            start = g[0] - pd.Timedelta(minutes=bins - 1)
            end = g[-1] + pd.Timedelta("1min")
            win = per_min[(per_min.index >= start) & (per_min.index < end)]
            start = win[win > 0].index[0]  # asli pehla failed attempt
            n = int(win.sum())
            ratio = float(hit.loc[g].max()) / cfg.bruteforce_threshold
            alerts.append(
                {
                    "alert_type": "brute_force",
                    "metric": "failed_auth",
                    "window_start": start.to_pydatetime(),
                    "window_end": end.to_pydatetime(),
                    "observed": float(n),
                    "baseline": float(cfg.bruteforce_threshold),
                    "score": round(ratio, 2),
                    "severity": "high" if ratio >= 5 else "medium",
                    "method": "threshold",
                    "summary": f"{n} failed auth attempts from {ip} (peak {int(hit.loc[g].max())} in {cfg.bruteforce_window})",
                    "details": {"ip": str(ip), "failures": n},
                }
            )
    alerts.sort(key=lambda a: a["window_start"])
    return alerts


def run_all(df: pd.DataFrame, cfg: DetectionConfig = None) -> List[Dict]:
    cfg = cfg or DetectionConfig()
    out = detect_anomalies(df, cfg) + detect_bruteforce(df, cfg)
    out.sort(key=lambda a: a["window_start"])
    return out
