"""What to bet today: one ranked card from every OG and FAV pick, line-shopped across every venue.

Expected win rate per pick (conservative, measured — never a hunch):
  OG S1-S4   the card's long-run win rate (S4's two-season replay, 56%, matched its card)
  T13        50% + 2.8% per point of measured line movement for this stage and gap size
  T2, T12    halfway between 50% and their two-season replay
  T21-T24    halfway between 50% and their six-season search record

Line shopping: every venue's price on the pick's side is turned into an expected return.
  A different number is worth a measured amount: results land around the line with an SD of
  14.14 points for sides (979 games) and 18.18 for totals (1,194 games), both 2025-26.
  So NOP +4.5 at 45c and NOP +3.5 at 50c are compared on the same scale. Whole numbers count pushes.
  Kalshi comes straight from Kalshi (every strike, exact fee). Other venues come from The Odds API's
  exchange feed at their posted price; their fees are NOT counted (marked on each quote).
  The best price is chosen among venues Caden has an account at; Novig is shown for reference.

Verdict:
  BET        the best venue has a positive expected return right now (or no exchange market yet
             and the win rate beats -110)
  LIMIT      worth betting, but every venue is too pricey: set a limit at the max price on Kalshi
  PASS       not enough edge at any normal price
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import NormalDist

from .sources import MY_VENUES
from .systems import SYSTEMS, TEST_SYSTEMS, label, group

BREAK_EVEN_110 = 110 / 210
TO_WIN = 20          # every bet is sized to win this many dollars
MONEYBALL_TO_WIN = 30  # MONEYBALL stacks: 2+ systems + players model 3+ (29-11 over 2 seasons at the open)
MIN_EV = 0.02        # the order placer's bar (bet_settings.min_ev): BET on the card means it WILL be bet

# 2-season replay of every system split by whether the players model agreed (engine/backtest_og.py)
try:
    import json as _json
    from .personnel import STATIC as _STATIC
    SYSTEM_PLAYERS_HISTORY = _json.loads((_STATIC / "og_personnel.json").read_text())
except Exception:
    SYSTEM_PLAYERS_HISTORY = {}
AGREE = [("players model disagrees", -99, 0), ("agrees by 0-3", 0, 3), ("agrees by 3-5", 3, 5),
         ("agrees by 5+", 5, 99)]


def agree_bucket(gap_on_side: float) -> str:
    for name, lo, hi in AGREE:
        if lo <= gap_on_side < hi:
            return name
    return AGREE[-1][0]


def players_history(grp: str, gap_on_side: float | None) -> dict | None:
    """2-season record (vs the open) of this group's spread bets with the players model in the same spot.
    3-5 and 5+ are pooled into 3+: the samples are small and the two buckets alone bounce around."""
    if gap_on_side is None:
        return None
    t = SYSTEM_PLAYERS_HISTORY.get(grp) or {}
    keys = (["agrees by 3-5", "agrees by 5+"] if gap_on_side >= 3 else [agree_bucket(gap_on_side)])
    w = sum((t.get(k) or {}).get("open", [0, 0, 0])[0] for k in keys)
    l = sum((t.get(k) or {}).get("open", [0, 0, 0])[1] for k in keys)
    name = "agrees by 3+" if gap_on_side >= 3 else agree_bucket(gap_on_side).replace("players model ", "")
    return {"w": w, "l": l, "label": name} if w + l else None


def players_gap(pick: dict, slate: list[dict]) -> float | None:
    """How many points the players model likes this side by, vs the market (negative = it likes the
    other side). Spreads only; the personnel model has no edge on totals."""
    if pick["bet"] != "spread":
        return None
    for g in slate:
        if g.get("game_id") == pick["game_id"]:
            view = g.get("personnel") or {}
            gap = view.get("gap")
            if gap is None:
                return None
            if (view.get("bad_team") or {}).get("team") == pick["side"]:
                return None          # players model doesn't back bottom-10 teams (measured: 46.8%)
            # with day-to-day players, count only what holds in EVERY version of tonight (plays or
            # sits) — the same rule T13 bets on. The early-combo history (26-10) was measured with
            # lineups known, so assuming an uncertain player plays overstates the agreement.
            gaps = [s["gap"] for s in view.get("scenarios") or [] if s.get("gap") is not None] or [gap]
            home = pick["side"] == g.get("home")
            mine = [x if home else -x for x in gaps]
            return round(min(mine), 1)
    return None
SPREAD_SD = 14.14        # measured: home margin minus spread, 979 games 2025-26
TOTAL_SD = 18.18         # measured: actual total minus closing total, 1,194 games 2025-26
MIN_SIZE = 10            # skip a quote with less than this much available
WINDOW = {"spread": 4.0, "total": 6.0}     # only compare numbers this close to the pick's line
_N = NormalDist()


def kalshi_fee(p: float) -> float:
    return math.ceil(0.07 * p * (1 - p) * 100 - 1e-9) / 100


def max_price(win: float) -> float | None:
    """Highest Kalshi ask (dollars) where the bet still has value after the fee."""
    best = None
    for c in range(1, 100):
        p = c / 100
        if p + kalshi_fee(p) <= win:
            best = p
    return best


def win_estimate(pick: dict, slate: list[dict]) -> float | None:
    return win_and_line(pick, slate)[0]


# EARLY + players model agreeing by 3+: 26-10 (72%) vs the open over 2 seasons (backtest_og.py).
# Only 36 games, so the win rate is shrunk hard toward 50%: 50% + 22.2 pts × 36 / (36 + 100) = 55.9%.
EARLY_STACK_MIN_GAP = 3.0
EARLY_STACK_WIN = 0.559


def _card_wl(card: str) -> tuple[int, int]:
    w, l = card.split(" ")[0].split("-")[:2]
    return int(w), int(l)


# The record each card bet carries before this season (shown as-is, never shrunk). This season's
# graded bets are added on top by run.build_board, so the number grows as the system bets.
HISTORY = {**{sid: (*_card_wl(m["card"]), f"{m['card'].split('·')[-1].strip()} card") for sid, m in SYSTEMS.items()},
           102: (56, 43, "2 seasons, at the open"), 112: (79, 62, "2 seasons, at the open"),
           121: (194, 124, "6 seasons"), 122: (149, 91, "6 seasons"), 123: (149, 86, "6 seasons"),
           124: (69, 31, "6 seasons"), 125: (212, 164, "6 seasons")}


def history(pick: dict, slate: list[dict]) -> dict | None:
    sid = pick["system"]
    if group(sid) == "EARLY":
        h = players_history("EARLY", EARLY_STACK_MIN_GAP)
        part = players_history(label(sid), EARLY_STACK_MIN_GAP)       # this one system's share of the combo
        return ({"w": h["w"], "l": h["l"], "label": "2 seasons, early system + players model 3+, at the open",
                 "part": {"tag": label(sid), "w": part["w"], "l": part["l"]} if part else None} if h else None)
    if sid == 113:
        for g in slate:
            c = ((g.get("personnel") or {}).get("case") or {})
            m = c.get("measured") or {}
            if g.get("game_id") == pick["game_id"] and c.get("side") == pick["side"] and m.get("w") is not None:
                return {"w": m["w"], "l": m["l"], "label": f"2 seasons, gaps of {m.get('tier', 3)}+, {m.get('window')}, at the open"}
        return None
    if sid in HISTORY:
        w, l, lab = HISTORY[sid]
        return {"w": w, "l": l, "label": lab}
    return None


def early_stack(pick: dict, slate: list[dict]) -> bool:
    """An early-season system bet where the players model likes the same side by 3+."""
    if group(pick["system"]) != "EARLY" or pick["bet"] != "spread":
        return False
    pg = players_gap(pick, slate)
    return pg is not None and pg >= EARLY_STACK_MIN_GAP


def win_and_line(pick: dict, slate: list[dict]) -> tuple[float | None, float | None]:
    """Expected win rate and the line it applies to. System rates apply at the pick's current line;
    the personnel case is rebuilt every run at the CURRENT market line, so a T13 bet that locked at an
    earlier number is shopped from where the market is now, not from the old number."""
    sid = pick["system"]
    if sid in SYSTEMS:
        return SYSTEMS[sid]["card_win_rate"], pick.get("line")
    if group(sid) == "EARLY":
        return (EARLY_STACK_WIN, pick.get("line")) if early_stack(pick, slate) else (None, None)
    if (TEST_SYSTEMS.get(sid) or {}).get("win_est"):
        return TEST_SYSTEMS[sid]["win_est"], pick.get("line")
    for g in slate:
        c = ((g.get("personnel") or {}).get("case") or {})
        if g.get("game_id") == pick["game_id"] and c.get("side") == pick["side"]:
            return c.get("win_est"), c.get("line", pick.get("line"))
    return None, None


def confidence(pick: dict, slate: list[dict]) -> str | None:
    """High / Medium / Low from the personnel case (how well the edge survives the stress tests)."""
    for g in slate:
        c = ((g.get("personnel") or {}).get("case") or {})
        if g.get("game_id") == pick["game_id"] and c.get("side") == pick["side"]:
            return c.get("level")
    return None


def market_line(pick: dict, slate: list[dict]) -> float | None:
    """The consensus number for the pick's side right now (median of US books)."""
    for g in slate:
        if g.get("game_id") != pick["game_id"]:
            continue
        if pick["bet"] == "total":
            return g.get("total")
        hs = g.get("home_spread")
        return None if hs is None else (hs if pick["side"] == g.get("home") else -hs)
    return None


