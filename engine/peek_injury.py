"""Official injury-report history for one team's players today. Run: python -m engine.peek_injury"""
import os

from .store import get_store

if __name__ == "__main__":
    st = get_store()
    for team in ("LAL", "LAC"):
        rows = st._req("GET", f"/injury_log?team=eq.{team}&select=*&order=first_seen.asc") or []
        for r in rows[-15:]:
            print(team, {k: r.get(k) for k in ("player", "status", "reason", "game_date", "first_seen", "last_seen")})
