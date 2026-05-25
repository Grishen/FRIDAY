# Sandboxed PC file & launch tools (brain)

When **`JARVIS_FILE_TOOLS=1`**, the OpenAI brain can call:

| Tool | Purpose |
|------|---------|
| `system_open_path` | Opens a folder or file with the OS default (Explorer / `open` / `xdg-open`). |
| `system_list_directory` | Lists immediate children under a folder (bounded count). |
| `system_read_text_preview` | Reads a UTF-8 text excerpt (byte + line capped). |
| `system_delete_paths` | Deletes **files**, optionally removes **empty directories** only. |
| `system_launch_path_executable` | Runs a single binary found on **`PATH`** by short name (extra flag below). |

## Sandboxing (critical)

Resolved paths **must** lie inside one root from **`JARVIS_TOOL_PATH_ROOTS`**.

- Use **`|`** to separate roots, e.g.  
  `%USERPROFILE%\Downloads\FridayWork|%USERPROFILE%\Documents\JarvisSafe`
- If **`JARVIS_TOOL_PATH_ROOTS`** is unset, only repo **`data/jarvis_workspace/`** is allowed — create/move files there, or widen roots deliberately.

Certain system trees are **always rejected** after `resolve()`, even if you misconfigure overlapping roots (`SystemRoot`, `ProgramFiles`, `/System`, …).

## Deletes

Deletes require **`user_explicitly_confirmed_delete: true`** on the API call — the assistant should **only** set this after you **verbally** ordered removal of **those paths**.  

Real enforcement remains **sandbox + blocklist** plus optional **large-file skip** defaults.

Relevant knobs:

| Env | Meaning |
|-----|---------|
| `JARVIS_SKIP_LARGE_DELETE` | Default `1` — skip deletes over `JARVIS_LARGE_FILE_DELETE_BYTES` (~100 MB default). |
| `JARVIS_LARGE_FILE_DELETE_BYTES` | Override size ceiling. |

Recursive directory wipe is intentionally **not** exposed.

## PATH executables (optional extra risk)

Requires **`JARVIS_ALLOW_PATH_EXECUTABLES=1`** alongside **`JARVIS_FILE_TOOLS=1`**.

Only whitelist-safe short names `[A-Za-z0-9._-]{1,96}` that register on **`shutil.which`**.  

No arguments — avoids “helpful” command injection chains.

## Why not “anything on the PC?”

Giving the LLM arbitrary shell + unrestricted paths converts misheard phrases or manipulated prompts into data loss **fast**. Narrow tools + sandbox + configurable roots approximate “reasonable autonomy” without silent global `rm`.

## PyInstaller reminder

Extend **`jarvis_shell.spec`** `hiddenimports` with `jarvis_system_tools` after freezing.
