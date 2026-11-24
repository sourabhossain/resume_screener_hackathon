"""Where a candidate's score sits among everyone scored for the same job."""
import math

MIN_POOL = 5
BANDS = ('Well below', 'Below', 'Average', 'Above', 'Well above')

# Chart geometry, in SVG units: percentile p sits at x = p * 5.
WIDTH, BASELINE, PEAK, SPREAD = 500, 116, 30, 17


def _curve_y(p):
    return BASELINE - (BASELINE - PEAK) * math.exp(-0.5 * ((p - 50) / SPREAD) ** 2)


def _from_counts(lower, pool):
    return min(99, max(1, round(lower * 100 / (pool - 1))))


def _percentile(score, scores):
    return _from_counts(sum(1 for s in scores if s < score), len(scores))


def _scored(**filters):
    from apps.core.models import Resume
    return Resume.objects.filter(screening_status='completed', final_score__isnull=False, **filters)


def _suffix(n):
    return 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


def score_standing(resume):
    """None until the candidate is scored; otherwise the card's numbers and drawing."""
    if resume.final_score is None or resume.screening_status != 'completed':
        return None
    # Counted in the database: a 10,000-CV job would otherwise send every
    # score to Python on each candidate page and status change.
    from django.db.models import Count, Max, Q
    pool_qs = _scored(job_id=resume.job_id).order_by()
    score = resume.final_score
    counts = pool_qs.aggregate(pool=Count('id'), lower=Count('id', filter=Q(final_score__lt=score)),
                               higher=Count('id', filter=Q(final_score__gt=score)), top=Max('final_score'))
    pool = counts['pool']
    if pool < MIN_POOL:
        return {'enough': False, 'pool': pool, 'needed': MIN_POOL}

    lower = counts['lower']
    percentile = _from_counts(lower, pool)
    position = counts['higher'] + 1
    top = counts['top']
    top_percentile = _from_counts(pool_qs.filter(final_score__lt=top).count(), pool)
    band = min(4, percentile // 20)
    curve = ' '.join(f'{"M" if p == 0 else "L"}{p * 5},{_curve_y(p):.1f}' for p in range(0, 101, 2))
    return {
        'enough': True,
        'pool': pool,
        'others': pool - 1,
        'lower': lower,
        'position': position,
        'percentile': percentile,
        'suffix': _suffix(percentile),
        'raw': round(resume.final_score),
        'band': BANDS[band],
        'top': round(top),
        'is_top': resume.final_score >= top,
        'svg': {
            'curve': curve,
            'area': f'{curve} L{WIDTH},{BASELINE} L0,{BASELINE} Z',
            'bands': [{'x': i * 100, 'label': label, 'mid': i * 100 + 50, 'current': i == band}
                      for i, label in enumerate(BANDS)],
            'x': percentile * 5,
            'y': round(_curve_y(percentile), 1),
            'top_x': top_percentile * 5,
        },
    }
