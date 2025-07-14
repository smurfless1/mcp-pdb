import atexit
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("mcp-pdb")

# --- Global Variables ---
pdb_process = None
pdb_output_queue = queue.Queue()
pdb_running = False
current_file = None           # Absolute path of the file being debugged
current_project_root = None # Root directory of the project being debugged
current_args = ""             # Additional args passed to the script/pytest
current_use_pytest = False    # Flag indicating if pytest was used
breakpoints = {}              # Tracks breakpoints: {abs_file_path: {line_num: {command_str, bp_number}}}
output_thread = None          # Thread object for reading output

# --- Helper Functions ---

# Removed complex wrapper approach - using proper pytest debugging flags instead

def read_pdb_output(process, output_queue):
    """Read output from the pdb process and put it in the queue."""
    try:
        # Use iter() with readline to avoid blocking readline() indefinitely
        # if the process exits unexpectedly or stdout closes.
        for line_bytes in iter(process.stdout.readline, b''):
            output_queue.put(line_bytes.decode('utf-8', errors='replace').rstrip())
    except ValueError:
        # Handle ValueError if stdout is closed prematurely (e.g., process killed)
        print("PDB output reader: ValueError (stdout likely closed).", file=sys.stderr)
    except Exception as e:
        print(f"PDB output reader: Unexpected error: {e}", file=sys.stderr)
        # Optionally log traceback here if needed
    finally:
        # Ensure stdout is closed if loop finishes normally or breaks
        if process and process.stdout and not process.stdout.closed:
             try:
                 process.stdout.close()
             except Exception as e:
                 print(f"PDB output reader: Error closing stdout: {e}", file=sys.stderr)
        print("PDB output reader thread finished.", file=sys.stderr)


def get_pdb_output(timeout=0.5):
    """Get accumulated output from the pdb process queue."""
    output = []
    start_time = time.monotonic()
    while True:
        try:
            # Calculate remaining time
            remaining_time = timeout - (time.monotonic() - start_time)
            if remaining_time <= 0:
                break
            line = pdb_output_queue.get(timeout=remaining_time)
            output.append(line)
            # Heuristic: If we see the pdb prompt, we likely have the main response
            # Be careful as some commands might produce output containing (Pdb)
            # Let's rely more on the timeout for now, but keep this in mind.
            if line.strip().endswith('(Pdb)'):
                break
        except queue.Empty:
            break # Timeout reached
    return '\n'.join(output)


def send_to_pdb(command, timeout_multiplier=1.0):
    """Send a command to the pdb process and get its response.

    Args:
        command: The PDB command to send
        timeout_multiplier: Multiplier to adjust timeout for complex commands
    """
    global pdb_process, pdb_running

    if pdb_process and pdb_process.poll() is None:
        # Clear queue before sending command to get only relevant output
        while not pdb_output_queue.empty():
            try: pdb_output_queue.get_nowait()
            except queue.Empty: break

        try:
            # Determine appropriate timeout based on command type
            base_timeout = 1.5
            if command.strip().lower() in ('c', 'continue', 'r', 'run', 'until', 'unt'):
                timeout = base_timeout * 3 * timeout_multiplier
            else:
                timeout = base_timeout * timeout_multiplier

            pdb_process.stdin.write((command + '\n').encode('utf-8'))
            pdb_process.stdin.flush()
            # Wait a bit for command processing. Adjust if needed.
            output = get_pdb_output(timeout=timeout) # Adjusted timeout for commands

            # Check if process ended right after the command
            if pdb_process.poll() is not None:
                 pdb_running = False
                 # Try to get any final output
                 final_output = get_pdb_output(timeout=0.1)
                 return f"Command output:\n{output}\n{final_output}\n\n*** The debugging session has ended. ***"

            return output

        except (OSError, BrokenPipeError) as e:
             print(f"Error writing to PDB stdin: {e}", file=sys.stderr)
             pdb_running = False
             # Try to get final output
             final_output = get_pdb_output(timeout=0.1)
             if pdb_process:
                 pdb_process.terminate() # Ensure process is stopped
                 pdb_process.wait(timeout=0.5)
             return f"Error communicating with PDB: {e}\nFinal Output:\n{final_output}\n\n*** The debugging session has likely ended. ***"
        except Exception as e:
            print(f"Unexpected error in send_to_pdb: {e}", file=sys.stderr)
            pdb_running = False
            return f"Unexpected error sending command: {e}"

    elif pdb_running:
        # Process exists but poll() is not None, means it terminated
        pdb_running = False
        final_output = get_pdb_output(timeout=0.1)
        return f"No active pdb process (it terminated).\nFinal Output:\n{final_output}"
    else:
        return "No active pdb process."


def find_project_root(start_path):
    """Find the project root containing pyproject.toml, .git or other indicators, searching upwards."""
    current_dir = os.path.abspath(start_path)
    # Common project root indicators
    root_indicators = ["pyproject.toml", ".git", "setup.py", "requirements.txt", "Pipfile", "poetry.lock"]

    # Guard against infinite loop if start_path is already root
    while current_dir and current_dir != os.path.dirname(current_dir):
        for indicator in root_indicators:
            if os.path.exists(os.path.join(current_dir, indicator)):
                print(f"Found project root indicator '{indicator}' at: {current_dir}")
                return current_dir
        current_dir = os.path.dirname(current_dir)

    # Fallback to the starting path's directory if no indicator found
    fallback_dir = os.path.abspath(start_path)
    print(f"No common project root indicators found upwards. Falling back to: {fallback_dir}")
    return fallback_dir