# What each extra point of spread is worth, MEASURED on six seasons (2020-21 to 2025-26, 6,979 games,
# closing consensus lines; engine/measure_points.py, reports/engine.measure_points.txt): the gain in cover
# chance for d = 0.5, 1.0, ... 7.0 extra points over the line. A bell curve (SD 14.14) says ~2.8% a point;
# real NBA results agree for lines within 3, but around lines of 3.5+ the first points are worth ~3.7-4.2%
# each (results bunch closer to the line than a bell curve). Totals stay on the bell curve (SD 18.18).
POINT_GAIN = {
    "close within 3": [0.014, 0.028, 0.040, 0.054, 0.071, 0.085, 0.097, 0.109, 0.122, 0.137, 0.154, 0.167, 0.181, 0.196],
    "3.5 to 7":       [0.021, 0.039, 0.056, 0.074, 0.093, 0.108, 0.122, 0.134, 0.147, 0.160, 0.174, 0.187, 0.198, 0.208],
    "7.5+":           [0.021, 0.039, 0.056, 0.075, 0.092, 0.110, 0.127, 0.145, 0.162, 0.178, 0.193, 0.208, 0.221, 0.233],
}


def point_gain(abs_line: float, d: float) -> float:
    """Measured change in cover chance from getting d more points (negative d = giving points up)."""
    g = POINT_GAIN["close within 3" if abs_line <= 3 else "3.5 to 7" if abs_line <= 7 else "7.5+"]
    a = abs(d)
    if a <= 7:
        i = a * 2                                        # position on the half-point grid
        lo = int(i)
        glo = 0.0 if lo == 0 else g[lo - 1]
        ghi = g[min(lo, 13)] if lo < 14 else g[13]
        val = glo + (ghi - glo) * (i - lo)
    else:
        val = g[13] + (g[13] - g[11]) * (a - 7)         # beyond 7: keep the last measured slope
    return val if d >= 0 else -val


