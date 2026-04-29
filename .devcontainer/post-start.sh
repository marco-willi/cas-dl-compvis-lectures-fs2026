#!/bin/bash
# Post-start command: Runs every time the container starts

set -e

echo "Running post-start tasks..."

# Ensure Poetry is on PATH (installed during post-create)
export PATH="$HOME/.local/bin:$PATH"

# Ensure .venv symlink points to the native-fs venv (survives container rebuilds)
VENV_REAL=$(poetry env info --path 2>/dev/null || true)
if [ -n "$VENV_REAL" ] && [ ! -L /workspace/.venv ]; then
    rm -rf /workspace/.venv
    ln -s "$VENV_REAL" /workspace/.venv
    echo "Re-linked .venv -> $VENV_REAL"
fi

# Redirect Quarto cache to native filesystem (avoids slow SQLite WAL on 9p)
# Always recreate the /tmp target — it is wiped on every container restart
mkdir -p /tmp/quarto-cache
if [ ! -L /workspace/.quarto ]; then
    rm -rf /workspace/.quarto
    ln -s /tmp/quarto-cache /workspace/.quarto
fi

# Install CLI tools
bash "$(dirname "$0")/cli-tools.sh"

echo ""
echo "Python : $(which python) ($(python --version 2>&1))"
echo "Poetry : $(poetry --version)"
echo "Venv   : /workspace/.venv -> $(readlink -f /workspace/.venv)"

echo ""
echo "Container ready!"