def find_venv_details(project_root):
    """Check for virtual environment directories and return python path and bin dir."""
    common_venv_names = ['.venv', 'venv', 'env', '.env', 'virtualenv', '.virtualenv']
    common_venv_locations = [project_root]

    # Also check parent directory as some projects keep venvs one level up
    parent_dir = os.path.dirname(project_root)
    if parent_dir != project_root:  # Avoid infinite loop at filesystem root
        common_venv_locations.append(parent_dir)

    # First check for environment variables pointing to active virtual env
    if 'VIRTUAL_ENV' in os.environ:
        venv_path = os.environ['VIRTUAL_ENV']
        if os.path.isdir(venv_path):
            if sys.platform == "win32":
                python_exe = os.path.join(venv_path, 'Scripts', 'python.exe')
                bin_dir = os.path.join(venv_path, 'Scripts')
            else:
                python_exe = os.path.join(venv_path, 'bin', 'python')
                bin_dir = os.path.join(venv_path, 'bin')

            if os.path.exists(python_exe):
                print(f"Found active virtual environment: {venv_path}")
                return python_exe, bin_dir

    # Check for conda environment
    if 'CONDA_PREFIX' in os.environ:
        conda_path = os.environ['CONDA_PREFIX']
        if sys.platform == "win32":
            python_exe = os.path.join(conda_path, 'python.exe')
            bin_dir = conda_path
        else:
            python_exe = os.path.join(conda_path, 'bin', 'python')
            bin_dir = os.path.join(conda_path, 'bin')

        if os.path.exists(python_exe):
            print(f"Found conda environment: {conda_path}")
            return python_exe, bin_dir

    for location in common_venv_locations:
        for name in common_venv_names:
            venv_path = os.path.join(location, name)
            if os.path.isdir(venv_path):
                if sys.platform == "win32":
                    python_exe = os.path.join(venv_path, 'Scripts', 'python.exe')
                    bin_dir = os.path.join(venv_path, 'Scripts')
                else:
                    python_exe = os.path.join(venv_path, 'bin', 'python')
                    bin_dir = os.path.join(venv_path, 'bin')

                if os.path.exists(python_exe):
                    print(f"Found virtual environment: {venv_path}")
                    return python_exe, bin_dir

    # Look for other common Python installations
    if sys.platform == "win32":
        for path in os.environ["PATH"].split(os.pathsep):
            py_exe = os.path.join(path, "python.exe")
            if os.path.exists(py_exe):
                return py_exe, path
    else:
        # On Unix, check if we have a user-installed Python in .local/bin
        local_bin = os.path.expanduser("~/.local/bin")
        if os.path.exists(local_bin):
            for f in os.listdir(local_bin):
                if f.startswith("python") and os.path.isfile(os.path.join(local_bin, f)):
                    py_exe = os.path.join(local_bin, f)
                    return py_exe, local_bin

    print(f"No virtual environment found in: {project_root}")
    return None, None


def has_poetry_config(project_root):
    """Check if project has Poetry configuration in pyproject.toml"""
    pyproject_path = os.path.join(project_root, "pyproject.toml")
    if not os.path.exists(pyproject_path):
        return False
    
    try:
        with open(pyproject_path, 'r') as f:
            content = f.read()
            return '[tool.poetry]' in content
    except (IOError, OSError):
        return False


def sanitize_arguments(args_str):
    """Validate and sanitize command line arguments to prevent injection."""
    dangerous_patterns = [';', '&&', '||', '`', '$(', '|', '>', '<']
    for pattern in dangerous_patterns:
        if pattern in args_str:
            raise ValueError(f"Invalid character in arguments: {pattern}")

    try:
        parsed_args = shlex.split(args_str)
        return parsed_args
    except ValueError as e:
        raise ValueError(f"Error parsing arguments: {e}")


# --- MCP Tools ---

