"""Print a few full log messages matching a pattern. Run: python -m engine.log_peek"""
from .store import get_store


def main():
    st = get_store()
    rows = st._req("GET", "/bet_log?message=like.Resting%20order%20check%20failed*&select=ts,message&order=ts.desc&limit=3") or []
    for r in rows:
        print(r["ts"], r["message"][:700])


if __name__ == "__main__":
    main()
