"""Read-only: every X2 pick (system 302) with its result."""
from .store import get_store


def main():
    st = get_store()
    rows = st._req("GET", "/picks?system=eq.302&select=key,game_date,tip_utc,away,home,side,label,line,first_line,"
                          "first_seen,active,dropped_reason,evidence,result,final_score,meta&order=first_seen") or []
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