@mcp.tool()
def start_debug(file_path: str, use_pytest: bool = False, args: str = "", pytest_debug_mode: str = "pdb") -> str:
    """Start a debugging session on a Python file within its project context.

    Args:
        file_path: Path to the Python file or test module to debug.
        use_pytest: If True, run using pytest with debugging support.
        args: Additional arguments to pass to the Python script or pytest (space-separated).
        pytest_debug_mode: How to handle pytest debugging:
            - "pdb": Run pytest --pdb (debug on failures)
            - "trace": Run pytest --trace (debug at start of each test)
            - "manual": Run python -m pdb -m pytest (full debugger control)
    """
    global pdb_process, pdb_running, current_file, current_project_root, output_thread
    global pdb_output_queue, breakpoints, current_args, current_use_pytest

    if pdb_running:
        # Check if the process is *really* still running
        if pdb_process and pdb_process.poll() is None:
            return f"Debugging session already running for {current_file}. Use restart_debug or end_debug first."
        else:
            print("Detected stale 'pdb_running' state. Resetting.")
            pdb_running = False # Reset state if process died

    # --- Validate Input and Find Project ---
    # Try multiple potential locations for the file
    paths_to_check = [
        file_path,                              # As provided
        os.path.abspath(file_path),             # Absolute path
        os.path.join(os.getcwd(), file_path),   # Relative to CWD
    ]

    # Add common directories to search in
    for common_dir in ["src", "tests", "lib"]:
        paths_to_check.append(os.path.join(os.getcwd(), common_dir, file_path))

    # Check all possible paths
    abs_file_path = None
    for path in paths_to_check:
        if os.path.exists(path):
            abs_file_path = path
            break

    if not abs_file_path:
        return f"Error: File not found at '{file_path}' (checked multiple locations including CWD, src/, tests/, lib/)"

    file_dir = os.path.dirname(abs_file_path)
    project_root = find_project_root(file_dir)

    # --- Update Global State ---
    current_project_root = project_root
    current_file = abs_file_path
    current_args = args
    current_use_pytest = use_pytest

    # Store original working directory before changing
    original_working_dir = os.getcwd()
    print(f"Original working directory: {original_working_dir}")

    # Initialize breakpoints structure for this file if new
    if current_file not in breakpoints:
        breakpoints[current_file] = {}

    # Clear the output queue rigorously
    while not pdb_output_queue.empty():
        try: pdb_output_queue.get_nowait()
        except queue.Empty: break

    try:
        # --- Determine Execution Environment ---
        use_uv = False
        use_poetry = False
        uv_path = shutil.which("uv")
        poetry_path = shutil.which("poetry")
        venv_python_path = None
        venv_bin_dir = None

        if uv_path and os.path.exists(os.path.join(project_root, "pyproject.toml")):
            # More reliably check for uv.lock as primary indicator
            if os.path.exists(os.path.join(project_root, "uv.lock")):
                 print("Found uv.lock, assuming uv project.")
                 use_uv = True
            else:
                 # Check pyproject.toml for [tool.uv] configuration
                 try:
                     with open(os.path.join(project_root, "pyproject.toml"), 'r') as f:
                         content = f.read()
                         if '[tool.uv]' in content:
                             print("Found [tool.uv] in pyproject.toml, assuming uv project.")
                             use_uv = True
                 except (IOError, OSError):
                     pass

        if not use_uv and poetry_path and os.path.exists(os.path.join(project_root, "pyproject.toml")):
            # Check for Poetry-specific indicators
            if os.path.exists(os.path.join(project_root, "poetry.lock")) or has_poetry_config(project_root):
                print("Found Poetry project")
                use_poetry = True

        if not use_uv and not use_poetry:
            # Look for a standard venv if uv or poetry isn't detected/used
            venv_python_path, venv_bin_dir = find_venv_details(project_root)

        # --- Prepare Command and Subprocess Environment ---
        cmd = []
        # Start with a clean environment copy, modify selectively
        env = os.environ.copy()

        # Calculate relative path from project root (preferred for tools)
        try:
            rel_file_path = os.path.relpath(abs_file_path, project_root)
            # Handle edge case where file is the project root itself (e.g., debugging a script there)
            if rel_file_path == '.':
                rel_file_path = os.path.basename(abs_file_path)

        except ValueError:
             # Handle cases where file is on a different drive (Windows)
             print(f"Warning: File '{abs_file_path}' not relative to project root '{project_root}'. Using absolute path.")
             rel_file_path = abs_file_path # Use absolute path if relative fails


        # Safely parse arguments using sanitize_arguments
        try:
            parsed_args = sanitize_arguments(args)
        except ValueError as e:
            return f"Error in arguments: {e}"

        # Determine command based on environment
        if use_uv:
            print(f"Using uv run in: {project_root}")
            # Clean potentially conflicting env vars for uv run
            env.pop('VIRTUAL_ENV', None)
            env.pop('PYTHONHOME', None)
            base_cmd = ["uv", "run", "--"]
            if use_pytest:
                if pytest_debug_mode == "manual":
                    # Run pytest under full pdb control
                    base_cmd.extend(["python", "-m", "pdb", "-m", "pytest"])
                    cmd = base_cmd + ["-s", rel_file_path] + parsed_args
                elif pytest_debug_mode == "trace":
                    # Debug at start of each test
                    base_cmd.extend(["pytest", "--trace", "-s"])
                    cmd = base_cmd + [rel_file_path] + parsed_args
                else:  # pytest_debug_mode == "pdb"
                    # Debug on failures
                    base_cmd.extend(["pytest", "--pdb", "-s"])
                    cmd = base_cmd + [rel_file_path] + parsed_args
            else:
                base_cmd.extend(["python", "-m", "pdb"])
                cmd = base_cmd + [rel_file_path] + parsed_args
        elif use_poetry:
            print(f"Using poetry run in: {project_root}")
            # Clean potentially conflicting env vars for poetry run
            env.pop('VIRTUAL_ENV', None)
            env.pop('PYTHONHOME', None)
            if use_pytest:
                if pytest_debug_mode == "manual":
                    # Run pytest under full pdb control
                    base_cmd = ["poetry", "run", "python", "-m", "pdb", "-m", "pytest"]
                    cmd = base_cmd + ["-s", rel_file_path] + parsed_args
                elif pytest_debug_mode == "trace":
                    # Debug at start of each test
                    base_cmd = ["poetry", "run", "pytest", "--trace", "-s"]
                    cmd = base_cmd + [rel_file_path] + parsed_args
                else:  # pytest_debug_mode == "pdb"
                    # Debug on failures
                    base_cmd = ["poetry", "run", "pytest", "--pdb", "-s"]
                    cmd = base_cmd + [rel_file_path] + parsed_args
            else:
                base_cmd = ["poetry", "run", "python", "-m", "pdb"]
                cmd = base_cmd + [rel_file_path] + parsed_args
        elif venv_python_path:
            print(f"Using venv Python: {venv_python_path}")
            venv_dir = os.path.dirname(os.path.dirname(venv_bin_dir)) # Get actual venv root
            env['VIRTUAL_ENV'] = venv_dir
            env['PATH'] = f"{venv_bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env.pop('PYTHONHOME', None)

            # Critical addition: Set PYTHONPATH to include project root
            env['PYTHONPATH'] = f"{project_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

            # Force unbuffered output for better debugging experience
            env['PYTHONUNBUFFERED'] = '1'

            if use_pytest:
                # Find pytest within the venv
                pytest_exe = os.path.join(venv_bin_dir, 'pytest' + ('.exe' if sys.platform == 'win32' else ''))
                if not os.path.exists(pytest_exe):
                    # Try finding via the venv python itself
                    try:
                        result = subprocess.run([venv_python_path, "-m", "pytest", "--version"], capture_output=True, text=True, check=True, cwd=project_root, env=env)
                        print(f"Found pytest via '{venv_python_path} -m pytest'")
                        if pytest_debug_mode == "manual":
                            cmd = [venv_python_path, "-m", "pdb", "-m", "pytest", "-s", rel_file_path] + parsed_args
                        elif pytest_debug_mode == "trace":
                            cmd = [venv_python_path, "-m", "pytest", "--trace", "-s", rel_file_path] + parsed_args
                        else:  # pytest_debug_mode == "pdb"
                            cmd = [venv_python_path, "-m", "pytest", "--pdb", "-s", rel_file_path] + parsed_args
                    except (subprocess.CalledProcessError, FileNotFoundError):
                         return f"Error: pytest not found or executable in the virtual environment at {venv_bin_dir}. Cannot run with --pytest."
                else:
                    if pytest_debug_mode == "manual":
                        cmd = [venv_python_path, "-m", "pdb", "-m", "pytest", "-s", rel_file_path] + parsed_args
                    elif pytest_debug_mode == "trace":
                        cmd = [pytest_exe, "--trace", "-s", rel_file_path] + parsed_args
                    else:  # pytest_debug_mode == "pdb"
                        cmd = [pytest_exe, "--pdb", "-s", rel_file_path] + parsed_args
            else:
                cmd = [venv_python_path, "-m", "pdb", rel_file_path] + parsed_args
        else:
            print("Warning: No uv, poetry, or standard venv detected in project root. Using system Python/pytest.")
            # Fallback to system python/pytest found in PATH
            python_exe = shutil.which("python") or sys.executable # Find system python more reliably
            if not python_exe:
                 return "Error: Could not find 'python' executable in system PATH."

            if use_pytest:
                 pytest_exe = shutil.which("pytest")
                 if not pytest_exe:
                     return "Error: pytest command not found in system PATH. Cannot run with --pytest."
                 if pytest_debug_mode == "manual":
                     cmd = [python_exe, "-m", "pdb", "-m", "pytest", "-s", rel_file_path] + parsed_args
                 elif pytest_debug_mode == "trace":
                     cmd = [pytest_exe, "--trace", "-s", rel_file_path] + parsed_args
                 else:  # pytest_debug_mode == "pdb"
                     cmd = [pytest_exe, "--pdb", "-s", rel_file_path] + parsed_args
            else:
                 cmd = [python_exe, "-m", "pdb", rel_file_path] + parsed_args

        # --- Launch Subprocess ---
        print(f"Executing command: {' '.join(map(shlex.quote, cmd))}")
        print(f"Working directory: {project_root}")
        print(f"Using VIRTUAL_ENV: {env.get('VIRTUAL_ENV', 'Not Set')}")
        # print(f"Using PATH: {env.get('PATH', 'Not Set')}") # Can be very long

        # Ensure previous thread is not running (important for restarts)
        if output_thread and output_thread.is_alive():
             print("Warning: Previous output thread was still alive.", file=sys.stderr)
             # Attempting to join might hang if readline blocks, so we just detach.

        pdb_process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr to stdout for easier capture
            text=False, # Read bytes for reliable readline behavior
            cwd=project_root, # <<< CRITICAL: Run from project root
            env=env,          # Pass the prepared environment
            bufsize=0         # Use system default buffering (often line-buffered)
        )

        # Start the output reader thread anew
        output_thread = threading.Thread(
            target=read_pdb_output,
            args=(pdb_process, pdb_output_queue),
            daemon=True # Allows main program to exit even if thread is running
        )
        output_thread.start()

        pdb_running = True # Set running state *before* waiting for output

        # --- Wait for Initial Output & Verify Start ---
        print("Waiting for PDB to start...")
        initial_output = get_pdb_output(timeout=30.0) # Longer timeout for potentially slow starts/imports

        # Check if process died immediately
        if pdb_process.poll() is not None:
             exit_code = pdb_process.poll()
             pdb_running = False
             # Attempt to get any remaining output directly if thread missed it
             final_out_bytes, _ = pdb_process.communicate()
             final_out_str = final_out_bytes.decode('utf-8', errors='replace')
             full_output = initial_output + "\n" + final_out_str.strip()
             return (f"Error: PDB process exited immediately (Code: {exit_code}). "
                     f"Command: {' '.join(map(shlex.quote, cmd))}\n"
                     f"Working Dir: {project_root}\n"
                     f"Output:\n---\n{full_output}\n---")

        # Check for typical PDB prompt indicators
        # Needs to be somewhat lenient as initial output varies (e.g., pytest header)
        has_pdb_prompt = "-> " in initial_output or "(Pdb)" in initial_output
        has_error = "Error:" in initial_output or "Exception:" in initial_output

        if not has_pdb_prompt:
             # If no prompt but also no obvious error and process is running,
             # it might be okay, just slower startup or waiting.
             if pdb_process.poll() is None and not has_error:
                  warning_msg = ("Warning: PDB started but initial prompt ('-> ' or '(Pdb)') "
                                 "not detected in first few seconds. It might be running.")
                  print(warning_msg, file=sys.stderr)
                  # Proceed but include the warning in the return message
                  initial_output = f"{warning_msg}\n\n{initial_output}"
             else:
                  # No prompt, process might have died silently or has error message
                  pdb_running = False
                  # Try to get more output
                  final_output = get_pdb_output(timeout=0.5)
                  full_output = initial_output + "\n" + final_output
                  return (f"Error starting PDB. No prompt detected and process may have issues.\n"
                           f"Command: {' '.join(map(shlex.quote, cmd))}\n"
                           f"Working Dir: {project_root}\n"
                           f"Output:\n---\n{full_output}\n---")

        # --- Restore Breakpoints ---
        restored_bps_output = ""
        if current_file in breakpoints and breakpoints[current_file]:
            print(f"Restoring {len(breakpoints[current_file])} breakpoints for {rel_file_path}...")
            # Use relative path for consistency in breakpoint commands
            try:
                bp_rel_path = os.path.relpath(current_file, project_root)
                if bp_rel_path == '.': bp_rel_path = os.path.basename(current_file)
            except ValueError:
                bp_rel_path = current_file # Fallback

            restored_bps_output += "\n--- Restoring Breakpoints ---\n"
            # Sort by line number for clarity
            for line_num in sorted(breakpoints[current_file].keys()):
                bp_command_rel = f"b {bp_rel_path}:{line_num}"
                print(f"Sending restore cmd: {bp_command_rel}")
                restore_out = send_to_pdb(bp_command_rel)
                restored_bps_output += f"Set {bp_rel_path}:{line_num}: {restore_out or '[No Response]'}\n"

                # Extract and update BP number if available
                match = re.search(r"Breakpoint (\d+) at", restore_out)
                if match:
                    bp_data = breakpoints[current_file][line_num]
                    if isinstance(bp_data, dict):
                        bp_data["bp_number"] = match.group(1)
                    else:
                        # Backward compatibility with older format
                        breakpoints[current_file][line_num] = {
                            "command": bp_data,
                            "bp_number": match.group(1)
                        }

            restored_bps_output += "--- Breakpoint Restore Complete ---\n"

        return f"Debugging session started for {rel_file_path} (in {project_root})\n\n{initial_output}\n{restored_bps_output}"

    except FileNotFoundError as e:
         pdb_running = False
         return f"Error starting debugging session: Command not found ({e.filename}). Is '{cmd[0]}' installed and in the correct PATH (system or venv)?\n{traceback.format_exc()}"
    except Exception as e:
        pdb_running = False
        return f"Error starting debugging session: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def send_pdb_command(command: str) -> str:
    """Send a command to the running PDB instance.

    Examples:
        n (next line), c (continue), s (step into), r (return from function)
        p variable (print variable), pp variable (pretty print)
        b line_num (set breakpoint in current file), b file:line_num
        cl num (clear breakpoint number), cl file:line_num
        l (list source code), ll (list longer source code)
        a (print arguments of current function)
        q (quit)

    Args:
        command: The PDB command string.
    """
    global pdb_running, pdb_process

    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # Double check process liveness
    if pdb_process is None or pdb_process.poll() is not None:
         pdb_running = False
         final_output = get_pdb_output(timeout=0.1)
         return f"The debugging session appears to have ended.\nFinal Output:\n{final_output}"

    try:
        # Determine appropriate timeout based on command complexity
        timeout_multiplier = 1.0
        if command.strip().lower() in ('c', 'continue', 'r', 'run'):
            # These commands might take longer to complete
            timeout_multiplier = 2.0

        response = send_to_pdb(command, timeout_multiplier)

        # Check if the session ended after this specific command (e.g., 'q' or fatal error)
        if not pdb_running: # send_to_pdb might set this if process ended
             return f"Command output:\n{response}" # Response already includes end notice

        # Provide extra context for common navigation commands
        # Only do this if the session is still running
        nav_commands = ['n', 's', 'c', 'r', 'unt', 'until', 'next', 'step', 'continue', 'return']
        if command.strip().lower() in nav_commands and pdb_running and pdb_process.poll() is None:
            # Give PDB a tiny bit more time after navigation before asking for location
            # Check again if it's running before sending 'l .'
            if pdb_running and pdb_process.poll() is None:
                print("Fetching context after navigation...")
                line_context = send_to_pdb("l .")
                 # Check again after sending 'l .'
                if pdb_running and pdb_process.poll() is None:
                    response += f"\n\n-- Current location --\n{line_context}"
                else:
                    response += "\n\n-- Session ended after navigation --"
                    pdb_running = False # Ensure state is correct

        return f"Command output:\n{response}"

    except Exception as e:
        # Catch unexpected errors during command sending/processing
        print(f"Error in send_pdb_command: {e}", file=sys.stderr)
        # Check process status again
        if pdb_process and pdb_process.poll() is not None:
             pdb_running = False
             return f"Error sending command: {str(e)}\n\n*** The debugging session has likely ended. ***\n{traceback.format_exc()}"
        else:
             return f"Error sending command: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
