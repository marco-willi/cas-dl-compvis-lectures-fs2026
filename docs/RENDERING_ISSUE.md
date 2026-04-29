# Quarto Render Hangs — Root Cause Analysis

## Symptom

`quarto render` hangs or takes an extremely long time to start (minutes instead of seconds). The Deno process enters D-state (uninterruptible sleep) waiting on 9p filesystem calls.

## Root Cause

**Quarto scans the entire project directory tree** — not just the files listed under `project.render` — to discover resources, dependencies, and metadata. This scan includes `.venv/`, which contains **tens of thousands of files** (PyTorch alone has thousands of subdirectories).

The workspace is mounted via **9p filesystem** (WSL2 drvfs → Windows `D:\`). Each `openat()` / `stat()` call on 9p is an order of magnitude slower than on a native Linux filesystem. Combined with the massive `.venv/` tree, the directory scan takes minutes or blocks entirely — the Deno process gets stuck in `p9_client_rpc` kernel calls.

```
D:\ on /workspace type 9p (rw,noatime,...,msize=65536,trans=fd)
```

### Why it "used to work"

This likely started or worsened when heavy packages (PyTorch, SymPy, etc.) were added to the venv, dramatically increasing the number of files Quarto must scan on the slow 9p mount.

## Evidence

1. **strace** shows Quarto scanning every subdirectory under `.venv/lib/python3.14/site-packages/torch/`:

   ```
   openat(AT_FDCWD, ".venv/lib/python3.14/site-packages/torch/_dynamo/...", O_RDONLY|O_DIRECTORY) = 31
   ```

   45,000+ `openat()` calls logged before the process blocked.

2. **Process state**: `cat /proc/<pid>/wchan` → `p9_client_rpc` (blocked on 9p filesystem RPC).

3. **Rendering from native filesystem works instantly**:

   ```bash
   # Copy project (without .venv) to /tmp → renders in ~3 seconds
   cp essential files to /tmp/quarto-test
   cd /tmp/quarto-test && quarto render index.qmd --no-execute
   # Output created: _output/index.html  ✓
   ```

4. **Quarto has no project-level directory ignore** ([docs](https://quarto.org/docs/reference/projects/options.html)). The `render:` exclusion (`!.venv/**`) only controls which files get rendered, not which directories get scanned for resources.

## Environment

| Component       | Value                              |
| --------------- | ---------------------------------- |
| Quarto          | 1.8.27                             |
| OS              | Linux 6.6.87 (WSL2)                |
| Workspace mount | 9p (drvfs, Windows D:)             |
| Python venv     | `.venv/` with PyTorch, SymPy, etc. |

## Solutions

### Option 1 — Render via `/tmp` (recommended, implemented in Makefile)

Copy the project (excluding `.venv` and heavy non-essential dirs) to the native Linux filesystem, render there, and copy output back:

```makefile
render:
	rm -rf /tmp/quarto-build/_output
	rsync -a --exclude='.venv' --exclude='demos' --exclude='.git' \
	    --exclude='_output' --exclude='.quarto' \
	    /workspace/ /tmp/quarto-build/
	cd /tmp/quarto-build && quarto render
	rsync -a /tmp/quarto-build/_output/ /workspace/_output/
```

### Option 2 — Move `.venv` to native filesystem

Keep the repo on 9p but move the venv to the Linux filesystem. Poetry/pip write there once; Quarto scans it fast.

```bash
# Move venv to native filesystem, symlink back
mv /workspace/.venv /home/vscode/.venv-native
ln -s /home/vscode/.venv-native /workspace/.venv
```

Add to `post-create.sh` to make persistent:

```bash
poetry config virtualenvs.path /home/vscode/.venvs
```

### Option 3 — Move entire repo to WSL2-native path

Store the repository on the Linux filesystem (`~/projects/`) instead of on the Windows drive. Best overall performance.

## Cleanup

After a hung render, stale Deno processes may remain:

```bash
kill -9 $(pgrep -f "quarto.js") 2>/dev/null
kill -9 $(pgrep -f "deno") 2>/dev/null
rm -rf /workspace/.quarto
```
