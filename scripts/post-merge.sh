#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Dependency installation is handled by the existing Streamlit workflow.
# Keep the merge hook fast and non-interactive while still catching syntax
# errors introduced by merged Python files.
python -m compileall -q .