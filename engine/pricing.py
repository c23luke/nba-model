"""What to bet today: one ranked card from every OG and FAV pick, priced.

Expected win rate per pick (conservative, measured — never a hunch):
  OG S1-S4   the card's long-run win rate (S4's two-season replay, 56%, matched its card)
  T13        50% + 2.8% per point of measured line movement for this stage and gap size
  T2, T12    halfway between 50% and their two-season replay
  T21-T24    halfway between 50% and their six-season search record
Verdict:
  BET        Kalshi's price (with fee) is at or under the most it's worth, or no Kalshi
             market and the win rate beats -110 (52.4%)
  LIMIT      worth betting, but Kalshi is too pricey right now: set a limit at the max price
  PASS       not enough edge at any normal price
"""
from __future__ import annotations

import math

from .systems import SYSTEMS, TEST_SYSTEMS, label, group

BREAK_EVEN_110 = 110 / 210


def kalshi_fee(p: float) -> float:
    return math.ceil(0.07 * p * (1 - p) * 100) / 100


def max_price(win: float) -> float | None:
    """Highest Kalshi ask (dollars) where the bet still has value after the fee."""
    best = None
    for c in range(1, 100):
        p = c / 100
        if p + kalshi_fee(p) <= win:
            best = p
    return best


def win_estimate(pick: dict, slate: list[dict]) -> float | None:
    sid = pick["system"]
    if sid in SYSTEMS:
        return SYSTEMS[sid]["card_win_rate"]
    if (TEST_SYSTEMS.get(sid) or {}).get("win_est"):
        return TEST_SYSTEMS[sid]["win_est"]
    for g in slate:
        c = ((g.get("personnel") or {}).get("case") or {})
        if g.get("game_id") == pick["game_id"] and c.get("side") == pick["side"]:
            return c.get("win_est")
    return None


def build_card(live: list[dict], slate: list[dict]) -> list[dict]:
    rows = []
    stacks = {}
    for p in live:
        if p["system"] < 300 and p.get("line") is not None:
            stacks.setdefault((p["game_id"], p["bet"], p["side"]), []).append(label(p["system"]))
    for p in live:
        if group(p["system"]) not in ("OG", "FAV") or p.get("line") is None:
            continue
        win = win_estimate(p, slate)
        if win is None:
            continue
        k = p.get("kalshi") or {}
        price = k.get("price")
        cap = max_price(win)
        cost = None if price is None else round(price + kalshi_fee(price), 2)
        if price is not None and cap is not None and price <= cap + 1e-9:
            verdict, why = "BET", f"Kalshi {round(price * 100)}¢ (+{round(kalshi_fee(price) * 100)}¢ fee) is under the {round(cap * 100)}¢ max"
        elif price is None and win > BREAK_EVEN_110:
            verdict, why = "BET", "No Kalshi market: take it at -110 or better at a book"
        elif price is not None and cap is not None and (win > BREAK_EVEN_110 or cap >= 0.45):
            verdict, why = "LIMIT", f"Kalshi {round(price * 100)}¢ is over the {round(cap * 100)}¢ max: set a limit at {round(cap * 100)}¢"
        else:
            verdict, why = "PASS", "Not enough edge at today's prices"
        edge = win - (cost if cost is not None else BREAK_EVEN_110)
        name = (SYSTEMS.get(p["system"]) or TEST_SYSTEMS.get(p["system"]) or {}).get("name", "")
        rows.append({"key": p["key"], "label": p["label"], "away": p["away"], "home": p["home"],
                     "tip_utc": p.get("tip_utc"), "tag": label(p["system"]), "group": group(p["system"]),
                     "name": name, "win": round(win, 3), "price": price, "cost": cost,
                     "max": cap, "verdict": verdict, "why": why, "edge": round(edge, 3),
                     "contract": k.get("contract"), "url": k.get("url"),
                     "with": [x for x in stacks.get((p["game_id"], p["bet"], p["side"]), []) if x != label(p["system"])]})
    order = {"BET": 0, "LIMIT": 1, "PASS": 2}
    rows.sort(key=lambda r: (order[r["verdict"]], -r["edge"]))
    return rows
