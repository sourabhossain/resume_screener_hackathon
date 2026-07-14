"""
Single source of truth for the job-family taxonomy.

The detector's label catalog, the set of valid job types, the per-family weight
lookup, and the role fragments all derive from this one mapping, so the detector
can never emit a label that has no downstream fragment (the [S4] coherence
guarantee).
"""
from collections import OrderedDict

JOB_FAMILIES = OrderedDict([
    ('software_engineering', ('Engineering', 'builds application software (backend, frontend, full-stack, mobile). Core: languages, frameworks, system design.')),
    ('devops_sre', ('Engineering', 'keeps systems deployable and reliable (DevOps, SRE, platform, cloud, infra). Core: CI/CD, IaC, observability. Product/customer-facing infra, not feature work.')),
    ('qa_test', ('Engineering', 'verifies software quality (QA, SDET, automation, manual QA). Core: test strategy, automation frameworks. Not building features.')),
    ('data_ai', ('Engineering', 'works with data and models (data engineering, data analysis, data science, ML/AI, BI). Core: pipelines, SQL, statistics, model training.')),
    ('security', ('Engineering', 'protects systems and data (AppSec, InfoSec, SecOps, GRC). Core: threat modeling, audits, compliance frameworks.')),
    ('product_management', ('Product and Design', 'defines what to build and why (PM, Sr PM, product owner). Core: roadmap, requirements, prioritization. Not delivery scheduling.')),
    ('design_creative', ('Product and Design', 'designs experience and visuals (product design, UX, UI, content design). Not front-end coding.')),
    ('project_management', ('Delivery', 'plans and delivers initiatives on time (project manager, program manager, scrum master, delivery). Core: schedules, coordination, agile ceremonies. Not defining the product.')),
    ('sales', ('Go to market', 'closes revenue (AE, SDR/BDR, sales engineer, sales manager). Core: quota, pipeline, deals.')),
    ('marketing', ('Go to market', 'drives demand and brand (demand gen, content, brand, product marketing, growth). Core: campaigns, funnel, positioning.')),
    ('customer_success', ('Go to market', 'retains and grows existing accounts (CSM, account manager, renewals). Core: adoption, relationship, retention. Not issue resolution.')),
    ('customer_support', ('Go to market', 'resolves customer issues (support engineer, technical support, helpdesk). Core: tickets, troubleshooting, SLAs.')),
    ('finance_admin', ('General and admin', 'manages money and accounting (accountant, FP&A, controller, payroll).')),
    ('hr_recruitment', ('General and admin', 'hires and supports people (recruiter, HRBP, people ops, L&D).')),
    ('legal_compliance', ('General and admin', 'handles law and regulatory risk (counsel, compliance, privacy).')),
    ('it_internal', ('General and admin', 'supports internal employees and corporate systems (IT support, sysadmin, corp eng). Internal-facing, unlike devops_sre.')),
    ('operations', ('General and admin', 'runs the business engine (BizOps, RevOps, strategy, operations analyst). Cross-functional process and analysis.')),
])

DEFAULT_FAMILY = None

FALLBACK_ROLE = 'software_engineering'

VALID_JOB_TYPES = frozenset(JOB_FAMILIES)

# Explicit recruiter-facing display labels, keyed by machine value. Kept as a
# parallel map (not folded into JOB_FAMILIES) so the LLM-facing render_catalog()
# and its (group, desc) tuple shape stay byte-identical: display labels are for
# humans only and must never leak into the detector's expected vocabulary.
# Every key in JOB_FAMILIES must appear here (enforced by tests).
FAMILY_LABELS = {
    'software_engineering': 'Software Engineering',
    'devops_sre': 'DevOps / SRE',
    'qa_test': 'QA & Testing',
    'data_ai': 'Data & AI',
    'security': 'Security',
    'product_management': 'Product Management',
    'design_creative': 'Design & Creative',
    'project_management': 'Project & Program Management',
    'sales': 'Sales',
    'marketing': 'Marketing',
    'customer_success': 'Customer Success',
    'customer_support': 'Customer Support',
    'finance_admin': 'Finance & Accounting',
    'hr_recruitment': 'HR & Recruitment',
    'legal_compliance': 'Legal & Compliance',
    'it_internal': 'IT & Internal Support',
    'operations': 'Operations',
}

def family_choices():
    """(value, human_label) pairs for the job-family taxonomy, in catalog order.

    Values are the machine keys (validated against VALID_JOB_TYPES); labels are
    the explicit recruiter-facing names from FAMILY_LABELS.
    """
    return [(value, FAMILY_LABELS[value]) for value in JOB_FAMILIES]

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
