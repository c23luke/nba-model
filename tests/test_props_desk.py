"""The props desk: tracking only. When a rotation player is freshly ruled out, who really gets his minutes?
2026-11-10 spec change: three kinds (history jump / model jump / fake bump), points + rebounds + assists, overs and
unders. The earlier points-only tests were rewritten for it."""
from datetime import date, datetime, timedelta, timezone

from engine import props_desk as PD
from engine.personnel import Player, TeamRead
from engine.props_splits import splits
from engine.state import Game

NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
G = Game(id="g1", game_date=date(2026, 11, 10), away="OKC", home="POR", tip_utc="2026-11-11T03:00Z")


def row(gid, name, mins, pts, reb=0, ast=0, team="POR"):
    return {"team": team, "game_id": gid, "game_date": f"2026-11-{int(gid[1:]) + 1:02d}", "name": name, "min": mins,
            "pts": pts, "orb": 0, "drb": reb, "ast": ast}


def box(bench_without=12, n_without=0):
    """10 games: Starter plays the first 10 - n_without; Bench Guard plays 12 min / 6 pts with him and
    `bench_without` minutes (at the same rate) without him."""
    rows = []
    for i in range(10):
        gid = f"x{i}"
        if i < 10 - n_without:
            rows += [row(gid, "Starter", 32, 20, 5, 4), row(gid, "Bench Guard", 12, 6, 2, 1)]
        else:
            rows += [row(gid, "Starter", 0, 0), row(gid, "Bench Guard", bench_without, bench_without // 2, 4, 3)]
    return rows


def reads(bench_minutes=26.0):
    tr = TeamRead("POR")
    tr.players = [Player("Starter", "out", 5, None), Player("Bench Guard", "active", 3, None, minutes=bench_minutes)]
    return {"POR": tr, "OKC": TeamRead("OKC")}


ROT = {"POR": {"starter": {"name": "Starter", "mpg": 32.0, "last": True}}}


def props(pts=8.5, reb=None, ast=None):
    out = {("bench guard", "pts"): {"line": pts, "over": -110, "under": -110, "books": 6}}
    if reb is not None:
        out[("bench guard", "reb")] = {"line": reb, "over": -110, "under": -110, "books": 6}
    if ast is not None:
        out[("bench guard", "ast")] = {"line": ast, "over": -110, "under": -110, "books": 6}
    return out


def test_splits_show_what_a_teammate_did_with_and_without_a_rotation_player():
    s = splits(box(bench_without=28, n_without=3))
    x = s["POR"]["starter"]["bench guard"]
    assert (x["n_with"], x["n_wo"], x["min_with"], x["min_wo"], x["pts_wo"], x["reb_wo"]) == (7, 3, 12.0, 28.0, 14.0, 4.0)


def test_no_history_yet_uses_the_players_model_minutes():
    b = box()
    c = PD.candidates(G, reads(), ROT, PD.scoring(b), splits(b))
    assert len(c) == 1 and c[0]["kind"] == "jump_model" and c[0]["proj"]["pts"] == 13.0 and c[0]["proj_min"] == 26.0


def test_a_real_minutes_jump_in_past_games_projects_from_those_games():
    b = box(bench_without=28, n_without=2)
    c = PD.candidates(G, reads(), ROT, PD.scoring(b), splits(b))
    assert c[0]["kind"] == "jump_hist" and c[0]["proj"] == {"pts": 14.0, "reb": 4.0, "ast": 3.0} and c[0]["n_wo"] == 2


def test_fake_bump_when_the_model_expects_minutes_but_history_says_no():
    b = box(bench_without=13, n_without=3)              # he played 13 without the starter, 12 with: no bump
    c = PD.candidates(G, reads(26.0), ROT, PD.scoring(b), splits(b))
    assert c[0]["kind"] == "fake" and c[0]["proj"]["pts"] == 6.0
    st = PD.step({}, NOW, [G], reads(26.0), ROT, b, lambda g: props(pts=10.5), {})
    bet = st["bets"][0]
    assert (bet["side"], bet["stat"], bet["line"], bet["price"], bet["edge"]) == ("under", "pts", 10.5, -110, 4.5)
    # two games of history isn't enough to call a bump fake
    b2 = box(bench_without=13, n_without=2)
    assert PD.candidates(G, reads(26.0), ROT, PD.scoring(b2), splits(b2)) == []


def test_paper_over_then_clv_then_grade_and_a_void_if_he_sits():
    b = box()
    st = PD.step({}, NOW, [G], reads(), ROT, b, lambda g: props(pts=8.5, reb=5.5), {})
    got = {(x["stat"], x["side"]) for x in st["bets"]}
    assert got == {("pts", "over")}                     # 26 min x 0.1 reb/min = 2.6 projected: no rebound bet
    # 30 minutes later: not re-read (every 90 minutes)...
    calls = []
    PD.step(st, NOW + timedelta(minutes=30), [G], reads(), ROT, b, lambda g: calls.append(1) or props(10.5), {})
    assert calls == []
    # ...but read once in the last 30 minutes before tip: the closing line, CLV +2
    st = PD.step(st, datetime(2026, 11, 11, 2, 40, tzinfo=timezone.utc), [G], reads(), ROT, b, lambda g: props(10.5), {})
    assert st["bets"][0]["clv"] == 2.0
    b2 = b + [row("g1", "Bench Guard", 27, 11)]
    st2 = PD.step(st, NOW + timedelta(hours=8), [], reads(), ROT, b2, lambda g: None, {"g1": {"final": True}})
    assert st2["bets"][0]["result"] == "W"
    s = PD.summary(st2)
    assert (s["bets"], s["w"], s["avg_clv"], s["by_kind"]["jump_model"]["w"], s["units"]) == (1, 1, 2.0, 1, 0.91)
    b3 = b + [row("g1", "Bench Guard", 0, 0)]
    assert PD.step(st, NOW + timedelta(hours=8), [], reads(), ROT, b3, lambda g: None, {"g1": {"final": True}})["bets"][0]["result"] == "VOID"


def test_no_bet_when_the_line_already_moved_or_the_news_is_old():
    b = box()
    assert PD.step({}, NOW, [G], reads(), ROT, b, lambda g: props(pts=11.5), {})["bets"] == []
    rot = {"POR": {"starter": {"name": "Starter", "mpg": 32.0, "last": False}}}      # out a while: nothing new
    assert PD.candidates(G, reads(), rot, PD.scoring(b), splits(b)) == []


def test_parse_props_takes_the_most_common_line_and_its_prices():
    js = {"bookmakers": [
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -115},
            {"name": "Under", "description": "Bench Guard", "point": 8.5, "price": -105}]},
            {"key": "player_assists", "outcomes": [
                {"name": "Over", "description": "Bench Guard", "point": 2.5, "price": 120},
                {"name": "Under", "description": "Bench Guard", "point": 2.5, "price": -150}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 9.5, "price": 100}]}]},
        {"markets": [{"key": "player_points", "outcomes": [
            {"name": "Over", "description": "Bench Guard", "point": 8.5, "price": -110},
            {"name": "Under", "description": "Bench Guard", "point": 8.5, "price": -110}]}]}]}
    p = PD.parse_props(js)
    assert p[("bench guard", "pts")] == {"line": 8.5, "over": -115, "under": -110, "books": 3}
    assert p[("bench guard", "ast")] == {"line": 2.5, "over": 120, "under": -150, "books": 1}
