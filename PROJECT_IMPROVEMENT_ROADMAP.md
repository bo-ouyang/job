# Project Improvement Roadmap

## Purpose
- Improve reliability on core traffic paths.
- Make behavior predictable across restarts and deployments.
- Build a clear iteration plan for feature expansion.

## Phase 1: Stabilization (this sprint)
- Replace non-deterministic cache keys based on Python `hash()` with stable digests.
  - Scope: `analysis_service` stats and keyword analysis cache keys.
  - Done when: same request params always generate the same cache key across process restarts.
- Fix fallback search path runtime risks.
  - Scope: invalid ORM field usage in AI-intent fallback filters and response mapping.
  - Done when: ES unavailable path still returns valid search results instead of raising attribute errors.
- Add targeted regression checks.
  - Scope: cache key generation + AI fallback query execution smoke check.
  - Done when: both checks pass in local test run.

## Phase 2: Observability and Guardrails
- Add structured logs for key cache events.
  - Cache miss/hit, lock acquire timeout, fallback activation.
- Add error budget style counters.
  - ES fallback rate, AI call failure rate, Redis lock timeout count.
- Add feature flags for expensive AI endpoints.
  - Protect production from cost spikes and third-party instability.

## Phase 3: Data and Search Quality
- Normalize salary units consistently across ES and PostgreSQL fallback.
- Improve AI-intent mapping.
  - Better extraction for location aliases, salary ranges, exclude terms.
- Add explainable ranking signals.
  - Keyword score, skill overlap, salary fit, location fit.

## Phase 4: Product Expansion
- Career Compass report history and comparison.
- Resume-to-job matching score with actionable gap suggestions.
- Industry trend snapshots and monthly change tracking.
- Enterprise analytics panel for hiring strategy.

## Execution Principles
- Keep API contract stable while refactoring internals.
- Prefer incremental, reversible changes.
- Ship with at least one regression check per risk fix.

## Immediate Change List (current task)
- [x] Draft roadmap document.
- [x] Refactor analysis cache key hashing.
- [x] Fix AI fallback invalid ORM fields in search path.
- [x] Run sanity checks and report.
