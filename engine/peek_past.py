"""Read-only: what happened on recent games for some teams — final score, every line move (price_log), every
injury-report status with when it first appeared (injury_log), our picks and our orders.
Run: TEAMS=ATL,LAL FROM=2026-11-08 TO=2026-11-10 python -m engine.peek_past"""
import json
import os

from .store import get_store


def main():
    st = get_store()
    teams = os.environ.get("TEAMS", "DEN,POR").split(",")
    d0, d1 = os.environ.get("FROM", "2026-11-03"), os.environ.get("TO", "2026-11-10")
    games = st._req("GET", f"/games?game_date=gte.{d0}&game_date=lte.{d1}&select=*") or []
    for g in sorted(games, key=lambda x: x.get("game_date") or ""):
        if g.get("away") not in teams and g.get("home") not in teams:
            continue
        gid = g["id"]
        print("=" * 100)
        print(f"GAME {gid} {g['game_date']} {g['away']} @ {g['home']}  final={g.get('final')} "
              f"score {g.get('away_score')}-{g.get('home_score')}  tip {g.get('tip_utc')}")
        print("--- line history (home spread / total, each change)")
        last = None
        for r in st._req("GET", f"/price_log?game_id=eq.{gid}&select=ts,home_spread,total&order=ts.asc&limit=10000") or []:
            k = (r.get("home_spread"), r.get("total"))
            if k != last:
                print("   ", r["ts"][:19], "home spread", r.get("home_spread"), "total", r.get("total"))
                last = k
        print("--- injury report (both teams, this game date), in the order it appeared")
        rows = []
        for t in (g["away"], g["home"]):
            rows += st._req("GET", f"/injury_log?team=eq.{t}&game_date=eq.{g['game_date']}&select=*") or []
        for r in sorted(rows, key=lambda x: x.get("first_seen") or x.get("last_seen") or ""):
            print("   ", (r.get("first_seen") or "")[:19], "→", (r.get("last_seen") or "")[:19], r["team"],
                  r["player"], r["status"], "|", r.get("reason"))
        print("--- picks")
        for p in st._req("GET", f"/picks?game_id=eq.{gid}&select=*") or []:
            m = p.get("meta") or {}
            print("   ", json.dumps({k: p.get(k) for k in ("key", "system", "side", "bet", "line", "status", "result",
                                                          "first_seen", "last_checked", "close_line")}, default=str))
            print("       meta:", json.dumps({k: m.get(k) for k in m if k not in ("history",)}, default=str)[:1500])
        print("--- orders")
        for o in st._req("GET", f"/bet_orders?game_id=eq.{gid}&select=created_at,updated_at,venue,status,pick,"
                                "contract,count,limit_price,fill_count,fill_cost,reason&order=created_at.asc") or []:
            print("   ", o)


if __name__ == "__main__":
    main()
