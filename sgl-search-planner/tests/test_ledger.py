from datetime import datetime, timedelta, timezone

from sgl_search.ledger import independent_visit_count


def test_independent_visit_count_respects_cadence():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = [t0, t0 + timedelta(days=1), t0 + timedelta(days=8)]
    assert independent_visit_count(times, min_separation_days=7) == 2
    assert independent_visit_count(times, min_separation_days=0) == 3
