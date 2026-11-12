"""Read-only: save the live board (what the public site already loads) to reports/engine.peek_board.json, so the
site can be tested in a browser against real data."""
import json
from pathlib import Path

from .store import get_store


def main():
    st = get_store()
    rows = st._req("GET", "/board?id=eq.1&select=data") or []
    data = rows[0]["data"] if rows else {}
    Path(__file__).resolve().parent.parent.joinpath("reports", "engine.peek_board.json").write_text(json.dumps(data))
    print("board keys:", sorted(data.keys()))


if __name__ == "__main__":
    main()
