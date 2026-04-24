# Pillywiggins Audit Report

**Date:** 2026-04-25  
**Commit:** `de97e41` — *WIP: all outstanding changes before audit*  
**Scope:** Architecture gap analysis, repository health, and git-status synthesis.

---

## Executive Summary

The codebase is in a strong post-implementation state. **1,168 tests pass in ~125 s**, and the core architecture (Docker Compose, per-agent processes, memory isolation via PostgreSQL RLS, skills system, and NATS messaging) is solid. There are **no TODOs or FIXMEs** in source.

> **Ollama is intentionally excluded from `docker-compose.yaml.example`.**  
> Ollama is expected to run externally (e.g. host machine, separate GPU container, or cloud endpoint). Agents connect via `OLLAMA_BASE_URL` in `.env`. This is a deliberate architectural choice to keep GPU drivers, model pulls, and VRAM management outside the project's Compose lifecycle. See `docs/pillywiggins-overview-v2.md` §6 and `IMPLEMENTATION-PLAN.md` §Phase 1.

The primary risks are:
1. **No real DB-level RLS integration test** — all RLS tests are mocked.

## Phase-by-Phase Health

| Phase | Progress | Gap |
|-------|----------|-----|
| 1 — One Agent Talks | ~90 % | No GPU passthrough configured. No restart policies. Ollama is intentionally external; see docs/pillywiggins-overview-v2.md §6. |
| 2 — Memory Works | ~95 % | `ConversationStore` does not set `app.agent_id` on pool init (unlike `PrivateMemory`). All RLS tests are mocked — no real PostgreSQL integration test. |
| 3 — Skills System | ~95 % | `src/pillywiggins/skills/templates.py` is missing. |
| 4 — Multi-Agent Communication | ~50 % | Slack adapter missing. NATS + APScheduler fully implemented. |
| 5 — Full Fleet | ~30 % | Matrix and Email adapters missing. No `slack.yaml`, `matrix.yaml`, or `email.yaml` personalities. |
| 6 — Hardening | ~20 % | Rate limiting, structured JSON logging, backup script, Docker healthchecks, restart policies, and autonomous memory consolidation are all missing. |

---

## Prioritized TODO List

### P0 — Blockers (must fix before usable)

1. **Add Docker healthchecks and `restart: unless-stopped` to all services**
   - Agents (`puck`, `puck-discord`, etc.) have no healthchecks and no restart policy.
   - Infrastructure (`postgres`, `redis`, `nats`) also lacks restart policies in the example.
   - *Impact:* Containers that crash will stay down. No self-healing.

2. **Fix `ConversationStore` pool init to set `app.agent_id`**
   - `PrivateMemory` already does this via `init=on_connect`. `ConversationStore` does not, bypassing RLS for conversation persistence.
   - *Impact:* Conversation rows may not be correctly scoped by agent.

### P1 — High Priority (core features missing)

3. **Write real PostgreSQL RLS integration test**
   - Spin up a real `pgvector` container (or use `pytest-postgresql`), create two DB roles, set `app.agent_id`, and assert that cross-agent reads return zero rows.
   - Current `tests/test_rls_isolation.py` is mocked.
   - *Impact:* The security boundary is unverified in CI.

4. **Implement Slack adapter (`src/pillywiggins/adapters/slack_adapter.py`)**
   - Use `slack_bolt` in Socket Mode (no public URL needed).
   - Add `personalities/slack.yaml` (e.g., Ariel).
   - Add `slack-agent` service to `docker-compose.yaml.example`.
   - *Impact:* Phase 4 verification gate requires two live agents.

5. **Add `src/pillywiggins/skills/templates.py`**
   - Template for LLM-generated skill boilerplate (metadata, `run()` signature, permissions).
   - Referenced in IMPLEMENTATION-PLAN §3.1.
   - *Impact:* Skill builder UX is incomplete without a standard template.

### P2 — Medium Priority (fleet expansion & hardening)

6. **Implement Matrix adapter**
   - `src/pillywiggins/adapters/matrix_adapter.py` using `matrix-nio`.
   - Add `personalities/matrix.yaml` (Cobweb).
   - Defer E2EE to Phase 7 per overview-v2.

