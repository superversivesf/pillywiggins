# Refactoring Recommendations for Pillywiggins

## Critical Bugs to Fix First

### 1. `list_models()` call signature mismatch will crash 3 adapters at runtime

Slack, Matrix, and Email adapters call `list_models(self.settings)` but `models.py` expects `(base_url: str, api_key: str, provider: str)`. Additionally, these three adapters access the result as dicts (`m['id']`) when it returns `list[ModelInfo]` dataclasses. This will cause a `TypeError` followed by `AttributeError` if anyone uses `!models` on those platforms.

### 2. Discord's command methods are unreachable dead code

`DiscordAdapter` defines `_cmd_help`, `_cmd_status`, `_cmd_models`, etc. but `_on_message` never dispatches to them. Discord users cannot trigger any commands.

### 3. Discord and Telegram use deprecated `asyncio.get_event_loop()`

Both adapters' `_idle()` method calls `asyncio.get_event_loop()`, which is deprecated since Python 3.10 and will be removed. The other three adapters correctly use `asyncio.get_running_loop()` with exception handling.

---

## High-Priority Structural Issues

### 4. Extract shared adapter logic into `BaseAdapter`

Five patterns are copy-pasted across all 5 adapters with only minor variations:

- `_is_authorized()` — identical logic, differs only in `int` vs `str` parameter type (standardize to `str`)
- `_should_respond_to_bot()` — byte-for-byte identical across all 5 adapters
- `_bot_chat_counts` dict initialization — identical
- `_allow_all` / `_allowed_user_ids` init pattern — identical
- `HELP_TEXT` — identical except command prefix (`/` vs `!`)

Move all of these into `BaseAdapter` or a mixin. Parameterize the command prefix.

### 5. Extract a command dispatcher from the 3x-duplicated `!command` handler

Slack, Matrix, and Email each have a near-identical `_handle_command()` method (~55 lines each) parsing `!command` syntax and routing to help/status/models/etc. Extract into `BaseAdapter.dispatch_command(text, conversation_key) -> str | None`. Telegram and Discord can use the same dispatcher with `/` prefix.

### 6. Create a `PgVectorMemoryBase` class to eliminate ~100 lines of duplication

`PrivateMemory` and `CouncilMemory` share identical implementations of:

- `__init__()` (same 3 params, same pool init, same default dimension)
- `_ensure_agent_id()` (identical SQL, identical docstring rationale)
- `connect()` (pool creation, `register_vector`, JSONB codec, `set_config` — only log message differs)
- `close()` (identical pattern, only log message differs)
- `search()` skeleton (similarity query, row mapping, dimension check)
- `delete()` (identical except table name)

A base class with `__init__`, `_ensure_agent_id`, `connect`, `close`, `_validate_dimension`, and a `delete` template method would eliminate the duplication. Subclasses only override table name, column mapping, and business-rule extras.

### 7. Move tool functions out of `brain.py` into a `tools.py` or `tools/` subpackage

`brain.py` is 782 lines. Lines 14-700 are tool function definitions (embedding calls, memory operations, skill lifecycle, scheduling, inter-agent messaging) that are not "brain" logic — they are capabilities. The actual `create_brain()` function is lines 703-782. Extracting the tools would make the file navigable and let each tool be tested in isolation.

### 8. Consolidate the 4x-duplicated embedding call pattern in brain tools

Four tool functions (`query_council_memory`, `share_to_council`, `recall_private_memory`, `save_to_private_memory`) each contain this identical block:

```python
from pillywiggins.config import Settings
settings = Settings()
embedding = await embed(text, base_url=settings.llm_base_url, ...)
if embedding is None:
    return "Could not generate embedding..."
```

Extract into `async def _embed_text(text: str) -> list[float] | None` and call it from each tool. This also fixes the problem of `Settings()` being instantiated 7 times across `brain.py`.

---

## Medium-Priority Simplifications

### 9. Unify dual message history storage

`PillywigginAgent` maintains both `self._message_history` (default conversation) and `self._conversation_histories` (per-key dict). This forces every method to branch on `if conversation_key:`, appearing in 5+ places. Replace with `self._conversation_histories: dict[str, list[ModelMessage]]` and use `""` as the default key. Remove `self._message_history` entirely.

### 10. Extract `_rebuild_brain()` method

`create_brain(...)` is called with identical arguments in 3 places (`__init__`, `_refresh_brain_tools`, `switch_model`). A `_rebuild_brain()` method would be a single edit point for signature changes.

### 11. Make `_builtin_*_handler` functions methods on `PillywigginAgent`

The module-level `_builtin_send_message_handler` and `_builtin_heartbeat_handler` reach into 10+ private attributes of `PillywigginAgent` via `_ACTIVE_AGENTS[agent_id]`. This is maximum coupling to hidden global state. Make them methods on the class and remove `_ACTIVE_AGENTS` entirely — pass the agent reference directly to the scheduler.

### 12. Decompose `start()` and `shutdown()` into named sub-methods

