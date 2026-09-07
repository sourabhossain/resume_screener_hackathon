"""The shapes SSL Wireless actually uses for job descriptions.

Derived from the postings the company has published, not invented. Reading
eight of them side by side, there is no single house format -- there are four,
and which one applies is decided by the *function*, not the seniority:

    Head of Government Project  -> commercial shape
    Head of Data                -> leadership shape
    Head of Internal Audit      -> executive charter shape

so "Head of" tells you nothing on its own. Each archetype below lists the exact
section headings those postings use, in their order, plus a trimmed skeleton of
a real example so the model matches the voice as well as the structure.

Two headings deliberately do not appear anywhere: "What we offer" and "How to
apply". An earlier version of this generator forced both, which is why its
output never looked like an SSL posting.
"""

TECHNICAL = 'technical'
COMMERCIAL = 'commercial'
LEADERSHIP = 'leadership'
EXECUTIVE = 'executive'

ARCHETYPES = {
    TECHNICAL: {
        'label': 'Technical (individual contributor)',
        'short': 'Technical',
        'used_by': 'AI Engineer, Data Engineer, AI Native Developer',
        'words': (300, 500),
        'sections': (
            'Core Responsibilities',
            'Key Skills & Qualifications',
            'Nice-to-Have Skills',
        ),
        'guidance': (
            'Open with one or two paragraphs saying what the role builds and '
            'where it sits in the platform -- concrete, not aspirational. '
            'Under "Key Skills & Qualifications" use labelled lines rather than '
            'plain bullets: start with Education and Experience, then one line '
            'per technical area naming the actual tools. "Nice-to-Have Skills" '
            'is a plain bullet list of adjacent technologies.'
        ),
        'skeleton': """\
The Data Engineer owns the end-to-end data pipeline from raw ingestion to the
warehouse. This role is the backbone of SSL Wireless's data platform — ensuring
data flows reliably, is correctly modelled, and meets the quality standards
required by analysts and AI/ML teams.

Core Responsibilities
- Design, build, and maintain end-to-end data pipelines for ingestion, processing, and storage
- Develop and optimize ETL/ELT workflows for structured and unstructured data sources
- Enforce data governance, consistency, and security best practices across all pipelines

Key Skills & Qualifications
Education: Bachelor's degree in Computer Science, Engineering, or a related field
Experience: 2-3 years of experience in Data Engineering or closely related roles
Data Modelling: Star & Snowflake schema design; dimensional modelling using DBT
Programming Languages: Python (primary), SQL (advanced)
ETL Frameworks & Tools: Apache Spark, Kafka, Flink, Airflow, DBT

Nice-to-Have Skills
- Experience with warehouse engines such as Doris, ClickHouse, or Druid
- Knowledge of CDC patterns using Debezium (MySQL binlog change data capture)
- Experience with containerization tools such as Docker and Kubernetes""",
    },

    COMMERCIAL: {
        'label': 'Commercial (sales, business development, accounts)',
        'short': 'Commercial',
        'used_by': ('Head of Government Project, Key Account Manager, '
                    'Merchant Acquisition Specialist'),
        'words': (330, 600),
        'sections': (
            'Key Responsibilities',
            'Experience Requirements',
            'Educational Qualification',
            'Required Skills & Competencies',
        ),
        'optional_sections': ('Compensation & Benefits',),
        'guidance': (
            'Open with "We are looking for..." or "<Company> is looking for..." '
            'and one paragraph on the commercial outcome the role owns. '
            'Responsibilities are one action per line, starting with a verb. '
            'Where the brief names a grade split (Executive / Senior '
            'Executive), give each its own experience line. Include '
            '"Compensation & Benefits" only if the brief asks for it, and then '
            'only in general terms -- "as per company policy", never a figure.'
        ),
        'skeleton': """\
We are looking for experienced and result-driven Key Account Managers to support
our enterprise sales strategy and revenue targets for Odoo, ERP, and customized
software solutions.

The ideal candidate should have strong B2B enterprise sales experience, good
understanding of software/IT solutions, and an existing corporate customer base.

Key Responsibilities
- Identify, develop, and manage enterprise-level sales opportunities
- Build and maintain strong relationships with corporate clients and decision-makers
- Manage the end-to-end sales cycle from lead generation to deal closure
- Provide regular pipeline reports, sales forecasts, and market insights to management

Experience Requirements
- 3 to 5 years of experience in B2B enterprise sales, ERP, SaaS, or IT solutions
- Must have an existing corporate customer base or active sales pipeline
- Proven track record of selling enterprise-level software solutions

Educational Qualification
- Bachelor's degree in CSE, Software Engineering, IT, or any related technical field is preferred
- BBA/MBA will be considered an added advantage

Required Skills & Competencies
- Strong consultative enterprise selling skills
- Strong client relationship management skills
- Strong communication, negotiation, and presentation skills""",
    },

    LEADERSHIP: {
        'label': 'Functional leadership (Head of / Lead)',
        'short': 'Functional leadership',
        'used_by': 'Head of Data',
        'words': (420, 650),
        'sections': (
            'Job Description / Responsibilities',
            'Educational Requirements',
            'Experience Requirements',
            'Additional Requirements',
        ),
        'guidance': (
            'Open with "<Company> is looking for a <Title> to..." then two or '
            'three short paragraphs: what the function covers, what the role is '
            'accountable for, and who it oversees. Under "Experience '
            'Requirements" state the band on its own line in the house style '
            '("8 to 10 year(s)") and name the business areas the experience '
            'should come from. "Additional Requirements" carries the detailed '
            'depth expectations, one per line.'
        ),
        'skeleton': """\
SSL Wireless is looking for a Head of Data to lead the company's overall data
function, including Data Science, Data Engineering, AI/ML, Analytics, Data
Governance, and Data Platforms.

The role will be responsible for setting the data strategy, leading multiple
technical teams, ensuring reliable data infrastructure, and delivering
business-focused data and AI solutions.

Job Description / Responsibilities
- Develop and lead the overall data strategy and roadmap for SSL Wireless
- Supervise Data Science and Data Engineering teams to ensure smooth delivery
- Establish and enforce data governance, data quality, PII protection, and compliance practices

Educational Requirements
Bachelor's or Master's degree in Computer Science, Engineering, Statistics, or a
related quantitative field.

Experience Requirements
8 to 10 year(s)

The applicants should have experience in the following business area(s):
Telecommunication, Financial Technology, Banking, Software Development, or
Enterprise Technology Services.

Additional Requirements
- Minimum 3 years of experience leading data teams or cross-functional initiatives
- Strong understanding of the complete data lifecycle
- Ability to communicate with technical teams, senior management, and external customers""",
    },

    EXECUTIVE: {
        'label': 'Executive charter (governance, assurance, control)',
        'short': 'Executive charter',
        'used_by': 'Head of Internal Audit',
        'words': (1200, 1900),
        'sections': (
            'Job Purpose',
            'Key Performance Indicators (KPIs)',
            'Required Qualifications',
            'Experience',
            'Competencies',
            'Success Measures',
        ),
        'guidance': (
            'This is a charter, not an advert. Open with "Job Purpose": two or '
            'three paragraphs on why the role exists, who it reports to, and '
            'the standard it operates against. Then a NUMBERED sequence of '
            'functional domains starting at 2 -- one per area of the mandate, '
            'each a short heading followed by four or five accountability '
            'lines. Where independence or authority matters, include a '
            '"Scope of Authority & Independence" domain. Then the fixed tail '
            'sections in order: Key Performance Indicators (KPIs) grouped under '
            'sub-labels, Required Qualifications, Experience, Competencies '
            '(grouped under sub-labels), and Success Measures phrased against '
            'time horizons.'
        ),
        'skeleton': """\
Job Purpose
The Head of Internal Audit leads the Group's independent internal audit
function, providing objective assurance and advisory services designed to add
value and improve the organization's operations. The role exists to give the
Audit Committee and the Board reasonable assurance over the adequacy and
effectiveness of governance, risk management, and internal control.

2. Audit Strategy & Planning
- Define and own the Group internal audit strategy, vision, and multi-year plan
- Prepare a risk-based annual audit plan for Audit Committee approval
- Establish and maintain the Internal Audit Charter, methodology, and QAIP

3. Risk-Based Internal Audit
- Direct risk-based audit engagements across financial, operational, IT, and compliance domains
- Track, follow up, and validate the timely implementation of agreed management actions

12. Scope of Authority & Independence
- Full, free, and unrestricted access to all Group records, systems, and personnel
- No operational authority or responsibility over the activities audited

15. Key Performance Indicators (KPIs)
Plan Delivery & Coverage
- Approved audit plan completion rate (% delivered on schedule)
Impact & Remediation
- % of audit recommendations agreed and implemented on time

16. Required Qualifications
- Professional certification essential / strongly preferred: CA / FCA, CIA, or ACCA
- Master's degree in Accounting, Finance, Business, or a related discipline

17. Experience
- 15+ years of progressive experience in internal / external audit, risk, and controls
- Demonstrated Audit Committee and Board-level interaction and reporting

18. Competencies
Independence & Integrity
- Uncompromising independence, objectivity, and professional skepticism
Leadership & Communication
- Board-level communication, influence, and gravitas

19. Success Measures
- Foundation (0-6 months): Charter, methodology, and risk-based plan in place
- Execution (6-12 months): First full risk-based audit cycle delivered
- Enduring: A trusted, independent assurance function that strengthens governance""",
    },
}

