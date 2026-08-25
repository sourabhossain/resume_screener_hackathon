from django.urls import path

from . import views

app_name = 'hr_verification'

urlpatterns = [
    # HR only. Keyed by the resume's opaque uuid, like every other recruiter page.
    path('resumes/<uuid:uuid>/hr-verification/', views.detail, name='detail'),
    path('resumes/<uuid:uuid>/hr-verification/start/', views.start, name='start'),
    path('resumes/<uuid:uuid>/hr-verification/submit/', views.submit, name='submit'),
    path('resumes/<uuid:uuid>/hr-verification/<slug:step_key>/',
         views.step, name='step'),
]
