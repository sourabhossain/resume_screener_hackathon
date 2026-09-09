"""The candidate's timed sitting, and the HR-only report.

Two audiences. The candidate arrives on an emailed link, proves it is them with
a code, and answers against a clock. HR reads the result; the candidate never
sees a score.
"""
import json
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.models import Resume

from . import scoring, services
from .models import SEIAssessment

logger = logging.getLogger(__name__)


# ── candidate side ───────────────────────────────────────────────────────
class InvalidLink(Exception):
    """The token names no sitting. Rendered as a page, not a raw 404."""


def _get(token):
    try:
        return SEIAssessment.objects.select_related(
            'resume', 'resume__job').get(token=token)
    except SEIAssessment.DoesNotExist as exc:
        raise InvalidLink from exc


def _candidate_page(view_fn):
    @wraps(view_fn)
    def wrapper(request, token, *args, **kwargs):
        try:
            return view_fn(request, token, *args, **kwargs)
        except InvalidLink:
            # Says nothing about whether the token ever existed.
            return render(request, 'sei_assessment/invalid_link.html', status=404)
    return wrapper


def _rate_key(group, request) -> str:
    """Rate-limit per link, not per IP: candidates may share a connection."""
    return str(request.resolver_match.kwargs.get('token', ''))


def _session_key(assessment) -> str:
    return f'sei_verified:{assessment.token}'


def _is_verified(request, assessment) -> bool:
    return bool(assessment.otp_verified_at) and request.session.get(
        _session_key(assessment)) is True


def _closed_response(request, assessment):
    """Whatever page applies when the sitting is over. None if still open."""
    services.finalise_if_time_is_up(assessment)
    if assessment.is_submitted:
        return render(request, 'sei_assessment/done.html', {'assessment': assessment})
    if assessment.is_expired:
        return render(request, 'sei_assessment/expired.html', {'assessment': assessment})
    return None


@_candidate_page
def entry(request, token):
    assessment = _get(token)
    closed = _closed_response(request, assessment)
    if closed:
        return closed
    if _is_verified(request, assessment):
        return redirect('sei_assessment:test', token=token)
    return redirect('sei_assessment:verify', token=token)


@ratelimit(key='ip', rate='300/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='30/h', method='POST', block=True)
@_candidate_page
def verify(request, token):
    assessment = _get(token)
    closed = _closed_response(request, assessment)
    if closed:
        return closed

    error = ''
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        if assessment.otp_is_locked:
            error = 'Too many incorrect codes. Use "Send me a new code" below.'
        elif assessment.otp_is_expired:
            error = 'That code has expired. Use "Send me a new code" below.'
        elif assessment.check_otp(code):
            request.session[_session_key(assessment)] = True
            return redirect('sei_assessment:test', token=token)
        else:
            error = (f'That code is not right. '
                     f'{assessment.otp_attempts_left} attempt(s) left.')

    return render(request, 'sei_assessment/verify.html', {
        'assessment': assessment,
        'error': error,
    })


@require_POST
@ratelimit(key='ip', rate='100/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='5/h', method='POST', block=True)
@_candidate_page
def resend_code(request, token):
    assessment = _get(token)
    closed = _closed_response(request, assessment)
    if closed:
        return closed
    try:
        services.resend_code(assessment)
    except Exception:
        logger.exception('sei.resend_failed assessment=%s', assessment.pk)
        messages.error(request, 'We could not send the code. Please try again.')
    else:
        messages.success(request, 'A new code is on its way.')
    return redirect('sei_assessment:verify', token=token)


@_candidate_page
def test(request, token):
    """The questions. Opening this page is what starts the clock."""
    assessment = _get(token)
    closed = _closed_response(request, assessment)
    if closed:
        return closed
    if not _is_verified(request, assessment):
        return redirect('sei_assessment:verify', token=token)

    started_now = assessment.start_clock()
    if started_now:
        logger.info('sei.started assessment=%s', assessment.pk)

    answers = assessment.answers or {}
    return render(request, 'sei_assessment/test.html', {
        'assessment': assessment,
        'items': [
            {'no': no, 'text': text, 'value': answers.get(str(no))}
            for no, text in sorted(scoring.ITEMS.items())
        ],
        'ratings': scoring.RATING_LABELS,
        'seconds_left': assessment.seconds_left,
        'minutes': assessment.TIME_LIMIT_MINUTES,
        'answered': assessment.answered_count,
        'total_items': len(scoring.ITEMS),
        'minimum_answers': scoring.MINIMUM_VALID_ANSWERS,
    })


@require_POST
@ratelimit(key=_rate_key, rate='240/h', method='POST', block=True)
@_candidate_page
def save(request, token):
    """Autosave from the page, and the final submit.

    Answers are written as they are picked so a closed laptop still leaves a
    scoreable paper -- the whole point of a timed sitting is that there is no
    second chance to re-enter them.
    """
    assessment = _get(token)
    if not _is_verified(request, assessment):
        return JsonResponse({'status': 'unverified'}, status=403)

    services.finalise_if_time_is_up(assessment)
    if assessment.is_submitted:
        return JsonResponse({'status': 'closed',
                             'reason': 'auto' if assessment.auto_submitted else 'done'})

    try:
        incoming = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'error': 'bad payload'}, status=400)

    cleaned = {}
    for key, value in (incoming.get('answers') or {}).items():
        try:
            item, rating = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if item in scoring.ITEMS and scoring.MIN_RATING <= rating <= scoring.MAX_RATING:
            cleaned[str(item)] = rating

    finish = bool(incoming.get('finish'))
    # select_for_update is not used: this is the only writer of `answers`, and
    # every other writer narrows its save to its own columns.
    merged = {**(assessment.answers or {}), **cleaned}
    fields = ['answers', 'updated_at']
    assessment.answers = merged
    if finish:
        from django.utils import timezone
        assessment.is_submitted = True
        assessment.submitted_at = timezone.now()
        assessment.auto_submitted = False
        fields += ['is_submitted', 'submitted_at', 'auto_submitted']
    assessment.save(update_fields=fields)

    if finish:
        logger.info('sei.submitted assessment=%s answered=%s',
                    assessment.pk, assessment.answered_count)
    return JsonResponse({
        'status': 'submitted' if finish else 'saved',
        'answered': assessment.answered_count,
        'seconds_left': assessment.seconds_left,
    })


@_candidate_page
def done(request, token):
    assessment = _get(token)
    if not assessment.is_submitted:
        return redirect('sei_assessment:entry', token=token)
    return render(request, 'sei_assessment/done.html', {'assessment': assessment})


# ── HR side ──────────────────────────────────────────────────────────────
def _hr_admin_required(view_fn):
    """HR staff only: this report describes a candidate's inner life."""
    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(
                request, 'Assessment results are restricted to HR administrators.')
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapper


@_hr_admin_required
def report(request, uuid):
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    assessment = getattr(resume, 'sei_assessment', None)
    if assessment is None:
        messages.info(request, 'No assessment has been sent to this candidate.')
        return redirect('core:resume_detail', uuid=uuid)

    services.finalise_if_time_is_up(assessment)
    return render(request, 'sei_assessment/report.html', {
        'resume': resume,
        'assessment': assessment,
        'result': assessment.result(),
        'items': scoring.ITEMS,
    })


@_hr_admin_required
@require_POST
def send(request, uuid):
    resume = get_object_or_404(Resume, uuid=uuid)
    try:
        services.issue_invite(resume, user=request.user, resend=True)
    except services.InviteError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Assessment sent to {resume.email}.')
    return redirect('core:resume_detail', uuid=uuid)
