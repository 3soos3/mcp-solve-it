# Troubleshooting Guide

Common issues when running, configuring, or extending the SOLVE-IT MCP Server.

> **Note:** Commands in this guide use `python -m mcp_chassis`. If you haven't installed the package with `pip install -e .`, use `python3 run.py` from the project root as a drop-in replacement — it accepts the same arguments.

---

## SOLVE-IT-Specific Issues

---

## Issue S1: Knowledge Base Fails to Load at Startup

**Symptom:** The server starts, but most SOLVE-IT tools are missing from the tool list. Calling `solveit_status` returns `{"status": "error", "error": "..."}`.

**Causes and fixes:**

1. **Wrong `solveit_data_path` in config.** The path in `config/default.toml` must point to the root of the SOLVE-IT repository (the directory that contains the `data/` folder and the `solve_it_library` package). Use an absolute path to avoid ambiguity:
   ```toml
   [app]
   solveit_data_path = "/absolute/path/to/solve-it"
   ```

2. **`solve_it_library` package not importable.** The init hook adds `solveit_data_path` to `sys.path` at runtime. If the library is not in that directory, the import will fail. Verify:
   ```bash
   python -c "import sys; sys.path.insert(0, '/path/to/solve-it'); from solve_it_library import KnowledgeBase; print('OK')"
   ```

3. **Wrong `objective_mapping` file name.** The mapping file must exist in the `data/` subdirectory of the SOLVE-IT repository. The default is `solve-it.json`. List available mappings:
   ```bash
   ls /path/to/solve-it/data/*.json
   ```

4. **Check startup logs for the exact error.** Run with debug logging:
   ```bash
   python -m mcp_chassis --config config/default.toml --log-level DEBUG 2>&1 | head -80
   ```
   Search for `Failed to load SOLVE-IT KB` in the output.

---

## Issue S2: Only `solveit_status` Appears in Tool List

**Symptom:** The tool list contains `solveit_status` and `__health_check` but none of the other SOLVE-IT tools (`solveit_get_technique`, `solveit_search`, etc.).

**Cause:** The KnowledgeBase failed to load. `solveit_status` is registered unconditionally; all other tools are skipped when `server._kb` is `None`.

**Fix:** Resolve the KB load failure first (see Issue S1 above). Once `solveit_status` returns `{"status": "ok", ...}`, all tools will be present.

---

## Issue S3: `solveit_search` Returns No Results

**Symptom:** Calling `solveit_search` with expected keywords returns an empty list.

**Causes and fixes:**

1. **Strict sanitization strips search characters.** The `strict` security profile removes shell metacharacters, quotes, and some punctuation from string inputs before they reach the handler. Switch to `moderate` sanitization:
   ```toml
   [security.input_sanitization]
   level = "moderate"
   ```

2. **`search_logic = "AND"` with multiple keywords is too restrictive.** The default is AND — all keywords must appear. Try OR logic by asking the LLM to use `search_logic = "OR"`, or set the default in config by hiding the parameter and adjusting the handler behavior.

3. **Word-boundary matching is filtering out partial matches.** The default `substring_match = false` requires whole-word matches. Set `substring_match = true` for partial matching.

---

## Issue S4: Tools Return `{"error": "not_found"}` for Valid IDs

**Symptom:** Calling `solveit_get_technique` with a known ID like `DFT-1001` returns `{"error": "not_found", "id": "DFT-1001"}`.

**Causes and fixes:**

1. **ID case sensitivity.** IDs are case-sensitive. Ensure the ID matches exactly (e.g. `DFT-1001` not `dft-1001`).

2. **Wrong KB data version.** The technique may not exist in the version of the SOLVE-IT data currently loaded. Use `solveit_list_techniques` to see all available IDs.

3. **Strict sanitization modified the ID.** The `-` in IDs like `DFT-1001` is safe, but if an ID somehow contains other characters, strict sanitization may alter it. Check by temporarily switching to `moderate` sanitization.

---

## Issue S5: `solveit_status` Shows Wrong Item Counts

**Symptom:** The `techniques`, `weaknesses`, or `mitigations` counts in `solveit_status` do not match what is expected for the current SOLVE-IT version.

**Causes and fixes:**

1. **Wrong data directory.** Verify `solveit_data_path` points to the correct SOLVE-IT version.

2. **Extensions not loading.** If `enable_extensions = true` but `extensions` is not in the `solveit_status` response, the SOLVE-IT-X extension data failed to load. Check logs for extension load errors at startup.

3. **Stale `__pycache__`.** Old cached `.pyc` files may prevent the latest KB code from loading:
   ```bash
   find /path/to/solve-it -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
   ```
   Then restart the server.

