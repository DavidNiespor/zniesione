#!/bin/sh
# Test funkcjonalny end-to-end (Linux, macOS, WSL, Git Bash). Na każdym systemie, także Windows: node tests/e2e/run.js
cd "$(dirname "$0")/../.." && exec node tests/e2e/run.js
