"""X2 — FADE THE TEAM MISSING 2+ ROTATION PLAYERS (tracking only; never bet until it earns it).

Measured (engine/measure_cluster.py, 2024-25 + 2025-26, vs the CLOSING line): when a team is missing 2+ rotation
players (20+ minutes a game over its last 10, in at least 5 of them) — more than its opponent — and at least one of
them played the team's previous game (fresh news), the opponent covered 249-199 (55.6%); 2024-25 56.1%, 2025-26 55.0%.
The market moves the line about a point but not enough. Long-known absences show nothing (37-33). Same-position
clusters were NOT special (118-111): the edge is in how many players are missing, not which position.
"""
from __future__ import annotations

from collections import defaultdict

from .personnel import norm
from .systems import Pick

ROT_MPG = 20.0
WINDOW = 10
MIN_GAMES = 5
RECORD = "2 seasons vs the close: opponent covered 249-199 (55.6%), both seasons 55-56%"


def rotations(box_rows: list[dict]) -> dict[str, dict[str, dict]]:
    """team -> {normalised name: {"name", "mpg", "last": played the team's latest game}} over its last 10 games."""
    games = defaultdict(dict)                       # team -> game_id -> date
    mins = defaultdict(lambda: defaultdict(dict))   # team -> name -> game_id -> minutes
    names = {}
    for r in box_rows:
        t, gid = r.get("team"), r.get("game_id")
        if not t or not gid:
            continue
        games[t][gid] = str(r.get("game_date") or "")
        k = norm(r.get("name") or "")
        names[(t, k)] = r.get("name")
        mins[t][k][gid] = int(r.get("min") or 0)
    out = {}
    for t, gs in games.items():
        last = sorted(gs, key=lambda g: (gs[g], g))[-WINDOW:]
        if len(last) < MIN_GAMES:
            continue
        rot = {}
        for k, by in mins[t].items():
            played = [by.get(g, 0) for g in last]
            if sum(1 for m in played if m > 0) >= MIN_GAMES and sum(played) / len(last) >= ROT_MPG:
                rot[k] = {"name": names[(t, k)], "mpg": round(sum(played) / len(last), 1), "last": by.get(last[-1], 0) > 0}
        out[t] = rot
    return out


def outs(team: str, rot: dict, reads: dict) -> list[dict]:
    """Rotation players of `team` that tonight's read has OUT (official report / ESPN). Day-to-day doesn't count."""
    r = reads.get(team)
    if r is None or team not in rot:
        return []
    found = []
    for p in r.players:
        x = rot[team].get(norm(p.name))
        if x and p.status == "out":
            found.append(x)
    return found


def cluster_pick(game, home_spread: float | None, rot: dict, reads: dict) -> list[Pick]:
    if home_spread is None:
        return []
    oh, oa = outs(game.home, rot, reads), outs(game.away, rot, reads)
    picks = []
    for dep, o_dep, other, o_other in ((game.home, oh, game.away, oa), (game.away, oa, game.home, oh)):
        if len(o_dep) >= 2 and len(o_dep) > len(o_other) and any(x["last"] for x in o_dep):
            line = home_spread if other == game.home else -home_spread
            who = ", ".join(f"{x['name']} ({x['mpg']:.0f} mpg{'' if x['last'] else ', out a while'})" for x in o_dep)
            picks.append(Pick(302, game.id, "spread", other, line,
                              [f"{dep} is missing {len(o_dep)} rotation players: {who}", RECORD],
                              {"outs": [x["name"] for x in o_dep], "n_out": len(o_dep), "opp_out": len(o_other)}))
    return picks
