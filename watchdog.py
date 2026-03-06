"""
watchdog.py — Process watchdog that restarts the bot if it crashes.

Run this instead of running the bot directly when deploying on a server.
It monitors the bot process and restarts it automatically on failure.

Usage:
  python watchdog.py grid BTCUSDT --lower 60000 --upper 70000 --grids 10 --qty 0.001
"""

from __future__ import annotations

import subprocess
import sys
import time
import os

from logger import get_logger
from utils import send_telegram_alert

log = get_logger("watchdog")

MAX_RESTARTS = 10           # Give up after this many consecutive crashes
RESTART_DELAY = 10          # Seconds to wait before restarting
CRASH_WINDOW = 60           # Seconds — if bot crashes within this window, count as crash
MIN_UPTIME = 30             # Seconds — if uptime < this it is considered an instant crash


def run_watchdog(bot_args: list) -> None:
    """
    Launch the bot as a subprocess and restart it on failure.

    bot_args: list of arguments to pass to grid_runner.py
    """
    restarts = 0
    consecutive_crashes = 0

    log.info(f"Watchdog started | command: python grid_runner.py {' '.join(bot_args)}")
    send_telegram_alert(f"Watchdog started\nCommand: {' '.join(bot_args)}")

    while True:
        start_time = time.time()
        log.info(f"Starting bot (restart #{restarts})...")

        try:
            proc = subprocess.run(
                [sys.executable, "grid_runner.py"] + bot_args,
                check=False,
            )
            exit_code = proc.returncode

        except Exception as exc:
            log.error(f"Failed to start bot process: {exc}")
            exit_code = -1

        uptime = time.time() - start_time
        restarts += 1

        # If exit code 0 it was a clean shutdown — do not restart
        if exit_code == 0:
            log.info("Bot exited cleanly. Watchdog stopping.")
            send_telegram_alert("Bot exited cleanly. Watchdog stopped.")
            break

        # Track consecutive crashes
        if uptime < MIN_UPTIME:
            consecutive_crashes += 1
            log.warning(
                f"Bot crashed after {uptime:.1f}s (exit code {exit_code}). "
                f"Consecutive crashes: {consecutive_crashes}/{MAX_RESTARTS}"
            )
        else:
            consecutive_crashes = 0  # Reset if it ran for a while

        if consecutive_crashes >= MAX_RESTARTS:
            msg = f"Bot crashed {MAX_RESTARTS} times consecutively. Watchdog giving up."
            log.error(msg)
            send_telegram_alert(f"CRITICAL: {msg}")
            break

        msg = (
            f"Bot crashed (exit {exit_code}, uptime {uptime:.0f}s). "
            f"Restarting in {RESTART_DELAY}s... ({restarts} restarts total)"
        )
        log.warning(msg)
        send_telegram_alert(f"Bot restarting\n{msg}")
        time.sleep(RESTART_DELAY)

    log.info("Watchdog exiting.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python watchdog.py <grid_runner args>")
        print("Example: python watchdog.py BTCUSDT --lower 60000 --upper 70000 --grids 10 --qty 0.001")
        sys.exit(1)
    run_watchdog(args)
