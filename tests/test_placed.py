"""Placed bets on the website: what we bought, where, at what price, why, and how it finished."""
from datetime import date, datetime, timezone

from engine.placed import american, grade, holding, placed_bets
from engine.run import run
from engine.store import LocalStore
from tests.test_run import START, fake_kalshi, fake_lines, make_fetch_day


def test_american_odds_and_what_we_hold():
    assert american(0.43) == 133 and american(0.55) == -122 and american(0.5) == 100
    assert holding({"side": "NOP", "line": 1.5, "bet": "spread"}) == "NOP +1.5"
    assert holding({"side": "MEM", "line": -1.0, "bet": "spread"}) == "MEM −1"
    assert holding({"side": "OVER", "line": 221.5, "bet": "total"}) == "OVER 221.5"
    assert holding({"side": "NOP", "line": -0.5, "bet": "spread", "market": "KXNBAGAME-26OCT21INDNOP-NOP"}) == "NOP ML"


def test_graded_at_the_number_we_hold_not_the_card_number():
    g = {"final": True, "home": "NOP", "away": "IND", "home_score": 110, "away_score": 113}
    assert grade({"side": "NOP", "line": 3.5, "bet": "spread"}, g) == "W"     # card number covers
    assert grade({"side": "NOP", "line": 1.5, "bet": "spread"}, g) == "L"     # the number we bought doesn't
    assert grade({"side": "NOP", "line": 3.0, "bet": "spread"}, g) == "P"
    assert grade({"side": "UNDER", "line": 224.5, "bet": "total"}, g) == "W"
    assert grade({"side": "NOP", "line": 1.5}, {**g, "final": False}) is None


def test_summary_counts_risk_fees_and_results():
    now = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    o = lambda **k: {"mode": "live", "venue": "kalshi", "bet_key": "k1", "game_id": "g1", "tip_utc": "2026-10-21T23:30:00+00:00",
                     "bet": "spread", "side": "NOP", "line": 1.5, "fill_count": 37, "fill_cost": 15.91, "fees": 0.63,
                     "created_at": "2026-10-21T01:40:00+00:00", "ev": 0.127, **k}
    games = {"g1": {"final": True, "home": "NOP", "away": "IND", "home_score": 115, "away_score": 108},
             "g2": {"final": False, "home": "MEM", "away": "UTA"}}
    picks = {"k1": {"key": "k1", "system": 113, "group": "FAV", "away": "IND", "home": "NOP", "meta": {
        "card_snap": {"name": "Players model", "why": "edge 4.2", "confidence": "Medium",
                      "history": {"w": 157, "l": 141, "label": "2 seasons"}}}}}
    out = placed_bets([o(), o(bet_key="k2", game_id="g2", venue="betopenly", fill_count=40, fill_cost=20.0, fees=0.2,
                         tip_utc="2026-10-23T00:00:00+00:00")],
                      picks, games, {}, lambda p: {"w": 1, "l": 0, "p": 0}, now)
    won, open_ = out["bets"][1], out["bets"][0]
    assert (won["status"], won["result"], won["holding"], won["venue_name"]) == ("FINAL", "W", "NOP +1.5", "Kalshi")
    assert won["risk"] == 16.54 and won["to_win"] == 20.46 and won["pnl"] == 20.46 and won["american"] == 133
    assert won["price_note"] == "edge 4.2" and won["record"]["w"] == 158 and won["record"]["l"] == 141
    assert open_["status"] == "OPEN" and open_["risk"] == 20.0 and open_["to_win"] == 19.8      # BetOpenly: fee from winnings
    s = out["summary"]
    assert (s["open"], s["w"], s["l"], s["pnl"], s["at_risk"]) == (1, 1, 0, 20.46, 20.0)
    assert s["by_venue"]["Kalshi"]["pnl"] == 20.46 and s["by_venue"]["BetOpenly"]["open"] == 1


def test_placed_bet_keeps_its_reasoning_after_it_tips_and_grades(tmp_path):
    store = LocalStore(tmp_path)
    kw = dict(fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines, **kw)
    c = next(c for c in b["card"] if c["tag"] == "S1")
    assert b["placed"]["bets"] == []
    store._write("bet_orders", [{"id": "o1", "mode": "live", "venue": "kalshi", "bet_key": c["key"], "game_id": c["game_id"],
                                 "tip_utc": c["tip_utc"], "pick": c["label"], "system": "S1", "bet": "spread", "side": "LAL",
                                 "line": 6.5, "contract": "NO · MIL wins by over 6.5 (= LAL +6.5)", "status": "filled",
                                 "fill_count": 36, "fill_cost": 19.8, "fees": 0.6, "ev": 0.08,
                                 "created_at": "2025-11-15T15:01:00+00:00"}])
    # during the game: off the card, but the bet still says why we took it
    b = run(now=datetime(2025, 11, 16, 1, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=lambda: ({}, {}), **kw)
    assert not any(x["key"] == c["key"] for x in b["card"])
    r = b["placed"]["bets"][0]
    assert (r["status"], r["holding"], r["price_note"], r["name"]) == ("LIVE", "LAL +6.5", c["why"], c["name"])
    assert r["evidence"] and "overtime" in r["evidence"][0]
    assert r["record"]["history"] == c["record"]["history"]
    # next morning: graded at +6.5 (LAL won 119-95)
    b = run(now=datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)), fetch_lines=lambda: ({}, {}), **kw)
    r = b["placed"]["bets"][0]
    assert (r["status"], r["result"], r["pnl"]) == ("FINAL", "W", 15.6)
    assert r["record"]["season"]["w"] == 1                              # the system's own graded pick counts this season
    assert b["placed"]["summary"]["pnl"] == 15.6
