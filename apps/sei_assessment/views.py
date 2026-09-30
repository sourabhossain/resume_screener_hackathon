"""The candidate's timed sittings, taken in order on one link, and the HR-only report."""
import json
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.models import Resume

from . import instruments, services
from .models import AssessmentInvitation, SEIAssessment

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = 'jobs@sslwireless.com'


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
            response = view_fn(request, token, *args, **kwargs)
        except InvalidLink:
            # Says nothing about whether the token ever existed.
            response = render(request, 'sei_assessment/invalid_link.html',
                              {'support_email': SUPPORT_EMAIL}, status=404)
        # Never from the browser's cache: Back must not bring up a page whose
        # clock or Start button no longer matches the server.
        add_never_cache_headers(response)
        return response
    return wrapper


def _rate_key(group, request) -> str:
    """Rate-limit per invitation, not per IP: candidates may share a connection.

    Resolved, because an old per-part token reaches the same invitation and must
    not bring a second allowance of code guesses with it.
    """
    token = str(request.resolver_match.kwargs.get('token', ''))
    try:
        return str(_resolve(token)[0].token)
    except InvalidLink:
        return token


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


def _stepper(sittings, active):
    """Instructions, Part 1..n, Submit, each marked done, active or ahead.

    A part is done once submitted even if it comes after the active step: a
    retake, or a part finished before the order changed, can leave one behind.
    """
    count = len(sittings)
    labels = ['Instructions', *[f'Part {n}' for n in range(1, count + 1)], 'Submit']
    submitted = {n for n, s in enumerate(sittings, start=1) if s.is_submitted}

    def state(i):
        if i == active:
            return 'active'
        if i in submitted or (i == 0 and active > 0) or (i == count + 1 and active > i):
            return 'done'
        return ''

    return [{'number': i + 1, 'label': label, 'state': state(i)}
            for i, label in enumerate(labels)]


def _portal(invitation, sittings, active):
    """What every candidate page shares: the name, the parts, the stepper."""
    return {
        'invitation': invitation,
        'first_name': _first_name(invitation),
        'part_count': len(sittings),
        'multi': len(sittings) > 1,
        'steps': _stepper(sittings, active) if len(sittings) > 1 else [],
        'support_email': SUPPORT_EMAIL,
    }


def _closed_response(request, invitation, sittings):
    """Whatever page applies when nothing is left to answer. None if something is.

    Anyone holding the link sees these, code or not, so the candidate's name and
    reference only appear to a verified session.
    """
    if not sittings:
        return render(request, 'sei_assessment/invalid_link.html',
                      {'support_email': SUPPORT_EMAIL}, status=404)
    verified = _is_verified(request, invitation)
    if all(s.is_submitted for s in sittings):
        return render(request, 'sei_assessment/done.html', {
            **_portal(invitation, sittings, len(sittings) + 2),
            'verified': verified,
            'auto_submitted': any(s.auto_submitted for s in sittings),
        })
    # A part already running keeps its own clock even if the link lapses mid-way.
    running = any(s.has_started and not s.is_submitted for s in sittings)
    if invitation.is_expired and not running:
        return render(request, 'sei_assessment/expired.html',
                      {**_portal(invitation, sittings, 0), 'verified': verified})
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


def _lobby(request, invitation, sittings, *, consent_error=False):
    """Welcome and instructions before Part 1, or the break before the next part."""
    current = invitation.current_sitting(sittings)
    number = sittings.index(current) + 1
    before = [s for s in sittings[:number - 1] if s.is_submitted]
    spec = current.spec
    return render(request, 'sei_assessment/lobby.html', {
        **_portal(invitation, sittings, number if before else 0),
        'mode': 'transition' if before else 'welcome',
        'parts': _parts(sittings, current),
        'current': current,
        'spec': spec,
        'current_number': number,
        'just_finished': before[-1] if before else None,
        'just_finished_number': sittings.index(before[-1]) + 1 if before else None,
        'total_minutes': sum(s.spec.time_limit_minutes for s in sittings if not s.is_submitted),
        'remaining_count': sum(1 for s in sittings if not s.is_submitted),
        'needs_consent': not invitation.consented_at,
        'consent_error': consent_error,
        'practice_scale': spec.scale,
    })


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
    return _lobby(request, invitation, sittings)


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
        **_portal(invitation, sittings, 0),
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


