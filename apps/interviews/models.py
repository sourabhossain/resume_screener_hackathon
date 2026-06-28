import uuid
from datetime import timedelta
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteModel

EVALUATION_CRITERIA = [
    ('educational_background',        'Educational Background'),
    ('job_related_knowledge',         'Job Related Knowledge'),
    ('job_related_skills',            'Job Related Skills'),
    ('relevant_work_experience',      'Relevant Work Experience'),
    ('related_training_certifications', 'Related Training / Certifications'),
    ('verbal_communication',          'Verbal Communication'),
    ('presentation_skills',           'Presentation Skills'),
    ('interpersonal_skills_team_play','Interpersonal Skills / Team Play'),
    ('knowledge_of_organization',     'Knowledge of Organization'),
    ('knowledge_of_industry',         'Knowledge of Industry'),
    ('knowledge_of_modern_concepts',  'Knowledge of Modern Concepts'),
    ('adaptability',                  'Adaptability'),
    ('enthusiasm',                    'Enthusiasm'),
    ('potential_to_grow',             'Potential to Grow'),
    ('initiative',                    'Initiative'),
    ('time_management',               'Time Management'),
    ('other_job_experience',          'Other Job Experience'),
    ('managing_customers',            'Managing Customers'),
    ('preparedness',                  'Preparedness'),
    ('dressed_appropriately',         'Dressed Appropriately'),
]

CRITERIA_KEYS = [k for k, _ in EVALUATION_CRITERIA]
MAX_SCORE = len(CRITERIA_KEYS) * 5  # 100


class Interview(SoftDeleteModel):
    PHASE_CHOICES = [('1', 'Interview 1'), ('2', 'Interview 2'), ('3', 'Interview 3')]
    STATUS_CHOICES = [('scheduled', 'Scheduled'), ('completed', 'Completed'), ('cancelled', 'Cancelled')]

    resume = models.ForeignKey(
        'core.Resume', on_delete=models.CASCADE, related_name='interviews'
    )
    phase = models.CharField(max_length=5, choices=PHASE_CHOICES, default='1')
    scheduled_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"{self.resume.candidate_name} - Interview {self.phase} ({self.scheduled_date})"

    def soft_delete(self):
        """Soft-delete the interview and expire its outstanding evaluation links.

        InterviewEvaluation is a plain model (no soft delete), and its public
        token URL stays reachable until expiry — so deleting an interview must
        also invalidate any unsubmitted evaluation tokens, or panelists could
        still open a form for a removed interview.
        """
        super().soft_delete()
        self.evaluations.filter(is_submitted=False).update(token_expires_at=self.deleted_at)

    @property
    def submitted_count(self):
        return self.evaluations.filter(is_submitted=True).count()

    @property
    def pending_count(self):
        return self.evaluations.filter(is_submitted=False).count()

    def avg_score(self):
        evals = self.evaluations.filter(is_submitted=True)
        if not evals.exists():
            return None
        totals = [e.total_score for e in evals if e.total_score is not None]
        return round(sum(totals) / len(totals)) if totals else None


class InterviewEvaluation(models.Model):
    RECOMMENDATION_CHOICES = [
        ('yes', 'Yes - Hire'),
        ('no', 'No - Reject'),
        ('maybe', 'Maybe - Further Review'),
    ]

    TOKEN_VALIDITY_DAYS = 30

    interview = models.ForeignKey(Interview, on_delete=models.CASCADE, related_name='evaluations')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    # Interviewer info
    interviewer_name = models.CharField(max_length=200)
    interviewer_position = models.CharField(max_length=200, blank=True)
    interviewer_department = models.CharField(max_length=200, blank=True)

    # Scores: {"educational_background": 4, "job_related_knowledge": 3, ...}
    scores = models.JSONField(default=dict, blank=True)

    # Summary
    impression = models.CharField(max_length=200, blank=True)
    recommendation = models.CharField(max_length=10, choices=RECOMMENDATION_CHOICES, blank=True)
    priority_rank = models.PositiveSmallIntegerField(null=True, blank=True)

    # Suggestions (checkboxes)
    another_phase_required = models.BooleanField(default=False)
    hard_negotiation = models.BooleanField(default=False)
    suitable_other_dept = models.BooleanField(default=False)
    suitable_higher_position = models.BooleanField(default=False)
    suitable_junior_position = models.BooleanField(default=False)

    additional_notes = models.TextField(blank=True)

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if not self.pk and not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(days=self.TOKEN_VALIDITY_DAYS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.interviewer_name} → {self.interview}"

    @property
    def is_expired(self):
        if self.is_submitted:
            return False
        return self.token_expires_at is not None and timezone.now() > self.token_expires_at

    @property
    def days_until_expiry(self):
        if self.is_submitted or self.is_expired or self.token_expires_at is None:
            return None
        delta = self.token_expires_at - timezone.now()
        return max(0, delta.days)

    @property
    def total_score(self):
        if not self.scores:
            return None
        vals = [v for v in self.scores.values() if isinstance(v, int) and 1 <= v <= 5]
        return sum(vals) if vals else None

    @property
    def percentage(self):
        if not self.scores:
            return None
        vals = [v for v in self.scores.values() if isinstance(v, int) and 1 <= v <= 5]
        if not vals:
            return None
        # Scale against the number of criteria actually scored (not the fixed
        # 100-point ceiling) so a partially-scored evaluation — e.g. one created
        # via the admin or a data import rather than the strict public form —
        # isn't silently dragged down by dividing a partial total by 100.
        return round((sum(vals) / (len(vals) * 5)) * 100)

    @property
    def impression_label(self):
        pct = self.percentage
        if pct is None:
            return ''
        if pct >= 80:
            return 'Good'
        if pct >= 60:
            return 'Satisfactory'
        return 'Unsatisfactory'

    @property
    def scores_with_labels(self):
        """Returns list of (label, score) for template rendering."""
        result = []
        for key, label in EVALUATION_CRITERIA:
            score = self.scores.get(key) if self.scores else None
            result.append((label, score))
        return result

    @property
    def public_url_token(self):
        return str(self.token)
