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


def test_model_vs_a_venues_own_line_even_when_pinnacle_has_a_different_number():
    js = {"bookmakers": [book("pinnacle", -110, -110, point=14.5, name="Sub Guy", market="player_points"),
                         book("novig", -110, -110, point=12.5, name="Sub Guy", market="player_points")]}
    proj = {("g1", "sub guy"): {"pts": 16.0, "mpg": 25.0}}
    e = E.venue_model_edges(js, "g1", proj)
    assert len(e) == 1 and (e[0]["venue"], e[0]["line"], e[0]["side"], e[0]["fair"], e[0]["pin_line"]) == ("novig", 12.5, "over", None, 14.5)
    st = E.step({}, NOW, [G], lambda g: js, [], {}, [], proj)
    assert E.summary(st)["model_venue"]["bets"] == 1 and st["bets"][0]["clv"] is None


def test_opening_lines_news_desk_and_the_ready_list():
    js = {"bookmakers": [book("novig", -110, -110, point=12.5, name="Sub Guy", market="player_points")]}
    proj = {("g1", "sub guy"): {"pts": 16.0, "mpg": 25.0, "team": "TOR"}}
    early = NOW - timedelta(hours=14)                       # 20 hours before tip: only the opening model reads
    st = E.step({}, early, [G], lambda g: js, [], {}, [], proj)
    assert [b["kind"] for b in st["bets"]] == ["open"] and st["bets"][0]["hours_before"] == 20.2
    # 3 hours later the line moved to 14.5: our over moved +2 our way
    moved = {"bookmakers": [book("novig", -110, -110, point=14.5, name="Sub Guy", market="player_points")]}
    st = E.step(st, early + timedelta(hours=3), [G], lambda g: moved, [], {}, [], proj)
    assert st["bets"][0]["move"] == 2.0 and len([b for b in st["bets"] if b["kind"] == "open"]) == 1
    # news: a TOR rotation player is ruled out -> forced read, teammates bet at the line right now
    st = E.step(st, NOW, [G], lambda g: js, [], {}, [], proj, {"g1": [("Starter", "TOR")]})
    nb = [b for b in st["bets"] if b["kind"] == "news"]
    assert len(nb) == 1 and nb[0]["news_player"] == "Starter"
    # the ready list: if a questionable player sits, Sub Guy's line would be 3+ off (and isn't now)
    calm = {("g1", "sub guy"): {"pts": 13.0, "mpg": 25.0, "team": "TOR"}}
    st = E.step(st, NOW + timedelta(minutes=5), [G], lambda g: js, [], {}, [], calm, {"g1": [("Other", "TOR")]},
                {("g1", "Starter"): {("g1", "sub guy"): {"pts": 17.0, "mpg": 25.0, "team": "TOR"}}})
    r = st["ready"]["g1"]["list"]
    assert r and r[0]["if_out"] == "Starter" and r[0]["side"] == "over" and r[0]["proj_now"] == 13.0
    s = E.summary(st)
    assert s["open_lines"]["bets"] == 1 and s["news_desk"]["bets"] == 1      # "Other" out: 13.0 vs 12.5, no bet


def test_a_first_read_close_to_tip_is_not_an_opening_line():
    js = {"bookmakers": [book("novig", -110, -110, point=12.5, name="Sub Guy", market="player_points")]}
    proj = {("g1", "sub guy"): {"pts": 16.0, "mpg": 25.0, "team": "TOR"}}
    st = E.step({}, NOW, [G], lambda g: js, [], {}, [], proj)          # 6 hours before tip
    assert not [b for b in st["bets"] if b["kind"] == "open"] and "g1" in st["opened"]


def test_props_stack_trackers_fire_on_both_flags_with_their_numbers_once_per_player():
    from engine.props_stack import fire
    # a 32 mpg starter on a 12-point underdog whose implied total is 6 below its average
    feat = {"name": "Derrick White", "m5": 32.0, "m10": 32.0, "abs_spread": 12.0, "team_total": 104.0, "team_avg": 110.0,
            "pts_savg": 15.0, "luck_pm": 0.0, "shot_match": 1.0, "pts_opp": 1.0}
    got = fire(feat, 15.5, 15.0)
    assert [(n, s) for n, s, _ in got] == [("Under: blowout + low team total", "under")]
    assert "12.0-point spread" in got[0][2][0] and "-6.0 vs its average" in got[0][2][1]
    assert fire({**feat, "abs_spread": 6.0}, 15.5, 15.0) == []                 # no blowout: nothing
    js = {"bookmakers": [book("pinnacle", -110, -110, point=15.5, market="player_points"),
                         book("novig", -105, 100, point=15.5, market="player_points")]}
    proj = {("g1", "derrick white"): {"pts": 15.0, "mpg": 32.0, "feat": feat}}   # keyed by the normalised name
    soon = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)                  # inside 12 hours of tip
    st = E.step({}, soon, [G], lambda g: js, [], {}, [], proj)
    pb = [b for b in st["bets"] if b.get("kind") == "pstack"]
    assert len(pb) == 1 and (pb[0]["side"], pb[0]["venue"], pb[0]["price"]) == ("under", "novig", 100)
    st = E.step(st, soon + timedelta(hours=2), [G], lambda g: js, [], {}, [], proj)
    assert len([b for b in st["bets"] if b.get("kind") == "pstack"]) == 1      # once per player and tracker
    s = E.summary(st)["stack_trackers"]
    assert s["Under: blowout + low team total"]["open"] == 1 and len(s) == 9
