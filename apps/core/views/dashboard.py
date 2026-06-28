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


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({'status': 'healthy', 'database': 'connected', 'version': '1.0.0'})
    except Exception as e:
        logger.error(f"Health check database connectivity failed: {e}")
        return JsonResponse({'status': 'unhealthy', 'database': 'disconnected'}, status=503)


@login_required
def dashboard(request):
    # Single-company internal tool: every authenticated recruiter sees all data.
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

    # Actionable alerts: evaluations expiring in <= 3 days, not yet submitted
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
