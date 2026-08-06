"""
Tests for public careers flow: careers_list, careers_apply (POST), careers_thanks.
Covers the happy path, all duplicate-detection branches, closed/expired jobs,
and missing-contact-info validation.
"""
import io
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.core.models import Job, Resume


def _fake_pdf(name="resume.pdf"):
    buf = io.BytesIO(b"%PDF-1.4 fake content for test")
    buf.name = name
    return buf


def _post_apply(client, job, extra=None):
    data = {
        "candidate_name": "Ali Hassan",
        "email": "ali@example.com",
        "phone": "+8801711000000",
        "file": _fake_pdf(),
    }
    if extra:
        data.update(extra)
    url = reverse("core:careers_apply", kwargs={"slug": job.slug})
    with patch("apps.core.tasks.screen_resume_task.delay"):
        return client.post(url, data)


@pytest.mark.django_db
class TestCareersList:
    def test_renders_active_jobs(self, client, sample_job):
        resp = client.get(reverse("core:careers"))
        assert resp.status_code == 200
        assert sample_job in resp.context["jobs"]

    def test_excludes_draft_jobs(self, client, sample_job):
        sample_job.status = "draft"
        sample_job.save()
        resp = client.get(reverse("core:careers"))
        assert sample_job not in resp.context["jobs"]

    def test_search_filters_results(self, client, sample_job):
        resp = client.get(reverse("core:careers"), {"q": "Python"})
        assert resp.status_code == 200
        assert sample_job in resp.context["jobs"]

    def test_htmx_request_returns_partial(self, client, sample_job):
        resp = client.get(
            reverse("core:careers"), {"q": "Python"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        # partial template — does not contain the outer page chrome
        assert b"<!DOCTYPE" not in resp.content

    def test_htmx_boosted_request_returns_full_page(self, client, sample_job):
        """Boosted nav (All positions, logo) must return #main-content, not search partial."""
        resp = client.get(
            reverse("core:careers"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_BOOSTED="true",
        )
        assert resp.status_code == 200
        assert b'id="main-content"' in resp.content
        assert b"Open positions" in resp.content


@pytest.mark.django_db
class TestCareersApplyGet:
    def test_active_job_renders_form(self, client, sample_job):
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        assert resp.status_code == 200
        assert "form" in resp.context

    def test_closed_job_renders_read_only_instead_of_404(self, client, sample_job):
        """Shared links outlive the deadline — a closed job must not dead-end on a 404."""
        sample_job.status = "closed"
        sample_job.save()
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        assert resp.status_code == 200
        assert resp.context["applications_open"] is False
        body = resp.content.decode()
        assert "This Job Is No Longer Available" in body
        assert "View Current Job Openings" in body
        # The submission form must be gone, not merely hidden.
        assert 'enctype="multipart/form-data"' not in body

    def test_closed_job_lists_other_open_roles(self, client, sample_job):
        """The closed page is a recovery path, not a dead end."""
        sample_job.status = "closed"
        sample_job.save()
        open_job = Job.objects.create(title="Still Open Role", status="active")
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        body = resp.content.decode()
        assert open_job.title in body
        assert reverse("core:careers_apply", kwargs={"slug": open_job.slug}) in body

    def test_closed_job_never_suggests_another_closed_role(self, client, sample_job):
        """Suggesting a role that is itself unavailable would repeat the bug."""
        sample_job.status = "closed"
        sample_job.save()
        expired = Job.objects.create(
            title="Expired Suggestion",
            status="active",
            closing_date=date.today() - timedelta(days=1),
        )
        drafted = Job.objects.create(title="Draft Suggestion", status="draft")
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        body = resp.content.decode()
        assert expired.title not in body
        assert drafted.title not in body
        # It must not suggest the job the candidate is already looking at.
        assert resp.context["other_jobs"] == []

    def test_draft_job_still_returns_404(self, client, sample_job):
        """Unpublished drafts stay invisible to the public."""
        sample_job.status = "draft"
        sample_job.save()
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestCareersApplyPost:
    def test_valid_submission_creates_resume_and_redirects(self, client, sample_job):
        resp = _post_apply(client, sample_job)
        assert resp.status_code == 302
        assert Resume.objects.filter(
            job=sample_job, candidate_name="Ali Hassan"
        ).exists()

    def test_valid_submission_queues_screening(self, client, sample_job):
        with patch("apps.core.tasks.screen_resume_task.delay") as mock_delay:
            url = reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
            client.post(url, {
                "candidate_name": "Ali Hassan",
                "email": "ali@example.com",
                "phone": "+8801711000000",
                "file": _fake_pdf(),
            })
        mock_delay.assert_called_once()

    def test_valid_submission_redirects_to_thanks(self, client, sample_job):
        resp = _post_apply(client, sample_job)
        assert reverse("core:careers_thanks", kwargs={"slug": sample_job.slug}) in resp["Location"]

    def test_resume_set_to_processing_status(self, client, sample_job):
        _post_apply(client, sample_job)
        resume = Resume.objects.get(job=sample_job, candidate_name="Ali Hassan")
        assert resume.screening_status == "processing"


@pytest.mark.django_db
class TestCareersApplyDuplicates:
    def test_duplicate_email_rejected(self, client, sample_job):
        Resume.objects.create(
            job=sample_job,
            candidate_name="Existing",
            email="ali@example.com",
            screening_status="completed",
        )
        resp = _post_apply(client, sample_job)
        # Should re-render the form, not redirect
        assert resp.status_code == 200
        assert Resume.objects.filter(job=sample_job, email="ali@example.com").count() == 1

    def test_duplicate_email_case_insensitive(self, client, sample_job):
        Resume.objects.create(
            job=sample_job,
            candidate_name="Existing",
            email="ALI@EXAMPLE.COM",
        )
        resp = _post_apply(client, sample_job, extra={"email": "ali@example.com"})
        assert resp.status_code == 200

    def test_duplicate_phone_rejected(self, client, sample_job):
        Resume.objects.create(
            job=sample_job,
            candidate_name="Existing",
            email="other@example.com",
            phone="+8801711000000",
        )
        resp = _post_apply(client, sample_job)
        assert resp.status_code == 200
        assert Resume.objects.filter(job=sample_job, phone="+8801711000000").count() == 1

    def test_duplicate_phone_ignores_formatting(self, client, sample_job):
        """Phone +880 1711-000 000 and +8801711000000 are the same."""
        Resume.objects.create(
            job=sample_job,
            candidate_name="Existing",
            email="other@example.com",
            phone="+880 1711-000 000",
        )
        resp = _post_apply(client, sample_job, extra={"email": "new@example.com"})
        assert resp.status_code == 200

    def test_duplicate_file_hash_rejected(self, client, sample_job):
        from apps.core.utils import compute_file_hash
        pdf_bytes = b"%PDF-1.4 fake content for test"
        file_hash = compute_file_hash(io.BytesIO(pdf_bytes))
        Resume.objects.create(
            job=sample_job,
            candidate_name="Existing",
            email="other@example.com",
            file_hash=file_hash,
        )
        resp = _post_apply(client, sample_job, extra={"email": "new@example.com"})
        assert resp.status_code == 200

    def test_same_email_different_job_allowed(self, client, sample_job, user):
        """Duplicate check is per-job — same email on a different job is fine."""
        other_job = Job.objects.create(
            owner=user, title="Other Job", status="active"
        )
        Resume.objects.create(
            job=other_job,
            candidate_name="Existing",
            email="ali@example.com",
        )
        resp = _post_apply(client, sample_job)
        assert resp.status_code == 302


@pytest.mark.django_db
class TestCareersApplyExpired:
    def test_past_closing_date_blocks_submission(self, client, sample_job):
        """Still 'active' because close_expired_jobs hasn't run yet — the date guard
        must reject the POST on its own."""
        sample_job.closing_date = date.today() - timedelta(days=1)
        sample_job.save()
        resp = _post_apply(client, sample_job)
        assert resp.status_code == 200
        assert resp.context["applications_open"] is False
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_past_closing_date_shows_unavailable_page(self, client, sample_job):
        sample_job.closing_date = date.today() - timedelta(days=1)
        sample_job.save()
        resp = client.get(
            reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "This Job Is No Longer Available" in body
        # The job title stays on the page so the candidate knows which role closed.
        assert sample_job.title in body

    def test_future_closing_date_allows_submission(self, client, sample_job):
        sample_job.closing_date = date.today() + timedelta(days=7)
        sample_job.save()
        resp = _post_apply(client, sample_job)
        assert resp.status_code == 302
        assert Resume.objects.filter(job=sample_job).count() == 1


@pytest.mark.django_db
class TestCareersApplyContactValidation:
    def test_missing_email_blocked(self, client, sample_job):
        resp = _post_apply(client, sample_job, extra={"email": ""})
        assert resp.status_code == 200
        assert Resume.objects.filter(job=sample_job).count() == 0

    def test_missing_phone_blocked(self, client, sample_job):
        resp = _post_apply(client, sample_job, extra={"phone": ""})
        assert resp.status_code == 200
        assert Resume.objects.filter(job=sample_job).count() == 0


@pytest.mark.django_db
class TestCareersThanks:
    def test_thanks_page_renders(self, client, sample_job):
        resp = client.get(
            reverse("core:careers_thanks", kwargs={"slug": sample_job.slug})
        )
        assert resp.status_code == 200


@pytest.mark.django_db
class TestErrorPageStyling:
    """The error pages once pulled Tailwind from cdn.tailwindcss.com. When that CDN
    was unreachable in production the 404 rendered with zero styling — full-size
    SVGs and default blue links. They must be self-hosted."""

    ERROR_TEMPLATES = ["403.html", "404.html", "500.html"]

    @pytest.mark.parametrize("template", ERROR_TEMPLATES)
    def test_no_cdn_stylesheet(self, template):
        from django.template.loader import render_to_string

        html = render_to_string(template)
        assert "cdn.tailwindcss.com" not in html
        assert "/static/css/app.css" in html

    @pytest.mark.parametrize("template", ERROR_TEMPLATES)
    def test_no_external_script_dependency(self, template):
        """Alpine was loaded from a CDN just to drive the dark-mode toggle."""
        from django.template.loader import render_to_string

        html = render_to_string(template)
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html

    def test_404_sends_anonymous_visitors_to_careers_not_login_gated_dashboard(self, client):
        resp = client.get("/careers/no-such-job-slug/")
        assert resp.status_code == 404
        body = resp.content.decode()
        assert reverse("core:careers") in body
        # The dashboard CTA is login-gated; it must only appear for staff.
        assert "Go to Dashboard" not in body
        assert "Browse open positions" in body
