# Architectural Patterns

Conventions that recur across the codebase. Follow them when extending the system;
each lists the canonical definition and representative call sites (file:line).

---

## 1. Soft delete + declarative cascade
Nothing is hard-deleted. An abstract base provides `is_deleted`/`deleted_at`, a default
manager that hides deleted rows, and `all_objects` for raw access.

- Base + manager: [apps/core/models.py:11](apps/core/models.py#L11) (`SoftDeleteManager`), [apps/core/models.py:24](apps/core/models.py#L24) (`SoftDeleteModel`).
- **Cascade is declarative**, not per-model overrides: a model lists reverse-relation
  accessors in `SOFT_DELETE_CASCADE` and the base walks them recursively
  ([apps/core/models.py:41](apps/core/models.py#L41), `_cascade_soft_delete` at [apps/core/models.py:57](apps/core/models.py#L57)).
- Declarations: `Resume.SOFT_DELETE_CASCADE = ('interviews',)` ([apps/core/models.py:177](apps/core/models.py#L177)); `Interview` → `('evaluations',)` ([apps/interviews/models.py](apps/interviews/models.py)).
- **Rule:** a new model that should disappear with its parent must (a) subclass
  `SoftDeleteModel` and (b) be listed in the parent's `SOFT_DELETE_CASCADE`. `on_delete=CASCADE`
  does NOT fire on soft delete — never rely on it for cleanup. `restore()` is shallow (does not un-cascade).
- Web/API querysets must also exclude soft-deleted *parents* (a deleted Job's resumes):
  filter `job__is_deleted=False` — centralized in `_get_active_resume` ([apps/core/views/_helpers.py](apps/core/views/_helpers.py)).

## 2. Service layer (business logic out of views/tasks)
Views and Celery tasks stay thin; domain logic lives in `apps/core/services/`.

- `ResumeService` orchestrates the whole screening flow: [apps/core/services/resume_service.py:17](apps/core/services/resume_service.py#L17) (`process_resume` at :191, `apply_screening_result` at :130).
- Celery tasks are thin wrappers that call the service and own retry/idempotency only ([apps/core/tasks.py](apps/core/tasks.py)).
- **Rule:** new domain behavior goes in a service module, not in a view or task body.

## 3. AI screening = LangGraph node pipeline
A linear `StateGraph` of pure-ish nodes mutating a typed state dict.

- Graph assembly: [apps/core/services/ai_screener.py:383](apps/core/services/ai_screener.py#L383); entry `screen_resume` at [apps/core/services/ai_screener.py:399](apps/core/services/ai_screener.py#L399).
- Nodes: `detect_job_type` → `extract_node` ([:169](apps/core/services/ai_screener.py#L169)) → `match_node` ([:206](apps/core/services/ai_screener.py#L206)) → `score_node` ([:251](apps/core/services/ai_screener.py#L251)) → `rank_node` ([:337](apps/core/services/ai_screener.py#L337)).
- Detector low-confidence routes a resume to `needs_review` instead of guessing a family.
- **Rule:** add a screening step as a new node + edge; read/write only via the state dict.

## 4. Per-family scoring via config-driven weights
Final score is a weighted sum whose weights depend on the detected job family.

- Weight vectors (each sums to 1.0): `FAMILY_WEIGHTS` in [config/settings/base.py:313](config/settings/base.py#L313); generic fallback [apps/core/services/ai_screener.py:34](apps/core/services/ai_screener.py#L34).
- Tier/recommendation thresholds: `AI_SCREENING_CONFIG` ([config/settings/base.py:300](config/settings/base.py#L300)); applied in `rank_node` AND in `Resume.assign_tier_and_recommendation_from_final_score` (single source of truth — keep them in sync).
- **Rule:** tune scoring via settings, not by editing node math. See [SCORING.md](../../SCORING.md).

## 5. LLM client: singleton + cache + retry + reasoning-model awareness
- Singleton with two model handles (text + JSON): [apps/core/services/llm_client.py:20](apps/core/services/llm_client.py#L20) (`__new__` at :44).
- Reasoning models (gpt-5 / o-series) reject non-default temperature — temperature is only
  sent for classic chat models (`_is_reasoning_model`, [apps/core/services/llm_client.py](apps/core/services/llm_client.py)).
- Responses cached in shared Redis keyed by `version + model + md5(prompt)` (`_get_cache_key` at [apps/core/services/llm_client.py:94](apps/core/services/llm_client.py#L94)); transient errors retried via tenacity (`_llm_retry` at [apps/core/services/llm_client.py:105](apps/core/services/llm_client.py#L105)).
- **Rule:** all LLM calls go through `llm_client.invoke_json` / `invoke_text`.

## 6. Prompt composition (shared base + role fragment)
Prompts are files, not string literals: a shared base is combined with a per-family fragment.

- Loader: [apps/core/services/prompt_loader.py](apps/core/services/prompt_loader.py) (`_read_text`/`_fragment_path`, `@lru_cache`); files in `apps/core/prompts/_base/` and `apps/core/prompts/roles/<family>.fragment.txt`.
- **Rule:** add a role by dropping a `*.fragment.txt` file + a `FAMILY_WEIGHTS` entry; don't hardcode prompts in Python.

## 7. Untrusted LLM I/O: injection guard, clamping, schema validation
Resume/JD text is attacker-controlled (public careers form), so model I/O is defended in depth.

- Injection guard appended to every system prompt: `_INJECTION_GUARD` [apps/core/services/ai_screener.py:27](apps/core/services/ai_screener.py#L27).
- Outputs parsed/validated/coerced through Pydantic with clamped scores: [apps/core/services/schemas.py:52](apps/core/services/schemas.py#L52) (`_clamp_score`; `parse_llm_json`).
- `skill_score` is recomputed against the extracted profile so fabricated matched-skills can't inflate it (`score_node`).
- Offline invariants (fabrication, PII leak, bad dates) checked by [apps/core/services/golden_checks.py](apps/core/services/golden_checks.py) — pure functions, run by `golden_eval.py`.
- **Rule:** never trust raw LLM JSON; parse via a schema and clamp numeric outputs.

## 8. SSRF-safe outbound fetch (candidate links)
Candidate-supplied URLs are validated and IP-pinned before any request.

- `url_safety.validate_and_pin` resolves once, rejects private/loopback/link-local/metadata IPs, returns a pinned IP ([apps/core/services/url_safety.py](apps/core/services/url_safety.py)).
- Crawler connects to the pinned IP with the original Host/SNI and a streamed byte cap to avoid DNS-rebinding and memory-DoS ([apps/core/services/link_crawler.py](apps/core/services/link_crawler.py)).
- **Rule:** any new outbound HTTP to user-supplied hosts must go through `url_safety` first.

## 9. Concurrency & idempotency (Celery + DB)
- Status-claim with conditional UPDATE / `select_for_update(skip_locked=True)` so concurrent
  triggers can't double-process: bulk dispatch [apps/core/tasks.py:148](apps/core/tasks.py#L148), result write [apps/core/services/resume_service.py:157](apps/core/services/resume_service.py#L157).
- Follow-up tasks queued via `transaction.on_commit` ([apps/core/services/resume_service.py:188](apps/core/services/resume_service.py#L188)).
- Tasks are `acks_late` with an idempotency short-circuit (skip if already `completed`) and a
  terminal-failure-only status write ([apps/core/tasks.py](apps/core/tasks.py)).
- Public form submits use a row lock + re-check ("use once") — [apps/interviews/views.py](apps/interviews/views.py) `evaluate`.
- **Rule:** background work must be safe to run twice (redelivery) and must not be re-claimable while in flight.

## 10. DRF API conventions
- ViewSets: `IsAuthenticated`, per-action `@ratelimit` decorators, owner stamped on create but
  read shared (single-tenant model): [apps/core/api_views.py:32](apps/core/api_views.py#L32) (Jobs), [apps/core/api_views.py](apps/core/api_views.py) (Resumes).
- Detail routes use the opaque `uuid` (`lookup_field = 'uuid'`), never the sequential pk, to stop enumeration.
- `get_queryset` excludes soft-deleted parents (`job__is_deleted=False`).
- Global throttle + pagination defaults: `REST_FRAMEWORK` in [config/settings/base.py:205](config/settings/base.py#L205).

## 11. HTMX fragment pattern
Server returns partials for live updates; full pages otherwise.

- Fragment views render `templates/*/partials/*.html` and use OOB swaps to refresh sibling
  regions (e.g. resume status + pipeline badges) — `resume_status_fragment` / `resume_row_fragment` in [apps/core/views/resumes.py](apps/core/views/resumes.py).
- HTMX requests detected via `request.headers.get('HX-Request')`; failures surface as toasts globally ([templates/base.html](templates/base.html)).
- **Rule:** reuse `partials/` for any live-updating region; don't return full pages to HTMX swaps.

## 12. Middleware, settings split & resilient cache
- Per-request correlation id links web↔Celery logs; site-wide CSP on every response:
  [config/middleware.py:7](config/middleware.py#L7) and [config/middleware.py:21](config/middleware.py#L21).
- Settings split `base/dev/prod/test`; prod validates required env and fails fast ([config/settings/prod.py:9](config/settings/prod.py#L9)).
- Cache degrades instead of 500-ing when Redis is down: `ResilientRedisCache` ([config/cache_backends.py:34](config/cache_backends.py#L34)); rate limiting is fail-open (`RATELIMIT_FAIL_OPEN`).
- **Rule:** environment-specific values come from env vars read in settings, never hardcoded.
