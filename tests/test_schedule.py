from datetime import UTC, datetime

from edgecraft.schedule import (
    SESSION_EU,
    SESSION_OFFHOURS,
    SESSION_US_CLOSE,
    SESSION_US_OPEN,
    scheduled_cycle_key,
    scheduled_input_path,
    scheduled_slot,
)


def test_scheduled_slots_cover_weekday_and_offhours() -> None:
    assert scheduled_slot(datetime(2026, 8, 25, 13, 0, tzinfo=UTC)) == SESSION_EU
    assert scheduled_slot(datetime(2026, 8, 25, 16, 0, tzinfo=UTC)) == SESSION_US_OPEN
    assert scheduled_slot(datetime(2026, 8, 25, 18, 59, tzinfo=UTC)) == SESSION_US_OPEN
    assert scheduled_slot(datetime(2026, 8, 25, 19, 0, tzinfo=UTC)) == SESSION_US_CLOSE
    assert scheduled_slot(datetime(2026, 8, 25, 23, 0, tzinfo=UTC)) == SESSION_OFFHOURS
    assert scheduled_slot(datetime(2026, 8, 25, 8, 30, tzinfo=UTC)) == SESSION_OFFHOURS


def test_scheduled_cycle_key_and_input_path_use_utc_date_and_slot() -> None:
    now = datetime(2026, 8, 25, 17, 18, 30, tzinfo=UTC)
    assert scheduled_cycle_key(now) == "2026-08-25-session-us-open"
    assert scheduled_input_path(now) == "state/fund-inputs/2026-08-25-session-us-open.json"


def test_pacific_close_scan_has_its_own_key_before_market_close_in_both_seasons() -> None:
    from zoneinfo import ZoneInfo

    from edgecraft.monitor import stock_market_is_open

    pacific = ZoneInfo("America/Los_Angeles")
    for month in (1, 7):
        open_scan = datetime(2026, month, 6, 10, 15, tzinfo=pacific)
        close_scan = datetime(2026, month, 6, 12, 15, tzinfo=pacific)
        assert stock_market_is_open(close_scan)
        assert scheduled_slot(open_scan) == SESSION_US_OPEN
        assert scheduled_slot(close_scan) == SESSION_US_CLOSE
        assert scheduled_cycle_key(open_scan) != scheduled_cycle_key(close_scan)
