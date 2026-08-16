"""
Pull NYC Motor Vehicle Collisions from the Socrata API.

    py scripts/pull_data.py --start-year 2019 --end-year 2025 --out data/raw/crashes_raw.csv

Design constraints, each earned by a bug or a review finding:

1. EVERY request carries `$order=crash_date`. Socrata has no default sort, so a
   request without one returns rows in storage order and pagination silently
   repeats and drops rows. This is the bug that produced an 8,000-row sample
   that was 89% one year. It is the whole reason this script exists.

2. Uses the `.csv` RESOURCE endpoint, never the bulk export. The bulk
   `rows.csv?accessType=DOWNLOAD` returns a DIFFERENT schema: uppercase
   space-separated headers and MM/DD/YYYY dates. The resource endpoint returns
   the snake_case ISO-date schema clean_crash_data.py speaks.

3. Resumable. An 848,000-row pull over a throttled connection will get
   interrupted. Re-running appends from where it stopped rather than restarting.

4. Named rescues, no bare excepts. Timeout and 429 back off and retry; 403 fails
   loudly because retrying a bad token forever helps nobody.

        page 0        page 1        page N
      ┌────────┐    ┌────────┐    ┌────────┐
      │ $limit │───▶│ $limit │───▶│ $limit │──▶ append to --out
      │ $offset│    │ $offset│    │ $offset│
      │ $order │    │ $order │    │ $order │   ◀── never omit this
      └────────┘    └────────┘    └────────┘
           │             │             │
           └── 429/5xx/timeout ─▶ backoff, retry, resume from same offset
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path

import requests

# Some networks (including the one this was developed on) intercept TLS. requests
# ships its own certifi bundle and the intercepting proxy resets the handshake:
#   ConnectionResetError(10054, 'An existing connection was forcibly closed')
# truststore makes Python use the OS certificate store instead, which already
# trusts the interceptor. Optional: on a clean network the import just fails and
# nothing changes. Same root cause as `uv` needing --system-certs here.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

DATASET = "h9gi-nx95"
BASE = f"https://data.cityofnewyork.us/resource/{DATASET}.csv"
COUNT_URL = f"https://data.cityofnewyork.us/resource/{DATASET}.json"

PAGE_SIZE = 50_000
MAX_RETRIES = 6
TIMEOUT = 120


class PullError(RuntimeError):
    """Fatal, non-retryable. A bad token or a malformed query."""


def load_token() -> str | None:
    """Read the app token from the environment, loading .env if present.

    python-dotenv is optional so the script still runs in CI without it.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    tok = os.environ.get("NYC_OPEN_DATA_APP_TOKEN", "").strip()
    return tok or None


def _where(start_year: int, end_year: int) -> str:
    return (f"crash_date >= '{start_year}-01-01T00:00:00'"
            f" AND crash_date < '{end_year + 1}-01-01T00:00:00'")


def total_rows(session: requests.Session, start_year: int, end_year: int) -> int:
    r = session.get(COUNT_URL,
                    params={"$select": "count(1) AS n",
                            "$where": _where(start_year, end_year)},
                    timeout=TIMEOUT)
    r.raise_for_status()
    return int(r.json()[0]["n"])


