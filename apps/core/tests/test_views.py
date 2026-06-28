"""
Unit tests for views.
"""
import pytest
from django.urls import reverse
from apps.core.models import Job, Resume


@pytest.mark.django_db
class TestErrorPages:
    """Tests for custom 404 and 500 error pages."""

    def test_404_page_returns_404(self, client):
        response = client.get('/404/')
        assert response.status_code == 404

    def test_404_page_contains_expected_content(self, client):
        response = client.get('/404/')
        assert b'404' in response.content
        assert b'Page not found' in response.content or b'page not found' in response.content.lower()

    def test_404_page_has_working_cta_for_anonymous(self, client):
        # Anonymous visitors must not be dead-ended at a login-only dashboard:
        # the CTA points to the public careers page instead.
        response = client.get('/404/')
        assert b'Browse open positions' in response.content
        assert b'/careers/' in response.content

    def test_404_page_has_go_back_link(self, client):
        response = client.get('/404/')
        assert b'Go back' in response.content

    def test_500_page_returns_500(self, rf):
        from config.urls import custom_500
        response = custom_500(rf.get('/'))
        assert response.status_code == 500

    def test_500_page_contains_expected_content(self, rf):
        from config.urls import custom_500
        response = custom_500(rf.get('/'))
        assert b'500' in response.content
        assert b'Something went wrong' in response.content

    def test_500_page_has_working_cta(self, rf):
        # The 500 page renders without context processors (no `user`), so its CTA
        # links to the public careers page, which works for anyone.
        from config.urls import custom_500
        response = custom_500(rf.get('/'))
        assert b'/careers/' in response.content
        assert b'Browse open positions' in response.content

    def test_500_page_has_notification_message(self, rf):
        from config.urls import custom_500
        response = custom_500(rf.get('/'))
        assert b'notified' in response.content


@pytest.mark.django_db
class TestHealthCheck:
    """Tests for health check endpoint."""
    
    def test_health_check_success(self, client):
        """Test health check returns 200 and healthy status."""
        response = client.get(reverse('core:health_check'))
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['database'] == 'connected'


