"""
Security tests for serve_protected_media:
- Unauthenticated access → redirect to login
- Valid authenticated request → file served
- Path-traversal attempts (../../../etc/passwd etc.) → 404
- Non-existent file → 404
"""
import os
import pytest
from django.urls import reverse


# ── helpers ───────────────────────────────────────────────────────────────────

def _media_url(path):
    """Build the protected-media URL for a given relative path."""
    return f"/media/{path}"


# ── authentication guard ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProtectedMediaAuth:

    def test_unauthenticated_redirects_to_login(self, client, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        f = tmp_path / "resumes" / "test.pdf"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"%PDF test")

        resp = client.get(_media_url("resumes/test.pdf"))
        assert resp.status_code == 302
        assert "login" in resp["Location"]

    def test_authenticated_serves_file(self, authenticated_client, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        f = tmp_path / "resumes" / "test.pdf"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"%PDF test content")

        resp = authenticated_client.get(_media_url("resumes/test.pdf"))
        assert resp.status_code == 200
        assert b"%PDF test content" in b"".join(resp.streaming_content)

    def test_nonexistent_file_returns_404(self, authenticated_client, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        resp = authenticated_client.get(_media_url("resumes/nonexistent.pdf"))
        assert resp.status_code == 404


# ── path traversal guard ──────────────────────────────────────────────────────

@pytest.mark.django_db
class TestProtectedMediaPathTraversal:

    def test_dotdot_traversal_returns_404(self, authenticated_client, tmp_path, settings):
        """../../../etc/passwd must NOT escape MEDIA_ROOT."""
        settings.MEDIA_ROOT = str(tmp_path)
        resp = authenticated_client.get(_media_url("../../../etc/passwd"))
        assert resp.status_code == 404

    def test_encoded_traversal_returns_404(self, authenticated_client, tmp_path, settings):
        """%2e%2e%2f traversal attempt must be blocked."""
        settings.MEDIA_ROOT = str(tmp_path)
        resp = authenticated_client.get(_media_url("%2e%2e%2fetc%2fpasswd"))
        assert resp.status_code == 404

    def test_traversal_to_sibling_dir_returns_404(self, authenticated_client, tmp_path, settings):
        """Path that resolves outside MEDIA_ROOT (sibling directory) is blocked."""
        settings.MEDIA_ROOT = str(tmp_path / "media")
        (tmp_path / "media").mkdir()
        # Create a file in a sibling directory
        sibling = tmp_path / "secrets"
        sibling.mkdir()
        secret_file = sibling / "secret.txt"
        secret_file.write_text("TOP SECRET")

        resp = authenticated_client.get(_media_url("../secrets/secret.txt"))
        assert resp.status_code == 404

    def test_legitimate_nested_path_serves_file(self, authenticated_client, tmp_path, settings):
        """A legitimate sub-directory path within MEDIA_ROOT still works."""
        settings.MEDIA_ROOT = str(tmp_path)
        nested = tmp_path / "resumes" / "2026"
        nested.mkdir(parents=True)
        f = nested / "cv.pdf"
        f.write_bytes(b"%PDF-1.4 legitimate")

        resp = authenticated_client.get(_media_url("resumes/2026/cv.pdf"))
        assert resp.status_code == 200
