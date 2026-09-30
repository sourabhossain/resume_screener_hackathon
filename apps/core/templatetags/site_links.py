from django import template

from apps.core.links import absolute_url

register = template.Library()


@register.filter(name='site_url')
def site_url(path):
    """A path as a full link on SITE_BASE_URL, the address outsiders can reach."""
    return absolute_url(path)
