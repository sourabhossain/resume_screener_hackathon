import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.documents import StoredDocumentMixin, display_date

from . import schema



class CandidateMapping(models.Model):
    """One Candidate Mapping & Assessment per candidate.

    Answers live in a JSONField keyed by `schema.QUESTIONS_BY_KEY`, as in both
    sibling forms. Prepared by HR or the interview panel, never by the candidate,
    so the record carries who assessed and who signed off.
    """

    resume = models.OneToOneField(
        'core.Resume',
        on_delete=models.CASCADE,
        related_name='candidate_mapping',
    )

    answers = models.JSONField(default=dict, blank=True)

    # Which sections have been saved at least once. Assessors move around the
    # form as information arrives, so progress is a set, not a pointer.
    completed_steps = models.JSONField(default=list, blank=True)

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='candidate_mappings_submitted',
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='candidate_mappings_started',
    )
    last_saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='candidate_mappings_saved',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'candidate mapping'
        verbose_name_plural = 'candidate mappings'

    def __str__(self):
        return f"Candidate mapping for {self.resume.candidate_name}"

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
        """Every section saved at least once, so sign-off cannot skip one."""
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
            out.append({
                'key': step_key,
                'section': step['section'],
                'title': step['title'],
                'complete': self.is_step_complete(step_key),
                'rows': [
                    {
                        'key': question['key'],
                        'label': question['label'],
                        'type': question['type'],
                        'value': self.display_value(question),
                        'files': files_by_key.get(question['key'], []),
                        'answered': self._is_answered(question, files_by_key),
                    }
                    for question in schema.questions(step_key)
                ],
            })
        return out

    # ── Headline outcome, for the recruiter-facing card ───────────────────
    @property
    def outcome_label(self) -> str:
        question = schema.QUESTIONS_BY_KEY.get('mapping_outcome')
        return self.display_value(question) if question else ''

    # Risk question -> what to call it when the answer is a concern.
    _FINDING_LABELS = {
        'adverse_record': 'Adverse record',
        'performance_concerns': 'Performance concerns',
        'integrity_issues': 'Integrity issues',
        'short_tenure_pattern': 'Short tenures',
    }

    @property
    def flagged_findings(self) -> list:
        """Risk questions whose answer is a concern."""
        answers = self.answers or {}
        found = [label for key, label in self._FINDING_LABELS.items()
                 if answers.get(key) == 'yes']
        # Involuntary separation is a flag in its own right, even where every
        # question above came back clean.
        if answers.get('separation_type') == 'terminated':
            found.append('Involuntary separation')
        return found

    @property
    def risk_summary(self) -> str:
        """One honest line for the card and the review header.

        "None flagged" is only said once the questions have actually been
        answered. Before that the line says so, rather than letting an
        unperformed check read as a clean result.
        """
        answers = self.answers or {}
        if any(answers.get(key) in (None, '', []) for key in self._FINDING_LABELS):
            return 'Not assessed'
        return ', '.join(self.flagged_findings) or 'None flagged'


def upload_to(instance, filename):
    """Storage path for one uploaded document.

    Lives under the HR-only media directory: this form holds adverse findings,
    and its assessor signature is as personal as the candidate's own. See
    `core.views.serve_protected_media`.
    """
    return (f"hr_verifications/candidate_mappings/{instance.mapping_id}/"
            f"{uuid.uuid4().hex}/{filename}")


class CandidateMappingFile(StoredDocumentMixin, models.Model):
    """A document uploaded against one question (the assessor signature)."""

    mapping = models.ForeignKey(
        CandidateMapping, on_delete=models.CASCADE, related_name='files'
    )
    question_key = models.CharField(max_length=100)
    file = models.FileField(upload_to=upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='candidate_mapping_uploads',
    )

    class Meta:
        ordering = ['question_key', 'uploaded_at']
        indexes = [
            models.Index(fields=['mapping', 'question_key'],
                         name='cm_file_form_question_idx'),
        ]

    def __str__(self):
        return f"{self.question_key}: {self.original_name or self.file.name}"

    @property
    def label(self) -> str:
        question = schema.QUESTIONS_BY_KEY.get(self.question_key)
        return question['label'] if question else self.question_key
