"""Print the live board JSON (the same data the public site reads) for previewing the site.
Run: python -m engine.dump_board"""
import json

from .store import get_store

if __name__ == "__main__":
    st = get_store()
    print(json.dumps((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}))
