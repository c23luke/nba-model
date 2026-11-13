"""Thin rosters (2026-11-11): the players model doesn't bet ALONE on a side leaning on players it barely knows."""
from datetime import date

from engine import personnel as P
from engine.personnel import Player, TeamRead
from engine.state import Game
from engine.systems import evaluate_personnel, personnel_call

G = Game(id="g", game_date=date(2026, 11, 11), away="CHI", home="BOS", tip_utc="2026-11-12T00:00Z")


def team(code, thin_minutes):
    tr = TeamRead(code)
    vet = {"mp": 1500}
    tr.players = [Player(f"{code}v{i}", "active", 5, vet, minutes=48.0) for i in range(5)]
    if thin_minutes:
        tr.players[0].last = None                         # a rookie / new to the league...
        tr.players[0].live = {"min": 150.0}               # ...with 150 minutes so far
        tr.players[0].minutes = thin_minutes
    return tr


def view(gap):
    return {"gap": gap, "fair": -5.0, "away_rating": 0.0, "home_rating": 0.0, "scenarios": []}


def test_thin_share_counts_only_players_with_no_season_behind_them_and_under_200_minutes():
    tr = team("CHI", 48.0)
    assert P.thin_share(tr) == 48 / 240
    tr.players[0].live = {"min": 250.0}
    assert P.thin_share(tr) == 0.0


def test_no_solo_bet_on_the_thinner_side_but_the_other_side_is_fine():
    v = view(-5.0)                                        # model likes CHI (away) by 5
    P.flag_thin(v, team("CHI", 48.0), team("BOS", 0.0))
    assert v["thin"]["team"] == "CHI" and personnel_call(v, 4.0) == {"call": "none", "thin": True}
    assert evaluate_personnel(G, 3.0, v) == []
    v2 = view(5.0)                                        # model likes BOS; CHI is the thin one: bet stands
    P.flag_thin(v2, team("CHI", 48.0), team("BOS", 0.0))
    assert "thin" not in v2 and personnel_call(v2, 4.0)["call"] == "now"
    v3 = view(-5.0)                                       # 4% apart: about even, no flag
    P.flag_thin(v3, team("CHI", 9.6), team("BOS", 0.0))
    assert "thin" not in v3


def test_t13_against_a_thin_roster_is_sized_at_2_units_and_counted_that_way():
    from engine.pricing import THIN_FADE_TO_WIN, thin_fade
    slate = [{"game_id": "g", "home": "BOS", "away": "CHI", "personnel": {"thin_share": {"home": 0.0, "away": 0.2}}}]
    t13 = {"system": 113, "bet": "spread", "game_id": "g", "side": "BOS"}
    assert thin_fade(t13, slate) == {"team": "CHI", "share": 0.2, "ours": 0.0} and THIN_FADE_TO_WIN == 40
    assert thin_fade({**t13, "side": "CHI"}, slate) is None          # we'd be the thin side (and T13 can't fire there)
    assert thin_fade({**t13, "system": 130}, slate) is None          # MONEYBALL is already 2 units
    slate[0]["personnel"]["thin_share"]["away"] = 0.04
    assert thin_fade(t13, slate) is None                             # under 5 points apart


def test_rosters_are_reused_for_15_minutes_and_cleared_by_news(monkeypatch):
    import engine.personnel as P
    calls = []

    def fake(url):
        calls.append(url)
        if url == P.ESPN_TEAMS:
            return {"sports": [{"leagues": [{"teams": [{"team": {"id": "2", "abbreviation": "BOS"}}]}]}]}
        return {"athletes": [{"displayName": "Derrick White", "status": {"type": "active"}}]}
    monkeypatch.setattr(P, "get_json", fake)
    P.clear_roster_cache()
    a = P.fetch_rosters(P.get_json)
    a["BOS"][0]["status"] = "edited"                 # a caller editing its copy doesn't touch the cache
    b = P.fetch_rosters(P.get_json)
    assert len(calls) == 2 and b["BOS"][0]["status"] == {"type": "active"}
    P.clear_roster_cache()                            # news came in: fresh read
    P.fetch_rosters(P.get_json)
    assert len(calls) == 4
    P.clear_roster_cache()
