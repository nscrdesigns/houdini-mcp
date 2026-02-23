# HoudiniMCP Installation Guide

Step-by-step instructions for installing HoudiniMCP on a new machine.

## Prerequisites

- **Houdini** 19.0 or newer
- **Python** 3.9 or newer (with `pip`)
- **An MCP client**: Claude Code (CLI), Claude Desktop, or Cursor

## Step 1: Clone and install

```bash
git clone https://github.com/nscrdesigns/houdini-mcp.git
cd houdini-mcp
pip install -e .
```

This installs the `houdini-mcp` command and the `houdini_mcp` Python package. The `-e` flag makes it editable — source changes take effect immediately without reinstalling.

For a non-editable install (e.g. on a production machine):
```bash
pip install .
```

Verify the install:
```bash
houdini-mcp --help
```

## Step 2: Set up Houdini auto-start

Run the installer to configure Houdini to auto-start the addon:

```bash
python install.py
```

This does two things:
1. **Creates a Houdini package** at `{houdini_prefs}/packages/houdinimcp.json` that sets environment variables (`HOUDINIMCP_ROOT`, `HOUDINIMCP_AUTO_START`)
2. **Patches `123.py`** in `{houdini_prefs}/scripts/` with an auto-start hook that imports and starts the addon when Houdini launches

The installer auto-detects your Houdini preferences directory (highest version found). Options:

```bash
python install.py --houdini-pref-dir "C:\Users\You\Documents\houdini21.0"  # explicit path
python install.py --dry-run                                                  # preview only
python install.py --uninstall                                                # remove hook + package
```

### Houdini preferences locations

| Platform | Default location |
|----------|-----------------|
| Windows  | `C:\Users\<user>\Documents\houdini<version>\` |
| macOS    | `/Users/<user>/Library/Preferences/houdini/<version>/` |
| Linux    | `~/houdini<version>/` |

You can also set the `HOUDINI_USER_PREF_DIR` environment variable to override.

## Step 3: Configure your MCP client

Choose one of the following:

### Claude Code (CLI)

Add to your Claude Code MCP configuration (user-scope `~/.claude.json` or project-scope `.mcp.json`):

```json
{
  "mcpServers": {
    "houdini": {
      "type": "stdio",
      "command": "houdini-mcp"
    }
  }
}
```

If `houdini-mcp` is not on your PATH, use the full path to the executable:
```json
{
  "mcpServers": {
    "houdini": {
      "type": "stdio",
      "command": "C:/Users/You/AppData/Local/Programs/Python/Python312/Scripts/houdini-mcp.exe"
    }
  }
}
```

### Claude Desktop

Go to Claude > Settings > Developer > Edit Config. Edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "houdini": {
      "command": "houdini-mcp"
    }
  }
}
```

Save and restart Claude Desktop.

### Cursor

Go to Cursor Settings > MCP and add the command:
```
houdini-mcp
```

> Only run one MCP client at a time connected to Houdini — not multiple simultaneously.

## Step 4: Test the connection

1. **Start Houdini**. You should see in the console:
   ```
   [HoudiniMCP] Server started on localhost:9877
   ```
   If you don't see this, the auto-start may not be configured. See [Troubleshooting](#troubleshooting).

2. **Open your MCP client** (Claude Code, Claude Desktop, or Cursor).

3. **Ask Claude to interact with Houdini**:
   ```
   Get the current Houdini scene info
   ```
   If the connection is working, Claude will return information about your Houdini scene.

## Running Multiple Houdini Instances

Each Houdini instance automatically binds to the next available port (9877-9886). The MCP server auto-discovers all running instances and connects to the most recent one.

Use these tools to manage instances:
- `list_houdini_instances` — see all running Houdini sessions
- `connect_to_houdini` — switch to a specific instance by port number

## Manual Start (without auto-start)

If you skip Step 2, you can start the addon manually each session:

1. In Houdini's Python Shell, run:
   ```python
   import sys
   sys.path.insert(0, r"D:\Coding\houdini-mcp")  # adjust to your repo path
   import houdinimcp_addon
   server = houdinimcp_addon.init_houdinimcp()
   ```

2. Or use the shelf tool if you've copied `houdini/toolbar/houdinimcp.shelf` to your Houdini toolbar directory.

## Uninstalling

Remove the Houdini auto-start hook and package:
```bash
python install.py --uninstall
```

Uninstall the Python package:
```bash
pip uninstall houdini-mcp
```

## Troubleshooting

### Addon doesn't auto-start

1. Verify the package file exists:
   - Windows: `C:\Users\<user>\Documents\houdini<ver>\packages\houdinimcp.json`
2. Verify the 123.py hook exists:
   - Windows: `C:\Users\<user>\Documents\houdini<ver>\scripts\123.py`
   - Look for the `# --- HoudiniMCP auto-start hook ---` marker
3. Re-run `python install.py` to reinstall

### "Module not found" errors

- Make sure you ran `pip install -e .` in the houdini-mcp directory
- Verify `houdini-mcp` is accessible: `houdini-mcp --help`
- If using a virtual environment, ensure it's activated

### Connection refused

- Check the Houdini console for the addon's startup message and port number
- The addon only listens on `localhost` — verify you're connecting from the same machine
- If port 9877 is in use, the addon tries ports up to 9886. The MCP server discovers the active port automatically.

### Port conflicts

If another application uses port 9877, the addon automatically binds to the next available port. No configuration needed. Use `list_houdini_instances` to see which port is active.

### Python version mismatch

The MCP server runs in your system Python (3.9+). The Houdini addon runs inside Houdini's embedded Python. These don't need to match — they communicate over TCP.
