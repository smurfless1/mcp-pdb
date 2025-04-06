from mcp.server.fastmcp import FastMCP
import subprocess
import threading
import queue
import os
import time
import atexit
import shutil
import shlex

# Initialize FastMCP server
mcp = FastMCP("mcp-pdb")

# Global variables to track the pdb process
pdb_process = None
pdb_output_queue = queue.Queue()
pdb_running = False
current_file = None
breakpoints = {}  # Dictionary to track breakpoints

def read_pdb_output(process, queue):
    """Read output from the pdb process and put it in the queue."""
    while True:
        line = process.stdout.readline()
        if not line:
            break
        queue.put(line.decode('utf-8').rstrip())
    process.stdout.close()

def get_pdb_output(timeout=0.5):
    """Get accumulated output from the pdb process."""
    output = []
    try:
        while True:
            line = pdb_output_queue.get(timeout=timeout)
            output.append(line)
    except queue.Empty:
        pass
    return '\n'.join(output)

def send_to_pdb(command):
    """Send a command to the pdb process."""
    global pdb_process
    if pdb_process and pdb_process.poll() is None:
        pdb_process.stdin.write((command + '\n').encode('utf-8'))
        pdb_process.stdin.flush()
        # Wait a bit for the command to be processed
        time.sleep(0.1)
        return get_pdb_output()
    return "No active pdb process."

@mcp.tool()
def start_debug(file_path: str, use_pytest: bool = False, args: str = "") -> str:
    """Start a debugging session on a Python file.

    Args:
        file_path: Path to the Python file to debug
        use_pytest: If True, run pytest with --pdb option
        args: Additional arguments to pass to the Python script or pytest
    """
    global pdb_process, pdb_running, current_file, pdb_output_queue, breakpoints

    if pdb_running:
        return "A debugging session is already running. Use restart_debug to restart it."

    current_file = file_path
    # Store breakpoints for the file rather than resetting all
    if file_path not in breakpoints:
        breakpoints[file_path] = {}

    # Clear the output queue
    while not pdb_output_queue.empty():
        pdb_output_queue.get()

    try:
        # Check if uv is installed and if the target project uses it
        use_uv = False
        uv_path = shutil.which("uv")
        target_dir = os.path.dirname(os.path.abspath(file_path))

        # Look for pyproject.toml in the target directory or its parents
        pyproject_path = None
        current_dir = target_dir
        while current_dir and current_dir != os.path.dirname(current_dir):
            possible_path = os.path.join(current_dir, "pyproject.toml")
            if os.path.exists(possible_path):
                pyproject_path = possible_path
                break
            current_dir = os.path.dirname(current_dir)

        # If we found pyproject.toml and uv is available, check if it's a uv project
        if pyproject_path and uv_path:
            try:
                # Get the project root directory (where pyproject.toml is)
                project_root = os.path.dirname(pyproject_path)

                # Check for uv.lock file as a reliable indicator of a uv project
                if os.path.exists(os.path.join(project_root, "uv.lock")):
                    use_uv = True
                else:
                    # Fallback: run uv tree in the project root
                    result = subprocess.run(
                        ["uv", "tree"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                        cwd=project_root
                    )
                    use_uv = result.returncode == 0 and "No `pyproject.toml` found" not in result.stderr
            except Exception:
                use_uv = False

        # Determine working directory: project root or file's directory
        target_dir = os.path.dirname(os.path.abspath(file_path))
        if pyproject_path:
            target_dir = os.path.dirname(pyproject_path)

        # Build appropriate commands based on environment
        if use_pytest:
            if use_uv and uv_path:
                cmd = ["uv", "run", "pytest", "--pdb", file_path]
            else:
                cmd = ["pytest", "--pdb", file_path]
        else:
            if use_uv and uv_path:
                cmd = ["uv", "run", "python", "-m", "pdb", file_path]
            else:
                cmd = ["python", "-m", "pdb", file_path]

        # Add any additional arguments
        if args:
            cmd.extend(args.split())

        # Use the current environment
        env = os.environ.copy()

        # Launch the process in the target directory
        pdb_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            cwd=target_dir,
            env=env
        )

        # Start a thread to read the output
        output_thread = threading.Thread(
            target=read_pdb_output,
            args=(pdb_process, pdb_output_queue)
        )
        output_thread.daemon = True
        output_thread.start()

        pdb_running = True

        # Wait a bit for pdb to start and get initial output
        time.sleep(1.0)
        output = get_pdb_output()

        # Check if pdb started successfully
        if not output or ("Error" in output and "-> " not in output):
            pdb_running = False
            return f"Error starting pdb: {output}"

        # Set pdb_running to True because we have output with '-> ' which indicates
        # pdb is running, even if the prompt isn't visible
        pdb_running = True

        return f"Debugging session started for {file_path}\n\n{output}"
    except Exception as e:
        pdb_running = False
        return f"Error starting debugging session: {str(e)}"

