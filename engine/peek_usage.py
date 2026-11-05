"""Read-only: how many bytes one model run downloads from Supabase, table by table, and table row counts.
Run: python -m engine.peek_usage"""
import json
import urllib.request

from .store import get_store


def main():
    st = get_store()
    total = 0
    for t in ("games", "picks", "player_games", "bet_orders", "bet_feed", "board", "bet_log", "price_log", "injury_log"):
        n, size, start = 0, 0, 0
        while True:
            try:
                chunk = st._req("GET", f"/{t}?select=*", extra={"Range": f"{start}-{start + 999}"}) or []
            except Exception as e:
                print(f"{t}: {e}"[:200]); break
            n += len(chunk); size += len(json.dumps(chunk)); start += 1000
            if len(chunk) < 1000 or start > 60000:
                break
        print(f"{t:14} rows {n:7}  {size / 1e6:8.2f} MB{'  (stopped at 60k rows)' if start > 60000 else ''}")
        if t in ("games", "picks", "player_games"):
            total += size
    print(f"\nEach model run downloads games+picks+player_games in full: {total / 1e6:.2f} MB")
    print(f"At ~12 runs an hour that's about {total / 1e6 * 12 * 24 / 1000:.1f} GB a day")


if __name__ == "__main__":
    main()
