"""Bets the order placer actually filled (bet_orders, live), shaped for the website.

Each row says what we bought and where, the price we paid, what it risks and pays, the expected
return the model saw, why we took it (the card's reasoning, snapshotted while the bet was on the card),
the system's record (all-time = its history + this season), and how it finished — graded at the
number we actually hold, not the card's number.
"""
from __future__ import annotations

import re
from datetime import datetime

from .pricing import outcome

VENUE_NAMES = {"kalshi": "Kalshi", "betopenly": "BetOpenly", "polymarket_us": "Polymarket US",
               "polymarket": "Polymarket", "prophetx": "ProphetX", "manual": "Other book"}

# what the website needs from a card row to explain a bet later, after the row has left the card
SNAP_KEYS = ("name", "why", "confidence", "to_win", "win", "players", "players_bucket", "players_history",
             "also_combo", "with", "label", "line")


def snapshot(card_row: dict) -> dict:
    s = {k: card_row.get(k) for k in SNAP_KEYS}
    s["history"] = (card_row.get("record") or {}).get("history") or card_row.get("history")
    return s


def american(p: float) -> int:
    """American odds for a price per $1 payout (0.43 -> +133, 0.5 -> +100, 0.55 -> -122)."""
    return round(100 * (1 - p) / p) if p <= 0.5 else -round(100 * p / (1 - p))     # even money is +100


def holding(o: dict) -> str:
    """The position we actually hold, in plain betting terms: 'NOP +1.5', 'OVER 221.5', 'NOP ML'."""
    side, line, bet = o.get("side") or "", o.get("line"), o.get("bet") or "spread"
    if line is None:
        return o.get("contract") or side
    if bet == "total":
        return f"{side} {line:g}"
    if "KXNBAGAME" in (o.get("market") or "") or "to win" in (o.get("contract") or ""):
        return f"{side} ML"
    return f"{side} {'+' if line > 0 else '−' if line < 0 else ''}{abs(line):g}" if line else f"{side} PK"


def margin(o: dict, g: dict) -> float | None:
    """How far the bet is winning by (negative = losing) at the number we hold, on the current score."""
    hs, as_ = g.get("home_score"), g.get("away_score")
    if hs is None or as_ is None:
        return None
    line = float(o["line"])
    if o.get("bet") == "total":
        return (line - (hs + as_)) if o.get("side") == "UNDER" else ((hs + as_) - line)
    return (hs - as_ if o.get("side") == g.get("home") else as_ - hs) + line


def grade(o: dict, g: dict) -> str | None:
    m = margin(o, g) if g.get("final") else None
    return None if m is None else "W" if m > 0 else "L" if m < 0 else "P"


def number(label: str | None) -> float | None:
    """The line in a pick label: 'NOP +3.5' -> 3.5, 'MEM −1' -> -1, 'OVER 220.5' -> 220.5."""
    m = re.search(r"([+\-−]?\d+(?:\.\d+)?)\s*$", (label or "").strip())
    return None if not m else float(m.group(1).replace("−", "-"))


def moved_our_way(bet: str, side: str, at_bet: float, now: float) -> float:
    """Points the market moved in our favour since we bet (+ = we got the better number)."""
    return round((now - at_bet) if side == "OVER" else (at_bet - now), 1)


def beat_close(o: dict, per: float, close: float) -> float | None:
    """Cents per $1 payout we beat the closing market by: what our exact number was worth at the close
    (a 50/50 market at the closing line, same result spread as the model) minus what we paid."""
    try:
        win, push = outcome(0.5, float(close), o.get("bet") or "spread", o.get("side") or "", float(o["line"]))
    except (TypeError, ValueError):
        return None
    return round((win / (1 - push) - per) * 100, 1)


