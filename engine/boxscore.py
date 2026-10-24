"""This season's player box scores (ESPN) → an impact number on the BPM scale.

Box → BPM formula, MEASURED on 2025-26 (Basketball-Reference per-100-possession box stats vs
BPM, 379 players with 500+ minutes, minutes-weighted least squares): R² 0.908, and 0.875 on the
half of players held out of the fit. Coefficients are per 100 possessions on the floor.
"""
from __future__ import annotations

from collections import defaultdict

from .sources import get_json
from .teams import code

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"

BOX_COEF = {"const": -10.3637, "pts": 0.7729, "fga": -0.7072, "fta": -0.1990, "fg3m": 0.4742,
            "orb": 0.3064, "drb": 0.3106, "ast": 0.6365, "stl": 1.5599, "blk": 0.8229,
            "tov": -1.2258, "pf": -0.3457}
RECENT_GAMES = 3      # last N games count extra for minutes (rotation changes)
RECENT_WEIGHT = 2.0
STATS = ["pts", "fga", "fta", "fg3m", "orb", "drb", "ast", "stl", "blk", "tov", "pf"]


def _pair(v: str) -> tuple[int, int]:
    try:
        a, b = v.split("-")
        return int(a), int(b)
    except (ValueError, AttributeError):
        return 0, 0


def _int(v) -> int:
    try:
        return int(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return 0


def parse_summary(js: dict, game_id: str, game_date: str) -> list[dict]:
    """One row per player who played. Adds team possessions and game length for per-100 math."""
    rows = []
    for t in (js.get("boxscore") or {}).get("players", []):
        team = code(t["team"]["abbreviation"])
        st = t["statistics"][0]
        keys = st["keys"]
        for a in st.get("athletes", []):
            if a.get("didNotPlay") or not a.get("stats"):
                continue
            d = dict(zip(keys, a["stats"]))
            mins = _int(d.get("minutes"))
            if mins <= 0:
                continue
            fgm, fga = _pair(d.get("fieldGoalsMade-fieldGoalsAttempted"))
            f3m, f3a = _pair(d.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
            ftm, fta = _pair(d.get("freeThrowsMade-freeThrowsAttempted"))
            ath = a.get("athlete") or {}
            rows.append({
                "id": f"{game_id}-{ath.get('id')}", "game_id": game_id, "game_date": game_date,
                "team": team, "espn_id": str(ath.get("id")), "name": ath.get("displayName", ""),
                "min": mins, "pts": _int(d.get("points")), "fgm": fgm, "fga": fga,
                "fg3m": f3m, "fg3a": f3a, "ftm": ftm, "fta": fta,
                "orb": _int(d.get("offensiveRebounds")), "drb": _int(d.get("defensiveRebounds")),
                "ast": _int(d.get("assists")), "stl": _int(d.get("steals")), "blk": _int(d.get("blocks")),
                "tov": _int(d.get("turnovers")), "pf": _int(d.get("fouls")), "pm": _int(d.get("plusMinus")),
            })
    by_team = defaultdict(list)
    for r in rows:
        by_team[r["team"]].append(r)
    for team_rows in by_team.values():
        poss = sum(r["fga"] + 0.44 * r["fta"] - r["orb"] + r["tov"] for r in team_rows)
        game_min = sum(r["min"] for r in team_rows) / 5      # 48, or more with overtime
        for r in team_rows:
            r["team_poss"] = round(poss, 1)
            r["game_min"] = round(game_min, 1)
    return rows


def fetch_box(game_id: str, game_date: str, fetch=get_json) -> list[dict]:
    return parse_summary(fetch(SUMMARY.format(game_id)), game_id, game_date)


def team_dates(rows: list[dict]) -> dict[str, list[str]]:
    """Each team's game dates this season (games with a box score), oldest first."""
    out: dict[str, set] = defaultdict(set)
    for r in rows:
        out[r["team"]].add(str(r["game_date"]))
    return {t: sorted(d) for t, d in out.items()}


def recent_players(rows: list[dict], last_n: int = 3) -> dict[str, list[dict]]:
    """Who played for each team in its last `last_n` games — only players whose latest game was for
    that team (a traded player counts for his new team). {team: [{espn_id, name, mpg, games}]}"""
    latest: dict[str, tuple] = {}
    for r in rows:
        k = r["espn_id"]
        if k not in latest or str(r["game_date"]) > latest[k][0]:
            latest[k] = (str(r["game_date"]), r["team"])
    dates = team_dates(rows)
    acc: dict[tuple, dict] = {}
    for r in rows:
        t = r["team"]
        if latest[r["espn_id"]][1] != t or str(r["game_date"]) not in dates[t][-last_n:] or r["min"] <= 0:
            continue
        a = acc.setdefault((t, r["espn_id"]), {"espn_id": str(r["espn_id"]), "name": r["name"], "min": 0.0, "games": 0})
        a["min"] += r["min"]
        a["games"] += 1
    out: dict[str, list[dict]] = defaultdict(list)
    for (t, _), a in acc.items():
        n = len(dates[t][-last_n:])
        out[t].append({**a, "mpg": a["min"] / n})
    return dict(out)


def season_impact(rows: list[dict]) -> dict[str, dict]:
    """Per player (keyed by ESPN id): minutes, games, minutes per game and box impact (BPM scale)."""
    acc: dict[str, dict] = {}
    for r in rows:
        p = acc.setdefault(r["espn_id"], {"name": r["name"], "min": 0.0, "games": 0, "poss": 0.0,
                                          **{s: 0.0 for s in STATS}, "dates": [], "log": []})
        p["min"] += r["min"]
        p["games"] += 1
        p["dates"].append(r["game_date"])
        p["log"].append((str(r["game_date"]), r["min"]))
        if r.get("game_min"):
            p["poss"] += r["team_poss"] * r["min"] / r["game_min"]
        for s in STATS:
            p[s] += r[s]
    out = {}
    for pid, p in acc.items():
        if p["poss"] <= 0:
            continue
        per100 = {s: p[s] / p["poss"] * 100 for s in STATS}
        bpm = BOX_COEF["const"] + sum(BOX_COEF[s] * per100[s] for s in STATS)
        # role minutes lean on the latest games: a coach's rotation change shows up there first
        log = sorted(p["log"])
        wts = [RECENT_WEIGHT if i >= len(log) - RECENT_GAMES else 1.0 for i in range(len(log))]
        out[pid] = {"name": p["name"], "min": p["min"], "games": p["games"],
                    "mpg": p["min"] / p["games"], "bpm_live": bpm,
                    "w_min": sum(w * m for w, (_, m) in zip(wts, log)), "w_games": sum(wts),
                    "last3": [m for _, m in log[-RECENT_GAMES:]], "last_date": log[-1][0]}
    return out