---

## Issue S6: Init Hook Failure

**Symptom:** Server exits immediately with a message like `Exiting: init_required=true and KB failed to load`.

**Cause:** `init_required = true` in `config/default.toml` causes the server to exit rather than start in degraded mode when the KB fails to load.

**Fix:** Either resolve the KB load failure (see Issue S1), or set `init_required = false` to allow the server to start in degraded mode (useful for development and testing):

```toml
[app]
init_required = false
```

In degraded mode, only `solveit_status` is available. It will report the load error so you can diagnose the problem.

---

## Issue S7: Extension Not Being Discovered

**Symptom:** A new tool/resource/prompt is not appearing in the server's tool list.

**Causes and fixes:**

1. **Missing `register()` function.** The extension file must define `def register(server)`. Check spelling — it must be exactly `register`.

2. **`auto_discover = false` in config.** Ensure auto-discovery is enabled:
   ```toml
   [extensions]
   auto_discover = true
   ```

3. **File named `__init__.py`.** Files named `__init__.py` are excluded from discovery. Rename your file.

4. **File in wrong directory.** Tools must go in `extensions/tools/`, resources in `extensions/resources/`, prompts in `extensions/prompts/`. Files in the `extensions/` root are NOT discovered.

5. **Syntax error in the extension file.** Run:
   ```bash
   python -c "import mcp_chassis.extensions.tools.solveit_tools"
   ```
   This will show the syntax error directly.

6. **Check logs for discovery errors:**
   ```bash
   python -m mcp_chassis --log-level DEBUG 2>&1 | grep extension
   ```

---

## General Server Issues

---

## Issue 1: Server Starts But Client Receives No Response

**Symptom:** The MCP client connects but never receives a response to `initialize`.

**Causes and fixes:**

1. **Log output going to stdout.** MCP requires stdout to be reserved for JSON-RPC. Check that logging is configured to write to stderr only. The server does this by default. If you added custom logging, ensure it uses `logging.StreamHandler(sys.stderr)`.

2. **Extension crashing on import.** A bad extension can crash the server before it processes any messages. Run:
   ```bash
   python -m mcp_chassis --config config/default.toml --log-level DEBUG 2>&1 | head -50
   ```
   Look for `ERROR` lines about extension loading.

3. **Config file not found.** If the config path is wrong, the server exits silently. Check the exit code: `echo $?` after starting the server.

---

## Issue 2: TOML Config Errors

**Symptom:** Server exits with a `TOML parse error` or `KeyError` traceback.

**Causes and fixes:**

1. **Syntax error in `config/default.toml`.** Validate the TOML file:
   ```bash
   python -c "import tomllib; tomllib.load(open('config/default.toml', 'rb'))"
   ```
   Python 3.11+ includes `tomllib`. For earlier versions: `pip install tomli`.

2. **Wrong type for a boolean value.** TOML booleans must be bare `true`/`false`, not quoted:
   ```toml
   # Correct
   enable_extensions = true
   # Wrong
   enable_extensions = "true"
   ```

3. **Unrecognized `[app]` key.** The init hook logs a warning (not an error) for unrecognized keys in `[app]`. Check startup logs for `Unrecognized [app] config key` warnings.

---

## Issue 3: Rate Limit Exceeded Immediately

**Symptom:** Tools return `RATE_LIMIT_EXCEEDED` on the first call.

**Causes and fixes:**

1. **Burst size is 0.** In `config/default.toml`, ensure `burst_size` is at least 1. The default is 10.

2. **Rate limiting is overly strict for development.** Set `profile = "permissive"` in `config/default.toml` during development, or use the env var:
   ```bash
   MCP_RATE_LIMIT_ENABLED=false python -m mcp_chassis
   ```

---

## Issue 4: Input Validation Rejects Valid Arguments

**Symptom:** Tool calls fail with `VALIDATION_ERROR` even with correct arguments.

**Causes and fixes:**

1. **String too long.** The default `max_string_length` is 10,000 characters. Increase it:
   ```toml
   [security.input_validation]
   max_string_length = 100000
   ```

2. **Array too long.** Default `max_array_length` is 100.

3. **Schema mismatch.** The registered input schema must match what the client sends. This is most commonly an issue with custom extensions, not built-in SOLVE-IT tools.

---

## Issue 5: Sanitization Strips Expected Characters

**Symptom:** Tool receives modified input — slashes, quotes, or special characters are removed.

**Causes and fixes:**

1. **Strict sanitization removes shell metacharacters.** Switch to `moderate` or `permissive`:
   ```toml
   [security.input_sanitization]
   level = "moderate"
   ```

