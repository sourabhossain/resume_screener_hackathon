import pytest
from dotenv import load_dotenv
from django.test import Client

# Load environment variables
load_dotenv()


@pytest.fixture(autouse=True)
def _stub_verify_resume_links_delay(monkeypatch):
    """Avoid real Celery/network during ResumeService.apply_screening_result in tests."""
    from apps.core.tasks import verify_resume_links_task

    monkeypatch.setattr(verify_resume_links_task, 'delay', lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the cache between tests so django-ratelimit counters (cache-backed,
    keyed by IP) don't leak across tests and trip the per-IP limits."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    """Django test client fixture."""
    return Client()


@pytest.fixture
def user(db, django_user_model):
    """The recruiter used by both the authenticated client and the owned sample data."""
    return django_user_model.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def authenticated_client(client, user):
    """Authenticated Django test client fixture (logged in as `user`)."""
    client.login(username='testuser', password='testpass123')
    return client


@pytest.fixture
def sample_job(db, user):
    """Create a sample job owned by `user` for testing."""
    from apps.core.models import Job
    return Job.objects.create(
        owner=user,
        title='Senior Python Developer',
        description='Looking for experienced Python developer',
        status='active'
    )


@pytest.fixture
def sample_resume(db, sample_job):
    """Create a sample resume for testing."""
    from apps.core.models import Resume
    return Resume.objects.create(
        job=sample_job,
        candidate_name='John Doe',
        experience_score=85,
        education_score=75,
        skills_score=90,
        final_score=85
    )
