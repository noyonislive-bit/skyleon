"""
Server-side video watch tracking.

The player sends heartbeats containing the time ranges the browser actually
played (HTMLMediaElement.played). The server merges them into the stored ranges
and computes coverage. A video only counts as watched when the merged coverage
reaches VIDEO_COMPLETION_THRESHOLD — clicking "complete" is not possible.

To stop crafted requests from faking a full watch, accepted coverage is capped twice:
  * per heartbeat: by the wall-clock time since the previous heartbeat (or, for the first
    one, since the video page was opened) at the maximum playback speed plus a small
    jitter tolerance, and
  * in total: by the wall-clock time since the video was first opened,
so firing many requests quickly cannot accumulate coverage. There is no up-front grace:
coverage can never run ahead of real time × MAX_PLAYBACK_RATE.
"""

from dataclasses import dataclass
from datetime import datetime

MAX_PLAYBACK_RATE = 2.0
JITTER_SECONDS = 2.0  # tolerance for network / timer jitter
MAX_RANGES = 200


Range = tuple[float, float]


def normalize_ranges(raw, duration: float) -> list[Range]:
    """Validate, clamp to [0, duration], drop junk, sort and merge."""
    result: list[Range] = []
    if not isinstance(raw, (list, tuple)):
        return result
    for item in raw[:MAX_RANGES]:
        try:
            start, end = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (start == start and end == end):  # NaN
            continue
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start >= 0.25:
            result.append((start, end))
    return merge_ranges(result)


def merge_ranges(ranges: list[Range], gap: float = 0.5) -> list[Range]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def total(ranges: list[Range]) -> float:
    return sum(e - s for s, e in ranges)


def subtract(new: list[Range], existing: list[Range]) -> list[Range]:
    """Parts of `new` not already covered by `existing` (both merged/sorted)."""
    out: list[Range] = []
    for s, e in new:
        cur = s
        for es, ee in existing:
            if ee <= cur or es >= e:
                continue
            if es > cur:
                out.append((cur, es))
            cur = max(cur, ee)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def trim_to_budget(ranges: list[Range], budget: float) -> list[Range]:
    out: list[Range] = []
    remaining = budget
    for s, e in ranges:
        if remaining <= 0:
            break
        length = e - s
        if length <= remaining:
            out.append((s, e))
            remaining -= length
        else:
            out.append((s, s + remaining))
            remaining = 0
    return out


@dataclass
class HeartbeatResult:
    ranges: list[Range]
    watched_seconds: float
    percent: float
    position: float
    completed: bool
    accepted_seconds: float


def apply_heartbeat(
    *,
    stored_ranges,
    duration: float,
    reported_ranges,
    position,
    last_heartbeat_at: datetime | None,
    now: datetime,
    threshold_percent: float,
    first_viewed_at: datetime | None = None,
) -> HeartbeatResult:
    duration = max(float(duration or 0), 0.0)
    existing = normalize_ranges(stored_ranges, duration) if duration else []
    try:
        pos = max(0.0, min(float(position or 0), duration or float(position or 0)))
    except (TypeError, ValueError):
        pos = 0.0

    if duration <= 0:
        return HeartbeatResult(existing, total(existing), 0.0, pos, False, 0.0)

    reported = normalize_ranges(reported_ranges, duration)
    fresh = subtract(reported, existing)

    since_first = max(0.0, (now - first_viewed_at).total_seconds()) if first_viewed_at is not None else 0.0
    if last_heartbeat_at is None:
        budget = (since_first + JITTER_SECONDS) * MAX_PLAYBACK_RATE
    else:
        elapsed = max(0.0, (now - last_heartbeat_at).total_seconds())
        budget = (elapsed + JITTER_SECONDS) * MAX_PLAYBACK_RATE
    # Absolute ceiling: total coverage can never exceed what could have been played since first view.
    if first_viewed_at is not None:
        ceiling = (since_first + JITTER_SECONDS) * MAX_PLAYBACK_RATE
        budget = max(0.0, min(budget, ceiling - total(existing)))
    accepted = trim_to_budget(fresh, budget)

    merged = merge_ranges(existing + accepted)
    watched = min(total(merged), duration)
    pct = round(min(100.0, watched / duration * 100.0), 2)
    return HeartbeatResult(
        ranges=[(round(s, 2), round(e, 2)) for s, e in merged],
        watched_seconds=round(watched, 2),
        percent=pct,
        position=pos,
        completed=pct >= threshold_percent,
        accepted_seconds=round(total(accepted), 2),
    )
