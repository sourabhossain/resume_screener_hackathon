"""
Tests for CV Link Verification: LinkExtractor, LinkVerifier scoring, and the Celery task.
"""
import pytest
from unittest.mock import patch

class TestLinkExtractor:

    def test_extracts_github_url(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "My GitHub: github.com/sourab-hossain and portfolio at sourab.dev"
        links = LinkExtractor.extract(text)
        github_links = [l for l in links if l.link_type == 'github']
        assert len(github_links) == 1
        assert 'github.com/sourab-hossain' in github_links[0].url

    def test_skips_email_domains(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "Contact: sourab@gmail.com or visit github.com/sourab"
        links = LinkExtractor.extract(text)
        urls = [l.url for l in links]
        assert not any('gmail.com' in u for u in urls)

    def test_deduplicates_same_url(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "github.com/sourab and also github.com/sourab again"
        links = LinkExtractor.extract(text)
        assert len(links) == 1

    def test_max_10_links(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = " ".join([f"site{i}.com" for i in range(20)])
        links = LinkExtractor.extract(text)
        assert len(links) <= 10

    def test_classifies_linkedin_correctly(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "LinkedIn: linkedin.com/in/sourab-hossain"
        links = LinkExtractor.extract(text)
        assert links[0].link_type == 'linkedin'

    def test_classifies_github_correctly(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "GitHub: github.com/sourab-hossain"
        links = LinkExtractor.extract(text)
        assert links[0].link_type == 'github'

    def test_classifies_portfolio_as_portfolio(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "Portfolio: sourab.dev/projects"
        links = LinkExtractor.extract(text)
        assert links[0].link_type == 'portfolio'

    def test_normalizes_url_without_scheme(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "github.com/sourab"
        links = LinkExtractor.extract(text)
        assert links[0].url.startswith('https://')

    def test_skips_social_domains(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "twitter.com/sourab facebook.com/sourab github.com/sourab"
        links = LinkExtractor.extract(text)
        urls = [l.url for l in links]
        assert not any('twitter.com' in u for u in urls)
        assert not any('facebook.com' in u for u in urls)
        assert any('github.com' in u for u in urls)

    def test_captures_context_around_url(self):
        from apps.core.services.link_extractor import LinkExtractor
        text = "Check out my open source work at github.com/sourab-hossain for details"
        links = LinkExtractor.extract(text)
        assert len(links) == 1
        assert 'github.com/sourab-hossain' in links[0].raw_text

    def test_skips_urls_blocked_by_ssrf_guard(self, monkeypatch):
        from apps.core.services import link_extractor as le
        monkeypatch.setattr(
            le,
            'is_safe_public_http_url',
            lambda url, resolve_dns=True: (False, 'blocked'),
        )
        links = le.LinkExtractor.extract('https://public.example/foo')
        assert links == []

class TestLinkVerifierScore:

    def test_full_verification_score(self):
        from apps.core.services.link_verifier import LinkVerifier
        details = [
            {'status': 'verified', 'verified_claims': ['Python', 'Django'], 'discrepancies': [], 'confidence': 0.9},
            {'status': 'verified', 'verified_claims': ['React'], 'discrepancies': [], 'confidence': 0.8},
        ]
        score = LinkVerifier._calculate_score(details)
        assert score > 70

    def test_discrepancies_lower_score(self):
        from apps.core.services.link_verifier import LinkVerifier
        details = [
            {'status': 'verified', 'verified_claims': ['Python'], 'discrepancies': ['claimed 5 years, found 2 years'], 'confidence': 0.9},
        ]
        score = LinkVerifier._calculate_score(details)
        assert score < 70

    def test_no_verified_links_returns_zero(self):
        from apps.core.services.link_verifier import LinkVerifier
        details = [
            {'status': 'unreachable', 'verified_claims': [], 'discrepancies': [], 'confidence': 0.0},
        ]
        score = LinkVerifier._calculate_score(details)
        assert score == 0.0

    def test_empty_details_returns_zero(self):
        from apps.core.services.link_verifier import LinkVerifier
        score = LinkVerifier._calculate_score([])
        assert score == 0.0

    def test_score_capped_at_100(self):
        from apps.core.services.link_verifier import LinkVerifier
        details = [
            {'status': 'verified', 'verified_claims': ['a', 'b', 'c', 'd', 'e'], 'discrepancies': [], 'confidence': 1.0},
        ]
        score = LinkVerifier._calculate_score(details)
        assert score <= 100.0

    def test_zero_claims_and_discrepancies_gives_50_base(self):
        from apps.core.services.link_verifier import LinkVerifier
        details = [
            {'status': 'verified', 'verified_claims': [], 'discrepancies': [], 'confidence': 1.0},
        ]
        score = LinkVerifier._calculate_score(details)
        assert score == 50.0

    def test_clean_html_strips_tags(self):
        from apps.core.services.link_verifier import LinkVerifier
        html = "<html><head><script>var x=1;</script></head><body><p>Hello World</p></body></html>"
        result = LinkVerifier._clean_html(html)
        assert 'Hello World' in result
        assert '<' not in result
        assert 'var x=1' not in result

@pytest.mark.django_db
class TestVerifyResumeLinksTask:

    @patch('apps.core.services.link_verifier.LinkVerifier.verify_resume')
    def test_task_updates_verification_status(self, mock_verify, sample_resume):
        from apps.core.tasks import verify_resume_links_task

        mock_verify.return_value = {
            'status': 'completed',
            'verification_score': 85.0,
            'verified_claims': ['Python', 'Django'],
            'discrepancies': [],
            'links_found': 2,
            'links_verified': 2,
            'details': []
        }

        verify_resume_links_task(sample_resume.id)
        sample_resume.refresh_from_db()
        assert sample_resume.verification_status == 'completed'
        assert sample_resume.verification_score == 85.0

    def test_task_handles_missing_resume(self):
        from apps.core.tasks import verify_resume_links_task
        result = verify_resume_links_task(99999)
        assert result['error'] == 'Resume not found'

    @patch('apps.core.services.link_verifier.LinkVerifier.verify_resume')
    def test_task_handles_no_links(self, mock_verify, sample_resume):
        from apps.core.tasks import verify_resume_links_task

        mock_verify.return_value = {
            'status': 'skipped',
            'reason': 'No verifiable links found in CV',
            'verification_score': None,
            'links_found': 0,
            'links_verified': 0,
            'verified_claims': [],
            'discrepancies': [],
            'details': []
        }

        verify_resume_links_task(sample_resume.id)
        sample_resume.refresh_from_db()
        assert sample_resume.verification_status == 'skipped'
        assert sample_resume.verified_at is None
        assert sample_resume.verified_at is None

    @patch('apps.core.services.link_verifier.LinkVerifier.verify_resume')
    def test_task_stores_verification_results(self, mock_verify, sample_resume):
        from apps.core.tasks import verify_resume_links_task

        expected = {
            'status': 'completed',
            'verification_score': 72.5,
            'verified_claims': ['Python'],
            'discrepancies': [],
            'links_found': 1,
            'links_verified': 1,
            'details': [{'url': 'https://github.com/test', 'status': 'verified'}]
        }
        mock_verify.return_value = expected

        verify_resume_links_task(sample_resume.id)
        sample_resume.refresh_from_db()
        assert sample_resume.verification_results['links_found'] == 1
        assert sample_resume.verified_at is not None

    @patch('apps.core.services.link_verifier.LinkVerifier.verify_resume')
    def test_task_sets_processing_before_running(self, mock_verify, sample_resume):
        from apps.core.tasks import verify_resume_links_task
        from apps.core.models import Resume

        statuses = []

        def capture_and_return(resume):
            r = Resume.objects.get(id=resume.id)
            statuses.append(r.verification_status)
            return {
                'status': 'completed', 'verification_score': 80.0,
                'verified_claims': [], 'discrepancies': [],
                'links_found': 1, 'links_verified': 1, 'details': []
            }

        mock_verify.side_effect = capture_and_return
        verify_resume_links_task(sample_resume.id)
        assert 'processing' in statuses
