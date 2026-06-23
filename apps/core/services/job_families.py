"""
Single source of truth for the job-family taxonomy.

The detector's label catalog, the set of valid job types, the per-family weight
lookup, and the role fragments all derive from this one mapping, so the detector
can never emit a label that has no downstream fragment (the [S4] coherence
guarantee).
"""
from collections import OrderedDict

# Ordered for deterministic catalog rendering. Grouped purely for the detector's
# readability; the value is "label -> (group, description)".
JOB_FAMILIES = OrderedDict([
    # Engineering
    ('software_engineering', ('Engineering', 'builds application software (backend, frontend, full-stack, mobile). Core: languages, frameworks, system design.')),
    ('devops_sre', ('Engineering', 'keeps systems deployable and reliable (DevOps, SRE, platform, cloud, infra). Core: CI/CD, IaC, observability. Product/customer-facing infra, not feature work.')),
    ('qa_test', ('Engineering', 'verifies software quality (QA, SDET, automation, manual QA). Core: test strategy, automation frameworks. Not building features.')),
    ('data_ai', ('Engineering', 'works with data and models (data engineering, data analysis, data science, ML/AI, BI). Core: pipelines, SQL, statistics, model training.')),
    ('security', ('Engineering', 'protects systems and data (AppSec, InfoSec, SecOps, GRC). Core: threat modeling, audits, compliance frameworks.')),
    # Product and Design
    ('product_management', ('Product and Design', 'defines what to build and why (PM, Sr PM, product owner). Core: roadmap, requirements, prioritization. Not delivery scheduling.')),
    ('design_creative', ('Product and Design', 'designs experience and visuals (product design, UX, UI, content design). Not front-end coding.')),
    # Delivery
    ('project_management', ('Delivery', 'plans and delivers initiatives on time (project manager, program manager, scrum master, delivery). Core: schedules, coordination, agile ceremonies. Not defining the product.')),
    # Go to market
    ('sales', ('Go to market', 'closes revenue (AE, SDR/BDR, sales engineer, sales manager). Core: quota, pipeline, deals.')),
    ('marketing', ('Go to market', 'drives demand and brand (demand gen, content, brand, product marketing, growth). Core: campaigns, funnel, positioning.')),
    ('customer_success', ('Go to market', 'retains and grows existing accounts (CSM, account manager, renewals). Core: adoption, relationship, retention. Not issue resolution.')),
    ('customer_support', ('Go to market', 'resolves customer issues (support engineer, technical support, helpdesk). Core: tickets, troubleshooting, SLAs.')),
    # General and admin
    ('finance_admin', ('General and admin', 'manages money and accounting (accountant, FP&A, controller, payroll).')),
    ('hr_recruitment', ('General and admin', 'hires and supports people (recruiter, HRBP, people ops, L&D).')),
    ('legal_compliance', ('General and admin', 'handles law and regulatory risk (counsel, compliance, privacy).')),
    ('it_internal', ('General and admin', 'supports internal employees and corporate systems (IT support, sysadmin, corp eng). Internal-facing, unlike devops_sre.')),
    ('operations', ('General and admin', 'runs the business engine (BizOps, RevOps, strategy, operations analyst). Cross-functional process and analysis.')),
])

# There is intentionally NO default family: an uncertain / low-confidence /
# unknown detection is flagged for manual review rather than silently routed.
DEFAULT_FAMILY = None

# Used only by the loader's backward-compatible convenience wrappers and tests
# (not a routing fallback).
FALLBACK_ROLE = 'software_engineering'

# Valid labels the detector may resolve to (derived, never hand-maintained).
VALID_JOB_TYPES = frozenset(JOB_FAMILIES)


def render_catalog() -> str:
    """Render the family catalog grouped, as '- label - description' lines."""
    lines = []
    current_group = None
    for label, (group, desc) in JOB_FAMILIES.items():
        if group != current_group:
            lines.append(f"\n{group.upper()}")
            current_group = group
        lines.append(f"- {label} - {desc}")
    return '\n'.join(lines).strip()
