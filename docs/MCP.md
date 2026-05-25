# MCP Server Integration

Practical guide for configuring MCP (Model Context Protocol) servers with Pillywiggins. Servers are global — configured once, available to all agents.

---

## Overview

MCP servers let Pillywiggins agents access external tools: filesystem access, GitHub APIs, database queries, and any other MCP tool server. Servers are configured in `skills/mcp_servers.json` (one file for the whole swarm), loaded at agent startup, and their tools are registered alongside existing skills as PydanticAI toolsets.

**Key facts:**
- **Global, not per-agent** — All agents get the same MCP tools. Use `tool_prefix` if you need to differentiate by purpose.
- **Two transport types** — stdio (runs a local command as a subprocess) or Streamable HTTP (connects to a remote server).
- **Configured via the onboard wizard** — `pillywiggins onboard`, then select "Configure MCP servers".
- **No restart needed for config** — Run the wizard, save, then `docker compose restart <agent>` to pick up changes.

---

## Adding MCP Servers via Onboard

The onboard wizard provides an interactive `🔌 Configure MCP servers` menu. Here's the full walkthrough:

### Step 1: Enter the wizard

```bash
pillywiggins onboard
```

From the main menu, select **`🔌 Configure MCP servers`**.

### Step 2: Add a server

The wizard asks whether to add a new server. Current servers are listed if any exist:

```
Add or update an MCP server? (Y/n)
```

Answer **Y** to proceed.

### Step 3: Name the server

```
MCP server name (lowercase, e.g. 'filesystem', 'github-tools'):
```

Names must be lowercase with letters, digits, underscores, or dashes (`[a-z][a-z0-9_-]*`).

### Step 4: Choose transport

```
Transport:
  ○ Stdio — run as subprocess (e.g. Python, npx, uvx)
  ○ Streamable HTTP — connect to remote server
```

### Step 5a: For stdio — command and arguments

```
Command: npx
Arguments (space-separated): -y @modelcontextprotocol/server-filesystem /tmp
```

### Step 5b: For Streamable HTTP — URL

```
Server URL: http://localhost:8000/mcp
```

### Step 6: Optional prefix

```
Tool prefix (optional, to avoid name clashes):
```

Use this to namespace tools from different servers. For example, prefix `fs` makes the filesystem server's tools appear as `fs_read_file`, `fs_write_file`, etc.

### Step 7: Save

The wizard writes to `skills/mcp_servers.json` and confirms:

```
✅ MCP configuration saved to skills/mcp_servers.json
  2 server(s) configured
```

### Editing and removing servers

Rerun `pillywiggins onboard` → `🔌 Configure MCP servers`. The wizard offers to edit existing servers or remove them.

---

## Transport Types

### Stdio

Runs a command as a subprocess. The agent spawns the process, communicates via stdin/stdout (MCP protocol), and kills it on shutdown.

```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
}
```

**Supported fields for stdio:**
| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Server identifier |
| `command` | Yes | Executable to run |
| `args` | No | Arguments (list of strings, default `[]`) |
| `env` | No | Environment variables (dict, e.g. `{"GITHUB_TOKEN": "ghp_..."}`) |
| `tool_prefix` | No | Prefix for all tools from this server |
| `timeout` | No | Tool execution timeout in seconds |

### Streamable HTTP

Connects to a remote MCP server over HTTP. Useful when the MCP server runs in another container, on another host, or as a cloud service.

```json
{
  "name": "weather-api",
  "url": "http://weather-mcp:8000/mcp"
}
```

**Supported fields for HTTP:**
| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Server identifier |
| `url` | Yes | Full URL to the MCP endpoint |
| `tool_prefix` | No | Prefix for all tools from this server |
| `timeout` | No | Tool execution timeout in seconds |

---

## Example Servers

Three real, copy-pasteable configurations.

### 1. Filesystem Access

Let agents read and write files in a specific directory. **Use with caution** — tools like `write_file` can modify your filesystem.

**Via the wizard:**
```
Server name: filesystem
Transport: stdio
Command: npx
Arguments: -y @modelcontextprotocol/server-filesystem /tmp
Tool prefix: fs
```

**Manual JSON:**
```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  "tool_prefix": "fs"
}
```

**Result:** After restart, agents have `fs_read_file`, `fs_write_file`, `fs_list_directory`, etc. All restricted to `/tmp`.

### 2. GitHub Tools

Read issues, create PRs, manage repositories — all from the agent.

**Prerequisites:**
1. Create a GitHub personal access token: [Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens)
2. Set it as an environment variable in your shell or `.env`:
   ```bash
   export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_yourtokenhere
   ```
