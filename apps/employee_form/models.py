import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from . import schema


class EmployeeForm(models.Model):
    """One Employee Information Form invitation per shortlisted candidate.

    Answers live in a JSONField keyed by `schema.QUESTIONS_BY_KEY` rather than in
    ~131 columns: the form is branching (a candidate only ever fills one of the
    D1-D6 role sections), so explicit columns would be mostly null, and adding
    the missing D2-D6 questions would mean a migration per question.
    Uploads cannot go in JSON and live in `EmployeeFormFile`.
    """

    TOKEN_VALIDITY_DAYS = 7
    OTP_VALIDITY_MINUTES = 15
    OTP_MAX_ATTEMPTS = 5
    OTP_DIGITS = 6

    resume = models.OneToOneField(
        'core.Resume',
        on_delete=models.CASCADE,
        related_name='employee_form',
    )

    # Opaque URL identifier -- the candidate is not logged in, so the token is
    # what identifies them. Paired with an emailed OTP so a leaked link alone
    # is not enough to open the form.
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    token_expires_at = models.DateTimeField()

    # The OTP is stored as a hash, never in plaintext: this row is readable by
    # every recruiter and by anyone with DB access, and the plaintext would let
    # them open a candidate's form.
    otp_hash = models.CharField(max_length=128, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)
    otp_verified_at = models.DateTimeField(null=True, blank=True)

    answers = models.JSONField(default=dict, blank=True)
    current_step = models.CharField(max_length=50, default=schema.FIRST_STEP)

    is_submitted = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)

    invited_at = models.DateTimeField(null=True, blank=True)
    invite_count = models.PositiveSmallIntegerField(default=0)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='employee_form_invites',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Employee form for {self.resume.candidate_name}"

    def save(self, *args, **kwargs):
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timedelta(days=self.TOKEN_VALIDITY_DAYS)
        super().save(*args, **kwargs)

    # ── Link state ───────────────────────────────────────────────────────
    @property
    def is_expired(self) -> bool:
        return bool(self.token_expires_at and timezone.now() > self.token_expires_at)

    @property
    def is_open(self) -> bool:
        """Candidate can still work on the form."""
        return not self.is_submitted and not self.is_expired

    def renew(self):
        """Push the link expiry out again, for a resend after it lapsed."""
        self.token_expires_at = timezone.now() + timedelta(days=self.TOKEN_VALIDITY_DAYS)

    # ── OTP ──────────────────────────────────────────────────────────────
    def issue_otp(self) -> str:
        """Generate a fresh OTP, store only its hash, and return the plaintext.

        The plaintext is returned once so the caller can email it; it is never
        persisted. Issuing resets the attempt counter so a resend gives the
        candidate a clean slate.
        """
        otp = f"{secrets.randbelow(10 ** self.OTP_DIGITS):0{self.OTP_DIGITS}d}"
        self.otp_hash = make_password(otp)
        self.otp_expires_at = timezone.now() + timedelta(minutes=self.OTP_VALIDITY_MINUTES)
        self.otp_attempts = 0
        self.otp_verified_at = None
        return otp

    @property
    def otp_is_expired(self) -> bool:
        return bool(self.otp_expires_at and timezone.now() > self.otp_expires_at)

    @property
    def otp_attempts_left(self) -> int:
        return max(0, self.OTP_MAX_ATTEMPTS - self.otp_attempts)

    @property
    def otp_is_locked(self) -> bool:
        return self.otp_attempts >= self.OTP_MAX_ATTEMPTS

    def check_otp(self, raw: str) -> bool:
        """Verify a submitted OTP, counting the attempt.

        Returns False (without consuming an attempt) when there is nothing to
        check against or the code has already lapsed -- the caller distinguishes
        those cases via `otp_is_expired` / `otp_is_locked` so the candidate gets
        an accurate message instead of "wrong code".
        """
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
    def path(self) -> list:
        return schema.step_path(self.answers or {})

    @property
    def total_steps(self) -> int:
        return len(self.path)

    @property
    def step_number(self) -> int:
        try:
            return self.path.index(self.current_step) + 1
        except ValueError:
            return 1

    @property
    def progress_percent(self) -> int:
        total = self.total_steps
        if not total:
            return 0
        completed = self.total_steps if self.is_submitted else self.step_number - 1
        return round((completed / total) * 100)

    def previous_step(self, step_key):
        path = self.path
        try:
            index = path.index(step_key)
        except ValueError:
            return None
        return path[index - 1] if index > 0 else None

    # ── Reading answers back ─────────────────────────────────────────────
    def documents(self):
        """Every uploaded document, each tagged with its viewer position.

        Built once and reused by both the document gallery and the per-question
        file chips so a chip always opens the viewer on the right document.
        """
        uploads = list(self.files.all())
        for position, upload in enumerate(uploads):
            upload.position = position
        return uploads

    def answered_sections(self):
        """Answers grouped by step, for the recruiter-facing view.

        Only steps on the candidate's own path are returned, so a Sales
        candidate's report does not show empty Finance or Technology sections.
        """
        files_by_key = {}
        for upload in self.documents():
            files_by_key.setdefault(upload.question_key, []).append(upload)

        sections = []
        for step_key in self.path:
            step = schema.get_step(step_key)
            if not step:
                continue
            rows = []
            for question in schema.numbered_questions(step_key, self.answers or {}):
                rows.append({
                    'key': question['key'],
                    'number': question['number'],
                    'label': question['label'],
                    'type': question['type'],
                    'value': self.display_value(question),
                    'files': files_by_key.get(question['key'], []),
                })
            if rows:
                sections.append({
                    'key': step_key,
                    'section': step['section'],
                    'title': step['title'],
                    'rows': rows,
                })
        return sections

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
        return raw

    @property
    def declaration_summary(self) -> str:
        """What the candidate answered on the Section D7 declaration.

        Surfaced on the candidate page because "I Do Not Agree" on a submitted
        form is a result the recruiter must not have to open the form to notice.
        """
        value = (self.answers or {}).get('declaration_agreement')
        if not value:
            return '—'
        return schema.choice_label('declaration_agreement', value)

    @property
    def status_label(self) -> str:
        """Plain-text status, for logs, the admin and CSV.

        The recruiter-facing chip is rendered by
        `employee_form/partials/status_chip.html` instead of from a tone name
        here: Tailwind only scans templates, so a class string assembled in
        Python would be purged from the stylesheet.
        """
        if self.is_submitted:
            return 'Submitted'
        if self.is_expired:
            return 'Link expired'
        if self.otp_verified_at:
            return 'In progress'
        if self.invited_at:
            return 'Invite sent'
        return 'Not sent'


