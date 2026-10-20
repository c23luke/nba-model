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
            gap = (g.get("personnel") or {}).get("gap")
            if gap is None:
                return None
            return round(gap if pick["side"] == g.get("home") else -gap, 1)
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


def win_and_line(pick: dict, slate: list[dict]) -> tuple[float | None, float | None]:
    """Expected win rate and the line it applies to. System rates apply at the pick's current line;
    the personnel case is rebuilt every run at the CURRENT market line, so a T13 bet that locked at an
    earlier number is shopped from where the market is now, not from the old number."""
    sid = pick["system"]
    if sid in SYSTEMS:
        return SYSTEMS[sid]["card_win_rate"], pick.get("line")
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


def outcome(win0: float, pick_line: float, bet: str, side: str, line: float) -> tuple[float, float]:
    """(win, push) at `line`, given a win rate of win0 at the pick's own line."""
    sd = TOTAL_SD if bet == "total" else SPREAD_SD
    z0 = _N.inv_cdf(min(max(win0, 0.01), 0.99))
    over = bet == "total" and side == "OVER"

    def cover(L):           # chance the result beats L (a half-point line)
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


def shop(p: dict, win0: float, base: float | None = None, market: float | None = None) -> list[dict]:
    base = p["line"] if base is None else base
    out = []
    for q in p.get("shop") or []:
        if q["bet"] != p["bet"] or q["side"] != p["side"]:
            continue
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
    out.sort(key=lambda q: -q["ev"])
    return out


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
    for p in live:
        if group(p["system"]) not in ("OG", "FAV") or p.get("line") is None:
            continue
        if p.get("tip_utc") and p["tip_utc"] < now_iso:
            continue  # already tipped: nothing left to bet
        win, base = win_and_line(p, slate)
        if win is None:
            continue
        quotes = shop(p, win, base, market_line(p, slate))
        mine = [q for q in quotes if q["mine"]]
        best = mine[0] if mine else None
        kalshi = [q for q in mine if q["venue"] == "kalshi"]
        # the Kalshi contract at (or nearest) the pick's own number — where a limit order goes
        at_line = min(kalshi, key=lambda q: (abs(q["line"] - p["line"]), -q["ev"])) if kalshi else None
        cap = max_price(at_line["max_cost"]) if at_line else None
        pg = players_gap(p, slate) if p["system"] != 113 else None      # T13 IS the players model
        pb = agree_bucket(pg) if pg is not None else None
        level = confidence(p, slate) if p["system"] == 113 else None
        if level == "Low":
            verdict = "PASS"
            why = ("Low confidence: the edge drops under 3 points in at least one version of the model. "
                   "Tracked on the every-game tracker, not bet")
        elif best and best["ev"] > 0:
            verdict = "BET"
            why = f"Best price: {_desc(best)}, {best['ev']:+.1%} expected return"
            runner = next((q for q in mine[1:] if q["venue"] != best["venue"]), None)
            if runner:
                why += f". Next best: {_desc(runner)}, {runner['ev']:+.1%}"
        elif best:
            if cap is not None and (win > BREAK_EVEN_110 or cap >= 0.45):
                verdict = "LIMIT"
                why = (f"No venue has value right now (best: {_desc(best)}, {best['ev']:+.1%}). "
                       f"Set a limit on Kalshi {at_line['contract']} at {round(cap * 100)}¢")
            else:
                verdict, why = "PASS", f"Not enough edge at today's prices (best: {_desc(best)}, {best['ev']:+.1%})"
        elif win > BREAK_EVEN_110:
            verdict, why = "BET", "No exchange market yet: take it at -110 or better"
        else:
            verdict, why = "PASS", "Not enough edge at today's prices"
        edge = best["ev"] if best else win - BREAK_EVEN_110
        name = (SYSTEMS.get(p["system"]) or TEST_SYSTEMS.get(p["system"]) or {}).get("name", "")
        k = p.get("kalshi") or {}
        rows.append({"key": p["key"], "label": p["label"], "away": p["away"], "home": p["home"],
                     "game_id": p["game_id"], "game_date": p.get("game_date"), "bet": p["bet"], "side": p["side"],
                     "line": p["line"], "tip_utc": p.get("tip_utc"), "tag": label(p["system"]),
                     "group": group(p["system"]), "name": name, "win": round(win, 3),
                     "price": at_line["price"] if at_line else k.get("price"),
                     "cost": at_line["cost"] if at_line else None, "max": cap,
                     "verdict": verdict, "why": why, "edge": round(edge, 4), "confidence": level,
                     "players": pg, "players_bucket": pb,
                     "players_history": players_history(group(p["system"]), pg),
                     "contract": at_line["contract"] if at_line else k.get("contract"),
                     "url": (best or {}).get("url") or k.get("url"),
                     "best": best, "shop": quotes[:8],
                     "with": [x for x in stacks.get((p["game_id"], p["bet"], p["side"]), []) if x != label(p["system"])]})
    order = {"BET": 0, "LIMIT": 1, "PASS": 2}
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
            "why": c["why"],
            "quotes": [{k: q.get(k) for k in ("venue", "venue_name", "contract", "side", "ml", "line", "price",
                                              "american", "cost", "fee_counted", "size", "win", "ev", "max_cost",
                                              "ticker", "order_side", "price_txt")}
                       for q in c.get("shop", [])],
        })
    return out
