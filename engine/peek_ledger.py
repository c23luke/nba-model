"""Walk the ledger filters on live data and print what each step keeps. Run: python -m engine.peek_ledger"""
from . import run as R
from .store import get_store


def main():
    st = get_store()
    orders = st.load_orders()
    print("orders loaded:", len(orders))
    for o in orders:
        if (o.get("created_at") or "") >= "2026-10-26T12":
            print("  ", o.get("system"), o.get("pick"), o.get("status"), o.get("fill_count"), "tip", repr(o.get("tip_utc")), "created", o.get("created_at"))
    games = {r["id"]: r for r in st.load_games()}
    p, kept = R.since_restart(st.load_picks(), orders, games)
    print("kept after restart filter:", [(o.get("system"), o.get("pick")) for o in kept])
    print("exclude:", R.excluded_keys(st.get_config("exclude")))


if __name__ == "__main__":
    main()