7. **Implement Email adapter**
   - `src/pillywiggins/adapters/email_adapter.py` using `aiosmtplib` + `imap-tools`.
   - Add `personalities/email.yaml` (Moth).
   - Start with 3-message context window per overview-v2 §13.

8. **Implement rate limiting**
   - Per-agent token bucket: max 10 LLM calls/minute.
   - Referenced in IMPLEMENTATION-PLAN §6.1 and overview-v2 §9.

9. **Implement structured JSON logging**
   - Replace any `print`/plain-text logs with structured JSON including `agent_id`, `processing_time_ms`, `tools_called`, `tokens_used`.
   - Referenced in IMPLEMENTATION-PLAN §6.2.

10. **Create `scripts/backup-db.sh`**
    - `pg_dump` wrapper producing a gzipped daily backup.
    - Documented in IMPLEMENTATION-PLAN §6.4.

11. **Implement autonomous memory consolidation**
    - `compact_history` exists, but periodic summarization and pruning of old private memories is not wired up.
    - Referenced in IMPLEMENTATION-PLAN §6.3.

12. **Add CI/CD pipeline (`.github/workflows/ci.yml`)**
    - Run `pytest`, `ruff`, and coverage on every PR.

13. **Raise coverage `fail_under`**
    - `pyproject.toml` currently has `fail_under = 0`. Raise to a meaningful threshold (e.g., 70 %) once the above gaps are filled.

### P3 — Polish & nice-to-have

14. **Align test file names with IMPLEMENTATION-PLAN**
    - Rename `tests/test_rls_isolation.py` → `tests/test_memory_isolation.py`.
    - Rename `tests/test_sandbox.py` → `tests/test_skill_sandbox.py`.
    - Content is already equivalent; this is purely cosmetic.

15. **Add pre-commit hooks (`.pre-commit-config.yaml`)**
    - `ruff check`, `ruff format`, `pytest` smoke test.

16. **Write operations runbook**
    - Restart procedures, log checking (`docker compose logs -f <agent>`), backup restoration, Ollama troubleshooting, DB RLS verification.
    - Referenced in IMPLEMENTATION-PLAN §6.6.

17. **(Future) Add Prometheus + Grafana**
    - Defer to Phase 7 per overview-v2 §13. Start with structured JSON logs only.

---

## Repository Health Notes

- **Tests:** 1,168 collected, all passing, ~125 s.
- **Lint:** `ruff` configured (E, F, I, N, W, UP).
- **Coverage:** `fail_under = 0` — not enforced.
- **Dependencies:** `pyproject.toml` only; pins are missing (channel SDKs are not pinned).
- **TODOs/FIXMEs:** Zero.
- **CI/CD:** None present.
- **Pre-commit:** None present.
- **Git status:** 41 changes committed as `de97e41`. Working tree clean. Branch ahead of `origin/main` by 1 commit.

---

## Suggested Next Steps

1. Work through **P0 items** in order (healthchecks → `ConversationStore` RLS fix).
   - Ollama is intentionally external — do **not** add it to `docker-compose.yaml.example`.
2. Then tackle **P1**: real RLS integration test, Slack adapter, `templates.py`.
3. After that, parallelize **P2** adapters (Matrix, Email) with hardening (rate limiting, logging, backups).
4. Finally, land **P3** polish (CI, pre-commit, coverage threshold, runbook) before declaring Phase 6 complete.

---

## Ollama Exclusion — Architecture Note

- **Status:** Intentional, not a bug.
- **Rationale:** Ollama requires NVIDIA drivers, GPU passthrough, large model downloads, and significant VRAM management. Including it in the project's `docker-compose.yaml` couples the application lifecycle to the inference stack.
- **Current approach:** Run Ollama externally (`host.docker.internal:11434`, a separate GPU host, or a cloud endpoint). Point agents to it via `OLLAMA_BASE_URL` in `.env`.
- **Impact:** `docker compose up` starts only PostgreSQL, Redis, NATS, and agent containers. Ollama health is checked by each agent at runtime, not via Compose `depends_on`.
- **Docs:** See `docs/pillywiggins-overview-v2.md` §6 ("What Runs Where") and `docs/IMPLEMENTATION-PLAN.md` §Phase 1 for details.
