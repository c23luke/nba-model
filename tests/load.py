import csv
from datetime import date
from engine.state import Game
from engine.teams import code

def fixture_games(path="tests/fixtures/espn_2025_oct_dec.csv"):
    out = []
    for i, r in enumerate(csv.DictReader(open(path))):
        out.append(Game(id=f"g{i}", game_date=date.fromisoformat(r["date"]),
                        away=code(r["away"]), home=code(r["home"]),
                        away_score=int(r["away_score"]), home_score=int(r["home_score"]),
                        periods=int(r["periods"]), final=True))
    return out