def set_breakpoint(file_path: str, line_number: int) -> str:
    """Set a breakpoint at a specific line in a file. Uses relative path if possible.

    Args:
        file_path: Path to the file (can be relative to project root or absolute).
        line_number: Line number for the breakpoint.
    """
    global breakpoints, current_project_root

    if not pdb_running:
        return "No active debugging session. Use start_debug first."
    if not current_project_root:
         return "Error: Project root not identified. Cannot reliably set breakpoint."

    abs_file_path = os.path.abspath(os.path.join(current_project_root, file_path)) # Resolve relative to root first
    if not os.path.exists(abs_file_path):
        abs_file_path = os.path.abspath(file_path) # Try absolute directly
        if not os.path.exists(abs_file_path):
             return f"Error: File not found at '{file_path}' (checked relative to project and absolute)."

    # Use relative path for the breakpoint command if possible
    try:
        rel_file_path = os.path.relpath(abs_file_path, current_project_root)
        if rel_file_path == '.': rel_file_path = os.path.basename(abs_file_path)
    except ValueError:
        rel_file_path = abs_file_path # Fallback to absolute

    # Track breakpoints using the *absolute* path as the key for internal consistency
    if abs_file_path not in breakpoints:
        breakpoints[abs_file_path] = {}

    if line_number in breakpoints[abs_file_path]:
        # Verify with pdb if it's actually set there
        current_bps = send_to_pdb("b")
        if f"{rel_file_path}:{line_number}" in current_bps:
             return f"Breakpoint already exists and is tracked at {abs_file_path}:{line_number}"
        else:
             print(f"Warning: Breakpoint tracked locally but not found in PDB output for {rel_file_path}:{line_number}. Will attempt to set.")


    command = f"b {rel_file_path}:{line_number}"
    response = send_to_pdb(command)

    # More robust verification using pattern matching
    bp_markers = ["Breakpoint", "at", str(line_number)]
    if all(marker in response for marker in bp_markers):
        # Extract breakpoint number from response
        match = re.search(r"Breakpoint (\d+) at", response)
        bp_number = match.group(1) if match else None

        # Store both command and breakpoint number
        breakpoints[abs_file_path][line_number] = {
            "command": command,
            "bp_number": bp_number
        }
        return f"Breakpoint #{bp_number} set and tracked:\n{response}"
    elif "Error" not in response and "multiple files" not in response.lower():
         # Maybe pdb didn't confirm explicitly but didn't error? (e.g., line doesn't exist yet)
         # We won't track it reliably unless PDB confirms it.
         return f"Breakpoint command sent. PDB response might indicate an issue (e.g., invalid line) or success without standard confirmation:\n{response}\n(Breakpoint NOT reliably tracked. Verify with list_breakpoints)"
    else:
        # PDB reported an error or ambiguity
        return f"Failed to set breakpoint. PDB response:\n{response}"


