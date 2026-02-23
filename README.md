# HoudiniMCP - Houdini Model Context Protocol Integration

HoudiniMCP connects Houdini to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Houdini. This integration enables prompt-assisted 3D modeling, scene creation, simulation setup, and rendering.

## Features

- **Two-way communication**: Connect Claude AI to Houdini through a socket-based server
- **Node manipulation**: Create, modify, and delete nodes in Houdini networks
- **Geometry creation**: Generate various primitive types with customizable parameters
- **Material control**: Apply and modify materials
- **Scene inspection**: Get detailed information about the current Houdini scene
- **Simulation setup**: Create and run physics simulations (fluids, particles, etc.)
- **Rendering control**: Configure and execute rendering operations, including COP/compositing renders
- **Code execution**: Run arbitrary Python code in Houdini from Claude
- **Viewport screenshots**: Capture viewport images for visual verification
- **File management**: Save/load HIP files, export to FBX, Alembic, and USD
- **Multi-instance support**: Run multiple Houdini sessions simultaneously with automatic port allocation
- **Auto-start**: Addon starts automatically when Houdini launches (via installer)

## Architecture

```
Claude AI  <-->  houdini-mcp (FastMCP/stdio)  <-->  houdinimcp_addon.py (TCP socket)  <-->  Houdini
```

The system consists of two main components:

1. **Houdini Addon (`houdinimcp_addon.py`)**: A Python extension that runs inside Houdini, creating a socket server to receive and execute commands. Supports dynamic port allocation (ports 9877-9886) for multiple simultaneous Houdini sessions.
2. **MCP Server (`src/houdini_mcp/server.py`)**: A FastMCP server that communicates with Claude via stdio and connects to the Houdini addon over TCP. Automatically discovers running Houdini instances via port files.

## Quick Start

### Prerequisites

- Houdini 19.0 or newer
- Python 3.9 or newer

### 1. Install the package

```bash
git clone https://github.com/nscrdesigns/houdini-mcp.git
cd houdini-mcp
pip install -e .
```

### 2. Set up Houdini auto-start

```bash
python install.py
```

This automatically:
- Creates a Houdini package (`houdinimcp.json`) in your Houdini preferences
- Patches `123.py` to auto-start the addon when Houdini launches

The installer auto-detects your Houdini preferences directory. Use `--houdini-pref-dir` to specify it manually, or `--dry-run` to preview changes.

### 3. Configure your MCP client

**Claude Code (CLI):**
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
Add this to your user or project MCP config (see [Claude Code docs](https://docs.anthropic.com/en/docs/claude-code)).

**Claude Desktop:**

Go to Claude > Settings > Developer > Edit Config > `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "houdini": {
      "command": "houdini-mcp"
    }
  }
}
```

**Cursor:**

Go to Cursor Settings > MCP and add the command: `houdini-mcp`

### 4. Launch Houdini

Start Houdini normally. The addon auto-starts and you should see in the console:
```
[HoudiniMCP] Server started on localhost:9877
```

You're ready to use Claude with Houdini.

## Tools

HoudiniMCP exposes 28 tools to Claude:

### Scene & Node Management
| Tool | Description |
|------|-------------|
| `get_scene_info` | Get scene information (nodes, network, hip file) |
| `get_node_info` | Get detailed information for a specific node |
| `create_node` | Create a new node with parameters |
| `create_geometry` | Create primitive geometry (box, sphere, torus, etc.) |
| `modify_node` | Modify an existing node's properties |
| `delete_node` | Remove a node from the scene |
| `set_parameter` | Set a parameter value on a node |
| `get_parameter_info` | Get detailed parameter information |
| `connect_nodes` | Connect two nodes together |
| `layout_network` | Auto-layout nodes in a network |
| `create_subnet` | Create a subnet to organize nodes |
| `create_digital_asset` | Create a Houdini Digital Asset from a subnet |

### Materials, Cameras & Lights
| Tool | Description |
|------|-------------|
| `set_material` | Apply or create materials for objects |
| `create_camera` | Create a camera with positioning options |
| `create_light` | Create a light with customizable type and parameters |

### Simulation
| Tool | Description |
|------|-------------|
| `create_simulation` | Set up a simulation network for physics |
| `run_simulation` | Execute a simulation for a frame range |

### Rendering & Export
| Tool | Description |
|------|-------------|
| `render_scene` | Render the scene with configurable options |
| `render_cop` | Render a COP/compositing node to disk |
| `screenshot_viewport` | Capture a viewport screenshot |
| `export_fbx` | Export to FBX format |
| `export_abc` | Export to Alembic format |
| `export_usd` | Export to USD format |

### File Management
| Tool | Description |
|------|-------------|
| `save_hip` | Save the current HIP file |
| `load_hip` | Load a HIP file |
| `execute_houdini_code` | Run arbitrary Python code in Houdini |

### Multi-Instance Management
| Tool | Description |
|------|-------------|
| `list_houdini_instances` | List all running Houdini instances |
| `connect_to_houdini` | Switch connection to a specific Houdini instance |

## Multi-Instance Support

You can run multiple Houdini sessions simultaneously. Each instance automatically binds to the next available port in the range 9877-9886 and registers itself via a port file.

The MCP server automatically discovers running instances and connects to the most recently started one. Use `list_houdini_instances` and `connect_to_houdini` to manage connections.

## Manual Start (without auto-start)

If you prefer not to use auto-start, you can start the addon manually in Houdini's Python shell:

```python
import houdinimcp_addon
server = houdinimcp_addon.init_houdinimcp()
```

Or use the shelf tool (if installed): **HoudiniMCP > Start MCP**

## Uninstalling

Remove the auto-start hook and Houdini package:
```bash
python install.py --uninstall
```

To fully uninstall:
```bash
pip uninstall houdini-mcp
```

## Troubleshooting

- **Connection issues**: Make sure the Houdini addon is running (check Houdini console for startup message). Verify the MCP server can reach `localhost` on the addon's port.
- **Port conflicts**: If port 9877 is in use, the addon automatically tries the next port in the range. Use `list_houdini_instances` to see which port was assigned.
- **Auto-start not working**: Verify the package file exists at `{houdini_prefs}/packages/houdinimcp.json` and the hook is present in `{houdini_prefs}/scripts/123.py`. Re-run `python install.py` if needed.
- **Module not found**: Make sure `pip install -e .` was run in the repo directory and `houdini-mcp` is on your PATH.
- **Timeout errors**: Try simplifying requests or breaking them into smaller steps.

## Limitations & Security

- The `execute_houdini_code` tool runs arbitrary Python code in Houdini. Use with caution and always save your work.
- Complex operations may need to be broken into smaller steps.
- The addon listens only on `localhost` — not exposed to the network.

## Contributing

Contributions are welcome! See [DEVELOPERS.md](DEVELOPERS.md) for the developer guide.

## Disclaimer

This is a third-party integration and is not made by SideFX.
