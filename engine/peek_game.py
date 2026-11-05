"""Read-only: why the players model's read on one game changed. Prints the line history (price_log), the
players-model view on the live board now (ratings, scenarios, who's day-to-day, evidence), and every pick row for
the game. Run: GAME=TOR python -m engine.peek_game   (a team code playing in the next 2 days)"""
import json
import os

from .store import get_store


def main():
    team = os.environ.get("GAME", "TOR")
    st = get_store()
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    g = next((x for x in b.get("slate") or [] if team in (x.get("away"), x.get("home"))), None)
    if not g:
        print("no game for", team, "on the board slate")
        return
    gid = g["game_id"]
    print("game", gid, g["away"], "@", g["home"], "tip", g.get("tip_utc"), "| board generated", b.get("generated_at"))
    print("market now: home spread", g.get("home_spread"), "from", g.get("line_source"), g.get("line_books"),
          "updated", g.get("line_updated"))
    print("\n=== line history (consensus home spread, each logged run)")
    last = None
    for r in st._req("GET", f"/price_log?game_id=eq.{gid}&select=ts,home_spread,total&order=ts.asc&limit=10000") or []:
        if r.get("home_spread") != last:
            print(" ", r["ts"][:19], "home spread", r.get("home_spread"), "total", r.get("total"))
            last = r.get("home_spread")
    print("\n=== players model view now")
    print(json.dumps(g.get("personnel"), indent=1, default=str))
    print("\n=== pick rows for this game")
    for p in st._req("GET", f"/picks?game_id=eq.{gid}&select=*") or []:
        print(json.dumps(p, default=str))


if __name__ == "__main__":
    main()
