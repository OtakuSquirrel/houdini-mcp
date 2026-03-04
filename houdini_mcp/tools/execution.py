"""Execution tools — run Python code, cook nodes, get errors."""

from __future__ import annotations

import io

from houdini_mcp.server import mcp, houdini
from houdini_mcp.utils import obtain, obtain_list


@mcp.tool()
def execute_python(code: str) -> dict:
    """Execute Python code inside the running Houdini process.

    The code has access to the full `hou` module and Houdini environment.
    Use this for operations not covered by other tools, or for complex
    multi-step scripting.

    Args:
        code: Python code to execute. The `hou` module is available.

    Returns:
        Dict with stdout output, return value (if the last line is an expression),
        and any errors.
    """
    conn = houdini.conn
    hou = houdini.hou

    # Execute code remotely via RPyC
    try:
        # Use RPyC's execute to run code in Houdini's Python environment
        result = conn.modules.builtins.eval(
            "exec(compile(__code__, '<mcp>', 'exec'), {'hou': __import__('hou')})",
        ) if False else None  # placeholder

        # Actually use rpyc's teleport/execute approach
        # We create a remote function and call it
        remote_exec = conn.modules.builtins.exec
        remote_eval = conn.modules.builtins.eval

        # Capture stdout
        remote_io = conn.modules.io
        remote_sys = conn.modules.sys

        old_stdout = remote_sys.stdout
        captured = remote_io.StringIO()
        remote_sys.stdout = captured

        error = None
        return_value = None

        try:
            # Build a namespace with hou available
            ns = conn.modules.builtins.dict()
            ns["hou"] = conn.modules.hou

            # Try to exec the whole code
            remote_exec(code, ns)

            # Try evaluating the last line as an expression for a return value
            lines = code.strip().split("\n")
            if lines:
                last_line = lines[-1].strip()
                if last_line and not last_line.startswith(("import ", "from ", "def ", "class ", "if ", "for ", "while ", "with ", "try:", "except", "#")):
                    try:
                        return_value = obtain(remote_eval(last_line, ns))
                    except Exception:
                        pass
        except Exception as e:
            error = str(e)
        finally:
            remote_sys.stdout = old_stdout

        stdout_text = obtain(captured.getvalue())

        result = {"stdout": stdout_text}
        if return_value is not None:
            result["return_value"] = return_value
        if error:
            result["error"] = error

        return result

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def cook_node(path: str) -> dict:
    """Force cook a node and return its cook status.

    Args:
        path: Full path of the node to cook.

    Returns:
        Dict with cook result, timing, and any errors.
    """
    hou = houdini.hou
    node = hou.node(path)
    if node is None:
        raise ValueError(f"Node not found: {path}")

    node.cook(force=True)

    errors = obtain(node.errors())
    warnings = obtain(node.warnings())

    result = {
        "node": path,
        "cooked": True,
    }

    cook_count = None
    try:
        cook_count = obtain(node.cookCount())
    except Exception:
        pass
    if cook_count is not None:
        result["cook_count"] = cook_count

    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings

    return result


@mcp.tool()
def get_node_errors(path: str | None = None) -> list[dict]:
    """Get errors and warnings from nodes.

    Args:
        path: Node path to check. If None, checks all nodes for errors.

    Returns:
        List of dicts with node path, errors, and warnings.
    """
    hou = houdini.hou

    if path is not None:
        node = hou.node(path)
        if node is None:
            raise ValueError(f"Node not found: {path}")
        nodes_to_check = [node]
    else:
        # Check all nodes recursively from /
        nodes_to_check = []
        root = hou.node("/")
        _collect_nodes_with_errors(root, nodes_to_check)

    results = []
    for node in nodes_to_check:
        errors = obtain(node.errors())
        warnings = obtain(node.warnings())
        if errors or warnings:
            entry = {"path": obtain(node.path())}
            if errors:
                entry["errors"] = errors
            if warnings:
                entry["warnings"] = warnings
            results.append(entry)

    if not results:
        return [{"message": "No errors or warnings found."}]
    return results


def _collect_nodes_with_errors(node, result_list, max_depth=5):
    """Recursively collect nodes that have errors."""
    if max_depth <= 0:
        return
    try:
        errors = obtain(node.errors())
        warnings = obtain(node.warnings())
        if errors or warnings:
            result_list.append(node)
        for child in node.children():
            _collect_nodes_with_errors(child, result_list, max_depth - 1)
    except Exception:
        pass
