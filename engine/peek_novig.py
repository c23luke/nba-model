"""Read-only: is Novig switched on, did the key check see it, what did the bettor do with it.
Run: python -m engine.peek_novig"""
from .store import get_store


def main():
    st = get_store()
    print("=== settings")
    print(" ", (st._req("GET", "/bet_settings?id=eq.1&select=*"
                        ) or [{}])[0])
    print("\n=== newest key checks")
    for r in st._req("GET", "/bet_log?select=ts,message&message=like.Key%20check*&order=ts.desc&limit=3") or []:
        print(" ", r["ts"][:19], r["message"])
    print("\n=== log lines mentioning Novig, newest 30")
    for r in st._req("GET", "/bet_log?select=ts,level,message&message=ilike.*novig*&order=ts.desc&limit=30") or []:
        print(" ", r["ts"][:19], r["level"], r["message"][:500])
    print("\n=== last run summary skips mentioning Novig")
    for r in st._req("GET", "/bet_log?select=ts,message,data&message=like.run%20(*&order=ts.desc&limit=1") or []:
        print(" ", r["ts"][:19], r["message"])
        for s in (r.get("data") or {}).get("skips") or []:
            print("    -", s.get("pick"), "|", str(s.get("reason"))[:600])
    print("\n=== Novig orders")
    for o in st._req("GET", "/bet_orders?venue=eq.novig&select=created_at,mode,status,pick,contract,count,stake,"
                            "fill_count,fill_cost,reason&order=created_at.desc&limit=20") or []:
        print(" ", o)


if __name__ == "__main__":
    main()
