import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from . import schema


class ReferenceCheck(models.Model):
    """One verification request sent to one person outside SSL.

    Two shapes of it -- a former employer's HR and a professional referee --
    differing only in which schema they answer (academic is kept only for older requests). The
    respondent is not a user of this system: they are reached by an emailed link
    plus a one-time code, exactly as the candidate is for their own form.

    `source_key` records which block of the candidate's Employee Information Form
    this request came from ('employer_2', 'reference_1'), so a resend goes to the
    same place and one request exists per employer or referee.
    """

    TOKEN_VALIDITY_DAYS = 14
    OTP_VALIDITY_MINUTES = 15
    OTP_MAX_ATTEMPTS = 5
    OTP_DIGITS = 6

    KIND_CHOICES = [
        (schema.EMPLOYER, 'Employment verification'),
        (schema.PROFESSIONAL, 'Professional reference'),
        (schema.ACADEMIC, 'Academic reference'),
    ]

    resume = models.ForeignKey(
        'core.Resume', on_delete=models.CASCADE, related_name='reference_checks'
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    source_key = models.CharField(
        max_length=40,
        help_text="Which block of the candidate's form this came from, "
                  "e.g. 'employer_2' or 'reference_1'.",
    )

    # Who it goes to. Seeded from the candidate's answers, editable by HR before
    # sending -- a candidate may have given a stale address.
    recipient_name = models.CharField(max_length=200)
    recipient_email = models.EmailField()
    recipient_organisation = models.CharField(max_length=200, blank=True)

    # The link is the credential, paired with an emailed code so a forwarded link
    # alone is not enough to open someone's employment record.
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token_expires_at = models.DateTimeField()

    otp_hash = models.CharField(max_length=128, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    otp_verified_at = models.DateTimeField(null=True, blank=True)

    answers = models.JSONField(default=dict, blank=True)
    current_step = models.CharField(max_length=40, blank=True)

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)

    invited_at = models.DateTimeField(null=True, blank=True)
    invite_count = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reference_checks_sent',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source_key', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['resume', 'source_key'], name='one_check_per_source'
            ),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} to {self.recipient_name}'

    def save(self, *args, **kwargs):
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(
                days=self.TOKEN_VALIDITY_DAYS)
        if not self.current_step:
            self.current_step = schema.first_step(self.kind) or ''
        super().save(*args, **kwargs)

    # ── Link state ───────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        return bool(self.token_expires_at and timezone.now() > self.token_expires_at)

    @property
    def is_open(self) -> bool:
        return not self.is_submitted and not self.is_expired

    def renew(self):
        self.token_expires_at = timezone.now() + timedelta(
            days=self.TOKEN_VALIDITY_DAYS)

    # ── OTP ──────────────────────────────────────────────────────────────
    # Exactly what issue_otp() touches. Named here because HR's resend and the
    # respondent's section save write this row concurrently, and each must
    # narrow its save() to its own columns or it silently reverts the other's.
    OTP_FIELDS = ('otp_hash', 'otp_expires_at', 'otp_attempts', 'otp_verified_at')

    def issue_otp(self) -> str:
        """Generate a fresh code, store only its hash, return the plaintext once.

        The plaintext is never persisted: this row is readable by every HR user
        and by anyone with database access, and the code would let them open the
        respondent's form and answer as them.
        """
        otp = f"{secrets.randbelow(10 ** self.OTP_DIGITS):0{self.OTP_DIGITS}d}"
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

    # ── Progress ─────────────────────────────────────────────────────────
    @property
    def steps(self) -> list:
        return schema.step_keys(self.kind)

    @property
    def total_steps(self) -> int:
        return schema.total_steps(self.kind)

    @property
    def resume_step(self) -> str:
        """Where the respondent picks up; older rows may name a retired section."""
        if self.current_step in self.steps:
            return self.current_step
        return schema.first_step(self.kind) or ''

    @property
    def step_number(self) -> int:
        return schema.step_number(self.kind, self.resume_step) or 1

    @property
    def verification_reference_id(self) -> str:
        """The reference quoted to the respondent -- never the secret token."""
        return f'SSLW-VR-{self.pk:06d}' if self.pk else ''

    @property
    def status_label(self) -> str:
        if self.is_submitted:
            return 'Completed'
        if self.is_expired:
            return 'Link expired'
        if self.otp_verified_at:
            return 'In progress'
        if self.invited_at:
            return 'Sent'
        return 'Not sent'

    # ── Reading answers back ─────────────────────────────────────────────
    def display_value(self, question):
        raw = (self.answers or {}).get(question['key'])
        if raw in (None, '', []):
            return ''
        if question['type'] in schema.CHOICE_TYPES:
            if isinstance(raw, list):
                return ', '.join(
                    str(schema.choice_label(self.kind, question['key'], v)) for v in raw)
            return schema.choice_label(self.kind, question['key'], raw)
        return raw

    def answered_sections(self):
        """Every section with its answers, for the HR-facing review page.

        Blank sections stay listed: on a conduct section, silence is information.
        """
        out = []
        for step in schema.steps(self.kind):
            rows = []
            for question in step['questions']:
                value = self.display_value(question)
                if value != '':
                    rows.append({
                        'key': question['key'],
                        'label': question['label'],
                        'value': value,
                    })
            out.append({'key': step['key'], 'title': schema.step_heading(step),
                        'rows': rows})
        legacy = self.legacy_rows()
        if legacy:
            out.append({'key': 'legacy', 'title': 'Answers from the earlier form version',
                        'rows': legacy})
        return out

    def legacy_rows(self):
        from .legacy import LEGACY_CHOICES, LEGACY_LABELS
        current = set(schema.questions_by_key(self.kind))
        labels = LEGACY_LABELS.get(self.kind, {})
        choices = LEGACY_CHOICES.get(self.kind, {})
        rows = []
        for key, label in labels.items():
            raw = (self.answers or {}).get(key)
            if key in current or raw in (None, '', []):
                continue
            options = choices.get(key, {})
            if isinstance(raw, list):
                value = ', '.join(str(options.get(v, v)) for v in raw)
            else:
                value = options.get(raw, raw)
            rows.append({'key': key, 'label': label, 'value': value})
        return rows

    HEADLINES = {
        schema.EMPLOYER: ('rehire_eligible', 'Eligible for rehire'),
        schema.PROFESSIONAL: ('hire_again', 'Would work with / recommend again'),
        schema.ACADEMIC: ('recommend', 'Recommends'),
    }

    @property
    def headline(self) -> str:
        """The one answer HR looks for first, per form."""
        answers = self.answers or {}
        if self.kind == schema.PROFESSIONAL and not answers.get('hire_again') \
                and answers.get('recommend'):
            from .legacy import LEGACY_CHOICES
            raw = answers['recommend']
            return LEGACY_CHOICES['professional'].get('recommend', {}).get(raw, raw)
        key = self.HEADLINES.get(self.kind, ('', ''))[0]
        question = schema.questions_by_key(self.kind).get(key)
        return self.display_value(question) if question else ''

    @property
    def headline_label(self) -> str:
        return self.HEADLINES.get(self.kind, ('', ''))[1]

    @property
    def flagged(self) -> bool:
        """Whether the response contains something HR must read.

        Conservative on purpose: a concern, a qualified verdict, an involuntary
        exit or an employer who cannot confirm employment all raise it. Keys of
        the pre-FINAL forms are still read so older replies keep their badge.
        """
        answers = self.answers or {}
        concern = (answers.get('conduct_concerns') == 'yes'
                   or answers.get('integrity_concerns') == 'yes')
        if self.kind == schema.EMPLOYER:
            return (concern
                    or answers.get('disciplinary_action') == 'yes'
                    or answers.get('was_employed') == 'no'
                    or answers.get('separation_nature') in {
                        'asked_to_resign', 'termination', 'involuntary'}
                    or answers.get('rehire_eligible') in {'no', 'conditional'})
        if self.kind == schema.PROFESSIONAL:
            return (concern
                    or answers.get('hire_again') in {'no', 'conditional',
                                                     'yes_reservations'}
                    or answers.get('recommend') in {'no', 'yes_reservations'})
        return (concern
                or answers.get('recommend') in {'unable', 'reservations'})
