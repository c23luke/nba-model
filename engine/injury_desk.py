"""THE INJURY DESK — tracking only, never bets (Caden 2026-11-10: "keep record of injury news and changes and try
to get ahead of those line changes ... track CLV and see how we do").

Two parts:
1. record_reads(): every model run, for every game on the slate, save a short history of what the players model
   and the market said — the market line, our fair line, the range of our fair line over the day-to-day versions,
   and who is day-to-day — appended only when something changed. Stored per game in bet_state ("read:<game_id>").
   The watcher reruns the model within about a minute of each official injury report, so this history shows
   what our number did the moment news landed, and what the market did after.
2. build(): for every official-report status change (injury_log), what happened:
     our move     how far our fair line moved on that news (home-spread points)
     market       the market line when our read updated, 15 / 30 / 60 minutes later, and the last one before tip
     paper bet    if the news left our worst-case read 3+ points off the market (and it wasn't before the news),
                  a paper bet at that moment's market number; graded at the final; CLV vs the close
   Saved to bet_state "injury_desk" and shown on the site (Lab tab).
Run by hand: python -m engine.injury_desk"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KEEP = 120            # read-history entries kept per game
PAPER_GAP = 3.0       # the same 3-point worst-case bar a system bet needs
MOVE_MIN = 1.0        # news that moved our number at least this much (home-spread points)
WINDOW_DAYS = 10


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def read_entry(g: dict, now: datetime) -> dict | None:
    """One snapshot of a slate game: market, our fair line, the day-to-day range, who is day-to-day."""
    v = g.get("personnel") or {}
    if g.get("home_spread") is None or v.get("fair") is None:
        return None
    fairs = [s["fair"] for s in v.get("scenarios") or [] if s.get("fair") is not None] or [v["fair"]]
    return {"ts": now.isoformat(), "mkt": g["home_spread"], "fair": v["fair"], "lo": min(fairs), "hi": max(fairs),
            "dtd": sorted(v.get("waiting_on") or []), "blind": bool(v.get("blind"))}


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("mkt", "fair", "lo", "hi", "dtd", "blind"))


def record_reads(store, slate: list[dict], now: datetime) -> int:
    """Append a read to each slate game's history when anything changed. Returns how many games were updated."""
    entries = {f"read:{g['game_id']}": e for g in slate if (e := read_entry(g, now))}
    if not entries:
        return 0
    old = store.load_state(list(entries))
    out = {}
    for k, e in entries.items():
        h = (old.get(k) or {}).get("h") or []
        if h and _same(h[-1], e):
            continue
        out[k] = {"h": (h + [e])[-KEEP:]}
    store.save_state(out)
    return len(out)


def _at(h: list[dict], t: datetime) -> dict | None:
    """The last read at or before time t."""
    best = None
    for e in h:
        if _ts(e["ts"]) <= t:
            best = e
        else:
            break
    return best


def events_from_log(rows: list[dict]) -> list[dict]:
    """Group official-report rows into events: one team, one game date, one report time (rows first seen
    within 3 minutes of each other). Keeps only rows that are a change: a player's first listing, or a status
    different from his previous one."""
    rows = sorted([r for r in rows if r.get("first_seen")], key=lambda r: r["first_seen"])
    last: dict = {}
    changes = []
    for r in rows:
        k = (r["team"], r["game_date"], r.get("player_key") or r["player"])
        prev = last.get(k)
        last[k] = r["status"]
        if prev != r["status"]:
            changes.append({**r, "was": prev})
    events: list[dict] = []
    for c in changes:
        e = next((x for x in events if x["team"] == c["team"] and x["game_date"] == c["game_date"]
                  and abs((_ts(c["first_seen"]) - _ts(x["at"])).total_seconds()) <= 180), None)
        if e is None:
            e = {"team": c["team"], "game_date": c["game_date"], "at": c["first_seen"], "changes": []}
            events.append(e)
        e["changes"].append(f"{c['player']}: {(c['was'] or 'not listed')} → {c['status']}")
    return events


