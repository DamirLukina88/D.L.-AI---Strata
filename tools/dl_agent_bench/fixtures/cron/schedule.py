"""When does a cron job run next."""
from datetime import datetime


def next_run(expr: str, after: datetime) -> datetime:
    """The first minute strictly after `after` that matches the 5-field cron expression `expr`
    (minute hour day-of-month month day-of-week; day-of-week 0-6 with 0 = Sunday).

    Each field is *, a number, a range a-b, a list a,b,c, or a step */n or a-b/n.  As in cron, when both
    day-of-month and day-of-week are restricted (not *), a day matches if either one matches.  Seconds of
    `after` are ignored.  A malformed expression or an out-of-range value raises ValueError.
    """
    raise NotImplementedError
