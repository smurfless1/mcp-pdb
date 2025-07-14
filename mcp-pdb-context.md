# MCP-PDB Debugging Context for Claude

This document provides context for Claude instances that have the MCP-PDB server available.

## What is MCP-PDB?

MCP-PDB is a Model Context Protocol (MCP) server that provides Python debugger (pdb) capabilities to Claude. It allows you to debug Python code interactively, set breakpoints, inspect variables, and step through code execution.

## Available Tools

You have access to the following debugging tools:

### Core Debugging Tools
- `start_debug(file_path, use_pytest=False, args="", pytest_debug_mode="pdb")` - Start debugging a Python file
- `send_pdb_command(command)` - Send commands directly to the debugger
- `set_breakpoint(file_path, line_number)` - Set breakpoints in code
- `clear_breakpoint(file_path, line_number)` - Remove breakpoints
- `list_breakpoints()` - Show all current breakpoints
- `examine_variable(variable_name)` - Inspect variable values and types
- `get_debug_status()` - Check debugging session status
- `restart_debug()` - Restart the current debugging session
- `end_debug()` - End the debugging session

## Debugging Workflows

### 1. Regular Python File Debugging
```
start_debug(file_path="script.py") 
set_breakpoint(file_path="script.py", line_number=10)
send_pdb_command("c")  # Continue to breakpoint
examine_variable("variable_name")
```

### 2. Test Debugging (Recommended Approaches)

#### For debugging failing tests:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="pdb")
```
- Debugger activates only when tests fail
- Good for investigating test failures

#### For debugging specific test execution:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="manual", args="-k test_function_name")
```
- **Recommended for most test debugging**
- Gives you full control to set breakpoints before tests run
- Only stops at your specific breakpoints, not every test
- Best for debugging test suites and catching specific code paths

#### For step-by-step test debugging:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="trace")
```
- Debugger activates at the start of each test
- Only use for debugging individual tests (not test suites)

## Common PDB Commands

Use these with `send_pdb_command()`:

- `n` - Next line (step over)
- `s` - Step into function
- `c` - Continue execution
- `r` - Return from current function
- `p variable` - Print variable value
- `pp variable` - Pretty print variable
- `l` - List source code around current line
- `w` - Show stack trace
- `b file:line` - Set breakpoint (or use `set_breakpoint()` tool)
- `cl num` - Clear breakpoint by number

## Environment Detection

MCP-PDB automatically detects and works with:
- **uv** projects (recommended)
- **Poetry** projects
- Standard Python virtual environments
- System Python installations

## Best Practices

1. **Always use `pytest_debug_mode="manual"`** when debugging test suites - it gives you the most control
2. **Set breakpoints before continuing** - use `set_breakpoint()` then `send_pdb_command("c")`
3. **Use `examine_variable()`** for detailed variable inspection instead of basic `p` commands
4. **Check `get_debug_status()`** if you're unsure about the debugging session state
5. **End sessions cleanly** with `end_debug()` when done

## Troubleshooting

- If debugging won't start, check that the file path exists and is executable
- For test debugging issues, try `pytest_debug_mode="manual"` for maximum control
- Use `get_debug_status()` to check if a session is already running
- If breakpoints aren't working, ensure you're using absolute paths or paths relative to the project root

## Example Debugging Session

```
# Start debugging with full control
start_debug(file_path="test/test_api.py", use_pytest=True, pytest_debug_mode="manual", args="-k test_user_login")

# Set a breakpoint in the code you want to debug
set_breakpoint(file_path="src/auth.py", line_number=45)

# Continue execution to the breakpoint
send_pdb_command("c")

# Examine variables when stopped at breakpoint
examine_variable("user_data")
examine_variable("request")

# Step through code
send_pdb_command("n")  # Next line
send_pdb_command("s")  # Step into function

# End the session
end_debug()
```

This context should help you effectively use the MCP-PDB debugging capabilities!