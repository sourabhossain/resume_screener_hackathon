"""Authenticated, rate-limited serving of protected media (resume/job files)."""
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django_ratelimit.decorators import ratelimit

@login_required
@ratelimit(key='user', rate='60/m', block=True)
def serve_protected_media(request, path):
    full_path = os.path.join(settings.MEDIA_ROOT, path)
    media_root = os.path.abspath(settings.MEDIA_ROOT) + os.sep
    if not os.path.abspath(full_path).startswith(media_root):
        raise Http404
    if not os.path.exists(full_path):
        raise Http404
    return FileResponse(open(full_path, 'rb'), as_attachment=True)
