"""X2: fade the team missing 2+ rotation players (tracking only)."""
from datetime import date

from engine import cluster as C
from engine.personnel import Player, TeamRead
from engine.state import Game


def box(team, dates, players):
    """players: name -> minutes per game (same for every date), or a list per date."""
    rows = []
    for i, d in enumerate(dates):
        for n, m in players.items():
            mm = m[i] if isinstance(m, list) else m
            rows.append({"team": team, "game_id": f"{team}{i}", "game_date": d, "name": n, "min": mm})
    return rows


def read(team, statuses):
    tr = TeamRead(team)
    for n, s in statuses.items():
        tr.players.append(Player(n, s, 5, None))
    return tr


DATES = [f"2026-11-{d:02d}" for d in range(1, 11)]


def test_rotation_needs_20_mpg_over_the_last_10_and_5_games():
    rows = box("ORL", DATES, {"Star A": 34, "Star B": 30, "Bench": 12, "Hurt Long": [30] * 4 + [0] * 6})
    rot = C.rotations(rows)["ORL"]
    assert set(rot) == {"star a", "star b"} and rot["star a"]["last"] and rot["star a"]["mpg"] == 34.0


def test_fires_on_two_fresh_outs_more_than_the_opponent():
    rows = box("ORL", DATES, {"Star A": 34, "Star B": 30, "Wing C": 25}) + box("WAS", DATES, {"Guard D": 33})
    rot = C.rotations(rows)
    g = Game(id="g1", game_date=date(2026, 11, 12), away="WAS", home="ORL")
    reads = {"ORL": read("ORL", {"Star A": "out", "Star B": "out", "Wing C": "active"}), "WAS": read("WAS", {"Guard D": "active"})}
    p = C.cluster_pick(g, -3.5, rot, reads)
    assert [(x.system, x.side, x.line) for x in p] == [(302, "WAS", 3.5)]
    assert p[0].meta["n_out"] == 2 and "missing 2 rotation players" in p[0].evidence[0]
    # day-to-day doesn't count; one out doesn't count; the opponent missing as many doesn't count
    reads["ORL"] = read("ORL", {"Star A": "out", "Star B": "day-to-day"})
    assert C.cluster_pick(g, -3.5, rot, reads) == []
    reads["ORL"] = read("ORL", {"Star A": "out", "Star B": "out"})
    rot["WAS"]["x"] = {"name": "X", "mpg": 22, "last": True}
    reads["WAS"] = read("WAS", {"Guard D": "out", "X": "out"})
    assert C.cluster_pick(g, -3.5, rot, reads) == []


def test_long_absences_alone_dont_fire():
    rows = box("ORL", DATES, {"A": [30] * 9 + [0], "B": [30] * 9 + [0], "C": 30})
    rot = C.rotations(rows)
    assert not rot["ORL"]["a"]["last"] and not rot["ORL"]["b"]["last"]
    g = Game(id="g1", game_date=date(2026, 11, 12), away="WAS", home="ORL")
    reads = {"ORL": read("ORL", {"A": "out", "B": "out"}), "WAS": read("WAS", {})}
    assert C.cluster_pick(g, -3.5, rot, reads) == []
