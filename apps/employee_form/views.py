import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.form_utils import form_errors_to_messages
from apps.core.models import Resume

from . import review, schema
from .forms import OtpForm, StepForm
from .models import EmployeeForm, EmployeeFormFile
from .prefill import pending_prefill
from .services import InviteError, issue_invite, issue_otp_only

logger = logging.getLogger(__name__)


def _rate_key(group, request) -> str:
    """Rate-limit the OTP endpoints per form, not per IP.

    Keying on the client IP punishes the wrong people here: Bangladeshi mobile
    carriers put many subscribers behind one NAT address, so a handful of
    candidates exhausting their own attempts would lock out every later
    candidate on that IP — even one entering the correct code. Brute force is
    already bounded per form by EmployeeForm.OTP_MAX_ATTEMPTS; this limit exists
    to cap request volume, so the form token is the right scope.
    """
    if request.resolver_match:
        token = request.resolver_match.kwargs.get('token', '')
    else:
        token = request.path
    return f'{group}:{token}'


def _stale_branch_keys(step_key, saved_answers, cleaned):
    """Question keys belonging to a role section the candidate has routed away from."""
    stale = []
    for branch_key in schema.INLINE_BRANCHES:
        if branch_key not in cleaned:
            continue
        was = schema.inline_target(step_key, saved_answers)
        now = schema.inline_target(step_key, {**saved_answers, **cleaned})
        if was and was != now:
            stale += [q['key'] for q in schema.get_step(was)['questions']]
    return stale


def _session_key(form) -> str:
    return f'employee_form_verified:{form.token}'


def _is_verified(request, form) -> bool:
    """Whether this browser has already cleared the OTP gate for this form."""
    return bool(form.otp_verified_at) and request.session.get(_session_key(form)) is True


class InvalidLink(Exception):
    """The token names no form. Rendered as a page, not a raw 404."""


def _get_form(token):
    """Look up the form behind a candidate's link.

    Raises InvalidLink rather than Http404 so the candidate-facing views can
    explain what happened. A bare "Page not found" gives someone holding a
    superseded or truncated link nothing to act on, and this is a public page —
    the message deliberately says nothing about whether the token ever existed.
    """
    try:
        return EmployeeForm.objects.select_related('resume', 'resume__job').get(
            token=token
        )
    except EmployeeForm.DoesNotExist as exc:
        raise InvalidLink from exc


def _candidate_page(view_fn):
    """Turn an unknown token into the "link not valid" page."""
    @wraps(view_fn)
    def wrapper(request, token, *args, **kwargs):
        try:
            return view_fn(request, token, *args, **kwargs)
        except InvalidLink:
            logger.info('employee_form.invalid_link token=%s', token)
            return render(request, 'employee_form/invalid_link.html', status=404)
    return wrapper


def _closed_response(request, form):
    """Render the terminal state of a form, or None if it is still open."""
    if form.is_submitted:
        return render(request, 'employee_form/already_submitted.html', {'form_obj': form})
    if form.is_expired:
        return render(request, 'employee_form/expired.html', {'form_obj': form})
    return None


# ── Candidate-facing (public, token + OTP) ───────────────────────────────
@_candidate_page
def entry(request, token):
    """Landing point for the emailed link: send to the OTP gate or resume work."""
    form = _get_form(token)

    closed = _closed_response(request, form)
    if closed:
        return closed

    if not _is_verified(request, form):
        return redirect('employee_form:verify', token=token)

    return redirect('employee_form:step', token=token, step_key=form.current_step)


