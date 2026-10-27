"""Quick health check of the live board (notes, card, rankings, logs). Run: python -m engine.board_check"""
from .store import get_store


def main():
    st = get_store()
    b = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    print("generated:", b.get("generated_at"))
    print("\nNOTES:")
    for n in b.get("notes") or []:
        print("  -", n[:300])
    print("\nCARD:")
    for c in b.get("card") or []:
        print(f"  {c.get('verdict'):8} {c.get('tag'):4} {c.get('label')}  {c.get('away')}@{c.get('home')}  players={c.get('players')}")
    print("\nPOWER (top 5 / bottom 5):")
    t = (b.get("power") or {}).get("teams") or []
    for r in t[:5] + t[-5:]:
        print(f"  {r['rank']:2} {r['team']} {r['rating']:+.1f} (players {r['players']:+.1f}, results {r['results_adj']:+.1f}, {r['results_games']} g) {r.get('record')}")
    for table in ("injury_log", "price_log"):
        try:
            rows = st._req("GET", f"/{table}?select=id&limit=1000") or []
            print(f"\n{table}: {len(rows)} rows (first 1000)")
        except Exception as e:
            print(f"\n{table}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
