from django.urls import path

from . import views

app_name = 'reference_checks'

urlpatterns = [
    # HR side, keyed by the resume's opaque uuid.
    path('resumes/<uuid:uuid>/reference-checks/', views.manage, name='manage'),
    path('resumes/<uuid:uuid>/reference-checks/<slug:source_key>/send/',
         views.send, name='send'),
    path('resumes/<uuid:uuid>/reference-checks/response/<int:pk>/',
         views.response, name='response'),

    # Respondent side: no login, reached by the emailed token plus a code.
    path('verification/<uuid:token>/', views.entry, name='entry'),
    path('verification/<uuid:token>/verify/', views.verify, name='verify'),
    path('verification/<uuid:token>/resend-code/', views.resend_code,
         name='resend_code'),
    path('verification/<uuid:token>/done/', views.done, name='done'),
    path('verification/<uuid:token>/<slug:step_key>/', views.step, name='step'),
]
