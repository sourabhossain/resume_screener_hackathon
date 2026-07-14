"""Primary-nav markup guards.

The three pipeline-triage pages (Talent Pool / Needs Review / Screening Failed)
are grouped under a "Pipeline" dropdown in the desktop nav so the row stays one
line. These pin: the dropdown trigger's ARIA wiring, that all three destinations
are reachable from inside the popup, the close affordances (click-away + Escape),
and that the mobile menu still lists all three directly.
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestPrimaryNavPipelineDropdown:
    def _nav_html(self, client):
        return client.get(reverse('core:dashboard')).content.decode()

    def test_dropdown_trigger_has_aria_wiring(self, authenticated_client):
        html = self._nav_html(authenticated_client)
        assert 'aria-haspopup="menu"' in html          # button announces a menu popup
        assert ':aria-expanded="pipelineOpen"' in html  # expanded state bound to Alpine
        assert 'Pipeline' in html                        # the group label

    def test_popup_contains_all_three_destinations(self, authenticated_client):
        html = self._nav_html(authenticated_client)
        assert 'role="menu"' in html
        assert reverse('core:talent_pool') in html
        assert reverse('core:needs_review') in html
        assert reverse('core:screening_failed') in html

    def test_dropdown_closes_on_clickaway_and_escape(self, authenticated_client):
        html = self._nav_html(authenticated_client)
        assert '@click.outside="pipelineOpen = false"' in html
        assert '@keydown.escape' in html

    def test_mobile_menu_still_lists_all_three_directly(self, authenticated_client):
        """Each destination appears at least twice: once in the desktop Pipeline
        popup and once as a direct mobile-menu entry."""
        html = self._nav_html(authenticated_client)
        assert html.count(reverse('core:talent_pool')) >= 2
        assert html.count(reverse('core:needs_review')) >= 2
        assert html.count(reverse('core:screening_failed')) >= 2

    def test_x_show_popup_carries_no_inline_flex_or_grid(self, authenticated_client):
        """Alpine discipline: the x-show popup is a plain wrapper, never an element
        whose own inline style forces display:flex/grid."""
        from html.parser import HTMLParser

        class _Collector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append(dict(attrs))

        c = _Collector()
        c.feed(self._nav_html(authenticated_client))
        offenders = [
            a for a in c.tags
            if 'x-show' in a
            and any(x in (a.get('style') or '').replace(' ', '').lower()
                    for x in ('display:flex', 'display:grid'))
        ]
        assert not offenders, f"x-show on flex/grid inline-styled element: {offenders}"
