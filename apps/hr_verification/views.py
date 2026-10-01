"""HR-only Background Verification & Joining Form.

Not a wizard: every section is reachable at any time and saves on its own.
Sign-off needs every section saved and re-checks every visible required answer.
"""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.form_logic import context_answers, page_rules
from apps.core.form_utils import form_errors_to_messages
from apps.core.models import Resume

from . import schema
from .forms import StepForm
from .models import HRVerification, HRVerificationFile
from .prefill import pending_prefill

logger = logging.getLogger(__name__)

# The point in the pipeline from which a background check makes sense. The
# Offer & Joining Clearance section covers events that happen after
# interviewing, so the gate has to stay open past it -- otherwise moving a
# candidate to "Offer Extended" would lock HR out of the section that records
# the offer.
# From Selected on (see apps.core.status).
from apps.core.status import POST_SELECTION as STATUSES_ALLOWING_START  # noqa: E402


def _hr_admin_required(view_fn):
    """HR staff only.

    This form holds police verification outcomes, adverse findings and reasons
    for leaving -- material every recruiter should not see. `is_staff` is the
    existing per-user flag in user management; superusers pass too.
    """
    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(
                request,
                'HR background verification is restricted to HR administrators.',
            )
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapper


def _get_resume(uuid):
    return get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)


def _existing(resume):
    return getattr(resume, 'hr_verification', None)


def _missing_summary(missing):
    """[(step_key, question)] grouped per section for display."""
    out = []
    for step_key, question in missing:
        if not out or out[-1]['key'] != step_key:
            out.append({'key': step_key, 'title': schema.get_step(step_key)['title'],
                        'labels': []})
        out[-1]['labels'].append(question['label'])
    return out


def _may_start(resume) -> bool:
    return resume.recruiter_status in STATUSES_ALLOWING_START


def _require_record(resume):
    """The verification, or a 404.

    Once started, the record stays reachable whatever the candidate's status
    becomes later. A verification that has already collected findings must not
    become unreachable because someone moved the candidate to Rejected -- that
    would strand the very record the decision rests on.
    """
    verification = _existing(resume)
    if verification is None:
        raise Http404('No HR verification has been started for this candidate.')
    return verification


@_hr_admin_required
@require_POST
def start(request, uuid):
    """Open a verification record for a candidate who has reached interviewing."""
    resume = _get_resume(uuid)

    existing = _existing(resume)
    if existing is not None:
        return redirect('hr_verification:step', uuid=uuid,
                        step_key=existing.next_unfinished_step)

    if not _may_start(resume):
        messages.error(
            request,
            'HR background verification opens once the candidate reaches '
            'Selected.',
        )
        return redirect('core:resume_detail', uuid=uuid)

    verification = HRVerification.objects.create(
        resume=resume, started_by=request.user, last_saved_by=request.user
    )
    logger.info(
        'hr_verification.started verification=%s resume=%s by=%s',
        verification.pk, resume.pk, request.user.pk,
    )
    messages.success(request, 'HR background verification started.')
    return redirect('hr_verification:step', uuid=uuid, step_key=schema.FIRST_STEP)


@_hr_admin_required
def detail(request, uuid):
    """Read-only review of everything recorded so far."""
    resume = _get_resume(uuid)
    verification = _require_record(resume)

    missing = [] if verification.is_submitted else verification.missing_required()
    return render(request, 'hr_verification/detail.html', {
        'resume': resume,
        'verification': verification,
        'sections': verification.answered_sections(),
        'documents': list(verification.files.all()),
        'missing': _missing_summary(missing),
        'consent_declined': _consent_declined(resume),
    })


def _consent_declined(resume) -> bool:
    form = getattr(resume, 'employee_form', None)
    return bool(form and (form.answers or {}).get('verification_consent') == 'no')


