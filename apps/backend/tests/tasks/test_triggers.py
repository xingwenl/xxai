"""任务触发器单元测试：cron 求值、最小间隔、时区与一次性任务语义。"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.tasks.triggers import (
    compute_next_run_at,
    ensure_min_interval,
    load_timezone,
    next_cron_run,
    next_once_run,
    validate_cron_expression,
)
from app.shared.exceptions import BadRequestException


def test_next_cron_run_uses_task_timezone() -> None:
    """「每天 9 点」必须按任务时区解释，而不是服务端本地时区。"""

    base = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)  # 北京时间 08:00
    nxt = next_cron_run("0 9 * * *", timezone_name="Asia/Shanghai", base=base)
    assert nxt.tzinfo is not None
    # 北京时间 09:00 == UTC 01:00
    assert nxt.astimezone(UTC) == datetime(2026, 9, 19, 1, 0, tzinfo=UTC)


def test_next_cron_run_is_strictly_after_base() -> None:
    """恰好落在触发点上的基准时间必须返回「下一个」触发点，避免原地重复触发。"""

    base = datetime(2026, 9, 19, 1, 0, tzinfo=UTC)  # 正好是 09:00 Asia/Shanghai
    nxt = next_cron_run("0 9 * * *", timezone_name="Asia/Shanghai", base=base)
    assert nxt == datetime(2026, 9, 20, 1, 0, tzinfo=UTC)


def test_next_cron_run_handles_dst_spring_forward() -> None:
    """夏令时春季跳变导致 02:30 不存在时，触发点顺延到跳变后的第一个有效时刻。

    croniter 会把不存在的本地时刻归一化到时钟跳变的瞬间（03:00 EDT），
    即该次触发不会被丢弃，只是被推迟到跳变后的第一个有效时刻。
    """

    base = datetime(2026, 3, 8, 1, 30, tzinfo=UTC)
    nxt = next_cron_run("30 2 * * *", timezone_name="America/New_York", base=base)
    assert nxt == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    # 落到跳变后的第一个有效本地时刻，且不是「跳过到第二天」
    assert nxt.astimezone(ZoneInfo("America/New_York")).hour == 3


def test_next_cron_run_normal_day_after_dst() -> None:
    """跳变次日恢复正常：仍然按任务时区的 02:30 触发。"""

    base = datetime(2026, 3, 9, 0, 0, tzinfo=UTC)
    nxt = next_cron_run("30 2 * * *", timezone_name="America/New_York", base=base)
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (2, 30)


def test_min_interval_rejects_every_minute_expression() -> None:
    """``* * * * *`` 的间隔为 1 分钟，处于下限，应被接受。"""

    ensure_min_interval("* * * * *", timezone_name="Asia/Shanghai")


def test_validate_rejects_six_field_expression() -> None:
    """六段式带秒的表达式必须被拒绝，否则秒级规则会绕过最小间隔下限。"""

    with pytest.raises(BadRequestException):
        validate_cron_expression("*/10 * * * * *")


def test_validate_rejects_bad_expressions() -> None:
    for bad in ["", "99 * * * *", "x", "* * * *", "0 25 * * *"]:
        with pytest.raises(BadRequestException):
            validate_cron_expression(bad)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(BadRequestException):
        load_timezone("Not/AZone")
    with pytest.raises(BadRequestException):
        next_cron_run("0 9 * * *", timezone_name="Not/AZone")


def test_next_once_run_interprets_naive_time_in_task_timezone() -> None:
    """无时区的一次性时刻按任务时区解释，与 cron 口径一致。"""

    result = next_once_run(
        datetime(2026, 9, 19, 9, 0), timezone_name="Asia/Shanghai"
    )
    assert result == datetime(2026, 9, 19, 1, 0, tzinfo=UTC)


def test_compute_next_run_at_cron_skips_missed_points() -> None:
    """停机期间错过的触发点不补跑：永远取严格晚于 now 的下一个点。"""

    now = datetime(2026, 9, 19, 10, 30, tzinfo=UTC)
    nxt = compute_next_run_at(
        trigger_type="cron",
        timezone_name="UTC",
        now=now,
        cron_expression="0 * * * *",
    )
    assert nxt == datetime(2026, 9, 19, 11, 0, tzinfo=UTC)


def test_compute_next_run_at_once_creation_honors_future_run_at() -> None:
    """创建场景：未来的时刻应原样保留，而不是顺延到下一个周期。"""

    now = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    nxt = compute_next_run_at(
        trigger_type="once",
        timezone_name="UTC",
        now=now,
        run_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
        honor_run_at=True,
    )
    assert nxt == datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def test_compute_next_run_at_once_is_exhausted_after_run() -> None:
    """推进场景：已过时刻的一次性任务返回 None，表示跑完即止。"""

    now = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    nxt = compute_next_run_at(
        trigger_type="once",
        timezone_name="UTC",
        now=now,
        run_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    assert nxt is None


def test_compute_next_run_at_rejects_unknown_trigger_type() -> None:
    with pytest.raises(BadRequestException):
        compute_next_run_at(
            trigger_type="event", timezone_name="UTC", now=datetime.now(UTC)
        )


def test_compute_next_run_at_requires_expression_and_run_at() -> None:
    with pytest.raises(BadRequestException):
        compute_next_run_at(
            trigger_type="cron", timezone_name="UTC", now=datetime.now(UTC)
        )
    with pytest.raises(BadRequestException):
        compute_next_run_at(
            trigger_type="once", timezone_name="UTC", now=datetime.now(UTC)
        )
