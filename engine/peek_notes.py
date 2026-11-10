"""Read-only: the live board's run notes (official report, roster checks, failures). Run: python -m engine.peek_notes"""
from .store import get_store


def main():
    st = get_store()
    b = ((st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {})
    print("board", b.get("generated_at"))
    for n in b.get("notes") or []:
        print(" -", n[:1500])


if __name__ == "__main__":
    main()
