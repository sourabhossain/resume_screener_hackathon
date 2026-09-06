"""External verification requests: the HR side and the respondent's side.

Two audiences in one app. HR (is_staff) decides who is asked and reads the
replies. The respondent is a stranger to this system -- a former employer's HR,
a referee, a professor -- who arrives on an emailed link, proves it is them with
a one-time code, and never sees anything but their own form.
"""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.form_utils import form_errors_to_messages
from apps.core.models import Resume

from . import schema, services
from .forms import StepForm
from .models import ReferenceCheck

logger = logging.getLogger(__name__)

# These open with the two HR instruments, once the candidate is actually being
# interviewed. Asking a former employer about someone you have not met yet is
# both premature and a disclosure the candidate would not expect.
STATUSES_ALLOWING_SEND = frozenset({'interviewing', 'offer_extended', 'hired'})


# ── HR side ──────────────────────────────────────────────────────────────
def _hr_admin_required(view_fn):
    """HR staff only. These replies carry other people's disclosures."""
    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(
                request, 'Reference checks are restricted to HR administrators.')
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapper


def _get_resume(uuid):
    return get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)


@_hr_admin_required
def manage(request, uuid):
    """Who can be asked, who has been asked, and what came back."""
    resume = _get_resume(uuid)
    refused = services.verification_refused(resume)
    return render(request, 'reference_checks/manage.html', {
        'resume': resume,
        'contacts': services.candidate_contacts(resume),
        'verification_refused': refused,
        'can_send': resume.recruiter_status in STATUSES_ALLOWING_SEND and not refused,
        'is_fresher': services.is_fresher(resume),
        'kind_labels': schema.KIND_LABELS,
        'kind_choices': ReferenceCheck.KIND_CHOICES,
    })


@_hr_admin_required
@require_POST
def send(request, uuid, source_key):
    """Send (or resend) one request, with whatever HR corrected on the row."""
    resume = _get_resume(uuid)

    if resume.recruiter_status not in STATUSES_ALLOWING_SEND:
        messages.error(
            request, 'Reference checks open once the candidate reaches Interviewing.')
        return redirect('reference_checks:manage', uuid=uuid)

    kind = request.POST.get('kind', '')
    if kind not in dict(ReferenceCheck.KIND_CHOICES):
        messages.error(request, 'Unknown form type.')
        return redirect('reference_checks:manage', uuid=uuid)

    try:
        services.issue_request(
            resume, source_key,
            kind=kind,
            recipient_name=request.POST.get('recipient_name', ''),
            recipient_email=request.POST.get('recipient_email', ''),
            recipient_organisation=request.POST.get('recipient_organisation', ''),
            user=request.user,
            resend=True,
        )
    except services.SendError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Request sent to {request.POST.get("recipient_email")}.')
    return redirect('reference_checks:manage', uuid=uuid)


@_hr_admin_required
def response(request, uuid, pk):
    """One completed reply, read-only."""
    resume = _get_resume(uuid)
    check = get_object_or_404(ReferenceCheck, pk=pk, resume=resume)
    return render(request, 'reference_checks/response.html', {
        'resume': resume,
        'check': check,
        'sections': check.answered_sections(),
        'form_title': schema.KIND_LABELS[check.kind],
    })


# ── Respondent side ──────────────────────────────────────────────────────
def _rate_key(group, request) -> str:
    """Rate-limit per link, not per IP: one employer's HR team may share one."""
    return str(request.resolver_match.kwargs.get('token', ''))


class InvalidLink(Exception):
    """The token names no request. Rendered as a page, not a raw 404."""


def _get_check(token):
    try:
        return ReferenceCheck.objects.select_related(
            'resume', 'resume__job').get(token=token)
    except ReferenceCheck.DoesNotExist as exc:
        raise InvalidLink from exc


def _respondent_page(view_fn):
    @wraps(view_fn)
    def wrapper(request, token, *args, **kwargs):
        try:
            return view_fn(request, token, *args, **kwargs)
        except InvalidLink:
            # Deliberately says nothing about whether the token ever existed.
            return render(request, 'reference_checks/invalid_link.html', status=404)
    return wrapper


def _session_key(check) -> str:
    return f'reference_check_verified:{check.token}'


def _is_verified(request, check) -> bool:
    return bool(check.otp_verified_at) and request.session.get(
        _session_key(check)) is True


def _closed_response(request, check):
    if check.is_submitted:
        return render(request, 'reference_checks/already_submitted.html',
                      {'check': check})
    if check.is_expired:
        return render(request, 'reference_checks/expired.html', {'check': check})
    return None


def _candidate_panel(check) -> dict:
    """The read-only facts the paper form has SSL fill in for the respondent."""
    resume = check.resume
    answers = getattr(resume, 'employee_form', None)
    answers = dict(answers.answers or {}) if answers else {}
    panel = {
        'Candidate': resume.candidate_name,
        'Position applied for': resume.job.title,
    }
    if check.kind == schema.ACADEMIC:
        for label, key in (
            ('University / institution', 'bachelors_institution'),
            ('Degree / programme', 'bachelors_degree_name'),
            ('Major / subject', 'bachelors_major'),
        ):
            if answers.get(key):
                panel[label] = answers[key]
    elif check.kind == schema.EMPLOYER and check.recipient_organisation:
        panel['Organisation'] = check.recipient_organisation
    return panel


