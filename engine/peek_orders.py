"""Today's live orders and the pick each one points to (meta), for debugging the ledger.
Run: python -m engine.peek_orders"""
from .store import get_store


def main():
    st = get_store()
    orders = st._req("GET", "/bet_orders?mode=eq.live&created_at=gte.2026-10-27T04:00:00Z&select=*&order=created_at.asc") or []
    picks = {p["key"]: p for p in st.load_picks()}
    for o in orders:
        p = picks.get(o.get("bet_key")) or {}
        print(o.get("created_at"), o.get("status"), o.get("system"), o.get("venue"), o.get("pick"), "|", o.get("bet_key"),
              "| pick found:", bool(p), "| active:", p.get("active"), "| meta:", {k: v for k, v in (p.get("meta") or {}).items() if k != "card_snap"})


if __name__ == "__main__":
    main()
