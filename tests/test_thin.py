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
