"""Read-only: every live order since Oct 31 (all fields), the picks on four games, and the bettor's
notes about them. Written to answer Caden's Nov 2 questions. Run: python -m engine.peek_nov2"""
import json

from .store import get_store

GAMES = ("BKN", "NYK", "WAS", "ORL", "BOS", "HOU", "TOR", "LAL")


def main():
    st = get_store()
    orders = st._req("GET", "/bet_orders?created_at=gte.2026-10-31T04:00:00Z&select=*&order=created_at.asc") or []
    print(f"=== {len(orders)} orders since Oct 31 (all modes)")
    for o in orders:
        o = {k: v for k, v in o.items() if k not in ("raw",)}
        print(json.dumps(o, default=str)[:1500])
        print()
    picks = [p for p in st.load_picks() if str(p.get("tip_utc") or p.get("tip") or "") >= "2026-11-01"]
    print(f"\n=== picks tipping Nov 1+ ({len(picks)})")
    for p in picks:
        if any(t in json.dumps(p, default=str) for t in GAMES):
            q = dict(p)
            meta = {k: v for k, v in (q.pop("meta", None) or {}).items() if k != "card_snap"}
            print(json.dumps(q, default=str)[:900], "| meta:", json.dumps(meta, default=str)[:900])
            print()
    logs = st._req("GET", "/bet_log?ts=gte.2026-11-02T20:00:00Z&select=ts,message&order=ts.asc&limit=4000") or []
    print(f"\n=== bettor notes Nov 2 3pm ET onward mentioning BKN/NYK ({len(logs)} rows scanned)")
    last = None
    for r in logs:
        m = str(r.get("message", ""))
        if ("BKN" in m or "NYK" in m or "Brooklyn" in m or "New York" in m) and m[:200] != last:
            print(r["ts"], m[:900])
            last = m[:200]


if __name__ == "__main__":
    main()