@_hr_admin_required
def step(request, uuid, step_key):
    """Render and accept one section."""
    resume = _get_resume(uuid)
    verification = _require_record(resume)

    if schema.get_step(step_key) is None:
        raise Http404('Unknown form section.')

    if verification.is_submitted:
        messages.info(
            request, 'This verification is signed off and can no longer be edited.'
        )
        return redirect('hr_verification:detail', uuid=uuid)

    answers = verification.answers or {}
    uploaded_keys = set(
        verification.files.filter(question_key__in=schema.FILE_QUESTION_KEYS)
        .values_list('question_key', flat=True)
    )
    prefill = pending_prefill(verification, user=request.user)

    if request.method == 'POST':
        step_form = StepForm(
            request.POST, request.FILES,
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers}, context=answers,
        )
        valid = step_form.is_valid()

        # Keep uploads that passed validation even when the section as a whole
        # did not. A browser cannot repopulate a file input, so otherwise one
        # mistyped date would make HR re-attach the agency report.
        for question_key, uploads in step_form.uploads():
            if step_form.errors.get(question_key):
                continue
            # Replacing an answer replaces its documents.
            verification.files.filter(question_key=question_key).delete()
            for upload in uploads:
                HRVerificationFile.objects.create(
                    verification=verification,
                    question_key=question_key,
                    file=upload,
                    original_name=upload.name[:255],
                    size_bytes=getattr(upload, 'size', 0) or 0,
                    uploaded_by=request.user,
                )

        if valid:
            # Re-read under a row lock before merging. `answers` holds every
            # section, so two HR users saving different sections at the same time
            # would otherwise each write the copy they loaded and silently drop
            # the other's work.
            with transaction.atomic():
                locked = (HRVerification.objects
                          .select_for_update()
                          .get(pk=verification.pk))
                locked.answers = {
                    **(locked.answers or {}), **step_form.storable_answers()
                }
                locked.mark_step_complete(step_key)
                locked.last_saved_by = request.user
                locked.save()
                verification.files.filter(
                    question_key__in=step_form.hidden_file_keys()).delete()
            verification = locked
            logger.info(
                'hr_verification.section_saved verification=%s section=%s by=%s',
                verification.pk, step_key, request.user.pk,
            )

            saved = schema.get_step(step_key)['title']
            next_key = schema.next_step_key(step_key)
            if next_key is None:
                messages.success(request, f'{saved} saved.')
                return redirect('hr_verification:detail', uuid=uuid)
            messages.success(request, f'{saved} saved.')
            return redirect('hr_verification:step', uuid=uuid, step_key=next_key)

        form_errors_to_messages(request, step_form)
    else:
        step_form = StepForm(
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers}, context=answers,
        )

    uploaded_keys = set(
        verification.files.filter(question_key__in=schema.FILE_QUESTION_KEYS)
        .values_list('question_key', flat=True)
    )
    page_questions = schema.questions(step_key)

    return render(request, 'hr_verification/step.html', {
        'consent_declined': _consent_declined(resume),
        'resume': resume,
        'verification': verification,
        'form': step_form,
        'step': schema.get_step(step_key),
        'step_key': step_key,
        'step_number': schema.step_number(step_key),
        'total_steps': schema.TOTAL_STEPS,
        'previous_step': schema.previous_step_key(step_key),
        'is_final': schema.next_step_key(step_key) is None,
        'groups': step_form.field_groups(),
        'uploaded_keys': uploaded_keys,
        'logic_rules': page_rules(page_questions),
        'logic_context': context_answers(page_questions, verification.answers or {}),
        # The shared prefill badge is candidate-facing copy.
        'prefilled_keys': set(),
        'sections': [
            {
                'key': key,
                'title': schema.get_step(key)['title'],
                'complete': verification.is_step_complete(key),
                'current': key == step_key,
            }
            for key in schema.STEP_KEYS
        ],
    })


@_hr_admin_required
@require_POST
def submit(request, uuid):
    """Final sign-off. Locks the record."""
    resume = _get_resume(uuid)
    verification = _require_record(resume)

    if verification.is_submitted:
        messages.info(request, 'This verification is already signed off.')
        return redirect('hr_verification:detail', uuid=uuid)

    if not verification.can_submit:
        missing = [
            schema.get_step(key)['title'] for key in schema.STEP_KEYS
            if not verification.is_step_complete(key)
        ]
        messages.error(
            request,
            'Save every section before signing off. Still outstanding: '
            + ', '.join(missing) + '.',
        )
        return redirect('hr_verification:step', uuid=uuid,
                        step_key=verification.next_unfinished_step)

    missing = verification.missing_required()
    if missing:
        summary = _missing_summary(missing)
        listed = '; '.join(f"{item['title']}: {', '.join(item['labels'])}"
                           for item in summary)
        messages.error(request, 'Cannot sign off yet. Still required — ' + listed + '.')
        return redirect('hr_verification:step', uuid=uuid, step_key=missing[0][0])

    verification.submit(user=request.user)
    # Only the sign-off columns: a bare save() would write back the `answers`
    # and `completed_steps` this request read earlier, losing a section another
    # reviewer saved in the meantime.
    verification.save(update_fields=['is_submitted', 'submitted_at', 'submitted_by',
                                'updated_at'])
    logger.info(
        'hr_verification.signed_off verification=%s resume=%s by=%s',
        verification.pk, resume.pk, request.user.pk,
    )
    from apps.core.status import advance
    advance(resume, 'bgv_completed', reason='HR verification signed off', user=request.user)
    if (verification.answers or {}).get('offer_letter_issued') == 'yes':
        advance(resume, 'offer_extended', reason='Offer letter recorded as issued', user=request.user)
    messages.success(request, 'HR background verification signed off.')
    return redirect('hr_verification:detail', uuid=uuid)
