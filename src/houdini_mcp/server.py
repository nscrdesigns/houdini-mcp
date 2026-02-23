from mcp.server.fastmcp import FastMCP, Context, Image
import socket
import json
import asyncio
import logging
import os
import sys
import platform
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HoudiniMCPServer")

@dataclass
class HoudiniConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Houdini addon socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Houdini at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Houdini: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Houdini addon"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Houdini: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Socket timeout
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        # If we get an empty chunk, the connection might be closed
                        if not chunks:  # If we haven't received anything yet, this is an error
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        # If we get here, it parsed successfully
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    # If we hit a timeout during receiving, break the loop and try to use what we have
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise  # Re-raise to be handled by the caller
        except socket.timeout:
            logger.warning("Socket timeout during chunked receive")
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        # Try to use what we have
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                # Try to parse what we have
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                # If we can't parse it, it's incomplete
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Houdini and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Houdini")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        try:
            # Log the command being sent
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # Set a timeout for receiving
            self.sock.settimeout(15.0)
            
            # Receive the response using the improved receive_full_response method
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Houdini error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Houdini"))
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Houdini")
            self.sock = None
            raise Exception("Timeout waiting for Houdini response - try simplifying your request")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Houdini lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Houdini: {str(e)}")
            # Try to log what was received
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            raise Exception(f"Invalid response from Houdini: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Houdini: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Houdini: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        # Log startup
        logger.info("HoudiniMCP server starting up")
        
        # Try to connect to Houdini on startup
        try:
            houdini = get_houdini_connection()
            logger.info("Successfully connected to Houdini on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Houdini on startup: {str(e)}")
            logger.warning("Make sure the Houdini addon is running before using Houdini resources or tools")
        
        # Return an empty context - we're using the global connection
        yield {}
    finally:
        # Clean up the global connection on shutdown
        global _houdini_connection
        if _houdini_connection:
            logger.info("Disconnecting from Houdini on shutdown")
            _houdini_connection.disconnect()
            _houdini_connection = None
        logger.info("HoudiniMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "HoudiniMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_houdini_connection = None
_target_port = None  # Explicitly selected port (via connect_to_houdini)

DEFAULT_PORT = 9877  # Backward-compat fallback


def _get_port_file_dir():
    """Get the platform-appropriate directory for instance port files."""
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'HoudiniMCP', 'instances')
    else:
        base = os.environ.get('XDG_DATA_HOME',
                              os.path.join(os.path.expanduser('~'), '.local', 'share'))
        return os.path.join(base, 'houdinimcp', 'instances')


def _is_pid_alive(pid):
    """Check if a process with the given PID is still running."""
    if sys.platform == 'win32':
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _discover_instances():
    """Scan port file directory and return list of live Houdini instances.

    Each entry is a dict with port, pid, hip_file, etc.
    Returns list sorted by started_at descending (newest first).
    Cleans up stale port files as a side effect.
    """
    port_dir = _get_port_file_dir()
    if not os.path.isdir(port_dir):
        return []

    instances = []
    for fname in os.listdir(port_dir):
        if not fname.startswith('houdini_') or not fname.endswith('.json'):
            continue
        fpath = os.path.join(port_dir, fname)
        try:
            with open(fpath, 'r') as f:
                info = json.load(f)
            pid = info.get('pid')
            if pid and not _is_pid_alive(pid):
                # Stale — clean up
                try:
                    os.remove(fpath)
                    logger.info(f"Cleaned stale port file: {fname}")
                except Exception:
                    pass
                continue
            instances.append(info)
        except Exception:
            continue

    # Sort newest first
    instances.sort(key=lambda x: x.get('started_at', ''), reverse=True)
    return instances


def get_houdini_connection():
    """Get or create a persistent Houdini connection.

    Priority:
    1. Reuse existing healthy connection.
    2. Connect to _target_port if explicitly set (via connect_to_houdini tool).
    3. Discover instances via port files and connect to the most recent.
    4. Fallback to DEFAULT_PORT (backward compat with older addon).
    """
    global _houdini_connection, _target_port

    # If we have an existing connection, check if it's still valid
    if _houdini_connection is not None:
        try:
            _houdini_connection.send_command("get_scene_info")
            return _houdini_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _houdini_connection.disconnect()
            except Exception:
                pass
            _houdini_connection = None

    # Determine which port to connect to
    port = None

    if _target_port is not None:
        port = _target_port
        logger.info(f"Using explicitly targeted port {port}")
    else:
        instances = _discover_instances()
        if instances:
            port = instances[0]['port']
            if len(instances) > 1:
                logger.info(
                    f"Found {len(instances)} Houdini instances. "
                    f"Connecting to most recent on port {port}. "
                    f"Use list_houdini_instances / connect_to_houdini to switch."
                )
            else:
                logger.info(f"Discovered Houdini instance on port {port}")

    if port is None:
        port = DEFAULT_PORT
        logger.info(f"No port files found, falling back to default port {port}")

    _houdini_connection = HoudiniConnection(host="localhost", port=port)
    if not _houdini_connection.connect():
        logger.error(f"Failed to connect to Houdini on port {port}")
        _houdini_connection = None
        raise Exception(
            "Could not connect to Houdini. Make sure the Houdini addon is running."
        )
    logger.info(f"Created new persistent connection to Houdini on port {port}")
    return _houdini_connection


#
# MCP Tool Definitions
#

@mcp.tool()
def get_scene_info(ctx: Context) -> str:
    """Get detailed information about the current Houdini scene"""
    try:
        houdini = get_houdini_connection()
        result = houdini.send_command("get_scene_info")
        
        # Format the information in a readable way
        formatted = json.dumps(result, indent=2)
        return formatted
    except Exception as e:
        logger.error(f"Error getting scene info from Houdini: {str(e)}")
        return f"Error getting scene info: {str(e)}"

@mcp.tool()
def get_node_info(ctx: Context, path: str) -> str:
    """
    Get detailed information about a specific node in the Houdini scene.
    
    Parameters:
    - path: Full path to the node (e.g., "/obj/geo1")
    """
    try:
        houdini = get_houdini_connection()
        result = houdini.send_command("get_node_info", {"path": path})
        
        # Format the information in a readable way
        formatted = json.dumps(result, indent=2)
        return formatted
    except Exception as e:
        logger.error(f"Error getting node info from Houdini: {str(e)}")
        return f"Error getting node info: {str(e)}"

@mcp.tool()
def create_geometry(
    ctx: Context,
    geo_type: str = "box",
    parent_path: str = "/obj",
    name: Optional[str] = None,
    position: Optional[List[float]] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create a new geometry object in Houdini.
    
    Parameters:
    - geo_type: Type of geometry (box, sphere, torus, grid, tube, circle, curve, line, platonic, cylinder)
    - parent_path: Path to the parent node (default: /obj)
    - name: Optional name for the geometry
    - position: Optional [x, y] position in the network
    - parameters: Optional dictionary of parameter values
    
    Returns:
    Information about the created geometry.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "geo_type": geo_type,
            "parent_path": parent_path
        }
        
        if name:
            params["name"] = name
        if position:
            params["position"] = position
        if parameters:
            params["parameters"] = parameters
            
        result = houdini.send_command("create_geometry", params)
        
        if "error" in result:
            return f"Error creating geometry: {result['error']}"
        
        # Return a user-friendly message
        return f"Created {geo_type} geometry at {result['path']}"
    except Exception as e:
        logger.error(f"Error creating geometry: {str(e)}")
        return f"Error creating geometry: {str(e)}"

@mcp.tool()
def create_node(
    ctx: Context,
    node_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    position: Optional[List[float]] = None
) -> str:
    """
    Create a new node in the Houdini network.
    
    Parameters:
    - node_type: Type of node to create
    - parent_path: Path to the parent node (default: /obj)
    - name: Optional name for the node
    - position: Optional [x, y] position in the network
    
    Returns:
    Information about the created node.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "node_type": node_type,
            "parent_path": parent_path
        }
        
        if name:
            params["node_name"] = name
        if position:
            params["position"] = position
            
        result = houdini.send_command("create_node", params)
        
        if "error" in result:
            return f"Error creating node: {result['error']}"
        
        # Return a user-friendly message
        return f"Created {node_type} node at {result['path']}"
    except Exception as e:
        logger.error(f"Error creating node: {str(e)}")
        return f"Error creating node: {str(e)}"

@mcp.tool()
def modify_node(
    ctx: Context,
    path: str,
    position: Optional[List[float]] = None,
    color: Optional[List[float]] = None,
    name: Optional[str] = None,
    bypass: Optional[bool] = None,
    display: Optional[bool] = None
) -> str:
    """
    Modify an existing node in Houdini.
    
    Parameters:
    - path: Path to the node to modify
    - position: Optional [x, y] position in the network
    - color: Optional [r, g, b] color values (0.0-1.0)
    - name: Optional new name for the node
    - bypass: Optional boolean to set bypass state
    - display: Optional boolean to set display flag
    
    Returns:
    Information about the modified node.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {"path": path}
        
        if position is not None:
            params["position"] = position
        if color is not None:
            params["color"] = color
        if name is not None:
            params["name"] = name
        if bypass is not None:
            params["bypass"] = bypass
        if display is not None:
            params["display"] = display
            
        result = houdini.send_command("modify_node", params)
        
        if "error" in result:
            return f"Error modifying node: {result['error']}"
        
        # Return a user-friendly message
        changes = []
        if position is not None:
            changes.append("position")
        if color is not None:
            changes.append("color")
        if name is not None:
            changes.append("name")
        if bypass is not None:
            changes.append("bypass state")
        if display is not None:
            changes.append("display flag")
            
        changes_str = ", ".join(changes)
        return f"Modified {changes_str} for node at {result['path']}"
    except Exception as e:
        logger.error(f"Error modifying node: {str(e)}")
        return f"Error modifying node: {str(e)}"

@mcp.tool()
def delete_node(ctx: Context, path: str) -> str:
    """
    Delete a node from the Houdini network.
    
    Parameters:
    - path: Path to the node to delete
    
    Returns:
    Confirmation of the deletion.
    """
    try:
        houdini = get_houdini_connection()
        
        result = houdini.send_command("delete_node", {"path": path})
        
        if "error" in result:
            return f"Error deleting node: {result['error']}"
        
        # Return a user-friendly message
        return f"Deleted node: {result['name']} at {result['path']}"
    except Exception as e:
        logger.error(f"Error deleting node: {str(e)}")
        return f"Error deleting node: {str(e)}"

@mcp.tool()
def set_parameter(
    ctx: Context,
    node_path: str,
    parameter_name: str,
    value: Any
) -> str:
    """
    Set a parameter value on a Houdini node.
    
    Parameters:
    - node_path: Path to the node
    - parameter_name: Name of the parameter to set
    - value: Value to set (can be a number, string, boolean, or list for vector parameters)
    
    Returns:
    Confirmation of the parameter change.
    """
    try:
        houdini = get_houdini_connection()
        
        result = houdini.send_command("set_parameter", {
            "node_path": node_path,
            "parameter_name": parameter_name,
            "value": value
        })
        
        if "error" in result:
            return f"Error setting parameter: {result['error']}"
        
        # Return a user-friendly message
        return f"Set parameter {parameter_name} on {node_path} to {value}"
    except Exception as e:
        logger.error(f"Error setting parameter: {str(e)}")
        return f"Error setting parameter: {str(e)}"

@mcp.tool()
def connect_nodes(
    ctx: Context,
    from_path: str,
    to_path: str,
    from_output: int = 0,
    to_input: int = 0
) -> str:
    """
    Connect two nodes in the Houdini network.
    
    Parameters:
    - from_path: Path to the source node
    - to_path: Path to the destination node
    - from_output: Output index on the source node (default: 0)
    - to_input: Input index on the destination node (default: 0)
    
    Returns:
    Confirmation of the connection.
    """
    try:
        houdini = get_houdini_connection()
        
        result = houdini.send_command("connect_nodes", {
            "from_path": from_path,
            "to_path": to_path,
            "from_output": from_output,
            "to_input": to_input
        })
        
        if "error" in result:
            return f"Error connecting nodes: {result['error']}"
        
        # Return a user-friendly message
        from_name = from_path.split("/")[-1]
        to_name = to_path.split("/")[-1]
        return f"Connected {from_name} (output {from_output}) to {to_name} (input {to_input})"
    except Exception as e:
        logger.error(f"Error connecting nodes: {str(e)}")
        return f"Error connecting nodes: {str(e)}"

@mcp.tool()
def set_material(
    ctx: Context,
    node_path: str,
    material_type: str = "principledshader",
    material_name: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create and apply a material to a node in Houdini.
    
    Parameters:
    - node_path: Path to the node to apply the material to
    - material_type: Type of material to create (default: principledshader)
    - material_name: Optional name for the material
    - parameters: Optional dictionary of material parameter values
    
    Returns:
    Confirmation of the material application.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "node_path": node_path,
            "material_type": material_type
        }
        
        if material_name:
            params["material_name"] = material_name
        if parameters:
            params["parameters"] = parameters
            
        result = houdini.send_command("set_material", params)
        
        if "error" in result:
            return f"Error setting material: {result['error']}"
        
        # Return a user-friendly message
        return f"Applied {material_type} material ({result['material_name']}) to {node_path}"
    except Exception as e:
        logger.error(f"Error setting material: {str(e)}")
        return f"Error setting material: {str(e)}"

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str) -> str:
    """
    Execute arbitrary Python code in Houdini.

    The code runs in a namespace with `hou` pre-imported. Print statements
    are captured and returned. Assign to `__result__` for an explicit return
    value (must be JSON-serializable).

    Parameters:
    - code: The Python code to execute

    Returns:
    Captured stdout output and/or __result__ value, or confirmation.
    """
    try:
        houdini = get_houdini_connection()

        result = houdini.send_command("execute_code", {"code": code})

        if "error" in result:
            return f"Error executing code: {result['error']}"

        parts = ["Code executed successfully in Houdini."]
        if result.get("output"):
            parts.append(f"Output:\n{result['output']}")
        if result.get("result") is not None:
            parts.append(f"Result: {json.dumps(result['result'], indent=2)}")
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"Error executing code: {str(e)}")
        return f"Error executing code: {str(e)}"

