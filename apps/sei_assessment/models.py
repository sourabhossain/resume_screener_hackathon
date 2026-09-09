"""The candidate-facing SEI assessment: one timed sitting per candidate."""
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from . import scoring


class SEIAssessment(models.Model):
    """A single sitting of the Social & Emotional Intelligence instrument.

    The clock starts when the candidate first opens the questions, not when the
    invitation is sent -- an email that sat unread for an hour must not cost
    them their fifteen minutes.

    The deadline is enforced here rather than in the browser. The page runs a
    countdown and submits itself, but a countdown is a courtesy: it can be
    paused with the devtools, and the tab can be closed. What actually decides
    the sitting is `deadline_at`, written once when the clock starts.
    """

    TOKEN_VALIDITY_DAYS = 7
    OTP_VALIDITY_MINUTES = 15
    OTP_MAX_ATTEMPTS = 5
    OTP_DIGITS = 6
    TIME_LIMIT_MINUTES = scoring.TIME_LIMIT_MINUTES
    OTP_FIELDS = ('otp_hash', 'otp_expires_at', 'otp_attempts', 'otp_verified_at')

    resume = models.OneToOneField(
        'core.Resume', on_delete=models.CASCADE, related_name='sei_assessment')

    # The candidate is not logged in, so the token identifies them. Paired with
    # an emailed code, so a forwarded link alone cannot sit the test for them.
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token_expires_at = models.DateTimeField()

    otp_hash = models.CharField(max_length=128, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    otp_verified_at = models.DateTimeField(null=True, blank=True)

    # Item number (as a string key) -> 0..3.
    answers = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Whether the clock ended the sitting rather than the candidate. Worth
    # recording: an unfinished paper reads very differently from a finished one.
    auto_submitted = models.BooleanField(default=False)

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
        db_table = 'sei_assessment'
        ordering = ['-created_at']

    def __str__(self):
        return f'SEI assessment for {self.resume.candidate_name}'

    def save(self, *args, **kwargs):
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(
                days=self.TOKEN_VALIDITY_DAYS)
        super().save(*args, **kwargs)

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

    @property
    def time_is_up(self) -> bool:
        return bool(self.deadline_at and timezone.now() >= self.deadline_at)

    @property
    def is_open(self) -> bool:
        """Whether the candidate may still answer."""
        return not self.is_submitted and not self.is_expired and not self.time_is_up

    # ── results ──────────────────────────────────────────────────────────
    @property
    def answered_count(self) -> int:
        """Counted the way the scorer counts.

        Not `len(answers)`: the validity gate below rests on this number, and a
        looser count here would let a paper the scorer refuses to score be
        reported as a valid one.
        """
        return scoring.answered_items(self.answers or {})

    def result(self) -> dict:
        return scoring.score(self.answers or {})

    @property
    def is_valid_result(self) -> bool:
        """Whether enough of the instrument was answered to score it at all."""
        return (self.answered_count >= scoring.MINIMUM_VALID_ANSWERS
                if self.is_submitted else False)

    @property
    def needs_retaking(self) -> bool:
        """Submitted, but with too many blanks to report anything."""
        return self.is_submitted and not self.is_valid_result

    @property
    def status_label(self) -> str:
        if self.is_submitted:
            if not self.is_valid_result:
                return scoring.INVALID_LABEL
            if self.auto_submitted:
                return 'Time expired'
            return 'Completed'
        if self.is_expired:
            return 'Link expired'
        if self.has_started:
            return 'In progress'
        return 'Sent' if self.invited_at else 'Not sent'
