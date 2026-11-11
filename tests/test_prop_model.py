"""Bottom-up props model (2026-11-11): the projection arithmetic."""
from engine.prop_model import P, project


def f(**kw):
    base = {"m5": 30.0, "m10": 30.0, "mseason": 30.0, "min_season": 900.0,
            "pts_r10": 0.5, "pts_rs": 0.5, "pts_rpos": 0.5, "reb_r10": 0.2, "reb_rs": 0.2, "reb_rpos": 0.2,
            "ast_r10": 0.1, "ast_rs": 0.1, "ast_rpos": 0.1}
    base.update(kw)
    return base


def test_plain_night_is_minutes_times_rate():
    pr = project(f(), P())
    assert pr["min"] == 30.0 and round(pr["pts"], 6) == 15.0 and round(pr["reb"], 6) == 6.0


def test_history_minutes_jump_and_usage_vacuum_and_team_total():
    p = P(split_trust=0.5, usage_k=1.0, team_total_exp=1.0, shrink_min=0.0)
    pr = project(f(split_gain=8.0, pts_absent_share=0.2, team_total=120.0, team_avg=110.0), p)
    assert pr["min"] == 34.0
    assert round(pr["pts"], 4) == round(34 * 0.5 / 0.8 * 120 / 110, 4)


def test_returning_star_loses_minutes_and_opponent_factor_shrinks_with_few_games():
    pr = project(f(returning=7), P())
    assert pr["min"] == 30 - 6.7
    p = P(opp_w=1.0, opp_shrink=10.0)
    pr = project(f(pts_opp=1.2, opp_games=10), p)
    assert round(pr["pts"], 6) == round(15 * (1 + 0.2 * 10 / 20), 6)


def test_live_projections_run_the_same_history_on_this_seasons_box_scores():
    from datetime import date
    from engine.personnel import Player, TeamRead
    from engine.prop_model import TUNED, live_projections
    from engine.state import Game
    rows = []
    for i in range(6):
        for team, opp in (("BOS", "NYK"), ("NYK", "BOS")):
            for j in range(5):
                rows.append({"game_id": f"x{i}", "game_date": f"2026-11-0{i + 1}", "team": team, "name": f"{team}{j}",
                             "min": 30 if j < 3 else 15, "pts": 15 if j < 3 else 6, "orb": 1, "drb": 4, "ast": 3})
    g = Game(id="g", game_date=date(2026, 11, 11), away="NYK", home="BOS", tip_utc="2026-11-12T00:00Z")
    reads = {}
    for t in ("BOS", "NYK"):
        tr = TeamRead(t)
        tr.players = [Player(f"{t}{j}", "out" if (t, j) == ("BOS", 0) else "active", 3, None) for j in range(5)]
        reads[t] = tr
    pr = live_projections(rows, [g], reads, {})
    assert ("g", "bos0") not in pr and ("g", "bos1") in pr and ("g", "nyk0") in pr
    # 0.50 pts/min over 180 minutes, pulled 50/230 of the way toward the league wing rate (57 pts / 120 min) -> 14.8
    assert pr[("g", "nyk0")]["min"] == 30.0 and pr[("g", "nyk0")]["pts"] == 14.8
    assert pr[("g", "bos1")]["fresh_out"] == ["BOS0"] and pr[("g", "bos1")]["pts"] > 15.0   # usage vacuum
    assert TUNED.usage_k == 0.5


def test_shot_zones_and_shooting_luck():
    from engine.prop_model import History, zone
    assert zone(25, 1, False) == "rim" and zone(25, 20, False) == "mid" and zone(3, 4, True) == "corner3"
    H = History({})
    for i in range(6):
        # the league shoots 50% at the rim; HOT makes every one (1 point per minute above expected over 5 min a game... )
        H.add_shots("A", "B", [("A", "HOT", "rim", 2), ("A", "HOT", "rim", 2), ("B", "COLD", "rim", 0), ("B", "COLD", "rim", 0)])
        H.add("A", "B", {"A": {"HOT": (10, 4, 0, 0)}, "B": {"COLD": (10, 0, 0, 0)}})
    hot, cold = H.shot_features("HOT", "B"), H.shot_features("COLD", "A")
    assert round(hot["luck_pm"], 6) == 0.2 and round(cold["luck_pm"], 6) == -0.2
