"""FOI statutory deadline calculation.

FOIA s10(1): a public authority must comply within 20 working days
following the date of receipt.

FOIA s10(6) / ICO guidance: a "working day" is any day other than
Saturday, Sunday, Christmas Day, Good Friday, or a bank holiday
in any part of the UK. We use the England & Wales bank-holiday list
published by GOV.UK.

The count starts on the working day after receipt. The deadline
is the 20th such working day.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BANK_HOLIDAYS_URL = "https://www.gov.uk/bank-holidays.json"
CACHE_PATH = Path(__file__).parent / "bank_holidays.json"
DIVISION = "england-and-wales"


def load_bank_holidays(refresh: bool = False) -> set[date]:
    """Return the set of England & Wales bank-holiday dates.

    Reads the cached JSON file next to this module. If refresh=True or
    the cache is missing, fetch from GOV.UK and rewrite the cache.
    """
    if refresh or not CACHE_PATH.exists():
        # URL is a hardcoded https constant, not user input.
        with urllib.request.urlopen(BANK_HOLIDAYS_URL, timeout=10) as resp:  # nosec B310
            payload = json.load(resp)
        CACHE_PATH.write_text(json.dumps(payload, indent=2))
    else:
        payload = json.loads(CACHE_PATH.read_text())
    return {date.fromisoformat(e["date"]) for e in payload[DIVISION]["events"]}


def calculate_deadline(received: date, holidays: set[date] | None = None) -> date:
    """Return the 20th working day after `received`.

    A working day is Mon-Fri and not in `holidays`. Pass `holidays`
    explicitly in tests; production callers can omit it and the
    cached GOV.UK list is used.
    """
    if holidays is None:
        holidays = load_bank_holidays()
    current = received
    added = 0
    while added < 20:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays:
            added += 1
    return current
