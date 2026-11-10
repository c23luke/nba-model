"""The props desk: tracking only. Teammates who gain minutes when a rotation player is freshly ruled out."""
from datetime import date, datetime, timedelta, timezone

from engine import props_desk as PD
from engine.personnel import Player, TeamRead
from engine.state import Game

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
G = Game(id="g1", game_date=date(2026, 11, 10), away="OKC", home="POR", tip_utc="2026-11-11T03:00Z")


def rows(team, name, mins, pts, n=10):
    return [{"team": team, "game_id": f"x{i}", "game_date": f"2026-11-{i + 1:02d}", "name": name, "min": mins, "pts": pts}
            for i in range(n)]


def setup():
    box = rows("POR", "Bench Guard", 12, 6) + rows("POR", "Starter", 32, 20)
    rot = {"POR": {"starter": {"name": "Starter", "mpg": 32.0, "last": True}}}
    tr = TeamRead("POR")
    tr.players = [Player("Starter", "out", 5, None), Player("Bench Guard", "active", 3, None, minutes=26.0)]
    return box, rot, {"POR": tr, "OKC": TeamRead("OKC")}


def test_a_bench_player_who_gains_minutes_is_projected_from_his_own_scoring():
    box, rot, reads = setup()
    c = PD.candidates(G, reads, rot, PD.scoring(box))
    assert c == [{"game_id": "g1", "team": "POR", "player": "Bench Guard", "because": ["Starter"], "mpg": 12.0,
                  "proj_min": 26.0, "proj_pts": 13.0, "dtd": False}]


def test_paper_over_when_the_line_is_3_below_our_projection_then_clv_and_grade():
    box, rot, reads = setup()
    props = {"bench guard": {"line": 8.5, "over": -110, "books": 6}}
    st = PD.step({}, NOW, [G], reads, rot, box, lambda g: props, {})
    b = st["bets"][0]
    assert (b["player"], b["line"], b["over"], b["proj_pts"]) == ("Bench Guard", 8.5, -110, 13.0)
    # 30 minutes later the line has moved to 10.5: CLV +2. No new bet for the same player.
    props = {"bench guard": {"line": 10.5, "over": -115, "books": 6}}
    st = PD.step(st, NOW + timedelta(minutes=31), [G], reads, rot, box, lambda g: props, {})
    assert len(st["bets"]) == 1 and st["bets"][0]["clv"] == 2.0
    # graded from the box score once the game is final
    box2 = box + [{"team": "POR", "game_id": "g1", "game_date": "2026-11-10", "name": "Bench Guard", "min": 27, "pts": 11}]
    st = PD.step(st, NOW + timedelta(hours=8), [], reads, rot, box2, lambda g: None, {"g1": {"final": True}})
    assert st["bets"][0]["result"] == "W"
    s = PD.summary(st)
    assert (s["bets"], s["w"], s["l"], s["avg_clv"]) == (1, 1, 0, 2.0)


def test_no_bet_when_the_line_already_moved_or_the_news_is_old():
    box, rot, reads = setup()
    assert PD.step({}, NOW, [G], reads, rot, box, lambda g: {"bench guard": {"line": 11.5, "over": -110, "books": 4}}, {})["bets"] == []
    rot["POR"]["starter"]["last"] = False             # he's been out a while: nothing new
    assert PD.candidates(G, reads, rot, PD.scoring(box)) == []


def test_props_are_read_at_most_every_30_minutes_per_game():
    box, rot, reads = setup()
    calls = []
    f = lambda g: calls.append(g.id) or {}
    st = PD.step({}, NOW, [G], reads, rot, box, f, {})
    PD.step(st, NOW + timedelta(minutes=10), [G], reads, rot, box, f, {})
    assert calls == ["g1"]


def test_parse_props_takes_the_median_line_across_books():
    js = {"bookmakers": [
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -115},
            {"name": "Under", "description": "Bench Guard", "point": 8.5, "price": -105}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 9.5, "price": 100}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -110}]}]}]}
    assert PD.parse_props(js) == {"bench guard": {"line": 8.5, "over": -110, "books": 3}}
