import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.text import slugify


class SoftDeleteManager(models.Manager):
    """Manager that filters out soft-deleted objects by default."""
    
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)
    
    def all_with_deleted(self):
        return super().get_queryset()
    
    def deleted_only(self):
        return super().get_queryset().filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    """Abstract base model with soft delete + declarative cascade.

    `on_delete=CASCADE` only fires on a hard DELETE, so a soft delete would
    orphan related rows (and leave their public links live). Instead of a
    bespoke soft_delete() override per model, a model declares which reverse
    relations to cascade into via SOFT_DELETE_CASCADE; the base walks them
    recursively. A new related model only needs to (a) be a SoftDeleteModel and
    (b) be listed by its parent — the cascade then "just works", which is what
    keeps the soft-delete strategy consistent across the codebase.
    """

    is_deleted = models.BooleanField(default=False, db_default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Reverse-relation accessor names (related_name) to cascade soft-deletes into.
    # Every listed relation MUST itself be a SoftDeleteModel.
    SOFT_DELETE_CASCADE = ()

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        if self.is_deleted:
            return
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])
        self._cascade_soft_delete()

    def _cascade_soft_delete(self):
        for accessor in self.SOFT_DELETE_CASCADE:
            related = getattr(self, accessor, None)
            if related is None:
                continue
            # all_with_deleted() so an already-deleted child isn't touched twice
            # but the queryset still resolves regardless of the default manager.
            qs = related.all_with_deleted() if hasattr(related, 'all_with_deleted') else related.all()
            for obj in qs.filter(is_deleted=False):
                obj.is_deleted = True
                obj.deleted_at = self.deleted_at
                obj.save(update_fields=['is_deleted', 'deleted_at'])
                cascade = getattr(obj, '_cascade_soft_delete', None)
                if cascade:
                    cascade()

    def restore(self):
        # Shallow restore by design: bringing back a parent does NOT auto-restore
        # children (they may have been deleted independently earlier).
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])


