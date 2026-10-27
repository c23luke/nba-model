"""Full audit of the live model: what's working, what isn't, and why bets were the size they were.

Reads the live Supabase tables (service key): picks, bet_orders, bet_log, board.
Sections:
  1. Every live order: system, site, what we asked for vs what we got (stake / to-win), and flags:
     SMALL = won less than 75% of the $20 / $10 target, with the cause (partial fill, offer size ...)
  2. Placed results by system, by group (OG / FAV / EARLY), by site
  3. Every system's season record from the model's own picks (official + if-bet-at-first-line),
     line movement (CLV), whether it is on the bet card (auto-bet) or only tracked
  4. Card bets that were never placed, and the placer's reasons (from its 15-minute logs)
  5. Players-model shadow (X1): by gap size and call
Run: python -m engine.audit   (needs SUPABASE_URL + SUPABASE_SERVICE_KEY)
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .store import get_store
from .systems import SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS, FAVORITES, label, group

NAMES = {sid: d.get("name", "") for defs in (SYSTEMS, TEST_SYSTEMS, EARLY_SYSTEMS) for sid, d in defs.items()}


def wl(rs):
    w, l, p = (sum(r == x for r in rs) for x in "WLP")
    pct = f"{w / (w + l):.1%}" if w + l else "  -  "
    return f"{w}-{l}" + (f"-{p}" if p else "") + f" ({pct})"


def money(x):
    return f"{'-' if x < 0 else '+'}${abs(x):.2f}"


def main():
    st = get_store()
    picks = st.load_picks()
    orders = st._req("GET", "/bet_orders?mode=eq.live&select=*&order=created_at.asc") or []
    board = (st._req("GET", "/board?id=eq.1&select=data") or [{}])[0].get("data") or {}
    runs = st._req("GET", "/bet_log?message=like.run%20(*&select=ts,data&order=ts.desc&limit=2000") or []
    by_key = {p["key"]: p for p in picks}
    excluded = {(str(x["game_id"]), x["side"]) for x in (st.get_config("exclude") or [])}
    placed = {(b.get("id")): b for b in (board.get("placed") or {}).get("bets", [])}

    print("=" * 100)
    print("1. EVERY LIVE ORDER (oldest first)")
    print("=" * 100)
    small = []
    for o in orders:
        cnt, cost, fees = float(o.get("fill_count") or 0), float(o.get("fill_cost") or 0), float(o.get("fees") or 0)
        got = cnt - cost - fees if cnt else 0.0
        p = by_key.get(o.get("bet_key")) or {}
        conf = ((p.get("meta") or {}).get("card_snap") or {}).get("confidence")
        target = 10.0 if conf == "Low" else 20.0
        aim = float(o.get("count") or 0) - float(o.get("stake") or 0) - float(o.get("est_fee") or 0)
        flag = ""
        if o["status"] in ("filled", "partial") and got < 0.75 * target:
            if o["status"] == "partial":
                cause = f"partial fill: {cnt:g} of {o.get('count')} contracts"
            elif aim < 0.75 * target:
                cause = (f"asked for only {money(aim)} to win — "
                         + (o.get("reason") or "the offer/market had no more at that price (or the stake was capped)"))
            else:
                cause = "filled smaller than asked"
            flag = f"  SMALL ({cause})"
            small.append((o, got, cause))
        ex = " [EXCLUDED: model bug]" if (str(o.get("game_id")), o.get("side")) in excluded else ""
        print(f"{str(o.get('created_at'))[:16]}  {o.get('system') or '?':4} {group_of(o):6} {o.get('venue'):9} "
              f"{o['status']:9} {o.get('pick') or '':14} | {(o.get('contract') or '')[:44]:44} | asked to win "
              f"{money(aim) if aim else '   -   '} got {money(got) if cnt else '   -   '}"
              f"{flag}{ex}" + (f"\n{'':20}reason: {(o.get('reason') or '')[:160]}" if o['status'] in ('error', 'unfilled') else ""))
    print(f"\n{len(small)} filled bets won under 75% of the target:")
    for o, got, cause in small:
        print(f"  {o.get('pick')} ({o.get('system')}, {o.get('venue')}): to win {money(got)} — {cause}")

    print()
    print("=" * 100)
    print("2. PLACED RESULTS (from the site's ledger; excluded model-bug bets left out)")
    print("=" * 100)
    bets = (board.get("placed") or {}).get("bets", [])
    for key, title in (("system", "by system"), ("group", "by group"), ("venue_name", "by site")):
        agg = defaultdict(lambda: {"r": [], "pnl": 0.0, "risk": 0.0, "open": 0, "bc": []})
        for b in bets:
            a = agg[b.get(key) or "?"]
            if b["status"] == "FINAL":
                a["r"].append(b["result"]); a["pnl"] += b["pnl"] or 0; a["risk"] += b["risk"] or 0
            else:
                a["open"] += 1
            if b.get("market") and b["market"].get("closed") and b["market"].get("beat_close") is not None:
                a["bc"].append(b["market"]["beat_close"])
        print(f"  {title}")
        for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["pnl"]):
            bc = f"beat close {sum(a['bc']) / len(a['bc']):+.1f}¢ ({len(a['bc'])})" if a["bc"] else "beat close -"
            print(f"    {k:12} {wl(a['r']):18} P&L {money(a['pnl']):>9}  risked ${a['risk']:7.2f}  open {a['open']}  {bc}")
    s = (board.get("placed") or {}).get("summary") or {}
    print(f"  TOTAL: {s.get('w')}-{s.get('l')}-{s.get('p')}  P&L {money(s.get('pnl') or 0)}  risked ${s.get('risked')}  "
          f"avg beat close {s.get('avg_beat_close')}¢  | excluded (model bug) P&L {money(s.get('excluded_pnl') or 0)}")

    print()
    print("=" * 100)
    print("3. EVERY SYSTEM THIS SEASON (the model's own picks, graded at the pick's line)")
    print("   official = still qualified at tip; if-first = every time it fired, graded at the first line")
    print("   CLV = points the line moved our way from first fire to close (+ good)")
    print("=" * 100)
    recs = {}
    for k in ("systems", "test_systems", "early_systems", "shadow_systems"):
        recs.update({int(sid) if str(sid).isdigit() else sid: r for sid, r in (board.get(k) or {}).items()})
    rows = []
    for sid, r in recs.items():
        try:
            sid_i = int(sid)
        except (TypeError, ValueError):
            continue
        g = group(sid_i)
        auto = ("AUTO-BET" if g in ("OG", "FAV") else "AUTO-BET when players model agrees 3+" if g == "EARLY"
                else "tracked only")
        hist = r.get("history") or r.get("record") or ""
        rows.append((g, label(sid_i), r, auto))
    order = {"OG": 0, "FAV": 1, "EARLY": 2, "TEST": 3, "SHADOW": 4}
    for g, tag, r, auto in sorted(rows, key=lambda x: (order.get(x[0], 9), x[1])):
        ff = r.get("if_first") or {}
        print(f"  {tag:4} {g:6} {auto:38} official {r.get('w', 0)}-{r.get('l', 0)}-{r.get('p', 0)}"
              f"  if-first {ff.get('w', 0)}-{ff.get('l', 0)}-{ff.get('p', 0)}"
              f"  CLV {r.get('avg_clv') if r.get('avg_clv') is not None else '-'} ({r.get('n_clv', 0)})"
              f"  | {NAMES.get(int(tag[1:]) + {'S': 0, 'T': 100, 'E': 200, 'X': 300}[tag[0]], '')[:48]}")

    print()
    print("=" * 100)
    print("4. CARD BETS THAT WERE NEVER PLACED (picks the card showed, no live order)")
    print("=" * 100)
    ordered = {o.get("bet_key") for o in orders if float(o.get("fill_count") or 0) > 0}
    reasons = defaultdict(Counter)
    for run in runs:
        for sk in (run.get("data") or {}).get("skips") or []:
            reasons[sk["pick"]][sk["reason"][:140]] += 1
    carded = [p for p in picks if (p.get("meta") or {}).get("card_snap")]
    missed = [p for p in carded if p["key"] not in ordered]
    res = [p.get("result") for p in missed if p.get("result")]
    print(f"  {len(carded)} picks were on the card; {len(carded) - len(missed)} placed; {len(missed)} never placed "
          f"(graded: {wl(res)})")
    for p in sorted(missed, key=lambda p: p.get("tip_utc") or ""):
        tag = label(p["system"])
        name = f"{p.get('label') or p.get('side')} ({tag}) {p.get('away')}@{p.get('home')}"
        lab = ((p.get("meta") or {}).get("card_snap") or {}).get("label") or p.get("label") or ""
        c = reasons.get(f"{lab} ({tag}) {p.get('away')}@{p.get('home')}") or Counter()
        top = c.most_common(2)
        print(f"  {str(p.get('tip_utc'))[:10]} {name:34} result {p.get('result') or 'open':5}  "
              f"why not placed: {' / '.join(r[0] for r in top) if top else 'no placer log (card row was PASS/LIMIT or off-card before the placer ran)'}")

    print()
    print("=" * 100)
    print("5. PLAYERS MODEL SHADOW (X1, every game) by gap and call")
    print("=" * 100)
    x1 = [p for p in picks if p["system"] == 301 and p.get("result")]
    buckets = defaultdict(list)
    for p in x1:
        m = p.get("meta") or {}
        gap = m.get("gap_first") or m.get("gap") or 0
        b = "0-2" if gap < 2 else "2-3" if gap < 3 else "3-4" if gap < 4 else "4+"
        buckets[("gap " + b)].append(p["result"])
        buckets[("call " + str(m.get("call")))].append(p["result"])
    for k in sorted(buckets):
        print(f"  {k:16} {wl(buckets[k])}")
    print()
    tr = board.get("tracking") or {}
    for k in ("by_groups", "by_count", "system_vs_personnel", "personnel_by_gap", "personnel_by_call", "by_combo"):
        print(f"tracking.{k}:")
        for kk, v in (tr.get(k) or {}).items():
            print(f"    {kk:36} {v.get('w')}-{v.get('l')}-{v.get('p')}  units {v.get('units')}")
    print(f"tracking.conflicts: {tr.get('conflicts')}")
    print()
    print("=" * 100)
    print("6. HEALTH: order placer heartbeat logs and errors per day (ET)")
    print("=" * 100)
    logs, start = [], 0
    while True:      # the API returns 1,000 rows at a time
        chunk = st._req("GET", "/bet_log?ts=gte.2026-10-20&or=(level.eq.error,message.like.run%20(*)"
                               "&select=ts,level,message&order=ts.asc",
                        extra={"Range": f"{start}-{start + 999}"}) or []
        logs += chunk
        if len(chunk) < 1000:
            break
        start += 1000
    per = defaultdict(lambda: Counter())
    for r in logs:
        from datetime import datetime, timedelta
        d = (datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) - timedelta(hours=4)).date().isoformat()
        per[d]["logs"] += 1
        per[d]["runs"] += r["message"].startswith("run (")
        per[d]["errors"] += r["level"] == "error"
        per[d]["crashed"] += "crashed" in r["message"]
    for d in sorted(per):
        c = per[d]
        print(f"  {d}: {c['runs']} run summaries, {c['errors']} errors, {c['crashed']} crashes")
    errs = Counter(r["message"][:90] for r in logs if r["level"] == "error"
                   and r["ts"] >= "2026-10-24")
    print("  errors since 10/24, by kind:")
    for m, n in errs.most_common(12):
        print(f"    {n:5} × {m}")


def group_of(o):
    t = o.get("system") or ""
    try:
        sid = int(t[1:]) + {"S": 0, "T": 100, "E": 200, "X": 300}[t[0]]
        return group(sid)
    except Exception:
        return "?"


if __name__ == "__main__":
    main()