def judge(event: dict, game: dict, h: list[dict]) -> dict | None:
    """What our number and the market did around one report event on one game."""
    t = _ts(event["at"])
    before = _at(h, t - timedelta(seconds=1))
    # our first read after the news (the watcher reruns within about a minute; allow 20)
    after = next((e for e in h if t <= _ts(e["ts"]) <= t + timedelta(minutes=20)
                  and (before is None or e["fair"] != before["fair"] or e["lo"] != before["lo"] or e["hi"] != before["hi"])), None)
    if before is None or after is None:
        return None
    move = round(after["fair"] - before["fair"], 1)
    worst_move = round(max(abs(after["lo"] - before["lo"]), abs(after["hi"] - before["hi"])), 1)
    if max(abs(move), worst_move) < MOVE_MIN:
        return None
    tip = _ts(game["tip_utc"]) if game.get("tip_utc") else None
    acted = _ts(after["ts"])
    def mkt(mins):
        x = _at(h, acted + timedelta(minutes=mins))
        return None if x is None or (tip and _ts(x["ts"]) >= tip) else x["mkt"]
    pre_tip = [e for e in h if not tip or _ts(e["ts"]) < tip]
    close = pre_tip[-1]["mkt"] if pre_tip else None
    out = {"game_id": game["id"], "away": game["away"], "home": game["home"], "team": event["team"],
           "at": event["at"], "changes": event["changes"][:8], "our_move": move,
           "fair_before": before["fair"], "fair_after": after["fair"], "mkt_before": before["mkt"],
           "mkt_at": after["mkt"], "mkt_15": mkt(15), "mkt_30": mkt(30), "mkt_60": mkt(60), "mkt_close": close,
           "seconds_to_read": int((acted - t).total_seconds())}
    # did the market follow us? + = the market moved the way our number moved (points, home spread)
    if close is not None:
        follow = close - after["mkt"]
        out["market_followed"] = round(follow if move > 0 else -follow, 1) if move else None
    # paper bet: the news put our WORST-case read 3+ off the market, and it wasn't before the news
    def worst(e, side):
        return (e["mkt"] - e["hi"]) if side == "home" else (e["lo"] - e["mkt"])
    for side in ("home", "away"):
        if not after["blind"] and worst(after, side) >= PAPER_GAP and worst(before, side) < PAPER_GAP:
            line = after["mkt"] if side == "home" else -after["mkt"]
            team = game["home"] if side == "home" else game["away"]
            bet = {"side": team, "line": line, "gap": round(worst(after, side), 1)}
            if close is not None:
                c = close if side == "home" else -close
                bet["clv"] = round(line - c, 1)          # + = our number was better than the close
            if game.get("final") and game.get("home_score") is not None:
                m = game["home_score"] - game["away_score"]
                r = (m + line) if side == "home" else (-m + line)
                bet["result"] = "W" if r > 0 else "L" if r < 0 else "P"
            out["paper"] = bet
    return out


def build(store, now: datetime | None = None, days: int = WINDOW_DAYS) -> dict:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()
    games = [g for g in store.load_games() if (g.get("game_date") or "") >= since]
    by_key = {(g["game_date"], t): g for g in games for t in (g["away"], g["home"])}
    rows = store._req("GET", f"/injury_log?game_date=gte.{since}&select=*") if hasattr(store, "_req") else \
        [r for r in store._read("injury_log", []) if (r.get("game_date") or "") >= since]
    events = events_from_log(rows or [])
    hist = store.load_state([f"read:{g['id']}" for g in games])
    out = []
    for e in events:
        g = by_key.get((e["game_date"], e["team"]))
        if not g:
            continue
        h = (hist.get(f"read:{g['id']}") or {}).get("h") or []
        j = judge(e, g, h) if h else None
        if j:
            out.append(j)
    out.sort(key=lambda x: x["at"], reverse=True)
    paper = [x["paper"] for x in out if x.get("paper")]
    graded = [p for p in paper if p.get("result") in ("W", "L")]
    clvs = [p["clv"] for p in paper if p.get("clv") is not None]
    follows = [x["market_followed"] for x in out if x.get("market_followed") is not None]
    reads = [x["seconds_to_read"] for x in out]
    summary = {"at": now.isoformat(), "days": days, "events": len(out),
               "paper": {"bets": len(paper), "w": sum(p["result"] == "W" for p in graded),
                         "l": sum(p["result"] == "L" for p in graded),
                         "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else None,
                         "beat_close": sum(c > 0 for c in clvs), "n_clv": len(clvs)},
               "market_followed_avg": round(sum(follows) / len(follows), 2) if follows else None,
               "median_seconds_to_read": sorted(reads)[len(reads) // 2] if reads else None,
               "recent": out[:40]}
    return summary


def main():
    from .store import get_store
    st = get_store()
    d = build(st)
    st.save_state({"injury_desk": d})
    print(f"events {d['events']}  paper {d['paper']}  market followed {d['market_followed_avg']}  "
          f"median seconds to read {d['median_seconds_to_read']}")
    for x in d["recent"]:
        print(" ", x["at"][:16], x["away"], "@", x["home"], x["team"], x["changes"], "our move", x["our_move"],
              "mkt", x["mkt_at"], "→", x["mkt_15"], x["mkt_30"], x["mkt_60"], "close", x["mkt_close"], x.get("paper"))


if __name__ == "__main__":
    main()
