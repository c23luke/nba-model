"""Same as engine.measure_props_soft, on the books that post ONE main line per player (DraftKings, FanDuel, BetMGM,
Caesars, BetOnline, Fanatics). Bovada and BetRivers post ladders of alternate lines, and the saved snapshot kept
only one of them per player, so their rows were graded against alternate lines (Bovada's "70%" at losing prices).
Uses the lines already saved in reports/engine.measure_props_soft.json: no credits.
Run: python -m engine.measure_props_soft_main"""
from . import measure_props_soft as M

if __name__ == "__main__":
    M.SOFT = ("draftkings", "fanduel", "betmgm", "williamhill_us", "betonlineag", "fanatics")
    M.KEY = ""                     # never buy lines in this run
    M.main()
