"""Numbers and chart geometry for the recruiter dashboard."""
import math
from collections import Counter
from datetime import datetime, time, timedelta

from django.db.models import Avg, Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import Job, Resume

RANGES = [
    ('7d', 'Last 7 days', 7),
    ('30d', 'Last 30 days', 30),
    ('90d', 'Last 90 days', 90),
    ('12m', 'Last 12 months', 365),
    ('all', 'All time', None),
]
RANGE_DAYS = {key: days for key, _, days in RANGES}
DEFAULT_RANGE = '90d'

FUNNEL_STAGES = [
    ('applied', 'Applications'),
    ('shortlisted', 'Shortlisted'),
    ('phone_screen', 'Phone screening'),
    ('assessment', 'Assessment / test'),
    ('interviewing', 'Interviewing'),
    ('selected', 'Selected'),
    ('info_received', 'Information received'),
    ('bgv_completed', 'Verification completed'),
    ('offer_extended', 'Offer letter sent'),
    ('pre_onboarding', 'Pre-onboarding'),
    ('hired', 'Onboarded'),
]
STAGE_RANK = {key: rank for rank, (key, _) in enumerate(FUNNEL_STAGES)}
STAGE_RANK['new'] = 0

CHART_W, CHART_H = 640, 200
PAD_L, PAD_R, PAD_T, PAD_B = 36, 12, 24, 28


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _nice_max(value, ticks=4):
    """Smallest round ceiling >= value that splits into `ticks` whole-number steps."""
    if value <= ticks:
        return ticks
    raw = value / ticks
    exponent = 0
    while True:
        for factor in (1, 1.5, 2, 2.5, 3, 4, 5):
            step = factor * 10 ** exponent
            if step == int(step) and step >= raw:
                return int(step) * ticks
        exponent += 1


