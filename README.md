# MCP-PDB: Interactive Python Debugging with Claude

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**MCP-PDB** seamlessly integrates Python's debugger (PDB) with the Claude AI assistant through the Multi-modal Chat Protocol (MCP), empowering you to debug complex Python code through natural language conversation.

## Key Features

- **Interactive Debugging**: Step through code, inspect variables, and set breakpoints using natural language
- **Conversational Interface**: Debug with Claude's assistance without memorizing PDB commands
- **Context-Aware**: Claude understands your code structure and debugging session state
- **Smart Breakpoints**: Easily manage breakpoints across files with tracking
- **Variable Inspection**: Examine complex data structures with detailed insights

## Getting Started

### Installation

```bash

```

### Basic Usage

1. Start the MCP server:
   ```bash
   mcp-pdb
   ```

2. Connect with Claude and start debugging:
   ```
   You: Debug my Python script at ~/projects/myapp/main.py
   Claude: I'll start a debugging session for that file. What would you like to focus on?

   You: Set a breakpoint on line 42 and run until there
   Claude: [Sets breakpoint and runs] Execution paused at line 42. Here's the current context...

   You: What's the value of user_data?
   Claude: The variable user_data is a dictionary with 3 keys: 'name', 'age', and 'preferences'...
   ```

## Example Commands

- "Debug my Python file at path/to/file.py"
- "Set a breakpoint at line 25"
- "Step through the next 5 lines"
- "What's the value of my_variable?"
- "Show me all local variables"
- "Continue execution until the next breakpoint"
- "Explain what's happening in this function"
- "Run pytest with debugging to fix test_<function_name>"

## Advanced Features

### Test Debugging

Debug tests easily with pytest integration:

```
You: Debug my test file tests/test_auth.py using pytest
Claude: Starting pytest with debugging for test_auth.py. What specific test are you interested in?

You: Run the test_login_failure test
Claude: [Runs test] Test paused at breakpoint in auth.py line 78. Here's what's happening...
```

### Variable Analysis

Explore complex data structures with Claude's analysis:

```
You: Examine the user_session object
Claude: The user_session object is an instance of Session class with the following properties:
- id: "sess_12345"
- authenticated: True
- permissions: A list of 5 permission strings ["read", "write", ...]
- data: A deeply nested dictionary containing user preferences and state
  ...
```

## Commands Reference

MCP-PDB supports all standard PDB commands through natural language, including:
- Navigation: step, next, continue, until, return
- Breakpoints: set, clear, list
- Inspection: print, examine, where, locals, globals
- Control: restart, quit

## Use Cases

- **Debugging Complex Logic**: Walk through intricate algorithms with step-by-step guidance
- **Learning New Codebases**: Explore unfamiliar code with Claude's explanations
- **Teaching Programming**: Perfect for mentoring as Claude explains what's happening
- **Finding Bugs**: Easily track down elusive bugs with intelligent variable inspection

## Development

For information about developing MCP-PDB, see [CLAUDE.md](CLAUDE.md).

## License

MIT License - See LICENSE file for details.

---

**Feedback and Contributions Welcome!** Open an issue or PR to help improve MCP-PDB.
