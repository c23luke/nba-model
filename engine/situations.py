"""Three situations found Nov 11, 2026 (engine/measure_ideas.py, 2 seasons). TRACKING ONLY (shadow systems).

X5  A team that WON its last game by 25+ -> bet that team. The market expects a letdown; it doesn't come.
    At the open 169-134 (55.8%; 52.8% / 58.5%), at the close 159-122 (56.6%; 54.2% / 58.7%).
X6  The opponent's last game went to OVERTIME -> bet against it. At the open 117-90 (56.5%; 59.6% / 53.1%),
    but only 105-95 (52.5%) at the close: the market catches up, so this one only works early (first line).
X8  The spread moved 2+ points from the first line we saw: follow the move, at the price after it. At the close
    279-223 (55.6%; 55.1% / 56.1%) (engine/measure_ideas2.py). The big moves still don't go far enough.
X9  Home team with 2+ more days of rest than the visitor -> home. 66-41 at the open, 63-43 at the close (both
    seasons 58%+). The visitor with the rest edge shows nothing (47-43).
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


def picks(game, hs, at, home_spread, total, luck: dict, first_home_spread: float | None = None) -> list[Pick]:
    out = []
    # X8: follow a 2+ point line move (from the first line we saw to now), at the price after the move
    if home_spread is not None and first_home_spread is not None:
        mv = first_home_spread - home_spread              # + = the line moved toward the home team
        if abs(mv) >= 2:
            side = game.home if mv > 0 else game.away
            out.append(Pick(308, game.id, "spread", side, home_spread if side == game.home else -home_spread,
                            [f"The line moved {abs(mv):g} points toward {side} (from {first_home_spread:+g} to {home_spread:+g} home)",
                             "2 seasons, following a 2+ move at the closing number: 279-223 (55.6%), both seasons"],
                            {"move": mv}))
    # X9: home team with 2+ more days of rest than the visitor
    lh, la = getattr(hs, "last_game", None), getattr(at, "last_game", None)
    if home_spread is not None and lh and la:
        rh, ra = (game.game_date - lh.game_date).days, (game.game_date - la.game_date).days
        if rh - ra >= 2:
            out.append(Pick(309, game.id, "spread", game.home, home_spread,
                            [f"{game.home} has {rh} days since its last game, {game.away} {ra}",
                             "2 seasons: 66-41 at the open, 63-43 at the close, both seasons"], {"rest": [rh, ra]}))
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


STACK_FLAGS_RECORD = ("2 seasons, each separate fact counted once: 4+ facts 217-148 (59.5%; 59.1% / 59.8%) at the "
                      "close; without line moves, 4+ facts 136-75 (64.5%) at the opening line (engine/measure_stack_flags.py, "
                      "Nov 14)")

# card systems built on the other team being tired (rest / overtime / back-to-back): part of the "tired opponent" fact
TIRED_SYSTEMS = {1, 3, 101, 102, 103, 104, 112, 124}


def stack_facts(game, side: str, picks: list, view: dict | None, hs, at, home_spread, first_home_spread,
                luck: dict) -> dict[str, str]:
    """The SEPARATE facts behind one side, each once, each with its own evidence (Caden 2026-11-14: the MIN STACK
    had 7 flags but 3 real things). The same grouping engine/measure_stack_flags.py tested:
      players model   3+ in EVERY version of tonight (each team's day-to-day players all play / all sit); a lean
                      that depends on an injury call doesn't count until the news settles it
      systems         card systems that aren't about rest (1 or more, one fact)
      tired opponent  back-to-back, off overtime (X6), home rest edge (X9) and the rest / overtime systems
      injuries        X2 / X3 / X4 (only players already ruled out)
      line move       moved 1+ toward this side since the first line (one fact however far)
      blowout win, unknown players, their shooting luck, our shooting luck: one each"""
    from .systems import COMBO_BETS, SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS, label
    names = {**SYSTEMS, **TEST_SYSTEMS, **EARLY_SYSTEMS}
    home = side == game.home
    opp = game.away if home else game.home
    sign = 1 if home else -1
    out: dict[str, str] = {}
    v = view or {}
    gaps = [sc["gap"] for sc in v.get("scenarios") or [] if sc.get("gap") is not None] or \
           ([v["gap"]] if v.get("gap") is not None else [])
    if gaps and min(sign * g for g in gaps) >= 3:
        lo, hi = min(sign * g for g in gaps), max(sign * g for g in gaps)
        out["players model"] = (f"players model likes {side} by {lo:.1f}" if len(gaps) == 1 or hi - lo < 0.05 else
                                f"players model likes {side} by {lo:.1f} to {hi:.1f}, whoever of the day-to-day players plays")
    sysd = sorted({p.system for p in picks if p.bet == "spread" and p.side == side and p.system < 300
                   and p.system not in (113, 301, *COMBO_BETS)})
    other = [s_ for s_ in sysd if s_ not in TIRED_SYSTEMS]
    if other:
        out["systems"] = "card system" + ("s" if len(other) > 1 else "") + ": " + ", ".join(
            f"{label(s_)} ({names.get(s_, {}).get('name', '')})" for s_ in other)
    tracked = {p.system: p for p in picks if p.bet == "spread" and p.side == side and p.system >= 302}
    tired = [f"{label(s_)} ({names.get(s_, {}).get('name', '')})" for s_ in sysd if s_ in TIRED_SYSTEMS]
    so, sm = (at, hs) if home else (hs, at)
    lgo, lgm = getattr(so, "last_game", None), getattr(sm, "last_game", None)
    if lgo and (game.game_date - lgo.game_date).days == 1 and not (lgm and (game.game_date - lgm.game_date).days == 1):
        tired.insert(0, f"{opp} is on a back-to-back, {side} isn't")
    for sid in (306, 309):
        if sid in tracked:
            tired.append(tracked[sid].evidence[0])
    if tired:
        out["tired opponent"] = "; ".join(tired)
    for sid in (304, 303, 302):                       # the most specific injury fade says it best
        if sid in tracked:
            out["injuries"] = tracked[sid].evidence[0]
            break
    if home_spread is not None and first_home_spread is not None:
        mv = (first_home_spread - home_spread) if home else (home_spread - first_home_spread)
        if mv >= 1:
            out["line move"] = f"line moved {mv:g} toward {side} since the first line"
    if 305 in tracked:
        out["blowout win"] = tracked[305].evidence[0]
    th = v.get("thin_share") or {}
    me, them = ("home", "away") if home else ("away", "home")
    if th and th.get(them, 0) > th.get(me, 0) + 0.05:
        out["unknown players"] = (f"{opp} leans on players the model barely knows ({th[them]:.0%} of its minutes "
                                  f"vs {th.get(me, 0):.0%})")
    lo5, lm5 = (luck.get(opp) or [])[-5:], (luck.get(side) or [])[-5:]
    if len(lo5) >= 3 and sum(lo5) / len(lo5) >= 3:
        out["their shooting luck"] = f"{opp} has shot {sum(lo5) / len(lo5):+.1f} a game above its shot quality (last 5)"
    if len(lm5) >= 3 and sum(lm5) / len(lm5) <= -3:
        out["our shooting luck"] = f"{side} has shot {sum(lm5) / len(lm5):+.1f} a game below its shot quality (last 5)"
    return out


def stack_picks(game, picks: list, view, hs, at, home_spread, first_home_spread, luck: dict) -> list[Pick]:
    """STACK (131), a card bet at 2 units: 4+ SEPARATE facts on one side (Caden 2026-11-14). Replaces "6+ flags, or 5
    with the players model and a system", which counted one fact several times (MIN: 7 flags, 3 facts). In the
    morning it can only see what's known before the line moves (opening prices); later a line move can be a fact."""
    from .systems import STACK
    if home_spread is None:
        return []
    out = []
    for side in (game.home, game.away):
        f = stack_facts(game, side, picks, view, hs, at, home_spread, first_home_spread, luck)
        line = home_spread if side == game.home else -home_spread
        if len(f) >= 4:
            fl = [f"{k}: {v}" for k, v in f.items()]
            out.append(Pick(STACK, game.id, "spread", side, line,
                            [f"{len(f)} separate facts on {side}: " + " | ".join(fl), STACK_FLAGS_RECORD],
                            {"flags": fl, "n_flags": len(f), "two_units": True}))
    return out


def system_x4_picks(game, picks: list) -> list[Pick]:
    """SYS+X4 (132), a card bet: a card system on a side AND X4 (the other team missing 2+ rotation players at different
    positions) on that same side. 42-18 (70.0%) at the close over 2 seasons (Caden 2026-11-11)."""
    from .systems import COMBO_BETS, SYS_X4, SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS, label
    names = {**SYSTEMS, **TEST_SYSTEMS, **EARLY_SYSTEMS}
    out = []
    for x4 in [p for p in picks if p.system == 304 and p.bet == "spread"]:
        sysd = sorted({p.system for p in picks if p.bet == "spread" and p.side == x4.side and p.system < 300
                       and p.system not in (113, *COMBO_BETS)})
        if sysd:
            out.append(Pick(SYS_X4, game.id, "spread", x4.side, x4.line,
                            [f"{label(s)} ({names.get(s, {}).get('name', '')}) fired on {x4.side}" for s in sysd]
                            + list(x4.evidence)
                            + ["2 seasons at the close: a system + this injury fade went 42-18 (70.0%; 22-10 / 20-8)"],
                            {"systems": [label(s) for s in sysd]}))
    for p in out:
        p.meta["flags"] = p.evidence[:-1]
    return out


def _b2b_edge(game, side, hs, at):
    """The other team is on a back-to-back and this side isn't (the stack study's opp_b2b flag)."""
    home = side == game.home
    so, sm = (at, hs) if home else (hs, at)
    lgo, lgm = getattr(so, "last_game", None), getattr(sm, "last_game", None)
    return bool(lgo and (game.game_date - lgo.game_date).days == 1
                and not (lgm and (game.game_date - lgm.game_date).days == 1))


def pair_picks(game, picks: list, view, hs, at, home_spread, first_home_spread) -> list[Pick]:
    """Three pairs from the stack study, bet at 1 unit (Caden 2026-11-11). Each flag is listed with its reason.
    133 X4+B2B 42-18, 134 X2+B2B 62-31, 135 MOVE+THIN 79-44 (2 seasons at the close)."""
    if home_spread is None:
        return []
    out = []
    for side in (game.home, game.away):
        home = side == game.home
        opp = game.away if home else game.home
        line = home_spread if home else -home_spread
        on = {p.system: p for p in picks if p.bet == "spread" and p.side == side}
        b2b = _b2b_edge(game, side, hs, at)
        b2b_txt = f"{opp} is on a back-to-back, {side} isn't"
        for sid, xs, rec in ((133, 304, "42-18 (70.0%; 23-9 / 19-9)"), (134, 302, "62-31 (66.7%; 33-16 / 29-15)")):
            if xs in on and b2b:
                fl = [on[xs].evidence[0], b2b_txt]
                out.append(Pick(sid, game.id, "spread", side, line,
                                fl + [f"2 seasons at the close: {rec}"], {"flags": fl}))
        th = (view or {}).get("thin_share") or {}
        me, them = ("home", "away") if home else ("away", "home")
        if first_home_spread is not None and th and th.get(them, 0) > th.get(me, 0) + 0.05:
            mv = (first_home_spread - home_spread) if home else (home_spread - first_home_spread)
            if mv >= 2:
                fl = [f"line moved {mv:g} toward {side} since the first line",
                      f"{opp} leans on players the model barely knows ({th[them]:.0%} of its minutes vs {th.get(me, 0):.0%})"]
                out.append(Pick(135, game.id, "spread", side, line,
                                fl + ["2 seasons at the close: 79-44 (64.2%; 36-17 / 43-27)"], {"flags": fl}))
    return out


# ---------------------------------------------------------------- shot-quality pairs (Caden 2026-11-12)
# cut-offs from engine/measure_stack2.py (both seasons pooled): top 15% / bottom 15% / top 30%
SQ_DIFF, SQ_UNLUCKY, SQ_3HOT, SQ_RIM, SQ_DRIM = 6.843, -7.194, 4.668, 0.284, 0.282
THREES = ("corner3", "above3")


def team_sq(shots: dict, finals: list) -> dict[str, dict]:
    """team -> shot-quality read from this season's finished games (the same numbers as engine/measure_stack2.py):
    xnet10   what its shots were worth minus what it allowed, a game, last 10 (league zone rates, season to date)
    luck_net10  real margin minus that, a game, last 10 (negative = results ran behind the shots)
    three_luck5 made-3 points above what its 3s were worth, a game, last 5
    rrim / drim  share of its shots / of its opponents' shots at the rim, last 10. Needs 5+ games with shots."""
    order = sorted((g for g in finals if str(g.id) in shots), key=lambda g: (g.game_date, str(g.id)))
    zl = {z: [0, 0] for z in ZONES}
    hist: dict[str, list] = {}
    for g in order:
        rows = counts_to_shots(shots[str(g.id)])
        L = {z: (v[1] / v[0] if v[0] else 0.0) for z, v in zl.items()}
        per = {t: {"xf": 0.0, "af": 0.0, "z": {z: 0 for z in ZONES}, "t3": 0.0} for t in (g.home, g.away)}
        for team, _, z, pts in rows:
            if team in per:
                per[team]["xf"] += L[z]; per[team]["af"] += pts; per[team]["z"][z] += 1
                if z in THREES:
                    per[team]["t3"] += pts - L[z]
        if (sum(v[0] for v in zl.values()) > 2000 and all(sum(per[t]["z"].values()) >= 50 for t in per)
                and g.home_score is not None and g.away_score is not None):
            sc = {g.home: g.home_score, g.away: g.away_score}
            for team, opp in ((g.home, g.away), (g.away, g.home)):
                a, b = per[team], per[opp]
                hist.setdefault(team, []).append({"xf": a["xf"], "xa": b["xf"], "af": a["af"], "aa": b["af"],
                                                  "margin": sc[team] - sc[opp], "zf": a["z"], "za": b["z"], "t3": a["t3"]})
        for _, _, z, pts in rows:
            zl[z][0] += 1; zl[z][1] += pts
    out = {}
    for team, h in hist.items():
        h = h[-10:]
        if len(h) < 5:
            continue
        tf = sum(sum(x["zf"].values()) for x in h) or 1
        ta = sum(sum(x["za"].values()) for x in h) or 1
        out[team] = {"games": len(h),
                     "xnet10": sum(x["xf"] - x["xa"] for x in h) / len(h),
                     "luck_net10": sum((x["af"] - x["xf"]) - (x["aa"] - x["xa"]) for x in h) / len(h),
                     "three_luck5": sum(x["t3"] for x in h[-5:]) / len(h[-5:]),
                     "rrim": sum(x["zf"]["rim"] for x in h) / tf, "drim": sum(x["za"]["rim"] for x in h) / ta}
    return out


def sq_pair_picks(game, picks: list, view, home_spread, first_home_spread, sq: dict) -> list[Pick]:
    """The five shot-quality pairs (136-140), 1 unit each. Every flag says its own number."""
    if home_spread is None or not sq:
        return []
    out = []
    for side in (game.home, game.away):
        home = side == game.home
        opp = game.away if home else game.home
        f, o = sq.get(side), sq.get(opp)
        if not f or not o:
            continue
        line = home_spread if home else -home_spread
        on = {p.system: p for p in picks if p.bet == "spread" and p.side == side}
        gap = (view or {}).get("gap")
        pm = gap is not None and (gap if home else -gap) >= 3
        th = (view or {}).get("thin_share") or {}
        me, them = ("home", "away") if home else ("away", "home")
        thin = bool(th) and th.get(them, 0) > th.get(me, 0) + 0.05
        mv = None if first_home_spread is None else ((first_home_spread - home_spread) if home else (home_spread - first_home_spread))
        better = f["xnet10"] - o["xnet10"]
        T = {
            "rim": (f["rrim"] >= SQ_RIM and o["drim"] >= SQ_DRIM,
                    f"{side} takes {f['rrim']:.0%} of its shots at the rim and {opp} allows {o['drim']:.0%} there (last 10)"),
            "pm": (pm, f"players model likes {side} by {abs(gap or 0):.1f}"),
            "better": (better >= SQ_DIFF, f"{side}'s shots have been worth {better:+.1f} a game more than {opp}'s, "
                                          f"net of what each allows (last 10)"),
            "unlucky": (f["luck_net10"] <= SQ_UNLUCKY, f"{side}'s real margins ran {f['luck_net10']:+.1f} a game behind "
                                                       f"what its shots said (last 10)"),
            "hot3": (o["three_luck5"] >= SQ_3HOT, f"{opp} has made 3s worth {o['three_luck5']:+.1f} a game more than "
                                                  f"its 3s were worth (last 5)"),
            "thin": (thin, f"{opp} leans on players the model barely knows ({th.get(them, 0):.0%} of its minutes vs "
                           f"{th.get(me, 0):.0%})"),
            "move": (mv is not None and mv >= 1, f"line moved {mv or 0:g} toward {side} since the first line"),
        }
        if 303 in on:
            T["x3"] = (True, on[303].evidence[0])
        if 304 in on:
            T["x4"] = (True, on[304].evidence[0])
        for sid, a, b, rec in ((136, "rim", "pm", "36-14 (72.0%; 24-8 / 12-6)"), (137, "better", "x3", "29-12 (70.7%; 14-7 / 15-5)"),
                               (138, "unlucky", "x4", "30-15 (66.7%; 18-9 / 12-6)"), (139, "better", "thin", "66-37 (64.1%; 35-15 / 31-22)"),
                               (140, "hot3", "move", "91-58 (61.1%; 39-24 / 52-34)")):
            if T.get(a, (False,))[0] and T.get(b, (False,))[0]:
                fl = [T[a][1], T[b][1]]
                out.append(Pick(sid, game.id, "spread", side, line, fl + [f"2 seasons at the close: {rec}"], {"flags": fl}))
    return out
