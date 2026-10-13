#!/usr/bin/env bash
# Put the Zephyr demo back to its starting point, ready to deliver again.
#
#   1. Rebuilds the portal's local database with `npm run demo:reset` (Example Co,
#      Single Co and Contoso Rail; the previous database is kept as
#      backend/data/artisyn.db.bak). Zephyr goes with it.
#   2. Seeds the Zephyr engagement again (scripts/seed_demo.py), as Allan, the
#      global admin in the rebuilt database.
#   3. With --repo, also puts the Zephyr code back: switches to main and discards
#      uncommitted changes under frontend/ and backend/. Branches are left alone.
#
# The portal backend must be running (`npm run dev` in artisyn-portal).
#
#   scripts/reset_demo.sh            # portal data only
#   scripts/reset_demo.sh --repo     # portal data and the Zephyr working tree
#
# Environment: ARTISYN_PORTAL_DIR (default ~/Code/artisyn-portal),
#              ARTISYN_EMAIL (default allan.wellenstein@dataart.com),
#              ARTISYN_PORTAL_URL (default http://localhost:3001).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
portal="${ARTISYN_PORTAL_DIR:-$HOME/Code/artisyn-portal}"
email="${ARTISYN_EMAIL:-allan.wellenstein@dataart.com}"

if [[ ! -f "$portal/backend/scripts/reset_ux_lab_demo.py" ]]; then
  echo "No artisyn-portal checkout at $portal. Set ARTISYN_PORTAL_DIR." >&2
  exit 1
fi

echo "== Rebuilding the portal's local database"
(cd "$portal/backend" && ./venv/bin/python scripts/reset_ux_lab_demo.py)

echo "== Seeding Zephyr"
python3 "$here/seed_demo.py" --email "$email"

if [[ "${1:-}" == "--repo" ]]; then
  echo "== Resetting the Zephyr working tree"
  git -C "$repo" switch main
  git -C "$repo" restore --staged --worktree -- frontend backend
fi

echo
echo "Ready. Sign in at http://localhost:5173 as steve.wilson@dataart.com (or any Zephyr person in the README)."
echo "MCP for the Zephyr Web workspace: python3 $here/show_connection.py --email steve.wilson@dataart.com --write"
