import sys
import hou

# Add the path to houdinimcp_addon.py
sys.path.append(r"D:\Coding\houdini-mcp")

try:
    import houdinimcp_addon
    server = houdinimcp_addon.init_houdinimcp()
    
    if server:
        print("HoudiniMCP server started successfully!")
    else:
        print("Failed to start HoudiniMCP server.")
except Exception as e:
    print(f"Error starting HoudiniMCP: {str(e)}")