def placed_bets(orders: list[dict], picks: dict, games: dict, card: dict, season_wl, now: datetime,
                line_now=None, names: dict | None = None) -> dict:
    """orders: filled live bet_orders rows. picks: key -> pick (meta.card_snap holds the snapshot).
    games: id -> game row. card: key -> current card row. season_wl(pick) -> {w, l, p} this season.
    line_now(game_id, bet, side) -> the market line on our side right now (before tip), or None."""
    now_iso = now.isoformat()
    rows, waiting = [], []
    for o in orders:
        cnt, cost = float(o.get("fill_count") or 0), float(o.get("fill_cost") or 0)
        if o.get("status") == "resting" and (o.get("tip_utc") or "") > now_iso:
            lim = float(o.get("limit_price") or 0)
            waiting.append({"key": o.get("bet_key"), "pick": o.get("pick"), "system": o.get("system"),
                            "venue_name": VENUE_NAMES.get(o.get("venue"), o.get("venue")), "contract": o.get("contract"),
                            "holding": holding(o), "price": lim, "american": american(lim) if 0 < lim < 1 else None,
                            "count": o.get("count"), "stake": o.get("stake"), "filled": cnt, "tip_utc": o.get("tip_utc"),
                            "placed_at": o.get("created_at")})
        if cnt <= 0:
            continue
        fees = float(o.get("fees") or 0)
        venue = o.get("venue") or ""
        p = picks.get(o.get("bet_key")) or {}
        snap = snapshot(card[o["bet_key"]]) if o.get("bet_key") in card else ((p.get("meta") or {}).get("card_snap") or {})
        o = {**o, "bet": o.get("bet") or p.get("bet"), "side": o.get("side") or p.get("side")}
        per = cost / cnt
        upfront_fee = fees if venue == "kalshi" else 0.0          # BetOpenly takes its cut out of winnings
        risk = cost + upfront_fee
        to_win = cnt - cost - fees
        g = games.get(o.get("game_id")) or {}
        tip = o.get("tip_utc") or p.get("tip_utc") or ""
        res = grade(o, g) if g else None
        status = "FINAL" if res else ("LIVE" if tip and tip <= now_iso else "OPEN")
        pnl = None if not res else round(to_win if res == "W" else -risk if res == "L" else -upfront_fee, 2)
        # the market since we bet: the card number when we placed it vs now (open) or at the close (tipped)
        at_bet = number(o.get("pick"))
        close = (p.get("meta") or {}).get("close_line") if status != "OPEN" else None
        if close is None and status == "OPEN" and line_now:
            now_line = line_now(o.get("game_id"), o.get("bet"), o.get("side"))
        else:
            now_line = close
        if close is None and status != "OPEN":
            close = g.get("total") if o.get("bet") == "total" else (
                None if g.get("home_spread") is None else
                g["home_spread"] if o.get("side") == g.get("home") else -g["home_spread"])
            now_line = close
        market = None
        if now_line is not None:
            market = {"at_bet": at_bet, "line": now_line, "closed": status != "OPEN",
                      "moved": None if at_bet is None else moved_our_way(o.get("bet"), o.get("side"), at_bet, now_line),
                      "beat_close": beat_close(o, per, now_line)}
        mg = margin(o, g) if status == "LIVE" and g else None
        hist = snap.get("history") or None
        season = season_wl(p) if p else {"w": 0, "l": 0, "p": 0}
        rows.append({
            "id": o.get("id"), "placed_at": o.get("created_at"), "key": o.get("bet_key"),
            "game_id": o.get("game_id"), "tip_utc": tip, "away": p.get("away"), "home": p.get("home"),
            "venue": venue, "venue_name": VENUE_NAMES.get(venue, venue), "contract": o.get("contract"),
            "holding": holding(o), "card_pick": o.get("pick"), "bet": o.get("bet"), "side": o.get("side"),
            "line": o.get("line"), "price": round(per, 4), "american": american(per) if 0 < per < 1 else None,
            "count": cnt, "cost": round(cost, 2), "fees": round(fees, 2), "risk": round(risk, 2),
            "to_win": round(to_win, 2), "ev": o.get("ev"), "model_price": o.get("model_price"),
            "system": o.get("system"), "group": p.get("group"), "name": snap.get("name") or (names or {}).get(o.get("system")),
            "evidence": p.get("evidence") or [], "price_note": snap.get("why"), "confidence": snap.get("confidence"), "win": snap.get("win"),
            "players": snap.get("players"), "players_history": snap.get("players_history"),
            "also_combo": snap.get("also_combo"), "with": snap.get("with") or [],
            # what the bet was sized to win when placed (older bets: $10 when the retired Low-confidence rule applied)
            "t13_gap": (p.get("meta") or {}).get("worst_gap") if o.get("system") == "T13" else None,
            "target": snap.get("to_win") or (10 if snap.get("confidence") == "Low" else 20),
            "record": {"history": hist, "season": season,
                       "w": (hist or {}).get("w", 0) + season["w"], "l": (hist or {}).get("l", 0) + season["l"]},
            "manual": venue == "manual", "status": status, "result": res, "pnl": pnl, "market": market, "covering": mg,
            "final_score": p.get("final_score") if res else None,
            "score": {"home": g.get("home_score"), "away": g.get("away_score")} if status != "OPEN" and g else None,
        })
    rows.sort(key=lambda r: (r["status"] == "FINAL", r["tip_utc"] or "", r["placed_at"] or ""))
    settled = [r for r in rows if r["status"] == "FINAL"]
    open_ = [r for r in rows if r["status"] != "FINAL"]
    w, l, pu = (sum(r["result"] == x for r in settled) for x in "WLP")
    pnl = round(sum(r["pnl"] for r in settled), 2)
    risked = round(sum(r["risk"] for r in settled), 2)
    by_venue = {}
    for r in rows:
        v = by_venue.setdefault(r["venue_name"], {"bets": 0, "open": 0, "pnl": 0.0})
        v["bets"] += 1
        v["open"] += r["status"] != "FINAL"
        v["pnl"] = round(v["pnl"] + (r["pnl"] or 0), 2)
    return {"bets": rows, "resting": waiting, "rules_now": rules_now(rows), "summary": {
        "open": len(open_), "at_risk": round(sum(r["risk"] for r in open_), 2),
        "open_to_win": round(sum(r["to_win"] for r in open_), 2),
        "w": w, "l": l, "p": pu, "pnl": pnl, "risked": risked,
        "roi": round(pnl / risked, 4) if risked else None,
        "since": min((r["placed_at"] for r in rows if r["placed_at"]), default=None),
        "avg_beat_close": (lambda xs: round(sum(xs) / len(xs), 1) if xs else None)(
            [r["market"]["beat_close"] for r in rows if r["market"] and r["market"]["closed"] and r["market"]["beat_close"] is not None]),
        "by_venue": by_venue}}


