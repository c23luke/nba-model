"""X5-X7 situations (tracking only, 2026-11-11)."""
from datetime import date

from engine.situations import picks, team_luck
from engine.state import Game, TeamState


def st(last):
    s = TeamState("X")
    s.last_game = last
    return s


G = Game(id="g", game_date=date(2026, 11, 12), away="CHI", home="BOS", tip_utc="2026-11-13T00:00Z")


def test_blowout_winner_and_overtime_fade():
    big = Game(id="p1", game_date=date(2026, 11, 10), away="NYK", home="BOS", home_score=130, away_score=100, periods=4, final=True)
    ot = Game(id="p2", game_date=date(2026, 11, 10), away="CHI", home="MIA", home_score=120, away_score=118, periods=5, final=True)
    ps = picks(G, st(big), st(ot), -4.5, 225.5, {})
    got = sorted((p.system, p.side, p.line) for p in ps)
    assert got == [(305, "BOS", -4.5), (306, "BOS", -4.5)]


def test_both_teams_cold_shooting_over():
    luck = {"BOS": [-3, -2.5, -4], "CHI": [-2, -3, -2.2]}
    ps = picks(G, st(None), st(None), None, 221.5, luck)
    assert [(p.system, p.side, p.line) for p in ps] == [(307, "OVER", 221.5)]
    luck["CHI"] = [-1, -1, -1]
    assert picks(G, st(None), st(None), None, 221.5, luck) == []
