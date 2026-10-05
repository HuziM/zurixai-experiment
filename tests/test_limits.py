"""Reading usage-limit reset times, and how long the loop waits."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness.limits import latest_reset, reset_time
from harness.loop import RESET_MARGIN_S, SHORT_WAIT_S, sleep_until, wait_seconds

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)  # a Monday


@pytest.mark.parametrize(("text", "expected"), [
    ("Claude AI usage limit reached|1791108000", datetime.fromtimestamp(1791108000, UTC)),
    ("5-hour limit reached ∙ resets 3pm", datetime(2026, 10, 5, 15, 0, tzinfo=UTC)),
    ("You've hit your limit · resets 9am", datetime(2026, 10, 6, 9, 0, tzinfo=UTC)),
    ("limit reached, resets at 15:30", datetime(2026, 10, 5, 15, 30, tzinfo=UTC)),
    ("resets 3:30pm (Asia/Karachi)", datetime(2026, 10, 5, 10, 30, tzinfo=UTC)),
    ("Weekly limit reached · resets Oct 9, 9am", datetime(2026, 10, 9, 9, 0, tzinfo=UTC)),
    ("Weekly limit reached · resets Thu 9am", datetime(2026, 10, 8, 9, 0, tzinfo=UTC)),
    ("resets at 2026-10-05T14:00:00Z", datetime(2026, 10, 5, 14, 0, tzinfo=UTC)),
    ("resets 12am", datetime(2026, 10, 6, 0, 0, tzinfo=UTC)),
])
def test_reset_time_formats(text, expected) -> None:
    assert reset_time(text, NOW) == expected


@pytest.mark.parametrize("text", ["", "Fable 5.1 requires usage credits.", "rate limited, try later"])
def test_unreadable_messages_give_none(text) -> None:
    assert reset_time(text, NOW) is None


def test_latest_reset_takes_the_last_future_one() -> None:
    assert latest_reset(["resets 1pm", "resets 2pm", "resets at 2026-10-05T08:00:00Z"], NOW) == \
        datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


def _limited_run(out: Path, run_id: str, message: str) -> None:
    (out / run_id).mkdir(parents=True)
    (out / run_id / "meta.json").write_text(json.dumps(
        {"status": "infra_failed", "api_error_status": 429, "error_message": message}))


def test_wait_until_the_reset_plus_margin(tmp_path: Path) -> None:
    _limited_run(tmp_path, "a", "5-hour limit reached ∙ resets 3pm")
    seconds, why = wait_seconds(tmp_path, ["a"], True, 5.5, NOW)
    assert seconds == timedelta(hours=5).total_seconds() + RESET_MARGIN_S
    assert "15:00 UTC" in why


def test_unreadable_message_falls_back_to_fixed_wait(tmp_path: Path) -> None:
    _limited_run(tmp_path, "a", "rate limited")
    seconds, why = wait_seconds(tmp_path, ["a"], True, 5.5, NOW)
    assert seconds == 5.5 * 3600 and "rate limited" in why


def test_no_limit_stop_means_short_pause(tmp_path: Path) -> None:
    assert wait_seconds(tmp_path, ["a"], False, 5.5, NOW)[0] == SHORT_WAIT_S


def test_sleep_until_follows_the_wall_clock_through_a_machine_sleep() -> None:
    clock = {"t": NOW}
    naps = []

    def fake_sleep(seconds: float) -> None:
        naps.append(seconds)
        # The machine sleeps for 2 hours during the first nap: wall time jumps ahead.
        clock["t"] += timedelta(seconds=seconds) + (timedelta(hours=2) if len(naps) == 1 else timedelta())

    sleep_until(NOW + timedelta(hours=1), now=lambda: clock["t"], sleep=fake_sleep)
    assert naps == [60]