@_respondent_page
def entry(request, token):
    check = _get_check(token)
    closed = _closed_response(request, check)
    if closed:
        return closed
    if _is_verified(request, check):
        return redirect('reference_checks:step', token=token,
                        step_key=check.current_step)
    return redirect('reference_checks:verify', token=token)


@ratelimit(key='ip', rate='300/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='30/h', method='POST', block=True)
@_respondent_page
def verify(request, token):
    check = _get_check(token)
    closed = _closed_response(request, check)
    if closed:
        return closed

    error = ''
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        if check.otp_is_locked:
            error = 'Too many incorrect codes. Use "Send me a new code" below.'
        elif check.otp_is_expired:
            error = 'That code has expired. Use "Send me a new code" below.'
        elif check.check_otp(code):
            request.session[_session_key(check)] = True
            return redirect('reference_checks:step', token=token,
                            step_key=check.current_step)
        else:
            error = (f'That code is not right. '
                     f'{check.otp_attempts_left} attempt(s) left.')

    return render(request, 'reference_checks/verify.html', {
        'check': check,
        'error': error,
        'form_title': schema.KIND_LABELS[check.kind],
    })


@require_POST
@ratelimit(key='ip', rate='100/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='5/h', method='POST', block=True)
@_respondent_page
def resend_code(request, token):
    check = _get_check(token)
    closed = _closed_response(request, check)
    if closed:
        return closed
    try:
        services.resend_code(check)
    except Exception:
        logger.exception('reference_checks.resend_failed check=%s', check.pk)
        messages.error(request, 'We could not send the code. Please try again.')
    else:
        messages.success(request, f'A new code is on its way to {check.recipient_email}.')
    return redirect('reference_checks:verify', token=token)


@_respondent_page
def step(request, token, step_key):
    check = _get_check(token)
    closed = _closed_response(request, check)
    if closed:
        return closed
    if not _is_verified(request, check):
        return redirect('reference_checks:verify', token=token)

    if schema.get_step(check.kind, step_key) is None:
        raise Http404('Unknown section.')

    keys = schema.step_keys(check.kind)
    reached = keys.index(check.current_step) if check.current_step in keys else 0
    if keys.index(step_key) > reached:
        # No skipping ahead: the last section carries the recommendation, and it
        # must not be submittable without the questions it rests on.
        return redirect('reference_checks:step', token=token,
                        step_key=keys[reached])

    # Anything already saved wins: the prefill is a starting point, and the
    # moment the respondent corrects a field their version is the answer.
    prefilled = services.prefill_answers(check)
    answers = {**prefilled, **(check.answers or {})}
    shows_prefill = bool(prefilled) and any(
        question['key'] in prefilled
        for question in schema.questions(check.kind, step_key)
    )

    if request.method == 'POST':
        form = StepForm(request.POST, kind=check.kind, step_key=step_key,
                        initial=answers)
        if form.is_valid():
            with transaction.atomic():
                locked = ReferenceCheck.objects.select_for_update().get(pk=check.pk)
                locked.answers = {**(locked.answers or {}), **form.storable_answers()}
                next_key = schema.next_step_key(check.kind, step_key)
                if next_key is None:
                    locked.current_step = step_key
                    locked.is_submitted = True
                    locked.submitted_at = timezone.now()
                else:
                    locked.current_step = next_key
                # Only this view's own columns: HR may be resending a code on
                # the same row, and a full write would undo the new one.
                locked.save(update_fields=[
                    'answers', 'current_step', 'is_submitted', 'submitted_at',
                    'updated_at',
                ])
            check = locked

            if check.is_submitted:
                logger.info('reference_checks.submitted check=%s resume=%s',
                            check.pk, check.resume_id)
                return redirect('reference_checks:done', token=token)
            return redirect('reference_checks:step', token=token,
                            step_key=check.current_step)
        form_errors_to_messages(request, form)
    else:
        form = StepForm(kind=check.kind, step_key=step_key, initial=answers)

    return render(request, 'reference_checks/step.html', {
        'check': check,
        'form': form,
        'rows': form.field_rows(),
        'step': schema.get_step(check.kind, step_key),
        'step_key': step_key,
        'step_number': schema.step_number(check.kind, step_key),
        'total_steps': schema.total_steps(check.kind),
        'previous_step': schema.previous_step_key(check.kind, step_key),
        'is_final': schema.next_step_key(check.kind, step_key) is None,
        'form_title': schema.KIND_LABELS[check.kind],
        'candidate_panel': _candidate_panel(check),
        'shows_prefill': shows_prefill,
        'conditional_rules': schema.conditional_rules(check.kind, step_key),
    })


@_respondent_page
def done(request, token):
    check = _get_check(token)
    if not check.is_submitted:
        return redirect('reference_checks:entry', token=token)
    if not _is_verified(request, check):
        # This page names the candidate. The link alone must not be enough to
        # learn who applied -- that is the whole point of the emailed code.
        return redirect('reference_checks:verify', token=token)
    return render(request, 'reference_checks/done.html', {
        'check': check,
        'form_title': schema.KIND_LABELS[check.kind],
    })
