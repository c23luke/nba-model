"""Read-only: for every placed bet, opposing players who played real minutes in that game but sat the opponent's
previous game, and whether the opponent's official report was filed when we bet. Under the Nov 10 rule such a
player (if ESPN still listed him out) is priced as maybe-playing until the report is in.
Run: python -m engine.audit_returners"""
from .store import get_store


def main():
    st = get_store()
    orders = [o for o in st.load_orders() if (o.get("fill_count") or 0) > 0 and (o.get("created_at") or "") >= "2026-10-29"]
    games = {g["id"]: g for g in st.load_games()}
    seen = set()
    for o in sorted(orders, key=lambda o: o["created_at"]):
        k = (o["game_id"], o.get("side"))
        if k in seen:
            continue
        seen.add(k)
        g = games.get(o["game_id"]) or {}
        if not g:
            continue
        opp = g["home"] if o.get("side") == g["away"] else g["away"]
        mine = st._req("GET", f"/player_games?game_id=eq.{g['id']}&team=eq.{opp}&select=name,min") or []
        prev = st._req("GET", f"/player_games?team=eq.{opp}&game_date=lt.{g['game_date']}&select=game_id,game_date,name,min"
                              f"&order=game_date.desc&limit=40") or []
        last_gid = prev[0]["game_id"] if prev else None
        played_last = {r["name"] for r in prev if r["game_id"] == last_gid and (r.get("min") or 0) > 0}
        back = [f"{r['name']} {r['min']}min" for r in mine if (r.get("min") or 0) >= 15 and r["name"] not in played_last]
        rep = st._req("GET", f"/injury_log?team=eq.{opp}&game_date=eq.{g['game_date']}&select=first_seen&order=first_seen.asc&limit=1") or []
        filed = rep[0]["first_seen"] if rep else None
        before = filed is None or filed > o["created_at"]
        print(f"{o['created_at'][:16]} {o.get('pick'):12} {o.get('system'):9} opp {opp}: report "
              f"{'NOT filed when we bet' if before else 'filed'} ({(filed or '')[:16]}); "
              f"opp players 15+ min who sat their previous game: {back or 'none'}")


if __name__ == "__main__":
    main()
