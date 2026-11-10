"""WITH / WITHOUT SPLITS (Caden 2026-11-10): when a player sits, who ACTUALLY gets his minutes?

Everyone assumes the backup gets the bump. Often the coach spreads it, plays a different lineup, or the "obvious"
guy's minutes don't move. This season's box scores answer it per pair: for each rotation player A on a team, every
teammate B's minutes, points, rebounds and assists in games A played vs games A missed.
Only games B himself played count (a game B missed says nothing about his role). Player-level, this season only.
"""
from __future__ import annotations

from collections import defaultdict

from .personnel import norm

ROT_MPG = 20.0          # A must average this when he plays...
ROT_GAMES = 5           # ...over at least this many games
STATS = ("min", "pts", "reb", "ast")


def _stat(r: dict, k: str) -> float:
    if k == "reb":
        return (r.get("orb") or 0) + (r.get("drb") or 0)
    return r.get(k) or 0


def splits(box_rows: list[dict]) -> dict[str, dict[str, dict[str, dict]]]:
    """team -> absent player (normalised) -> teammate (normalised) ->
    {"name", "n_with", "n_wo", "min_with", "min_wo", "pts_with", "pts_wo", "reb_with", ...} (averages)."""
    games = defaultdict(set)                         # team -> game ids
    rows = defaultdict(dict)                         # (team, game) -> norm name -> row
    names = {}
    for r in box_rows:
        t, g = r.get("team"), r.get("game_id")
        if not t or not g:
            continue
        games[t].add(g)
        k = norm(r.get("name") or "")
        rows[(t, g)][k] = r
        names[k] = r.get("name")
    out = {}
    for t, gs in games.items():
        played = defaultdict(set)                    # name -> games with minutes
        for g in gs:
            for k, r in rows[(t, g)].items():
                if (r.get("min") or 0) > 0:
                    played[k].add(g)
        rot = [a for a, pg in played.items() if len(pg) >= ROT_GAMES
               and sum(rows[(t, g)][a]["min"] for g in pg) / len(pg) >= ROT_MPG]
        team = {}
        for a in rot:
            missed = gs - played[a]
            if not missed:
                continue
            per = {}
            for b, pg in played.items():
                if b == a:
                    continue
                w, wo = pg & played[a], pg & missed
                if not w or not wo:
                    continue
                d = {"name": names[b], "n_with": len(w), "n_wo": len(wo)}
                for s in STATS:
                    d[f"{s}_with"] = round(sum(_stat(rows[(t, g)][b], s) for g in w) / len(w), 1)
                    d[f"{s}_wo"] = round(sum(_stat(rows[(t, g)][b], s) for g in wo) / len(wo), 1)
                per[b] = d
            if per:
                team[a] = per
        out[t] = team
    return out
