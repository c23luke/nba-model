"""This season's results, fed back into the players model.

The players model rates a team from its players' box-score impact. Box scores miss defense, fit,
coaching and effort; results don't. So after every game we ask: did this team do better or worse
than the players model expected, given who actually played? Each team carries the running total of
those misses, and its rating moves by

    correction = sum of this season's misses / (games played + K)          K = 5

MEASURED (engine/measure_personnel_upgrades.py): K and the full weight were CHOSEN on 2024-25 and
TESTED untouched on 2025-26. Out of sample, 3+ gaps vs the opener went 148-119 (55.4%) instead of
167-166 (50.2%); the result beat the open by +0.38 pts per point of gap (t 2.5) instead of +0.13
(t 1.0); bottom-10 teams 72-68 instead of 73-82. Both seasons: 304-253 (54.6%) vs 339-330 (50.7%).

Only THIS season's games; nothing from any prior-season team. The model's "expected" margin for a
past game uses the players who actually played it and each player's numbers from before that game.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import boxscore
from . import personnel as P

K = 5
WEIGHT = 1.0
# Opponents' three-point shooting is mostly luck, so it's taken out of each game's miss before it counts.
# MEASURED (engine/measure_moneyball.py, chosen on 2024-25, tested on 2025-26): 3+ gaps 175-133 (56.8%)
# vs 148-119 (55.4%) without it; both seasons 347-275 (55.8%) vs 304-253 (54.6%).
REMOVE_OPP_3PT_LUCK = True


def _prior(last: dict) -> dict:
    """Each player's pre-season number and role, the same way the live model builds them."""
    out = {}
    for key, l in last.items():
        out[key] = {"bpm": l["bpm_blend"] + l.get("age_delta", 0.0),
                    "role": min(l["mpg"], P.MIN_CAP) * min(1.0, l["g"] / P.ROLE_GAMES),
                    "kind": "returner" if l.get("missed_last") else "veteran"}
    return out


def _rating(players, prior, live):
    """Team rating from the players who played (top-down minutes, bench fill) — the live model's way."""
    rows = []
    for pid, name in players:
        pr = prior.get(P.norm(name)) or P.find(prior, name)
        kind = pr["kind"] if pr else "none"
        b0, role0 = (pr["bpm"], pr["role"]) if pr else (P.BASELINE, 0.0)
        lv = live.get(pid)
        if lv and lv["min"] > 0:
            w = P.PRIOR_MIN[kind]
            b = (b0 * w + lv["bpm_live"] * lv["min"]) / (w + lv["min"])
            role = min((role0 * P.PRIOR_GAMES + lv["w_min"]) / (P.PRIOR_GAMES + lv["w_games"]), P.MIN_CAP)
        else:
            b, role = b0, role0
        rows.append((b, role))
    left, tot = 240.0, 0.0
    for b, role in sorted(rows, key=lambda r: -r[1]):
        m = min(role, left)
        left -= m
        tot += b * m / 48
    return tot + (left * P.BASELINE / 48 if left > 0 else 0.0)


def team_results(box_rows: list[dict], finals, last: dict) -> dict[str, dict]:
    """finals: this season's finished games (Game objects with scores). Returns per team:
    {"games", "miss" (average pts/game vs expectation, + = better than expected), "adj" (rating change)}."""
    prior = _prior(last)
    by_game = defaultdict(list)
    for r in box_rows:
        by_game[str(r["game_id"])].append(r)
    games = sorted([g for g in finals if str(g.id) in by_game and g.home_score is not None],
                   key=lambda g: (g.game_date, str(g.id)))
    res: dict[str, list[float]] = defaultdict(list)
    last_day: dict[str, date] = {}
    hist: list[dict] = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g.game_date].append(g)
    m3 = a3 = 0
    for day in sorted(by_day):
        live = boxscore.season_impact(hist) if hist else {}
        p3 = m3 / a3 if a3 else 0.36
        todays = []
        for g in by_day[day]:
            rows = by_game[str(g.id)]
            ppl = defaultdict(list)
            for r in rows:
                if r.get("min"):
                    ppl[r["team"]].append((r["espn_id"], r["name"]))
            hb = last_day.get(g.home) == day - timedelta(1)
            ab = last_day.get(g.away) == day - timedelta(1)
            pred = (_rating(ppl[g.home], prior, live) - _rating(ppl[g.away], prior, live)
                    + P.HOME_COURT - P.B2B * hb + P.B2B * ab)
            e = (g.home_score - g.away_score) - pred
            sh = defaultdict(lambda: [0, 0])
            for r in rows:
                sh[r["team"]][0] += r.get("fg3m") or 0
                sh[r["team"]][1] += r.get("fg3a") or 0
            luck_h = 3 * (sh[g.home][0] - sh[g.home][1] * p3)       # home shot this many pts above the league rate
            luck_a = 3 * (sh[g.away][0] - sh[g.away][1] * p3)
            todays.append((g, e, luck_h, luck_a, sh))
        for g, e, luck_h, luck_a, sh in todays:
            eh, ea = e, -e
            if REMOVE_OPP_3PT_LUCK:
                eh += luck_a          # opponents' hot/cold shooting isn't the defense's doing
                ea += luck_h
            res[g.home].append(eh)
            res[g.away].append(ea)
            for x in sh.values():
                m3 += x[0]; a3 += x[1]
            last_day[g.home] = last_day[g.away] = day
            hist += by_game[str(g.id)]
    return {t: {"games": len(v), "miss": round(sum(v) / len(v), 1),
                "adj": round(WEIGHT * sum(v) / (len(v) + K), 2)} for t, v in res.items()}
