#!/bin/bash
# SessionStart hook: prepare a Claude Code on the web container to run this
# project's CLI, tests and linter.
#
# The engine itself needs only PyYAML, but tests import the package and the
# `trailguide` command, so an editable install is the simplest thing that makes
# every documented command work from a fresh container.
set -euo pipefail

# Local machines are already set up by their owner; only configure web sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

echo "[trailguide] installing project and dev dependencies..."

# Editable install brings in PyYAML and puts the `trailguide` CLI on PATH.
# Idempotent: re-running simply refreshes the install.
python3 -m pip install --quiet --disable-pip-version-check -e ".[dev]"

# Linter is not a runtime dependency but is expected by the contributing flow.
python3 -m pip install --quiet --disable-pip-version-check ruff

# Tests import the package from src/ and their shared fixtures from tests/,
# so both need to be importable no matter which directory a command runs from.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR}/src:${CLAUDE_PROJECT_DIR}/tests\"" >> "$CLAUDE_ENV_FILE"
fi

echo "[trailguide] ready. Run the test suite with:"
echo "    python3 -m unittest discover -s tests -p 'test_*.py'"
