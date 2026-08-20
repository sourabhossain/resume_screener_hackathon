from django.urls import path

from . import views

app_name = 'employee_form'

urlpatterns = [
    # Public — candidate reaches these from the emailed link, no login.
    # Access is the opaque token plus the emailed one-time code.
    path('information-form/<uuid:token>/', views.entry, name='entry'),
    path('information-form/<uuid:token>/verify/', views.verify, name='verify'),
    path('information-form/<uuid:token>/resend-code/', views.resend_code, name='resend_code'),
    path('information-form/<uuid:token>/step/<slug:step_key>/', views.step, name='step'),
    path('information-form/<uuid:token>/done/', views.done, name='done'),

    # Recruiter portal
    path('resumes/<uuid:uuid>/information-form/', views.detail, name='detail'),
    path('resumes/<uuid:uuid>/information-form/send/', views.send, name='send'),
]
