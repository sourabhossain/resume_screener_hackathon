"""The candidate's timed sittings, taken in order on one link, and the HR-only report."""
import json
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.models import Resume

from . import instruments, services
from .models import AssessmentInvitation, SEIAssessment

logger = logging.getLogger(__name__)


# ── candidate side ───────────────────────────────────────────────────────
class InvalidLink(Exception):
    """The token names no invitation. Rendered as a page, not a raw 404."""


def _resolve(token):
    """(invitation, legacy sitting) for an invitation token or a pre-grouping sitting token."""
    invitation = AssessmentInvitation.objects.select_related(
        'resume', 'resume__job').filter(token=token).first()
    if invitation is not None:
        return invitation, None
    legacy = SEIAssessment.objects.select_related(
        'invitation', 'invitation__resume', 'invitation__resume__job',
    ).filter(token=token).first()
    if legacy is None:
        raise InvalidLink
    return legacy.invitation, legacy


def _get(token):
    return _resolve(token)[0]


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


def _session_key(invitation) -> str:
    return f'sei_verified:{invitation.token}'


def _is_verified(request, invitation) -> bool:
    if not invitation.otp_verified_at:
        return False
    if request.session.get(_session_key(invitation)) is True:
        return True
    # Sessions verified on a per-part link before parts were grouped.
    legacy_keys = [f'sei_verified:{s.token}' for s in invitation.sittings.all()]
    if any(request.session.get(key) is True for key in legacy_keys):
        request.session[_session_key(invitation)] = True
        return True
    return False


def _settle(invitation):
    """Ordered sittings, closing any whose clock ran out so the next part unlocks."""
    sittings = invitation.ordered_sittings()
    for sitting in sittings:
        services.finalise_if_time_is_up(sitting)
    return sittings


def _first_name(invitation) -> str:
    # Just the first name for the greeting. truncatewords would append an
    # ellipsis, and a full name in a "Hi ..." line reads like a form letter.
    full_name = (invitation.resume.candidate_name or '').strip()
    return full_name.split()[0].title() if full_name else 'there'


def _closed_response(request, invitation, sittings):
    """Whatever page applies when nothing is left to answer. None if something is."""
    if not sittings:
        return render(request, 'sei_assessment/invalid_link.html', status=404)
    if all(s.is_submitted for s in sittings):
        return render(request, 'sei_assessment/done.html', {
            'invitation': invitation,
            'sittings': sittings,
            'auto_submitted': any(s.auto_submitted for s in sittings),
        })
    if invitation.is_expired:
        return render(request, 'sei_assessment/expired.html',
                      {'invitation': invitation})
    return None


def _parts(sittings, current):
    """Each sitting tagged done, current or locked."""
    parts = []
    for number, sitting in enumerate(sittings, start=1):
        if sitting.is_submitted:
            state = 'done'
        elif current is not None and sitting.pk == current.pk:
            state = 'current'
        else:
            state = 'locked'
        parts.append({'number': number, 'sitting': sitting,
                      'spec': sitting.spec, 'state': state})
    return parts


@_candidate_page
def entry(request, token):
    """The link in the email, and where the candidate returns between parts."""
    invitation, legacy = _resolve(token)
    if legacy is not None:
        return redirect('sei_assessment:entry', token=invitation.token)

    sittings = _settle(invitation)
    closed = _closed_response(request, invitation, sittings)
    if closed:
        return closed
    if not _is_verified(request, invitation):
        return redirect('sei_assessment:verify', token=token)

    current = invitation.current_sitting(sittings)
    if current.has_started:
        return redirect('sei_assessment:test', token=token)

    finished = [s for s in sittings if s.is_submitted]
    remaining = [s for s in sittings if not s.is_submitted]
    return render(request, 'sei_assessment/lobby.html', {
        'invitation': invitation,
        'first_name': _first_name(invitation),
        'parts': _parts(sittings, current),
        'part_count': len(sittings),
        'current': current,
        'current_number': sittings.index(current) + 1,
        'just_finished': finished[-1] if finished else None,
        'remaining_count': len(remaining),
        'remaining_minutes': sum(s.spec.time_limit_minutes for s in remaining),
    })


