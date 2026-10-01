from django.urls import path
from . import views

app_name = 'interviews'

urlpatterns = [
    path('resumes/<uuid:resume_uuid>/interviews/create/', views.interview_create, name='create'),
    path('interviews/<int:pk>/', views.interview_detail, name='detail'),
    path('interviews/<int:pk>/delete/', views.interview_delete, name='delete'),
    path('interviews/<int:pk>/status/', views.interview_status, name='status'),
    path('interviews/evaluations/<uuid:token>/delete/', views.evaluation_delete, name='evaluation_delete'),
    path('interviews/evaluations/<uuid:token>/renew/', views.evaluation_renew, name='evaluation_renew'),
    path('interviews/evaluations/<uuid:token>/resend/', views.evaluation_resend, name='evaluation_resend'),
    path('interviews/<int:pk>/candidate-email/', views.candidate_resend, name='candidate_resend'),

    path('jobs/<slug:job_slug>/rank-report/', views.rank_report, name='rank_report'),

    # Public — no login
    path('evaluate/<uuid:token>/', views.evaluate, name='evaluate'),
    path('evaluate/<uuid:token>/done/', views.evaluate_done, name='evaluate_done'),
]
