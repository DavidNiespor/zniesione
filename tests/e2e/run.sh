#!/bin/sh
# Test funkcjonalny end-to-end. Wymaga: python, node, `npm i jsdom` (w tests/e2e lub globalnie z NODE_PATH).
set -e
cd "$(dirname "$0")/../.."
export DATABASE=/tmp/zn_e2e.db SECRET_KEY=e2e DEVICE_BASE=http://127.0.0.1:9000
rm -f "$DATABASE"
python tools/fake_device.py 9000 & FD=$!
python -m flask --app zniesione seed-demo
python -m gunicorn -b 127.0.0.1:8765 -w 1 'zniesione:create_app()' >/tmp/zn_e2e.log 2>&1 & GU=$!
trap 'kill $FD $GU 2>/dev/null' EXIT
sleep 2
node tests/e2e/e2e.js
