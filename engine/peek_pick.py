"""Read-only: one or more picks in full (evidence + meta). Run: KEYS=k1,k2 python -m engine.peek_pick"""
import json
import os

from .store import get_store


def main():
    st = get_store()
    for k in os.environ.get("KEYS", "401909927-S113-MEM,401909927-S301-MEM,401909291-S113-MEM,401909946-S113-LAL").split(","):
        for p in st._req("GET", f"/picks?key=eq.{k}&select=*") or []:
            print("=" * 80)
            print(json.dumps({x: p.get(x) for x in ("key", "line", "first_line", "first_seen", "result", "evidence")}, indent=1, default=str))
            print("meta:", json.dumps(p.get("meta"), default=str)[:3000])


if __name__ == "__main__":
    main()
