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
    assert [(p.system, p.side, p.meta["n_flags"]) for p in ps] == [(131, "BOS", 7)]     # STACK: a card bet
    view["gap"] = 0.0
    picks = picks[:1]
    ps = stack_picks(G, picks, {"gap": 0.0, "thin_share": {"home": 0.0, "away": 0.2}}, st(big), st(yday), -4.0, -2.5, {})
    assert ps == []                     # 4 flags (1 system, moved 1.5, thin, back-to-back): no longer a pick


def test_stack_is_a_card_bet_without_needing_a_players_read():
    from engine.pricing import eligible, history, PRICE_WIN as WIN, TO_WIN
    from engine.systems import label, group, STACK
    p = {"system": STACK, "bet": "spread", "side": "BOS", "game_id": "g"}
    assert eligible(p, []) == (True, None)                    # no players-model read needed: the flags are the case
    assert history(p, [])["w"] == 213 and label(STACK) == "STACK" and group(STACK) == "FAV"
    assert abs(WIN[STACK] - 0.569) < 0.001 and TO_WIN == 20   # (213 + 50) / (362 + 100), one unit


def test_stack_is_two_units_only_with_the_players_model_and_a_system():
    from engine.situations import stack_picks
    from engine.systems import Pick
    big = Game(id="p1", game_date=date(2026, 11, 10), away="NYK", home="BOS", home_score=130, away_score=100, periods=4, final=True)
    yday = Game(id="y", game_date=date(2026, 11, 11), away="CHI", home="Y", home_score=100, away_score=90, periods=4, final=True)
    picks = [Pick(5, "g", "spread", "BOS", -4.0), Pick(305, "g", "spread", "BOS", -4.0, ["BOS won its last game by 30"])]
    thin = {"home": 0.0, "away": 0.2}
    both = stack_picks(G, picks, {"gap": 4.0, "thin_share": thin}, st(big), st(yday), -4.0, -2.5, {})
    assert both[0].meta["n_flags"] == 6 and both[0].meta["two_units"] is True      # players model + 1 system
    no_pm = stack_picks(G, picks, {"gap": 0.0, "thin_share": thin}, st(big), st(yday), -4.0, -2.5, {})
    assert no_pm[0].meta["n_flags"] == 5 and no_pm[0].meta["two_units"] is False   # 5 flags, no players model: 1 unit


def test_sys_x4_needs_a_card_system_and_x4_on_the_same_side_and_thin_system_bets_are_30():
    from engine.situations import system_x4_picks
    from engine.systems import Pick
    from engine.pricing import eligible, thin_system, thin_fade
    x4 = Pick(304, "g", "spread", "BOS", -4.0, ["NYK is missing 2 rotation players at different positions"])
    assert system_x4_picks(G, [x4]) == []                                        # no system: nothing
    assert system_x4_picks(G, [x4, Pick(5, "g", "spread", "NYK", 4.0)]) == []   # system on the other side
    ps = system_x4_picks(G, [x4, Pick(5, "g", "spread", "BOS", -4.0)])
    assert [(p.system, p.side) for p in ps] == [(132, "BOS")] and "NYK is missing" in ps[0].evidence[1]
    assert eligible({"system": 132, "bet": "spread", "side": "BOS", "game_id": "g"}, []) == (True, None)
    slate = [{"game_id": "g", "home": "BOS", "away": "NYK", "personnel": {"thin_share": {"home": 0.0, "away": 0.2}}}]
    sysbet = {"system": 5, "bet": "spread", "side": "BOS", "game_id": "g"}
    assert thin_system(sysbet, slate)["team"] == "NYK" and thin_fade(sysbet, slate) is None
    assert thin_system({**sysbet, "system": 130}, slate) is None                  # MONEYBALL keeps its own size


def test_pair_bets_fire_only_when_both_edges_are_on_the_same_side():
    from engine.situations import pair_picks
    from engine.systems import Pick, label
    yday = Game(id="y", game_date=date(2026, 11, 11), away="NYK", home="Y", home_score=100, away_score=90, periods=4, final=True)
    old = Game(id="o", game_date=date(2026, 11, 8), away="BOS", home="Z", home_score=100, away_score=90, periods=4, final=True)
    x4 = Pick(304, "g", "spread", "BOS", -4.0, ["NYK is missing 2 rotation players at different positions"])
    x2 = Pick(302, "g", "spread", "BOS", -4.0, ["NYK is missing 2 rotation players"])
    thin = {"gap": 0.0, "thin_share": {"home": 0.0, "away": 0.2}}
    ps = pair_picks(G, [x4, x2], thin, st(old), st(yday), -4.0, -1.5)       # NYK (away) on a b2b, line moved 2.5 to BOS
    assert sorted((p.system, label(p.system), p.side) for p in ps) == [(133, "X4+B2B", "BOS"), (134, "X2+B2B", "BOS"),
                                                                      (135, "MOVE+THIN", "BOS")]
    assert all(len(p.meta["flags"]) == 2 for p in ps)
    assert pair_picks(G, [x4, x2], thin, st(old), st(old), -4.0, -3.0) == []  # no back-to-back, move only 1
