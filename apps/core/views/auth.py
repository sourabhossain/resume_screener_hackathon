"""Authentication views."""
from django.contrib.auth import views as auth_views

from ..form_utils import form_errors_to_messages


class ToastLoginView(auth_views.LoginView):
    """Login form errors surface as toasts (consistent with the rest of the app)."""

    template_name = 'auth/login.html'
    redirect_authenticated_user = True

    def form_invalid(self, form):
        form_errors_to_messages(self.request, form)
        return super().form_invalid(form)
