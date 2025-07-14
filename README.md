# MCP-PDB: Python Debugger Interface for Claude/LLMs

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

MCP-PDB provides tools for using Python's debugger (pdb) with Claude and other LLMs through the Model Context Protocol (MCP). This was inspired by [debug-gym](https://microsoft.github.io/debug-gym/) by Microsoft, which showed gains in various coding benchmarks by providing a coding agent access to a python debugger.

## ⚠️ Security Warning

This tool executes Python code through the debugger. Use in trusted environments only.

## Installation

Works best with [uv](https://docs.astral.sh/uv/getting-started/features/)

### Claude Code
```bash
# Install the MCP server
claude mcp add mcp-pdb -- uv run --with mcp-pdb mcp-pdb
# or for poetry
claude mcp add mcp-pdb -- poetry run mcp-pdb

# Alternative: Install with specific Python version
claude mcp add mcp-pdb -- uv run --python 3.13 --with mcp-pdb mcp-pdb

# Note: The -- separator is required for Claude Code CLI
```

### Windsurf

```json
{
  "mcpServers": {
    "mcp-pdb": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "mcp-pdb",
        "mcp-pdb"
      ]
    }
  }
}

```

Or for poetry:

```json
        
{
  "mcpServers": {
    "mcp-pdb": {
      "command": "poetry",
      "args": [
        "run",
        "mcp-pdb"
      ]
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `start_debug(file_path, use_pytest, args, pytest_debug_mode)` | Start a debugging session for a Python file |
| `send_pdb_command(command)` | Send a command to the running PDB instance |
| `set_breakpoint(file_path, line_number)` | Set a breakpoint at a specific line |
| `clear_breakpoint(file_path, line_number)` | Clear a breakpoint at a specific line |
| `list_breakpoints()` | List all current breakpoints |
| `restart_debug()` | Restart the current debugging session |
| `examine_variable(variable_name)` | Get detailed information about a variable |
| `get_debug_status()` | Show the current state of the debugging session |
| `end_debug()` | End the current debugging session |

## Common PDB Commands

| Command | Description |
|---------|-------------|
| `n` | Next line (step over) |
| `s` | Step into function |
| `c` | Continue execution |
| `r` | Return from current function |
| `p variable` | Print variable value |
| `pp variable` | Pretty print variable |
| `b file:line` | Set breakpoint |
| `cl num` | Clear breakpoint |
| `l` | List source code |
| `q` | Quit debugging |

## Features

- Project-aware debugging with automatic virtual environment detection
- **Enhanced pytest integration** with multiple debugging modes:
  - `pdb`: Debug only on test failures (traditional `--pdb`)
  - `trace`: Hit a breakpoint at the start of each test (`--trace`)
  - `manual`: Traditional "stop when the process is up, so I can set breakpoints" (`python -m pdb -m pytest`)
- Automatic breakpoint tracking and restoration between sessions
- Works with UV, Poetry, and standard virtual environments
- Variable inspection with type information and attribute listing

## Pytest Debugging Modes

When using `start_debug()` with `use_pytest=True`, you can specify different debugging approaches:

### `pytest_debug_mode="pdb"` (Default)
```python
start_debug("test_file.py", use_pytest=True, pytest_debug_mode="pdb")
```
- Uses `pytest --pdb -s`
- Debugger activates **only on test failures**
- Best for: Finding and debugging failing tests

### `pytest_debug_mode="trace"`
```python
start_debug("test_file.py", use_pytest=True, pytest_debug_mode="trace")
```
- Uses `pytest --trace -s`
- Debugger activates **at the start of each test**
- Best for: Step-by-step debugging of individual tests

### `pytest_debug_mode="manual"` (Recommended for test suites)
```python
start_debug("test_file.py", use_pytest=True, pytest_debug_mode="manual", args="-k specific_test")
```
- Uses `python -m pdb -m pytest -s`
- **Full debugger control from the start**
- Set breakpoints with `b filename:line_number` before tests run
- Continue with `c` to run the test suite
- Only stops at your specific breakpoints, not every test
- Best for: Debugging test suites with specific code paths

## Troubleshooting

### Claude Code Installation Issues

If you encounter an error like:
```
MCP server "mcp-pdb" Connection failed: spawn /Users/xxx/.local/bin/uv run --python 3.13 --with mcp-pdb mcp-pdb ENOENT
```

Make sure to include the `--` separator when using `claude mcp add`:
```bash
# ✅ Correct
claude mcp add mcp-pdb -- uv run --with mcp-pdb mcp-pdb

# ❌ Incorrect (missing --)
claude mcp add mcp-pdb uv run --with mcp-pdb mcp-pdb
```

To verify your installation:
```bash
# Check if mcp-pdb is listed
claude mcp list | grep mcp-pdb

# Check server status in Claude Code
# Type /mcp in Claude Code to see connection status
```

## License

MIT License - See LICENSE file for details.