3. Pass it via the `env` field (manual JSON only — the wizard doesn't prompt for env vars; edit `skills/mcp_servers.json` directly for this).

**Manual JSON:**
```json
{
  "name": "github",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_yourtokenhere"
  },
  "tool_prefix": "gh"
}
```

**Result:** Agents can `gh_search_repositories`, `gh_create_issue`, `gh_create_pull_request`, etc.

**Security note:** Never commit `skills/mcp_servers.json` if it contains tokens. The file is gitignored by default, but verify with `git status`.

### 3. PostgreSQL Explorer

Let agents run read-only SQL queries against your database.

**Manual JSON:**
```json
{
  "name": "postgres-explorer",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost:5432/mydb"],
  "tool_prefix": "pg"
}
```

**Tip:** For the Pillywiggins database itself, the connection string is in `.env` as `DATABASE_URL`. Only use read-only credentials — agents should never have write access to the production DB.

**Docker network note:** If PostgreSQL runs in Docker Compose, use the service name as hostname: `postgresql://pillywiggins:password@postgres:5432/pillywiggins`.

---

## Manual Configuration

The onboard wizard is the recommended path, but you can also create or edit `skills/mcp_servers.json` directly.

### File location

```
skills/mcp_servers.json
```

### Format

A JSON array of server objects:

```json
[
  {
    "name": "filesystem",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "tool_prefix": "fs"
  },
  {
    "name": "github",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_yourtokenhere"
    },
    "tool_prefix": "gh"
  },
  {
    "name": "weather-api",
    "url": "http://weather-mcp:8000/mcp"
  },
  {
    "name": "postgres-explorer",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@localhost:5432/mydb"],
    "tool_prefix": "pg",
    "timeout": 30
  }
]
```

### Applying changes

After editing the file, restart the agent(s):

```bash
docker compose restart puck
docker compose restart bramblethorn
```

Or rebuild:

```bash
docker compose up -d --build puck
```

---

## Runtime Behavior

### Startup

1. Agent process starts (`__main__.py`).
2. `_load_mcp_config()` reads `skills/mcp_servers.json`.
3. For each server entry, `_build_mcp_toolsets()` creates either:
   - `MCPServerStdio(command, args=..., env=..., tool_prefix=...)`
   - `MCPServerStreamableHTTP(url, tool_prefix=...)`
4. These toolsets are registered on the PydanticAI Agent via `agent._function_toolset._register(ts)`.

### Tool Discovery

MCP servers expose tools through the MCP `tools/list` handshake. The agent calls this at startup to discover available tools. Tools appear alongside skill-based tools — the agent's LLM sees them all as a unified tool list.

### Lifecycle

- **Stdio subprocesses** are spawned when the agent starts and killed when the agent stops.
- **HTTP connections** are established lazily (on first tool use) and maintained for the agent's lifetime.
- If a server crashes, the agent logs the error and continues. Tools from that server become unavailable.
- If `skills/mcp_servers.json` is missing or invalid JSON, agents start with zero MCP tools and log a warning — no crash.

### Tool Naming

Without a `tool_prefix`, tools use their native MCP names. With a prefix, they're namespaced:

| Server | Prefix | Tool Name |
|--------|--------|-----------|
| filesystem | `fs` | `fs_read_file` |
| filesystem | none | `read_file` |
| github | `gh` | `gh_create_issue` |
| weather-api | none | `get_forecast` |

---

## Troubleshooting

### Server won't start — "command not found"

**Symptom:** Agent logs show `Failed to create MCP server 'myserver'` or the subprocess exits immediately.

**Diagnosis:**
```bash
# Test the command manually
npx -y @modelcontextprotocol/server-filesystem /tmp

# Check if npx/node are installed
which npx
which node
```

**Fix:** Install Node.js (MCP servers typically require it):
```bash
# Ubuntu/Debian
sudo apt install nodejs npm

# macOS
brew install node
```

### Permissions / file access denied

**Symptom:** Agent can't access filesystem tools or gets permission errors.

**Fix:** For the filesystem MCP server, the directory you pass as an argument is the only one accessible. Ensure:
- The directory exists: `mkdir -p /tmp/mcp-workspace`
- The agent process has read/write permissions on it
- You're using an absolute path (not relative)

### Docker: agent can't reach MCP server

**Symptom:** Streamable HTTP MCP server unreachable from agent container.

**Diagnosis:**
```bash
# From inside the agent container
docker compose exec puck curl http://my-mcp-server:8000/mcp

# Check network
docker compose exec puck ping my-mcp-server
```

**Fix:** Ensure the MCP server is either:
- In the same Docker Compose network (add it to `docker-compose.yaml`)
- Reachable via `host.docker.internal` (Docker Desktop) or host IP (Linux — see OPS-RUNBOOK.md §7.1)
- Exposed on the Docker host at `0.0.0.0`

### Agent can't see MCP tools

**Symptom:** Agent acts like MCP tools don't exist. No tool-related errors, just silence.

**Diagnosis:**
```bash
# Verify the config file exists and is valid JSON
cat skills/mcp_servers.json | python -m json.tool

# Check agent logs for MCP loading messages
docker compose logs puck 2>&1 | grep -i "mcp"
```

Expected output: `MCP server 'filesystem' loaded (stdio)` or `MCP server 'github' loaded (http)`.

**Fix:**
- If the file is missing: run `pillywiggins onboard` → `🔌 Configure MCP servers` and add servers.
- If the file exists but no "loaded" messages: check JSON validity. A trailing comma or missing quote breaks the whole array.
- If loaded but tools don't appear: verify the MCP server itself is running and responding. Test the command or HTTP endpoint directly.

### Timeout errors on tool calls

**Symptom:** Agent times out when calling an MCP tool, especially slow operations like database queries or API calls.

**Fix:** Set a `timeout` field (in seconds) per server:
```json
{
  "name": "postgres-explorer",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://..."],
  "timeout": 60
}
```
Default is whatever the MCPServer implementation uses (typically 30s). Increase for slow operations.
