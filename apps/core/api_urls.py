"""
API URL routes for core app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import JobViewSet, ResumeViewSet

router = DefaultRouter()
router.register(r'jobs', JobViewSet, basename='job')
router.register(r'resumes', ResumeViewSet, basename='resume')

urlpatterns = router.urls
