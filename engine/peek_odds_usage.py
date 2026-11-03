"""Read-only: how many model runs happened per hour over the last 2 days (each run writes one price_log
timestamp), so Odds API credits can be split between this model and anything else sharing the key.
Run: python -m engine.peek_odds_usage"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from .store import get_store


def main():
    st = get_store()
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    ts = set()
    off = 0
    while True:
        rows = st._req("GET", f"/price_log?ts=gte.{since}&select=ts&order=ts.asc&limit=1000&offset={off}") or []
        ts |= {r["ts"] for r in rows}
        if len(rows) < 1000:
            break
        off += 1000
    by_hour = Counter(t[:13] for t in ts)
    print(f"model runs in the last 48h: {len(ts)}")
    for h in sorted(by_hour):
        print(f"  {h}:00 UTC  {by_hour[h]:3d} runs")


if __name__ == "__main__":
    main()
