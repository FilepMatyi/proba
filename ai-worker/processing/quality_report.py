import math


def _bounded_score(value, fallback=100):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(score):
        return fallback
    return round(max(0, min(100, score)))


def segmentation_quality_report(metrics, base_quality_score=None):
    """Build an actionable framing/segmentation report for a 360 image set."""
    valid_metrics = [item for item in metrics if isinstance(item, dict)]
    if not valid_metrics:
        return _bounded_score(base_quality_score), [], {'segmentation': {}}

    frame_count = len(valid_metrics)
    edge_frames = sum(bool(item.get('touchesEdge')) for item in valid_metrics)
    small_frames = sum(item.get('bboxWidthRatio', 0) < 0.32 for item in valid_metrics)
    full_width_frames = sum(item.get('bboxWidthRatio', 0) >= 0.98 for item in valid_metrics)
    target_lock_frames = sum(bool(item.get('targetLockApplied')) for item in valid_metrics)
    edge_ratio = edge_frames / frame_count
    small_ratio = small_frames / frame_count
    full_width_ratio = full_width_frames / frame_count
    score = _bounded_score(base_quality_score)

    if edge_ratio >= 0.50:
        score = min(score, 20)
    elif edge_ratio >= 0.25:
        score = min(score, 45)
    elif edge_ratio >= 0.10:
        score = min(score, 67)
    elif edge_frames:
        score = min(score, round(100 - edge_ratio * 100))

    if full_width_ratio >= 0.25:
        score = min(score, 35)
    if small_ratio >= 0.25:
        score = min(score, 55)
    elif small_ratio >= 0.10:
        score = min(score, 67)

    warnings = []
    if edge_ratio >= 0.25:
        warnings.append(
            f'A jármű {edge_frames}/{frame_count} nézetben eléri a képszélt. '
            'Készíts új felvételt nagyobb távolságból, az egész autó végig maradjon a képen.'
        )
    elif edge_frames:
        warnings.append(
            f'{edge_frames} nézetben a jármű közel került a képszélhez; ellenőrzés ajánlott.'
        )
    if full_width_ratio >= 0.25:
        warnings.append(
            'A maszk több nézetben a teljes képszélességet lefedi; a céljármű más autókkal vagy háttérelemekkel összetapadhatott.'
        )
    if small_frames >= 4:
        warnings.append(
            'A jármű több nézetben túl kicsi a képen; a következő felvételnél menj közelebb.'
        )

    return score, warnings, {
        'segmentation': {
            'frames': frame_count,
            'edgeTouchingFrames': edge_frames,
            'fullWidthMaskFrames': full_width_frames,
            'smallVehicleFrames': small_frames,
            'targetLockRefinedFrames': target_lock_frames,
            'edgeTouchingRatio': round(edge_ratio, 4),
            'averageAlphaCoverage': round(
                sum(item.get('alphaCoverage', 0) for item in valid_metrics) / frame_count,
                4,
            ),
        }
    }
