"""This season's results fed back into the players model (engine/results_adj.py)."""
from datetime import date

from engine import personnel as P
from engine import results_adj as R
from engine.state import Game
from tests.test_personnel import LAST, ath


def box(gid, d, team, players):
    out = []
    for pid, name, mins in players:
        out.append({"game_id": gid, "game_date": d, "team": team, "espn_id": pid, "name": name, "min": mins,
                    "pts": 10, "fgm": 4, "fga": 9, "fg3m": 1, "fg3a": 3, "ftm": 1, "fta": 2, "orb": 1, "drb": 3,
                    "ast": 2, "stl": 1, "blk": 0, "tov": 1, "pf": 2, "pm": 0, "team_poss": 100.0, "game_min": 48.0})
    return out


def test_team_that_loses_by_more_than_expected_is_marked_down_and_shrunk():
    rows, finals = [], []
    for i, d in enumerate(["2026-10-21", "2026-10-23", "2026-10-25"]):
        gid = f"g{i}"
        rows += box(gid, d, "BOS", [("1", "Star Guard", 34), ("2", "Role Wing Jr.", 30), ("6", "Bench", 0)])
        rows += box(gid, d, "NYK", [("3", "Role Wing", 30), ("4", "Tiny Sample", 10), ("5", "Nobody", 0)])
        finals.append(Game(gid, date.fromisoformat(d), "NYK", "BOS", 130, 90, 4, True, None))  # BOS loses by 40
    out = R.team_results(rows, finals, LAST)
    assert out["BOS"]["games"] == 3 and out["BOS"]["miss"] < -20       # far worse than its players say
    # mirror images except for each side's opponent-shooting luck (taken out separately, so not exactly zero-sum)
    assert out["NYK"]["adj"] > 15 and abs(out["NYK"]["adj"] + out["BOS"]["adj"]) < 1.0
    # shrunk: 3 games of misses count as sum / (3 + 5), not the full average
    assert abs(out["BOS"]["adj"] - out["BOS"]["miss"] * 3 / 8) < 0.1


def test_results_move_the_team_rating_and_show_in_evidence():
    roster = [ath("Star Guard")] + [ath("Role Wing")] * 8
    base = P.rate_team("BOS", roster, LAST)
    tr = P.rate_team("BOS", roster, LAST)
    tr.results = {"games": 3, "miss": -12.0, "adj": -4.5}
    tr.rating += tr.results["adj"]
    assert abs(tr.rating - (base.rating - 4.5)) < 1e-9
    assert any("12.0 pts/game worse than its players predicted" in e for e in P.evidence(tr))
    assert abs(P.stress_rating(tr, True, False) - P.stress_rating(base, True, False) + 4.5) < 1e-9


def test_opponents_three_point_luck_is_taken_out():
    # same game twice; in the second, the opponent (NYK) hit 6 extra threes on the same attempts.
    def season(extra_nyk_threes):
        rows = box("g0", "2026-10-21", "BOS", [("1", "Star Guard", 34), ("2", "Role Wing Jr.", 30)])
        nyk = box("g0", "2026-10-21", "NYK", [("3", "Role Wing", 30), ("4", "Tiny Sample", 10)])
        nyk[0]["fg3m"] += extra_nyk_threes
        rows += nyk
        return R.team_results(rows, [Game("g0", date(2026, 10, 21), "NYK", "BOS", 110, 100, 4, True, None)], LAST)
    base, hot = season(0), season(6)
    # NYK's hot shooting (18 extra points) no longer counts against BOS's defense: BOS's miss is 18 better
    assert abs((hot["BOS"]["miss"] - base["BOS"]["miss"]) - 18.0) < 0.2