def _sitting_named(invitation, instrument=None, part=None):
    """The sitting a URL names: by its opaque part key, or by the old slug."""
    if part is not None:
        return invitation.sittings.filter(token=part).first()
    if instrument is not None:
        return invitation.sittings.filter(instrument=instrument).first()
    return None


@require_POST
@_candidate_page
def begin(request, token, instrument=None, part=None):
    """Start the named part's clock, only if it is the part now open."""
    invitation = _get(token)
    sittings = _settle(invitation)
    closed = _closed_response(request, invitation, sittings)
    if closed:
        return closed
    if not _is_verified(request, invitation):
        return redirect('sei_assessment:verify', token=invitation.token)

    current = invitation.current_sitting(sittings)
    named = _sitting_named(invitation, instrument, part)
    if named is None or current.pk != named.pk:
        return redirect('sei_assessment:entry', token=invitation.token)
    if not current.has_started and not invitation.consented_at:
        if request.POST.get('consent') != '1':
            return _lobby(request, invitation, sittings, consent_error=True)
        invitation.record_consent()
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
    pages = spec.paginate(assessment.answers)
    seconds_left = assessment.seconds_left
    return render(request, 'sei_assessment/test.html', {
        **_portal(invitation, sittings, number),
        'assessment': assessment,
        'instrument': spec,
        'part_number': number,
        'is_last_part': all(s.is_submitted for s in sittings if s.pk != assessment.pk),
        'pages': pages,
        'items': [item for page in pages for item in page],
        'scale': spec.scale,
        'seconds_left': seconds_left,
        'clock': f'{seconds_left // 60:02d}:{seconds_left % 60:02d}',
        'answered': assessment.answered_count,
        'total_items': spec.total_items,
        'state': {
            'answers': {str(item['no']): item['value'] for page in pages
                        for item in page if item['value'] is not None},
            'items': [no for no, _ in spec.sorted_items],
            'perPage': spec.per_page,
            'secondsLeft': seconds_left,
            'saveUrl': reverse('sei_assessment:save_part', kwargs={
                'token': invitation.token, 'part': assessment.token}),
            'entryUrl': reverse('sei_assessment:entry', kwargs={'token': invitation.token}),
        },
    })


@require_POST
# The page flushes every five seconds, so a candidate answering steadily for
# the full fifteen minutes makes ~180 calls, and a retake reuses the same token
# within the hour. A limit at that boundary would
# start refusing saves in the last minutes of a timed test -- the one place
# answers cannot be re-entered.
@ratelimit(key=_rate_key, rate='900/h', method='POST', block=True)
@_candidate_page
def save(request, token, instrument=None, part=None):
    """Autosave from the page, and the final submit.

    Answers are written as they are picked so a closed laptop still leaves a
    scoreable paper -- the whole point of a timed sitting is that there is no
    second chance to re-enter them. The URL names the part, since item numbers
    repeat across instruments.
    """
    invitation, legacy = _resolve(token)
    if not _is_verified(request, invitation):
        return JsonResponse({'status': 'unverified'}, status=403)

    if instrument is not None or part is not None:
        assessment = _sitting_named(invitation, instrument, part)
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
    # In a timed sitting there is no chance to enter them again. Re-checked
    # under the lock: a submit or the sweep may have closed it meanwhile.
    with transaction.atomic():
        locked = SEIAssessment.objects.select_for_update().get(pk=assessment.pk)
        if locked.is_submitted or locked.past_grace:
            closed = locked
        else:
            closed = None
            locked.answers = {**(locked.answers or {}), **cleaned}
            fields = ['answers', 'updated_at']
            if finish:
                locked.is_submitted = True
                locked.submitted_at = timezone.now()
                # The page's clock runs up to a second ahead of the server's, so
                # it says when the timer, not the candidate, ended the part.
                locked.auto_submitted = locked.time_is_up or bool(incoming.get('timed_out'))
                fields += ['is_submitted', 'submitted_at', 'auto_submitted']
            locked.save(update_fields=fields)
    if closed is not None:
        services.finalise_if_time_is_up(closed)
        return JsonResponse({'status': 'closed',
                             'reason': 'auto' if closed.auto_submitted else 'done'})
    assessment = locked

    if finish:
        logger.info('sei.submitted assessment=%s answered=%s auto=%s',
                    assessment.pk, assessment.answered_count, assessment.auto_submitted)
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
