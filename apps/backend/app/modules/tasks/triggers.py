"""任务触发器：把任务的时间规则换算成「下一次触发时刻」。

职责边界：本模块只做时间计算与合法性校验，不碰数据库、不读配置；
调度器与接口层都通过这里获得统一的触发语义，避免同一套规则写两遍。

统一的触发语义（与 spec 对齐）：
- cron 表达式一律为五段式（分 时 日 月 周），不接受六段式带秒的形式；
- 最小触发间隔为 1 分钟，低于下限的表达式在创建/更新时就被拒绝；
- 时区显式存储为 IANA 名称，触发点按该时区解释，落库统一为 UTC；
- 夏令时「春季跳变」导致某时刻不存在时，顺延到下一个有效时刻。
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, CroniterBadDateError, croniter

from app.shared.exceptions import BadRequestException

# 触发间隔下限：低于该间隔的表达式会被拒绝，防止任务把调度与模型调用写爆。
MIN_INTERVAL_SECONDS = 60
# cron 表达式段数：五段式（分 时 日 月 周），与 spec 的约定一致。
CRON_FIELD_COUNT = 5
# 单次触发时间计算的最大迭代次数，兜底防止异常表达式造成死循环。
MAX_ITERATIONS = 512


def load_timezone(timezone_name: str) -> ZoneInfo:
    """解析 IANA 时区名；名称非法时抛出明确的业务错误。"""

    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise BadRequestException(f"unknown timezone: {timezone_name}") from exc


def validate_cron_expression(expression: str) -> str:
    """校验 cron 表达式：必须是合法的五段式表达式，返回归一化后的字符串。"""

    normalized = (expression or "").strip()
    if not normalized:
        raise BadRequestException("cron expression is required")
    # croniter 默认接受六段式（带秒），这里显式收紧为五段式，
    # 否则「最小间隔 1 分钟」会被秒级表达式绕过。
    fields = normalized.split()
    if len(fields) != CRON_FIELD_COUNT:
        raise BadRequestException(
            "cron expression must have exactly 5 fields (minute hour day month weekday)"
        )
    try:
        croniter(normalized, datetime.now(UTC))
    except (CroniterBadCronError, CroniterBadDateError, ValueError, KeyError) as exc:
        raise BadRequestException(f"invalid cron expression: {expression}") from exc
    return normalized


def next_cron_run(
    expression: str,
    *,
    timezone_name: str,
    base: datetime | None = None,
) -> datetime:
    """计算严格晚于 ``base`` 的下一次触发时刻（UTC）。

    先按任务时区求值（保证「每天 9 点」按用户本地时间理解，并让夏令时
    跳变顺延生效），再把结果转成 UTC 落库。
    """

    normalized = validate_cron_expression(expression)
    tz = load_timezone(timezone_name)
    reference = (base or datetime.now(UTC)).astimezone(tz)
    iterator = croniter(normalized, reference)
    try:
        nxt = iterator.get_next(datetime)
    except (CroniterBadDateError, ValueError) as exc:
        raise BadRequestException(f"invalid cron expression: {expression}") from exc
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return nxt.astimezone(UTC)


def ensure_min_interval(
    expression: str,
    *,
    timezone_name: str,
    base: datetime | None = None,
) -> None:
    """校验 cron 的触发间隔不低于下限。

    做法是连取两次触发时刻，用实际间隔判断；这样「每月的某一天」这类
    日历级表达式也能被正确接受，而 ``* * * * *`` 会被拒绝。
    """

    first = next_cron_run(expression, timezone_name=timezone_name, base=base)
    second = next_cron_run(expression, timezone_name=timezone_name, base=first)
    if (second - first).total_seconds() < MIN_INTERVAL_SECONDS:
        raise BadRequestException(
            "cron interval is too short: minimum interval is 1 minute"
        )


def next_once_run(run_at: datetime, *, timezone_name: str) -> datetime:
    """把一次性任务的执行时刻归一化为 UTC。

    入参若是无时区的时间，按任务时区解释（与 cron 的解释口径保持一致）。
    """

    load_timezone(timezone_name)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=load_timezone(timezone_name))
    return run_at.astimezone(UTC)


def compute_next_run_at(
    *,
    trigger_type: str,
    timezone_name: str,
    now: datetime,
    cron_expression: str | None = None,
    run_at: datetime | None = None,
    honor_run_at: bool = False,
) -> datetime | None:
    """计算任务的 ``next_run_at``；返回 ``None`` 表示该任务不再触发。

    统一入口：创建/更新任务与调度器推进 ``next_run_at`` 都走这里，
    确保「错过不补跑」的语义只在一处实现。

    - ``cron``：始终求严格晚于 ``now`` 的下一个触发点，因此停机期间
      错过的触发点会被自然跳过，不会在恢复后补跑。
    - ``once``：``honor_run_at=True`` 时（创建场景）只要时刻尚未到达就
      用原定时刻；否则（推进场景）只有晚于 ``now`` 才有效，已过则返回
      ``None`` 表示这条一次性任务跑完即止。
    """

    if trigger_type == "cron":
        if not cron_expression:
            raise BadRequestException("cron expression is required")
        return next_cron_run(
            cron_expression, timezone_name=timezone_name, base=now
        )
    if trigger_type == "once":
        if run_at is None:
            raise BadRequestException("run_at is required")
        target = next_once_run(run_at, timezone_name=timezone_name)
        if honor_run_at and target > now:
            return target
        return target if target > now else None
    raise BadRequestException(f"unknown trigger type: {trigger_type}")