def outcome(win0: float, pick_line: float, bet: str, side: str, line: float) -> tuple[float, float]:
    """(win, push) at `line`, given a win rate of win0 at the pick's own line."""
    sd = TOTAL_SD if bet == "total" else SPREAD_SD
    z0 = _N.inv_cdf(min(max(win0, 0.01), 0.99))
    over = bet == "total" and side == "OVER"

    def cover(L):           # chance the result beats L (a half-point line)
        if bet != "total":                              # spreads: measured value of each point
            return min(max(win0 + point_gain(abs(pick_line), L - pick_line), 0.01), 0.99)
        return _N.cdf(z0 + ((pick_line - L) if over else (L - pick_line)) / sd)

    if float(line).is_integer():
        worse, better = (line + 0.5, line - 0.5) if over else (line - 0.5, line + 0.5)
        w = cover(worse)
        return w, cover(better) - w
    return cover(line), 0.0


def expected_return(win: float, push: float, cost: float) -> float:
    """Per $1 staked, buying $1 payouts at `cost` each."""
    return win * (1 / cost - 1) - (1 - win - push)


def price_text(q: dict) -> str:
    if q["venue"] == "kalshi":
        return f"{round(q['price'] * 100)}¢"
    a = q["american"]
    return f"{a:+d}"


