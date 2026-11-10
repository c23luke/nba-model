"""Read-only: the 'exclude' config value and what the board did with it. Run: python -m engine.peek_exclude"""
from .store import get_store


def main():
    st = get_store()
    print("raw:", st._req("GET", "/config?key=eq.exclude&select=key,value"))
    try:
        print("parsed:", st.get_config("exclude"))
    except Exception as e:
        print("parse failed:", e)
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    print("board", b.get("generated_at"), "excluded:", (b.get("placed") or {}).get("excluded"))
    print("notes:", [n for n in b.get("notes") or [] if "exclu" in n.lower()])


if __name__ == "__main__":
    main()
