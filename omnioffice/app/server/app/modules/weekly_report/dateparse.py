"""日期时间归一化（V10 3.5）。

把识别出的各种原始写法统一转为 ISO8601（业务时区 Asia/Shanghai，不做时区转换）：
  2026/10/09、2026-10-09、10-09、10/9、10月9日、Oct 9、周四、261012(YYMMDD)
  + 时间区间「15:30 至 22:00」（结束只有时刻时继承开始日期）

规则（V10 3.5 原文）：
- 缺年份：以当前周报周期所在年份补全（不做跨年智能推断，疑似跨年靠越界高亮交人工）；
- 跨天任务：默认归属开始日期（strategy='start'），可配 end；
- 越界：落在周报周期（周一~周日）之外 → out_of_period=True 由校对界面高亮；
- 无法解析：抛 DateParseError，校对界面标红必填，绝不猜测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- 常量

WEEKDAY_CN = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
}
WEEKDAY_EN = {
    "mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2,
    "wed": 3, "weds": 3, "wednesday": 3, "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "fri": 5, "friday": 5, "sat": 6, "sat.": 6, "saturday": 6,
    "sun": 7, "sunday": 7,
}
MONTH_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# 15:30 / 15：30 / 9:05
_CLOCK_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})")
# 261012
_COMPACT_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
# 2026/10/09、2026-10-09、2026.10.9
_FULL_YMD_RE = re.compile(r"(?<!\d)(20\d{2})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})\s*日?")
# 10月9日 / 10 月 9 号
_CN_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
# 10-09 / 10/9（无年份；冒号是时刻分隔符天然不匹配；"00-18" 这类会被月份 1-12 校验拦掉）
_NUM_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
# Oct 9 / Oct. 9 / October 9
_EN_MD_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z.]*\s*\.?\s*(\d{1,2})(?!\d)",
    re.IGNORECASE,
)
# 周四 / 星期四 / 礼拜四
_CN_WEEK_RE = re.compile(r"(?:星期|礼拜|周)\s*([一二三四五六日天1-7])")
# Thu / Thursday
_EN_WEEK_RE = re.compile(
    r"\b(mon|tues?|wed(?:s)?|thu(?:rs?)?|fri|sat\.?|sun)(?:day)?\b", re.IGNORECASE
)


class DateParseError(ValueError):
    """无法解析的日期/时间；调用方应将该字段标记为待人工处理。"""


@dataclass
class NormalizedTime:
    start_at: str  # ISO8601：2026-10-08T15:30
    end_at: str    # 缺结束时刻时与 start 同日期、时间为空 → 给开始时刻（见 warnings）
    weekday: int   # 1=周一 … 7=周日（按归属策略日期）
    out_of_period: bool
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 日期解析


def _ymd(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError as e:
        raise DateParseError(f"非法日期 {y}-{m}-{d}：{e}") from None


def _weekday_date(wd: int, period_start: date) -> date:
    """相对星期 → 当前周报周期内对应日期（周一 + wd-1 天）。"""
    return period_start + timedelta(days=wd - 1)


def parse_date(text: str, period_start: date) -> date:  # noqa: C901 —— 多模式顺序匹配，可读性优先
    """从文本中解析日期。按「信息量从高到低」依次匹配，首个命中即返回。"""
    if not text or not text.strip():
        raise DateParseError("日期为空")
    s = text.strip()
    year = period_start.year

    m = _FULL_YMD_RE.search(s)
    if m:
        return _ymd(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _COMPACT_RE.search(s)
    if m:
        yy = int(m.group(1)[:2])
        # POSIX 风格世纪规则：<70 → 20YY；≥70 → 19YY
        full_year = 2000 + yy if yy < 70 else 1900 + yy
        mm = int(m.group(1)[2:4])
        dd = int(m.group(1)[4:6])
        return _ymd(full_year, mm, dd)

    m = _EN_MD_RE.search(s)
    if m:
        return _ymd(year, MONTH_EN[m.group(1).lower().rstrip(".")], int(m.group(2)))

    m = _CN_MD_RE.search(s)
    if m:
        return _ymd(year, int(m.group(1)), int(m.group(2)))

    # 中文/英文星期（在纯数字月日前匹配，避免「周四」被其他规则吞掉）
    m = _CN_WEEK_RE.search(s)
    if m:
        token = m.group(1)
        if token in WEEKDAY_CN:
            return _weekday_date(WEEKDAY_CN[token], period_start)

    m = _EN_WEEK_RE.search(s)
    if m:
        key = m.group(1).lower().rstrip(".")
        if key in WEEKDAY_EN:
            return _weekday_date(WEEKDAY_EN[key], period_start)

    m = _NUM_MD_RE.search(s)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            return _ymd(year, mm, dd)

    raise DateParseError(f"无法解析日期：{text!r}")


# ---------------------------------------------------------------- 时间区间


def _clocks(text: str) -> list[tuple[int, int]]:
    out = []
    for m in _CLOCK_RE.finditer(text):
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            out.append((h, mi))
    return out


def parse_range(text: str, period_start: date) -> tuple[datetime, datetime | None, list[str]]:
    """解析「日期 + 起止时刻」文本，返回 (开始时间, 结束时间|None, warnings)。

    不预拆区间：直接在全文按出现顺序提取时刻——第一个为开始、第二个为结束，
    规避「10-09 09:00-18:00」中日期连字符被误判为区间分隔的问题。
    """
    warnings: list[str] = []
    start_date = parse_date(text, period_start)
    clocks = _clocks(text)
    if not clocks:
        raise DateParseError(f"未找到开始时刻：{text!r}")

    h, mi = clocks[0]
    start_dt = datetime.combine(start_date, datetime.min.time()).replace(hour=h, minute=mi)
    end_dt = None
    if len(clocks) >= 2:
        eh, em = clocks[1]
        end_dt = datetime.combine(start_date, datetime.min.time()).replace(hour=eh, minute=em)
        if end_dt < start_dt:
            # 结束时刻早于开始时刻 → 跨到次日
            end_dt += timedelta(days=1)
            warnings.append("END_NEXT_DAY")
    else:
        warnings.append("END_TIME_MISSING")
    return start_dt, end_dt, warnings


# ---------------------------------------------------------------- 对外主入口


def normalize_task(
    start_raw: str,
    end_raw: str = "",
    *,
    period_start: str,
    strategy: str = "start",
) -> NormalizedTime:
    """归一化单条任务的时间。

    start_raw / end_raw 为识别原文；end_raw 为空时在 start_raw 内寻找区间
    （「10月8日 15:30 至 22:00」这类只有一段文本的常见截图写法）。
    period_start: 周报周一日期 YYYY-MM-DD。
    strategy: 跨天任务归属 start（默认，V10）/end。
    """
    try:
        ps = date.fromisoformat(period_start)
    except ValueError as e:
        raise DateParseError(f"period_start 必须为 YYYY-MM-DD：{period_start!r}") from e
    period_end = ps + timedelta(days=6)

    warnings: list[str] = []
    start_dt: datetime
    end_dt: datetime | None

    if end_raw and end_raw.strip():
        # 起止分开给：开始段必须有日期；结束段没日期就继承开始日期（V10 3.5）
        start_date = parse_date(start_raw, ps)
        start_clocks = _clocks(start_raw)
        if not start_clocks:
            raise DateParseError(f"开始时间缺时刻：{start_raw!r}")
        h, mi = start_clocks[0]
        start_dt = datetime.combine(start_date, datetime.min.time()).replace(hour=h, minute=mi)

        end_clocks = _clocks(end_raw)
        end_date: date
        try:
            end_date = parse_date(end_raw, ps)
            warnings.append("END_DATE_PARSED")
        except DateParseError:
            # 结束只有时刻 → 继承开始日期
            end_date = start_date
            warnings.append("END_DATE_INHERITED")
        if not end_clocks:
            raise DateParseError(f"结束时间缺时刻：{end_raw!r}")
        eh, em = end_clocks[0]
        end_dt = datetime.combine(end_date, datetime.min.time()).replace(hour=eh, minute=em)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
            if "END_DATE_INHERITED" in warnings:
                warnings.append("END_NEXT_DAY")
    else:
        start_dt, end_dt, w = parse_range(start_raw, ps)
        warnings.extend(w)

    anchor = start_dt.date() if strategy == "start" else (end_dt.date() if end_dt else start_dt.date())
    out_of_period = not (ps <= anchor <= period_end)
    if out_of_period:
        warnings.append("OUT_OF_PERIOD")

    return NormalizedTime(
        start_at=start_dt.isoformat(timespec="minutes"),
        end_at=(end_dt.isoformat(timespec="minutes") if end_dt else start_dt.isoformat(timespec="minutes")),
        weekday=anchor.isoweekday(),
        out_of_period=out_of_period,
        warnings=sorted(set(warnings)),
    )
