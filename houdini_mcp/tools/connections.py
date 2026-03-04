"""Node connection (wiring) tools — connect, disconnect, list."""

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain


@mcp.tool()
def connect_nodes(
    from_path: str,
    from_output: int,
    to_path: str,
    to_input: int,
) -> str:
    """Connect two nodes: wire an output of one node to an input of another.

    Args:
        from_path: Path of the source node.
        from_output: Output index on the source node (0-based).
        to_path: Path of the destination node.
        to_input: Input index on the destination node (0-based).
    """
    hou = houdini.hou
    from_node = hou.node(from_path)
    to_node = hou.node(to_path)
    if from_node is None:
        raise ValueError(f"Source node not found: {from_path}")
    if to_node is None:
        raise ValueError(f"Destination node not found: {to_path}")

    to_node.setInput(to_input, from_node, from_output)
    return f"Connected {from_path}[{from_output}] -> {to_path}[{to_input}]"


@mcp.tool()
def disconnect_nodes(to_path: str, to_input: int) -> str:
    """Disconnect an input on a node.

    Args:
        to_path: Path of the node whose input to disconnect.
        to_input: Input index to disconnect (0-based).
    """
    hou = houdini.hou
    to_node = hou.node(to_path)
    if to_node is None:
        raise ValueError(f"Node not found: {to_path}")

    to_node.setInput(to_input, None)
    return f"Disconnected input {to_input} on {to_path}"


@mcp.tool()
def get_connections(path: str) -> dict:
    """Get all input and output connections for a node.

    Args:
        path: Full path of the node.

    Returns:
        Dict with 'inputs' and 'outputs' lists.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    inputs = []
    for i, inp in enumerate(node.inputs()):
        if inp is not None:
            inputs.append({
                "input_index": i,
                "input_name": obtain(node.inputNames()[i]) if i < len(node.inputNames()) else str(i),
                "connected_from": obtain(inp.path()),
            })

    outputs = []
    for conn in node.outputs():
        outputs.append({
            "connected_to": obtain(conn.path()),
        })

    return {
        "node": path,
        "inputs": inputs,
        "outputs": outputs,
    }
