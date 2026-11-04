"""Read-only: the bet_feed row (every quote the model priced) for one bet key. Run: KEY=... python -m engine.peek_feed"""
import os

from .store import get_store

if __name__ == "__main__":
    st = get_store()
    for r in st._req("GET", f"/bet_feed?key=eq.{os.environ.get('KEY', '401909926-S204-CHI')}&select=*") or []:
        print("updated", r.get("updated_at"), "status", r.get("status"), "pick", r.get("pick"), "why", r.get("why"))
        for q in sorted(r.get("quotes") or [], key=lambda q: (q.get("venue"), q.get("line"))):
            print("  ", q.get("venue"), q.get("contract"), "line", q.get("line"), "price", q.get("price_txt"),
                  "cost", q.get("cost"), "size", q.get("size"), "win", q.get("win"), "ev", q.get("ev"))
