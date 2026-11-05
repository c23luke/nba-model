"""Read-only: every order and every non-heartbeat log line since a time (default today 8 AM ET).
Run: python -m engine.peek_today"""
import os

from .store import get_store


def main():
    st = get_store()
    since = os.environ.get("SINCE", "2026-11-05T04:00:00Z")
    print("=== orders since", since)
    for o in st._req("GET", f"/bet_orders?created_at=gte.{since}&select=created_at,updated_at,venue,mode,status,pick,"
                            "contract,count,limit_price,stake,fill_count,fill_cost,reason&order=created_at.asc") or []:
        print(" ", o)
    print("\n=== log since", since, "(key checks left out)")
    off = 0
    while True:
        rows = st._req("GET", f"/bet_log?ts=gte.{since}&select=ts,level,message,data&order=ts.asc&limit=500&offset={off}") or []
        for r in rows:
            m = r["message"]
            if m.startswith("Key check"):
                continue
            if m.startswith("run (") and m.endswith("0 skipped") and "0 action" in m:
                continue
            print(" ", r["ts"][:19], r["level"], m[:700])
            for s in (r.get("data") or {}).get("skips") or []:
                print("      skip:", s.get("pick"), "|", str(s.get("reason"))[:900])
        if len(rows) < 500:
            break
        off += 500


if __name__ == "__main__":
    main()
