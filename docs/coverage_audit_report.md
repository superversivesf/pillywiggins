# Comprehensive Test Coverage Audit Report

## Overall Metrics
- **Total source statements**: ~4,815
- **Missing statements**: 711-712
- **Overall line coverage**: **85%**
- **Tests collected (unit/integration)**: ~1,446 passed (plus ~70 integration/real tests skipped/deselected/errors)
- **Files with 100% coverage**: 8
- **Files with <80% coverage**: 5

---

## Per-Module Breakdown

| Module | Coverage | Tests | Gaps |
|---|---|---|---|
| adapters/matrix_adapter.py | **39%** | test_matrix_adapter.py (5 tests) | `connect()`, `listen()`, `_handle_message()`, `send()`, `normalize()` — entire async runtime paths untested; only basic construction tested |
| adapters/slack_adapter.py | **44%** | test_slack_adapter.py (6 tests) | `listen()`, `_on_message()`, `_get_bot_user_id()`, `send()` — socket-handler and message routing untested |
| adapters/email_adapter.py | **46%** | test_email_adapter.py (7 tests) | `connect()`, `listen()`, `_poll_inbox()`, `_handle_email()`, `_send_email()` — all email I/O paths untested |
| embeddings/resolver.py | **48%** | test_embeddings.py (31 tests) | `_resolve_disk_embedding()`, error branch for nonexistent model file, async disk-read fallback |
| onboard.py | **79%** | test_onboard*.py (151 tests) | Docker wizard flows, validation edge cases, interactive TTY branch, many CLI edge cases |
| memory/private.py | **80%** | test_private_memory.py (27 tests) | `_init_pool()` error path, connection-retry branch |
| memory/embeddings.py | **81%** | test_embeddings.py (31 tests) | `_fetch_remote()`, batch-insert error path, `_cleanup()` |
| agents/personality.py | **82%** | test_personality.py (31 tests) | `load_personality()` fallback path, schedule parsing error |
| memory/cache.py | **82%** | test_cache.py (13 tests) | Redis disconnect retry, TTL miss edge case |
| config.py | **83%** | test_config.py (26 tests) | Validation error branches, fallback URL parsing |
| adapters/discord_adapter.py | **85%** | test_discord_adapter.py (34 tests) | `on_message()` edge cases with attachments, `_handle_command()`, reaction errors |
| skills/builder.py | **86%** | test_builder.py (108 tests) | `_run_skill_test()` failure path, `_deploy()` rollback, file-watch race |
| skills/registry.py | **86%** | test_skill_registry.py (50 tests) | `reload()` race, `_discover()` permission error, `execute_skill()` timeout |
| skills/sandbox.py | **86%** | test_sandbox.py (40 tests) | `_kill()` SIGKILL branch, cgroup edge case, network-deny failure |
| skills/url_filter.py | **89%** | test_url_filter.py (19 tests) | `clean` with malformed URLs |
| memory/council.py | **90%** | test_council.py (50 tests) | `_validate_write()` branch for invalid agent, `search()` with empty result |
| agents/tools.py | **90%** | test_brain_skill_tools.py (54 tests) | `make_skill` with invalid docstring, `recall` with no memories, `_run_in_sandbox` timeout |
| messaging/nats_bus.py | **91%** | test_nats_bus*.py (107 tests) | `publish()` when disconnected, `subscribe()` re-subscribe after NATS restart |
| scheduling/scheduler.py | **91%** | test_scheduler.py (38 tests) | `_run_job()` exception handler, reschedule on misfire |
| skills/logger.py | **92%** | test_logs (via helpers) | Minor edge case in formatting |
| adapters/telegram_adapter.py | **93%** | test_telegram_adapter.py (16 tests) | `_handle_webhook()` with no message, `send()` when not connected |
| memory/store.py | **94%** | test_conversation_store.py (19 tests) | `_prune_old()` boundary edge case |
| agents/base.py | **94%** | test_agents*.py (91 tests) | `_start_scheduler()` error path, graceful shutdown edge cases |
| memory/base.py | **95%** | test_memory base tests | `close()` double-call |
| skills/schema.py | **96%** | test_skill_schema.py (31 tests) | Invalid schema type error |
| adapters/base.py | **96%** | test_base_adapter.py (35 tests) | `_is_authorized()` list-match, `dispatch_command()` unknown command |
| health.py | **98%** | test_health.py (17 tests) | `check_health()` LLM non-200 edge case (test exists but coverage missing due to async mock) |
| adapters/models.py | **100%** | test_models.py (17 tests) | — |
| agents/brain.py | **100%** | test_brain.py (25 tests) | — |
| agents/deps.py | **100%** | test_deps.py (12 tests) | — |
| agents_config.py | **100%** | test_agents_config.py (30 tests) | — |
| logging_utils.py | **100%** | test_logging.py (15 tests) | — |
| messaging/unified.py | **100%** | test_messaging_exports.py (4 tests) | — |
| security/prompt_sanitizer.py | **100%** | test_prompt_sanitizer.py (33 tests) | — |
| skills/templates.py | **100%** | test_skill_templates.py (33 tests) | — |

