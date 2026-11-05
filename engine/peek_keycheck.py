"""Read-only: the bettor's newest key-check lines in full (Novig test results). Run: python -m engine.peek_keycheck"""
from .store import get_store

if __name__ == "__main__":
    for r in get_store()._req("GET", "/bet_log?message=like.Key%20check*&select=ts,message&order=ts.desc&limit=2") or []:
        print(r["ts"][:19])
        for part in r["message"].split(" · "):
            print("  ", part)
