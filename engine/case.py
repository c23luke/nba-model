"""The case for a personnel bet, written out so it can be checked line by line.

Built from numbers only (no hand-written opinions), in this order:
  1. the bet and our number vs the market's
  2. why we're different: each team's rating from its current players and who drives it
  3. why we think we're right: every stress test and day-to-day version, and how far the
     market needs the faded team to be off for its number to be right
  4. where the value is: cover chance if our number is right (measured spread spread-of-results)
  5. why we took it: the rule it passed
  6. what could make us wrong
  7. confidence — last, from the checks above
"""
from __future__ import annotations

import math

from . import personnel as P

# Measured 2025-26 regular season: home margin minus closing spread (DraftKings via ESPN),
# 979 games: mean -0.28, SD 14.14. Used as how far a result lands from a fair line.
RESULT_SD = 14.14
RESULT_SD_NOTE = "measured on 979 games last season"
BREAK_EVEN = 110 / 210          # -110


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _line(team: str, spread: float) -> str:
    return f"{team} PK" if spread == 0 else f"{team} {spread:+g}"


def _fav(home: str, away: str, home_spread: float) -> str:
    if abs(home_spread) < 0.05:
        return "a pick'em"
    return f"{home} by {abs(home_spread):.1f}" if home_spread < 0 else f"{away} by {abs(home_spread):.1f}"


def _src(p: P.Player, team: str) -> str:
    if p.prior:
        return f"rookie, rated on draft slot (#{p.draft['pick']} pick)" if p.draft else "rookie, rated on draft slot"
    if p.last and p.last.get("missed_last"):
        return "back from a missed season"
    if p.last and p.last["team"] != team:
        return f"new, came from {p.last['team']}"
    return "same team as last season"


def _player_line(p: P.Player, team: str) -> str:
    impact = p.bpm_used * p.minutes / 48
    live = (f"; this season {p.live['games']} g, {p.live['mpg']:.0f} mpg, box impact {p.live['bpm_live']:+.1f}"
            if p.live and p.live.get("games") else "")
    return (f"{p.name}: rated {p.bpm_used:+.1f} (BPM scale), projected {p.wanted:.0f} min role → "
            f"{impact:+.2f} pts/100 for {team} ({_src(p, team)}{live})")