def fetch_page(session: requests.Session, offset: int,
               start_year: int, end_year: int) -> str:
    """One page of CSV text. Retries on transient failures, raises on fatal ones."""
    params = {
        "$limit": PAGE_SIZE,
        "$offset": offset,
        # NEVER remove this. See constraint 1 in the module docstring.
        "$order": "crash_date",
        "$where": _where(start_year, end_year),
    }
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(BASE, params=params, timeout=TIMEOUT)
        except requests.Timeout:
            if attempt == MAX_RETRIES:
                raise PullError(f"timed out {MAX_RETRIES}x at offset {offset}")
            print(f"    timeout at offset {offset:,}, retry {attempt}/{MAX_RETRIES} "
                  f"in {delay:.0f}s", flush=True)
            time.sleep(delay); delay *= 2
            continue
        except requests.ConnectionError as e:
            if attempt == MAX_RETRIES:
                raise PullError(f"connection failed {MAX_RETRIES}x at offset {offset}: {e}")
            print(f"    connection error at offset {offset:,}, retry {attempt}/"
                  f"{MAX_RETRIES} in {delay:.0f}s", flush=True)
            time.sleep(delay); delay *= 2
            continue

        if r.status_code == 200:
            return r.text
        if r.status_code == 403:
            raise PullError(
                "403 Forbidden. The app token is present but rejected. Check "
                "NYC_OPEN_DATA_APP_TOKEN in .env, or remove it to pull "
                "unauthenticated (slower but works)."
            )
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == MAX_RETRIES:
                raise PullError(f"HTTP {r.status_code} {MAX_RETRIES}x at offset {offset}")
            wait = float(r.headers.get("Retry-After", delay))
            print(f"    HTTP {r.status_code} at offset {offset:,}, backing off "
                  f"{wait:.0f}s (retry {attempt}/{MAX_RETRIES})", flush=True)
            time.sleep(wait); delay *= 2
            continue
        raise PullError(f"HTTP {r.status_code} at offset {offset}: {r.text[:300]}")

    raise PullError(f"exhausted retries at offset {offset}")


def rows_already_written(path: Path) -> tuple[int, list[str] | None]:
    """(data row count, header) for resume. (0, None) if absent or empty."""
    if not path.exists() or path.stat().st_size == 0:
        return 0, None
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return 0, None
        return sum(1 for _ in reader), header


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--restart", action="store_true",
                    help="ignore any existing output and pull from scratch")
    args = ap.parse_args()

    if args.start_year > args.end_year:
        print("ERROR: --start-year is after --end-year", file=sys.stderr)
        return 2

    token = load_token()
    session = requests.Session()
    if token:
        session.headers["X-App-Token"] = token
        print(f"App token: loaded ({len(token)} chars). Higher rate limit.")
    else:
        print("App token: NONE. Pulling unauthenticated, which is throttled and "
              "slower.\n  Get one at "
              "https://data.cityofnewyork.us/profile/edit/developer_settings\n"
              "  then put it in .env as NYC_OPEN_DATA_APP_TOKEN=...")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.restart and args.out.exists():
        args.out.unlink()

    expected = total_rows(session, args.start_year, args.end_year)
    done, header = rows_already_written(args.out)
    if done:
        print(f"Resuming: {done:,} rows already in {args.out}")
    print(f"Target: {expected:,} rows, {args.start_year}-{args.end_year}, "
          f"page size {PAGE_SIZE:,}")

    started = time.time()
    offset = done
    with args.out.open("a", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        while offset < expected:
            page = fetch_page(session, offset, args.start_year, args.end_year)
            rows = list(csv.reader(io.StringIO(page)))
            if not rows:
                print("  empty page, stopping early")
                break
            page_header, data = rows[0], rows[1:]

            if header is None:
                writer.writerow(page_header)
                header = page_header
            elif page_header != header:
                # Guards the ragged-schema failure: the API can vary its column
                # set. Silently appending mismatched rows would corrupt the file.
                raise PullError(
                    "column set changed mid-pull.\n"
                    f"  expected: {header}\n  got:      {page_header}"
                )

            if not data:
                break
            writer.writerows(data)
            out.flush()
            offset += len(data)
            pct = offset / expected * 100
            rate = offset / max(time.time() - started, 1e-9)
            eta = (expected - offset) / rate if rate else 0
            print(f"  {offset:>9,} / {expected:,} ({pct:5.1f}%)  "
                  f"{rate:,.0f} rows/s  ETA {eta/60:.1f} min", flush=True)

    final, _ = rows_already_written(args.out)
    mb = args.out.stat().st_size / 1_048_576
    print(f"\nDone: {final:,} rows -> {args.out} ({mb:.1f} MB) "
          f"in {(time.time()-started)/60:.1f} min")
    if final != expected:
        print(f"WARNING: expected {expected:,}, got {final:,}. "
              f"Re-run to resume; the dataset may also have changed mid-pull.")
        return 1
    print("Row count matches the API's own count.")
    print(f"\nNext: py scripts/clean_crash_data.py {args.out} data/processed/crashes_cleaned")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PullError as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to resume.", file=sys.stderr)
        sys.exit(130)
