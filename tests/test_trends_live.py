from datetime import date, datetime, timedelta, timezone

from engine import trends_live as TL
from engine.state import Game


class FakeStore:
    def __init__(self):
        self.state = {}

    def load_state(self, keys):
        return {k: self.state[k] for k in keys if k in self.state}

    def save_state(self, values):
        self.state.update(values)


START = date(2026, 10, 21)


def _season():
    """BOS plays 9 games; scores 88 in the last one (a Trends Center 'scored 90 or less' spot)."""
    finals, stored = [], {}
    for i in range(9):
        d = date(2026, 10, 22) + timedelta(days=2 * i)
        g = Game(id=f"f{i}", game_date=d, away="NYK", home="BOS", away_score=100,
                 home_score=110 if i < 8 else 88, periods=4, final=True)
        finals.append(g)
        stored[g.id] = {"home_spread": -5.0, "total": 220.0, "final": True}
    return finals, stored


def test_fires_once_and_grades_at_the_line_it_fired_on():
    finals, stored = _season()
    up = Game(id="u1", game_date=date(2026, 11, 10), away="MIA", home="BOS")
    store = FakeStore()
    now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
    out = TL.run(store, now, finals, stored, [up], {"u1": (-4.0, 221.0, -4.0)}, START, {})
    t = next(x for x in out["trends"] if x["name"].startswith("Team that scored 90 or less"))
    assert t["open"] == [{"game": "MIA @ BOS", "side": "BOS", "line": -4.0, "date": "2026-11-10"}]
    # the line moves later: the stored entry keeps the line it first fired on
    TL.run(store, now, finals, stored, [up], {"u1": (-6.0, 221.0, -6.0)}, START, {})
    key = "Team that scored 90 or less in its last game (their version: Celtics only, 14-0)|u1|BOS"
    assert store.state["trends_fired"][key]["line"] == -4.0
    # BOS wins by 4 at -4: a push; by 5: a win
    done = Game(id="u1", game_date=up.game_date, away="MIA", home="BOS", away_score=100, home_score=105,
                periods=4, final=True)
    out = TL.run(store, now, finals, stored, [], {}, START, {"u1": done})
    t = next(x for x in out["trends"] if x["name"].startswith("Team that scored 90 or less"))
    assert t["live"]["w"] == 1 and t["open"] == [] and t["recent"][0]["result"] == "W"


def test_line_move_trend_uses_the_current_line():
    finals, stored = _season()
    up = Game(id="u2", game_date=date(2026, 11, 10), away="MIA", home="BOS")
    fired = TL.evaluate(finals, stored, [up], {"u2": (-3.0, 220.0, -6.0)}, START)
    mv = [f for f in fired if f[0] in TL.AT_CURRENT]
    assert [(f[2], f[3]) for f in mv] == [("BOS", -6.0)]          # moved 3 toward BOS; bet at -6
    assert not [f for f in TL.evaluate(finals, stored, [up], {"u2": (-3.0, 220.0, -4.5)}, START)
                if f[0] in TL.AT_CURRENT]                          # 1.5 is not enough


def test_grade_totals_and_pushes():
    g = Game(id="x", game_date=START, away="A", home="B", away_score=100, home_score=110, final=True)
    assert TL.grade({"kind": "total", "side": "UNDER", "line": 215.5}, g) == "W"
    assert TL.grade({"kind": "total", "side": "OVER", "line": 210}, g) == "P"
    assert TL.grade({"kind": "spread", "side": "A", "line": 9.5}, g) == "L"
    assert TL.grade({"kind": "spread", "side": "A", "line": 10}, g) == "P"


def test_every_trend_has_our_record():
    for name, *_ in TL.trends():
        assert name in TL.OURS_6, name


def test_stack_needs_two_trends_on_one_side_and_none_on_the_other(monkeypatch):
    finals, stored = _season()
    up = Game(id="u3", game_date=date(2026, 11, 10), away="MIA", home="BOS")
    one = [("A", "s", "", "spread", None, lambda r: r["home"])]
    two = one + [("B", "s", "", "spread", None, lambda r: r["home"])]
    split = two + [("C", "s", "", "spread", None, lambda r: not r["home"])]
    for rules, want in ((one, 0), (two, 1), (split, 0)):
        monkeypatch.setattr(TL, "trends", lambda rules=rules: rules)
        out = TL.run(FakeStore(), datetime(2026, 11, 10, tzinfo=timezone.utc), finals, stored, [up],
                     {"u3": (-4.0, 220.0, -4.0)}, START, {})
        st = next(x for x in out["trends"] if x["name"] == TL.STACK)
        assert len(st["open"]) == want and all(o["side"] == "BOS" for o in st["open"])
