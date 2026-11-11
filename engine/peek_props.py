"""Read-only: which books carry NBA player props on our odds feed (Pinnacle? our exchanges?), and credits left.
Costs about 3-6 credits (one game, points/rebounds/assists, US + EU regions). Never prints the key."""
import os
import urllib.parse

from . import sources

KEY = os.environ.get("ODDS_API_KEY", "")
BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"


def main():
    meta = {}
    evs = sources.get_json(f"{BASE}/events?apiKey={urllib.parse.quote(KEY)}", meta=meta) or []
    print("events listed:", len(evs), "| credits left:", meta.get("x-requests-remaining"), "used:", meta.get("x-requests-used"))
    if not evs:
        return
    ev = evs[0]
    print("game:", ev.get("away_team"), "@", ev.get("home_team"), ev.get("commence_time"))
    meta = {}
    js = sources.get_json(f"{BASE}/events/{ev['id']}/odds?apiKey={urllib.parse.quote(KEY)}&regions=us,us_ex,eu"
                          "&markets=player_points,player_rebounds,player_assists&oddsFormat=american", meta=meta) or {}
    print("credits left:", meta.get("x-requests-remaining"), "| this call cost:", meta.get("x-requests-last"))
    for bk in js.get("bookmakers") or []:
        mk = {m["key"]: len(m.get("outcomes") or []) for m in bk.get("markets") or []}
        print(f"  {bk['key']:22} {mk}")
    pin = next((b for b in js.get("bookmakers") or [] if b["key"] == "pinnacle"), None)
    if pin:
        for m in pin["markets"][:1]:
            for o in m["outcomes"][:6]:
                print("   pinnacle sample:", m["key"], o.get("description"), o.get("name"), o.get("point"), o.get("price"))


if __name__ == "__main__":
    main()
