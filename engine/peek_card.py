"""Read-only: today's card rows from the live board, with the players-model read and the reason.
Run: python -m engine.peek_card"""
import json

from .store import get_store


def main():
    st = get_store()
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    print("board generated", b.get("generated_at"))
    for c in b.get("card") or []:
        print(json.dumps({k: c.get(k) for k in ("verdict", "tag", "label", "away", "home", "tip", "players", "with",
                                                 "rule_pass", "why", "line", "market", "best")}, default=str)[:1500])


if __name__ == "__main__":
    main()
