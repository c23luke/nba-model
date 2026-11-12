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
    # 2026-11-11: both outs played the last game, so X3 (2+ fresh) fires too; no positions given, so no X4
    assert [(x.system, x.side, x.line) for x in p] == [(302, "WAS", 3.5), (303, "WAS", 3.5)]
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


def test_testing_side_lists_every_idea_and_the_bar_to_real_money():
    from engine.run import TESTING_BAR, testing_side
    board = {"shadow_systems": {302: {"if_first": {"w": 30, "l": 22, "p": 0}, "avg_clv": 0.4, "open": 1}},
             "injury_desk": {"paper": {"bets": 3, "w": 2, "l": 1, "avg_clv": 1.5}},
             "props_desk": {"by_kind": {"fake": {"name": "Fake bump", "bets": 2, "w": 1, "l": 1, "avg_clv": 0.5, "open": 0}}},
             "placed": {"bets": [{"game_id": "g", "side": "WAS", "result": "W", "rules": {"counted": True}, "market": {"beat_close": 2.0}}]}}
    t = testing_side(board, [{"system": 302, "game_id": "g", "side": "WAS"}])
    # 2026-11-10: props split into six kinds (returning star, fill-ins, hidden bump, history jump, fake bump, model jump)
    # 2026-11-11: props models A (opening lines), B (news desk), C (price-shopping, 2 entries), then the props model and its two spots, before the bigger-bet candidates
    # 2026-11-11: X3 and X4 (tighter X2 versions) after X2, then X5-X9 (situations), then the two STACK trackers
    assert [x["name"][:9] for x in t] == ["X2: fade ", "X3: fade ", "X4: fade ", "X5: back ", "X6: fade ", "X7: both ", "X8: follo", "X9: home ", "STACK 5+:", "STACK 4: ", "Injury de", "Props: re", "Props: fi", "Props: hi", "Props: ju",
                                          "Props: Fa", "Props: ju", "Props A: ", "Props B: ", "Props C: ", "Props C: ",
                                          "Props mod", "Props mod", "Props spo", "Props spo", "Our bet +"]
    assert t[15]["bets"] == 2 and t[15]["avg_clv"] == 0.5                  # the fake-bump props entry (moved by X3/X4)
    assert (t[0]["w"], t[0]["l"], t[0]["bets"], t[0]["ready"]) == (30, 22, 52, True)
    assert t[10]["ready"] is False and t[25]["w"] == 1 and t[25]["avg_clv"] == 2.0 and TESTING_BAR == 50


def test_x3_needs_two_fresh_absences_and_x4_needs_different_positions():
    from datetime import date
    from engine.cluster import cluster_pick
    from engine.personnel import Player, TeamRead
    from engine.state import Game
    g = Game(id="g", game_date=date(2026, 11, 11), away="MIA", home="UTA", tip_utc="2026-11-12T02:00Z")
    rot = {"UTA": {"keyonte george": {"name": "Keyonte George", "mpg": 32.0, "last": True},
                   "lauri markkanen": {"name": "Lauri Markkanen", "mpg": 25.0, "last": False}}, "MIA": {}}
    tr = TeamRead("UTA")
    tr.players = [Player("Keyonte George", "out", 3, None), Player("Lauri Markkanen", "out", 8, None)]
    reads = {"UTA": tr, "MIA": TeamRead("MIA")}
    pos = {"Keyonte George": "PG", "Lauri Markkanen": "PF"}
    tags = sorted(p.system for p in cluster_pick(g, 8.5, rot, reads, pos))
    assert tags == [302, 304]                       # only one fresh: no X3; guard + big: X4
    rot["UTA"]["lauri markkanen"]["last"] = True
    pos["Lauri Markkanen"] = "SG"
    assert sorted(p.system for p in cluster_pick(g, 8.5, rot, reads, pos)) == [302, 303]   # two fresh, two guards
