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
    for g in b.get("slate") or []:
        pv = g.get("personnel") or {}
        if pv.get("thin_share"):
            print("thin:", g.get("away"), "@", g.get("home"), pv.get("thin_share"), "flag:", pv.get("thin"))
    pe = b.get("props_ev") or {}
    print("props ev:", {k: pe.get(k) for k in ("bets", "w", "l", "open", "avg_ev", "avg_clv")}, "stacked:", (pe.get("stacked") or {}).get("bets"))
    for x in (pe.get("recent") or [])[:8]:
        print("   ", x["player"], x["side"], x["line"], x["stat"], x["venue"], x["price"], "pin", x["pin_price"], "ev", x["ev"])
    pm = (b.get("props_ev") or {}).get("model") or {}
    print("props model:", {k: pm.get(k) for k in ("bets", "w", "l", "open")}, "| players projected tonight:",
          (b.get("props_ev") or {}).get("projected"), "| biggest moves vs last-10:", (b.get("props_ev") or {}).get("sample_proj"))
    for x in (pm.get("recent") or [])[:12]:
        print("   ", x["player"], x["side"], x["line"], x["stat"], "proj", x["proj"], "l10", x.get("l10"), x["venue"], x["price"],
              "ev vs pin", x["ev"], "out:", x.get("fresh_out"), "ret:", x.get("returning"))
    print("all notes:", [n for n in (b.get("log") or b.get("notes") or [])][:10])
    pe2 = b.get("props_ev") or {}
    for k in ("open_lines", "news_desk"):
        x = pe2.get(k) or {}
        print(f"{k}:", {kk: x.get(kk) for kk in ("bets", "w", "l", "open", "avg_move")})
    rd = pe2.get("ready") or {}
    print("ready list games:", len(rd), "entries:", sum(len(v.get("list") or []) for v in rd.values()))
    print("news notes:", [n for n in (b.get("log") or b.get("notes") or []) if "News desk" in str(n) or "props" in str(n).lower() or "Shot" in str(n)])
    print("notes:", [n for n in b.get("log") or b.get("notes") or [] if "props" in str(n) or "testing" in str(n) or "cluster" in str(n)])
    print("notes mentioning the desk:", [n for n in b.get("notes") or [] if "desk" in n.lower()])


if __name__ == "__main__":
    main()
