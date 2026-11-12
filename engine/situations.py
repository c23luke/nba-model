"""Three situations found Nov 11, 2026 (engine/measure_ideas.py, 2 seasons). TRACKING ONLY (shadow systems).

X5  A team that WON its last game by 25+ -> bet that team. The market expects a letdown; it doesn't come.
    At the open 169-134 (55.8%; 52.8% / 58.5%), at the close 159-122 (56.6%; 54.2% / 58.7%).
X6  The opponent's last game went to OVERTIME -> bet against it. At the open 117-90 (56.5%; 59.6% / 53.1%),
    but only 105-95 (52.5%) at the close: the market catches up, so this one only works early (first line).
X7  Both teams shot 2+ points a game WORSE than their shots were worth over their last 5 (shot locations) ->
    over. At the open 121-102 (54.3%; 54.9% / 53.7%), at the close 114-98 (53.8%).
"""
from __future__ import annotations

from .prop_model import ZONES, counts_to_shots
from .systems import Pick


def team_luck(shots: dict, finals: list) -> dict[str, list[float]]:
    """team -> field-goal points above what its shots were worth at league rates, per game, oldest first."""
    order = sorted((g for g in finals if str(g.id) in shots), key=lambda g: (g.game_date, str(g.id)))
    zl = {z: [0, 0] for z in ZONES}
    out: dict[str, list[float]] = {}
    for g in order:
        rows = counts_to_shots(shots[str(g.id)])
        L = {z: (v[1] / v[0] if v[0] else 0) for z, v in zl.items()}
        per: dict[str, list[float]] = {}
        for team, _, z, pts in rows:
            a = per.setdefault(team, [0.0, 0.0])
            a[0] += pts
            a[1] += L[z]
        if sum(v[0] for v in zl.values()) > 2000:
            for team, (act, exp) in per.items():
                out.setdefault(team, []).append(act - exp)
        for _, _, z, pts in rows:
            zl[z][0] += 1
            zl[z][1] += pts
    return out


def picks(game, hs, at, home_spread, total, luck: dict) -> list[Pick]:
    out = []
    if home_spread is not None:
        for st, team, line in ((hs, game.home, home_spread), (at, game.away, -home_spread)):
            lg = getattr(st, "last_game", None)
            if not lg or lg.home_score is None:
                continue
            mg = (lg.home_score - lg.away_score) * (1 if lg.home == team else -1)
            if mg >= 25:
                out.append(Pick(305, game.id, "spread", team, line,
                                [f"{team} won its last game by {mg}", "2 seasons: 169-134 at the open, 159-122 at the close"],
                                {"last_margin": mg}))
            if (lg.periods or 4) > 4:
                other = game.away if team == game.home else game.home
                o_line = -line
                out.append(Pick(306, game.id, "spread", other, o_line,
                                [f"{team}'s last game went to overtime", "2 seasons: 117-90 at the open (only works early)"],
                                {"ot_team": team}))
    if total is not None:
        lh, la = (luck.get(game.home) or [])[-5:], (luck.get(game.away) or [])[-5:]
        if len(lh) >= 3 and len(la) >= 3:
            h, a = sum(lh) / len(lh), sum(la) / len(la)
            if h <= -2 and a <= -2:
                out.append(Pick(307, game.id, "total", "OVER", total,
                                [f"Both teams shooting below their shot quality: {game.home} {h:+.1f}, {game.away} {a:+.1f} "
                                 "points a game (last 5)", "2 seasons: 121-102 at the open, 114-98 at the close"],
                                {"luck_home": round(h, 1), "luck_away": round(a, 1)}))
    return out
