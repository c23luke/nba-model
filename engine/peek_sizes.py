"""Read-only: how many bytes the main reads pull from Supabase (egress), to find what uses the quota.
Run: python -m engine.peek_sizes"""
import json
import time

from .store import get_store


def size(st, path, extra=None):
    t = time.time()
    r = st._req("GET", path, extra=extra)
    return len(json.dumps(r)), (len(r) if isinstance(r, list) else 1), round(time.time() - t, 1)


def main():
    st = get_store()
    for name, path, extra in [
        ("board (the site loads this every 60 s per open tab)", "/board?id=eq.1&select=data", None),
        ("picks, all rows (model, every run)", "/picks?select=*", {"Range": "0-9999"}),
        ("games, all rows (model, every run)", "/games?select=*", {"Range": "0-9999"}),
        ("player_games, all (model, every 30 min)", "/player_games?select=*", {"Range": "0-99999"}),
        ("bet_orders live filled (model, every run)", "/bet_orders?mode=eq.live&or=(fill_count.gt.0,status.eq.resting)&select=*", None),
        ("bet_feed (bettor, every minute)", "/bet_feed?select=*", None),
        ("bet_log last 50", "/bet_log?select=*&order=ts.desc&limit=50", None),
        ("injury_log all", "/injury_log?select=*", {"Range": "0-99999"}),
        ("price_log last 2 days", "/price_log?select=*&ts=gte.2026-11-08T00:00:00Z", {"Range": "0-99999"}),
    ]:
        try:
            b, n, s = size(st, path, extra)
            print(f"{name:55} {b / 1e6:8.2f} MB  {n:6} rows  {s}s")
        except Exception as e:
            print(f"{name:55} failed: {str(e)[:120]}")
    b = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    print("\nboard parts:")
    for k, v in sorted(b.items(), key=lambda kv: -len(json.dumps(kv[1], default=str))):
        print(f"  {k:28} {len(json.dumps(v, default=str)) / 1e3:9.1f} KB")


if __name__ == "__main__":
    main()
