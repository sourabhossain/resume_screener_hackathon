from django.urls import path
from . import views

app_name = 'interviews'

urlpatterns = [
    path('resumes/<uuid:resume_uuid>/interviews/create/', views.interview_create, name='create'),
    path('interviews/<int:pk>/', views.interview_detail, name='detail'),
    path('interviews/<int:pk>/delete/', views.interview_delete, name='delete'),
    path('interviews/evaluations/<uuid:token>/delete/', views.evaluation_delete, name='evaluation_delete'),
    path('interviews/evaluations/<uuid:token>/renew/', views.evaluation_renew, name='evaluation_renew'),

    path('jobs/<slug:job_slug>/rank-report/', views.rank_report, name='rank_report'),

    # Public — no login
    path('evaluate/<uuid:token>/', views.evaluate, name='evaluate'),
    path('evaluate/<uuid:token>/done/', views.evaluate_done, name='evaluate_done'),
]
