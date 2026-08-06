"""
Template integrity checks that unit tests on view logic cannot catch.

These exist because two real bugs shipped past a green suite: a multi-line
Django comment rendered as literal text on the live 404 page, and the error
pages pulled Tailwind from a CDN that the app's own CSP blocked, stripping
every style off the page.
"""
import pathlib
import re
from datetime import date, timedelta

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from apps.core.models import Job
from config.middleware import ContentSecurityPolicyMiddleware

CSP = ContentSecurityPolicyMiddleware._CSP


def _strip_code(html):
    """Tag-like text inside <script>/<style> is not markup."""
    return re.sub(r'<(script|style)\b.*?</\1>', '', html, flags=re.S | re.I)


def _balance(html, tag):
    html = _strip_code(html)
    opens = len(re.findall(rf'<{tag}[\s>]', html))
    closes = len(re.findall(rf'</{tag}>', html))
    return opens, closes


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["open", "closed", "expired"])
def test_apply_page_html_is_balanced(client, sample_job, state):
    if state == "closed":
        sample_job.status = "closed"
    elif state == "expired":
        sample_job.closing_date = date.today() - timedelta(days=1)
    sample_job.save()
    Job.objects.create(title="A Live Role", status="active")

    html = client.get(
        reverse("core:careers_apply", kwargs={"slug": sample_job.slug})
    ).content.decode()

    for tag in ("div", "main", "nav", "footer", "a", "form", "body", "html"):
        o, c = _balance(html, tag)
        assert o == c, f"{state}: <{tag}> {o} open vs {c} close"


@pytest.mark.django_db
@pytest.mark.parametrize("path,kind", [("/404/", "404")])
def test_error_page_html_is_balanced(client, path, kind):
    html = client.get(path).content.decode()
    for tag in ("div", "main", "nav", "body", "html", "a", "svg"):
        o, c = _balance(html, tag)
        assert o == c, f"{kind}: <{tag}> {o} open vs {c} close"


@pytest.mark.django_db
def test_no_unrendered_template_syntax_leaks_into_any_page(client, sample_job):
    """A stray {# #} or {% %} in the output means a template bug."""
    sample_job.status = "closed"
    sample_job.save()
    pages = [
        reverse("core:careers"),
        reverse("core:careers_apply", kwargs={"slug": sample_job.slug}),
        "/404/",
        reverse("login"),
    ]
    for p in pages:
        html = client.get(p).content.decode()
        assert "{#" not in html, f"{p}: leaked Django comment"
        assert "{%" not in html, f"{p}: leaked template tag"
        assert "{{" not in html, f"{p}: leaked template variable"

def _allowed(directive):
    m = re.search(rf'{directive}([^;]*)', CSP)
    return set(re.findall(r'https://([a-z0-9.-]+)', m.group(1))) if m else set()


@pytest.mark.parametrize("template", ["403.html", "404.html", "500.html"])
def test_error_pages_load_no_csp_blocked_origin(template):
    html = render_to_string(template)
    script_ok = _allowed('script-src')
    style_ok = _allowed('style-src')
    font_ok = _allowed('font-src')
    for host in re.findall(r'<script[^>]+src="https://([a-z0-9.-]+)', html):
        assert host in script_ok, f"{template}: script from {host} is blocked by CSP"
    for host in re.findall(r'<link[^>]+href="https://([a-z0-9.-]+)', html):
        assert host in style_ok | font_ok, f"{template}: link to {host} is blocked by CSP"


@pytest.mark.parametrize("template", ["403.html", "404.html", "500.html"])
def test_error_pages_are_self_contained_for_styling(template):
    """Styling must never depend on a third-party host."""
    html = render_to_string(template)
    assert '/static/css/app.css' in html
    assert not re.search(r'<link[^>]+stylesheet[^>]+https://(?!fonts\.googleapis)', html)


def test_css_cache_buster_is_consistent_everywhere():
    import pathlib
    versions = set()
    for p in pathlib.Path('templates').rglob('*.html'):
        versions |= set(re.findall(r"app\.css'\s*%\}\?v=(\d+)", p.read_text()))
    assert len(versions) == 1, f"mismatched app.css cache-busters: {versions}"


@pytest.mark.django_db
def test_500_page_renders_without_touching_the_database(rf):
    """A 500 is often caused by the DB being down; the handler must not re-query it."""
    from django.db import connection
    from config.urls import custom_500

    queries_before = len(connection.queries_log)
    resp = custom_500(rf.get('/'))
    assert resp.status_code == 500
    assert len(connection.queries_log) == queries_before, "500 page issued a DB query"


@pytest.mark.django_db
def test_404_shows_dashboard_cta_only_to_authenticated_users(client, user):
    assert b'Go to Dashboard' not in client.get('/404/').content
    client.force_login(user)
    assert b'Go to Dashboard' in client.get('/404/').content


@pytest.mark.django_db
def test_location_chip_is_not_duplicated_when_it_equals_location_type(client):
    """A job with location_type=remote and location='Remote' must not show two
    identical chips on either the listing or the job page."""
    job = Job.objects.create(
        title="Remote Role", status="active",
        location_type="remote", location="Remote",
    )
    for path in [reverse("core:careers"),
                 reverse("core:careers_apply", kwargs={"slug": job.slug})]:
        html = client.get(path).content.decode()
        assert html.count(">Remote<") == 1, f"{path}: duplicated location chip"


@pytest.mark.django_db
def test_distinct_location_still_shown(client):
    job = Job.objects.create(
        title="Dhaka Role", status="active",
        location_type="hybrid", location="Dhaka, Bangladesh",
    )
    html = client.get(
        reverse("core:careers_apply", kwargs={"slug": job.slug})
    ).content.decode()
    assert "Hybrid" in html and "Dhaka, Bangladesh" in html
