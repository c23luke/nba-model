"""Read-only AUDIT of every bet placed since the restart (Caden 2026-11-10: "audit every game that we bet and what
was played, did we win, did we get CLV, why or why not").

For each bet (one ticket per game side, split fills merged): the system and the card's number, what we bought,
where, when and at what price; the result and the final margin vs our number; the line path (first seen, at the
bet, at tip) and CLV; every injury-report change for both teams AFTER we bet (the news that moved the line);
the players model's read when we bet and now; whether today's record counts it and why not.
Also: who actually played (minutes) for any player listed out/questionable, so a wrong status is visible.
Run: python -m engine.audit_bets"""
from __future__ import annotations

from datetime import datetime, timezone

from . import sources
from .run import SEASON_START, build_board
from .store import get_store


def _t(s):
    return (s or "")[:16].replace("T", " ")


def main():
    st = get_store()
    live = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    now = datetime.now(timezone.utc)
    today = now.astimezone(sources.ET).date()
    games = {r["id"]: r for r in st.load_games()}
    picks = st.load_picks()
    by_key = {p["key"]: p for p in picks}
    b = build_board(now, today, live.get("slate") or [], picks, live.get("odds_api") or {}, [],
                    live.get("line_source") or "", max(0, (today - SEASON_START).days), st.load_orders(), games,
                    st.get_config("bench"), st.get_config("exclude"))
    placed = b["placed"]
    rows = sorted(placed["bets"], key=lambda r: r.get("placed_at") or "")
    rn = placed["rules_now"]
    s = placed["summary"]
    print(f"RECORD (today's rules): {rn['w']}-{rn['l']}-{rn['p']}  pnl {rn['pnl']}   | real account {s['w']}-{s['l']}-{s['p']} pnl {s['pnl']}")
    if placed.get("excluded"):
        print("EXCLUDED (model bug):", placed["excluded"])
    print(f"{len(rows)} tickets\n")
    for i, r in enumerate(rows, 1):
        gid = r["game_id"]
        g = games.get(gid) or {}
        p = by_key.get(r.get("key")) or {}
        meta = p.get("meta") or {}
        R = r.get("rules") or {}
        print("=" * 110)
        print(f"#{i} {r['status']} {r.get('result') or '-'}  {r['system']:9} card {r.get('card_pick')}  BOUGHT {r['holding']} "
              f"at {r.get('american')} on {r['venue_name']}  risk ${r['risk']} to win ${r['to_win']}  real pnl {r.get('pnl')}")
        print(f"   game {gid} {g.get('away')} @ {g.get('home')} {g.get('game_date')}  final {g.get('away_score')}-{g.get('home_score')}"
              f"  placed {_t(r.get('placed_at'))}Z  tip {_t(r.get('tip_utc'))}Z")
        if g.get("final") and r.get("line") is not None and r.get("bet") == "spread":
            m = (g["home_score"] - g["away_score"]) if r["side"] == g["home"] else (g["away_score"] - g["home_score"])
            print(f"   {r['side']} margin {m:+d}; with our {r['line']:+g} → covered by {m + float(r['line']):+g}")
        print(f"   record: {'COUNTED pnl ' + str(R.get('pnl')) if R.get('counted') else 'NOT COUNTED: ' + str(R.get('why'))}"
              f"   | ev at bet {r.get('ev')}  | players at bet {r.get('players')} now {r.get('players_now')}"
              f"  | frozen snapshot: {'yes' if meta.get('bet_snap') else 'no'}")
        print(f"   why (card): {str(r.get('price_note'))[:260]}")
        if r.get("pieces"):
            print("   pieces:", [(x["holding"], x["count"], x["cost"], x["american"]) for x in r["pieces"]])
        # line path
        pl = st._req("GET", f"/price_log?game_id=eq.{gid}&select=ts,home_spread,total&order=ts.asc&limit=10000") or []
        pl = [x for x in pl if x.get("home_spread") is not None]
        if pl:
            at = [x for x in pl if x["ts"] <= (r.get("placed_at") or "")]
            first, bet_line, last = pl[0], (at[-1] if at else None), pl[-1]
            side_line = lambda hs: (hs if r["side"] == g.get("home") else -hs) if hs is not None else None
            print(f"   line on our side: first seen {side_line(first['home_spread']):+g} ({_t(first['ts'])}Z)"
                  f" · when we bet {side_line(bet_line['home_spread']) if bet_line else None}"
                  f" · last before tip {side_line(last['home_spread']):+g} ({_t(last['ts'])}Z)"
                  f"  → CLV vs close {r.get('clv_pts')} pts")
            moves, prev = [], None
            for x in pl:
                if prev is not None and abs(x["home_spread"] - prev) >= 1.0:
                    moves.append(f"{_t(x['ts'])}Z {side_line(prev):+g}→{side_line(x['home_spread']):+g}")
                prev = x["home_spread"]
            if moves:
                print("   big moves (1+ pt):", "; ".join(moves[:8]))
        # injury news for both teams on this game date, and when it appeared vs our bet
        inj = []
        for t in (g.get("away"), g.get("home")):
            if t and g.get("game_date"):
                inj += st._req("GET", f"/injury_log?team=eq.{t}&game_date=eq.{g['game_date']}&select=*") or []
        after = sorted([x for x in inj if (x.get("first_seen") or "") > (r.get("placed_at") or "")],
                       key=lambda x: x.get("first_seen") or "")
        before = [x for x in inj if (x.get("first_seen") or "") <= (r.get("placed_at") or "")]
        print(f"   injury report: {len(before)} entries known when we bet, {len(after)} new/changed after")
        for x in after:
            print(f"      after bet: {_t(x.get('first_seen'))}Z {x['team']} {x['player']} → {x['status']} | {x.get('reason')}")
        listed = {(x["team"], x["player"]) for x in inj if x["status"] in ("Out", "Doubtful", "Questionable")}
        if listed and g.get("final"):
            box = st._req("GET", f"/player_games?game_id=eq.{gid}&select=team,name,min") or []
            mins = {(x["team"], x["name"]): x.get("min") for x in box}
            played = [f"{t} {n} {mins[(t, n)]}min" for t, n in sorted(listed) if (mins.get((t, n)) or 0) > 0]
            if played:
                print("   listed out/doubtful/questionable at some point but PLAYED:", "; ".join(played))
    print("\nOPEN STANDING ORDERS:", placed.get("resting"))


if __name__ == "__main__":
    main()
