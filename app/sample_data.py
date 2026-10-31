"""Synthetic log generator (testing/demo ke liye).

python -m app.sample_data --hours 6 --out data/sample.log
Normal: 2-5 errors/min. Beech mein 3 minute ka spike (~100 errors/min) aur
ek brute-force IP (203.0.113.77) inject hota hai.
"""
import argparse
from datetime import datetime, timedelta
from typing import List

import numpy as np

SERVICES = ["api-gateway", "auth-service", "order-service", "payment-service", "db-proxy"]
NORMAL_ERRORS = [
    ("db-proxy", "Database connection timeout after {n}s"),
    ("order-service", "Failed to process order id={n}"),
    ("api-gateway", "Upstream timeout on /api/items/{n}"),
    ("payment-service", "Card gateway returned error code {n}"),
]


def generate_lines(
    start: datetime = datetime(2026, 10, 27, 0, 0, 0),
    hours: int = 6,
    seed: int = 42,
    spike_at_minute: int = None,
    spike_len: int = 3,
    spike_errors: int = 100,
    brute_force: bool = True,
) -> List[str]:
    rng = np.random.default_rng(seed)
    total_min = hours * 60
    spike_at = int(total_min * 0.7) if spike_at_minute is None else spike_at_minute
    bf_at = int(total_min * 0.4)
    events = []  # (datetime, level, service, message)

    def rand_ip():
        return f"10.0.{rng.integers(0, 5)}.{rng.integers(1, 250)}"

    for m in range(total_min):
        t0 = start + timedelta(minutes=m)
        n_info = int(rng.integers(40, 80))
        n_warn = int(rng.integers(3, 9))
        n_err = int(rng.integers(2, 6))
        in_spike = spike_at <= m < spike_at + spike_len
        if in_spike:
            n_err = spike_errors + int(rng.integers(-10, 10))

        for _ in range(n_info):
            t = t0 + timedelta(seconds=int(rng.integers(0, 60)))
            events.append((t, "INFO", str(rng.choice(SERVICES)),
                           f"GET /api/users/{rng.integers(1, 5000)} completed ip={rand_ip()} "
                           f"status=200 latency_ms={rng.integers(10, 300)}"))
        for _ in range(n_warn):
            t = t0 + timedelta(seconds=int(rng.integers(0, 60)))
            events.append((t, "WARNING", str(rng.choice(SERVICES)),
                           f"Slow response {rng.integers(800, 2000)}ms ip={rand_ip()} status=200"))
        for _ in range(n_err):
            t = t0 + timedelta(seconds=int(rng.integers(0, 60)))
            if in_spike:
                events.append((t, "ERROR", "payment-service",
                               f"Upstream payment provider unavailable (attempt {rng.integers(1, 9)})"))
            else:
                svc, tpl = NORMAL_ERRORS[int(rng.integers(0, len(NORMAL_ERRORS)))]
                events.append((t, "ERROR", svc, tpl.format(n=rng.integers(1, 100))))
        if rng.random() < 0.3:  # kabhi kabhi ek failed login (normal noise)
            t = t0 + timedelta(seconds=int(rng.integers(0, 60)))
            events.append((t, "WARNING", "auth-service",
                           f"Failed login for user u{rng.integers(1, 99)} ip={rand_ip()} status=401"))

        if brute_force and bf_at <= m < bf_at + 5:
            for _ in range(15):
                t = t0 + timedelta(seconds=int(rng.integers(0, 60)))
                events.append((t, "WARNING", "auth-service",
                               "Failed login for user admin ip=203.0.113.77 status=401"))

    events.sort(key=lambda e: e[0])
    return [f"{t:%Y-%m-%d %H:%M:%S} [{lvl}] {svc}: {msg}" for t, lvl, svc, msg in events]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/sample.log")
    a = ap.parse_args()
    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    lines = generate_lines(hours=a.hours, seed=a.seed)
    with open(a.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(lines)} lines -> {a.out}")