@mcp.tool()
def clear_breakpoint(file_path: str, line_number: int) -> str:
    """Clear a breakpoint at a specific line in a file. Uses relative path if possible.

    Args:
        file_path: Path to the file where the breakpoint exists.
        line_number: Line number of the breakpoint to clear.
    """
    global breakpoints, current_project_root

    if not pdb_running:
        return "No active debugging session. Use start_debug first."
    if not current_project_root:
         return "Error: Project root not identified. Cannot reliably clear breakpoint."

    abs_file_path = os.path.abspath(os.path.join(current_project_root, file_path))
    if not os.path.exists(abs_file_path):
        abs_file_path = os.path.abspath(file_path)
        if not os.path.exists(abs_file_path):
             # If file doesn't exist, we likely don't have a BP anyway
             if abs_file_path in breakpoints and line_number in breakpoints[abs_file_path]:
                  del breakpoints[abs_file_path][line_number]
                  if not breakpoints[abs_file_path]: del breakpoints[abs_file_path]
             return f"Warning: File not found at '{file_path}'. Breakpoint untracked (if it was tracked)."


    try:
        rel_file_path = os.path.relpath(abs_file_path, current_project_root)
        if rel_file_path == '.': rel_file_path = os.path.basename(abs_file_path)
    except ValueError:
        rel_file_path = abs_file_path

    # Check if we have a breakpoint number stored, which is more reliable for clearing
    bp_number = None
    if abs_file_path in breakpoints and line_number in breakpoints[abs_file_path]:
        bp_data = breakpoints[abs_file_path][line_number]
        if isinstance(bp_data, dict) and "bp_number" in bp_data:
            bp_number = bp_data["bp_number"]

    # Use the breakpoint number if available, otherwise use file:line
    if bp_number:
        command = f"cl {bp_number}"
    else:
        command = f"cl {rel_file_path}:{line_number}"

    response = send_to_pdb(command)

    # Check response for confirmation (e.g., "Deleted breakpoint", "No breakpoint")
    breakpoint_cleared_in_pdb = "Deleted breakpoint" in response or "No breakpoint" in response or "Error: " not in response

    # Update internal tracking
    if abs_file_path in breakpoints and line_number in breakpoints[abs_file_path]:
        if breakpoint_cleared_in_pdb:
            del breakpoints[abs_file_path][line_number]
            if not breakpoints[abs_file_path]: # Remove file entry if no more bps
                 del breakpoints[abs_file_path]
            status_msg = "Breakpoint untracked."
        else:
            status_msg = "Breakpoint potentially still exists in PDB despite local tracking. Verify with list_breakpoints."
    else:
        status_msg = "Breakpoint was not tracked locally."


    return f"Clear breakpoint result:\n{response}\n({status_msg})"


