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


def test_stack_counts_each_fact_once_and_a_min_like_pile_of_one_fact_is_not_a_bet():
    """Nov 14 MIN: S1 + T12 + CHI off overtime + CHI on a back-to-back + a 39-point win + the line moving 2 = 7 old
    flags, but 2 facts known before the line moves: tired opponent, blowout win. Not a STACK bet any more."""
    from engine.situations import stack_facts, stack_picks
    from engine.systems import Pick
    big = Game(id="p1", game_date=date(2026, 11, 10), away="NYK", home="BOS", home_score=139, away_score=100, periods=4, final=True)
    yday = Game(id="y", game_date=date(2026, 11, 11), away="CHI", home="Y", home_score=100, away_score=90, periods=5, final=True)
    picks = [Pick(1, "g", "spread", "BOS", -4.0), Pick(112, "g", "spread", "BOS", -4.0),
             Pick(306, "g", "spread", "BOS", -4.0, ["CHI's last game went to overtime"]),
             Pick(305, "g", "spread", "BOS", -4.0, ["BOS won its last game by 39"])]
    view = {"gap": -1.0, "thin_share": {}}
    f = stack_facts(G, "BOS", picks, view, st(big), st(yday), -4.0, -2.0, {})
    assert list(f) == ["tired opponent", "blowout win"]                      # the line move is never a fact
    assert "CHI is on a back-to-back, BOS isn't" in f["tired opponent"] and "S1" in f["tired opponent"] \
        and "T12" in f["tired opponent"] and "overtime" in f["tired opponent"]
    assert stack_picks(G, picks, view, st(big), st(yday), -4.0, -2.0, {}) == []
    # add a system that isn't about rest and an opponent leaning on unknown players: 4 separate facts -> STACK
    picks.append(Pick(2, "g", "spread", "BOS", -4.0))                     # S2, road favorite on a losing streak
    view = {"gap": -1.0, "thin_share": {"home": 0.0, "away": 0.2}}
    ps = stack_picks(G, picks, view, st(big), st(yday), -4.0, -2.0, {})
    assert [(p.system, p.side, p.meta["n_flags"], p.meta["two_units"]) for p in ps] == [(131, "BOS", 4, True)]
    assert not any(x.startswith("line move") for x in ps[0].meta["flags"])
    assert all(": " in x for x in ps[0].meta["flags"]) and ps[0].meta["flags"][0] == "systems: card system: S2 (Road favorite on 4+ game losing streak)"


def test_the_players_model_counts_for_stack_only_if_it_holds_whoever_plays():
    from engine.situations import stack_facts
    from engine.systems import Pick
    picks = [Pick(5, "g", "spread", "BOS", -4.0)]
    solid = {"gap": 4.0, "scenarios": [{"gap": 4.0}, {"gap": 3.4}], "thin_share": {}}
    shaky = {"gap": 4.0, "scenarios": [{"gap": 4.0}, {"gap": 1.5}], "thin_share": {}}     # 3+ only if someone sits
    assert "players model" in stack_facts(G, "BOS", picks, solid, None, None, -4.0, -4.0, {})
    assert "players model likes BOS by 3.4 to 4.0" in stack_facts(G, "BOS", picks, solid, None, None, -4.0, -4.0, {})["players model"]
    assert "players model" not in stack_facts(G, "BOS", picks, shaky, None, None, -4.0, -4.0, {})


def test_stack_is_a_card_bet_without_needing_a_players_read():
    from engine.pricing import eligible, history, PRICE_WIN as WIN
    from engine.systems import label, group, STACK
    p = {"system": STACK, "bet": "spread", "side": "BOS", "game_id": "g"}
    assert eligible(p, []) == (True, None)                    # no players-model read needed: the facts are the case
    assert history(p, [])["w"] == 136 and label(STACK) == "STACK" and group(STACK) == "FAV"   # 4+ facts at the open
    assert abs(WIN[STACK] - (136 + 50) / (211 + 100)) < 0.001


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


def test_shot_quality_pairs_fire_only_with_both_flags_and_say_their_numbers():
    from engine.situations import sq_pair_picks
    from engine.systems import Pick, label
    bos = {"games": 10, "xnet10": 5.0, "luck_net10": -8.0, "three_luck5": 0.0, "rrim": 0.30, "drim": 0.25}
    nyk = {"games": 10, "xnet10": -3.0, "luck_net10": 2.0, "three_luck5": 5.0, "rrim": 0.25, "drim": 0.30}
    x4 = Pick(304, "g", "spread", "BOS", -4.0, ["CHI is missing 2 rotation players at different positions"])
    x3 = Pick(303, "g", "spread", "BOS", -4.0, ["CHI is missing 2 fresh rotation players"])
    view = {"gap": 3.5, "thin_share": {"home": 0.0, "away": 0.2}}
    ps = sq_pair_picks(G, [x3, x4], view, -4.0, -3.0, {"BOS": bos, "CHI": nyk})
    got = sorted((label(p.system), p.side) for p in ps)
    # rim 30% / 30% + players 3.5; better by 8.0 + X3; unlucky -8.0 + X4; better + thin; CHI 3s +5.0 + moved 1
    assert got == [("RIM+PM", "BOS"), ("SQ+THIN", "BOS"), ("SQ+X3", "BOS"), ("UNLUCKY+X4", "BOS"), ("X10", "BOS")]
    assert next(p for p in ps if p.system == 310)      # 3HOT+MOVE still fires, on paper (310) since Nov 14
    assert all(len(p.meta["flags"]) == 2 for p in ps)
    rim = next(p for p in ps if label(p.system) == "RIM+PM")
    assert "30% of its shots at the rim" in rim.meta["flags"][0] and "by 3.5" in rim.meta["flags"][1]
    assert sq_pair_picks(G, [], {"gap": 0.0}, -4.0, -4.0, {"BOS": bos, "CHI": nyk}) == []   # no second flag anywhere


def test_a_system_plus_players_model_bet_is_a_combo_and_t13_alone_is_not():
    from engine.pricing import _is_combo
    assert _is_combo({"system": 5, "bet": "spread"}) and not _is_combo({"system": 113, "bet": "spread"})
    assert not _is_combo({"system": 130, "bet": "spread"}) and not _is_combo({"system": 136, "bet": "spread"})


def test_units_follow_the_sorted_estimate_from_nov_14():
    from engine.pricing import COMBO_TO_WIN, THIN_SYSTEM_TO_WIN, THIN_FADE_TO_WIN, MONEYBALL_TO_WIN, STACK_2U_TO_WIN
    assert (COMBO_TO_WIN, THIN_SYSTEM_TO_WIN) == (20, 20)                          # 58.0% sorted: 1 unit
    assert (THIN_FADE_TO_WIN, MONEYBALL_TO_WIN, STACK_2U_TO_WIN) == (40, 40, 40)   # 60%+ sorted, planned tests: 2 units
