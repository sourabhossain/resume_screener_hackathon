"""HR-only Candidate Mapping & Assessment Document.

Same shape as the HR verification form: every section reachable at any time,
saved on its own, sign-off gated on having saved them all. The two are separate
records on purpose -- the mapping is an assessment of the candidate's previous
role, the verification is a check of the facts, and either can be in progress
while the other has not started.
"""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.form_utils import form_errors_to_messages
from apps.core.models import Resume

from . import schema
from .forms import StepForm
from .models import CandidateMapping, CandidateMappingFile
from .prefill import pending_prefill

logger = logging.getLogger(__name__)

# The mapping is drawn from the CV and the interview, so it opens when the
# candidate reaches interviewing and stays open afterwards -- an assessment
# finished during offer stage must still be recordable.
STATUSES_ALLOWING_START = frozenset({'interviewing', 'offer_extended', 'hired'})


def _hr_admin_required(view_fn):
    """HR staff only.

    "Confidential — HR Use Only" on the source document, and it records adverse
    professional findings. `is_staff` is the existing per-user flag; superusers
    pass too.
    """
    @wraps(view_fn)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(
                request, 'Candidate mapping is restricted to HR administrators.'
            )
            return redirect('core:dashboard')
        return view_fn(request, *args, **kwargs)
    return wrapper


def _get_resume(uuid):
    return get_object_or_404(Resume.objects.select_related('job'), uuid=uuid)


def _existing(resume):
    return getattr(resume, 'candidate_mapping', None)


def _require_record(resume):
    """The mapping, or a 404.

    Once started it stays reachable whatever the candidate's status becomes: an
    assessment already recorded must not be stranded because someone moved the
    candidate on.
    """
    mapping = _existing(resume)
    if mapping is None:
        raise Http404('No candidate mapping has been started for this candidate.')
    return mapping


@_hr_admin_required
@require_POST
def start(request, uuid):
    resume = _get_resume(uuid)

    existing = _existing(resume)
    if existing is not None:
        return redirect('candidate_mapping:step', uuid=uuid,
                        step_key=existing.next_unfinished_step)

    if resume.recruiter_status not in STATUSES_ALLOWING_START:
        messages.error(
            request,
            'Candidate mapping opens once the candidate reaches Interviewing.',
        )
        return redirect('core:resume_detail', uuid=uuid)

    mapping = CandidateMapping.objects.create(
        resume=resume, started_by=request.user, last_saved_by=request.user
    )
    logger.info(
        'candidate_mapping.started mapping=%s resume=%s by=%s',
        mapping.pk, resume.pk, request.user.pk,
    )
    messages.success(request, 'Candidate mapping started.')
    return redirect('candidate_mapping:step', uuid=uuid, step_key=schema.FIRST_STEP)


@_hr_admin_required
def detail(request, uuid):
    resume = _get_resume(uuid)
    mapping = _require_record(resume)

    return render(request, 'candidate_mapping/detail.html', {
        'resume': resume,
        'mapping': mapping,
        'sections': mapping.answered_sections(),
        'documents': list(mapping.files.all()),
        'declaration_text': schema.DECLARATION_TEXT,
    })