@mcp.tool()
def send_pdb_command(command: str) -> str:
    """Send a command to the pdb debugger.

    Examples:
        "p x" to print the value of x.
        "b 42" to set a breakpoint at line 42 in the current file.
        "cl src/code.py:26" to clear the breakpoint at line 26 in the file src/code.py.
        "c" to continue execution until the next breakpoint.

    Args:
        command: The pdb command to execute (e.g., 'n', 'c', 'p x', etc.)
    """
    global pdb_running

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    try:
        # Check if the process is still running
        if pdb_process.poll() is not None:
            pdb_running = False
            return "The debugging session has ended. Use start_debug to start a new session."

        response = send_to_pdb(command)

        # Check if the process ended after the command
        if pdb_process.poll() is not None:
            pdb_running = False
            return f"Command output:\n{response}\n\nThe debugging session has ended."

        # Add current line context for navigation commands
        if command in ['n', 's', 'c', 'r', 'until']:
            line_context = send_to_pdb("l .")
            response += f"\n\nCurrent line context:\n{line_context}"

        return f"Command output:\n{response}"
    except Exception as e:
        return f"Error sending command: {str(e)}"

@mcp.tool()
def set_breakpoint(file_path: str, line_number: int) -> str:
    """Set a breakpoint at a specific line in a file.

    Args:
        file_path: Path to the file
        line_number: Line number for the breakpoint
    """
    global breakpoints

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # Initialize file in breakpoints dict if it doesn't exist
    if file_path not in breakpoints:
        breakpoints[file_path] = {}

    # Check if breakpoint already exists
    if line_number in breakpoints[file_path]:
        return f"Breakpoint already exists at {file_path}:{line_number}"

    command = f"b {file_path}:{line_number}"
    response = send_to_pdb(command)

    if "Error" not in response:
        breakpoints[file_path][line_number] = command

    return f"Breakpoint result:\n{response}"

@mcp.tool()
def clear_breakpoint(file_path: str, line_number: int) -> str:
    """Clear a breakpoint at a specific line in a file.

    Args:
        file_path: Path to the file
        line_number: Line number for the breakpoint
    """
    global breakpoints

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # Check if file and line number exist in breakpoints
    if file_path not in breakpoints or line_number not in breakpoints[file_path]:
        return f"No breakpoint exists at {file_path}:{line_number}"

    command = f"cl {file_path}:{line_number}"
    response = send_to_pdb(command)

    if "Error" not in response:
        del breakpoints[file_path][line_number]

    return f"Clear breakpoint result:\n{response}"

@mcp.tool()
def list_breakpoints() -> str:
    """List all currently set breakpoints."""
    global breakpoints

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    response = send_to_pdb("b")

    # Format our tracked breakpoints
    tracked_bps = []
    for file_path, lines in breakpoints.items():
        for line_num in lines:
            tracked_bps.append(f"{file_path}:{line_num}")

    return f"Current breakpoints:\n{response}\n\nTracked breakpoints:\n{tracked_bps}"

@mcp.tool()
def restart_debug() -> str:
    """Restart the current debugging session."""
    global pdb_process, pdb_running

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # Store current file
    file_to_debug = current_file

    # End the current session
    if pdb_process and pdb_process.poll() is None:
        pdb_process.terminate()
        pdb_process.wait()

    # Clear the output queue
    while not pdb_output_queue.empty():
        pdb_output_queue.get()

    pdb_running = False

    # Start a new session
    start_result = start_debug(file_to_debug)

    # Restore breakpoints for the current file
    if file_to_debug in breakpoints:
        for line_num, bp_command in breakpoints[file_to_debug].items():
            send_to_pdb(bp_command)

    return f"Debugging session restarted:\n{start_result}"

@mcp.tool()
def examine_variable(variable_name: str) -> str:
    """Examine a variable's properties and values using pdb.

    Args:
        variable_name: Name of the variable to examine
    """
    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # First get basic info with 'p'
    basic_info = send_to_pdb(f"p {variable_name}")

    # Then try to get more detailed info with 'dir' for objects
    dir_info = send_to_pdb(f"dir({variable_name})")

    # Get type info
    type_info = send_to_pdb(f"type({variable_name})")

    return f"Variable examination:\n\nValue: {basic_info}\n\nType: {type_info}\n\nProperties/Methods: {dir_info}"

@mcp.tool()
def get_debug_status() -> str:
    """Get the current status of the debugging session."""
    global pdb_running, current_file

    if not pdb_running:
        return "No active debugging session."

    if pdb_process and pdb_process.poll() is not None:
        pdb_running = False
        return "The debugging session has ended."

    # Format breakpoints for better readability
    bp_list = []
    for file_path, lines in breakpoints.items():
        for line_num in lines:
            bp_list.append(f"{file_path}:{line_num}")

    status = {
        "running": pdb_running,
        "current_file": current_file,
        "breakpoints": bp_list,
        "process_id": pdb_process.pid if pdb_process else None
    }

    return f"Debug session status:\n{status}"

@mcp.tool()
def end_debug() -> str:
    """End the current debugging session."""
    global pdb_process, pdb_running

    if not pdb_running:
        return "No active debugging session."

    if pdb_process and pdb_process.poll() is None:
        pdb_process.terminate()
        try:
            pdb_process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pdb_process.kill()

    pdb_running = False
    return "Debugging session ended."

def cleanup():
    """Clean up resources when the server exits."""
    global pdb_process
    if pdb_process and pdb_process.poll() is None:
        pdb_process.terminate()
        try:
            pdb_process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pdb_process.kill()

atexit.register(cleanup)

def main():
    # Initialize and run the server
    mcp.run()