SUSPECT = 0.10     # a quote 10+ points of probability cheaper than the consensus says is a data error, not a gift


# The numbers each system allows on the bet itself (Caden: if a system needs +8 or more, never shop
# down to +7 — then it isn't that system's bet). Spread lines are the bet side's line; totals are the total.
LINE_BOUNDS = {
    2: (-99.0, -0.5),     # S2 road FAVORITE
    3: (-99.0, -0.5),     # S3 home FAVORITE
    4: (220.5, 999.0),    # S4 over: total above 220
    112: (-99.0, -8.0),   # T12 favorite by 8+
    202: (0.5, 7.0),      # E2 home underdog of 7 or less
    203: (10.0, 99.0),    # E3 underdog of 10+
    205: (0.5, 99.0),     # E5 bet against a favorite → we're the dog
    207: (0.5, 99.0),     # E7 bet against a favorite → we're the dog
}


def allowed_lines(p: dict, slate: list[dict]) -> tuple[float, float]:
    """Lowest and highest number this bet may be taken at."""
    lo, hi = LINE_BOUNDS.get(p["system"], (-999.0, 999.0))
    if p["system"] == 113:               # T13: the players-model edge must stay 3+ at the number we take
        for g in slate:
            c = ((g.get("personnel") or {}).get("case") or {})
            if g.get("game_id") == p["game_id"] and c.get("side") == p["side"] and c.get("cushion") is not None:
                lo = max(lo, c["line"] - (c["cushion"] - 3.0))
    return lo, hi


def shop(p: dict, win0: float, base: float | None = None, market: float | None = None,
         bounds: tuple[float, float] = (-999.0, 999.0)) -> list[dict]:
    base = p["line"] if base is None else base
    out = []
    for q in p.get("shop") or []:
        if q["bet"] != p["bet"] or q["side"] != p["side"]:
            continue
        if not (bounds[0] - 1e-9 <= q["line"] <= bounds[1] + 1e-9):
            continue                      # outside what the system allows
        if q.get("size") is not None and q["size"] < MIN_SIZE:
            continue
        if abs(q["line"] - p["line"]) > WINDOW[p["bet"]]:
            continue
        win, push = outcome(win0, base, p["bet"], p["side"], q["line"])
        if market is not None:
            mw, mp = outcome(0.5, market, p["bet"], p["side"], q["line"])
            if q["cost"] < mw / (1 - mp) - SUSPECT:
                continue                    # e.g. a feed that swapped the two teams' spreads
        breakeven = win / (1 - push) if push < 1 else 1.0          # cost at which expected return is 0
        out.append({**q, "win": round(win, 4), "push": round(push, 4),
                    "ev": round(expected_return(win, push, q["cost"]), 4),
                    "max_cost": round(breakeven, 4), "price_txt": price_text(q),
                    "mine": q["venue"] in MY_VENUES})
    return prefer_points(out)


# Caden (2026-10-22): when two prices make about the same money, take the one that wins more often.
# A cheaper number has to beat the best price with more points by this much expected return to be chosen.
POINTS_TIEBREAK = 0.02


def prefer_points(quotes: list[dict]) -> list[dict]:
    """Best first. Among quotes within POINTS_TIEBREAK of the top expected return, the one most likely
    to cash (more points) goes first; everything else stays in expected-return order."""
    out = sorted(quotes, key=lambda q: -q["ev"])
    if not out:
        return out
    top = out[0]["ev"]
    near = [q for q in out if q["ev"] >= top - POINTS_TIEBREAK]
    rest = [q for q in out if q["ev"] < top - POINTS_TIEBREAK]
    near.sort(key=lambda q: (-(q["win"] + q.get("push", 0) / 2), -q["ev"]))
    return near + rest


