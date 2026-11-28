"""Keeps the watcher running around the clock on the always-on server (Fly.io), in place of GitHub's hourly launches.

    python -m engine.serve

Starts `python -m engine.watch` (one ~55-minute launch: checks every minute, reruns the model on news and every
5 minutes, refreshes the injury desk once), and starts the next one the moment it ends. Each launch is its own
process, so a crash or a memory leak never outlives the hour. If launches keep failing it tells your phone once
(the same ntfy channel the bet alerts use) and keeps trying; it tells you again when it's back.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

FAILS_BEFORE_ALERT = 3      # launches in a row that crashed or ended early
SHORT_RUN = 120             # a launch that ends inside 2 minutes didn't do its job
MAX_WAIT = 300              # never wait more than 5 minutes between tries


def wait_after(fails: int) -> int:
    """Seconds to wait before the next launch: none after a good one, then 15, 30, 60 ... up to 5 minutes."""
    return 0 if fails <= 0 else min(MAX_WAIT, 15 * 2 ** (fails - 1))


def failed(code: int, seconds: float) -> bool:
    return code != 0 or seconds < SHORT_RUN


def tell(title: str, body: str, log) -> None:
    topic = "".join((os.environ.get("NTFY_TOPIC") or "").split())
    if not topic:
        try:
            from .store import get_store
            topic = get_store().get_config("ntfy_topic")
        except Exception as e:
            log(f"no alert channel: {e}")
            return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), method="POST",
                                     headers={"Title": title, "Tags": "warning", "Priority": "high"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log(f"alert failed: {e}")


def main(launch=None, sleep=time.sleep, rounds: int | None = None, alert=tell) -> None:
    log = lambda m: print(f"{datetime.now(timezone.utc):%H:%M:%S} serve: {m}", flush=True)
    launch = launch or (lambda: subprocess.run([sys.executable, "-m", "engine.watch"]).returncode)
    os.environ.setdefault("WATCH_NO_PULL", "1")        # no git checkout on the server; new code arrives by deploy
    fails, told, n = 0, False, 0
    while rounds is None or n < rounds:
        n += 1
        t0 = time.time()
        try:
            code = launch()
        except Exception as e:
            log(f"launch error: {e}")
            code = 1
        took = time.time() - t0
        if failed(code, took):
            fails += 1
            log(f"watcher ended badly (exit {code} after {took:.0f}s), {fails} in a row")
            if fails >= FAILS_BEFORE_ALERT and not told:
                alert("NBA watcher is DOWN", f"The watcher has failed {fails} times in a row on the server. "
                      "The board is not updating. Check the Fly logs.", log)
                told = True
        else:
            if told:
                alert("NBA watcher is back", "The watcher is running again.", log)
            fails, told = 0, False
        sleep(wait_after(fails))


if __name__ == "__main__":
    main()
