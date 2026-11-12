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


def test_follow_a_2_point_line_move_and_home_rest_edge():
    from engine.situations import picks as P_
    ps = P_(G, st(None), st(None), -6.0, None, {}, -3.5)          # moved 2.5 toward BOS (home)
    assert [(p.system, p.side, p.line) for p in ps] == [(308, "BOS", -6.0)]
    assert P_(G, st(None), st(None), -5.0, None, {}, -3.5) == []    # only 1.5
    old = Game(id="o", game_date=date(2026, 11, 8), away="X", home="BOS", home_score=100, away_score=90, periods=4, final=True)
    yday = Game(id="y", game_date=date(2026, 11, 11), away="CHI", home="Y", home_score=100, away_score=90, periods=4, final=True)
    ps = P_(G, st(old), st(yday), -4.0, None, {}, None)
    assert [(p.system, p.side) for p in ps] == [(309, "BOS")]       # 4 days vs 1


def test_stack_counts_every_flag_with_its_evidence_and_fires_at_5_plus():
    from engine.situations import stack_flags, stack_picks
    from engine.systems import Pick
    big = Game(id="p1", game_date=date(2026, 11, 10), away="NYK", home="BOS", home_score=130, away_score=100, periods=4, final=True)
    yday = Game(id="y", game_date=date(2026, 11, 11), away="CHI", home="Y", home_score=100, away_score=90, periods=4, final=True)
    picks = [Pick(5, "g", "spread", "BOS", -4.0), Pick(7, "g", "spread", "BOS", -4.0),
             Pick(305, "g", "spread", "BOS", -4.0, ["BOS won its last game by 30"])]
    view = {"gap": 4.0, "thin_share": {"home": 0.0, "away": 0.2}}
    fl = stack_flags(G, "BOS", picks, view, st(big), st(yday), -4.0, -2.5, {})
    # players model, 1 system, 2+ systems, X5, moved 1.5, CHI thin, CHI on a back-to-back = 7
    assert len(fl) == 7 and fl[0] == "players model likes BOS by 4.0" and "BOS won its last game by 30" in fl
    ps = stack_picks(G, picks, view, st(big), st(yday), -4.0, -2.5, {})
    assert [(p.system, p.side, p.meta["n_flags"]) for p in ps] == [(310, "BOS", 7)]
    view["gap"] = 0.0
    picks = picks[:1]
    ps = stack_picks(G, picks, {"gap": 0.0, "thin_share": {"home": 0.0, "away": 0.2}}, st(big), st(yday), -4.0, -2.5, {})
    assert ps == []                     # 4 flags (1 system, moved 1.5, thin, back-to-back): no longer a pick