`start()` is 59 lines with 4 independent try/except blocks for subsystem initialization. `shutdown()` is 38 lines with 5 independent `try/except/log/nullify` blocks. Extract each into `_start_council_memory()`, `_start_private_memory()`, `_start_nats_bus()`, `_start_scheduler()`, and a `async def _safe_close(resource, name)` helper.

### 13. Extract the 3x-duplicated skill draft/test pipeline

`test_skill_code`, `review_skill_code`, and `publish_skill_code` in `brain.py` all contain the same 3-phase pipeline: parse `test_cases_json` -> draft the skill -> run tests. A `_draft_and_test(name, code, test_cases_json) -> Draft | str` helper would collapse ~30 lines x 3 into single call sites.

### 14. Consolidate sandbox execution into a single function

`run_sandboxed()` and `run_test_driven()` in `sandbox.py` share ~80% identical code (temp file creation, subprocess spawn, timeout handling, stdout/stderr decoding, JSON parsing, cleanup). Extract a shared `_run_in_subprocess(code, args, timeout)` core function.

### 15. Pass `Settings` through `AgentDeps` instead of re-instantiating it

`Settings()` is instantiated 7 times in `brain.py` tool functions via `from pillywiggins.config import Settings; settings = Settings()`. This is a hidden dependency, wasteful if Settings re-parses env, and untestable without monkeypatching. Add `settings: Settings` to `AgentDeps` and pass it through.

### 16. Type `AgentDeps` fields properly instead of using `Any`

7 of 11 fields on `AgentDeps` are typed as `Any` despite proper types being available (`Personality`, `PrivateMemory`, `SkillRegistry`, etc.). This defeats static analysis and IDE support.

### 17. Fix `apply_agent_env()` process-wide mutation

`agents_config.py:apply_agent_env()` sets `os.environ` keys globally, making it unsafe for multi-agent same-process scenarios. It also overwrites existing env vars without checking. Consider scoping agent config to the agent instance rather than mutating global state.

---

## Inconsistencies to Standardize

### 18. Standardize "not connected" error handling across memory modules

There are 5 distinct behaviors across 11 "not connected" guard clauses: error log + return sentinel, warning log + return, debug log + return, silent return, and structured error dict. Choose one pattern and apply it consistently. Recommended: return a `Result` type or raise a custom `NotConnectedError`.

### 19. Standardize error return types from tool functions

Tool functions in `brain.py` return errors as strings with inconsistent prefixes: `"Error: ..."`, `"Could not ..."`, `"Failed to ..."`, `"Scheduler not available"`. Define a convention (e.g., always prefix with the tool name or use a structured error format).

### 20. Standardize logging approach

Four different logging strategies exist: `logging.getLogger(__name__)` (builder.py), a hardcoded named logger `"pillywiggins.skill_exec"` (logger.py), custom `AgentLogger` with per-agent file handlers (logging_utils.py), and `print()` statements (onboard.py). Adopt a single pattern — `AgentLogger` for agent-specific logs, `logging.getLogger(__name__)` for infrastructure.

### 21. Standardize `Optional[X]` vs `X | None`

The codebase mixes `Optional` from `typing` and `X | None` union syntax. Since the project requires Python 3.12+, adopt `X | None` consistently and remove `Optional` imports.

### 22. Use proper generic type annotations

`base.py` uses bare `list` instead of `list[ModelMessage]`, bare `dict` instead of `dict[str, Any]`, and `Optional` mixed with `str | None`. Clean up for consistency.

### 23. Move `HELP_TEXT` to a parameterized template

Each adapter defines its own `HELP_TEXT` constant that differs only in command prefix (`/` vs `!`). Define it once in `BaseAdapter` with a configurable prefix.

---

## Test Suite Improvements

### 24. Extract shared test helpers into `conftest.py` or a `tests/helpers.py`

These patterns are duplicated across multiple test files and should be shared:

- `_make_pool_mock()` — identical in `test_council.py`, `test_conversation_store.py`, `test_private_memory.py`
- `_make_ctx()` for `AgentDeps` — in `test_brain.py`, `test_brain_tools.py`, `test_make_skill_tool.py`
- `_make_skill()` — in `test_brain.py`, `test_make_skill_tool.py`
- `_make_adapter()` — in `test_adapters.py`, `test_discord_adapter.py`
- Mock aiohttp session factory — in `test_brave_search.py`, `test_check_website.py`, `test_embeddings.py` (~15 repetitions)

### 25. Consolidate Docker integration test infrastructure

`test_e2e_compose.py`, `test_compose_health.py`, and `test_infra_smoke.py` each independently implement `_merged_compose_with_alt_ports()`, `_wait_for_healthy()`, and `docker_available` fixtures. Extract into `tests/integration/conftest.py`.

### 26. Parameterize the `test_health.py` sys.modules manipulation

The file has 6+ nearly identical 30-50 line test functions that differ only in which modules they mock. Each repeats the same `sys.modules` save/patch/restore pattern. Use `pytest.mark.parametrize` with a fixture or context manager.

### 27. Split oversized test files

- `test_brain.py` (1462 lines) — split tool tests into `test_brain_tools.py` (which already exists but is underused), `test_brain_memory_tools.py`, `test_brain_skill_tools.py`, `test_brain_schedule_tools.py`
- `test_onboard.py` (2773 lines) — split into `test_onboard_config.py`, `test_onboard_docker.py`, `test_onboard_flows.py`