@mcp.tool()
def list_breakpoints() -> str:
    """List breakpoints known by PDB and compare with internally tracked breakpoints."""
    global breakpoints, current_project_root

    if not pdb_running:
        return "No active debugging session. Use start_debug first."
    if not current_project_root:
        # List only tracked BPs if PDB isn't running or root unknown
        tracked_bps_formatted = []
        for abs_path, lines in breakpoints.items():
             # Try to show relative if possible, else absolute
            try:
                disp_path = os.path.relpath(abs_path, os.getcwd()) # Relative to current dir might be useful
            except ValueError:
                disp_path = abs_path
            for line_num in sorted(lines.keys()):
                bp_data = lines[line_num]
                if isinstance(bp_data, dict) and "bp_number" in bp_data:
                    tracked_bps_formatted.append(f"{disp_path}:{line_num} (BP #{bp_data['bp_number']})")
                else:
                    tracked_bps_formatted.append(f"{disp_path}:{line_num}")
        return "No active PDB session or project root unknown.\n\n--- Tracked Breakpoints ---\n" + ('\n'.join(tracked_bps_formatted) if tracked_bps_formatted else "None")


    pdb_response = send_to_pdb("b")

    # Format our tracked breakpoints using relative paths from project root where possible
    tracked_bps_formatted = []
    for abs_path, lines in breakpoints.items():
        try:
            rel_path = os.path.relpath(abs_path, current_project_root)
            if rel_path == '.': rel_path = os.path.basename(abs_path)
        except ValueError:
            rel_path = abs_path # Fallback if not relative
        for line_num in sorted(lines.keys()):
            bp_data = lines[line_num]
            if isinstance(bp_data, dict) and "bp_number" in bp_data:
                tracked_bps_formatted.append(f"{rel_path}:{line_num} (BP #{bp_data['bp_number']})")
            else:
                tracked_bps_formatted.append(f"{rel_path}:{line_num}")

    # Add a comparison note
    comparison_note = "\n(Compare PDB list above with tracked list below. Use set/clear to synchronize if needed.)"

    return (f"--- PDB Breakpoints ---\n{pdb_response}\n\n"
            f"--- Tracked Breakpoints ---\n" +
            ('\n'.join(tracked_bps_formatted) if tracked_bps_formatted else "None") +
            comparison_note)

