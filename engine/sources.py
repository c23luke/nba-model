"""Data feeds: ESPN (schedule + final scores), The Odds API (lines), Kalshi (prices).

Only the Python standard library is used, so the runner needs no installs.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .state import Game
from .teams import code

ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "nba-model/1.0"}


def get_json(url: str, headers: dict | None = None, meta: dict | None = None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        if meta is not None:
            meta.update({k.lower(): v for k, v in r.headers.items()})
        return json.loads(r.read().decode())


def et_date(iso_utc: str) -> date:
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(ET).date()


# --------------------------------------------------------------------- ESPN
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"


def espn_day(day: date) -> list[tuple[Game, dict | None]]:
    """Regular-season games on one ET date, each with ESPN's posted line (DraftKings) if any."""
    data = get_json(ESPN.format(day.strftime("%Y%m%d")))
    out = []
    for e in data.get("events", []):
        if e.get("season", {}).get("type") != 2:          # 2 = regular season
            continue
        c = e["competitions"][0]
        home = next(x for x in c["competitors"] if x["homeAway"] == "home")
        away = next(x for x in c["competitors"] if x["homeAway"] == "away")
        st = e["status"]
        final = bool(st["type"].get("completed"))
        g = Game(
            id=str(e["id"]), game_date=et_date(e["date"]), tip_utc=e["date"],
            away=code(away["team"]["abbreviation"]), home=code(home["team"]["abbreviation"]),
            away_score=int(away["score"]) if final else None,
            home_score=int(home["score"]) if final else None,
            periods=int(st.get("period") or 0) if final else None, final=final,
        )
        out.append((g, _espn_line(c.get("odds") or [], g)))
    return out


def _espn_line(odds: list, g: Game) -> dict | None:
    if not odds:
        return None
    o = odds[0]
    details = (o.get("details") or "").strip()
    home_spread = None
    if details.upper() in ("EVEN", "PK", "PICK"):
        home_spread = 0.0
    elif details:
        try:
            abbr, num = details.rsplit(" ", 1)
            num = float(num)
            home_spread = num if code(abbr) == g.home else -num
        except (ValueError, KeyError):
            home_spread = None
    total = o.get("overUnder")
    if home_spread is None and total is None:
        return None
    return {"home_spread": home_spread, "total": float(total) if total else None,
            "source": f"ESPN ({(o.get('provider') or {}).get('name', 'book')})", "books": 1}


# ----------------------------------------------------------- The Odds API
ODDS = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        "?apiKey={key}&regions=us&markets=spreads,totals&oddsFormat=american")


def odds_api_lines(api_key: str) -> tuple[dict, dict]:
    """Consensus (median across US books) home spread and total, keyed by (ET date, away, home).

    Costs 2 credits per call (2 markets x 1 region)."""
    meta: dict = {}
    events = get_json(ODDS.format(key=api_key), meta=meta)
    lines = parse_odds_events(events)
    usage = {"remaining": meta.get("x-requests-remaining"), "used": meta.get("x-requests-used")}
    return lines, usage


# Exchanges: one call covers every venue Caden uses (3 credits: spreads, totals, moneyline).
EXCHANGE_ODDS = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
                 "?apiKey={key}&regions=us_ex&markets=spreads,totals,h2h&oddsFormat=american&includeBetLimits=true")
VENUES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US", "polymarket": "Polymarket",
          "prophetx": "ProphetX", "betopenly": "BetOpenly", "novig": "Novig"}
MY_VENUES = {"kalshi", "polymarket_us", "polymarket", "prophetx", "betopenly"}   # where Caden has accounts
EXCHANGE_CACHE_SECONDS = 180
_exchange_cache: dict = {}


def american_cost(a) -> float:
    """What $1 of payout costs at American odds (= implied probability, vig included)."""
    a = float(a)
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def parse_exchange_events(events: list) -> dict:
    """Every exchange price, keyed by (ET date, away, home). Kalshi is skipped here: it comes straight
    from Kalshi with every strike and the exact fee."""
    out = {}
    for ev in events:
        try:
            home, away = code(ev["home_team"]), code(ev["away_team"])
        except KeyError:
            continue
        qs = []
        for bk in ev.get("bookmakers", []):
            if bk["key"] == "kalshi" or bk["key"] not in VENUES:
                continue
            for m in bk.get("markets", []):
                for o in m.get("outcomes", []):
                    try:
                        if m["key"] == "totals":
                            bet, side, line, ml = "total", o["name"].upper(), float(o["point"]), False
                            contract = f"{o['name']} {line:g}"
                        else:
                            bet, side, ml = "spread", code(o["name"]), m["key"] == "h2h"
                            line = -0.5 if ml else float(o["point"])
                            contract = f"{side} to win" if ml else f"{side} {line:+g}"
                        out_q = {"venue": bk["key"], "venue_name": VENUES[bk["key"]], "bet": bet, "side": side,
                                 "line": line, "ml": ml, "american": int(o["price"]),
                                 "cost": round(american_cost(o["price"]), 4), "fee_counted": False,
                                 "size": o.get("bet_limit"), "contract": contract, "url": None, "ticker": None}
                    except (KeyError, TypeError, ValueError):
                        continue
                    qs.append(out_q)
        out[(et_date(ev["commence_time"]), away, home)] = qs
    return out


