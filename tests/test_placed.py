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


def test_line_movement_and_beating_the_close():
    from engine.placed import beat_close, moved_our_way, number
    assert number("NOP +3.5") == 3.5 and number("MEM −1") == -1 and number("OVER 220.5") == 220.5 and number("x") is None
    assert moved_our_way("spread", "NOP", 3.5, 2.5) == 1.0          # dog got a point more than the close
    assert moved_our_way("total", "OVER", 220.5, 222.5) == 2.0 and moved_our_way("total", "UNDER", 220.5, 222.5) == -2.0
    o = {"bet": "spread", "side": "NOP", "line": 1.5}
    assert beat_close(o, 0.43, 1.5) == 7.0                              # 50¢ fair at the close, paid 43¢
    assert beat_close(o, 0.43, 3.5) < 7.0 and beat_close(o, 0.43, 3.5) > 0    # +1.5 is worth less when the close is +3.5
    assert beat_close(o, 0.43, -0.5) > 7.0                               # market moved our way: NOP now favoured
    assert beat_close(o, 0.43, 8.5) < 0                                  # market moved hard against us


def test_open_bet_tracks_the_market_and_live_bet_shows_if_covering():
    now = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)
    o = {"mode": "live", "venue": "kalshi", "bet_key": "k1", "game_id": "g1", "pick": "NOP +3.5", "bet": "spread",
         "side": "NOP", "line": 1.5, "fill_count": 37, "fill_cost": 15.91, "fees": 0.63, "created_at": "2026-10-21T01:40:00+00:00"}
    picks = {"k1": {"key": "k1", "system": 113, "group": "FAV", "away": "IND", "home": "NOP"}}
    later = {**o, "tip_utc": "2026-10-23T00:00:00+00:00"}
    r = placed_bets([later], picks, {}, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now, lambda gid, bet, side: 2.5)["bets"][0]
    assert r["market"]["moved"] == 1.0 and r["market"]["closed"] is False and r["market"]["line"] == 2.5
    live = {**o, "tip_utc": "2026-10-22T00:00:00+00:00"}
    g = {"g1": {"final": False, "home": "NOP", "away": "IND", "home_score": 88, "away_score": 90, "home_spread": 3.5}}
    r = placed_bets([live], picks, g, {}, lambda p: {"w": 0, "l": 0, "p": 0}, now)["bets"][0]
    assert r["status"] == "LIVE" and r["covering"] == -0.5                     # down 2 with +1.5
    assert r["market"]["line"] == 3.5 and r["market"]["closed"]                # NOP home dog +3.5 at the close


def test_placer_skip_reasons_reach_the_board(tmp_path):
    store = LocalStore(tmp_path)
    store._write("bet_log", [{"ts": "2025-11-15T14:59:00+00:00", "message": "run (live, prod): 1 bets", "level": "info",
                              "data": {"skips": [{"pick": "LAL +6 (S1) LAL@MIL", "reason": "price moved"}]}}])
    b = run(now=datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc),
            fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)), fetch_lines=fake_lines,
            fetch_kalshi=fake_kalshi, store=store, season_start=START, personnel_fetch=None, fetch_box=None)
    assert b["placer"]["skips"][0]["reason"] == "price moved"


def test_a_bet_placed_by_hand_counts_like_any_other():
    o = {"venue": "manual", "bet_key": "k", "game_id": "g", "tip_utc": "2026-10-20T19:00Z", "pick": "DET +1.5", "system": "T13",
         "bet": "spread", "side": "DET", "line": 1.5, "fill_count": 40.8, "fill_cost": 20.8, "fees": 0,
         "created_at": "2026-10-20T18:00:00Z"}
    g = {"g": {"final": True, "home": "DET", "away": "BOS", "home_score": 121, "away_score": 113, "home_spread": 1.5}}
    out = placed_bets([o], {"k": {"key": "k", "system": 113, "group": "FAV", "away": "BOS", "home": "DET"}}, g, {},
                      lambda p: {"w": 1, "l": 0, "p": 0}, datetime(2026, 10, 21, 3, tzinfo=timezone.utc), names={"T13": "Personnel gap"})
    r = out["bets"][0]
    assert (r["venue_name"], r["manual"], r["american"], r["risk"], r["to_win"]) == ("Other book", True, -104, 20.8, 20.0)
    assert (r["result"], r["pnl"], r["name"]) == ("W", 20.0, "Personnel gap")
    assert out["summary"]["w"] == 1 and out["summary"]["pnl"] == 20.0