@_hr_admin_required
def step(request, uuid, step_key):
    resume = _get_resume(uuid)
    mapping = _require_record(resume)

    if schema.get_step(step_key) is None:
        raise Http404('Unknown form section.')

    if mapping.is_submitted:
        messages.info(
            request, 'This mapping is signed off and can no longer be edited.'
        )
        return redirect('candidate_mapping:detail', uuid=uuid)

    answers = mapping.answers or {}
    uploaded_keys = set(
        mapping.files.filter(question_key__in=schema.FILE_QUESTION_KEYS)
        .values_list('question_key', flat=True)
    )
    prefill = pending_prefill(mapping, user=request.user)

    if request.method == 'POST':
        step_form = StepForm(
            request.POST, request.FILES,
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers},
        )
        valid = step_form.is_valid()

        # Keep uploads that passed validation even when the section did not: a
        # browser cannot repopulate a file input, and a drawn signature would
        # otherwise have to be drawn again.
        for question_key, uploads in step_form.uploads():
            if step_form.errors.get(question_key):
                continue
            mapping.files.filter(question_key=question_key).delete()
            for upload in uploads:
                CandidateMappingFile.objects.create(
                    mapping=mapping,
                    question_key=question_key,
                    file=upload,
                    original_name=upload.name[:255],
                    size_bytes=getattr(upload, 'size', 0) or 0,
                    uploaded_by=request.user,
                )

        if valid:
            # Re-read under a row lock before merging: `answers` holds every
            # section, so two assessors saving different sections at once would
            # otherwise each write the copy they loaded.
            with transaction.atomic():
                locked = (CandidateMapping.objects
                          .select_for_update().get(pk=mapping.pk))
                locked.answers = {
                    **(locked.answers or {}), **step_form.storable_answers()
                }
                locked.mark_step_complete(step_key)
                locked.last_saved_by = request.user
                locked.save()
            mapping = locked
            logger.info(
                'candidate_mapping.section_saved mapping=%s section=%s by=%s',
                mapping.pk, step_key, request.user.pk,
            )

            messages.success(request, f"{schema.get_step(step_key)['title']} saved.")
            next_key = schema.next_step_key(step_key)
            if next_key is None:
                return redirect('candidate_mapping:detail', uuid=uuid)
            return redirect('candidate_mapping:step', uuid=uuid, step_key=next_key)

        form_errors_to_messages(request, step_form)
    else:
        step_form = StepForm(
            step_key=step_key, already_uploaded=uploaded_keys,
            initial={**prefill, **answers},
        )

    return render(request, 'candidate_mapping/step.html', {
        'resume': resume,
        'mapping': mapping,
        'form': step_form,
        'step': schema.get_step(step_key),
        'step_key': step_key,
        'step_number': schema.step_number(step_key),
        'total_steps': schema.TOTAL_STEPS,
        'previous_step': schema.previous_step_key(step_key),
        'is_final': schema.next_step_key(step_key) is None,
        'groups': step_form.field_groups(),
        'uploaded_keys': uploaded_keys,
        # The shared field template's prefill badge is candidate-facing copy; the
        # section banner says where these values come from instead.
        'prefilled_keys': set(),
        'conditional_rules': schema.conditional_rules(step_key),
        'show_safeguard': step_key == 'risk',
        'safeguard_text': schema.SAFEGUARD_TEXT,
        'declaration_text': (schema.DECLARATION_TEXT
                             if step_key == schema.FINAL_STEP else ''),
        'sections': [
            {
                'key': key,
                'title': schema.get_step(key)['title'],
                'complete': mapping.is_step_complete(key),
                'current': key == step_key,
            }
            for key in schema.STEP_KEYS
        ],
    })


@_hr_admin_required
@require_POST
def submit(request, uuid):
    """Assessor declaration and sign-off. Locks the record."""
    resume = _get_resume(uuid)
    mapping = _require_record(resume)

    if mapping.is_submitted:
        messages.info(request, 'This mapping is already signed off.')
        return redirect('candidate_mapping:detail', uuid=uuid)

    if not mapping.can_submit:
        missing = [schema.get_step(key)['title'] for key in schema.STEP_KEYS
                   if not mapping.is_step_complete(key)]
        messages.error(
            request,
            'Save every section before signing off. Still outstanding: '
            + ', '.join(missing) + '.',
        )
        return redirect('candidate_mapping:step', uuid=uuid,
                        step_key=mapping.next_unfinished_step)

    mapping.submit(user=request.user)
    mapping.save()
    logger.info(
        'candidate_mapping.signed_off mapping=%s resume=%s by=%s',
        mapping.pk, resume.pk, request.user.pk,
    )
    messages.success(request, 'Candidate mapping signed off.')
    return redirect('candidate_mapping:detail', uuid=uuid)
