"""Read-only: what shot data is available for free. ESPN play-by-play (shot locations?) and NBA.com tracking
(closest-defender shooting, shot locations). Prints what it finds."""
import json
import urllib.request

from . import backtest as BT
from . import sources


def main():
    games = sources.espn_day(__import__("datetime").date(2026, 11, 9)) or []
    gid = next((g.id for g, _ in games if g.final), None)
    js = sources.get_json(BT.SUM.format(gid)) or {}
    print("ESPN summary keys:", sorted(js.keys()))
    pl = js.get("plays") or []
    shots = [p for p in pl if p.get("shootingPlay")]
    print("plays:", len(pl), "| shooting plays:", len(shots))
    for p in shots[:3]:
        print(json.dumps({k: p.get(k) for k in ("text", "coordinate", "scoreValue", "scoringPlay", "type", "participants")})[:400])
    hdr = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/", "Origin": "https://www.nba.com",
           "Accept": "application/json", "x-nba-stats-origin": "stats", "x-nba-stats-token": "true"}
    for name, url in (("NBA.com closest-defender shooting", "https://stats.nba.com/stats/leaguedashplayerptshot?CloseDefDistRange=0-2%20Feet%20-%20Very%20Tight&LeagueID=00&PerMode=Totals&Season=2025-26&SeasonType=Regular%20Season"),
                      ("NBA.com shot locations", "https://stats.nba.com/stats/leaguedashplayershotlocations?DistanceRange=By%20Zone&LeagueID=00&PerMode=Totals&Season=2025-26&SeasonType=Regular%20Season")):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            rs = d.get("resultSets") or d.get("resultSet")
            rs = rs[0] if isinstance(rs, list) else rs
            print(name, ": OK", len(rs.get("rowSet") or []), "rows; columns", (rs.get("headers") or [])[:12])
        except Exception as e:
            print(name, ": FAILED", str(e)[:120])


if __name__ == "__main__":
    main()