def _desc(q: dict) -> str:
    fee = "" if q["fee_counted"] else " (fees not counted)"
    return f"{q['venue_name']} {q['contract']} at {q['price_txt']}{fee}"


def build_card(live: list[dict], slate: list[dict], now: datetime | None = None) -> list[dict]:
    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    rows = []
    stacks = {}
    for p in live:
        if p["system"] < 300 and p.get("line") is not None:
            stacks.setdefault((p["game_id"], p["bet"], p["side"]), []).append(label(p["system"]))
    main_sides = {(p["game_id"], p["bet"], p["side"]) for p in live
                  if group(p["system"]) in ("OG", "FAV") and p.get("line") is not None}
    # a MONEYBALL stack replaces every other card bet on that same side (one bigger bet, not several)
    mb_sides = {(p["game_id"], p["bet"], p["side"]) for p in live if p["system"] == 130 and p.get("line") is not None}
    for p in live:
        if p.get("line") is None:
            continue
        if p["system"] != 130 and (p["game_id"], p["bet"], p["side"]) in mb_sides:
            continue
        if group(p["system"]) not in ("OG", "FAV"):
            # EARLY + players model 3+ makes the card, unless an OG/FAV bet already covers that side
            if not early_stack(p, slate) or (p["game_id"], p["bet"], p["side"]) in main_sides:
                continue
        if p.get("tip_utc") and p["tip_utc"] < now_iso:
            continue  # already tipped: nothing left to bet
        win, base = win_and_line(p, slate)
        if win is None:
            continue
        quotes = shop(p, win, base, market_line(p, slate), allowed_lines(p, slate))
        mine = [q for q in quotes if q["mine"]]
        best = mine[0] if mine else None
        kalshi = [q for q in mine if q["venue"] == "kalshi"]
        # the Kalshi contract at (or nearest) the pick's own number — where a limit order goes
        at_line = min(kalshi, key=lambda q: (abs(q["line"] - p["line"]), -q["ev"])) if kalshi else None
        cap = max_price(at_line["max_cost"]) if at_line else None
        pg = players_gap(p, slate)          # for T13 this is its own gap (worst day-to-day case)
        pb = agree_bucket(pg) if pg is not None else None
        if best and best["ev"] >= MIN_EV:
            verdict = "BET"
            why = f"Best price: {_desc(best)}, {best['ev']:+.1%} expected return"
            runner = next((q for q in mine[1:] if q["venue"] != best["venue"]), None)
            if runner:
                why += f". Next best: {_desc(runner)}, {runner['ev']:+.1%}"
        elif best:
            if cap is not None and (win > BREAK_EVEN_110 or cap >= 0.45):
                verdict = "LIMIT"
                why = (f"No venue clears the {MIN_EV:.0%} bar right now (best: {_desc(best)}, {best['ev']:+.1%}). "
                       f"Set a limit on Kalshi {at_line['contract']} at {round(cap * 100)}¢")
            else:
                verdict, why = "PASS", f"Not enough edge at today's prices (best: {_desc(best)}, {best['ev']:+.1%})"
        elif win > BREAK_EVEN_110:
            verdict, why = "BET", "No exchange market yet: take it at -110 or better"
        else:
            verdict, why = "PASS", "Not enough edge at today's prices"
        edge = best["ev"] if best else win - BREAK_EVEN_110
        from .systems import EARLY_SYSTEMS
        name = (SYSTEMS.get(p["system"]) or TEST_SYSTEMS.get(p["system"]) or EARLY_SYSTEMS.get(p["system"]) or {}).get("name", "")
        if group(p["system"]) == "EARLY":
            name += f" + players model agrees by {pg:g} (2 seasons: 26-10 at the open)"
        k = p.get("kalshi") or {}
        rows.append({"key": p["key"], "label": p["label"], "away": p["away"], "home": p["home"],
                     "game_id": p["game_id"], "game_date": p.get("game_date"), "bet": p["bet"], "side": p["side"],
                     "line": p["line"], "tip_utc": p.get("tip_utc"), "tag": label(p["system"]),
                     "group": group(p["system"]), "name": name, "win": round(win, 3),
                     "price": at_line["price"] if at_line else k.get("price"),
                     "cost": at_line["cost"] if at_line else None, "max": cap,
                     "verdict": verdict, "why": why, "edge": round(edge, 4),
                     # bet size: every card bet wins $20; MONEYBALL wins $30. (Confidence sizing removed
                     # 2026-10-27: T13 now needs a 4+ gap, so the small, weak edges it shrank are gone.)
                     "to_win": MONEYBALL_TO_WIN if p["system"] == 130 else TO_WIN,
                     # what an order placer needs to price ANY number on this bet (e.g. P2P offers)
                     "model": {"win0": round(win, 4), "base": base, "bet": p["bet"], "side": p["side"],
                               "sd": TOTAL_SD if p["bet"] == "total" else SPREAD_SD,
                               "lo": allowed_lines(p, slate)[0], "hi": allowed_lines(p, slate)[1],
                               "market": market_line(p, slate)},
                     "players": pg, "players_bucket": pb, "system": p["system"], "history": history(p, slate),
                     "players_history": players_history(group(p["system"]), pg),
                     "contract": at_line["contract"] if at_line else k.get("contract"),
                     "url": (best or {}).get("url") or k.get("url"),
                     "best": best, "shop": quotes[:8],
                     "with": [x for x in stacks.get((p["game_id"], p["bet"], p["side"]), []) if x != label(p["system"])]})
    # a main bet that an early stack also lands on: show the early combo's record on it too
    for r in rows:
        if r["group"] == "EARLY":
            continue
        for p in live:
            if (p["game_id"], p["bet"], p["side"]) == (r["game_id"], r["bet"], r["side"]) and early_stack(p, slate):
                h = history(p, slate)
                if h:
                    r["also_combo"] = {**h, "tag": label(p["system"])}
                break
    # never bet both sides of the same game: when card bets disagree, none of them is bet.
    # MEASURED (engine/measure_combined.py, 2025-26 out of sample): 12 such games; betting both sides
    # only pays the vig twice. One bet per game with conflicts skipped: 135-97, +12.2% per unit.
    live_ = [r for r in rows if r["verdict"] in ("BET", "LIMIT")]
    for r in live_:
        other = [x for x in live_ if x["game_id"] == r["game_id"] and x["bet"] == r["bet"] and x["side"] != r["side"]]
        if other:
            r["verdict"] = "CONFLICT"
            r["why"] = ("Not bet: " + ", ".join(f"{x['tag']} ({x['label']})" for x in other)
                        + " is on the other side of this game. Betting both sides only pays the vig twice.")
    order = {"BET": 0, "LIMIT": 1, "PASS": 2, "CONFLICT": 3}
    rows.sort(key=lambda r: (order[r["verdict"]], -r["edge"]))
    return rows


