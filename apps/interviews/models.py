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
    SCHEDULED, COMPLETED, CANCELLED = 'scheduled', 'completed', 'cancelled'
    STATUS_CHOICES = [(SCHEDULED, 'Scheduled'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled')]

    resume = models.ForeignKey(
        'core.Resume', on_delete=models.CASCADE, related_name='interviews'
    )
    IN_PERSON, ONLINE = 'in_person', 'online'
    MODE_CHOICES = [(IN_PERSON, 'In person'), (ONLINE, 'Online')]
    DURATION_CHOICES = [(30, '30 minutes'), (45, '45 minutes'), (60, '1 hour'),
                        (90, '1 hour 30 minutes'), (120, '2 hours')]

    phase = models.CharField(max_length=5, choices=PHASE_CHOICES, default='1')
    scheduled_date = models.DateField()
    # Blank only on interviews scheduled before the time was asked for.
    scheduled_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(choices=DURATION_CHOICES, default=60)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=IN_PERSON)
    # A room or address in person, a meeting link online.
    location = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    # Internal: never sent to the candidate.
    notes = models.TextField(blank=True)

    # Raised on every reschedule: calendars match an update to the invitation
    # by UID and keep whichever carries the higher SEQUENCE.
    schedule_version = models.PositiveSmallIntegerField(default=0)

    notify_candidate = models.BooleanField(default=True)
    candidate_notified_at = models.DateTimeField(null=True, blank=True)
    candidate_reminded_at = models.DateTimeField(null=True, blank=True)
    candidate_email_error = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_date', '-scheduled_time']

    def __str__(self):
        return f"{self.resume.candidate_name} - Interview {self.phase} ({self.scheduled_date})"

    @property
    def starts_at(self):
        """The start as an aware datetime in Dhaka, or None without a time."""
        if self.scheduled_time is None:
            return None
        from datetime import datetime
        return timezone.make_aware(datetime.combine(self.scheduled_date, self.scheduled_time))

    @property
    def ends_at(self):
        start = self.starts_at
        return start + timedelta(minutes=self.duration_minutes or 60) if start else None

    def evaluation_link_expiry(self):
        """Evaluation links stay open until a week after the interview, and never
        less than the usual 30 days: one booked six weeks out must still work
        on the day."""
        from datetime import datetime, time
        end = self.ends_at or timezone.make_aware(datetime.combine(self.scheduled_date, time(23, 59)))
        return max(timezone.now() + timedelta(days=InterviewEvaluation.TOKEN_VALIDITY_DAYS),
                   end + timedelta(days=7))

    @property
    def candidate_email_pending(self) -> bool:
        return (self.notify_candidate and self.scheduled_time is not None and self.status == self.SCHEDULED
                and not self.candidate_notified_at and not self.candidate_email_error)

    @property
    def delivery_pending(self) -> bool:
        """Any invitation still on its way, so the page keeps checking."""
        if self.candidate_email_pending:
            return True
        return any(ev.interviewer_email and not ev.is_submitted and not ev.invited_at and not ev.invite_error
                   for ev in self.evaluations.all())

    @property
    def is_online(self) -> bool:
        return self.mode == self.ONLINE

    @property
    def submitted_count(self):
        return self.evaluations.filter(is_submitted=True).count()

    @property
    def pending_count(self):
        return self.evaluations.filter(is_submitted=False).count()

    def complete_if_all_submitted(self) -> bool:
        """Mark a scheduled interview completed once every evaluator has submitted."""
        if self.status != self.SCHEDULED:
            return False
        evaluations = list(self.evaluations.all())
        if evaluations and all(e.is_submitted for e in evaluations):
            Interview.objects.filter(pk=self.pk, status=self.SCHEDULED).update(status=self.COMPLETED)
            self.status = self.COMPLETED
            return True
        return False

    def avg_score(self):
        # From .all() so a prefetch is used: one query per interview otherwise.
        evals = [e for e in self.evaluations.all() if e.is_submitted]
        if not evals:
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

    # Interviewer info. A staff member is linked through `evaluator`; the name
    # and email are copied so the record survives the account being removed.
    evaluator = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='interview_evaluations')
    interviewer_name = models.CharField(max_length=200)
    interviewer_email = models.EmailField(blank=True)
    interviewer_position = models.CharField(max_length=200, blank=True)
    interviewer_department = models.CharField(max_length=200, blank=True)

    invited_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    invite_error = models.CharField(max_length=500, blank=True)

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
        ts = self.total_score
        return round((ts / MAX_SCORE) * 100) if ts is not None else None

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
