# HoudiniMCP Developer Guide

Guide for developers extending or modifying HoudiniMCP.

## Architecture Overview

```
Claude AI  <-->  MCP Server (stdio)  <-->  TCP Socket  <-->  Houdini Addon  <-->  Houdini
```

### Components

| Component | File | Description |
|-----------|------|-------------|
| MCP Server | `src/houdini_mcp/server.py` | FastMCP server, stdio transport. Discovers addon instances, exposes 28 tools to Claude. |
| Houdini Addon | `houdinimcp_addon.py` | Runs inside Houdini. Socket server, command handlers, dynamic port binding. |
| Installer | `install.py` | Deploys Houdini package + 123.py hook for auto-start. |
| Package template | `houdini/packages/houdinimcp.json` | Template for the Houdini package file. |

### Communication Protocol

Commands are JSON objects sent over TCP:
```json
{"type": "command_name", "params": {"key": "value"}}
```

Responses:
```json
{"status": "success", "result": {...}}
{"status": "error", "message": "error description"}
```

The addon uses chunked receive with JSON-completeness checking (brace counting) to handle large responses.

## Multi-Instance Architecture

### Dynamic Port Allocation

The addon tries ports 9877-9886 sequentially. First available port wins. This allows multiple Houdini sessions to run simultaneously without configuration.

### Port Files

Each running instance writes a port file to advertise itself:

| Platform | Location |
|----------|----------|
| Windows | `%LOCALAPPDATA%\HoudiniMCP\instances\houdini_{port}.json` |
| Linux/Mac | `~/.local/share/houdinimcp/instances/houdini_{port}.json` |

Port file contents:
```json
{
  "port": 9877,
  "pid": 12345,
  "hip_file": "C:/scenes/project.hip",
  "hip_name": "project.hip",
  "houdini_version": "21.0.506",
  "started_at": "2026-02-22T14:30:00",
  "hostname": "localhost"
}
```

### Instance Discovery

The MCP server discovers instances by:
1. Scanning the port file directory for `houdini_*.json` files
2. Validating each PID is still alive (stale files are cleaned up)
3. Connecting to the most recently started instance by default

Connection priority:
1. Reuse existing healthy connection
2. User-specified port (via `connect_to_houdini` tool)
3. Newest discovered instance
4. Fallback to port 9877 (backward compatibility)

## Adding New Tools

To add a new tool, modify both the addon and the server.

### Step 1: Add a command handler in `houdinimcp_addon.py`

In the `execute_command` method, add your command to the `handlers` dictionary and implement the handler method:

```python
# In the handlers dictionary
handlers = {
    # Existing handlers...
    "my_new_command": self.my_new_command,
}

# Handler method
def my_new_command(self, param1, param2=None):
    try:
        # Your Houdini logic here
        result = {"success": True, "data": "some_value"}
        return result
    except Exception as e:
        print(f"Error in my_new_command: {str(e)}")
        traceback.print_exc()
        return {"error": str(e)}
```

### Step 2: Add a tool in `src/houdini_mcp/server.py`

```python
@mcp.tool()
def my_new_tool(ctx: Context, param1: str, param2: Optional[str] = None) -> str:
    """
    Description of what this tool does.

    Parameters:
    - param1: Description
    - param2: Description (optional)
    """
    try:
        houdini = get_houdini_connection()
        result = houdini.send_command("my_new_command", {
            "param1": param1,
            "param2": param2
        })

        if "error" in result:
            return f"Error: {result['error']}"

        return f"Success: {result['data']}"
    except Exception as e:
        logger.error(f"Error in my_new_tool: {str(e)}")
        return f"Error: {str(e)}"
```

### Key conventions

- All data must be JSON-serializable. Convert Houdini types (matrices, colors, etc.) to lists/dicts.
- Use `try/except Exception:` (never bare `except:`) around all Houdini operations.
- Return user-friendly error messages from tools.
- The addon captures stdout from `execute_houdini_code` via `io.StringIO` + `contextlib.redirect_stdout`.

## Project Structure

```
houdini-mcp/
  src/houdini_mcp/
    __init__.py
    server.py              # MCP server (FastMCP)
  houdinimcp_addon.py      # Houdini addon (socket server)
  install.py               # Houdini auto-start installer
  pyproject.toml           # Package config
  houdini/
    packages/
      houdinimcp.json      # Houdini package template
  CLAUDE.md                # AI assistant context
  README.md                # User-facing docs
  INSTALLATION.md          # Installation guide
  DEVELOPERS.md            # This file
```

## Development Workflow

1. **Edit source files** — changes to `server.py` and `houdinimcp_addon.py` are live immediately if installed with `pip install -e .`
2. **Restart the MCP server** — close and reopen your MCP client, or restart the stdio process
3. **Reload the addon** — use the shelf tool "Restart MCP" button, or run in Houdini's Python shell:
   ```python
   import importlib, houdinimcp_addon
   importlib.reload(houdinimcp_addon)
   houdinimcp_addon.init_houdinimcp()
   ```
4. **Test** — ask Claude to use your new tool

## Security

- The addon listens only on `localhost` — not exposed to the network.
- `execute_houdini_code` runs arbitrary Python in Houdini. Powerful but dangerous in untrusted contexts.
- Validate all inputs before passing to Houdini operations.
