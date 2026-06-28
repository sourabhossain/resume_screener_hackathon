"""
Django REST Framework ViewSets for Job and Resume.
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Prefetch, Q
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import extend_schema, extend_schema_view

from .models import Job, Resume
from .serializers import JobListSerializer, JobDetailSerializer, ResumeSerializer


@extend_schema_view(
    list=extend_schema(tags=['Jobs'], summary='List jobs', operation_id='job_list'),
    create=extend_schema(tags=['Jobs'], summary='Create job', operation_id='job_create'),
    retrieve=extend_schema(tags=['Jobs'], summary='Get job', operation_id='job_read'),
    update=extend_schema(tags=['Jobs'], summary='Update job', operation_id='job_update'),
    partial_update=extend_schema(tags=['Jobs'], summary='Patch job', operation_id='job_partial_update'),
    destroy=extend_schema(tags=['Jobs'], summary='Delete job', operation_id='job_delete'),
)
@method_decorator(ratelimit(key='user_or_ip', rate='30/m', method='GET', block=True), name='list')
@method_decorator(ratelimit(key='user_or_ip', rate='30/m', method='GET', block=True), name='retrieve')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='POST', block=True), name='create')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='PUT', block=True), name='update')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='PATCH', block=True), name='partial_update')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='DELETE', block=True), name='destroy')
class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all()
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return JobListSerializer
        return JobDetailSerializer
    
    def perform_create(self, serializer):
        # Record the creator (informational); single-company tool shares all data.
        serializer.save(owner=self.request.user)

    def get_queryset(self):
        queryset = Job.objects.annotate(
            resume_count=Count('resumes', filter=Q(resumes__is_deleted=False))
        ).prefetch_related(
            Prefetch(
                'resumes',
                queryset=Resume.objects.filter(is_deleted=False),
                to_attr='_active_resumes',
            )
        )
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(title__icontains=search)
        status_filter = self.request.query_params.get('status', None)
        if status_filter in ['active', 'draft', 'closed']:
            queryset = queryset.filter(status=status_filter)
        return queryset.order_by('-created_at')

    def perform_destroy(self, instance):
        instance.soft_delete()

    @extend_schema(tags=['Jobs'], summary='Restore job', operation_id='job_restore')
    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        try:
            job = Job.objects.all_with_deleted().get(pk=pk)
        except Job.DoesNotExist:
            raise NotFound(f"Job {pk} not found.")
        if job.owner_id and job.owner_id != request.user.pk and not request.user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to restore this job.")
        job.restore()
        return Response({'status': 'restored'})


@extend_schema_view(
    list=extend_schema(tags=['Resumes'], summary='List resumes', operation_id='resume_list'),
    create=extend_schema(tags=['Resumes'], summary='Upload resume', operation_id='resume_create'),
    retrieve=extend_schema(tags=['Resumes'], summary='Get resume', operation_id='resume_read'),
    update=extend_schema(tags=['Resumes'], summary='Update resume', operation_id='resume_update'),
    partial_update=extend_schema(tags=['Resumes'], summary='Patch resume', operation_id='resume_partial_update'),
    destroy=extend_schema(tags=['Resumes'], summary='Delete resume', operation_id='resume_delete'),
)
@method_decorator(ratelimit(key='user_or_ip', rate='30/m', method='GET', block=True), name='list')
@method_decorator(ratelimit(key='user_or_ip', rate='30/m', method='GET', block=True), name='retrieve')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='POST', block=True), name='create')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='PUT', block=True), name='update')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='PATCH', block=True), name='partial_update')
@method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='DELETE', block=True), name='destroy')
class ResumeViewSet(viewsets.ModelViewSet):
    queryset = Resume.objects.all()
    serializer_class = ResumeSerializer
    permission_classes = [IsAuthenticated]
    # Address detail routes by the opaque uuid, not the sequential pk, so candidate
    # PII can't be harvested by walking /api/resumes/1, /2, /3 ...
    lookup_field = 'uuid'

    def perform_create(self, serializer):
        from apps.core.tasks import screen_resume_task
        resume = serializer.save(screening_status='processing')
        screen_resume_task.delay(resume.id)

    def get_queryset(self):
        # Exclude resumes whose parent job was soft-deleted, matching the web
        # views (a "deleted" job's candidates must not surface anywhere).
        queryset = Resume.objects.select_related('job').filter(job__is_deleted=False)
        job_id = self.request.query_params.get('job', None)
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        tier = self.request.query_params.get('tier', None)
        if tier in ['top', 'mid', 'low']:
            queryset = queryset.filter(tier=tier)
        return queryset.order_by('-final_score', '-created_at')
    
    def perform_destroy(self, instance):
        instance.soft_delete()
