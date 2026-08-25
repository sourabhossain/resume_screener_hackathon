from django.urls import path

from . import views

app_name = 'candidate_mapping'

urlpatterns = [
    # HR only. Keyed by the resume's opaque uuid, like every other recruiter page.
    path('resumes/<uuid:uuid>/candidate-mapping/', views.detail, name='detail'),
    path('resumes/<uuid:uuid>/candidate-mapping/start/', views.start, name='start'),
    path('resumes/<uuid:uuid>/candidate-mapping/submit/', views.submit, name='submit'),
    path('resumes/<uuid:uuid>/candidate-mapping/<slug:step_key>/',
         views.step, name='step'),
]