@mcp.tool()
def create_camera(
    ctx: Context,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    position: Optional[List[float]] = None,
    look_at: Optional[List[float]] = None
) -> str:
    """
    Create a camera in Houdini.
    
    Parameters:
    - parent_path: Path to the parent node (default: /obj)
    - name: Optional name for the camera
    - position: Optional [x, y, z] position for the camera
    - look_at: Optional [x, y, z] look-at target for the camera
    
    Returns:
    Information about the created camera.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {"parent_path": parent_path}
        
        if name:
            params["name"] = name
        if position:
            params["position"] = position
        if look_at:
            params["look_at"] = look_at
            
        result = houdini.send_command("create_camera", params)
        
        if "error" in result:
            return f"Error creating camera: {result['error']}"
        
        # Return a user-friendly message
        msg = f"Created camera at {result['path']}"
        if position:
            msg += f" at position {position}"
        if look_at:
            msg += f", looking at {look_at}"
        return msg
    except Exception as e:
        logger.error(f"Error creating camera: {str(e)}")
        return f"Error creating camera: {str(e)}"

@mcp.tool()
def create_light(
    ctx: Context,
    light_type: str = "point",
    parent_path: str = "/obj",
    name: Optional[str] = None,
    position: Optional[List[float]] = None,
    parameters: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create a light in Houdini.
    
    Parameters:
    - light_type: Type of light (point, spot, directional, area, environment)
    - parent_path: Path to the parent node (default: /obj)
    - name: Optional name for the light
    - position: Optional [x, y, z] position for the light
    - parameters: Optional dictionary of light parameter values
    
    Returns:
    Information about the created light.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "light_type": light_type,
            "parent_path": parent_path
        }
        
        if name:
            params["name"] = name
        if position:
            params["position"] = position
        if parameters:
            params["parameters"] = parameters
            
        result = houdini.send_command("create_light", params)
        
        if "error" in result:
            return f"Error creating light: {result['error']}"
        
        # Return a user-friendly message
        return f"Created {light_type} light at {result['path']}"
    except Exception as e:
        logger.error(f"Error creating light: {str(e)}")
        return f"Error creating light: {str(e)}"

@mcp.tool()
def create_simulation(
    ctx: Context,
    sim_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    position: Optional[List[float]] = None
) -> str:
    """
    Create a simulation network in Houdini.
    
    Parameters:
    - sim_type: Type of simulation (pyro, fluid, cloth, rigid, wire, grains, flip, particles, crowd)
    - parent_path: Path to the parent node (default: /obj)
    - name: Optional name for the simulation network
    - position: Optional [x, y] position in the network
    
    Returns:
    Information about the created simulation network.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "sim_type": sim_type,
            "parent_path": parent_path
        }
        
        if name:
            params["name"] = name
        if position:
            params["position"] = position
            
        result = houdini.send_command("create_sim", params)
        
        if "error" in result:
            return f"Error creating simulation: {result['error']}"
        
        # Return a user-friendly message
        return f"Created {sim_type} simulation network at {result['path']}"
    except Exception as e:
        logger.error(f"Error creating simulation: {str(e)}")
        return f"Error creating simulation: {str(e)}"

