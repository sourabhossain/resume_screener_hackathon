from django.urls import path

from . import views

app_name = 'sei_assessment'

urlpatterns = [
    # HR side, keyed by the resume's opaque uuid and which instrument.
    path('resumes/<uuid:uuid>/assessment/<slug:instrument>/',
         views.report, name='report'),
    path('resumes/<uuid:uuid>/assessment/<slug:instrument>/send/',
         views.send, name='send'),

    # Candidate side: no login, reached by the emailed token plus a code.
    path('assessment/<uuid:token>/', views.entry, name='entry'),
    path('assessment/<uuid:token>/verify/', views.verify, name='verify'),
    path('assessment/<uuid:token>/resend-code/', views.resend_code,
         name='resend_code'),
    path('assessment/<uuid:token>/save/', views.save, name='save'),
    path('assessment/<uuid:token>/done/', views.done, name='done'),
    path('assessment/<uuid:token>/start/', views.test, name='test'),
]
