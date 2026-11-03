"""Read-only: is the new bettor live and is the site showing the new record?
Run: python -m engine.check_live_now"""
from .store import get_store


def main():
    st = get_store()
    print("=== Kalshi standing orders marked unfilled/resting since Nov 1 (the new bettor re-reads these)")
    for o in st._req("GET", "/bet_orders?venue=eq.kalshi&mode=eq.live&created_at=gte.2026-11-01T04:00:00Z"
                            "&select=created_at,updated_at,status,pick,contract,count,fill_count,fill_cost,reason"
                            "&order=created_at.asc") or []:
        print(" ", o)
    print("\n=== bettor log, newest 40")
    for r in st._req("GET", "/bet_log?select=ts,level,message&order=ts.desc&limit=40") or []:
        print(" ", r["ts"][:19], r["level"], r["message"][:220])
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    p = b.get("placed") or {}
    rn, s = p.get("rules_now") or {}, p.get("summary") or {}
    print("\n=== live site board generated", b.get("generated_at"))
    print("  record under today's rules:", rn.get("w"), "-", rn.get("l"), "-", rn.get("p"), "pnl", rn.get("pnl"),
          "| open", rn.get("open"), "at risk", rn.get("at_risk"))
    print("  real account:", s.get("w"), "-", s.get("l"), "pnl", s.get("pnl"))
    print("  has combo_live (new code):", "combo_live" in b, "| report card has systems_p3:",
          "systems_p3" in (b.get("report_card") or {}))
    for r in p.get("bets") or []:
        R = r.get("rules") or {}
        print(f"   {r['status']:6} {r.get('result') or '-'} {r['system']:9} {r['holding']:22} {r['venue_name']:18} "
              f"real {r.get('pnl')}  {'counted ' + str(R.get('pnl')) if R.get('counted') else 'hidden: ' + str(R.get('why'))}")


if __name__ == "__main__":
    main()
