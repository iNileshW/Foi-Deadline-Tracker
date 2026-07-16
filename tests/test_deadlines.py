"""Tests for FOI deadline calculation.

Bank-holiday sets are hard-coded per year so the tests do not depend
on the GOV.UK API being reachable. Dates verified against the
GOV.UK bank-holidays JSON for england-and-wales.
"""

from datetime import date

import pytest

from deadlines import calculate_deadline

HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 6),   # Easter Monday
    date(2026, 5, 4),   # Early May bank holiday
    date(2026, 5, 25),  # Spring bank holiday
    date(2026, 8, 31),  # Summer bank holiday
    date(2026, 12, 25), # Christmas Day
    date(2026, 12, 28), # Boxing Day (substitute — 26 Dec 2026 is Sat)
}

HOLIDAYS_2025 = {
    date(2025, 1, 1),
    date(2025, 4, 18),  # Good Friday
    date(2025, 4, 21),  # Easter Monday
    date(2025, 5, 5),
    date(2025, 5, 26),
    date(2025, 8, 25),
    date(2025, 12, 25),
    date(2025, 12, 26),
}


def test_maundy_thursday_2026_scenario():
    """The statutory-breach scenario from the brief.

    Received Maundy Thursday 2026-04-02. Good Friday (Apr 3),
    Easter Monday (Apr 6) and Early May (May 4) must be skipped.
    Correct deadline is Tue 2026-05-05.
    """
    assert calculate_deadline(date(2026, 4, 2), HOLIDAYS_2026) == date(2026, 5, 5)


def test_maundy_thursday_vs_weekend_only_differs():
    """Regression guard against the old (weekend-only) behaviour.

    Ignoring bank holidays gave Thu 2026-04-30 — 3 working days
    earlier than the correct deadline.
    """
    weekend_only = calculate_deadline(date(2026, 4, 2), holidays=set())
    correct = calculate_deadline(date(2026, 4, 2), HOLIDAYS_2026)
    assert weekend_only == date(2026, 4, 30)
    assert correct == date(2026, 5, 5)
    assert correct > weekend_only


def test_no_holidays_in_window():
    """Received Fri 2026-07-03. Twenty clean working days → Fri 2026-07-31."""
    assert calculate_deadline(date(2026, 7, 3), HOLIDAYS_2026) == date(2026, 7, 31)


def test_received_on_weekend_clock_starts_monday():
    """Received Sat 2026-07-04. Should reach the same deadline as
    the following Sun 2026-07-05 or the prior Fri 2026-07-03 case
    ending Fri 2026-07-31."""
    assert calculate_deadline(date(2026, 7, 4), HOLIDAYS_2026) == date(2026, 7, 31)


def test_received_on_bank_holiday():
    """Received Good Friday 2026-04-03. Sat/Sun and Easter Monday
    are skipped; day 1 is Tue 2026-04-07. Deadline Tue 2026-05-05."""
    assert calculate_deadline(date(2026, 4, 3), HOLIDAYS_2026) == date(2026, 5, 5)


def test_christmas_window_2026():
    """Received Mon 2026-11-30. Christmas (Fri Dec 25) and Boxing
    Day substitute (Mon Dec 28) fall inside the window. Deadline
    Wed 2026-12-30."""
    assert calculate_deadline(date(2026, 11, 30), HOLIDAYS_2026) == date(2026, 12, 30)


def test_easter_2025():
    """Received Maundy Thursday 2025-04-17. Skip Good Fri Apr 18 and
    Easter Mon Apr 21 and Early May Mon May 5. Deadline Mon 2025-05-19."""
    # Trace:
    # Fri Apr 18 skip (Good Fri). Mon Apr 21 skip (Easter Mon).
    # Tue Apr 22=1, Wed 23=2, Thu 24=3, Fri 25=4,
    # Mon 28=5, Tue 29=6, Wed 30=7, Thu May 1=8, Fri May 2=9,
    # Mon May 5 skip (Early May), Tue May 6=10, Wed 7=11, Thu 8=12, Fri 9=13,
    # Mon 12=14, Tue 13=15, Wed 14=16, Thu 15=17, Fri 16=18,
    # Mon 19=19, Tue 20=20 → deadline Tue 2025-05-20.
    assert calculate_deadline(date(2025, 4, 17), HOLIDAYS_2025) == date(2025, 5, 20)


def test_ico_day_zero_rule():
    """The received date itself is never counted. Received Mon
    2026-06-01 (a working day). Day 1 is Tue 2026-06-02.
    Deadline is 20th working day = Mon 2026-06-29."""
    # Mon Jun 1 received. Jun 2..5=1..4. Jun 8..12=5..9. Jun 15..19=10..14.
    # Jun 22..26=15..19. Mon Jun 29=20.
    assert calculate_deadline(date(2026, 6, 1), HOLIDAYS_2026) == date(2026, 6, 29)


def test_deadline_is_always_a_working_day():
    """The returned deadline itself must be a working day —
    responding on a weekend or bank holiday is not compliant."""
    for start_offset in range(0, 60):
        received = date(2026, 3, 1) + \
            __import__("datetime").timedelta(days=start_offset)
        d = calculate_deadline(received, HOLIDAYS_2026)
        assert d.weekday() < 5
        assert d not in HOLIDAYS_2026


def test_holidays_none_uses_cached_file():
    """Smoke test: default path loads from cache without network."""
    # Should not raise; cache is committed in the repo.
    d = calculate_deadline(date(2026, 4, 2))
    assert d == date(2026, 5, 5)
