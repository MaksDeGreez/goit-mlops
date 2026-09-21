#!/usr/bin/env python3
"""Send traffic to the prediction API and report what came back.

Four kinds of traffic, one per `--mode`:

* `normal`  — rows taken from the dataset snapshot, the traffic a healthy
  service sees;
* `drift`   — the same rows with three features moved, so the drift job has
  something to find;
* `invalid` — a mix of broken bodies, every one of them an HTTP 400;
* `burst`   — as fast as the machine can, so the rate limit answers 429.

The script only uses the standard library, so it runs with plain `python3` and
needs no virtual environment:

    python3 scripts/send_traffic.py --mode normal --count 250 --rate 15
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FEATURES = [
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
]

# scripts/send_traffic.py -> final-project/data/
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "california_housing.csv"

DEFAULT_URL = "http://localhost:8001"

# Clients used by the burst mode when nothing else is asked for.
BURST_CLIENTS = 8

# The API refuses anything outside the ranges California really has, so the
# drifted rows are clipped back into them. A refused request would tell us
# nothing about drift. The ranges are the ones in services/inference/README.md.
LIMITS = {
    "MedInc": (0.0, 20.0),
    "HouseAge": (0.0, 100.0),
    "AveRooms": (0.01, 200.0),
    "AveBedrms": (0.01, 50.0),
    "Population": (1.0, 50000.0),
    "AveOccup": (0.01, 1500.0),
    "Latitude": (32.0, 42.5),
    "Longitude": (-125.0, -114.0),
}

VALID_ROW = {
    "MedInc": 8.3252,
    "HouseAge": 41.0,
    "AveRooms": 6.9841,
    "AveBedrms": 1.0238,
    "Population": 322.0,
    "AveOccup": 2.5556,
    "Latitude": 37.88,
    "Longitude": -122.23,
}


def load_rows(path: Path) -> list[dict[str, float]]:
    """The eight feature columns of the dataset snapshot."""
    with open(path, newline="") as handle:
        return [{name: float(row[name]) for name in FEATURES} for row in csv.DictReader(handle)]


def clip(row: dict[str, float]) -> dict[str, float]:
    """Keep every value inside the range the API accepts."""
    clipped = {}
    for name, value in row.items():
        low, high = LIMITS[name]
        clipped[name] = min(max(value, low), high)
    return clipped


def normal_rows(rows: list[dict[str, float]], count: int, rng: random.Random) -> list[dict]:
    return [dict(rng.choice(rows)) for _ in range(count)]


def drifted_rows(rows: list[dict[str, float]], count: int, rng: random.Random) -> list[dict]:
    """The same rows with three features moved far enough to be noticed.

    These three changes are not a random choice. PSI compares bins built from
    the reference sample, and a column with a very long tail (`AveOccup`,
    `Population`) hardly moves even when the values are multiplied by five.
    The numbers here are the ones measured in services/drift-monitor/README.md.
    """
    drifted = []
    for row in normal_rows(rows, count, rng):
        row["MedInc"] = row["MedInc"] * 2.5
        row["HouseAge"] = rng.uniform(1.0, 6.0)
        row["Population"] = row["Population"] * 2
        drifted.append(clip(row))
    return drifted


def invalid_payloads(count: int, rng: random.Random) -> list[object]:
    """Bodies that must all be refused with HTTP 400."""
    missing = {name: value for name, value in VALID_ROW.items() if name != "MedInc"}
    out_of_range = {**VALID_ROW, "Latitude": 88.0}
    wrong_type = {**VALID_ROW, "MedInc": "8.3"}
    unknown_field = {**VALID_ROW, "MedIncome": 8.3}
    not_json = b"{not json at all"
    broken = [missing, out_of_range, wrong_type, unknown_field, not_json]
    return [broken[index % len(broken)] for index in range(count)]


def post(url: str, payload: object, timeout: float = 10.0) -> tuple[int, float, str]:
    """One POST. Returns the status, the time it took and the body."""
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    request = urllib.request.Request(  # noqa: S310 - the URL is a command line option
        url, data=data, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    except urllib.error.URLError as error:
        return 0, (time.perf_counter() - started) * 1000, str(error.reason)
    return status, (time.perf_counter() - started) * 1000, body.decode(errors="replace")


def percentile(values: list[float], share: float) -> float:
    """The value below which `share` of the measurements fall."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(round(share * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def send(
    url: str, payloads: list[object], rate: float, concurrency: int = 1
) -> tuple[list[int], list[float], dict]:
    """Send every payload and collect the answers.

    One client sends them one after the other, paced by `rate`. Several
    clients send them at the same time and ignore the rate, which is the only
    way to go over a limit of 20 requests per second: one request through the
    Docker network takes long enough that a single client never gets there.
    """
    predict_url = url.rstrip("/") + "/predict"

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(lambda payload: post(predict_url, payload), payloads))
    else:
        results = []
        gap = 1.0 / rate if rate > 0 else 0.0
        for payload in payloads:
            started = time.perf_counter()
            results.append(post(predict_url, payload))
            if gap:
                time.sleep(max(0.0, gap - (time.perf_counter() - started)))

    statuses = [status for status, _, _ in results]
    latencies = [latency for _, latency, _ in results]
    examples: dict[int, str] = {}
    for status, _, body in results:
        examples.setdefault(status, body)
    return statuses, latencies, examples