def _ticks(maximum, count=4):
    return [maximum * i // count for i in range(count + 1)]


# ── Filters and the time window ──────────────────────────────────────────
def parse_filters(params):
    range_key = params.get('range') if params.get('range') in RANGE_DAYS else DEFAULT_RANGE
    job = None
    slug = params.get('job') or ''
    if slug:
        job = job_options().filter(slug=slug).first()
    return range_key, job


def job_options():
    return Job.objects.order_by('title', '-created_at')


def window(range_key, now=None):
    """(unit, buckets, start) shared by every number on the page; start is None for all time."""
    now = now or timezone.now()
    unit, buckets = _buckets(range_key, now)
    if not RANGE_DAYS[range_key]:
        return unit, buckets, None
    return unit, buckets, timezone.make_aware(datetime.combine(buckets[0], time.min))


def scoped_resumes(range_key, job, *, previous=False, now=None):
    now = now or timezone.now()
    qs = Resume.objects.filter(job__is_deleted=False)
    if job:
        qs = qs.filter(job=job)
    _, _, start = window(range_key, now)
    if start is None:
        return qs
    if previous:
        return qs.filter(created_at__gte=start - (now - start), created_at__lt=start)
    return qs.filter(created_at__gte=start, created_at__lte=now)


def hr_answers(resumes):
    """{resume_id: HR verification answers} for the candidates in view, read once."""
    from apps.hr_verification.models import HRVerification

    return dict(HRVerification.objects.filter(resume__in=resumes)
                .values_list('resume_id', 'answers'))


# ── Funnel: furthest stage each candidate reached ────────────────────────
def furthest_stages(resumes, hr=None):
    """{resume_id: stage rank}, from the current status plus what has happened since.

    A rejected candidate keeps the furthest stage their records prove: the
    status history, an information form (sent, then submitted), an assessment
    sent, a held interview, and (HR view only) a signed-off verification and an
    issued offer letter.
    """
    from apps.core.models import StatusChange
    from apps.employee_form.models import EmployeeForm
    from apps.interviews.models import Interview
    from apps.sei_assessment.models import AssessmentInvitation

    evidence = {}

    def reach(pks, stage):
        for pk in pks:
            evidence[pk] = max(evidence.get(pk, 0), STAGE_RANK[stage])

    for pk, to_status in StatusChange.objects.filter(resume__in=resumes).values_list(
            'resume_id', 'to_status'):
        if to_status in STAGE_RANK:
            evidence[pk] = max(evidence.get(pk, 0), STAGE_RANK[to_status])
    forms = EmployeeForm.objects.filter(resume__in=resumes)
    reach(forms.values_list('resume_id', flat=True), 'shortlisted')
    reach(forms.filter(is_submitted=True).values_list('resume_id', flat=True), 'info_received')
    reach(AssessmentInvitation.objects.filter(resume__in=resumes, invited_at__isnull=False)
          .values_list('resume_id', flat=True), 'assessment')
    reach(Interview.objects.filter(resume__in=resumes).exclude(status='cancelled')
          .values_list('resume_id', flat=True), 'interviewing')
    # HR-only evidence only for an HR view: a recruiter's funnel must not reveal
    # which candidates cleared background verification.
    if hr:
        from apps.hr_verification.models import HRVerification
        reach(HRVerification.objects.filter(resume__in=resumes, is_submitted=True)
              .values_list('resume_id', flat=True), 'bgv_completed')
        reach([pk for pk, a in hr.items() if (a or {}).get('offer_letter_issued') == 'yes'],
              'offer_extended')
    ranks = {}
    for pk, status in resumes.values_list('id', 'recruiter_status'):
        ranks[pk] = max(STAGE_RANK.get(status, 0), evidence.get(pk, 0))
    return ranks


def funnel(ranks):
    total = len(ranks)
    stages, previous = [], None
    for rank, (key, label) in enumerate(FUNNEL_STAGES):
        count = sum(1 for r in ranks.values() if r >= rank)
        stages.append({
            'key': key,
            'label': label,
            'count': count,
            'share': _pct(count, total),
            'width': (count * 100 / total) if total else 0,
            'step_rate': _pct(count, previous) if previous is not None else None,
        })
        previous = count
    return {'stages': stages, 'total': total}


# ── Trend ────────────────────────────────────────────────────────────────
def _buckets(range_key, now):
    today = timezone.localtime(now).date()
    if range_key in ('7d', '30d'):
        days = RANGE_DAYS[range_key]
        return 'day', [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    if range_key == '90d':
        start = today - timedelta(days=today.weekday())
        return 'week', [start - timedelta(weeks=i) for i in range(12, -1, -1)]
    first = today.replace(day=1)
    months = []
    for i in range(11, -1, -1):
        y, m = first.year, first.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        months.append(first.replace(year=y, month=m))
    return 'month', months


def _bucket_of(unit, day):
    if unit == 'day':
        return day
    if unit == 'week':
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _bucket_label(unit, day):
    if unit == 'month':
        return day.strftime('%b %Y')
    if unit == 'week':
        return f"Week of {day.strftime('%d %b')}"
    return day.strftime('%d %b')


def trend(range_key, job, now=None):
    now = now or timezone.now()
    unit, buckets, _ = window(range_key, now)
    # Datetime bound: created_at__date needs MySQL tz tables and silently matches nothing without them.
    start = timezone.make_aware(datetime.combine(buckets[0], time.min))
    qs = Resume.objects.filter(job__is_deleted=False, created_at__gte=start, created_at__lte=now)
    if job:
        qs = qs.filter(job=job)
    counts = Counter(_bucket_of(unit, timezone.localtime(ts).date())
                     for ts in qs.values_list('created_at', flat=True))
    values = [counts.get(b, 0) for b in buckets]
    peak = _nice_max(max(values) if values else 0)
    plot_w, plot_h = CHART_W - PAD_L - PAD_R, CHART_H - PAD_T - PAD_B
    step = plot_w / max(len(values) - 1, 1)
    points = []
    for i, (bucket, value) in enumerate(zip(buckets, values)):
        x = PAD_L + i * step
        y = PAD_T + plot_h - (value / peak) * plot_h
        points.append({
            'x': round(x, 1), 'y': round(y, 1), 'value': value,
            'label': _bucket_label(unit, bucket),
            'hit_x': round(x - step / 2, 1), 'hit_w': round(step, 1),
            'tick': i in (0, len(values) - 1) or (len(values) > 6 and i == len(values) // 2),
        })
    line = ' '.join(f"{'M' if i == 0 else 'L'}{p['x']},{p['y']}" for i, p in enumerate(points))
    base_y = PAD_T + plot_h
    area = f"{line} L{points[-1]['x']},{base_y} L{points[0]['x']},{base_y} Z" if points else ''
    grid = [{'y': round(PAD_T + plot_h - (t / peak) * plot_h, 1), 'label': t}
            for t in _ticks(peak)]
    last = points[-1] if points else None
    return {
        'unit': unit, 'points': points, 'line': line, 'area': area, 'grid': grid,
        'last': last, 'total': sum(values), 'width': CHART_W, 'height': CHART_H,
        'pad_l': PAD_L, 'pad_r': CHART_W - PAD_R, 'base_y': base_y, 'top_y': PAD_T,
        'spark': _sparkline(values),
    }


def _sparkline(values, width=120, height=32):
    if not values:
        return ''
    peak = max(values) or 1
    step = width / max(len(values) - 1, 1)
    return ' '.join(
        f"{'M' if i == 0 else 'L'}{round(i * step, 1)},{round(height - 2 - (v / peak) * (height - 4), 1)}"
        for i, v in enumerate(values))


# ── Screening quality ────────────────────────────────────────────────────
def score_distribution(resumes):
    scores = list(resumes.filter(screening_status='completed', final_score__isnull=False)
                  .values_list('final_score', flat=True))
    bins = [0] * 10
    for score in scores:
        bins[min(int(score // 10), 9)] += 1
    peak = _nice_max(max(bins) if bins else 0)
    tallest = max(bins) if bins else 0
    bars = [{
        'is_peak': count == tallest and count > 0 and bins.index(tallest) == i,
        'label': f'{i * 10}–{i * 10 + 9 if i < 9 else 100}',
        'count': count,
        'height': (count / peak * 100) if peak else 0,
        'band': 'top' if i >= 8 else 'mid' if i >= 6 else 'low',
    } for i, count in enumerate(bins)]
    return {'bars': bars, 'total': len(scores), 'peak': peak}


def tier_mix(resumes):
    stats = resumes.aggregate(
        top=Count('id', filter=Q(tier='top')),
        mid=Count('id', filter=Q(tier='mid')),
        low=Count('id', filter=Q(tier='low')),
    )
    total = sum(stats.values())
    return {
        'total': total,
        'segments': [
            {'key': key, 'label': label, 'range': rng, 'count': stats[key],
             'share': _pct(stats[key], total), 'width': (stats[key] * 100 / total) if total else 0}
            for key, label, rng in (('top', 'Top', '≥ 80%'), ('mid', 'Mid', '60–79%'),
                                    ('low', 'Low', '< 60%'))
        ],
    }


# ── Post-shortlist pipeline ──────────────────────────────────────────────
def pipeline_progress(resumes, *, hr_view):
    from apps.employee_form.models import EmployeeForm
    from apps.hr_verification.models import HRVerification
    from apps.reference_checks.models import ReferenceCheck
    from apps.sei_assessment import instruments
    from apps.sei_assessment.models import AssessmentInvitation

    form_stats = EmployeeForm.objects.filter(resume__in=resumes).aggregate(
        sent=Count('id', filter=Q(invited_at__isnull=False)),
        done=Count('id', filter=Q(is_submitted=True)),
        failed=Count('id', filter=~Q(last_error='') & Q(is_submitted=False)),
    )
    rows = [_meter('Information form', form_stats['done'], form_stats['sent'], 'submitted',
                   note=f"{form_stats['failed']} invite failed" if form_stats['failed'] else '')]
    if not hr_view:
        return rows

    done = retake = sent = 0
    invitations = (AssessmentInvitation.objects.filter(resume__in=resumes, invited_at__isnull=False)
                   .prefetch_related('sittings'))
    for invitation in invitations:
        sittings = [s for s in invitation.sittings.all() if s.instrument in instruments.REGISTRY]
        if not sittings:
            continue
        sent += 1
        done += all(s.is_valid_result for s in sittings)
        retake += any(s.needs_retaking for s in sittings)
    refs = list(ReferenceCheck.objects.filter(resume__in=resumes, invited_at__isnull=False)
                .only('kind', 'answers', 'is_submitted'))
    bgv = HRVerification.objects.filter(resume__in=resumes).aggregate(
        started=Count('id'), done=Count('id', filter=Q(is_submitted=True)))
    rows += [
        _meter('Assessments', done, sent, 'completed',
               note=_plural(retake, 'candidate needs a retake', 'candidates need a retake')),
        _meter('Reference checks', sum(1 for r in refs if r.is_submitted), len(refs), 'replied',
               note=_plural(sum(1 for r in refs if r.is_submitted and r.flagged),
                            'reply flagged', 'replies flagged')),
        _meter('Background verification', bgv['done'], bgv['started'], 'signed off'),
    ]
    return rows


def _plural(count, one, many):
    if not count:
        return ''
    return f'{count} {one if count == 1 else many}'


def _meter(label, done, total, verb, note=''):
    return {'label': label, 'done': done, 'total': total, 'verb': verb, 'note': note,
            'share': _pct(done, total), 'width': (done * 100 / total) if total else 0}


def interview_summary(resumes):
    from apps.interviews.models import Interview, InterviewEvaluation

    today = timezone.localdate()
    interviews = Interview.objects.filter(resume__in=resumes)
    stats = interviews.aggregate(
        upcoming=Count('id', filter=Q(status='scheduled', scheduled_date__gte=today)),
        overdue=Count('id', filter=Q(status='scheduled', scheduled_date__lt=today)),
        completed=Count('id', filter=Q(status='completed')),
    )
    evals = InterviewEvaluation.objects.filter(interview__in=interviews.exclude(status='cancelled'))
    verdicts = evals.filter(is_submitted=True).aggregate(
        yes=Count('id', filter=Q(recommendation='yes')),
        maybe=Count('id', filter=Q(recommendation='maybe')),
        no=Count('id', filter=Q(recommendation='no')),
    )
    submitted = sum(verdicts.values())
    return {
        **stats,
        'evaluations_pending': evals.filter(is_submitted=False).filter(
            Q(token_expires_at__isnull=True) | Q(token_expires_at__gte=timezone.now())).count(),
        'evaluations_submitted': submitted,
        'verdicts': [
            {'key': key, 'label': label, 'count': verdicts[key],
             'share': _pct(verdicts[key], submitted),
             'width': (verdicts[key] * 100 / submitted) if submitted else 0}
            for key, label in (('yes', 'Hire'), ('maybe', 'Further review'), ('no', 'Reject'))
        ],
    }


def bgv_outcomes(hr):
    from apps.hr_verification.schema import JOINING_CLEARANCE, RISK_RATING

    answers = [a or {} for a in hr.values()]
    risk = Counter(a.get('risk_rating') for a in answers if a.get('risk_rating'))
    clearance = Counter(a.get('final_joining_clearance') for a in answers
                        if a.get('final_joining_clearance'))
    rated = sum(risk.values())
    short = {'green': 'Green', 'amber': 'Amber', 'red': 'Red', 'critical': 'Critical'}
    return {
        'rated': rated,
        'risk': [{'key': key, 'label': short[key], 'detail': label.split('–', 1)[-1].strip(),
                  'count': risk.get(key, 0), 'share': _pct(risk.get(key, 0), rated),
                  'width': (risk.get(key, 0) * 100 / rated) if rated else 0}
                 for key, label in RISK_RATING],
        'clearance': [{'label': label, 'count': clearance.get(key, 0)}
                      for key, label in JOINING_CLEARANCE],
    }


# ── Jobs and recruiters ──────────────────────────────────────────────────
def job_leaderboard(resumes, ranks, limit=8):
    per_job = Counter()
    hired = Counter()
    job_of = dict(resumes.values_list('id', 'job_id'))
    for pk, job_id in job_of.items():
        per_job[job_id] += 1
        if ranks.get(pk, 0) >= STAGE_RANK['hired']:
            hired[job_id] += 1
    jobs = {j.pk: j for j in Job.objects.filter(pk__in=per_job)}
    top = per_job.most_common(limit)
    peak = top[0][1] if top else 0
    return [{
        'job': jobs[job_id], 'count': count, 'hired': hired[job_id],
        'width': (count * 100 / peak) if peak else 0,
    } for job_id, count in top if job_id in jobs]


def recruiter_table(resumes, ranks):
    rows = {}
    for pk, owner_id, first, last, username, job_id in resumes.values_list(
            'id', 'job__owner_id', 'job__owner__first_name', 'job__owner__last_name',
            'job__owner__username', 'job_id'):
        name = f"{first or ''} {last or ''}".strip() or username or 'Unassigned'
        row = rows.setdefault(owner_id, {'name': name, 'jobs': set(), 'candidates': 0,
                                         'shortlisted': 0, 'hired': 0})
        row['jobs'].add(job_id)
        row['candidates'] += 1
        rank = ranks.get(pk, 0)
        row['shortlisted'] += rank >= STAGE_RANK['shortlisted']
        row['hired'] += rank >= STAGE_RANK['hired']
    out = []
    for row in rows.values():
        out.append({**row, 'jobs': len(row['jobs']),
                    'shortlist_rate': _pct(row['shortlisted'], row['candidates']),
                    'hire_rate': _pct(row['hired'], row['shortlisted'])})
    return sorted(out, key=lambda r: (-r['candidates'], r['name']))


# ── Needs attention ──────────────────────────────────────────────────────
def attention_items(*, hr_view):
    from apps.employee_form.models import EmployeeForm
    from apps.hr_verification.models import HRVerification
    from apps.interviews.models import InterviewEvaluation
    from apps.reference_checks.models import ReferenceCheck
    from apps.sei_assessment.models import AssessmentInvitation

    now = timezone.now()
    live = Resume.objects.filter(job__is_deleted=False)
    stats = live.aggregate(
        failed=Count('id', filter=Q(screening_status='failed')),
        review=Count('id', filter=Q(screening_status='needs_review')),
        unseen=Count('id', filter=Q(seen_status='unseen')),
        pool=Count('id', filter=Q(recommendation='talent_pool')),
    )
    on_live = {'resume__in': live}
    invite_failures = EmployeeForm.objects.filter(is_submitted=False, **on_live).exclude(
        last_error='').count()
    if hr_view:
        invite_failures += (
            AssessmentInvitation.objects.filter(**on_live).exclude(last_error='').count()
            + ReferenceCheck.objects.filter(is_submitted=False, **on_live).exclude(
                last_error='').count())
    stalled_forms = EmployeeForm.objects.filter(
        is_submitted=False, invited_at__lt=now - timedelta(days=3), token_expires_at__gt=now,
        **on_live).count()
    expiring = InterviewEvaluation.objects.filter(
        is_submitted=False, token_expires_at__gte=now, token_expires_at__lte=now + timedelta(days=3),
        interview__resume__in=live).exclude(interview__status='cancelled').count()

    rejection_pending = live.filter(recruiter_status='rejected',
                                    rejection_email_sent_at__isnull=True).count()
    checklists_open = sum(1 for r in live.filter(recruiter_status='pre_onboarding').only(
        'onboarding_checklist') if not r.onboarding_complete)

    items = [
        ('critical', stats['failed'], 'Screening failed', reverse('core:screening_failed')),
        ('warning', stats['review'], 'Needs review', reverse('core:needs_review')),
        ('critical', invite_failures, 'Invites failed to send', None),
        ('warning', expiring, 'Evaluation links expiring in 3 days', None),
        ('warning', stalled_forms, 'Information forms waiting over 3 days', None),
        ('warning', rejection_pending, 'Rejection emails not sent', None),
        ('info', checklists_open, 'Pre-onboarding checklists open', None),
        ('info', stats['unseen'], 'Unseen candidates', reverse('core:job_list')),
        ('info', stats['pool'], 'Talent pool candidates', reverse('core:talent_pool')),
    ]
    if hr_view:
        flagged = sum(1 for r in ReferenceCheck.objects.filter(is_submitted=True, **on_live).only(
            'kind', 'answers') if r.flagged)
        items.insert(3, ('warning', flagged, 'Reference replies flagged', None))
        awaiting = HRVerification.objects.filter(is_submitted=False, **on_live).count()
        items.append(('info', awaiting, 'Background checks awaiting sign-off', None))
        not_started = live.filter(recruiter_status='info_received', hr_verification__isnull=True).count()
        items.append(('warning', not_started, 'Information received, verification not started', None))
    return [{'tone': tone, 'count': count, 'label': label, 'url': url}
            for tone, count, label, url in items if count]


# ── Everything ───────────────────────────────────────────────────────────
def build(user, params):
    range_key, job = parse_filters(params)
    hr_view = bool(user.is_staff or user.is_superuser)
    now = timezone.now()
    resumes = scoped_resumes(range_key, job, now=now)
    hr = hr_answers(resumes) if hr_view else {}
    ranks = furthest_stages(resumes, hr)
    total = len(ranks)
    shortlisted = sum(1 for r in ranks.values() if r >= STAGE_RANK['shortlisted'])
    hired = sum(1 for r in ranks.values() if r >= STAGE_RANK['hired'])
    status_counts = resumes.aggregate(
        rejected=Count('id', filter=Q(recruiter_status='rejected')),
        withdrawn=Count('id', filter=Q(recruiter_status='withdrawn')),
        pending=Count('id', filter=Q(screening_status='pending')),
        processing=Count('id', filter=Q(screening_status='processing')),
        avg=Avg('final_score', filter=Q(screening_status='completed', final_score__isnull=False)),
    )
    previous = None
    if RANGE_DAYS[range_key]:
        previous = scoped_resumes(range_key, job, previous=True, now=now).count()

    series = trend(range_key, job, now=now)
    range_label = dict((k, label) for k, label, _ in RANGES)[range_key]
    rejected, withdrawn = status_counts['rejected'], status_counts['withdrawn']

    kpis = [
        {'key': 'candidates', 'label': 'Candidates', 'value': total, 'format': 'int',
         'delta': (total - previous) if previous is not None else None,
         'delta_base': range_label.lower().replace('last', 'previous'),
         'spark': series['spark']},
        {'key': 'shortlisted', 'label': 'Shortlisted', 'value': shortlisted, 'format': 'int',
         'caption': f'{_fmt_pct(_pct(shortlisted, total))} of candidates'},
        {'key': 'hire_conversion', 'label': 'Onboard conversion', 'value': _pct(hired, shortlisted),
         'format': 'pct', 'caption': f'{hired} onboarded of {shortlisted} shortlisted'},
    ]
    if hr_view:
        offers = _offer_stats(hr)
        decided = offers['accepted'] + offers['declined']
        kpis.append({'key': 'offer_acceptance', 'label': 'Offer acceptance',
                     'value': _pct(offers['accepted'], decided), 'format': 'pct',
                     'caption': f"{offers['accepted']} accepted · {offers['declined']} declined · "
                                f"{offers['pending']} pending"})
    else:
        kpis.append({'key': 'withdrawn', 'label': 'Withdrawn', 'value': _pct(withdrawn, total),
                     'format': 'pct', 'caption': f'{withdrawn} of {total} candidates'})
    kpis += [
        {'key': 'rejection', 'label': 'Rejection rate', 'value': _pct(rejected, total),
         'format': 'pct', 'caption': f'{rejected} of {total} candidates'},
        {'key': 'avg_score', 'label': 'Avg. AI score',
         'value': round(status_counts['avg'], 1) if status_counts['avg'] is not None else None,
         'format': 'pct', 'caption': 'Screened resumes'},
    ]
    job_stats = Job.objects.aggregate(total=Count('id'), active=Count('id', filter=Q(status='active')))
    return {
        'range_key': range_key,
        'range_label': range_label,
        'ranges': [(k, label) for k, label, _ in RANGES],
        'job': job,
        'job_options': job_options(),
        'hr_view': hr_view,
        'total_jobs': job_stats['total'],
        'active_jobs': job_stats['active'],
        'kpis': kpis,
        'funnel': funnel(ranks),
        'trend': series,
        'scores': score_distribution(resumes),
        'tiers': tier_mix(resumes),
        'pipeline': pipeline_progress(resumes, hr_view=hr_view),
        'interviews': interview_summary(resumes),
        'bgv': bgv_outcomes(hr) if hr_view else None,
        'jobs_board': job_leaderboard(resumes, ranks),
        'recruiters': recruiter_table(resumes, ranks),
        'attention': attention_items(hr_view=hr_view),
        'pending_screening': status_counts['pending'],
        'processing_screening': status_counts['processing'],
    }


def _offer_stats(hr):
    counts = Counter()
    for answers in hr.values():
        answers = answers or {}
        if answers.get('offer_letter_issued') == 'yes':
            counts[{'yes': 'accepted', 'no': 'declined'}.get(answers.get('offer_accepted'), 'pending')] += 1
    return {'accepted': counts['accepted'], 'declined': counts['declined'],
            'pending': counts['pending']}


def _fmt_pct(value):
    return '—' if value is None else f'{value:g}%'
