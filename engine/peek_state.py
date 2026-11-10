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
    for x in b.get("testing") or []:
        print("testing:", x["name"], f'{x["w"]}-{x["l"]}', "bets", x["bets"], "open", x["open"], "clv", x["avg_clv"], "ready", x["ready"])
    pd = b.get("props_desk") or {}
    print("props desk:", {k: pd.get(k) for k in ("bets", "w", "l", "avg_clv")}, [ (r["player"], r["line"], r["proj_pts"]) for r in pd.get("recent") or []][:5])
    print("X2 picks today:", [(p.get("label"), (p.get("evidence") or [""])[0]) for p in b.get("shadow") or b.get("shadow_picks") or []][:8])
    print("notes:", [n for n in b.get("log") or b.get("notes") or [] if "props" in str(n) or "testing" in str(n) or "cluster" in str(n)])
    print("notes mentioning the desk:", [n for n in b.get("notes") or [] if "desk" in n.lower()])


if __name__ == "__main__":
    main()
