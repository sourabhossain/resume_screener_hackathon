import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.documents import StoredDocumentMixin, display_date

from . import schema



class HRVerification(models.Model):
    """One HR Background Verification & Joining Clearance record per candidate.

    Answers live in a JSONField keyed by `schema.QUESTIONS_BY_KEY` for the same
    reason the Employee Information Form does it: 201 questions would be 201
    mostly-null columns, and a migration per wording change.

    Unlike that form this one is internal -- no token, no OTP. Access is a
    logged-in HR user (see `views._hr_admin_required`), so the record carries who
    touched it instead of how they proved who they were.
    """

    resume = models.OneToOneField(
        'core.Resume',
        on_delete=models.CASCADE,
        related_name='hr_verification',
    )

    answers = models.JSONField(default=dict, blank=True)

    # Which sections have been saved at least once. The form is not a wizard for
    # HR -- they jump around -- so "progress" cannot be a single pointer the way
    # the candidate form's current_step is.
    completed_steps = models.JSONField(default=list, blank=True)

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='hr_verifications_submitted',
    )

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='hr_verifications_started',
    )
    last_saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='hr_verifications_saved',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'HR verification'
        verbose_name_plural = 'HR verifications'

    def __str__(self):
        return f"HR verification for {self.resume.candidate_name}"

    # ── Progress ─────────────────────────────────────────────────────────
    @property
    def total_steps(self) -> int:
        return schema.TOTAL_STEPS

    @property
    def completed_count(self) -> int:
        # Intersected with the schema so a section removed from the form stops
        # counting towards progress instead of inflating it forever.
        return len(set(self.completed_steps or []) & set(schema.STEP_KEYS))

    def is_step_complete(self, step_key) -> bool:
        return step_key in (self.completed_steps or [])

    def mark_step_complete(self, step_key):
        done = list(self.completed_steps or [])
        if step_key not in done:
            done.append(step_key)
            self.completed_steps = done

    @property
    def next_unfinished_step(self) -> str:
        for key in schema.STEP_KEYS:
            if not self.is_step_complete(key):
                return key
        return schema.FINAL_STEP

    @property
    def status_label(self) -> str:
        if self.is_submitted:
            return 'Signed off'
        if self.completed_count:
            return 'In progress'
        return 'Not started'

    @property
    def can_submit(self) -> bool:
        """Every section saved at least once, so sign-off cannot skip a section."""
        return self.completed_count >= schema.TOTAL_STEPS

    def submit(self, user=None):
        self.is_submitted = True
        self.submitted_at = timezone.now()
        self.submitted_by = user

    # ── Reading answers back ─────────────────────────────────────────────
    def display_value(self, question):
        """Stored answer rendered for display: choice labels, not raw values."""
        if question['type'] in schema.FILE_TYPES:
            return ''
        raw = (self.answers or {}).get(question['key'])
        if raw in (None, '', []):
            return ''
        if question['type'] == schema.CHECKBOX:
            return ', '.join(schema.choice_label(question['key'], v) for v in raw)
        if question['type'] in schema.CHOICE_TYPES:
            return schema.choice_label(question['key'], raw)
        if question['type'] == schema.DATE:
            return display_date(raw)
        return raw

    def _is_answered(self, question, files_by_key) -> bool:
        """Whether a question carries an answer, a stored file counting as one.

        Not a truth test on the displayed value: a numeric 0 -- no direct
        reports, a notice period of none -- is an answer, and truthiness would
        drop the row off the review page entirely.
        """
        if files_by_key.get(question['key']):
            return True
        return self.display_value(question) != ''

    def answered_sections(self):
        """Every section with its answers, for the read-only review page."""
        files_by_key = {}
        for upload in self.files.all():
            files_by_key.setdefault(upload.question_key, []).append(upload)

        out = []
        for step_key in schema.STEP_KEYS:
            step = schema.get_step(step_key)
            rows = [
                {
                    'key': question['key'],
                    'label': question['label'],
                    'type': question['type'],
                    'value': self.display_value(question),
                    'files': files_by_key.get(question['key'], []),
                    'answered': self._is_answered(question, files_by_key),
                }
                for question in schema.questions(step_key)
            ]
            out.append({
                'key': step_key,
                'section': step['section'],
                'title': step['title'],
                'complete': self.is_step_complete(step_key),
                'rows': rows,
            })
        return out

    # ── Headline outcomes, for the recruiter-facing card ──────────────────
    def _label(self, key):
        question = schema.QUESTIONS_BY_KEY.get(key)
        return self.display_value(question) if question else ''

    @property
    def risk_rating_label(self) -> str:
        return self._label('risk_rating')

    @property
    def recommendation_label(self) -> str:
        return self._label('verification_recommendation')

    @property
    def joining_clearance_label(self) -> str:
        return self._label('final_joining_clearance')


def upload_to(instance, filename):
    """Storage path for one uploaded document.

    A per-upload random segment keeps paths unguessable and stops two files of
    the same name from colliding. Served only through the login-protected media
    view, never from a public URL.
    """
    return f"hr_verifications/{instance.verification_id}/{uuid.uuid4().hex}/{filename}"


class HRVerificationFile(StoredDocumentMixin, models.Model):
    """A document uploaded against one question (the agency report, so far)."""

    verification = models.ForeignKey(
        HRVerification, on_delete=models.CASCADE, related_name='files'
    )
    question_key = models.CharField(max_length=100)
    file = models.FileField(upload_to=upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='hr_verification_uploads',
    )

    class Meta:
        ordering = ['question_key', 'uploaded_at']
        indexes = [
            models.Index(fields=['verification', 'question_key'],
                         name='hrv_file_form_question_idx'),
        ]

    def __str__(self):
        return f"{self.question_key}: {self.original_name or self.file.name}"

    @property
    def label(self) -> str:
        question = schema.QUESTIONS_BY_KEY.get(self.question_key)
        return question['label'] if question else self.question_key