2. **Path traversal sequences are stripped.** `../` sequences are removed in `strict` and `moderate` modes.

3. **Control characters are removed.** Only `strict` mode removes newlines inside strings.

---

## Issue 6: Server Crashes on Startup with `FileNotFoundError`

**Symptom:** Server exits with a traceback mentioning a missing config file.

**Fix:** The config path must be absolute or relative to the current working directory. From the repo root:
```bash
python -m mcp_chassis --config config/default.toml
```

From another directory, use an absolute path:
```bash
python -m mcp_chassis --config /path/to/repo/config/default.toml
```

Or set the env var:
```bash
MCP_CHASSIS_CONFIG=/path/to/config.toml python -m mcp_chassis
```

---

## Issue 7: Docker Container Exits Immediately

**Symptom:** `docker run` exits without processing any messages.

**Causes and fixes:**

1. **No stdin attached.** MCP servers require an interactive stdin pipe. Use `-i`:
   ```bash
   docker run -i my-mcp-server
   ```

2. **Config file not found in container.** The default config is at `/app/config/default.toml` inside the container (set via `MCP_CHASSIS_CONFIG`). Mount a custom config if needed:
   ```bash
   docker run -i -v $(pwd)/config/my-config.toml:/app/config/default.toml my-mcp-server
   ```

3. **`solveit_data_path` points outside the container.** If you mount SOLVE-IT data into the container, ensure the path in the TOML (or `MCP_APP_SOLVEIT_DATA_PATH`) matches the mount point inside the container.

4. **Startup error.** Add `--log-level DEBUG` to see startup errors:
   ```bash
   docker run -i my-mcp-server --log-level DEBUG
   ```

---

## Issue 8: `ModuleNotFoundError` for `mcp_chassis`

**Symptom:** `python -m mcp_chassis` fails with `No module named mcp_chassis`.

**Fix:** The package is not installed. Install it in editable mode:
```bash
pip install -e ".[dev]"
```

---

## Issue 9: Health Check Shows Wrong Tools

**Symptom:** `__health_check` output lists unexpected tools or is missing expected ones.

**Causes and fixes:**

1. **Extensions loaded from a previous run cached in `__pycache__`.** Clear cache:
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
   ```

2. **`auto_discover = false`** — extensions won't load. See Issue S7.

3. **Extension failed silently.** Check logs for `ERROR` messages during startup.

---

## Issue 10: `asyncio.TimeoutError` in Integration Tests

**Symptom:** Integration tests time out waiting for the server subprocess to respond.

**Causes and fixes:**

1. **Server not starting fast enough.** Increase the startup timeout in the test fixture. The default is 15 seconds.

2. **Server crashing on startup.** Run the server manually to see error output:
   ```bash
   python -m mcp_chassis --config config/default.toml --log-level DEBUG 2>&1
   ```

3. **Server writing debug logs to stdout.** If any code writes to `stdout` (e.g., a `print()` statement), the test client may misinterpret it as a JSON-RPC message. Search for `print(` in extension code.

---

## Issue 11: Token Auth Rejected on Stdio

**Symptom:** Server raises `ValueError: Token auth is not supported on stdio transport`.

**Fix:** Disable auth for stdio transport:
```toml
[security.auth]
enabled = false
provider = "none"
```

Token auth is not meaningful over stdio pipes — the OS provides process-level isolation instead.

---

## Enabling Debug Logging

To see all server internals:
```bash
python -m mcp_chassis --log-level DEBUG 2>debug.log
```

The log is JSON-structured. Filter for specific loggers:
```bash
python -m mcp_chassis --log-level DEBUG 2>&1 | python -c "
import sys, json
for line in sys.stdin:
    try:
        r = json.loads(line)
        if 'extension' in r.get('logger', ''):
            print(line, end='')
    except:
        pass
"
```

## Quick Reference

| Problem | Quick Fix |
|---|---|
| KB not loading | Check `solveit_data_path` in TOML — use absolute path |
| Only `solveit_status` available | KB failed to load — resolve Issue S1 first |
| Empty search results | Try `search_logic = "OR"` or `substring_match = true` |
| `not_found` for valid ID | Check case: IDs are uppercase (e.g. `DFT-1001`) |
| Config parse error | Validate TOML: `python -c "import tomllib; tomllib.load(open('config/default.toml','rb'))"` |
| Extension not discovered | Confirm file defines `def register(server)` in correct subdirectory |
| Module not found | `pip install -e ".[dev]"` |
| Rate limit hit | `profile = "permissive"` in TOML or `MCP_RATE_LIMIT_ENABLED=false` |
| Docker exits immediately | Add `-i` flag; check `solveit_data_path` inside container |
