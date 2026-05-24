# Daily batch logging configuration for MyNews Radio.
#
# Produces a single daily log file at data/logs/YYYY-MM-DD.log shared
# by every batch script so that cron output and Python logs land in one place.

import datetime as dt
import logging
import os
import sys


LOG_DIR = os.environ.get("BATCH_LOG_DIR", os.path.join("data", "logs"))

# When multiple scripts open the same file concurrently (cron piping + Python),
# use a per-process FileHandler whose filename follows YYYY-MM-DD rotation.
_DATE_STR = dt.date.today().isoformat()


def setup_daily_logging(name: str, level: int = logging.INFO) -> None:
    """Set up logging with console + daily-file handlers for *name*.

    The log file is ``data/logs/YYYY-MM-DD.log`` and all batch scripts share it.

    This function calls `logging.basicConfig` under the hood — call it exactly
    once at each entry point (run_daily.py, orchestrate.py).  Later invocations
    are no-ops so the root logger configuration cannot be accidentally overwritten.

    Parameters
    ----------
    name : str
        Logger module name used for identification (e.g. ``__name__``).
    level : int
        Minimum log level (default INFO).
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    filepath = os.path.join(LOG_DIR, f"{_DATE_STR}.log")

    # Prevent duplicate handlers on repeated calls.
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler = logging.FileHandler(filepath, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_log_file_path() -> str:
    return os.path.join(LOG_DIR, f"{_DATE_STR}.log")
