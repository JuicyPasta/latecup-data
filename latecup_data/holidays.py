"""The manifest's `holidays`: dates on which hours may differ.

US federal holidays on their actual dates (not the observed weekday), plus
Thanksgiving eve, Christmas Eve and New Year's Eve. The app shows a banner on
these dates; nobody guesses holiday hours.
"""
from datetime import date, timedelta


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def for_year(year):
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    return [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Presidents' Day"),
        (_last_weekday(year, 5, 0), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day / Indigenous Peoples' Day"),
        (date(year, 11, 11), "Veterans Day"),
        (thanksgiving - timedelta(days=1), "Thanksgiving Eve"),
        (thanksgiving, "Thanksgiving"),
        (date(year, 12, 24), "Christmas Eve"),
        (date(year, 12, 25), "Christmas Day"),
        (date(year, 12, 31), "New Year's Eve"),
    ]


def upcoming(today, months=13):
    """[{date, name}] from `today` through `months` months ahead, in order."""
    m = today.month - 1 + months
    y, mo = today.year + m // 12, m % 12 + 1
    last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).day
    end = date(y, mo, min(today.day, last))
    out = []
    for year in range(today.year, end.year + 1):
        for d, name in for_year(year):
            if today <= d <= end:
                out.append({"date": d.isoformat(), "name": name})
    return sorted(out, key=lambda h: h["date"])
