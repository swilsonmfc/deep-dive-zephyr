#!/usr/bin/env python3
"""Print how to connect an MCP client to one of the Zephyr engagement's workspaces.

Looks the engagement up on the portal and prints, for the chosen workspace (the
"Zephyr Web" delivery workspace unless --workspace names another):

- the workspace's MCP endpoint, on the frontend origin (http://localhost:5173), which
  Vite proxies to the backend. Sign-in only completes on that one origin, and the
  trailing slash matters: without it the request reaches the unscoped server, which
  lists no tools;
- the `claude mcp add` command for Claude Code;
- the `.artisyn/config.json` binding the Artisyn delivery loop reads.

With --write it saves `.mcp.json` and `.artisyn/config.json` at the root of the
Zephyr repository (the folder above this one), so Claude Code started there finds
the server. Neither file holds a secret; the OAuth token stays in Claude Code.

    python3 scripts/show_connection.py --email you@dataart.com
    python3 scripts/show_connection.py --email you@dataart.com --workspace "Zephyr Data" --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artisyn_api import DEFAULT_PORTAL_URL, ArtisynClient  # noqa: E402

FOLDER = Path(__file__).resolve().parent.parent
REPO_ROOT = FOLDER.parent
DATA_FILE = FOLDER / "engagement.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--email", default=os.environ.get("ARTISYN_EMAIL"), help="your portal user (or ARTISYN_EMAIL)")
    parser.add_argument("--portal", default=os.environ.get("ARTISYN_PORTAL_URL", DEFAULT_PORTAL_URL), help="portal API base URL")
    parser.add_argument("--app-url", default="http://localhost:5173", help="the portal's frontend origin")
    parser.add_argument("--workspace", default="Zephyr Web", help="workspace name")
    parser.add_argument("--server-name", default="artisyn-zephyr", help="MCP server name to register")
    parser.add_argument("--write", action="store_true", help="write .mcp.json and .artisyn/config.json in the repo")
    args = parser.parse_args()
    if not args.email:
        parser.error("--email is required (or set ARTISYN_EMAIL)")

    slug = json.loads(DATA_FILE.read_text(encoding="utf-8"))["engagement"]["slug"]
    client = ArtisynClient(args.portal)
    client.sign_in(args.email)
    engagement = client.find_engagement(slug)
    if engagement is None:
        print(f"No engagement /{slug} that {args.email} can see. Run scripts/seed_demo.py first.")
        return 1

    workspaces = client.get(f"/api/engagements/{engagement['id']}/workspaces")
    print(f"Engagement {engagement['name']}: {args.app_url}/engagements/{engagement['slug']} (id {engagement['id']})")
    print("Workspaces:")
    for ws in workspaces:
        print(f"  {ws['name']:<20} {ws['type']:<9} {args.app_url}/mcp/w/{ws['id']}/")

    chosen = next((ws for ws in workspaces if ws["name"].lower() == args.workspace.lower()), None)
    if chosen is None:
        print(f"\nNo workspace named {args.workspace!r}.")
        return 1
    endpoint = f"{args.app_url}/mcp/w/{chosen['id']}/"
    mcp_json = {"mcpServers": {args.server_name: {"type": "http", "url": endpoint}}}
    binding = {
        "instanceUrl": f"{args.app_url}/",
        "engagementId": engagement["id"],
        "mcpServerName": args.server_name,
        "environment": "dev",
        "artifactSetVersion": "1",
    }

    print(f"\nConnect Claude Code to {chosen['name']}:")
    print(f"  claude mcp add --transport http {args.server_name} {endpoint}")
    print("  then run /mcp in Claude Code and choose Authenticate. A browser opens; if you are")
    print("  signed in to the portal there it completes at once, otherwise enter your email.")
    print("  (Needs DEMO_AUTH_ENABLED=true in artisyn-portal/backend/.env.)")
    print("\n.mcp.json:")
    print(json.dumps(mcp_json, indent=2))
    print("\n.artisyn/config.json:")
    print(json.dumps(binding, indent=2))

    if args.write:
        (REPO_ROOT / ".mcp.json").write_text(json.dumps(mcp_json, indent=2) + "\n", encoding="utf-8")
        (REPO_ROOT / ".artisyn").mkdir(exist_ok=True)
        (REPO_ROOT / ".artisyn" / "config.json").write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {REPO_ROOT / '.mcp.json'} and {REPO_ROOT / '.artisyn' / 'config.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