---

## Un-Covered Functions / Methods (with significance and missing paths)

### 🔴 Critical — User-facing adapters and agents

1. **`adapters/matrix_adapter.py:connect()`** (lines 29-37) — No test exercises the `SyncResponse` success branch or warning path; error handling not verified
2. **`adapters/matrix_adapter.py:listen()`** (lines 39-72) — Entire async message loop untested; `signal` setup, `RoomMessageText` processing, error backoff not covered
3. **`adapters/matrix_adapter.py:_handle_message()`** (lines 74-98) — Authorization skip, command dispatch, normal message routing to agent, error reply all untested
4. **`adapters/matrix_adapter.py:send()`** (lines 100-116) — Room send logic not tested; exception path also uncovered
5. **`adapters/slack_adapter.py:listen()`** (lines 36-53) — Async socket-mode startup and shutdown loop untested
6. **`adapters/slack_adapter.py:_on_message()`** (lines 55-100) — Bot user filtering, message normalization, command dispatch, agent reply all untested
7. **`adapters/slack_adapter.py:_get_bot_user_id()`** (lines 102-107) — `auth_test()` path untested
8. **`adapters/slack_adapter.py:send()`** (lines 109-121) — `chat_postMessage` with thread_ts not tested
9. **`adapters/email_adapter.py:connect()`** (lines 88-101) — SMTP login success/failure paths untested
10. **`adapters/email_adapter.py:listen()`** (lines 103-120) — IMAP polling loop and signal setup untested
11. **`adapters/email_adapter.py:_poll_inbox()`** (lines 122-140) — `MailBox` fetch and threaded message handling untested
12. **`adapters/email_adapter.py:_handle_email()`** (lines 142-207) — Thread context building, command dispatch, `_send_email` call paths all untested
13. **`adapters/email_adapter.py:_send_email()`** (lines 209-241) — Full email send flow via `aiosmtplib` untested
14. **`embeddings/resolver.py:_resolve_disk_embedding()`** (lines 24-44) — Fallback disk embedding logic untested; only Ollama path is covered
15. **`agents/base.py:_start_scheduler()`** (line 217-222) — Error path when scheduler fails to start is not tested
16. **`agents/base.py:shutdown()`** (line 354-356) — Graceful shutdown branch with active scheduler worker is only partially hit

### 🟡 High — Memory, scheduling, messaging

17. **`memory/private.py:_init_pool()`** (lines 35-37) — Retry logic on `asyncpg` connection failure not tested
18. **`memory/embeddings.py:_fetch_remote()`** (lines 136-143) — Remote model fetch branch lacks test
19. **`memory/embeddings.py:_cleanup()`** (lines 438-451) — Background cleanup task branch not hit
20. **`memory/cache.py:connect()`** — Redis connection retry after disconnect not simulated
21. **`messaging/nats_bus.py:publish()`** (lines 138-142, 145-147) — Publish when NATS is temporarily disconnected not tested
22. **`messaging/nats_bus.py:subscribe()`** (lines 326-328, 350) — Re-subscribe after NATS restart not tested
23. **`scheduling/scheduler.py:_run_job()`** (lines 176-177, 187-188) — Exception within scheduled job and misfire handling not tested

---

## Test Quality Assessment

### Happy-path only (no error/exhaustive cases)

1. **`test_brain.py:test_agent_run` —** Only tests successful agent run; does not test tool call failure or model timeout
2. **`test_health.py:test_check_health_ok` —** Only validates all-healthy; does not test partial failure or timeout
3. **`test_onboard_flows.py` —** Majority of tests validate success flows; many do not test user pressing "cancel" or providing invalid paths

### Shallow mocks / patch everything