@pytest.mark.django_db
class TestDashboardView:
    """Tests for dashboard view."""
    
    def test_dashboard_requires_login(self, client):
        """Test dashboard redirects unauthenticated users."""
        response = client.get(reverse('core:dashboard'))
        assert response.status_code == 302
        assert 'login' in response.url
    
    def test_dashboard_authenticated(self, authenticated_client):
        """Test dashboard accessible when authenticated."""
        response = authenticated_client.get(reverse('core:dashboard'))
        assert response.status_code == 200
    
    def test_dashboard_context(self, authenticated_client, sample_job):
        """Test dashboard contains expected context."""
        response = authenticated_client.get(reverse('core:dashboard'))
        assert 'total_jobs' in response.context
        assert 'active_jobs' in response.context
        assert 'total_resumes' in response.context

    def test_dashboard_counts_needs_review(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        Resume.objects.create(job=sample_job, candidate_name="Pat", screening_status="needs_review")
        response = authenticated_client.get(reverse('core:dashboard'))
        assert response.context['needs_review_count'] == 1
        assert b'Needs review' in response.content  # surfaced in the attention panel

    def test_dashboard_stats_deleted_job_resumes(self, authenticated_client, sample_job, sample_resume):
        """Test dashboard counts exclude resumes from deleted jobs."""
        # Initial check
        response = authenticated_client.get(reverse('core:dashboard'))
        assert response.context['total_resumes'] == 1
        
        # Soft delete the job
        sample_job.soft_delete()
        
        # Check again - currently this will fail if my hypothesis is correct (it will still be 1)
        response = authenticated_client.get(reverse('core:dashboard'))
        
        # We EXPECT resumes from deleted jobs to be excluded? 
        # Usually yes. If the job is deleted, we shouldn't count its resumes as "active" in the system overview.
        assert response.context['total_resumes'] == 0


@pytest.mark.django_db
class TestJobViews:
    """Tests for job CRUD views."""
    
    def test_job_list_requires_login(self, client):
        """Test job list redirects unauthenticated users."""
        response = client.get(reverse('core:job_list'))
        assert response.status_code == 302
    
    def test_job_list_authenticated(self, authenticated_client):
        """Test job list accessible when authenticated."""
        response = authenticated_client.get(reverse('core:job_list'))
        assert response.status_code == 200
    
    def test_job_list_search(self, authenticated_client, sample_job):
        """Test job list search functionality."""
        response = authenticated_client.get(
            reverse('core:job_list'), 
            {'q': 'Python'}
        )
        assert response.status_code == 200
        assert sample_job in response.context['jobs']
    
    def test_job_list_default_active(self, authenticated_client, sample_job):
        """Bare /jobs/ defaults to the 'active' filter — only active jobs are shown."""
        # Create a draft job
        Job.objects.create(title='Draft Job', status='draft', owner=sample_job.owner)

        response = authenticated_client.get(reverse('core:job_list'))

        # Should only contain the active job (draft is filtered out by default)
        assert len(response.context['jobs']) == 1
        assert response.context['jobs'][0] == sample_job
        assert response.context['status_filter'] == 'active'

    def test_job_list_all_filter(self, authenticated_client, sample_job):
        """Test explicit 'all' filter returns all jobs."""
        Job.objects.create(title='Draft Job', status='draft', owner=sample_job.owner)
        
        response = authenticated_client.get(reverse('core:job_list'), {'status': 'all'})
        
        # Should contain both jobs
        assert len(response.context['jobs']) == 2
        assert response.context['status_filter'] == 'all'
        
    def test_job_list_filter_status(self, authenticated_client, sample_job):
        """Test job list status filter."""
        response = authenticated_client.get(
            reverse('core:job_list'), 
            {'status': 'active'}
        )
        assert response.status_code == 200
        assert sample_job in response.context['jobs']
    
    def test_job_create_get(self, authenticated_client):
        """Test job create form displays."""
        response = authenticated_client.get(reverse('core:job_create'))
        assert response.status_code == 200
        assert 'form' in response.context
    
    def test_job_create_post(self, authenticated_client):
        """Test creating a new job."""
        data = {
            'title': 'New Job',
            'description': 'Job description',
            'status': 'draft'
        }
        response = authenticated_client.post(reverse('core:job_create'), data)
        assert response.status_code == 302  # Redirect after success
        assert Job.objects.filter(title='New Job').exists()
    
    def test_job_detail(self, authenticated_client, sample_job):
        """Test job detail view."""
        response = authenticated_client.get(
            reverse('core:job_detail', kwargs={'slug': sample_job.slug})
        )
        assert response.status_code == 200
        assert response.context['job'] == sample_job
    
    def test_job_detail_candidates_interview_ordered_first(self, authenticated_client, sample_job):
        """Interview-tier candidates sort above talent pool when scores reflect those tiers."""
        Resume.objects.filter(job=sample_job).delete()
        Resume.objects.create(
            job=sample_job,
            candidate_name='Interview tier candidate',
            final_score=85,
        )
        Resume.objects.create(
            job=sample_job,
            candidate_name='Talent pool candidate',
            final_score=70,
        )
        response = authenticated_client.get(
            reverse('core:job_detail', kwargs={'slug': sample_job.slug})
        )
        names = [r.candidate_name for r in response.context['resumes']]
        assert names[0] == 'Interview tier candidate'
        assert names[1] == 'Talent pool candidate'
    
    def test_job_edit(self, authenticated_client, sample_job):
        """Test editing a job."""
        data = {
            'title': 'Updated Title',
            'description': sample_job.description,
            'status': sample_job.status
        }
        authenticated_client.post(
            reverse('core:job_edit', kwargs={'slug': sample_job.slug}),
            data
        )
        sample_job.refresh_from_db()
        assert sample_job.title == 'Updated Title'
    
    def test_job_delete(self, authenticated_client, sample_job):
        """Test soft deleting a job."""
        response = authenticated_client.post(
            reverse('core:job_delete', kwargs={'slug': sample_job.slug})
        )
        assert response.status_code == 302
        assert Job.objects.filter(pk=sample_job.pk).count() == 0


@pytest.mark.django_db
class TestResumeViews:
    """Tests for resume CRUD views."""
    
    def test_resume_create_requires_active_job(self, authenticated_client, sample_job):
        """Test resume creation requires active job."""
        sample_job.status = 'draft'
        sample_job.save()
        
        response = authenticated_client.get(
            reverse('core:resume_create', kwargs={'job_slug': sample_job.slug})
        )
        # Should redirect with error message
        assert response.status_code == 302
    
    def test_resume_detail(self, authenticated_client, sample_resume):
        """Test resume detail view."""
        response = authenticated_client.get(
            reverse('core:resume_detail', kwargs={'uuid': sample_resume.uuid})
        )
        assert response.status_code == 200
        assert response.context['resume'] == sample_resume
    
    def test_needs_review_list_shows_only_needs_review(self, authenticated_client, sample_job, sample_resume):
        from apps.core.models import Resume
        nr = Resume.objects.create(job=sample_job, candidate_name="Uncertain Uma", screening_status="needs_review")
        resp = authenticated_client.get(reverse('core:needs_review'))
        assert resp.status_code == 200
        names = [r.candidate_name for r in resp.context['page_obj']]
        assert "Uncertain Uma" in names
        assert sample_resume.candidate_name not in names  # completed one excluded

    def test_pipeline_row_shows_needs_review_badge(self, authenticated_client, sample_job):
        from apps.core.models import Resume
        nr = Resume.objects.create(job=sample_job, candidate_name="Uma", screening_status="needs_review")
        body = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': nr.uuid})
        ).content.decode()
        assert "Needs review" in body  # distinguishable from a plain unscored row

    def test_detail_disables_screening_button_while_processing(self, authenticated_client, sample_resume):
        """While screening is running, the action shows a disabled state and NO
        rescreen form — so repeated clicks can't spam re-runs or pollute history."""
        sample_resume.screening_status = 'processing'
        sample_resume.save(update_fields=['screening_status'])
        body = authenticated_client.get(
            reverse('core:resume_detail', kwargs={'uuid': sample_resume.uuid})
        ).content.decode()
        assert 'Screening in progress' in body
        assert reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid}) not in body
        # The header action must appear exactly once (no duplicate id on full page).
        assert body.count('id="screening-action"') == 1

    def test_status_fragment_oob_refreshes_action_button(self, authenticated_client, sample_resume):
        """The polling fragment carries an OOB swap of the action button so it
        updates the moment screening finishes — no full reload needed."""
        sample_resume.screening_status = 'processing'
        sample_resume.save(update_fields=['screening_status'])
        body = authenticated_client.get(
            reverse('core:resume_status_fragment', kwargs={'uuid': sample_resume.uuid})
        ).content.decode()
        assert 'id="screening-action"' in body
        assert 'hx-swap-oob="true"' in body

    def test_resume_delete(self, authenticated_client, sample_resume):
        """Test soft deleting a resume."""
        response = authenticated_client.post(
            reverse('core:resume_delete', kwargs={'uuid': sample_resume.uuid})
        )
        assert response.status_code == 302
        assert Resume.objects.filter(pk=sample_resume.pk).count() == 0

    def test_resume_create_get_form(self, authenticated_client, sample_job):
        """Test resume upload form renders for active job."""
        response = authenticated_client.get(
            reverse('core:resume_create', kwargs={'job_slug': sample_job.slug})
        )
        assert response.status_code == 200
        assert 'form' in response.context

    def test_resume_create_post(self, authenticated_client, sample_job, monkeypatch):
        """Test submitting a valid resume queues screening and redirects."""
        import io
        from unittest.mock import patch

        # Stub Celery task so no real task is dispatched
        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            pdf_bytes = b'%PDF-1.4 fake content'
            fake_file = io.BytesIO(pdf_bytes)
            fake_file.name = 'test_resume.pdf'

            response = authenticated_client.post(
                reverse('core:resume_create', kwargs={'job_slug': sample_job.slug}),
                {
                    'candidate_name': 'Jane Smith',
                    'file': fake_file,
                },
            )

        assert response.status_code == 302
        assert Resume.objects.filter(candidate_name='Jane Smith', job=sample_job).exists()
        mock_delay.assert_called_once()

    def test_resume_rescreen_queues_task(self, authenticated_client, sample_resume):
        """Test re-screening a resume queues the screening task."""
        from unittest.mock import patch

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            response = authenticated_client.post(
                reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid})
            )

        assert response.status_code == 302
        mock_delay.assert_called_once_with(sample_resume.id)

    def test_resume_rescreen_htmx_swaps_in_place_without_redirect(self, authenticated_client, sample_resume):
        """An HTMX rescreen swaps the status region in place (200, no 302 redirect)
        so it doesn't push a duplicate browser-history entry."""
        from unittest.mock import patch

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            response = authenticated_client.post(
                reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid}),
                HTTP_HX_REQUEST='true',
            )

        assert response.status_code == 200  # fragment, not a 302 redirect
        mock_delay.assert_called_once_with(sample_resume.id)
        body = response.content.decode()
        assert 'id="screening-status"' in body          # status region swapped in place
        assert 'hx-swap-oob="true"' in body             # action button OOB-refreshed
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'processing'

    def test_resume_rescreen_allowed_for_needs_review(self, authenticated_client, sample_resume):
        """A needs_review resume shows the Run AI Screening button, so clicking it
        must actually re-queue (not silently do nothing)."""
        from unittest.mock import patch

        sample_resume.screening_status = 'needs_review'
        sample_resume.save(update_fields=['screening_status'])

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            response = authenticated_client.post(
                reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid})
            )

        assert response.status_code == 302
        mock_delay.assert_called_once_with(sample_resume.id)
        sample_resume.refresh_from_db()
        assert sample_resume.screening_status == 'processing'

    def test_resume_rescreen_blocked_while_processing(self, authenticated_client, sample_resume):
        """Test re-screening is blocked when screening is already in progress."""
        from unittest.mock import patch

        sample_resume.screening_status = 'processing'
        sample_resume.save()

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            response = authenticated_client.post(
                reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid})
            )

        assert response.status_code == 302
        mock_delay.assert_not_called()

    def test_resume_edit_post(self, authenticated_client, sample_resume):
        """Test editing a resume's scores and candidate name."""
        data = {
            'candidate_name': 'John Doe Updated',
            'experience_score': 92,
            'education_score': 80,
            'skills_score': 88,
            'certification_score': '',
            'achievement_score': '',
            'final_score': 87,
        }
        response = authenticated_client.post(
            reverse('core:resume_edit', kwargs={'uuid': sample_resume.uuid}),
            data,
        )
        assert response.status_code == 302
        sample_resume.refresh_from_db()
        assert sample_resume.candidate_name == 'John Doe Updated'
        assert float(sample_resume.final_score) == 87

    def test_resume_rescreen_get_redirects(self, authenticated_client, sample_resume):
        """Test GET to rescreen endpoint redirects without queuing."""
        from unittest.mock import patch

        with patch('apps.core.tasks.screen_resume_task.delay') as mock_delay:
            response = authenticated_client.get(
                reverse('core:resume_rescreen', kwargs={'uuid': sample_resume.uuid})
            )

        assert response.status_code == 302
        mock_delay.assert_not_called()

    def test_resume_status_fragment_returns_200(self, authenticated_client, sample_resume):
        """Test the HTMX status fragment endpoint renders successfully."""
        response = authenticated_client.get(
            reverse('core:resume_status_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert response.status_code == 200

    def test_resume_row_fragment_returns_200(self, authenticated_client, sample_resume):
        """Test the HTMX table-row fragment endpoint renders successfully."""
        response = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert response.status_code == 200

    def test_resume_status_fragment_polls_when_processing(self, authenticated_client, sample_resume):
        """Fragment includes polling trigger when screening is in progress."""
        sample_resume.screening_status = 'processing'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_status_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' in response.content

    def test_resume_status_fragment_no_poll_when_done(self, authenticated_client, sample_resume):
        """Fragment omits polling trigger when screening is complete, stopping the poll."""
        sample_resume.screening_status = 'completed'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_status_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' not in response.content

    def test_resume_row_fragment_polls_when_processing(self, authenticated_client, sample_resume):
        """Row fragment includes polling trigger when screening is in progress."""
        sample_resume.screening_status = 'processing'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' in response.content

    def test_resume_row_fragment_polls_when_verification_processing(self, authenticated_client, sample_resume):
        """Row fragment keeps polling when screening is done but verification is still running."""
        sample_resume.screening_status = 'completed'
        sample_resume.verification_status = 'processing'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' in response.content

    def test_resume_row_fragment_no_poll_when_done(self, authenticated_client, sample_resume):
        """Row fragment stops polling only when both screening and verification are terminal."""
        sample_resume.screening_status = 'completed'
        sample_resume.verification_status = 'completed'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' not in response.content

    def test_resume_row_fragment_no_poll_when_screening_done_verification_skipped(self, authenticated_client, sample_resume):
        """Row fragment stops polling when screening is complete and verification is skipped."""
        sample_resume.screening_status = 'completed'
        sample_resume.verification_status = 'skipped'
        sample_resume.save()
        response = authenticated_client.get(
            reverse('core:resume_row_fragment', kwargs={'uuid': sample_resume.uuid})
        )
        assert b'hx-trigger="every 3s"' not in response.content


@pytest.mark.django_db
class TestLoginRatelimitFailsafe:
    """Login fails closed (503) when rate-limit cache is unreachable;
    non-auth endpoints keep fail-open behavior."""

    def test_login_post_returns_503_when_cache_unreachable(self, client, monkeypatch):
        """POST /login/ returns 503 instead of bypassing rate limit when Redis is down."""
        from django.core.cache import caches
        monkeypatch.setattr(caches['default'], 'is_available', lambda: False, raising=False)
        response = client.post(reverse('login'), {'username': 'x', 'password': 'y'})
        assert response.status_code == 503

    def test_login_post_503_carries_retry_after_header(self, client, monkeypatch):
        """503 response includes Retry-After so clients know when to retry."""
        from django.core.cache import caches
        monkeypatch.setattr(caches['default'], 'is_available', lambda: False, raising=False)
        response = client.post(reverse('login'), {'username': 'x', 'password': 'y'})
        assert response.status_code == 503
        assert response['Retry-After'] == '60'

    def test_login_get_unaffected_when_cache_unreachable(self, client, monkeypatch):
        """GET /login/ (form render) is not blocked; fail-closed applies to POST only."""
        from django.core.cache import caches
        monkeypatch.setattr(caches['default'], 'is_available', lambda: False, raising=False)
        response = client.get(reverse('login'))
        assert response.status_code == 200

    def test_careers_apply_fails_open_when_cache_unreachable(self, client, sample_job, monkeypatch):
        """careers_apply GET succeeds (fail-open) even when is_available() returns False.
        _auth_cache_required is not applied to non-auth endpoints."""
        from django.core.cache import caches
        monkeypatch.setattr(caches['default'], 'is_available', lambda: False, raising=False)
        response = client.get(
            reverse('core:careers_apply', kwargs={'slug': sample_job.slug})
        )
        assert response.status_code == 200