@mcp.tool()
def restart_debug() -> str:
    """Restart the debugging session with the same file, arguments, and pytest flag."""
    global pdb_process, pdb_running, current_file, current_args, current_use_pytest

    if not current_file:
        return "No debugging session was previously started (or state lost) to restart."

    # Store details before ending the current session
    file_to_debug = current_file
    args_to_use = current_args
    use_pytest_flag = current_use_pytest
    print(f"Attempting to restart debug for: {file_to_debug} with args='{args_to_use}' pytest={use_pytest_flag}")

    # End the current session forcefully if running
    end_result = "Previous session not running or already ended."
    if pdb_running:
        print("Ending current session before restart...")
        end_result = end_debug() # Use the dedicated end function
        print(f"Restart: {end_result}")

    # Reset state explicitly (end_debug should handle most, but belt-and-suspenders)
    pdb_process = None
    pdb_running = False
    # output_thread should be handled by new start_debug call

    # Clear the output queue again just in case
    while not pdb_output_queue.empty():
       try: pdb_output_queue.get_nowait()
       except queue.Empty: break

    # Start a new session using stored parameters
    print("Calling start_debug for restart...")
    start_result = start_debug(file_path=file_to_debug, use_pytest=use_pytest_flag, args=args_to_use)

    # Note: Breakpoints are now restored within start_debug using the tracked 'breakpoints' dict

    return f"--- Restart Attempt ---\nPrevious session end result: {end_result}\n\nNew session status:\n{start_result}"


@mcp.tool()
def examine_variable(variable_name: str) -> str:
    """Examine a variable's type, value (print), and attributes (dir) using PDB.

    Args:
        variable_name: Name of the variable to examine (e.g., 'my_var', 'self.data').
    """
    if not pdb_running:
        return "No active debugging session. Use start_debug first."

    # Basic print
    p_command = f"p {variable_name}"
    print(f"Sending command: {p_command}")
    basic_info = send_to_pdb(p_command)
    if not pdb_running: return f"Session ended after 'p {variable_name}'. Output:\n{basic_info}"

    # Type info
    type_command = f"p type({variable_name})"
    print(f"Sending command: {type_command}")
    type_info = send_to_pdb(type_command)
    # Check if session ended, but proceed if possible
    if not pdb_running and "Session ended" not in basic_info :
        return f"Value:\n{basic_info}\n\nSession ended after 'p type({variable_name})'. Type Output:\n{type_info}"

    # Attributes/methods using dir(), protect with try-except in PDB
    dir_command = f"import inspect; print(dir({variable_name}))" # More robust than just dir()
    print("Sending command: (inspect dir)")
    dir_info = send_to_pdb(dir_command)
    if not pdb_running and "Session ended" not in type_info :
         return f"Value:\n{basic_info}\n\nType:\n{type_info}\n\nSession ended after 'dir()'. Dir Output:\n{dir_info}"

    # Pretty print (useful for complex objects)
    pp_command = f"pp {variable_name}"
    print(f"Sending command: {pp_command}")
    pretty_info = send_to_pdb(pp_command)
    if not pdb_running and "Session ended" not in dir_info :
         return f"Value:\n{basic_info}\n\nType:\n{type_info}\n\nAttributes/Methods:\n{dir_info}\n\nSession ended after 'pp'. PP Output:\n{pretty_info}"

    return (f"--- Variable Examination: {variable_name} ---\n\n"
            f"Value (p):\n{basic_info}\n\n"
            f"Pretty Value (pp):\n{pretty_info}\n\n"
            f"Type (p type()):\n{type_info}\n\n"
            f"Attributes/Methods (dir()):\n{dir_info}\n"
            f"--- End Examination ---")