4. **`test_agents.py:test_handle_message` —** Mocks entire `agent.brain.run()`; does not assert on actual return value parsing or tool invocation
5. **`test_discord_adapter.py:test_on_message` —** Mocks `self.agent.handle_message` return but does not verify discord API call arguments or exception handling branches
6. **`test_nats_bus.py:test_publish_success` —** Mocks `nats_client.publish` extensively; does not verify actual NATS connection state

### Missing parametrize for multiple inputs

7. **`test_skill_schema.py` —** Good coverage overall, but several individual schema field tests are duplicated across separate functions instead of using `@pytest.mark.parametrize` on a single test for field type + valid/invalid combos
8. **`test_prompt_sanitizer.py` —** Could benefit from parametrized injection strings instead of one test per string variant
9. **`test_templates.py` —** Template rendering tests are duplicated for each template; should be parametrized over template names and expected output snippets

### No assertion on returned values

10. **`test_agents_failure_paths.py:test_unauthorized_user` —** Asserts that handler returns `None` but does not assert that no agent method was called (risky if logic changes)
11. **`test_council.py:test_store` —** Some tests assert `store()` succeeds but do not assert the actual stored row exists or has correct content

---

## Recommended Priority Order for New Tests

### P0 — Critical (add immediately; user-facing functionality completely untested)

1. **Matrix adapter async flow** — Add mocked `nio.AsyncClient` fixtures and test `connect()`, `listen()`, `_handle_message()`, and `send()` end-to-end with fake `SyncResponse` and `RoomMessageText`
2. **Slack adapter async flow** — Mock `AsyncApp`, `AsyncWebClient`, and `AsyncSocketModeHandler`; test `_on_message` with full message lifecycle and bot-user filtering
3. **Email adapter I/O flow** — Mock `aiosmtplib.SMTP` and `imap_tools.MailBox`; test full `connect()`, `_poll_inbox()`, `_handle_email()`, and `_send_email()` paths (success + SMTP failure)
4. **`agents/base.py:_start_scheduler()` error path** — Inject a broken scheduler configuration and assert that the agent logs an error or raises gracefully

### P1 — High (improves reliability of core infra)

5. **`memory/private.py:_init_pool()` retry path** — Use `asyncpg.connect` side-effect to simulate 1 failure then success
6. **`memory/embeddings.py:_fetch_remote()`** — Mock `httpx.AsyncClient.get` with delayed/failed responses
7. **`messaging/nats_bus.py:publish()` disconnected** — Disconnect NATS client mid-test, assert that publish queues or raises correctly
8. **`scheduling/scheduler.py:_run_job()` exception handler** — Inject a job that raises `RuntimeError` and assert scheduler logs/retries

### P2 — Medium (refactor and enrich existing suites)

9. **Parametrize `test_templates.py`** — Single parametrized test for all built-in personality templates
10. **Parametrize `test_prompt_sanitizer.py`** — Single parametrized test for injection strings and expected sanitized output
11. **Strengthen `test_agents.py`** — Add assertions that verify `handle_message` actually parses LLM output into tools or a text reply, rather than only mocking `brain.run()`
12. **Add branch coverage for `config.py`** — Parametrize invalid YAML / missing env var scenarios

### P3 — Low (nice-to-have)

13. **`skills/builder.py:_deploy()` rollback** — Force a deployment failure and assert rollback state
14. **`skills/sandbox.py:_kill()` SIGKILL branch** — Simulate a subprocess that ignores SIGTERM
15. **Edge cases in `onboard.py` interactive TTY paths** — Add integration tests for Docker wizard under mocked `curses`-style input

---

## Files Skipped / Not Counted

- `src/pillywiggins/__main__.py` and `src/pillywiggins/__init__.py` — Coverage not tracked (boilerplate / thin CLI wrappers mostly covered by `test_main.py`)
- External library mocks and conftest utilities are excluded.

---

## Conclusion

Overall test coverage is **solid at 85%**, but there is a stark gap in **adapter async runtime paths** (Matrix, Slack, Email) and some **edge-case error handling** in core agent and memory modules. Prioritizing adapter I/O tests will significantly increase coverage while protecting the primary user-facing interface. Error-path tests for `_start_scheduler` and `_init_pool` will improve operational resilience.

*Report generated by coverage.py + pytest-cov | 1,446 tests analyzed (excluding real-postgres / real-nats / real-redis / e2e).*