# Per-form cap on OTP submissions, plus a loose per-IP backstop against a
# host hammering many tokens at once.
@ratelimit(key='ip', rate='300/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='30/h', method='POST', block=True)
@_candidate_page
def verify(request, token):
    """The OTP gate. The code was emailed together with this link."""
    form = _get_form(token)

    closed = _closed_response(request, form)
    if closed:
        return closed

    if _is_verified(request, form):
        return redirect('employee_form:step', token=token, step_key=form.current_step)

    otp_form = OtpForm(request.POST or None)

    if request.method == 'POST':
        if form.otp_is_locked:
            messages.error(
                request,
                'Too many incorrect attempts. Request a new code to continue.',
            )
        elif form.otp_is_expired:
            messages.error(
                request, 'That code has expired. Request a new one to continue.'
            )
        elif otp_form.is_valid():
            if form.check_otp(otp_form.cleaned_data['code']):
                request.session[_session_key(form)] = True
                logger.info('employee_form.otp_verified form=%s', form.pk)
                return redirect('employee_form:step', token=token, step_key=form.current_step)
            if form.otp_is_locked:
                messages.error(
                    request,
                    'Incorrect code. You have no attempts left — request a new code.',
                )
            else:
                messages.error(
                    request,
                    f'Incorrect code. {form.otp_attempts_left} attempt(s) left.',
                )
        else:
            form_errors_to_messages(request, otp_form)

    return render(request, 'employee_form/verify.html', {
        'form_obj': form,
        'otp_form': otp_form,
    })


@require_POST
@ratelimit(key='ip', rate='100/h', method='POST', block=True)
@ratelimit(key=_rate_key, rate='5/h', method='POST', block=True)
@_candidate_page
def resend_code(request, token):
    """Candidate-triggered resend of the one-time code."""
    form = _get_form(token)

    closed = _closed_response(request, form)
    if closed:
        return closed

    try:
        issue_otp_only(form)
    except Exception:
        logger.exception('employee_form.resend_failed form=%s', form.pk)
        messages.error(
            request, 'Could not send a new code right now. Please try again shortly.'
        )
    else:
        messages.success(request, 'A new code is on its way to your email.')

    return redirect('employee_form:verify', token=token)


@_candidate_page
def step(request, token, step_key):
    """Render and accept one step of the wizard."""
    form = _get_form(token)

    closed = _closed_response(request, form)
    if closed:
        return closed

    if not _is_verified(request, form):
        return redirect('employee_form:verify', token=token)

    if schema.get_step(step_key) is None:
        raise Http404('Unknown form step.')

    answers = form.answers or {}
    path = form.path

    # Keep the candidate on their own branch: a hand-edited URL pointing at a
    # step their answers do not lead to would collect data that is then never
    # shown, so send them back to where they actually are.
    if step_key not in path:
        return redirect('employee_form:step', token=token, step_key=form.current_step)

    # Revisiting an earlier step is fine (that is what Back does), but jumping
    # *ahead* is not: with no answers yet the declaration is already the last
    # entry in the path, so without this a candidate could open the final step
    # directly, submit it, and skip Sections A-C entirely.
    reached = path.index(form.current_step) if form.current_step in path else 0
    if path.index(step_key) > reached:
        return redirect('employee_form:step', token=token, step_key=path[reached])

    uploaded_keys = set(
        form.files.filter(question_key__in=schema.FILE_QUESTION_KEYS)
        .values_list('question_key', flat=True)
    )

    # Questions we can answer from the application itself, offered as a starting
    # point for anything the candidate has not filled in yet.
    prefill = pending_prefill(form.resume, answers)

    if request.method == 'POST':
        step_form = StepForm(
            request.POST, request.FILES,
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers},
        )
        valid = step_form.is_valid()

        # Store uploads that passed validation even when the step as a whole did
        # not. A browser cannot repopulate a file input, so without this a single
        # mistyped year on Section B (three required certificates) would make the
        # candidate re-attach every document.
        for question_key, uploads in step_form.uploads():
            if step_form.errors.get(question_key):
                continue
            # Replacing an answer replaces its documents, so a corrected
            # upload does not leave the old file attached to the question.
            form.files.filter(question_key=question_key).delete()
            for upload in uploads:
                EmployeeFormFile.objects.create(
                    form=form,
                    question_key=question_key,
                    file=upload,
                    original_name=upload.name[:255],
                    size_bytes=getattr(upload, 'size', 0) or 0,
                )

        if valid:
            # Changing department re-routes the page to a different role section.
            # Whatever was typed into the previous one is dropped, so a Finance
            # candidate's answers never linger on a submission that now says
            # Engineering.
            for key in _stale_branch_keys(step_key, answers, step_form.cleaned_data):
                answers.pop(key, None)

            answers = {**answers, **step_form.storable_answers()}
            form.answers = answers

            # Unticking "I have a Master's" also detaches its certificate, so a
            # document cannot outlive the qualification it belongs to.
            for question_key in step_form.gated_off_file_keys():
                for upload in form.files.filter(question_key=question_key):
                    upload.delete()

            next_key = schema.next_step_key(step_key, answers)
            if next_key is None:
                form.is_submitted = True
                form.submitted_at = timezone.now()
                form.current_step = step_key
                form.save()
                logger.info(
                    'employee_form.submitted form=%s resume=%s', form.pk, form.resume_id
                )
                return redirect('employee_form:done', token=token)

            form.current_step = next_key
            form.save()
            return redirect('employee_form:step', token=token, step_key=next_key)
        form_errors_to_messages(request, step_form)
    else:
        step_form = StepForm(
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers},
        )

    # Recomputed: a failed POST may still have stored some uploads above, and the
    # re-rendered step must show those as already on file.
    uploaded_keys = set(
        form.files.filter(question_key__in=schema.FILE_QUESTION_KEYS)
        .values_list('question_key', flat=True)
    )

    # Section D shows its role questions on this same page, so the template gets
    # the step's own blocks and the absorbed ones separately -- only the absorbed
    # part is re-fetched when the department changes.
    branch_key = next(
        (k for k in schema.INLINE_BRANCHES if k in step_form.fields), None
    )
    own_keys = {q['key'] for q in schema.get_step(step_key)['questions']}
    all_groups = step_form.field_groups()
    if branch_key:
        own_groups = [
            g for g in all_groups
            if all(i['question']['key'] in own_keys for i in g['fields'])
        ]
        branch_groups = [g for g in all_groups if g not in own_groups]
        branch_target = schema.inline_target(step_key, {**answers, **(
            {branch_key: request.POST.get(branch_key)} if request.method == 'POST' else {}
        )})
        branch_section = (
            schema.get_step(branch_target)['section'] if branch_target else ''
        )
    else:
        own_groups, branch_groups, branch_section = all_groups, [], ''

    return render(request, 'employee_form/step.html', {
        'form_obj': form,
        'step': schema.get_step(step_key),
        'step_form': step_form,
        'own_groups': own_groups,
        'branch_key': branch_key,
        'branch_groups': branch_groups,
        'branch_section': branch_section,
        'step_key': step_key,
        'previous_step': form.previous_step(step_key),
        'step_number': form.path.index(step_key) + 1,
        'total_steps': len(form.path),
        'uploaded_keys': uploaded_keys,
        # Marked in the template so a prefilled value reads as "check this",
        # not as something already confirmed by the candidate.
        'prefilled_keys': set(prefill),
        'is_final': schema.next_step_key(step_key, answers) is None,
    })


