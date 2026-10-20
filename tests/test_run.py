"""Full pass of the runner, offline: real 2025 results, fake lines + fake Kalshi book."""
from datetime import date, datetime, timedelta, timezone

from engine.run import run
from engine.state import Game
from engine.store import LocalStore
from tests.load import fixture_games

ALL = fixture_games()
START = date(2025, 10, 21)


def make_fetch_day(sim_today: date, finals_through: date):
    def fetch_day(d):
        out = []
        for g in ALL:
            if g.game_date != d:
                continue
            tip = f"{(d + timedelta(1)).isoformat()}T00:30Z"           # 7:30pm ET
            if d <= finals_through:
                out.append((Game(g.id, d, g.away, g.home, g.away_score, g.home_score, g.periods, True, tip), None))
            else:
                out.append((Game(g.id, d, g.away, g.home, tip_utc=tip), None))
        return out
    return fetch_day


def fake_lines():
    # LAL @ MIL, Nov 15 2025: MIL -6 / 224.5 (MIL won in OT the night before → System 1 on LAL +6)
    return {(date(2025, 11, 15), "LAL", "MIL"): {"home_spread": -6.0, "total": 224.5,
                                                "source": "test", "books": 8}}, {"remaining": "999000"}


def fake_kalshi(series, g):
    if series != "KXNBASPREAD":
        return []
    return [{"ticker": f"KXNBASPREAD-25NOV15LALMIL-MIL{k}", "floor_strike": k - 0.5,
             "yes_bid_dollars": "0.45", "yes_ask_dollars": "0.47"} for k in range(3, 10)]


def test_full_pass_fires_prices_and_grades(tmp_path):
    store = LocalStore(tmp_path)
    morning = datetime(2025, 11, 15, 15, 0, tzinfo=timezone.utc)      # 10am ET Nov 15
    board = run(now=morning, fetch_day=make_fetch_day(date(2025, 11, 15), date(2025, 11, 14)),
                fetch_lines=fake_lines, fetch_kalshi=fake_kalshi, store=store, season_start=START)

    bets = board["bets"]
    assert [(b["system"], b["side"], b["line"]) for b in bets] == [(1, "LAL", 6.0)]
    k = bets[0]["kalshi"]
    # LAL +6 → no 6.0 strike on Kalshi; take NO on "MIL wins by over 6.5" (= LAL +6.5, the better side of the tie)
    assert k["contract"].startswith("NO · MIL wins by over 6.5") and k["price"] == 0.55 and not k["exact"]
    assert any(s["away"] == "LAL" and s["home"] == "MIL" and s["picks"] for s in board["slate"])
    assert board["odds_api"]["remaining"] == "999000"

    # next morning: game is final (LAL won 119-95) → graded W
    nxt = datetime(2025, 11, 16, 15, 0, tzinfo=timezone.utc)
    board = run(now=nxt, fetch_day=make_fetch_day(date(2025, 11, 16), date(2025, 11, 15)),
                fetch_lines=lambda: ({}, {}), fetch_kalshi=fake_kalshi, store=store, season_start=START)
    h = [p for p in board["history"] if p["key"] == bets[0]["key"]]
    assert h and h[0]["result"] == "W" and "LAL 119 @ MIL 95" in h[0]["final_score"]
    assert board["systems"][1]["w"] == 1 and board["systems"][1]["l"] == 0


def test_bet_drops_when_line_moves_out(tmp_path):
    from engine.state import team_state
    # first game in the fixture where the home team won its last game and the road team lost its last
    def fits(x):
        fin = [y for y in ALL if y.game_date < x.game_date]
        return (team_state(x.home, fin, x.game_date).last_won is True
                and team_state(x.away, fin, x.game_date).last_won is False)
    g = next(x for x in ALL if x.game_date >= date(2025, 11, 10) and fits(x))
    day = g.game_date
    t = lambda h: datetime(day.year, day.month, day.day, h, 0, tzinfo=timezone.utc)

    def lines(total):
        return lambda: ({(day, g.away, g.home): {"home_spread": -10.5, "total": total,
                                                 "source": "test", "books": 5}}, {})

    store = LocalStore(tmp_path)
    fd = make_fetch_day(day, day - timedelta(1))
    b = run(now=t(15), fetch_day=fd,
            fetch_lines=lines(228.5), fetch_kalshi=fake_kalshi, store=store, season_start=START)
    assert any(p["system"] == 4 and p["game_id"] == g.id for p in b["bets"])

    # total drops to 219.5 an hour later → System 4 no longer qualifies
    b = run(now=t(16), fetch_day=fd,
            fetch_lines=lines(219.5), fetch_kalshi=fake_kalshi, store=store, season_start=START)
    assert not any(p["system"] == 4 and p["game_id"] == g.id for p in b["bets"])
    d = [p for p in b["dropped"] if p["system"] == 4 and p["game_id"] == g.id]
    assert d and d[0]["first_line"] == 228.5