class Job(SoftDeleteModel):
    """Job Description model - stores job postings for resume screening."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ]

    EMPLOYMENT_TYPE_CHOICES = [
        ('full_time', 'Full-time'),
        ('part_time', 'Part-time'),
        ('contract', 'Contract'),
        ('freelance', 'Freelance'),
        ('internship', 'Internship'),
    ]

    LOCATION_TYPE_CHOICES = [
        ('on_site', 'On-site'),
        ('remote', 'Remote'),
        ('hybrid', 'Hybrid'),
    ]

    # The recruiter who created this job (informational/audit). This is a
    # single-company internal tool: every authenticated recruiter can see and
    # act on all jobs and candidates, so access is intentionally NOT isolated
    # per owner. `owner` records provenance and gates owner-only actions like
    # API restore, not read access.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='jobs',
        null=True,
        blank=True,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    # Public, URL-safe identifier for the careers pages (avoids exposing the numeric id).
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True)
    description = models.TextField(blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='jobs/', blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPE_CHOICES, blank=True)
    location_type = models.CharField(max_length=10, choices=LOCATION_TYPE_CHOICES, blank=True)
    location = models.CharField(max_length=255, blank=True)
    posted_date = models.DateField(null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_type = models.CharField(max_length=50, blank=True)
    

    required_skills = models.JSONField(default=list, blank=True, help_text="Required skills for matching")
    required_experience = models.FloatField(null=True, blank=True, help_text="Required years of experience")
    required_education = models.JSONField(default=list, blank=True, help_text="Required education levels")
    
    class Meta:
        db_table = 'job_description'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'is_deleted'], name='job_status_deleted_idx'),
            models.Index(fields=['-created_at'], name='job_created_idx'),
            models.Index(fields=['title'], name='job_title_idx'),
        ]
    
    def __str__(self):
        return self.title

    def _generate_unique_slug(self):
        base = slugify(self.title) or 'job'
        slug = base
        n = 2
        # all_objects so a soft-deleted job's slug isn't silently reused
        while Job.all_objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    def save(self, *args, **kwargs):
        # Generate the slug once at creation and keep it stable so public URLs don't break.
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    @property
    def active_resumes(self):
        return self.resumes.filter(is_deleted=False)


class Resume(SoftDeleteModel):
    """Resume model - stores candidate resumes and their screening results."""

    # Soft-deleting a candidate cascades to their interviews (and, transitively,
    # the interviews' evaluations) so deleted-candidate data and its public
    # evaluation links disappear consistently. See SoftDeleteModel.
    SOFT_DELETE_CASCADE = ('interviews',)

    TIER_CHOICES = [
        ('low', 'Low'),
        ('mid', 'Mid'),
        ('top', 'Top'),
    ]
    
    RECOMMENDATION_CHOICES = [
        ('interview', 'Interview'),
        ('talent_pool', 'Talent Pool'),
        ('reject', 'Reject'),
    ]
    
    # Opaque public identifier used in recruiter URLs and the REST API instead of
    # the sequential numeric pk (prevents enumeration). Non-nullable: every row is
    # backfilled (migration 0010) and new rows get a default, so the opaque-id
    # guarantee is enforced at the DB level.
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='resumes',
        db_column='job_id'
    )
    file_name = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to='resumes/', blank=True, null=True)
    candidate_name = models.CharField(max_length=255)
    raw_text = models.TextField(blank=True)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, blank=True)
    recommendation = models.CharField(max_length=20, choices=RECOMMENDATION_CHOICES, blank=True)
    matched_skills = models.JSONField(default=list, blank=True)
    missing_skills = models.JSONField(default=list, blank=True)
    _score_validators = [MinValueValidator(0), MaxValueValidator(100)]
    experience_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    education_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    skills_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    final_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_type = models.CharField(max_length=50, blank=True)
    

    skills = models.JSONField(default=list, blank=True, help_text="Extracted skills from resume")
    education = models.JSONField(default=list, blank=True, help_text="Extracted education")
    certifications = models.JSONField(default=list, blank=True, help_text="Extracted certifications")
    achievements = models.JSONField(default=list, blank=True, help_text="Extracted quantifiable achievements")
    experience_years = models.FloatField(null=True, blank=True, help_text="Total years of experience")
    certification_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    achievement_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    reasoning = models.TextField(blank=True, help_text="AI reasoning for recommendation")
    
    SCREENING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('needs_review', 'Needs Review'),
        ('failed', 'Failed'),
    ]
    screening_status = models.CharField(
        max_length=20,
        choices=SCREENING_STATUS_CHOICES,
        default='pending'
    )

    # SHA-256 of the uploaded file — used to detect duplicate submissions for the same job.
    file_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # Link Verification
    extracted_links = models.JSONField(default=list, blank=True)
    verification_results = models.JSONField(default=dict, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
        ],
        default='pending'
    )
    verification_score = models.FloatField(null=True, blank=True, validators=_score_validators)
    verified_at = models.DateTimeField(null=True, blank=True)

    RECRUITER_STATUS_CHOICES = [
        ('new', 'New'),
        ('shortlisted', 'Shortlisted'),
        ('phone_screen', 'Phone Screen'),
        ('interviewing', 'Interviewing'),
        ('offer_extended', 'Offer Extended'),
        ('hired', 'Hired'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]
    recruiter_status = models.CharField(
        max_length=20,
        choices=RECRUITER_STATUS_CHOICES,
        default='new',
        blank=True,
    )
    # Tracks whether a recruiter manually changed AI-generated scores.
    score_manually_edited = models.BooleanField(default=False)
    score_edited_at = models.DateTimeField(null=True, blank=True)
    score_edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='edited_resumes',
    )

    class Meta:
        db_table = 'resumes'
        ordering = [F('final_score').desc(nulls_last=True), '-created_at']
        indexes = [
            models.Index(fields=['job', 'is_deleted'], name='resume_job_deleted_idx'),
            models.Index(fields=['tier'], name='resume_tier_idx'),
            models.Index(fields=['-final_score'], name='resume_score_idx'),
            models.Index(fields=['screening_status'], name='resume_status_idx'),
        ]
        constraints = [
            # DB-level backstop against duplicate submissions: the same file can't
            # be submitted twice for one job. Complements the app-level .exists()
            # checks in the views, closing the race window between check and save.
            # Scoped to non-deleted rows with a real hash so re-uploads after a
            # delete, and rows without a file, are unaffected.
            models.UniqueConstraint(
                fields=['job', 'file_hash'],
                condition=Q(is_deleted=False) & ~Q(file_hash=''),
                name='uniq_active_resume_file_per_job',
            ),
        ]
    
    def __str__(self):
        return f"{self.candidate_name} - {self.job.title}"

    def assign_tier_and_recommendation_from_final_score(self) -> None:
        """Align tier and decision with final_score using AI_SCREENING_CONFIG thresholds."""
        if self.final_score is None:
            return
        cfg = settings.AI_SCREENING_CONFIG
        score = self.final_score
        if score >= cfg['TOP_TIER_THRESHOLD']:
            self.tier = 'top'
            self.recommendation = 'interview'
        elif score >= cfg['MID_TIER_THRESHOLD']:
            self.tier = 'mid'
            self.recommendation = 'talent_pool'
        else:
            self.tier = 'low'
            self.recommendation = 'reject'

    def save(self, *args, **kwargs):
        self.assign_tier_and_recommendation_from_final_score()
        super().save(*args, **kwargs)


class ResumeNote(models.Model):
    """Internal recruiter notes attached to a resume."""
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='resume_notes',
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.resume.candidate_name} by {self.author}"