def role_fields(request, token, step_key):
    """The role-section block for the department currently chosen (htmx).

    Section D renders its role questions on the same page, but the server is what
    knows which questions a department maps to -- so the select fetches this
    fragment on change instead of shipping all six sections as hidden inputs.
    """
    # An htmx fragment, never a page someone lands on, so an unknown token is a
    # plain 404 rather than the "link not valid" page.
    try:
        form = _get_form(token)
    except InvalidLink:
        raise Http404('Unknown form.')

    if not form.is_open or not _is_verified(request, form):
        raise Http404

    if step_key not in schema.INLINE_BRANCHES:
        raise Http404('That step has no role section.')

    answers = form.answers or {}
    # The chosen value comes from the live select, not from what is saved.
    chosen = {**answers, step_key: request.GET.get(step_key, '')}
    target = schema.inline_target(step_key, chosen)

    step_form = StepForm(
        step_key=step_key, already_uploaded=(),
        initial={**pending_prefill(form.resume, answers), **answers,
                 step_key: chosen[step_key]},
    )
    # Only the absorbed section's blocks; the select itself stays on the page.
    own_keys = {q['key'] for q in schema.get_step(step_key)['questions']}
    groups = [
        group for group in step_form.field_groups()
        if any(item['question']['key'] not in own_keys for item in group['fields'])
    ]

    return render(request, 'employee_form/partials/role_fields.html', {
        'form_obj': form,
        'groups': groups,
        'section': schema.get_step(target)['section'] if target else '',
        'prefilled_keys': set(),
        'uploaded_keys': set(),
    })


@_candidate_page
def done(request, token):
    form = _get_form(token)
    if not form.is_submitted:
        return redirect('employee_form:entry', token=token)
    return render(request, 'employee_form/done.html', {'form_obj': form})


# ── Recruiter-facing (portal) ────────────────────────────────────────────
@login_required
def detail(request, uuid):
    """Full read-only view of a candidate's submitted form."""
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    form = getattr(resume, 'employee_form', None)
    if form is None:
        messages.info(
            request, f'No information form has been sent to {resume.candidate_name} yet.'
        )
        return redirect('core:resume_detail', uuid=uuid)

    documents = form.documents()

    return render(request, 'employee_form/detail.html', {
        'resume': resume,
        'form_obj': form,
        'review': review.build(form),
        'documents': documents,
        # Serialised for the viewer via {{ ... |json_script }} rather than
        # hand-built in the template: filenames are candidate-supplied, and
        # assembling JS string literals from them invites an escaping mistake.
        'documents_json': [
            {
                'label': doc.label,
                'name': doc.original_name or 'Document',
                'size': doc.size_display,
                'kind': doc.kind,
                'ext': doc.extension,
                'view': doc.view_url,
                'download': doc.file.url,
            }
            for doc in documents
        ],
    })


@login_required
@require_POST
def send(request, uuid):
    """Recruiter-triggered send or re-send of the invitation."""
    resume = get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)
    existing = getattr(resume, 'employee_form', None)
    resend = existing is not None

    try:
        issue_invite(resume, user=request.user, resend=resend)
    except InviteError as exc:
        messages.error(request, str(exc))
    else:
        verb = 'queued again' if resend else 'queued'
        messages.success(
            request,
            f'Information form invitation {verb} for {resume.email}. '
            f'The link stays valid for {EmployeeForm.TOKEN_VALIDITY_DAYS} days.',
        )

    return redirect('core:resume_detail', uuid=uuid)
