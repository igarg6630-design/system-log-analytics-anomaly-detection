"""Pure-logic tests (FastAPI/DB ki zarurat nahi): pytest ya `python tests/test_core.py`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cleaning import clean_logs, to_records
from app.detector import DetectionConfig, detect_anomalies, detect_bruteforce, run_all
from app.parser import parse_lines
from app.sample_data import generate_lines
from app.store import InMemoryLogStore


def _prep(lines):
    df, bad = parse_lines(lines)
    df, _ = clean_logs(df)
    return df, bad


def test_parser_handles_formats_and_garbage():
    lines = [
        "2026-10-27 10:00:00 [ERROR] auth: boom ip=1.2.3.4 status=500",
        "2026-10-27T10:00:01,250 WARN api: slow",
        "this is not a log line",
        "",
    ]
    df, bad = _prep(lines)
    assert bad == 1 and len(df) == 2
    assert df.loc[0, "ip"] == "1.2.3.4" and df.loc[0, "status"] == 500
    assert set(df["level"]) == {"ERROR", "WARNING"}  # WARN normalised


def test_identical_lines_not_deduplicated():
    line = "2026-10-27 10:00:00 [ERROR] svc: same thing"
    df, _ = _prep([line] * 50)
    assert len(df) == 50  # spike signal bachna chahiye


def test_spike_and_bruteforce_detected_without_noise():
    df, _ = _prep(generate_lines(hours=6, seed=42))
    alerts = run_all(df, DetectionConfig())
    spikes = [a for a in alerts if a["alert_type"] == "spike"]
    brutes = [a for a in alerts if a["alert_type"] == "brute_force"]
    assert len(spikes) == 1 and spikes[0]["severity"] == "critical"
    assert spikes[0]["details"]["top_service"] == "payment-service"
    assert len(brutes) == 1 and brutes[0]["details"]["ip"] == "203.0.113.77"
    assert brutes[0]["details"]["failures"] == 75


def test_normal_traffic_has_no_alerts():
    df, _ = _prep(generate_lines(hours=4, seed=7, spike_errors=0, spike_len=0, brute_force=False))
    assert run_all(df, DetectionConfig()) == []


def test_small_bump_below_min_errors_ignored():
    # 6 errors/min jaise normal se thoda upar -> alert nahi (min_errors guard)
    df, _ = _prep(generate_lines(hours=3, seed=3, spike_errors=7, spike_len=2, brute_force=False))
    assert detect_anomalies(df, DetectionConfig()) == []


def test_inmemory_store_search_and_counts():
    df, _ = _prep(generate_lines(hours=1, seed=1))
    s = InMemoryLogStore()
    s.insert_many(1, to_records(df))
    total, items = s.search({"upload_id": 1, "level": "ERROR", "q": "timeout"}, limit=5)
    assert total >= len(items) > 0 and all(i["level"] == "ERROR" for i in items)
    assert sum(s.level_counts(1).values()) == len(df)
    assert s.top_messages(1, 3)[0]["count"] > 0
    s.delete_upload(1)
    assert s.level_counts(1) == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
