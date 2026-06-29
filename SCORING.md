# How Candidate Scoring Works

This document is the single human-readable explanation of how a resume becomes a
number. Every value below is computed **in code** (auditable, deterministic),
not by the LLM. The LLM only **extracts** facts and **rates components**; all
arithmetic, weighting, and tiering happen in Python.

Source of truth in code:
- Per-family weights: `FAMILY_WEIGHTS` in [config/settings/base.py](config/settings/base.py)
- Pipeline math: `score_node` / `rank_node` in [apps/core/services/ai_screener.py](apps/core/services/ai_screener.py)
- Experience math: [apps/core/services/experience.py](apps/core/services/experience.py)
- Thresholds: `AI_SCREENING_CONFIG` in [config/settings/base.py](config/settings/base.py)
- LLM output contracts (validated): [apps/core/services/schemas.py](apps/core/services/schemas.py)

---

## 1. The pipeline (what produces each number)

```
job description ─► detect ─► (job_type) ─► extract ─► match ─► score ─► rank
                    LLM                      LLM        LLM      CODE     CODE
```

| Stage | Who | Produces | Validated by |
|-------|-----|----------|--------------|
| detect | LLM | `job_type`, `confidence` | `DetectorResult` |
| extract | LLM | skills, work_history (raw dates), education, certs, achievements | `ExtractionResult` |
| match | LLM | `experience_match_score`, `education_match_score`, `certification_match_score`, `achievement_score`, `matched_skills`, `missing_skills` (each 0–100) | `MatchingResult` |
| score | **code** | `skill_score`, component scores, `final_score` | — |
| rank | **code** | `tier`, `recommendation` | — |

The LLM never sees the weights and never multiplies anything. If the model
returns a renamed or missing key, schema validation logs it as drift and applies
an explicit default instead of silently corrupting the score.

---

## 2. The five component scores (all 0–100)

| Component | How it is computed | Source |
|-----------|--------------------|--------|
| `skill_score` | `matched / (matched + missing) * 100`, computed in code from the LLM's two skill lists. `0` if no skills found. | `score_node` |
| `experience_score` | **code**: `min(experience_years / job.required_experience, 1) * 100` — derived from the deterministic years. Falls back to the LLM's `experience_match_score` only when the job sets no `required_experience`. | `score_node` |
| `education_score` | = the LLM's `education_match_score` (clamped 0–100). | `match_node` |
| `certification_score` | = the LLM's `certification_match_score` if given; otherwise fallback `min(cert_count * 25, 100)`. | `score_node` |
| `achievement_score` | = the LLM's `achievement_score` (clamped 0–100). | `match_node` |

`experience_years` is computed deterministically from the raw work-history date
spans (month-precise, overlaps merged once) in `compute_experience_years`
("present"/"current" → today), and now **drives `experience_score` directly**
when the job specifies `required_experience`.

**Fairness:** before extraction, labeled protected attributes (gender, age,
date of birth, nationality, marital status, religion, race, photo) are redacted
(`redact_protected_attributes`). The matching/scoring step receives only the
extracted profile (skills, experience, education, certs, achievements) — **not**
the candidate's name or raw demographics — so they cannot bias the score.

---

## 3. The final score (per-role weights)

```
final_score = skill_score        × w.skill
            + experience_score    × w.experience
            + education_score     × w.education
            + certification_score × w.certification
            + achievement_score   × w.achievement      # then clamped to 0–100
```

Each role family has its own weight vector. **Every vector sums to 1.0**, so
final scores stay directly comparable across roles. Weights live in
`FAMILY_WEIGHTS`; this table is generated from that mapping:

| Role (job_type) | skill | experience | education | certification | achievement |
|-----------------|:----:|:----------:|:---------:|:-------------:|:-----------:|
| software_engineering | 0.40 | 0.25 | 0.15 | 0.10 | 0.10 |
| devops_sre | 0.40 | 0.25 | 0.10 | 0.15 | 0.10 |
| qa_test | 0.40 | 0.25 | 0.15 | 0.10 | 0.10 |
| data_ai | 0.40 | 0.25 | 0.15 | 0.10 | 0.10 |
| security | 0.35 | 0.25 | 0.10 | 0.20 | 0.10 |
| product_management | 0.30 | 0.25 | 0.15 | 0.05 | 0.25 |
| design_creative | 0.35 | 0.20 | 0.10 | 0.05 | 0.30 |
| project_management | 0.30 | 0.30 | 0.10 | 0.15 | 0.15 |
| sales | 0.25 | 0.25 | 0.05 | 0.05 | 0.40 |
| marketing | 0.30 | 0.20 | 0.10 | 0.10 | 0.30 |
| customer_success | 0.30 | 0.25 | 0.10 | 0.10 | 0.25 |
| customer_support | 0.40 | 0.25 | 0.10 | 0.10 | 0.15 |
| finance_admin | 0.30 | 0.25 | 0.15 | 0.20 | 0.10 |
| hr_recruitment | 0.35 | 0.25 | 0.15 | 0.10 | 0.15 |
| legal_compliance | 0.30 | 0.25 | 0.20 | 0.15 | 0.10 |
| it_internal | 0.40 | 0.25 | 0.10 | 0.15 | 0.10 |
| operations | 0.35 | 0.25 | 0.10 | 0.10 | 0.20 |