# Function decides the shape, seniority only refines it. Ordered: the first
# matching rule wins, so the governance test sits above the seniority test.
_GOVERNANCE = (
    'internal audit', 'chief audit', 'audit executive', 'compliance', 'risk',
    'legal', 'company secretar', 'governance', 'assurance', 'controller',
)
_SENIOR = (
    'head of', 'chief', 'director', 'vp ', 'vice president', 'cxo', 'cto',
    'cfo', 'ceo', 'coo', 'ciso', 'group ',
)
_COMMERCIAL = (
    'sales', 'business development', 'account manager', 'key account',
    'merchant', 'acquisition', 'partnership', 'marketing', 'commercial',
    'relationship manager', 'client', 'customer success', 'government project',
    'bd ', 'revenue',
)
_TECHNICAL = (
    'engineer', 'developer', 'programmer', 'architect', 'scientist', 'analyst',
    'devops', 'sre', 'qa ', 'tester', 'administrator', 'dba', 'designer',
    'data ', 'ai ', 'ml ', 'software', 'security', 'network', 'support',
)


def detect_archetype(title: str) -> str:
    """Pick the shape from the job title, the way a recruiter would.

    Deliberately ordered rather than scored: a governance mandate is a charter
    whatever else the title says, and a commercial head is written as a
    commercial role, not as a functional lead.
    """
    name = f' {(title or "").strip().lower()} '

    if any(word in name for word in _GOVERNANCE):
        return EXECUTIVE
    if any(word in name for word in _COMMERCIAL):
        return COMMERCIAL
    if any(word in name for word in _SENIOR):
        return LEADERSHIP
    if any(word in name for word in _TECHNICAL):
        return TECHNICAL
    # Nothing matched: the commercial shape is the most general of the four and
    # the least odd-looking when the guess is wrong.
    return COMMERCIAL


def get(archetype: str) -> dict:
    return ARCHETYPES.get(archetype) or ARCHETYPES[COMMERCIAL]


ORDER = (TECHNICAL, COMMERCIAL, LEADERSHIP, EXECUTIVE)


def choices():
    """The shapes, for the "rewrite as" links under a finished draft.

    Not offered before the first draft: which shape suits a role is a judgement
    you can only make once you can see one, and asking up front turned a button
    into a form field nobody could answer.
    """
    return [
        {'value': key,
         'label': ARCHETYPES[key]['label'],
         'short': ARCHETYPES[key]['short']}
        for key in ORDER
    ]