def build_case(away: str, home: str, side: str, bet_line: float, market_home: float,
               view: dict, reads: dict, stress: dict, cal, systems_on_side: list[str],
               t13_record: dict | None = None) -> dict:
    a, h = reads[away], reads[home]
    us_home = side == home
    opp = away if us_home else home
    fair_home = view["fair"]
    gaps_dtd = [s["gap"] for s in view.get("scenarios") or [] if s.get("gap") is not None] or [view["gap"]]
    gaps_stress = {k: v["gap"] for k, v in (stress or {}).items()}
    # positive gap = we like home more than the market → flip for an away bet
    sgn = 1 if us_home else -1
    cushion_dtd = [sgn * g for g in gaps_dtd]
    cushion_stress = {k: sgn * g for k, g in gaps_stress.items()}
    cushion = sgn * view["gap"]
    ranked = sorted(reads, key=lambda t: -reads[t].rating)
    rank = {t: ranked.index(t) + 1 for t in ranked}

    sections = []

    # 1. the bet
    sections.append({"title": "The bet", "lines": [
        f"{_line(side, bet_line)}. Market: {_fav(home, away, market_home)}. "
        f"Our players-only line: {_fav(home, away, fair_home)}.",
        f"That's {cushion:.1f} points of cushion on {side}.",
        ("Also on this side: " + ", ".join(systems_on_side)) if systems_on_side else
        "No other system is on this side.",
    ]})

    # 2. why we're different
    lines = [f"Every team is rated only from the players on tonight's roster — each player's own last two "
             f"seasons wherever he played, aged with a measured curve, plus this season's games once they "
             f"exist. Last season's team results are not used."]
    for t, tr in ((away, a), (home, h)):
        rot = [p for p in tr.rotation if p.bpm_used is not None][:9]
        lines.append(f"{t}: {tr.rating:+.1f} pts per 100 vs an average team ({rank[t]} of {len(ranked)}). "
                     f"{tr.continuity:.0%} of minutes from players who finished last season with {t}.")
        top = [p for p in sorted(rot, key=lambda p: -(p.bpm_used * p.minutes)) if p.bpm_used > 0][:3]
        drag = [p for p in sorted(rot, key=lambda p: p.bpm_used * p.minutes) if p.bpm_used < -1][:3]
        lines += ["  carries them — " + _player_line(p, t) for p in top]
        lines += ["  drags them down — " + _player_line(p, t) for p in drag]
        if tr.out:
            lines.append(f"  out tonight: " + ", ".join(p.name for p in tr.out))
    sections.append({"title": "Why we're different from the market", "lines": lines})

    # 3. why we think we're right
    lines = []
    if cushion_stress:
        held = sum(c >= P.GAP_TO_FIRE for c in cushion_stress.values())
        lines.append(f"We re-priced the game with our two most arguable choices flipped. "
                     f"The edge stayed 3+ in {held} of {len(cushion_stress)}:")
        for k, c in cushion_stress.items():
            v = stress[k]
            lines.append(f"  {k}: {c:+.1f} on {side} ({away} {v['away']:+.1f}, {home} {v['home']:+.1f} per 100)")
    if len(cushion_dtd) > 1:
        lines.append(f"Day-to-day players ({', '.join(view.get('waiting_on') or [])}): "
                     f"edge {min(cushion_dtd):+.1f} to {max(cushion_dtd):+.1f} whether they play or sit.")
    else:
        lines.append("No day-to-day players in either rotation.")
    # how wrong would we have to be about the team we're fading?
    if cal and cal[1]:
        need = cushion / cal[1]
        opp_tr = reads[opp]
        key = "away" if opp == away else "home"
        swings = ([(k, v[key] - stress["base"][key]) for k, v in stress.items() if k != "base"]
                  if stress and "base" in stress else [])
        best = max(swings, key=lambda s: s[1]) if swings else None
        lines.append(f"For the market's number to be right, {opp} has to be about {need:.1f} pts per 100 better "
                     f"than our read (that's {opp} going from {rank[opp]} of {len(ranked)} to roughly a "
                     f"{_rank_at(reads, opp_tr.rating + need)} team).")
        if best:
            lines.append(f"The most any stress test helps {opp} is {best[1]:+.1f} ({best[0]}).")
    sections.append({"title": "Why we think we're right", "lines": lines})

    # 4. value
    exp_margin = -fair_home if us_home else fair_home        # our expected margin for the side we bet
    p_cover = _phi((exp_margin + bet_line) / RESULT_SD)
    worst = min(list(cushion_stress.values()) + cushion_dtd + [cushion])
    p_worst = _phi(worst / RESULT_SD)
    sections.append({"title": "Where the value is", "lines": [
        f"If our line is right, {_line(side, bet_line)} covers about {p_cover:.0%} of the time "
        f"(results land around a fair line with a spread of ±{RESULT_SD:.1f} points, {RESULT_SD_NOTE}).",
        f"Using the weakest version above ({worst:+.1f}), it's still about {p_worst:.0%}.",
        f"Break-even at −110 is {BREAK_EVEN:.1%}.",
        "Those percentages assume our number is right. It has no live record yet, so read them as the "
        "ceiling, not the expectation.",
    ]})

    # 5. why we took it
    sections.append({"title": "Why we took it", "lines": [
        f"T13 fires only when our line is 3+ points off the market in every day-to-day version and the "
        f"model has no blind spots on either team. This game: {min(cushion_dtd):+.1f} at the worst, no blind spots.",
    ]})

    # 6. what could make us wrong
    risks = []
    for t, tr in ((away, a), (home, h)):
        for p in tr.dtd:
            if p.minutes > 0:
                risks.append(f"{t}: {p.name} is day-to-day (priced both ways above).")
        rk = [p for p in tr.rotation if p.prior]
        if rk:
            risks.append(f"{t}: {sum(p.minutes for p in rk):.0f} minutes from rookies rated only on draft slot "
                         f"({', '.join(p.name for p in rk)}).")
        for p in tr.rotation:
            if p.last and p.last.get("missed_last"):
                risks.append(f"{t}: {p.name} is back from a missed season — rated {p.bpm_used:+.1f}; "
                             f"that number is a judgement, not a measurement.")
        unk = [p for p in tr.unknown]
        if unk:
            risks.append(f"{t}: {len(unk)} player(s) with no NBA numbers ({', '.join(p.name for p in unk)}), "
                         f"counted at zero minutes.")
    risks.append("Ratings come from box-score numbers; camp news (a new role, a minutes limit, a coach's "
                 "rotation plan) only shows up once games are played.")
    if t13_record is not None:
        n = t13_record.get("w", 0) + t13_record.get("l", 0)
        risks.append(f"T13's live record: {t13_record.get('w', 0)}-{t13_record.get('l', 0)}"
                     + (" — no games graded yet." if not n else "."))
    sections.append({"title": "What could make us wrong", "lines": risks})

    # 7. confidence — last
    checks = list(cushion_stress.values()) + cushion_dtd
    all_held = all(c >= P.GAP_TO_FIRE for c in checks)
    low = min(checks) if checks else cushion
    if all_held and low >= 4.5:
        level = "High"
    elif all_held:
        level = "Medium"
    else:
        level = "Low"
    graded = (t13_record or {}).get("w", 0) + (t13_record or {}).get("l", 0)
    why = (f"the edge held 3+ in all {len(checks)} versions we tried, smallest {low:+.1f}" if all_held
           else f"the edge dropped under 3 in at least one version (smallest {low:+.1f})")
    sections.append({"title": "Confidence", "lines": [
        f"{level}: {why}.",
        ("The model has no graded games yet, so this is confidence in the read, not a proven record."
         if graded < 20 else f"T13 has {graded} graded games live."),
    ]})
    return {"side": side, "line": bet_line, "level": level, "cushion": round(cushion, 1),
            "worst": round(low, 1), "p_cover": round(p_cover, 3), "p_worst": round(p_worst, 3),
            "sections": sections}


def _rank_at(reads: dict, rating: float) -> str:
    better = sum(tr.rating > rating for tr in reads.values())
    n = better + 1
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}-best"
