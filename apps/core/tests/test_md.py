"""The `md` filter renders recruiter markdown on PUBLIC careers pages, so it must
be XSS-safe while preserving normal markdown formatting."""
from apps.core.templatetags.md import markdown


def test_raw_script_is_escaped():
    out = markdown('## Job\n<script>alert(1)</script>')
    assert '<script>' not in out
    assert '&lt;script&gt;' in out


def test_img_onerror_is_escaped():
    out = markdown('## J\n<img src=x onerror=alert(1)>')
    assert '<img' not in out
    assert 'onerror' not in out or '&lt;img' in out


def test_javascript_link_scheme_stripped():
    out = markdown('## Job\n[click](javascript:alert(1))')
    assert 'javascript:' not in out
    assert 'href="#"' in out


def test_data_uri_link_stripped():
    out = markdown('## Job\n[x](data:text/html,<script>alert(1)</script>)')
    assert 'data:text/html' not in out


def test_normal_markdown_preserved():
    out = markdown('## Title\n- one\n- two\n\n**bold** and [site](https://ok.com)')
    assert '<h2>Title</h2>' in out
    assert '<li>one</li>' in out
    assert '<strong>bold</strong>' in out
    assert '<a href="https://ok.com">site</a>' in out


def test_plain_text_branch_still_escapes():
    # Non-"# heading" text goes through _plain_to_html, which escapes everything.
    out = markdown('We need <b>X</b> & <script>bad</script>')
    assert '<script>' not in out
    assert '<b>X</b>' not in out
