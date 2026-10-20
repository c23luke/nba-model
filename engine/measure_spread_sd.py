"""Measure how far NBA results land from the closing spread (2025-26 regular season, ESPN lines)."""
from __future__ import annotations
import math
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from . import sources

days = [date(2025, 10, 21) + timedelta(i) for i in range((date(2026, 4, 12) - date(2025, 10, 21)).days + 1)]
def one(d):
    try:
        return sources.espn_day(d)
    except Exception:
        return []
with ThreadPoolExecutor(8) as ex:
    allg = [x for day in ex.map(one, days) for x in day]
res = []
for g, ln in allg:
    if g.final and ln and ln.get("home_spread") is not None:
        res.append((g.home_score - g.away_score) + ln["home_spread"])   # >0 home covered
n = len(res)
mean = sum(res) / n
sd = math.sqrt(sum((r - mean) ** 2 for r in res) / (n - 1))
print(f"games with a line and a result: {n} (of {len(allg)})")
print(f"home margin minus spread: mean {mean:+.2f}, SD {sd:.2f}")
for k in (1, 2, 3, 4, 5, 6):
    big = [r for r in res if abs(r) > k]
    print(f"  result beat the spread by more than {k}: {len(big)/n:.1%}")