def exchange_quotes(api_key: str, clock=time.time) -> tuple[dict, dict]:
    """Exchange prices for every game, cached a few minutes so a busy news hour doesn't burn credits."""
    if _exchange_cache and clock() - _exchange_cache["at"] < EXCHANGE_CACHE_SECONDS:
        return _exchange_cache["data"], _exchange_cache["usage"]
    meta: dict = {}
    events = get_json(EXCHANGE_ODDS.format(key=api_key), meta=meta)
    data = parse_exchange_events(events)
    usage = {"remaining": meta.get("x-requests-remaining"), "used": meta.get("x-requests-used")}
    _exchange_cache.update(at=clock(), data=data, usage=usage)
    return data, usage


ODDS_HIST = ("https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"
             "?apiKey={key}&regions=us&markets={markets}&oddsFormat=american&date={when}")


def odds_api_historical(api_key: str, when_iso: str, markets: str = "spreads") -> tuple[dict, dict]:
    """Snapshot of every NBA line at one moment in the past (10 credits per market x region)."""
    meta: dict = {}
    js = get_json(ODDS_HIST.format(key=api_key, when=when_iso, markets=markets), meta=meta)
    return parse_odds_events(js.get("data") or []), {"remaining": meta.get("x-requests-remaining")}


def parse_odds_events(events: list) -> dict:
    lines = {}
    for ev in events:
        try:
            home, away = code(ev["home_team"]), code(ev["away_team"])
        except KeyError:
            continue
        spreads, totals, per_book = [], [], {}
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m["key"] == "spreads":
                    for oc in m["outcomes"]:
                        if code(oc["name"]) == home and oc.get("point") is not None:
                            spreads.append(float(oc["point"]))
                            per_book.setdefault(bk["key"], {})["spread"] = float(oc["point"])
                elif m["key"] == "totals":
                    for oc in m["outcomes"]:
                        if oc["name"] == "Over" and oc.get("point") is not None:
                            totals.append(float(oc["point"]))
                            per_book.setdefault(bk["key"], {})["total"] = float(oc["point"])
        if not spreads and not totals:
            continue
        lines[(et_date(ev["commence_time"]), away, home)] = {
            "home_spread": _half(statistics.median(spreads)) if spreads else None,
            "total": _half(statistics.median(totals)) if totals else None,
            "source": "Odds API consensus", "books": len(per_book), "by_book": per_book,
        }
    return lines


def _half(x: float) -> float:
    """Median of books can land on .25/.75 — snap to the nearest half point."""
    return round(x * 2) / 2


# ------------------------------------------------------------------ Kalshi
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker={}&limit=200"


def kalshi_event(series: str, g: Game) -> str:
    d = g.game_date
    return f"{series}-{d:%y}{d.strftime('%b').upper()}{d:%d}{g.away}{g.home}"


def kalshi_markets(series: str, g: Game) -> list[dict]:
    try:
        return get_json(KALSHI.format(kalshi_event(series, g))).get("markets", [])
    except Exception:
        return []


def _px(m: dict, field: str) -> float | None:
    v = m.get(f"{field}_dollars")
    if v is None and m.get(field) is not None:
        v = m[field] / 100
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 1 else None


def kalshi_fee(p: float) -> float:
    """Kalshi taker fee per contract: 7% x P x (1-P), rounded up to the cent."""
    import math
    return math.ceil(0.07 * p * (1 - p) * 100 - 1e-9) / 100


