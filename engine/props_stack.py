"""PROPS STACK TRACKERS (Caden 2026-11-12: "yes build way more trackers"). Paper only, on the testing side.

Every player with Pinnacle's points line gets OVER flags and UNDER flags, from what's known before tip (the same
definitions engine/measure_props_stack.py tested on 2025-26 against Pinnacle's closing lines). A tracker fires when
both of its flags are on the same side. The records below are that backtest (the two halves of 2025-26 stand in for
two seasons; graded at Pinnacle's price). None of them is proven: most won one half far more than the other.
"""
from __future__ import annotations


def flags(f: dict, line: float, proj_pts: float | None) -> tuple[dict, dict]:
    """f: the player's feature dict (engine.prop_model.History.features). Returns (over, under): flag -> its reason."""
    o, u = {}, {}
    nm = f.get("name", "he")
    if proj_pts is not None:
        if proj_pts - line >= 2:
            o["model"] = f"our model has {nm} at {proj_pts:.1f}, {proj_pts - line:+.1f} vs the line"
        if line - proj_pts >= 2:
            u["model"] = f"our model has {nm} at {proj_pts:.1f}, {proj_pts - line:+.1f} vs the line"
    fresh = f.get("fresh_out")
    n_fresh = len(fresh) if isinstance(fresh, list) else (fresh or 0)
    if n_fresh > 0 and (f.get("share_gain") or 0) >= 2:
        o["fresh"] = f"a rotation teammate is freshly out; he picks up about {f['share_gain']:.1f} of those minutes"
    if (f.get("split_gain") or 0) >= 3:
        o["split"] = f"without that teammate he has played {f['split_gain']:+.1f} more minutes"
    if f.get("returning"):
        u["returning"] = f"he's back from {f['returning']} missed games as a {f.get('mseason', 0):.0f} mpg player"
    lp = f.get("luck_pm")
    if lp is not None:
        if lp * 30 <= -2:
            o["luck"] = f"his shooting has run {lp * 30:+.1f} points per 30 minutes below what his shots were worth"
        if lp * 30 >= 2:
            u["luck"] = f"his shooting has run {lp * 30:+.1f} points per 30 minutes above what his shots were worth"
    sm = f.get("shot_match")
    if sm is not None:
        if sm >= 1.05:
            o["match"] = f"tonight's defense allows {sm - 1:+.0%} vs the league on his shot mix"
        if sm <= 0.95:
            u["match"] = f"tonight's defense allows {sm - 1:+.0%} vs the league on his shot mix"
    po = f.get("pts_opp")
    if po is not None:
        if po >= 1.08:
            o["opp"] = f"tonight's opponent allows {po - 1:+.0%} points to his position"
        if po <= 0.92:
            u["opp"] = f"tonight's opponent allows {po - 1:+.0%} points to his position"
    if f.get("m5") is not None and f.get("m10") is not None:
        if f["m5"] - f["m10"] >= 3:
            o["trend"] = f"his last 5 games' minutes ({f['m5']:.1f}) are {f['m5'] - f['m10']:+.1f} vs his last 10"
        if f["m10"] - f["m5"] >= 3:
            u["trend"] = f"his last 5 games' minutes ({f['m5']:.1f}) are {f['m5'] - f['m10']:+.1f} vs his last 10"
    if f.get("pts_savg") is not None:
        if f["pts_savg"] - line >= 2:
            o["vs_avg"] = f"the line is {line - f['pts_savg']:+.1f} vs his season average ({f['pts_savg']:.1f})"
        if line - f["pts_savg"] >= 2:
            u["vs_avg"] = f"the line is {line - f['pts_savg']:+.1f} vs his season average ({f['pts_savg']:.1f})"
    if f.get("team_total") is not None and f.get("team_avg") is not None:
        d = f["team_total"] - f["team_avg"]
        if d >= 4:
            o["team_tot"] = f"his team's implied total ({f['team_total']:.1f}) is {d:+.1f} vs its average"
        if d <= -4:
            u["team_tot"] = f"his team's implied total ({f['team_total']:.1f}) is {d:+.1f} vs its average"
    if (f.get("abs_spread") or 0) >= 10 and (f.get("m10") or 0) >= 28:
        u["blowout"] = f"a {f['abs_spread']:.1f}-point spread and he plays {f['m10']:.0f} mpg: he can sit late"
    return o, u


# name, side, the two flags (or a flag count), the backtest (2025-26 vs Pinnacle's close, first half / second half)
TRACKERS = [
    ("Under: blowout + low team total", "under", ("blowout", "team_tot"),
     "206-150 (57.9%, +7.0% a bet); 84-74 then 122-76"),
    ("Under: bad shot matchup + low team total", "under", ("match", "team_tot"),
     "116-89 (56.6%, +5.1%); 60-49 then 56-40"),
    ("Under: blowout + tough defense on his position", "under", ("blowout", "opp"),
     "68-52 (56.7%, +4.5%); 48-38 then 20-14"),
    ("Under: shooting above his shots + line above his average", "under", ("luck", "vs_avg"),
     "118-96 (55.1%, +2.1%); 42-27 then 76-69"),
    ("Over: shooting below his shots + line below his average", "over", ("luck", "vs_avg"),
     "64-49 (56.6%, +5.9%); 22-19 then 42-30"),
    ("Over: soft defense on his position + line below his average", "over", ("opp", "vs_avg"),
     "70-52 (57.4%, +6.0%); 47-36 then 23-16"),
    ("Over: more minutes without a teammate + high team total", "over", ("split", "team_tot"),
     "84-62 (57.5%, +7.7%); 27-12 then 57-50"),
    ("Over: 4+ over flags", "over", 4, "218-181 (54.6%); 4 flags 171-145, 5+ 47-36"),
    ("Under: 3+ under flags", "under", 3, "about 557-473 (54.1%); 3 flags 438-361 (58.1% then 51.9%)"),
]


def fire(f: dict, line: float, proj_pts: float | None) -> list[tuple[str, str, list[str]]]:
    """-> [(tracker name, side, the flags' reasons)] for every tracker this player-line sets off."""
    o, u = flags(f, line, proj_pts)
    out = []
    for name, side, need, _ in TRACKERS:
        have = o if side == "over" else u
        if isinstance(need, int):
            if len(have) >= need:
                out.append((name, side, list(have.values())))
        elif all(k in have for k in need):
            out.append((name, side, [have[k] for k in need]))
    return out
