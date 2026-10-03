"""
Scoring of a practice segmentation against the trainer's reference.

score = 50% boundary F1 (start/end points within the tolerance)
      + 30% mean IoU of each reference clip with its best-matching clip
      + 20% coverage of the "hands present" range
Without a reference segmentation, the score is the coverage only.
"""

Clip = tuple[float, float]


def clean_clips(raw, lo: float, hi: float, limit: int = 500) -> list[Clip]:
    clips: list[Clip] = []
    if not isinstance(raw, (list, tuple)):
        return clips
    for item in raw[:limit]:
        try:
            s, e = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if s != s or e != e:  # NaN
            continue
        if e < s:
            s, e = e, s
        s, e = max(lo, min(s, hi)), max(lo, min(e, hi))
        if e - s >= 0.05:
            clips.append((round(s, 3), round(e, 3)))
    return sorted(clips)


def union(clips: list[Clip]) -> list[Clip]:
    out: list[Clip] = []
    for s, e in sorted(clips):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def uncovered(clips: list[Clip], lo: float, hi: float) -> list[Clip]:
    gaps, cur = [], lo
    for s, e in union(clips):
        if s > cur:
            gaps.append((cur, min(s, hi)))
        cur = max(cur, e)
    if cur < hi:
        gaps.append((cur, hi))
    return [(s, e) for s, e in gaps if e - s > 0.05]


def iou(a: Clip, b: Clip) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    uni = max(a[1], b[1]) - min(a[0], b[0])
    return inter / uni if uni > 0 else 0.0


def boundaries(clips: list[Clip]) -> list[float]:
    pts = sorted({round(p, 3) for c in clips for p in c})
    return pts


def match_boundaries(ref: list[float], usr: list[float], tol: float):
    """Greedy nearest matching. Returns (matched pairs, unmatched ref, unmatched usr)."""
    candidates = sorted(
        ((abs(r - u), i, j) for i, r in enumerate(ref) for j, u in enumerate(usr) if abs(r - u) <= tol)
    )
    used_r, used_u, pairs = set(), set(), []
    for d, i, j in candidates:
        if i in used_r or j in used_u:
            continue
        used_r.add(i)
        used_u.add(j)
        pairs.append((ref[i], usr[j]))
    return pairs, [r for i, r in enumerate(ref) if i not in used_r], [u for j, u in enumerate(usr) if j not in used_u]


def fmt(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def score_attempt(user_clips: list[Clip], ref_clips: list[Clip], lo: float, hi: float, tol: float) -> dict:
    span = max(hi - lo, 0.001)
    covered = sum(e - s for s, e in union(user_clips))
    coverage = min(1.0, covered / span)
    gaps = uncovered(user_clips, lo, hi)
    issues: list[dict] = []

    overlaps = [(a, b) for a, b in zip(user_clips, user_clips[1:]) if b[0] < a[1] - 1e-6]
    for a, b in overlaps[:10]:
        issues.append({"kind": "overlap", "text": f"Clips overlap between {fmt(b[0])} and {fmt(min(a[1], b[1]))}."})
    for s, e in gaps[:10]:
        if e - s >= tol:
            issues.append({"kind": "uncovered", "text": f"Hands-present time not covered: {fmt(s)} – {fmt(e)}."})

    result = {
        "coverage": round(coverage * 100, 1),
        "clip_count": len(user_clips),
        "reference_count": len(ref_clips),
        "uncovered": [[round(s, 2), round(e, 2)] for s, e in gaps],
    }
    if not ref_clips:
        result.update(score=round(coverage * 100, 1), boundary_f1=None, mean_iou=None, issues=issues)
        return result

    ref_b, usr_b = boundaries(ref_clips), boundaries(user_clips)
    pairs, missed_b, extra_b = match_boundaries(ref_b, usr_b, tol)
    precision = len(pairs) / len(usr_b) if usr_b else 0.0
    recall = len(pairs) / len(ref_b) if ref_b else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    best = []
    for idx, r in enumerate(ref_clips, start=1):
        scored = sorted(((iou(r, u), u) for u in user_clips), reverse=True)
        best_iou, best_clip = scored[0] if scored else (0.0, None)
        best.append(best_iou)
        if best_iou < 0.5:
            issues.append({"kind": "missed", "text": f"Reference clip {idx} ({fmt(r[0])} – {fmt(r[1])}) has no matching clip."})
        elif best_clip:
            ds, de = best_clip[0] - r[0], best_clip[1] - r[1]
            if abs(ds) > tol:
                issues.append({"kind": "boundary", "text": f"Clip for reference {idx} starts {abs(ds):.2f}s {'late' if ds > 0 else 'early'}."})
            if abs(de) > tol:
                issues.append({"kind": "boundary", "text": f"Clip for reference {idx} ends {abs(de):.2f}s {'late' if de > 0 else 'early'}."})
    mean_iou = sum(best) / len(best) if best else 0.0
    extra_clips = [u for u in user_clips if max((iou(u, r) for r in ref_clips), default=0) < 0.3]
    for u in extra_clips[:10]:
        issues.append({"kind": "extra", "text": f"Extra clip {fmt(u[0])} – {fmt(u[1])} does not match any reference action."})

    score = 100 * (0.5 * f1 + 0.3 * mean_iou + 0.2 * coverage)
    result.update(
        score=round(score, 1),
        boundary_f1=round(f1 * 100, 1),
        boundary_precision=round(precision * 100, 1),
        boundary_recall=round(recall * 100, 1),
        mean_iou=round(mean_iou * 100, 1),
        matched_boundaries=len(pairs),
        missed_boundaries=len(missed_b),
        extra_boundaries=len(extra_b),
        mean_boundary_error=round(sum(abs(r - u) for r, u in pairs) / len(pairs), 3) if pairs else None,
        issues=issues,
    )
    return result
