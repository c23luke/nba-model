"""BOTTOM-UP PLAYER PROPS MODEL (Caden 2026-11-11: "let's build a bottom up origination model ... I trust you").

Projection for one player tonight = MINUTES x RATE PER MINUTE x CONTEXT.

MINUTES
  base       his recent minutes (weighted between his last 5, last 10 and season, in games he played)
  absences   a rotation teammate out tonight who played the last game (fresh): if this season has 2+ games without
             that teammate, his real minutes then (trusted part-way); otherwise the absent minutes shared out in
             proportion to everyone's minutes (trusted part-way)
  returning  a 28+ mpg player back after 3+ straight games out: the measured first-game drop
  blowout    spread 12+: starters a little less (measured -2.4), bench a little more
RATE PER MINUTE (points, rebounds, assists)
  blend of his last 10 games and his season, shrunk toward his position's league rate when the sample is small
  usage vacuum: his share grows when teammates who take that stat are out: rate / (1 - absent share) ^ k
CONTEXT
  team total: the market's implied team total tonight vs his team's average points so far (points; ^ exponent)
  game total: the market's total vs the league average so far (rebounds and assists; ^ exponent)
  opponent by position: what tonight's opponent gives up per minute to his position group (guards / wings /
  bigs) vs the league, over its games so far, shrunk by games played (^ weight)
Every weight is a parameter in P, chosen on 2024-25 by engine.measure_prop_model and tested on 2025-26.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STATS = ("pts", "reb", "ast")


def group(pos: str) -> str:
    p = (pos or "").upper()
    if p in ("C", "F-C", "C-F", "PF"):
        return "big"
    if p in ("PG", "SG", "G"):
        return "guard"
    return "wing"


@dataclass
class P:
    w5: float = 0.4            # minutes: weight on last 5 (rest split last 10 / season below)
    w10: float = 0.4
    split_trust: float = 0.6   # with/without history (measured 0.60 overall, 0.95 bench)
    share_trust: float = 0.3   # naive shared-out minutes (measured: +5.9 expected -> +1.5 real)
    rate_recent: float = 0.5   # rate: weight on last 10 vs season
    shrink_min: float = 150.0  # rate shrinks toward the position rate with weight min / (min + shrink)
    usage_k: float = 0.5       # usage vacuum exponent
    team_total_exp: float = 0.5
    game_total_exp: float = 0.5
    opp_w: float = 0.5         # opponent-by-position factor ^ opp_w
    opp_shrink: float = 10.0   # opponent factor uses n / (n + shrink) of its games
    blowout: bool = True
    returning: bool = True
    extra: dict = field(default_factory=dict)


RETURN_GAME1 = ((5, -3.6), (10, -6.7), (20, -6.4), (999, -9.1))


def project(f: dict, p: P) -> dict:
    """f: the features for one player tonight (built by engine.measure_prop_model.features).
    Returns {"min": projected minutes, "pts": ..., "reb": ..., "ast": ...}."""
    base = p.w5 * f["m5"] + p.w10 * f["m10"] + (1 - p.w5 - p.w10) * f["mseason"]
    add = 0.0
    if f.get("split_gain") is not None:
        add += p.split_trust * f["split_gain"]
    elif f.get("share_gain"):
        add += p.share_trust * f["share_gain"]
    if p.returning and f.get("returning"):
        add += next(d for lim, d in RETURN_GAME1 if f["returning"] <= lim)
    if p.blowout and f.get("abs_spread") is not None and f["abs_spread"] >= 12:
        add += -2.4 if base >= 30 else 2.0 if base < 15 else 0.0
    mins = max(0.0, min(44.0, base + add))
    out = {"min": mins}
    for s in STATS:
        r10, rs, rpos = f[f"{s}_r10"], f[f"{s}_rs"], f[f"{s}_rpos"]
        rate = p.rate_recent * r10 + (1 - p.rate_recent) * rs
        w = f["min_season"] / (f["min_season"] + p.shrink_min)
        rate = w * rate + (1 - w) * rpos
        absent = min(0.6, f.get(f"{s}_absent_share") or 0.0)
        rate /= (1 - absent) ** p.usage_k
        ctx = 1.0
        if s == "pts" and f.get("team_total") and f.get("team_avg"):
            ctx *= (f["team_total"] / f["team_avg"]) ** p.team_total_exp
        elif s != "pts" and f.get("game_total") and f.get("league_total"):
            ctx *= (f["game_total"] / f["league_total"]) ** p.game_total_exp
        o, n = f.get(f"{s}_opp"), f.get("opp_games") or 0
        if o:
            ctx *= (1 + (o - 1) * n / (n + p.opp_shrink)) ** p.opp_w
        out[s] = mins * rate * ctx
    return out