@ratelimit(key='ip', rate='300/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='30/h', method='POST', block=True)
@_candidate_page
def verify(request, token):
    invitation = _get(token)
    sittings = _settle(invitation)
    closed = _closed_response(request, invitation, sittings)
    if closed:
        return closed

    error = ''
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        if invitation.otp_is_locked:
            error = 'Too many incorrect codes. Use "Send me a new code" below.'
        elif invitation.otp_is_expired:
            error = 'That code has expired. Use "Send me a new code" below.'
        elif invitation.check_otp(code):
            request.session[_session_key(invitation)] = True
            return redirect('sei_assessment:entry', token=invitation.token)
        else:
            error = (f'That code is not right. '
                     f'{invitation.otp_attempts_left} attempt(s) left.')

    return render(request, 'sei_assessment/verify.html', {
        'invitation': invitation,
        'part_count': len(sittings),
        'error': error,
    })


@require_POST
@ratelimit(key='ip', rate='100/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='5/h', method='POST', block=True)
@_candidate_page
def resend_code(request, token):
    invitation = _get(token)
    closed = _closed_response(request, invitation, _settle(invitation))
    if closed:
        return closed
    try:
        services.resend_code(invitation)
    except Exception:
        logger.exception('sei.resend_failed invitation=%s', invitation.pk)
        messages.error(request, 'We could not send the code. Please try again.')
    else:
        messages.success(request, 'A new code is on its way.')
    return redirect('sei_assessment:verify', token=invitation.token)


@require_POST
@_candidate_page
def begin(request, token, instrument):
    """Start the named part's clock, only if it is the part now open."""
    invitation = _get(token)
    sittings = _settle(invitation)
    closed = _closed_response(request, invitation, sittings)
    if closed:
        return closed
    if not _is_verified(request, invitation):
        return redirect('sei_assessment:verify', token=invitation.token)

    current = invitation.current_sitting(sittings)
    if current.instrument != instrument:
        return redirect('sei_assessment:entry', token=invitation.token)
    if current.start_clock():
        logger.info('sei.started assessment=%s instrument=%s',
                    current.pk, current.instrument)
    return redirect('sei_assessment:test', token=invitation.token)


@_candidate_page
def test(request, token):
    """The running part's questions. Never starts a clock."""
    invitation = _get(token)
    sittings = _settle(invitation)
    closed = _closed_response(request, invitation, sittings)
    if closed:
        return closed
    if not _is_verified(request, invitation):
        return redirect('sei_assessment:verify', token=invitation.token)

    assessment = invitation.running_sitting(sittings)
    if assessment is None:
        return redirect('sei_assessment:entry', token=invitation.token)

    spec = assessment.spec
    number = sittings.index(assessment) + 1
    return render(request, 'sei_assessment/test.html', {
        'invitation': invitation,
        'assessment': assessment,
        'instrument': spec,
        'part_number': number,
        'part_count': len(sittings),
        'next_part': sittings[number] if number < len(sittings) else None,
        'first_name': _first_name(invitation),
        'pages': spec.paginate(assessment.answers),
        'scale': spec.scale,
        'seconds_left': assessment.seconds_left,
        'minutes': spec.time_limit_minutes,
        'answered': assessment.answered_count,
        'total_items': spec.total_items,
        'minimum_answers': spec.minimum_answers,
    })


@require_POST
# The page flushes every five seconds, so a candidate answering steadily for
# the full fifteen minutes makes ~180 calls, and a retake reuses the same token
# within the hour. A limit at that boundary would
# start refusing saves in the last minutes of a timed test -- the one place
# answers cannot be re-entered.
@ratelimit(key=_rate_key, rate='900/h', method='POST', block=True)
@_candidate_page
def save(request, token, instrument=None):
    """Autosave from the page, and the final submit.

    Answers are written as they are picked so a closed laptop still leaves a
    scoreable paper -- the whole point of a timed sitting is that there is no
    second chance to re-enter them. The URL names the part, since item numbers
    repeat across instruments.
    """
    invitation, legacy = _resolve(token)
    if not _is_verified(request, invitation):
        return JsonResponse({'status': 'unverified'}, status=403)

    if instrument is not None:
        assessment = invitation.sittings.filter(instrument=instrument).first()
    elif legacy is not None:
        assessment = legacy
    else:
        assessment = invitation.running_sitting()
    if assessment is None:
        return JsonResponse({'status': 'error', 'error': 'unknown part'}, status=404)

    services.finalise_if_time_is_up(assessment)
    if assessment.is_submitted:
        return JsonResponse({'status': 'closed',
                             'reason': 'auto' if assessment.auto_submitted else 'done'})
    if not assessment.has_started:
        return JsonResponse({'status': 'not_started'}, status=409)

    try:
        incoming = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'error': 'bad payload'}, status=400)

    spec = assessment.spec
    cleaned = {}
    for key, value in (incoming.get('answers') or {}).items():
        try:
            item, rating = int(key), int(value)
        except (TypeError, ValueError):
            continue
        # Validated against this sitting's own instrument. SEI runs 0-3 over 48
        # items and PE 0-4 over 15, so a shared rule would either drop a real
        # PE answer of 4 or accept an SEI item number that does not exist.
        if item in spec.items and spec.min_rating <= rating <= spec.max_rating:
            cleaned[str(item)] = rating

    finish = bool(incoming.get('finish'))
    # Locked, because two tabs answering at once would otherwise each merge onto
    # the copy they loaded and the later write would drop the earlier answers.
    # In a timed sitting there is no chance to enter them again.
    with transaction.atomic():
        locked = SEIAssessment.objects.select_for_update().get(pk=assessment.pk)
        locked.answers = {**(locked.answers or {}), **cleaned}
        fields = ['answers', 'updated_at']
        if finish:
            locked.is_submitted = True
            locked.submitted_at = timezone.now()
            locked.auto_submitted = False
            fields += ['is_submitted', 'submitted_at', 'auto_submitted']
        locked.save(update_fields=fields)
    assessment = locked

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
    invitation = _get(token)
    sittings = _settle(invitation)
    if not sittings or not all(s.is_submitted for s in sittings):
        return redirect('sei_assessment:entry', token=invitation.token)
    return _closed_response(request, invitation, sittings)


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


def _instrument_or_404(key):
    try:
        return instruments.get(key)
    except KeyError:
        raise Http404(f'No assessment named {key!r}')


@_hr_admin_required
def report(request, uuid, instrument):
    spec = _instrument_or_404(instrument)
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    assessment = services.sitting_for(resume, instrument)
    if assessment is None:
        messages.info(
            request,
            f'The {spec.label} assessment has not been sent to this candidate.')
        return redirect('core:resume_detail', uuid=uuid)

    services.finalise_if_time_is_up(assessment)
    context = {
        'resume': resume,
        'assessment': assessment,
        'instrument': spec,
        'result': assessment.result(),
    }
    if instrument == instruments.PE:
        from . import pe_scoring
        # The sheet prints all eight so a reader can see where this one sits
        # among them, rather than being handed a bare label.
        context['categories'] = list(pe_scoring.CATEGORIES.items())
    return render(request, spec.report_template, context)


@_hr_admin_required
@require_POST
def send(request, uuid):
    """Send, or resend, the candidate's one assessment invitation."""
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    try:
        services.issue_invite(resume, user=request.user, resend=True)
    except services.InviteError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Assessment link sent to {resume.email}.')
    return redirect('core:resume_detail', uuid=uuid)