@mcp.tool()
def get_debug_status() -> str:
    """Get the current status of the debugging session and tracked state."""
    global pdb_running, current_file, current_project_root, breakpoints, pdb_process

    if not pdb_running:
         # Check if process exists but isn't running
         if pdb_process and pdb_process.poll() is not None:
              return "Debugging session ended. Process terminated."
         return "No active debugging session."

    # Check process liveness again
    if pdb_process and pdb_process.poll() is not None:
        pdb_running = False
        return "Debugging session has ended (process terminated)."

    # Format tracked breakpoints for status
    bp_list = []
    for abs_path, lines in breakpoints.items():
         try:
             rel_path = os.path.relpath(abs_path, current_project_root or os.getcwd())
             if rel_path == '.': rel_path = os.path.basename(abs_path)
         except ValueError:
             rel_path = abs_path
         for line_num in sorted(lines.keys()):
            bp_data = lines[line_num]
            if isinstance(bp_data, dict) and "bp_number" in bp_data:
                bp_list.append(f"{rel_path}:{line_num} (BP #{bp_data['bp_number']})")
            else:
                bp_list.append(f"{rel_path}:{line_num}")

    status = {
        "running": pdb_running,
        "current_file": current_file,
        "project_root": current_project_root,
        "use_pytest": current_use_pytest,
        "arguments": current_args,
        "process_id": pdb_process.pid if pdb_process else None,
        "tracked_breakpoints": bp_list,
    }

    # Try to get current location from PDB without advancing
    current_loc_output = "[Could not query PDB location]"
    if pdb_running and pdb_process and pdb_process.poll() is None:
         current_loc_output = send_to_pdb("l .") # Get location without changing state
         if not pdb_running: # Check if the query itself ended the session
             status["running"] = False
             current_loc_output += "\n -- Session ended during status check --"


    return "--- Debug Session Status ---\n" + \
           f"Running: {status['running']}\n" + \
           f"PID: {status['process_id']}\n" + \
           f"Project Root: {status['project_root']}\n" + \
           f"Debugging File: {status['current_file']}\n" + \
           f"Using Pytest: {status['use_pytest']}\n" + \
           f"Arguments: '{status['arguments']}'\n" + \
           f"Tracked Breakpoints: {status['tracked_breakpoints'] or 'None'}\n\n" + \
           f"-- Current PDB Location --\n{current_loc_output}\n" + \
           "--- End Status ---"


@mcp.tool()
def end_debug() -> str:
    """End the current debugging session forcefully."""
    global pdb_process, pdb_running, output_thread

    if not pdb_running and (pdb_process is None or pdb_process.poll() is not None):
        return "No active debugging session to end."

    print("Ending debugging session...")
    result_message = "Debugging session ended."

    if pdb_process and pdb_process.poll() is None:
        try:
            # Try sending SIGINT (Ctrl+C) first for cleaner exit
            if sys.platform != "win32":
                try:
                    os.kill(pdb_process.pid, signal.SIGINT)
                    try:
                        pdb_process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                except (OSError, ProcessLookupError) as e:
                    print(f"SIGINT failed: {e}")

            # Next try sending quit command for graceful exit
            if pdb_process.poll() is None:
                try:
                    print("Attempting graceful exit with 'q'...")
                    pdb_process.stdin.write(b'q\n')
                    pdb_process.stdin.flush()
                    # Wait briefly for potential cleanup
                    pdb_process.wait(timeout=0.5)
                    print("PDB process quit gracefully.")
                except (subprocess.TimeoutExpired, OSError, BrokenPipeError) as e:
                    print(f"Graceful quit failed or timed out ({e}). Terminating forcefully.")

            # If still running, terminate forcefully
            if pdb_process.poll() is None:
                try:
                    pdb_process.terminate() # Send SIGTERM
                    pdb_process.wait(timeout=1.0) # Wait for termination
                    print("PDB process terminated.")
                except subprocess.TimeoutExpired:
                    print("Terminate timed out. Killing process.")
                    pdb_process.kill() # Send SIGKILL
                    pdb_process.wait(timeout=0.5) # Wait for kill
                    print("PDB process killed.")
                except Exception as term_err:
                     print(f"Error during terminate/kill: {term_err}", file=sys.stderr)
                     result_message = f"Debugging session ended with errors during termination: {term_err}"
        except Exception as e:
            print(f"Error during end_debug: {e}", file=sys.stderr)
            result_message = f"Debugging session ended with errors: {e}"

    # Clean up state
    pdb_process = None
    pdb_running = False

    # Wait briefly for the output thread to potentially finish reading remaining output
    if output_thread and output_thread.is_alive():
         print("Waiting for output thread to finish...")
         output_thread.join(timeout=0.5)
         if output_thread.is_alive():
              print("Warning: Output thread did not finish cleanly.", file=sys.stderr)

    output_thread = None # Clear thread object reference

    # Clear the queue one last time
    while not pdb_output_queue.empty():
        try: pdb_output_queue.get_nowait()
        except queue.Empty: break

    # No cleanup needed for pytest debugging flags approach

    print("Debugging session ended and state cleared.")
    return result_message

# --- Cleanup on Exit ---

def cleanup():
    """Ensure the PDB process is terminated when the MCP server exits."""
    print("Running atexit cleanup...")
    if pdb_running or (pdb_process and pdb_process.poll() is None):
        end_debug()

atexit.register(cleanup)

# --- Main Execution ---

def main():
    """Initialize and run the FastMCP server."""
    print("--- Starting MCP PDB Tool Server ---")
    print(f"Python Executable: {sys.executable}")
    print(f"Working Directory: {os.getcwd()}")
    # Add any other relevant startup info here
    mcp.run()
    print("--- MCP PDB Tool Server Shutdown ---")

if __name__ == "__main__":
    main()