### 28. Stop testing private attributes directly

`test_agents.py` tests `agent._model_name`, `agent._provider`, `agent._api_key`, etc. — all underscore-prefixed internals. Test behavior through public methods. Similarly, `test_brain.py` inspects `agent._function_toolset.tools.keys()` which couples to pydantic-ai internals.

### 29. Remove duplicate `test_health.py` `_make_mock_nats()` definition

Defined at lines 11-16 and again at lines 103-108. The first definition is shadowed and never used.

### 30. Remove duplicate `test_builder.py` test method

`test_escaped_newline_literal_caught_gracefully` is defined twice with identical bodies. Python silently shadows the first.

---

## Security Hardening

### 31. Sandbox permissions are advisory, not enforced

The `SKILL_NETWORK`, `SKILL_SUBPROCESS`, `SKILL_FILE_WRITE` env vars are flags that skill code is expected to respect, but there is no OS-level enforcement. Any skill can access the network or filesystem regardless of its declared permissions. Consider using `subprocess` resource limits (`resource.setrlimit`), network namespaces, or a container runtime for actual isolation.

### 32. Skill code runs in the main process on load

`SkillRegistry._load_skill_file()` uses `importlib.util.spec_from_file_location` to execute skill code directly in the agent process. Top-level code in a skill file runs with full privileges. Only *test* execution goes through the sandbox.

### 33. `eval()` on SKILL_META AST values in `builder.py`

Line 102: `eval(compiled)` on an AST node extracted from untrusted skill code. If `SKILL_META` contains a call expression like `{"key": os.system("...")}`, it would execute. Use `ast.literal_eval` instead.

### 34. Sandbox temp files written to hardcoded `/tmp`

`sandbox.py` uses `tempfile.NamedTemporaryFile(dir="/tmp")`, bypassing the OS's secure temp directory. Remove the `dir="/tmp"` argument to let Python use its default secure location.

### 35. PII leak in `private.py` dimension mismatch log

Line 72 logs `content[:100]` at ERROR level when an embedding dimension mismatches. This leaks user content into logs. Remove the content from the log message.

---

## Dead Code and Unused Paths

### 36. Remove `_is_dangerous_env()` and `DENIED_ENV_PATTERNS` from `sandbox.py`

Defined but never called. `restricted_env()` uses an allowlist (`SAFE_ENV_VARS`), not this deny-list.

### 37. Remove `SkillRegistry.broadcast_reload()`

Never called anywhere. It silently does nothing if no event loop is running.

### 38. Remove `Personality.scheduling` field

Set in `load_personality` but never referenced anywhere. The `schedules` field is used instead.

### 39. Remove redundant `if self.archetype:` inside `elif self.archetype:` in `personality.py`

Line 34: `if self.archetype:` inside an `elif self.archetype:` block is always True — dead code.

### 40. Remove `functools.partial` import from `scheduler.py`

Line 4: imported but never used.

### 41. Remove `_ACTIVE_AGENTS` global registry

Replace by passing agent references directly to scheduler callbacks rather than looking them up from module-level mutable global state.

---

## Minor Cleanups

### 42. Fix Email adapter's `_should_respond_to_bot` dead code

Defined but never called — email has no bot-chat-limit enforcement.

### 43. Move `import html` to module level in `email_adapter.py`

Currently imported inside a method body, executed on every HTML email.

### 44. Fix `cache.py`/`store.py` close inconsistency

`cache.py` does not log on close; `store.py` does. Also `cache.py` sets `self._redis = None` on failure (self-healing) but `store.py` does not null out `self._pool`. Decide on one pattern and apply consistently.

### 45. Fix `council.py`'s two-branch INSERT

Lines 153-179 have separate INSERT statements for with-embedding and without-embedding cases. Use a single parameterized INSERT passing `None` for missing embeddings, which asyncpg handles natively.

### 46. Move `onboard.py` relative paths to use `Settings` or `Path(__file__)`

Module-level `Path("personalities")` etc. depend on CWD. Use `Path(__file__).parent.parent.parent / "personalities"` or resolve via Settings.

### 47. Fix `onboard.py` hardcoded "Telegram" in reconfigure flow

Line 976: `_reconfigure_agent_flow()` always says "Telegram bot token" regardless of the agent's channel.

### 48. Replace pure-Python cosine similarity in `council.py` with pgvector operator

Lines 322-330 compute cosine similarity in Python over 768-dimension vectors fetched from the database. Push this computation to PostgreSQL using pgvector's `<=>` operator in the deduplication query instead.

### 49. Add `__aenter__`/`__aexit__` to memory classes

None of `PrivateMemory`, `CouncilMemory`, `ConversationCache`, `ConversationStore` implement async context manager. Callers must remember manual `close()`. Adding `async with` support would prevent resource leaks.

### 50. Add `shutdown()` as abstract method on `BaseAdapter`

Telegram, Discord, and Matrix implement it, but Slack and Email do not. Adding it to the ABC with a default no-op implementation would formalize the contract.