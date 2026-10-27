"""Print the placed-bets record under today's rules from the live board (needs SUPABASE env).
Run: python -m engine.peek_rules_now"""
import json

from .store import get_store


def main():
    st = get_store()
    b = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    pl = b.get("placed") or {}
    s = pl.get("summary") or {}
    print("REAL:", {k: s.get(k) for k in ("w", "l", "p", "pnl", "risked", "roi", "avg_beat_close")})
    print("TODAY'S RULES:", json.dumps(pl.get("rules_now"), indent=1))
    for x in pl.get("bets") or []:
        if x["status"] == "FINAL":
            print(f"  {x['holding']:12} {x['system']:9} {x['result']} to_win {x['to_win']:6} risk {x['risk']:6} "
                  f"pnl {x['pnl']:7} t13_gap {x.get('t13_gap')} target {x.get('target')} players {x.get('players')}")


if __name__ == "__main__":
    main()