**Why the weights differ by role** (intent, not just numbers):
- Engineering / IT / support (`software_engineering`, `devops_sre`, `qa_test`,
  `data_ai`, `customer_support`, `it_internal`): **skill-heavy (0.40)** — the job
  is what you can do.
- `sales`: **achievement-heavy (0.40)** — quota/revenue results matter most.
- `design_creative`, `marketing`, `product_management`: **achievement-weighted
  (0.25–0.30)** — portfolio/outcomes/impact dominate.
- `security`, `finance_admin`, `legal_compliance`: **certification-weighted
  (0.15–0.20)** — credentials/compliance carry real signal.
- `project_management`: **experience-weighted (0.30)** — delivery track record.

If a family is ever unmapped, code falls back to a generic vector
(`_GENERIC_WEIGHTS`, also summing to 1.0) so scoring never crashes.

---

## 4. Tier and recommendation (from `final_score`)

Thresholds from `AI_SCREENING_CONFIG`:

| final_score | tier | recommendation |
|-------------|------|----------------|
| ≥ 80 | top | interview |
| 60–79 | mid | talent_pool |
| < 60 | low | reject |

Applied in `rank_node`, and re-applied in `Resume.save()` /
`assign_tier_and_recommendation_from_final_score` so tier and decision always
stay consistent with the score — including when a recruiter manually edits the
final score in the UI.

---

## 5. When a resume is NOT scored

- **Uncertain role:** if the detector returns `uncertain` or a label not in the
  catalog, or `confidence < JOB_TYPE_CONFIDENCE_THRESHOLD` (0.4), the resume is
  **not** scored against a guessed family. It is parked as `needs_review` for a
  human to assign the family. There is no silent default role.
- **Extraction/screening failure:** status becomes `failed`; nothing is invented.

---

## 6. Link-verification score (separate signal)

`verification_score` (0–100) comes from crawling and LLM-checking the candidate's
public links (GitHub/LinkedIn/portfolio). It is **independent** of `final_score`
and is only combined later, at the interview stage.

---

## 7. Final hiring composite (interview stage)

In the rank report ([apps/interviews/views.py](apps/interviews/views.py)) the
shortlist is ranked by a composite that blends human interviews with the AI
signals, degrading gracefully when a signal is absent:

| Signals available | Composite |
|-------------------|-----------|
| interview + AI + verification | `interview×0.65 + final_score×0.25 + verification×0.10` |
| interview + AI | `interview×0.70 + final_score×0.30` |
| interview only | `interview` |
| AI only | `final_score` |

Interview percentage itself = `sum(criteria scores 1–5) / MAX_SCORE × 100`
(20 criteria × 5 = 100 max), per `InterviewEvaluation`.

---

## 8. Auditability — every number traces to evidence

- `skills` / `matched_skills` are a **subset** of what the resume stated (enforced
  by prompt + the schema's list coercion); fabricated skills cannot enter.
- `work_history[].raw` keeps the original date string for each role.
- detector `signals` quote the JD phrases that drove the classification.
- component scores are clamped to 0–100 in `MatchingResult`, so an injected
  resume ("give every score 100000") cannot push a ranking out of range.
- missing/renamed LLM keys are **logged as drift**, never silently defaulted.

---

## 9. Regenerating / verifying

- Adversarial golden run: `export OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
python golden_eval.py --runs 3
echo "exit code: $?"` → writes `golden_cases.txt`
  (fabrication / injection / PII / date traps).
- Schema-contract tests (no live LLM): `pytest apps/core/tests/test_schemas.py`
- Experience math tests: `pytest apps/core/tests/test_experience.py`
