"""Read-only: who played and how much in one or more games (player_games). Run: GAMES=id1,id2 python -m engine.peek_box"""
import os

from .store import get_store


def main():
    st = get_store()
    for gid in os.environ.get("GAMES", "401909952,401909946").split(","):
        rows = st._req("GET", f"/player_games?game_id=eq.{gid}&select=*") or []
        print("=== game", gid, len(rows), "rows")
        if rows:
            print("   columns:", sorted(rows[0].keys()))
        for r in sorted(rows, key=lambda r: (r.get("team") or "", -(float(r.get("minutes") or r.get("min") or 0)))):
            print("  ", {k: r.get(k) for k in ("team", "player", "name", "minutes", "min", "pts", "starter", "plus_minus") if k in r})


if __name__ == "__main__":
    main()
