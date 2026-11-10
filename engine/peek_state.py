"""Read-only: the injury desk's per-game read histories (bet_state read:*) and the last board's notes.
Run: python -m engine.peek_state"""
from .store import get_store


def main():
    st = get_store()
    rows = st._req("GET", "/bet_state?key=like.read:*&select=key,updated_at,value") or []
    print(len(rows), "games with a read history")
    for r in rows[:12]:
        h = (r.get("value") or {}).get("h") or []
        print(" ", r["key"], r["updated_at"][:19], len(h), "entries; last:", h[-1] if h else None)
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    print("board", b.get("generated_at"), "injury_desk on board:", bool(b.get("injury_desk")))
    print("notes mentioning the desk:", [n for n in b.get("notes") or [] if "desk" in n.lower()])


if __name__ == "__main__":
    main()
