"""Fiscal periods resolved from visible column headings, not numeric fact values."""
from datetime import date, datetime
import re
from .accounting import CALENDARS


def period_identity(period):
    return tuple(period.get(key) for key in (
        "start_date", "end_date", "duration", "duration_days", "fiscal_year", "period_type"))


def make_period(start, end, months, fiscal_year, period_type):
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return {"id": f"{start}/{end}/{period_type}", "start_date": start, "end_date": end,
            "duration": f"P{months}M", "duration_days": days,
            "fiscal_year": fiscal_year, "period_type": period_type}


def resolve_period(header, document):
    """Reject incomplete/unknown headings instead of guessing from column order."""
    years = re.findall(r"\b20\d{2}\b", header)
    if len(set(years)) != 1:
        raise ValueError(f"Expected one calendar year in period header: {header!r}")
    year = int(years[0])
    calendar = CALENDARS.get(document["company"])
    if calendar and document["form"] == "10-K":
        if calendar["header"] not in header:
            raise ValueError(f"Unsupported calendar header: {header!r}")
        return make_period(f"{year}-{calendar['start_month_day']}", f"{year}-{calendar['end_month_day']}", 12, year, "annual")
    if document["company"] == "Walmart":
        if document["form"] == "10-Q":
            match = re.search(r"(Three|Nine) Months Ended October 31,", header)
            if not match:
                raise ValueError(f"Unsupported quarterly period header: {header!r}")
            months = 3 if match[1] == "Three" else 9
            return make_period(f"{year}-{'08' if months == 3 else '02'}-01",
                               f"{year}-10-31", months, year + 1,
                               "quarter" if months == 3 else "year_to_date")
        if "January 31" not in header:
            raise ValueError(f"Unsupported annual period header: {header!r}")
        return make_period(f"{year-1}-02-01", f"{year}-01-31", 12, year, "annual")
    if document["company"] == "Apple" and document["form"] == "10-K":
        starts = {2025: "2024-09-29", 2024: "2023-10-01", 2023: "2022-09-25"}
        match = re.search(r"September \d{1,2}, 20\d{2}", header)
        if not match or year not in starts:
            raise ValueError(f"Unsupported Apple annual header: {header!r}")
        end = datetime.strptime(match[0], "%B %d, %Y").date().isoformat()
        return make_period(starts[year], end, 12, year, "annual")
    raise ValueError(f"Unsupported document: {document['id']}")