def save_csv(path: str, rows: list[dict], statuses: list[int]) -> int:
    """Write the rows the service really answered to a CSV file.

    The drift job reads its live data from Loki in the cluster. There is no
    Loki on a laptop, so the same rows are written here and the job is started
    with `--current-csv`.
    """
    accepted = [row for row, status in zip(rows, statuses, strict=True) if status == 200]
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEATURES)
        writer.writeheader()
        writer.writerows(accepted)
    return len(accepted)


def report(
    mode: str, url: str, statuses: list[int], latencies: list[float], examples: dict
) -> None:
    counts: dict[int, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1

    print(f"{mode} traffic to {url}: {len(statuses)} requests")
    print(f"{'status':>8}  {'count':>6}")
    print(f"{'-' * 8}  {'-' * 6}")
    for status in sorted(counts):
        name = "no answer" if status == 0 else str(status)
        print(f"{name:>8}  {counts[status]:>6}")
    print(
        f"latency ms: p50 {percentile(latencies, 0.5):.1f}  p95 {percentile(latencies, 0.95):.1f}"
    )

    for status in sorted(examples):
        if status != 200:
            print(f"example {status}: {examples[status][:200]}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["normal", "drift", "invalid", "burst"], default="normal")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"base URL, default {DEFAULT_URL}")
    parser.add_argument("--count", type=int, default=100, help="how many requests to send")
    parser.add_argument(
        "--rate",
        type=float,
        default=10.0,
        help="requests per second; 0 means as fast as possible",
    )
    parser.add_argument("--seed", type=int, default=42, help="seed of the row sample")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="clients sending at the same time; 0 means 1, or 8 in burst mode",
    )
    parser.add_argument(
        "--data",
        default=str(DATA_PATH),
        help="CSV with the feature rows; the default is the dataset of this repository",
    )
    parser.add_argument("--save-csv", help="write the accepted rows to this CSV file")
    parser.add_argument(
        "--expect",
        type=int,
        help="exit 1 unless at least one answer had this status code",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rng = random.Random(args.seed)  # noqa: S311 - traffic shaping, not cryptography

    if args.mode == "invalid":
        payloads: list[object] = invalid_payloads(args.count, rng)
        rows: list[dict] = []
    else:
        rows = load_rows(Path(args.data))
        maker = drifted_rows if args.mode == "drift" else normal_rows
        rows = maker(rows, args.count, rng)
        payloads = list(rows)

    # A burst is only a burst without pacing and with several clients.
    burst = args.mode == "burst"
    rate = 0.0 if burst else args.rate
    concurrency = args.concurrency or (BURST_CLIENTS if burst else 1)
    statuses, latencies, examples = send(args.url, payloads, rate, concurrency)
    report(args.mode, args.url, statuses, latencies, examples)

    if args.save_csv and rows:
        saved = save_csv(args.save_csv, rows, statuses)
        print(f"saved {saved} accepted rows to {args.save_csv}")

    if args.expect is not None and args.expect not in statuses:
        print(f"expected at least one answer with status {args.expect}, got none")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