def feed_rows(card: list[dict], now: datetime) -> list[dict]:
    """One row per card bet for the bet_feed table (what an outside bettor/scanner reads)."""
    out = []
    for c in card:
        b = c.get("best") or {}
        out.append({
            "key": c["key"], "updated_at": now.isoformat(), "status": c["verdict"].lower(), "verdict": c["verdict"],
            "game_id": c["game_id"], "game_date": c.get("game_date"), "tip_utc": c.get("tip_utc"),
            "away": c["away"], "home": c["home"], "system": c["tag"], "sys_group": c["group"],
            "bet": c["bet"], "side": c["side"], "pick": c["label"], "model_line": c["line"], "win": c["win"],
            "best_venue": b.get("venue"), "best_line": b.get("line"),
            "best_price": b.get("price") if b.get("venue") == "kalshi" else b.get("american"),
            "best_cost": b.get("cost"), "best_ev": b.get("ev"), "best_contract": b.get("contract"),
            "best_ticker": b.get("ticker"), "best_url": b.get("url"), "max_price": c.get("max"),
            "why": c["why"], "to_win": c.get("to_win"), "model": c.get("model"),
            "quotes": [{k: q.get(k) for k in ("venue", "venue_name", "contract", "side", "ml", "line", "price",
                                              "american", "cost", "fee_counted", "size", "win", "ev", "max_cost",
                                              "ticker", "order_side", "price_txt")}
                       for q in c.get("shop", [])],
        })
    return out