@mcp.tool()
def run_simulation(
    ctx: Context,
    node_path: str,
    start_frame: int = 1,
    end_frame: int = 10,
    save_to_disk: bool = False
) -> str:
    """
    Run a simulation for a node in Houdini.
    
    Parameters:
    - node_path: Path to the simulation node
    - start_frame: Start frame for the simulation (default: 1)
    - end_frame: End frame for the simulation (default: 10)
    - save_to_disk: Whether to save the simulation cache to disk (default: False)
    
    Returns:
    Information about the simulation run.
    """
    try:
        houdini = get_houdini_connection()
        
        result = houdini.send_command("run_simulation", {
            "node_path": node_path,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "save_to_disk": save_to_disk
        })
        
        if "error" in result:
            return f"Error running simulation: {result['error']}"
        
        # Return a user-friendly message
        msg = f"Ran simulation for {node_path} from frame {start_frame} to {end_frame}"
        if save_to_disk and "cache_path" in result:
            msg += f"\nSaved cache to: {result['cache_path']}"
        return msg
    except Exception as e:
        logger.error(f"Error running simulation: {str(e)}")
        return f"Error running simulation: {str(e)}"

@mcp.tool()
def render_scene(
    ctx: Context,
    output_path: Optional[str] = None,
    renderer: str = "mantra",
    resolution: Optional[List[int]] = None,
    camera_path: Optional[str] = None
) -> str:
    """
    Render the current Houdini scene.
    
    Parameters:
    - output_path: Optional path to save the rendered image
    - renderer: Renderer to use (mantra, karma, arnold, redshift, renderman)
    - resolution: Optional [width, height] resolution override
    - camera_path: Optional path to the camera to use for rendering
    
    Returns:
    Information about the render.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {"renderer": renderer}
        
        if output_path:
            params["output_path"] = output_path
        if resolution:
            params["resolution"] = resolution
        if camera_path:
            params["camera_path"] = camera_path
            
        result = houdini.send_command("render_scene", params)
        
        if "error" in result:
            return f"Error rendering scene: {result['error']}"
        
        # Return a user-friendly message
        msg = f"Rendered scene using {renderer}"
        if "file_path" in result:
            msg += f"\nSaved output to: {result['file_path']}"
        if "resolution" in result:
            msg += f"\nResolution: {result['resolution'][0]}x{result['resolution'][1]}"
        return msg
    except Exception as e:
        logger.error(f"Error rendering scene: {str(e)}")
        return f"Error rendering scene: {str(e)}"

@mcp.tool()
def export_fbx(
    ctx: Context,
    node_path: str,
    file_path: Optional[str] = None,
    animation: bool = False
) -> str:
    """
    Export a node to FBX format.
    
    Parameters:
    - node_path: Path to the node to export
    - file_path: Optional path to save the FBX file
    - animation: Whether to export animation (default: False)
    
    Returns:
    Information about the export.
    """
    try:
        houdini = get_houdini_connection()
        
        # Pass parameters to the Houdini command
        params = {
            "node_path": node_path,
            "animation": animation
        }
        
        if file_path:
            params["file_path"] = file_path
            
        result = houdini.send_command("export_fbx", params)
        
        if "error" in result:
            return f"Error exporting to FBX: {result['error']}"
        
        # Return a user-friendly message
        msg = f"Exported {node_path} to FBX"
        if "file_path" in result:
            msg += f"\nSaved to: {result['file_path']}"
        if animation:
            msg += "\nIncluded animation data"
        return msg
    except Exception as e:
        logger.error(f"Error exporting to FBX: {str(e)}")
        return f"Error exporting to FBX: {str(e)}"

@mcp.tool()
def layout_network(ctx: Context, path: str) -> str:
    """
    Auto-layout nodes in a Houdini network.

    Parameters:
    - path: Path to the network node (e.g., "/obj/geo1")

    Returns:
    Confirmation of the layout operation.
    """
    try:
        houdini = get_houdini_connection()
        result = houdini.send_command("layout_network", {"path": path})
        if "error" in result:
            return f"Error laying out network: {result['error']}"
        return f"Auto-laid out nodes in {result['path']}"
    except Exception as e:
        logger.error(f"Error laying out network: {str(e)}")
        return f"Error laying out network: {str(e)}"

@mcp.tool()
def create_subnet(
    ctx: Context,
    parent_path: str,
    name: Optional[str] = None,
    position: Optional[List[float]] = None,
    node_type: str = "subnet"
) -> str:
    """
    Create a subnet container node in Houdini.

    Parameters:
    - parent_path: Path to the parent node
    - name: Optional name for the subnet
    - position: Optional [x, y] position in the network
    - node_type: Node type to create (default: subnet)

    Returns:
    Information about the created subnet.
    """
    try:
        houdini = get_houdini_connection()
        params = {"parent_path": parent_path, "node_type": node_type}
        if name:
            params["name"] = name
        if position:
            params["position"] = position
        result = houdini.send_command("create_subnet", params)
        if "error" in result:
            return f"Error creating subnet: {result['error']}"
        return f"Created subnet at {result['path']}"
    except Exception as e:
        logger.error(f"Error creating subnet: {str(e)}")
        return f"Error creating subnet: {str(e)}"

@mcp.tool()
def create_digital_asset(
    ctx: Context,
    node_path: str,
    name: str,
    label: Optional[str] = None,
    save_path: Optional[str] = None
) -> str:
    """
    Create a Houdini Digital Asset (HDA) from an existing node.

    Parameters:
    - node_path: Path to the source node
    - name: Internal name for the asset
    - label: Optional human-readable label
    - save_path: Optional file path to save the HDA (default: $TEMP/<name>.hda)

    Returns:
    Information about the created HDA.
    """
    try:
        houdini = get_houdini_connection()
        params = {"node_path": node_path, "name": name}
        if label:
            params["label"] = label
        if save_path:
            params["save_path"] = save_path
        result = houdini.send_command("create_digital_asset", params)
        if "error" in result:
            return f"Error creating digital asset: {result['error']}"
        msg = f"Created HDA '{name}' at {result['path']}"
        if "hda_file" in result:
            msg += f"\nSaved to: {result['hda_file']}"
        return msg
    except Exception as e:
        logger.error(f"Error creating digital asset: {str(e)}")
        return f"Error creating digital asset: {str(e)}"

@mcp.tool()
def get_parameter_info(
    ctx: Context,
    node_path: str,
    parameter_name: Optional[str] = None
) -> str:
    """
    Get detailed parameter information for a Houdini node.

    Parameters:
    - node_path: Path to the node
    - parameter_name: Optional specific parameter name. If omitted, returns all parameters.

    Returns:
    JSON-formatted parameter details.
    """
    try:
        houdini = get_houdini_connection()
        params = {"node_path": node_path}
        if parameter_name:
            params["parameter_name"] = parameter_name
        result = houdini.send_command("get_parameter_info", params)
        if "error" in result:
            return f"Error getting parameter info: {result['error']}"
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting parameter info: {str(e)}")
        return f"Error getting parameter info: {str(e)}"

@mcp.tool()
def save_hip(ctx: Context, file_path: Optional[str] = None) -> str:
    """
    Save the current Houdini scene file.

    Parameters:
    - file_path: Optional path to save to. If omitted, saves to the current file.

    Returns:
    Confirmation with the saved file path.
    """
    try:
        houdini = get_houdini_connection()
        params = {}
        if file_path:
            params["file_path"] = file_path
        result = houdini.send_command("save_hip", params)
        if "error" in result:
            return f"Error saving scene: {result['error']}"
        return f"Saved scene to: {result['file_path']}"
    except Exception as e:
        logger.error(f"Error saving scene: {str(e)}")
        return f"Error saving scene: {str(e)}"

@mcp.tool()
def load_hip(ctx: Context, file_path: str) -> str:
    """
    Load a Houdini scene file. Automatically backs up unsaved changes.

    Parameters:
    - file_path: Path to the .hip file to load

    Returns:
    Confirmation with the loaded file info.
    """
    try:
        houdini = get_houdini_connection()
        result = houdini.send_command("load_hip", {"file_path": file_path})
        if "error" in result:
            return f"Error loading scene: {result['error']}"
        return f"Loaded scene: {result['name']} from {result['file_path']}"
    except Exception as e:
        logger.error(f"Error loading scene: {str(e)}")
        return f"Error loading scene: {str(e)}"

@mcp.tool()
def export_abc(
    ctx: Context,
    node_path: str,
    file_path: Optional[str] = None,
    animation: bool = False
) -> str:
    """
    Export a node to Alembic (.abc) format.

    Parameters:
    - node_path: Path to the node to export
    - file_path: Optional path for the output file
    - animation: Whether to export animation (default: False)

    Returns:
    Information about the export.
    """
    try:
        houdini = get_houdini_connection()
        params = {"node_path": node_path, "animation": animation}
        if file_path:
            params["file_path"] = file_path
        result = houdini.send_command("export_abc", params)
        if "error" in result:
            return f"Error exporting to Alembic: {result['error']}"
        msg = f"Exported {node_path} to Alembic"
        if "file_path" in result:
            msg += f"\nSaved to: {result['file_path']}"
        if animation:
            msg += "\nIncluded animation data"
        return msg
    except Exception as e:
        logger.error(f"Error exporting to Alembic: {str(e)}")
        return f"Error exporting to Alembic: {str(e)}"

@mcp.tool()
def export_usd(
    ctx: Context,
    node_path: str,
    file_path: Optional[str] = None,
    animation: bool = False
) -> str:
    """
    Export a node to USD format.

    Parameters:
    - node_path: Path to the node to export
    - file_path: Optional path for the output file
    - animation: Whether to export animation (default: False)

    Returns:
    Information about the export.
    """
    try:
        houdini = get_houdini_connection()
        params = {"node_path": node_path, "animation": animation}
        if file_path:
            params["file_path"] = file_path
        result = houdini.send_command("export_usd", params)
        if "error" in result:
            return f"Error exporting to USD: {result['error']}"
        msg = f"Exported {node_path} to USD"
        if "file_path" in result:
            msg += f"\nSaved to: {result['file_path']}"
        if animation:
            msg += "\nIncluded animation data"
        return msg
    except Exception as e:
        logger.error(f"Error exporting to USD: {str(e)}")
        return f"Error exporting to USD: {str(e)}"

@mcp.tool()
def render_cop(
    ctx: Context,
    node_path: str,
    output_path: Optional[str] = None,
    frame: Optional[int] = None
) -> str:
    """
    Render a COP (compositing) node output to an image file.

    Parameters:
    - node_path: Path to the COP node to render
    - output_path: Optional path to save the image (default: $HIP/mcp_cop_render.png)
    - frame: Optional frame number to render (default: current frame)

    Returns:
    Information about the rendered image including file path.
    """
    try:
        houdini = get_houdini_connection()

        params = {"node_path": node_path}

        if output_path:
            params["output_path"] = output_path
        if frame is not None:
            params["frame"] = frame

        result = houdini.send_command("render_cop", params)

        if "error" in result:
            return f"Error rendering COP: {result['error']}"

        msg = f"Rendered COP node {node_path}"
        if "file_path" in result:
            msg += f"\nSaved to: {result['file_path']}"
        return msg
    except Exception as e:
        logger.error(f"Error rendering COP: {str(e)}")
        return f"Error rendering COP: {str(e)}"

@mcp.tool()
def list_houdini_instances(ctx: Context) -> str:
    """
    List all running Houdini instances discovered via port files.

    Shows port, PID, hip file, Houdini version, and start time for each
    instance. The currently connected instance (if any) is marked with *.
    Use connect_to_houdini(port=XXXX) to switch between instances.

    Returns:
    A formatted list of discovered Houdini instances.
    """
    try:
        instances = _discover_instances()
        if not instances:
            return (
                "No Houdini instances discovered via port files.\n"
                "If the addon is running, it may be an older version without "
                "port file support. The MCP server will fall back to port 9877."
            )

        # Determine currently connected port
        connected_port = None
        if _houdini_connection and _houdini_connection.sock:
            connected_port = _houdini_connection.port

        lines = [f"Found {len(instances)} Houdini instance(s):\n"]
        for inst in instances:
            marker = " *" if inst.get('port') == connected_port else "  "
            lines.append(
                f"{marker} Port {inst['port']}  |  PID {inst.get('pid', '?')}  |  "
                f"{inst.get('hip_name', '?')}  |  "
                f"Houdini {inst.get('houdini_version', '?')}  |  "
                f"started {inst.get('started_at', '?')}"
            )

        if len(instances) > 1:
            lines.append(
                "\nUse connect_to_houdini(port=XXXX) to switch to a different instance."
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error listing instances: {str(e)}")
        return f"Error listing Houdini instances: {str(e)}"


@mcp.tool()
def connect_to_houdini(ctx: Context, port: int) -> str:
    """
    Switch the MCP server's connection to a specific Houdini instance.

    Parameters:
    - port: The port number of the Houdini instance to connect to.

    Use list_houdini_instances() first to see available instances.

    Returns:
    Scene info from the newly connected Houdini instance, confirming success.
    """
    global _houdini_connection, _target_port

    try:
        # Validate that the port corresponds to a known instance
        instances = _discover_instances()
        known_ports = {inst['port'] for inst in instances}

        if port not in known_ports:
            available = ", ".join(str(p) for p in sorted(known_ports)) if known_ports else "none"
            return (
                f"No Houdini instance found on port {port}.\n"
                f"Available ports: {available}"
            )

        # Disconnect current connection
        if _houdini_connection:
            try:
                _houdini_connection.disconnect()
            except Exception:
                pass
            _houdini_connection = None

        # Set target and connect
        _target_port = port
        houdini = get_houdini_connection()
        result = houdini.send_command("get_scene_info")

        return (
            f"Connected to Houdini on port {port}.\n"
            f"Scene: {result.get('name', '?')}  |  "
            f"Nodes: {result.get('node_count', '?')}  |  "
            f"Frame: {result.get('current_frame', '?')}"
        )
    except Exception as e:
        logger.error(f"Error connecting to Houdini on port {port}: {str(e)}")
        return f"Error connecting to port {port}: {str(e)}"


@mcp.tool()
def screenshot_viewport(
    ctx: Context,
    output_path: Optional[str] = None
) -> str:
    """
    Take a screenshot of the current Houdini viewport.

    Parameters:
    - output_path: Optional path to save the screenshot (default: $HIP/mcp_viewport_screenshot.png)

    Returns:
    Information about the screenshot including file path.
    """
    try:
        houdini = get_houdini_connection()

        params = {}
        if output_path:
            params["output_path"] = output_path

        result = houdini.send_command("screenshot_viewport", params)

        if "error" in result:
            return f"Error taking screenshot: {result['error']}"

        if result.get("success"):
            msg = f"Screenshot saved to: {result.get('file_path', 'unknown')}"
            return msg
        else:
            return f"Screenshot failed: {result.get('error', 'unknown error')}"
    except Exception as e:
        logger.error(f"Error taking screenshot: {str(e)}")
        return f"Error taking screenshot: {str(e)}"

@mcp.prompt()
def modeling_strategy() -> str:
    """Defines the preferred strategy for 3D modeling in Houdini"""
    return """When creating 3D content in Houdini, follow these guidelines:

    1. First use get_scene_info() to understand the current scene structure

    2. For basic modeling:
       - Use create_geometry() with appropriate geo_type for primitive shapes
       - For complex models, build node networks by connecting multiple nodes
       - Use create_subnet() to organize nodes into containers
       - Use layout_network() to auto-arrange nodes neatly
       - Remember Houdini is procedural, so focus on building node chains rather than direct modeling

    3. For materials:
       - Use set_material() with appropriate material_type
       - Common material types: principledshader, phong, constant

    4. For scene setup:
       - Create lights using create_light() with appropriate light types
       - Set up cameras with create_camera()
       - Position elements using modify_node() or set_parameter()
       - Use get_parameter_info() to inspect parameter details on any node

    5. For simulations:
       - Create simulation networks with create_simulation()
       - Configure using set_parameter()
       - Run simulations with run_simulation()

    6. For rendering:
       - Use render_scene() to create final images
       - Use render_cop() to render COP/compositing node output to image files
       - Typically use Mantra (the default) or Karma renderers

    7. For data export:
       - Use export_fbx() for FBX exchange with other 3D applications
       - Use export_abc() for Alembic format export
       - Use export_usd() for USD format export

    8. For scene management:
       - Use save_hip() to save the current scene
       - Use load_hip() to load a scene file
       - Use create_digital_asset() to package nodes into reusable HDAs

    9. For multi-instance workflows:
       - Use list_houdini_instances() to see all running Houdini sessions
       - Use connect_to_houdini(port=XXXX) to switch between instances
       - The server auto-discovers instances via port files and connects to the most recent

    Remember that Houdini is node-based and procedural, so focus on building networks rather than direct manipulation of geometry.
    """

# Main execution function
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
