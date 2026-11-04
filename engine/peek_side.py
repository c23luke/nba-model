"""Read-only: every order on one team's side of an upcoming game, and the bettor's notes on it.
Run: TEAM=CHI python -m engine.peek_side"""
import os

from .store import get_store


def main():
    st, team = get_store(), os.environ.get("TEAM", "CHI")
    for o in st._req("GET", f"/bet_orders?side=eq.{team}&mode=eq.live&created_at=gte.2026-11-03T04:00:00Z&select=*&order=created_at.asc") or []:
        print({k: o.get(k) for k in ("created_at", "venue", "market", "contract", "pick", "system", "bet_key", "line",
                                     "model_price", "ask_at_check", "limit_price", "count", "stake", "status",
                                     "fill_count", "fill_cost", "fees", "ev", "reason")})
    for r in st._req("GET", f"/bet_log?message=ilike.*{team}*&ts=gte.2026-11-03T04:00:00Z&select=ts,level,message&order=ts.asc&limit=60") or []:
        if "skip" not in r["message"][:20]:
            print(r["ts"][:19], r["level"], r["message"][:300])


if __name__ == "__main__":
    main()
