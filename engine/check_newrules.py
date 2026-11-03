"""Read-only: rebuild the board from live data with the code in this commit (nothing saved) and print what
the new rules do — today's card, every placed bet counted or not and why, the record, the systems' records.
The board JSON follows the line BOARD_JSON so the site can be previewed with it.
Run: python -m engine.check_newrules"""
import json
from datetime import datetime, timezone

from . import sources
from .run import SEASON_START, build_board
from .store import get_store


def main():
    st = get_store()
    live = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    now = datetime.now(timezone.utc)
    today = now.astimezone(sources.ET).date()
    games = {r["id"]: r for r in st.load_games()}
    b = build_board(now, today, live.get("slate") or [], st.load_picks(), live.get("odds_api") or {}, [],
                    live.get("line_source") or "", max(0, (today - SEASON_START).days), st.load_orders(), games,
                    st.get_config("bench"), st.get_config("exclude"))
    b["placer"] = live.get("placer")
    print("=== CARD (today, new rule)")
    for c in b["card"]:
        print(f"  {c['verdict']:8} {c['tag']:9} {c['label']:14} {c['away']}@{c['home']}  players {c.get('players')}  "
              f"with {c.get('with')}  | {str(c.get('why'))[:150]}")
    print("\n=== PLACED BETS since Oct 29 (one ticket per side)")
    for r in b["placed"]["bets"]:
        R = r.get("rules") or {}
        print(f"  {r['status']:6} {r.get('result') or '-':2} {r['system']:9} {r['holding']:22} {r['venue_name']:20} "
              f"fills {len(r.get('fills') or [])}  players {r.get('players')}  real pnl {r.get('pnl')}  "
              f"{'COUNTED pnl ' + str(R.get('pnl')) if R.get('counted') else 'NOT COUNTED: ' + str(R.get('why'))}")
    rn = b["placed"]["rules_now"]
    print(f"\n=== RECORD under today's rules: {rn['w']}-{rn['l']}-{rn['p']}  pnl {rn['pnl']}  risked {rn['risked']}  "
          f"open {rn['open']} at risk {rn['at_risk']}")
    s = b["placed"]["summary"]
    print(f"    real account (every order): {s['w']}-{s['l']}-{s['p']} pnl {s['pnl']}")
    print("\n=== SYSTEMS since Oct 29 (graded at the number it fired; only picks today's rule would bet)")
    for grp in ("systems", "test_systems", "early_systems"):
        for k, v in (b.get(grp) or {}).items():
            f = v.get("if_first") or {}
            if v.get("w") or v.get("l") or f.get("n") or v.get("open"):
                print(f"  {v['tag']:9} {v['w']}-{v['l']}  (at first line {f.get('w')}-{f.get('l')})  open {v.get('open')}")
    print(f"  combo (system + players 3+, one per side): {b.get('combo_live')}")
    print("\nBOARD_JSON")
    print(json.dumps(b, default=str))


if __name__ == "__main__":
    main()
