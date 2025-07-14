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

#### For debugging tests:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="trace", args="-k test_function_name")
```
- **Recommended for debugging passing tests**
- Stops at the beginning of the test execution
- Allows you to set breakpoints and inspect variables during normal execution
- Always specify the specific test with `-k test_name` to avoid stepping through multiple tests

#### For debugging tests to stop on failures:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="pdb")
```
- Debugger activates only when tests fail
- Good for investigating test failures

#### For complex test debugging scenarios:
```
start_debug(file_path="test_file.py", use_pytest=True, pytest_debug_mode="manual", args="-k test_function_name")
```
- Full control but requires test failures to activate debugger
- Better for debugging test setup/teardown issues
- **Note:** This mode only works effectively with failing tests

### 3. Variable Inspection Workflow

1. Start debugging with trace mode for non-failing tests
2. Set breakpoints at key lines using `set_breakpoint()`
3. Continue to breakpoint with `send_pdb_command("c")`
4. Step through execution with `send_pdb_command("n")` (next line)
5. Examine variables with `examine_variable("variable_name")`
6. Use `send_pdb_command("p variable.attribute")` for quick checks

**Example:**
```python
# Debug a specific test
start_debug("test/test_api.py", use_pytest=True, pytest_debug_mode="trace", args="-k test_user_login")

# Set breakpoint at the line you want to inspect
set_breakpoint("test/test_api.py", line_number=47)

# Continue to breakpoint
send_pdb_command("c")

# Execute the line you want to debug
send_pdb_command("n")

# Examine the result
examine_variable("response")
```

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

1. **For variable inspection during tests**: Use `pytest_debug_mode="trace"` with `-k test_name`
2. **For failing tests**: Use `pytest_debug_mode="pdb"`
3. **Prefer to target specific tests** with `-k test_name` to avoid stepping through entire test suites
4. **Set breakpoints immediately** after starting the debug session
5. **Use `examine_variable()`** for comprehensive variable inspection
6. **Use `send_pdb_command("n")`** to step through line by line
7. **End sessions cleanly** with `end_debug()` when done

## Troubleshooting

### Common Issues

**Test exits immediately without stopping:**
- For passing tests, use `pytest_debug_mode="trace"` instead of `"manual"` or `"pdb"`
- Always include `-k test_name` to target specific tests
- The `"pdb"` mode only activates on test failures

**Breakpoints not hit:**
- Ensure you're using `pytest_debug_mode="trace"` for non-failing tests
- Set breakpoints after the debugger starts but before continuing execution
- Verify file paths are correct (use absolute paths or relative to project root)

**General troubleshooting:**
- If debugging won't start, check that the file path exists and is executable
- Use `get_debug_status()` to check if a session is already running
- If breakpoints aren't working, ensure you're using absolute paths or paths relative to the project root

## Example Debugging Session

```
# Start debugging with trace mode for a passing test
start_debug(file_path="test/test_api.py", use_pytest=True, pytest_debug_mode="trace", args="-k test_user_login")

# Set a breakpoint in the code you want to debug
set_breakpoint(file_path="test/test_api.py", line_number=45)

# Continue execution to the breakpoint
send_pdb_command("c")

# Step to the next line to execute the line you want to inspect
send_pdb_command("n")

# Examine variables when stopped at the line
examine_variable("user_data")
examine_variable("request")

# Step through code
send_pdb_command("n")  # Next line
send_pdb_command("s")  # Step into function

# End the session
end_debug()
```

This context should help you effectively use the MCP-PDB debugging capabilities!