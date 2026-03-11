# Houdini MCP - AI Assistant Context

This file helps LLMs (Claude Code, Cursor, etc.) understand and assist with this project.

## What This Is

HoudiniMCP connects Houdini to AI assistants via the Model Context Protocol (MCP). It has two components:

1. **MCP Server** (`src/houdini_mcp/server.py`) — FastMCP server, stdio transport, connects to Houdini over TCP
2. **Houdini Addon** (`houdinimcp_addon.py`) — socket server running inside Houdini, executes commands via Houdini's Python API

```
AI Client  <-->  houdini-mcp (FastMCP/stdio)  <-->  houdinimcp_addon.py (TCP :9877)  <-->  Houdini
```

## Installation Summary

```bash
# 1. Clone and install
git clone https://github.com/nscrdesigns/houdini-mcp.git
cd houdini-mcp
pip install -e .

# 2. Set up Houdini auto-start
python install.py

# 3. Add to MCP client config (e.g. ~/.claude.json)
# { "mcpServers": { "houdini": { "type": "stdio", "command": "houdini-mcp" } } }

# 4. Launch Houdini — addon auto-starts on localhost:9877
```

If `houdini-mcp` is not on PATH after install, use the full path to the executable. On Windows this is typically `C:/Users/<user>/AppData/Local/Programs/Python/Python3XX/Scripts/houdini-mcp.exe`.

See [INSTALLATION.md](INSTALLATION.md) for detailed steps and troubleshooting.

## Key Files

| File | Purpose |
|------|---------|
| `src/houdini_mcp/server.py` | MCP server — 25 tools exposed to the AI client |
| `houdinimcp_addon.py` | Houdini addon — socket server with command handlers |
| `install.py` | Auto-start installer (patches Houdini's 123.py and 456.py) |
| `pyproject.toml` | Package config, entry point `houdini-mcp` |
| `houdini/packages/houdinimcp.json` | Houdini package template (sets env vars) |

## Architecture Details

- **Multi-instance**: addon tries ports 9877-9886, registers via port files in `%LOCALAPPDATA%/HoudiniMCP/instances/` (Win) or `~/.local/share/houdinimcp/instances/` (Linux/Mac)
- **Discovery**: MCP server scans port files, validates PIDs, connects to newest instance
- **Protocol**: JSON over TCP — `{"type": "command", "params": {...}}` → `{"status": "success", "result": {...}}`
- **Auto-start**: `install.py` creates a Houdini package + patches startup scripts with an import hook

## Development

- `pip install -e .` makes source changes live immediately
- See [DEVELOPERS.md](DEVELOPERS.md) for adding new tools and the full developer guide
- Dependencies: `mcp[cli]>=1.3.0` (declared in pyproject.toml)
- Requires: Python 3.9+, Houdini 19.0+

## Origin

Forked from [katha-begin/houdini-mcp](https://github.com/katha-begin/houdini-mcp). Upstream remote is configured as `upstream`.
