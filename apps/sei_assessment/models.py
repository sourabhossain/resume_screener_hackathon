"""Candidate assessments: one invitation per candidate, one timed sitting per instrument."""
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from . import instruments

# Both instruments word an unscoreable paper the same way, and the recruiter
# sees it as a status rather than as a score.
INVALID_LABEL = 'Invalid - Insufficient Responses'


class AssessmentInvitation(models.Model):
    """One link and one code covering every assessment the job asks for."""

    TOKEN_VALIDITY_DAYS = 7
    OTP_VALIDITY_MINUTES = 15
    OTP_MAX_ATTEMPTS = 5
    OTP_DIGITS = 6
    OTP_FIELDS = ('otp_hash', 'otp_expires_at', 'otp_attempts', 'otp_verified_at')

    resume = models.OneToOneField(
        'core.Resume', on_delete=models.CASCADE,
        related_name='assessment_invitation')

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token_expires_at = models.DateTimeField()

    otp_hash = models.CharField(max_length=128, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    otp_verified_at = models.DateTimeField(null=True, blank=True)

    # When the candidate ticked the consent box on the portal. Asked once,
    # before the first clock starts; a part already running is never blocked.
    consented_at = models.DateTimeField(null=True, blank=True)

    invited_at = models.DateTimeField(null=True, blank=True)
    invite_count = models.PositiveSmallIntegerField(default=0)
    invited_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+')
    last_error = models.TextField(blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'assessment_invitation'
        ordering = ['-created_at']

    def __str__(self):
        return f'Assessments for {self.resume.candidate_name}'

    def save(self, *args, **kwargs):
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(
                days=self.TOKEN_VALIDITY_DAYS)
        super().save(*args, **kwargs)

    @property
    def reference_id(self) -> str:
        """What the candidate quotes to HR. Never the token, which is the key."""
        return f'SSLW-ASM-{self.pk:06d}'

    def record_consent(self) -> None:
        if self.consented_at:
            return
        now = timezone.now()
        AssessmentInvitation.objects.filter(
            pk=self.pk, consented_at__isnull=True).update(consented_at=now)
        self.consented_at = now

    # ── the sittings, in the order they are taken ────────────────────────
    def ordered_sittings(self):
        """Sittings of known instruments, in `instruments.ORDER`."""
        rank = {key: i for i, key in enumerate(instruments.ORDER)}
        return sorted(
            (s for s in self.sittings.all() if s.instrument in rank),
            key=lambda s: rank[s.instrument])

    def current_sitting(self, sittings=None):
        """The running sitting if any, else the first unsubmitted one."""
        sittings = sittings if sittings is not None else self.ordered_sittings()
        pending = [s for s in sittings if not s.is_submitted]
        running = [s for s in pending if s.has_started]
        return (running or pending or [None])[0]

    def running_sitting(self, sittings=None):
        current = self.current_sitting(sittings)
        return current if current is not None and current.has_started else None

    @property
    def is_complete(self) -> bool:
        sittings = self.ordered_sittings()
        return bool(sittings) and all(s.is_submitted for s in sittings)

    # ── link ─────────────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        return bool(self.token_expires_at and timezone.now() > self.token_expires_at)

    def renew(self):
        self.token_expires_at = timezone.now() + timedelta(
            days=self.TOKEN_VALIDITY_DAYS)

    # ── one-time code ────────────────────────────────────────────────────
    def issue_otp(self) -> str:
        """Generate a code, store only its hash, return the plaintext once."""
        otp = f'{secrets.randbelow(10 ** self.OTP_DIGITS):0{self.OTP_DIGITS}d}'
        self.otp_hash = make_password(otp)
        self.otp_expires_at = timezone.now() + timedelta(
            minutes=self.OTP_VALIDITY_MINUTES)
        self.otp_attempts = 0
        self.otp_verified_at = None
        return otp

    @property
    def otp_is_expired(self) -> bool:
        return bool(self.otp_expires_at and timezone.now() > self.otp_expires_at)

    @property
    def otp_is_locked(self) -> bool:
        return self.otp_attempts >= self.OTP_MAX_ATTEMPTS

    @property
    def otp_attempts_left(self) -> int:
        return max(0, self.OTP_MAX_ATTEMPTS - self.otp_attempts)

    def check_otp(self, raw: str) -> bool:
        if not self.otp_hash or self.otp_is_expired or self.otp_is_locked:
            return False
        if check_password(raw, self.otp_hash):
            self.otp_verified_at = timezone.now()
            self.otp_attempts = 0
            self.save(update_fields=['otp_verified_at', 'otp_attempts', 'updated_at'])
            return True
        self.otp_attempts += 1
        self.save(update_fields=['otp_attempts', 'updated_at'])
        return False


class SEIAssessment(models.Model):
    """A single sitting of one instrument by one candidate.

    The clock starts when the candidate first opens the questions, not when the
    invitation is sent -- an email that sat unread for an hour must not cost
    them their time.

    The deadline is enforced here rather than in the browser. The page runs a
    countdown and submits itself, but a countdown is a courtesy: it can be
    paused with the devtools, and the tab can be closed. What actually decides
    the sitting is `deadline_at`, written once when the clock starts.

    The class name and table still say SEI because that was the only instrument
    when they were written -- see the naming note in instruments.py.
    """

    # `sittings`, not `assessments`: Job.assessments already means "which
    # questionnaires this job asks for". Two different things under one name on
    # neighbouring models is a trap for whoever reads this next.
    resume = models.ForeignKey(
        'core.Resume', on_delete=models.CASCADE, related_name='sittings')
    invitation = models.ForeignKey(
        AssessmentInvitation, on_delete=models.CASCADE, related_name='sittings')
    # Which questionnaire this sitting is. Every row written before there was
    # more than one is SEI, which is what the migration backfills.
    instrument = models.CharField(
        max_length=32, default=instruments.SEI, db_index=True)

    # Only resolves links emailed before sittings were grouped.
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Item number (as a string key) -> rating on the instrument's scale.
    answers = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Whether the clock ended the sitting rather than the candidate. Worth
    # recording: an unfinished paper reads very differently from a finished one.
    auto_submitted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'sei_assessment'
        ordering = ['-created_at']
        constraints = [
            # One sitting per instrument per candidate. Resending reuses the
            # row rather than opening a second one, so two live sittings of the
            # same questionnaire cannot exist.
            models.UniqueConstraint(
                fields=['resume', 'instrument'], name='one_sitting_per_instrument'),
        ]

    def __str__(self):
        return f'{self.instrument_label} for {self.resume.candidate_name}'

    def save(self, *args, **kwargs):
        if self.invitation_id is None:
            self.invitation, _ = AssessmentInvitation.objects.get_or_create(
                resume=self.resume)
        super().save(*args, **kwargs)

    # ── which instrument ─────────────────────────────────────────────────
    @property
    def spec(self):
        """The instrument definition this sitting belongs to."""
        return instruments.get(self.instrument)

    @property
    def instrument_label(self) -> str:
        return self.spec.label

    @property
    def TIME_LIMIT_MINUTES(self) -> int:
        """Per instrument, not per app. Kept under the old name because the
        emails and pages already read it that way."""
        return self.spec.time_limit_minutes

    # ── link ─────────────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        return self.invitation.is_expired

    # ── the clock ────────────────────────────────────────────────────────
    def start_clock(self):
        """Begin the sitting, once. Returns True if this call started it.

        A conditional UPDATE, so a double-submitted page or two tabs opened
        together cannot restart the clock and hand out extra time.
        """
        if self.started_at is not None:
            return False
        now = timezone.now()
        deadline = now + timedelta(minutes=self.TIME_LIMIT_MINUTES)
        claimed = SEIAssessment.objects.filter(
            pk=self.pk, started_at__isnull=True,
        ).update(started_at=now, deadline_at=deadline)
        if claimed:
            self.started_at, self.deadline_at = now, deadline
            return True
        self.refresh_from_db(fields=['started_at', 'deadline_at'])
        return False

    @property
    def has_started(self) -> bool:
        return self.started_at is not None

    @property
    def seconds_left(self) -> int:
        if not self.deadline_at:
            return self.TIME_LIMIT_MINUTES * 60
        return max(0, int((self.deadline_at - timezone.now()).total_seconds()))

    # The page submits itself at zero with whatever it had not flushed yet, so
    # that request always lands just after the deadline. Without a grace the
    # last answers would be thrown away -- and PE needs every one of them.
    SAVE_GRACE_SECONDS = 10

    @property
    def past_grace(self) -> bool:
        """The deadline and the grace for the page's final save have both passed."""
        return bool(self.deadline_at and timezone.now() >= self.deadline_at + timedelta(
            seconds=self.SAVE_GRACE_SECONDS))

    @property
    def time_is_up(self) -> bool:
        return bool(self.deadline_at and timezone.now() >= self.deadline_at)

    @property
    def is_open(self) -> bool:
        """Whether the candidate may still answer."""
        return not self.is_submitted and not self.is_expired and not self.time_is_up

    def reset(self):
        """Clear a sitting back to unopened, for a retake. Caller saves."""
        self.answers = {}
        self.started_at = None
        self.deadline_at = None
        self.is_submitted = False
        self.submitted_at = None
        self.auto_submitted = False

    RESET_FIELDS = ('answers', 'started_at', 'deadline_at', 'is_submitted',
                    'submitted_at', 'auto_submitted')

    # ── results ──────────────────────────────────────────────────────────
    @property
    def answered_count(self) -> int:
        """Counted the way the scorer counts.

        Not `len(answers)`: the validity gate below rests on this number, and a
        looser count here would let a paper the scorer refuses to score be
        reported as a valid one.
        """
        return self.spec.answered_items(self.answers or {})

    def result(self) -> dict:
        return self.spec.score(self.answers or {})

    @property
    def is_valid_result(self) -> bool:
        """Whether enough of the instrument was answered to score it at all."""
        return (self.answered_count >= self.spec.minimum_answers
                if self.is_submitted else False)

    @property
    def needs_retaking(self) -> bool:
        """Submitted, but with too many blanks to report anything."""
        return self.is_submitted and not self.is_valid_result

    @property
    def status_label(self) -> str:
        if self.is_submitted:
            if not self.is_valid_result:
                return INVALID_LABEL
            if self.auto_submitted:
                return 'Time expired'
            return 'Completed'
        if self.has_started:
            return 'In progress'
        if self.is_expired:
            return 'Link expired'
        if not self.invitation.invited_at:
            return 'Not sent'
        current = self.invitation.current_sitting()
        if current is not None and current.pk != self.pk:
            return 'Waiting'
        return 'Sent'
