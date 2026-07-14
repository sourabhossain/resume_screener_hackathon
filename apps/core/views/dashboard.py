"""Dashboard and health-check views."""
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import render

from ..models import Job, Resume

logger = logging.getLogger(__name__)

# Celery worker liveness is probed via a broker broadcast (app.control.ping),
# which is heavier than a local check, so the result is cached briefly to keep a
# frequently-polled /health/ from hammering the broker.
CELERY_PING_TIMEOUT = 1.0
_CELERY_CACHE_KEY = '__health_celery_ok__'
_CELERY_CACHE_TTL = 30


def _probe_db():
    """DB reachability via SELECT 1."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error("Health: database probe failed: %s", e)
        return False


def _probe_redis():
    """Redis reachability, short-bounded. Uses ResilientRedisCache.is_available()
    when present (socket_connect_timeout/socket_timeout are pinned to 1s in
    settings, so a dead Redis cannot hang the endpoint); falls back to a cache
    round-trip for non-Redis backends (e.g. LocMemCache in tests)."""
    from django.core.cache import cache
    is_available = getattr(cache, 'is_available', None)
    if callable(is_available):
        try:
            return bool(is_available())
        except Exception as e:
            logger.warning("Health: redis probe error: %s", e)
            return False
    try:
        cache.set('__health_redis_probe__', '1', 5)
        return cache.get('__health_redis_probe__') == '1'
    except Exception as e:
        logger.warning("Health: cache round-trip probe error: %s", e)
        return False


def _celery_ping():
    """Broadcast a ping to workers; True if any worker replies. Bounded by a
    short timeout so a dead broker/worker cannot hang the endpoint."""
    try:
        from config.celery import app
        replies = app.control.ping(timeout=CELERY_PING_TIMEOUT)
        return bool(replies)
    except Exception as e:
        logger.warning("Health: celery ping error: %s", e)
        return False


def _probe_celery():
    """Cached Celery worker liveness (see CELERY_CACHE_TTL note above)."""
    from django.core.cache import cache
    cached = cache.get(_CELERY_CACHE_KEY)
    if cached is not None:
        return bool(cached)
    ok = _celery_ping()
    cache.set(_CELERY_CACHE_KEY, ok, _CELERY_CACHE_TTL)
    return ok


def health_check(request):
    """Unauthenticated liveness/readiness probe for db, redis and celery.

    200 {"status":"ok"} when all pass. 503 otherwise: "unhealthy" if the DB is
    down (cannot serve), "degraded" if the DB is up but Redis/Celery are down
    (reads may work but the screening pipeline cannot run). The payload exposes
    only component name + ok/reason -- never connection strings or hostnames.
    """
    components = {
        'db': _probe_db(),
        'redis': _probe_redis(),
        'celery': _probe_celery(),
    }

    detail = {}
    for name, ok in components.items():
        detail[name] = {'ok': ok} if ok else {'ok': False, 'reason': 'unreachable'}

    if not components['db']:
        status = 'unhealthy'
    elif not all(components.values()):
        status = 'degraded'
    else:
        status = 'ok'

    http_status = 200 if status == 'ok' else 503
    if status != 'ok':
        logger.error("Health check %s: %s", status,
                     {n: v['ok'] for n, v in detail.items()})
    return JsonResponse(
        {'status': status, 'components': detail, 'version': '1.0.0'},
        status=http_status,
    )

@login_required
def dashboard(request):
    from django.utils import timezone as tz
    from apps.interviews.models import InterviewEvaluation

    job_stats = Job.objects.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(status='active'))
    )

    resume_stats = Resume.objects.filter(job__is_deleted=False).aggregate(
        total=Count('id'),
        avg_score=Avg('final_score', filter=Q(final_score__isnull=False, screening_status='completed')),
        top_tier=Count('id', filter=Q(tier='top')),
        mid_tier=Count('id', filter=Q(tier='mid')),
        low_tier=Count('id', filter=Q(tier='low')),
        pending=Count('id', filter=Q(screening_status='pending')),
        processing=Count('id', filter=Q(screening_status='processing')),
        screening_failed=Count('id', filter=Q(screening_status='failed')),
        needs_review=Count('id', filter=Q(screening_status='needs_review')),
        talent_pool_count=Count('id', filter=Q(recommendation='talent_pool')),
    )

    expiry_threshold = tz.now() + timedelta(days=3)
    expiring_evals = InterviewEvaluation.objects.filter(
        is_submitted=False,
        token_expires_at__lte=expiry_threshold,
        token_expires_at__gte=tz.now(),
    ).count()

    recent_jobs = Job.objects.annotate(
        resume_count=Count('resumes', filter=Q(resumes__is_deleted=False))
    )[:5]
    recent_resumes = Resume.objects.filter(job__is_deleted=False).select_related('job')[:5]

    context = {
        'total_jobs': job_stats['total'],
        'active_jobs': job_stats['active'],
        'total_resumes': resume_stats['total'],
        'avg_score': round(resume_stats['avg_score'] or 0, 1),
        'recent_jobs': recent_jobs,
        'recent_resumes': recent_resumes,
        'top_tier': resume_stats['top_tier'],
        'mid_tier': resume_stats['mid_tier'],
        'low_tier': resume_stats['low_tier'],
        'pending_screening': resume_stats['pending'],
        'processing_screening': resume_stats['processing'],
        'screening_failed': resume_stats['screening_failed'],
        'needs_review_count': resume_stats['needs_review'],
        'talent_pool_count': resume_stats['talent_pool_count'],
        'expiring_evals': expiring_evals,
    }
    return render(request, 'core/dashboard.html', context)