T13_GAP_NOW = 4.0      # engine/systems.T13_GAP


def rules_now(rows: list[dict]) -> dict:
    """Every settled bet re-judged under TODAY's rules, at the price we actually got:
      - T13 only at a 4+ gap (worst case over day-to-day players): smaller ones would not be placed
      - both sides of one game: neither is placed
      - every bet sized to win $20 (MONEYBALL $30), even ones the old Low-confidence rule cut to $10
        or that only part-filled
    The real money (what actually happened) stays as it is; this is the record the current model
    would have, so the systems are judged fairly."""
    done = [r for r in rows if r["status"] == "FINAL" and not r.get("manual")]
    sides = {}
    for r in rows:
        sides.setdefault(r["game_id"], set()).add((r.get("bet"), r.get("side")))
    out = {"w": 0, "l": 0, "p": 0, "pnl": 0.0, "risked": 0.0, "dropped": [], "resized": []}
    for r in done:
        why = None
        if r["system"] == "T13" and r.get("t13_gap") is not None and r["t13_gap"] < T13_GAP_NOW:
            why = f"T13 gap {r['t13_gap']:g}: today it needs 4+"
        spreads = {sd for bt, sd in sides.get(r["game_id"], set()) if bt == r.get("bet")}
        if len(spreads) > 1:
            why = "we held both sides of this game: today neither is bet"
        if why:
            out["dropped"].append({"holding": r["holding"], "system": r["system"], "result": r["result"],
                                   "pnl": r["pnl"], "why": why})
            continue
        target = 30.0 if r["system"] == "MONEYBALL" else 20.0
        odds = r["risk"] / r["to_win"] if r["to_win"] else 1.0         # risk per $1 of winnings, at our price
        pnl = target if r["result"] == "W" else -target * odds if r["result"] == "L" else 0.0
        if abs(r["to_win"] - target) >= 1:
            out["resized"].append({"holding": r["holding"], "system": r["system"], "result": r["result"],
                                   "had": round(r["to_win"], 2), "now": target, "pnl_had": r["pnl"], "pnl_now": round(pnl, 2)})
        out[{"W": "w", "L": "l"}.get(r["result"], "p")] += 1
        out["pnl"] += pnl
        out["risked"] += target * odds
    out["pnl"], out["risked"] = round(out["pnl"], 2), round(out["risked"], 2)
    return out
