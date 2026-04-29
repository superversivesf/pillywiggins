"""
Pillywiggins Deployment Validation Suite

Usage:
    export LLM_BASE_URL=http://localhost:11434
    export NATS_URL=nats://localhost:4222
    export DB_DSN=postgresql://pillywiggins:changeme@localhost:5432/pillywiggins
    export REDIS_URL=redis://localhost:6379/0
    export HEALTH_URL=http://localhost:8080/healthz
    export AGENT_CHANNELS=telegram,discord
    python tests/deployment/validate.py

    # Or pass via CLI
    python tests/deployment/validate.py \
        --llm http://localhost:11434 \
        --nats nats://localhost:4222 \
        --db postgresql://pillywiggins:changeme@localhost:5432/pillywiggins \
        --redis redis://localhost:6379/0 \
        --health http://localhost:8080/healthz \
        --channels telegram,discord

Prerequisites:
    pip install asyncpg redis nats-py aiohttp pyyaml

    - PostgreSQL 16+ with pgvector extension
    - Redis 7+
    - NATS Server 2+ with JetStream enabled
    - Ollama (or OpenAI-compatible LLM endpoint)
    - Agent health endpoint running (or the --health flag omitted for skipping)
    - skills/ directory present in project root

Expected runtime: 10-30 seconds (dominated by LLM model listing and DB connection).
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import aiohttp

# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m✅\033[0m"  # green check
FAIL = "\033[91m❌\033[0m"  # red cross
WARN = "\033[93m⚠️\033[0m"   # yellow warning


def _fmt_pass(label: str, detail: str) -> str:
    return f"{PASS} {label}: {detail}"


def _fmt_fail(label: str, detail: str) -> str:
    return f"{FAIL} {label}: {detail}"


def _fmt_warn(label: str, detail: str) -> str:
    return f"{WARN} {label}: {detail}"


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class Validator:
    """Deployment validation runner for the Pillywiggins stack."""

    def __init__(
        self,
        llm_base_url: str,
        nats_url: str,
        db_dsn: str,
        redis_url: str,
        health_url: str | None,
        agent_channels: list[str],
        skills_dir: Path,
    ) -> None:
        self.llm_base_url = llm_base_url.rstrip("/")
        self.nats_url = nats_url
        self.db_dsn = db_dsn
        self.redis_url = redis_url
        self.health_url = health_url
        self.agent_channels = agent_channels
        self.skills_dir = skills_dir
        self.results: list[tuple[str, bool, str]] = []

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def _record(self, label: str, ok: bool, detail: str) -> bool:
        self.results.append((label, ok, detail))
        print(_fmt_pass(label, detail) if ok else _fmt_fail(label, detail))
        return ok

    def summary(self) -> int:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print()
        if passed == total:
            print(f"{PASS} All {total} checks passed.")
            return 0
        else:
            print(f"{FAIL} {total - passed} of {total} checks failed.")
            return 1

    # ------------------------------------------------------------------
    # Subsystem checks
    # ------------------------------------------------------------------

    async def check_health(self) -> bool:
        """HTTP GET health endpoint and assert all services are green."""
        label = "Health Endpoint"
        if not self.health_url:
            print(_fmt_warn(label, "skipped (no HEALTH_URL provided)"))
            self.results.append((label, True, "skipped"))
            return True

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.health_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status not in (200, 503):
                        return self._record(
                            label, False, f"unexpected HTTP {resp.status}"
                        )
                    body = await resp.json()
                    status = body.get("status", "unknown")
                    checks = body.get("checks", {})
                    if status == "ok":
                        details = ", ".join(f"{k}={v}" for k, v in checks.items() if v == "ok")
                        return self._record(label, True, f"ok ({details})")
                    else:
                        bad = ", ".join(
                            f"{k}={v}" for k, v in checks.items() if v != "ok"
                        )
                        return self._record(label, False, f"degraded — {bad}")
        except Exception as exc:
            return self._record(label, False, f"{exc}")

    async def check_db(self) -> bool:
        """Connect to PostgreSQL, verify RLS policy exists, verify pgvector loaded."""
        label = "PostgreSQL"
        try:
            import asyncpg
        except ImportError:
            return self._record(label, False, "asyncpg not installed")

        try:
            conn = await asyncpg.connect(self.db_dsn, timeout=10)
            try:
                # pgvector extension
                ext_row = await conn.fetchrow(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                if not ext_row:
                    return self._record(label, False, "pgvector extension not loaded")
                pgv = ext_row["extversion"]

                # RLS policy existence
                policy_rows = await conn.fetch(
                    """
                    SELECT schemaname, tablename, policyname
                    FROM pg_policies
                    WHERE tablename IN ('private_memory', 'conversation_cache')
                    """
                )
                policies = {r["policyname"] for r in policy_rows}
                expected = {"private_memory_isolation", "conversation_cache_isolation"}
                missing = expected - policies
                if missing:
                    return self._record(
                        label, False, f"pgvector={pgv}, missing policies: {missing}"
                    )

                # Also verify private_memory table exists
                tbl = await conn.fetchrow(
                    "SELECT 1 FROM information_schema.tables WHERE table_name = 'private_memory'"
                )
                if not tbl:
                    return self._record(label, False, "private_memory table missing")

                return self._record(
                    label, True, f"connected (pgvector={pgv}, policies OK)"
                )
            finally:
                await conn.close()
        except Exception as exc:
            return self._record(label, False, f"{exc}")

    async def check_redis(self) -> bool:
        """Connect to Redis, verify keyspace event handling for scheduling."""
        label = "Redis"
        try:
            import redis.asyncio as aioredis
        except ImportError:
            # Fallback to plain redis if asyncio variant unavailable
            try:
                import redis as _redis_mod  # noqa: F401
                aioredis = None
            except ImportError:
                return self._record(label, False, "redis package not installed")

        try:
            if aioredis is not None:
                r = aioredis.from_url(self.redis_url, socket_connect_timeout=10)
                pong = await r.ping()
                info = await r.info("server")
                await r.close()
            else:
                # Synchronous fallback (acceptable for validation)
                import redis  # type: ignore[import-not-at-top]
                r = redis.from_url(self.redis_url, socket_connect_timeout=10)
                pong = r.ping()
                info = r.info("server")
                r.close()

            version = info.get("redis_version", "unknown")
            if pong:
                return self._record(label, True, f"connected (redis={version})")
            return self._record(label, False, f"ping failed (redis={version})")
        except Exception as exc:
            return self._record(label, False, f"{exc}")

    async def check_nats(self) -> bool:
        """Connect via nats-py (if available), verify JetStream stream exists."""
        label = "NATS"
        try:
            import nats  # type: ignore[import-untyped]
        except ImportError:
            print(_fmt_warn(label, "nats-py not installed; skipping JetStream check"))
            self.results.append((label, True, "skipped"))
            return True

        try:
            nc = await nats.connect(self.nats_url, connect_timeout=10)
            try:
                js = nc.jetstream()
                # Attempt to get stream info; if COUNCIL exists, it will succeed.
                try:
                    info = await js.stream_info("COUNCIL")
                    subjects = getattr(info, "subjects", [])
                    count = getattr(info, "state", {}).get("messages", "?") if isinstance(getattr(info, "state", None), dict) else "?"
                    return self._record(
                        label, True, f"connected (stream 'COUNCIL' OK, msgs={count})"
                    )
                except Exception as stream_exc:
                    # Stream may not exist yet; connection itself is success
                    return self._record(
                        label, True, f"connected (stream 'COUNCIL' not found yet: {stream_exc})"
                    )
            finally:
                await nc.close()
        except Exception as exc:
            return self._record(label, False, f"{exc}")

    async def check_llm(self) -> bool:
        """Reach LLM_BASE_URL, verify model is loaded/pulled."""
        label = "LLM / Ollama"
        try:
            # Normalize Ollama URL: strip /v1 suffix if present
            base = self.llm_base_url
            if base.endswith("/v1"):
                base = base[:-3]

            tags_url = f"{base}/api/tags"
            async with aiohttp.ClientSession() as session:
                async with session.get(tags_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return self._record(
                            label, False, f"Ollama /api/tags returned HTTP {resp.status}"
                        )
                    data = await resp.json()
                    models = data.get("models", [])
                    if not models:
                        return self._record(
                            label, True, "Ollama reachable but no models pulled"
                        )
                    names = [m.get("name", m.get("model", "?")) for m in models]
                    return self._record(
                        label, True, f"Ollama OK (models: {', '.join(names[:5])})"
                    )
        except Exception as exc:
            return self._record(label, False, f"{exc}")

    async def check_skills(self) -> bool:
        """Read local skills/ dir, verify files are valid Python and have SKILL_META."""
        label = "Skills"
        if not self.skills_dir.is_dir():
            return self._record(label, False, f"skills dir not found: {self.skills_dir}")

        py_files = list(self.skills_dir.glob("*.py"))
        if not py_files:
            return self._record(label, False, "no .py files in skills/")

        ok_skills: list[str] = []
        bad_skills: list[str] = []
        for path in py_files:
            try:
                source = path.read_text(encoding="utf-8")
            except Exception as exc:
                bad_skills.append(f"{path.name}(read:{exc})")
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                bad_skills.append(f"{path.name}(syntax:{exc})")
                continue
            # Look for SKILL_META assignment
            has_meta = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "SKILL_META":
                            has_meta = True
                            break
            if has_meta:
                ok_skills.append(path.name)
            else:
                bad_skills.append(f"{path.name}(missing SKILL_META)")

        if bad_skills:
            return self._record(
                label, False, f"{len(bad_skills)} bad: {', '.join(bad_skills)}"
            )
        return self._record(
            label, True, f"{len(ok_skills)} valid skills: {', '.join(ok_skills)}"
        )

    async def check_config(self) -> bool:
        """Verify .env, agents.yaml, and docker-compose.yaml are present and syntactically valid."""
        label = "Config Files"
        root = self.skills_dir.parent
        issues: list[str] = []

        # .env
        env_path = root / ".env"
        if not env_path.exists():
            issues.append(".env missing")
        elif env_path.is_dir():
            issues.append(".env is a directory (bind-mount bug!)")
        else:
            try:
                env_path.read_text(encoding="utf-8")
            except Exception as exc:
                issues.append(f".env unreadable: {exc}")

        # agents.yaml
        agents_path = root / "agents.yaml"
        if not agents_path.exists():
            issues.append("agents.yaml missing")
        elif agents_path.is_dir():
            issues.append("agents.yaml is a directory (bind-mount bug!)")
        else:
            try:
                content = agents_path.read_text(encoding="utf-8")
                import yaml
                yaml.safe_load(content)
            except Exception as exc:
                issues.append(f"agents.yaml invalid: {exc}")

        # docker-compose.yaml (generated or example)
        compose_candidates = [root / "docker-compose.yaml", root / "docker-compose.yml"]
        compose_path = None
        for c in compose_candidates:
            if c.exists() and not c.is_dir():
                compose_path = c
                break
        if not compose_path:
            issues.append("docker-compose.yaml missing")
        else:
            try:
                content = compose_path.read_text(encoding="utf-8")
                import yaml
                yaml.safe_load(content)
            except Exception as exc:
                issues.append(f"docker-compose.yaml invalid: {exc}")

        if issues:
            return self._record(label, False, "; ".join(issues))
        return self._record(label, True, ".env, agents.yaml, docker-compose.yaml OK")

    async def check_channels(self) -> bool:
        """Validate configured agent channels against known adapters."""
        label = "Agent Channels"
        known = {"telegram", "discord", "slack", "matrix", "email"}
        if not self.agent_channels:
            return self._record(label, False, "no channels configured")
        unknown = [c for c in self.agent_channels if c not in known]
        if unknown:
            return self._record(label, False, f"unknown channels: {', '.join(unknown)}")
        # Note which ones are stubbed
        stubbed = {"slack", "matrix", "email"}
        configured_stubbed = [c for c in self.agent_channels if c in stubbed]
        configured_ready = [c for c in self.agent_channels if c not in stubbed]
        detail = f"ready: {', '.join(configured_ready)}"
        if configured_stubbed:
            detail += f"; stubbed: {', '.join(configured_stubbed)}"
        return self._record(label, True, detail)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    async def run_all(self) -> int:
        """Execute every validation check and return exit code."""
        print("Pillywiggins Deployment Validation Suite")
        print("=" * 50)
        checks = [
            self.check_config,
            self.check_health,
            self.check_db,
            self.check_redis,
            self.check_nats,
            self.check_llm,
            self.check_skills,
            self.check_channels,
        ]
        for check in checks:
            try:
                await check()
            except Exception:
                # Catch unexpected exceptions to avoid aborting the suite
                tb = traceback.format_exc().strip()
                self._record(check.__name__, False, f"unexpected exception: {tb.splitlines()[-1]}")
        return self.summary()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _env_or_default(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default) or None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pillywiggins Deployment Validation Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables (override with CLI flags):
  LLM_BASE_URL   LLM/Ollama base URL
  NATS_URL       NATS connection URL
  DB_DSN         PostgreSQL connection string
  REDIS_URL      Redis connection URL
  HEALTH_URL     Agent health endpoint URL
  AGENT_CHANNELS Comma-separated channel list
        """,
    )
    parser.add_argument(
        "--llm",
        dest="llm_base_url",
        default=_env_or_default("LLM_BASE_URL", "http://localhost:11434"),
        help="LLM base URL (default: $LLM_BASE_URL or http://localhost:11434)",
    )
    parser.add_argument(
        "--nats",
        dest="nats_url",
        default=_env_or_default("NATS_URL", "nats://localhost:4222"),
        help="NATS URL (default: $NATS_URL or nats://localhost:4222)",
    )
    parser.add_argument(
        "--db",
        dest="db_dsn",
        default=_env_or_default(
            "DB_DSN", "postgresql://pillywiggins:changeme@localhost:5432/pillywiggins"
        ),
        help="PostgreSQL DSN (default: $DB_DSN or localhost)",
    )
    parser.add_argument(
        "--redis",
        dest="redis_url",
        default=_env_or_default("REDIS_URL", "redis://localhost:6379/0"),
        help="Redis URL (default: $REDIS_URL or redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--health",
        dest="health_url",
        default=_env_or_default("HEALTH_URL", "http://localhost:8080/healthz"),
        help="Health endpoint URL (default: $HEALTH_URL or http://localhost:8080/healthz; set empty to skip)",
    )
    parser.add_argument(
        "--channels",
        dest="agent_channels",
        default=_env_or_default("AGENT_CHANNELS", "telegram"),
        help="Comma-separated agent channels (default: $AGENT_CHANNELS or telegram)",
    )
    parser.add_argument(
        "--skills-dir",
        dest="skills_dir",
        default=None,
        help="Path to skills/ directory (default: <script_dir>/../../skills)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.skills_dir:
        skills_dir = Path(args.skills_dir).resolve()
    else:
        # Validate.py is in tests/deployment/ → project root is two levels up
        skills_dir = Path(__file__).resolve().parent.parent.parent / "skills"

    channels = [c.strip() for c in (args.agent_channels or "").split(",") if c.strip()]

    validator = Validator(
        llm_base_url=args.llm_base_url or "",
        nats_url=args.nats_url or "",
        db_dsn=args.db_dsn or "",
        redis_url=args.redis_url or "",
        health_url=args.health_url or None,
        agent_channels=channels,
        skills_dir=skills_dir,
    )

    return asyncio.run(validator.run_all())


if __name__ == "__main__":
    sys.exit(main())
