"""Props +EV vs Pinnacle (tracking only, 2026-11-11)."""
from datetime import date, datetime, timedelta, timezone

from engine import props_ev as E
from engine.state import Game

NOW = datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc)
G = Game(id="g1", game_date=date(2026, 11, 11), away="BOS", home="TOR", tip_utc="2026-11-12T00:10Z")


def book(key, over, under, point=4.5, name="Derrick White", market="player_assists"):
    outs = []
    if over is not None:
        outs.append({"name": "Over", "description": name, "point": point, "price": over})
    if under is not None:
        outs.append({"name": "Under", "description": name, "point": point, "price": under})
    return {"key": key, "markets": [{"key": market, "outcomes": outs}]}


def test_fair_odds_take_pinnacles_vig_out():
    f = E.fair({"Over": -110.0, "Under": -110.0})
    assert round(f["Over"], 4) == 0.5
    f = E.fair({"Over": -123.0, "Under": -107.0})
    assert round(f["Over"] + f["Under"], 6) == 1.0 and f["Over"] > 0.5


def test_a_venue_paying_3_percent_more_than_fair_is_an_edge_at_the_same_line_only():
    js = {"bookmakers": [book("pinnacle", -110, -110), book("novig", 112, -130),
                         book("prophetx", 120, -140, point=5.5)]}           # different line: ignored
    e = E.edges(js)
    assert len(e) == 1 and (e[0]["venue"], e[0]["side"], e[0]["stat"], e[0]["line"]) == ("novig", "over", "ast", 4.5)
    assert e[0]["ev"] == round(0.5 * E.dec(112) - 1, 4)                     # +6%
    assert E.edges({"bookmakers": [book("pinnacle", -110, -110), book("novig", 102, -120)]}) == []   # +1%: no


def test_paper_bet_then_clv_against_pinnacles_close_then_grade():
    js = {"bookmakers": [book("pinnacle", -110, -110), book("novig", 112, -130)]}
    st = E.step({}, NOW, [G], lambda g: js, [], {}, [{"game_id": "g1", "player": "Derrick White", "stat": "ast", "side": "over"}])
    b = st["bets"][0]
    assert b["stacked"] is True and b["clv"] == round(0.5 - 1 / E.dec(112), 4)
    # 30 minutes later: not re-read; in the last 25 minutes: the closing read (Pinnacle moved to -130 on the over)
    calls = []
    E.step(st, NOW + timedelta(minutes=30), [G], lambda g: calls.append(1) or js, [], {}, [])
    assert calls == []
    close = {"bookmakers": [book("pinnacle", -130, 110)]}
    st = E.step(st, datetime(2026, 11, 11, 23, 50, tzinfo=timezone.utc), [G], lambda g: close, [], {}, [])
    cf = E.fair({"Over": -130.0, "Under": 110.0})["Over"]
    assert st["bets"][0]["close_fair"] == round(cf, 4) and st["bets"][0]["clv"] == round(round(cf, 4) - 1 / E.dec(112), 4)   # +7.1 cents
    box = [{"game_id": "g1", "team": "BOS", "name": "Derrick White", "min": 33, "pts": 12, "orb": 0, "drb": 3, "ast": 7}]
    st = E.step(st, NOW + timedelta(hours=9), [], lambda g: None, box, {"g1": {"final": True}}, [])
    s = E.summary(st)
    assert (s["w"], s["l"], s["stacked"]["w"], s["units"]) == (1, 0, 1, 1.12)


def test_model_edge_takes_the_best_venue_price_on_the_side_our_projection_points_to():
    js = {"bookmakers": [book("pinnacle", -110, -110, point=12.5, name="Sub Guy", market="player_points"),
                         book("novig", -105, -115, point=12.5, name="Sub Guy", market="player_points")]}
    proj = {("g1", "sub guy"): {"pts": 16.0, "reb": 3.0, "ast": 2.0, "min": 26.0, "l10": {"pts": 11.0},
                                "fresh_out": ["Starter"], "mpg": 14.0}}
    e = E.model_edges(js, "g1", proj)
    assert len(e) == 1 and (e[0]["side"], e[0]["venue"], e[0]["price"], e[0]["proj"]) == ("over", "novig", -105.0, 16.0)
    assert E.model_edges(js, "g1", {("g1", "sub guy"): {"pts": 14.0}}) == []          # only 1.5 off
    st = E.step({}, NOW, [G], lambda g: js, [], {}, [], proj)
    s = E.summary(st)
    assert s["model"]["bets"] == 1 and s["bets"] == 0
    assert s["spot_fresh"]["bets"] == 1 and s["spot_bench"]["bets"] == 1           # both spots tracked on their own