def kalshi_quote(pick, g: Game, fetch=kalshi_markets) -> dict | None:
    """Find the Kalshi contract that matches the pick and what it costs right now."""
    if pick.line is None:
        return None
    url = f"https://kalshi.com/markets/kxnbagame/nba-game/{kalshi_event('KXNBAGAME', g).lower()}"

    if pick.bet == "total":
        mk = [m for m in fetch("KXNBATOTAL", g) if m.get("floor_strike") is not None]
        want = pick.line
        best = _closest(mk, want, lambda m: float(m["floor_strike"]))
        if not best:
            return None
        price = _px(best, "yes_ask")
        return _quote(best["ticker"], f"YES · Over {best['floor_strike']:g}", price,
                      float(best["floor_strike"]) == want, url)

    team, opp = pick.side, (g.away if pick.side == g.home else g.home)
    if -1.0 <= pick.line <= 0:          # pick'em or -1: winning outright is the same or better bet
        pick_line_ml = True
    else:
        pick_line_ml = False
    if pick_line_ml:                                           # straight win market
        mk = [m for m in fetch("KXNBAGAME", g) if m["ticker"].endswith("-" + team)]
        if not mk:
            return None
        return _quote(mk[0]["ticker"], f"YES · {team} to win", _px(mk[0], "yes_ask"), pick.line == 0, url)

    mk = fetch("KXNBASPREAD", g)
    strike = abs(pick.line)
    if pick.line < 0:      # favorite: YES on "team wins by over X"
        cands = [m for m in mk if m["ticker"].rsplit("-", 1)[-1].startswith(team) and m.get("floor_strike") is not None]
        best = _closest(cands, strike, lambda m: float(m["floor_strike"]))
        if not best:
            return None
        return _quote(best["ticker"], f"YES · {team} wins by over {best['floor_strike']:g}",
                      _px(best, "yes_ask"), float(best["floor_strike"]) == strike, url)
    # underdog +X: NO on "opponent wins by over X"
    cands = [m for m in mk if m["ticker"].rsplit("-", 1)[-1].startswith(opp) and m.get("floor_strike") is not None]
    best = _closest(cands, strike, lambda m: float(m["floor_strike"]), prefer_low=False)
    if not best:
        return None
    price = _px(best, "no_ask")
    if price is None and _px(best, "yes_bid") is not None:
        price = round(1 - _px(best, "yes_bid"), 4)
    return _quote(best["ticker"], f"NO · {opp} wins by over {best['floor_strike']:g}  (= {team} +{best['floor_strike']:g})",
                  price, float(best["floor_strike"]) == strike, url)


def _no_price(m: dict) -> float | None:
    p = _px(m, "no_ask")
    if p is None and _px(m, "yes_bid") is not None:
        p = round(1 - _px(m, "yes_bid"), 4)
    return p


def kalshi_ladder(pick, g: Game, fetch=kalshi_markets) -> list[dict]:
    """Every Kalshi contract that pays on the pick's side, at every strike (so +4.5 at 45c can be
    weighed against +3.5 at 50c), with the fee counted. Moneyline counts as -0.5."""
    url = f"https://kalshi.com/markets/kxnbagame/nba-game/{kalshi_event('KXNBAGAME', g).lower()}"
    out: list[dict] = []

    def add(m, contract, side, line, price, bet, ml=False):
        if price is None:
            return
        fee = kalshi_fee(price)
        out.append({"venue": "kalshi", "venue_name": "Kalshi", "bet": bet, "side": side, "line": line, "ml": ml,
                    "order_side": "no" if contract.startswith("NO") else "yes",
                    "price": price, "fee": fee, "cost": round(price + fee, 4), "fee_counted": True,
                    "size": None, "contract": contract, "url": url, "ticker": m["ticker"]})

    if pick.bet == "total":
        for m in fetch("KXNBATOTAL", g):
            if m.get("floor_strike") is None:
                continue
            x = float(m["floor_strike"])
            if pick.side == "OVER":
                add(m, f"YES · Over {x:g}", "OVER", x, _px(m, "yes_ask"), "total")
            else:
                add(m, f"NO · Over {x:g}  (= Under {x:g})", "UNDER", x, _no_price(m), "total")
        return out
    team = pick.side
    opp = g.away if team == g.home else g.home
    for m in fetch("KXNBAGAME", g):
        if m["ticker"].endswith("-" + team):
            add(m, f"YES · {team} to win", team, -0.5, _px(m, "yes_ask"), "spread", ml=True)
    for m in fetch("KXNBASPREAD", g):
        if m.get("floor_strike") is None:
            continue
        x, who = float(m["floor_strike"]), m["ticker"].rsplit("-", 1)[-1]
        if who.startswith(team):
            add(m, f"YES · {team} wins by over {x:g}", team, -x, _px(m, "yes_ask"), "spread")
        elif who.startswith(opp):
            add(m, f"NO · {opp} wins by over {x:g}  (= {team} +{x:g})", team, x, _no_price(m), "spread")
    return out


def _closest(markets, target, key, prefer_low=True):
    """Nearest strike; on a tie take the one better for the bettor
    (lower strike for overs/favorites, higher strike when we hold the NO side for an underdog)."""
    return min(markets, key=lambda m: (abs(key(m) - target), key(m) if prefer_low else -key(m)), default=None)


def _quote(ticker, desc, price, exact, url):
    if price is None:
        return {"ticker": ticker, "contract": desc, "price": None, "exact": exact, "url": url}
    fee = kalshi_fee(price)
    return {"ticker": ticker, "contract": desc, "price": price, "fee": fee,
            "cost": round(price + fee, 4), "exact": exact, "url": url}