def upload_to(instance, filename):
    """Storage path for one uploaded document.

    Deliberately *not* keyed by `form.token`: the token is the credential in the
    candidate's emailed link, and putting it in the media path would hand it to
    anyone who can see a document URL. A per-upload random segment keeps paths
    unguessable without reusing the secret, and stops two files of the same name
    from colliding.
    """
    return (
        f"employee_forms/{instance.form_id}/"
        f"{uuid.uuid4().hex}/{filename}"
    )


class EmployeeFormFile(models.Model):
    """A document uploaded against one question (NID scan, certificate, ...).

    Served only through the login-protected media view, never from a public URL.
    """

    form = models.ForeignKey(EmployeeForm, on_delete=models.CASCADE, related_name='files')
    question_key = models.CharField(max_length=100)
    file = models.FileField(upload_to=upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['question_key', 'uploaded_at']
        indexes = [
            models.Index(fields=['form', 'question_key'], name='ef_file_form_question_idx'),
        ]

    def __str__(self):
        return f"{self.question_key}: {self.original_name or self.file.name}"

    @property
    def label(self) -> str:
        q = schema.QUESTIONS_BY_KEY.get(self.question_key)
        return q['label'] if q else self.question_key

    IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp')

    @property
    def extension(self) -> str:
        name = self.original_name or self.file.name or ''
        return name.rsplit('.', 1)[-1].lower() if '.' in name else ''

    @property
    def kind(self) -> str:
        """How the viewer should render this: 'image', 'pdf' or 'file'.

        'file' covers doc/docx, which no browser displays — those are offered as
        a download instead of being put in a dead iframe.
        """
        name = (self.original_name or self.file.name or '').lower()
        if name.endswith(self.IMAGE_SUFFIXES):
            return 'image'
        if name.endswith('.pdf'):
            return 'pdf'
        return 'file'

    @property
    def view_url(self) -> str:
        """URL that renders in the browser rather than downloading.

        `serve_protected_media` only honours inline for formats it considers safe,
        so this falls back to the plain (download) URL for anything else.
        """
        if self.kind == 'file':
            return self.file.url
        return f'{self.file.url}?inline=1'

    @property
    def size_display(self) -> str:
        size = self.size_bytes or 0
        if size >= 1024 * 1024:
            return f'{size / (1024 * 1024):.1f} MB'
        if size >= 1024:
            return f'{size / 1024:.0f} KB'
        return f'{size} B'
