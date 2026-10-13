# Zephyr in Artisyn — demo engagement

This folder sets up **Zephyr** as an engagement in a local Artisyn portal, with content like the portal's own Example Co and Single Co demos:

| Area | What the demo has |
|---|---|
| **Initiatives** | *Reliable live map* and *Flight insight*, both owned by the Flight Experience shaping team, plus the default Portfolio |
| **Goals** | 5 measurable goals (one closed, achieved) |
| **Problem Space** | 13 problems across triage, active, backlog, a draft, a declined one, a merged duplicate and a resolved one |
| **Solution Space** | 11 solutions (planning packages) across identified → shaped → accepted → committed → delivered, plus one dropped and one blocker |
| **Milestones** | 4 (achieved, missed, two planned, with solutions rolled up) |
| **Feedback** | 7 beta-tester reports across triage, in progress, ready to send and closed |
| Extras | tags, comment threads, Questions, Tasks |

**The delivery item for the demo** is the planning package **"Turn JetBlue callsigns red"**. It's a *committed* Solution owned by Map Squad, in the **Zephyr Web** delivery workspace, which points at this repository. It describes a small, real change: in `frontend/js/markers.js`, draw planes whose callsign matches `JBU*` in red on the map.

## Files

```
artisyn/
  engagement.json          the demo content: edit this to change what gets created
  scripts/
    reset_demo.sh          start over: rebuild the portal's data, then seed Zephyr
    seed_demo.py           create Zephyr through the portal's REST API
    show_connection.py     print (or --write) the MCP connection for a workspace
    artisyn_api.py         small REST client (Python standard library only)
```

No dependencies: Python 3.10+ is enough.

## One-time setup (artisyn-portal)

In `~/Code/artisyn-portal/backend/.env`:

```
ENVIRONMENT=development
CORS_ORIGIN=http://localhost:5173
DEMO_AUTH_ENABLED=true        # passwordless sign-in for MCP clients, local only
```

Then start the portal with `npm run dev` (frontend on :5173, backend on :3001).

## Run the demo, again and again

```bash
~/Code/zephyr/artisyn/scripts/reset_demo.sh          # portal data only
~/Code/zephyr/artisyn/scripts/reset_demo.sh --repo   # also put the Zephyr code back
```

What it does:
1. Runs the portal's `npm run demo:reset` script. That rebuilds the whole local database with Example Co, Single Co and Contoso Rail, and keeps the old database as `backend/data/artisyn.db.bak`.
2. Seeds Zephyr as **Allan** (`allan.wellenstein@dataart.com`), who is the global admin in the rebuilt data.
3. With `--repo`, also switches this repo to `main` and discards uncommitted changes under `frontend/` and `backend/`. Branches are left alone, so delete a demo branch yourself if one was created.

The data is stored in the portal's database file, so it **survives restarts**. Only a reset (or another `npm run demo:reset`) removes it.

Sign in at http://localhost:5173 as **`steve.wilson@dataart.com`**. That one login can shape work and deliver the JetBlue item, and it sees the other demo engagements too. The other Zephyr people are there for showing different roles:

| Person | Team (role) |
|---|---|
| **steve.wilson@dataart.com** | Global admin; Management, Flight Experience and Map Squad (admin) |
| priya.nair@dataart.com | Management (admin), Flight Experience (admin) |
| leo.grant@dataart.com | Flight Experience |
| ana.sousa@dataart.com | Map Squad (admin) |
| marcus.lee@dataart.com | Map Squad |
| tom.becker@dataart.com | Data Pipeline (admin) |
| hana.ito@dataart.com | Data Pipeline |

To seed without resetting (on a database that has no Zephyr yet): `python3 scripts/seed_demo.py --email <your admin address>`. It refuses to run if Zephyr already exists.

## Connect an MCP workspace

```bash
python3 scripts/show_connection.py --email steve.wilson@dataart.com          # print it
python3 scripts/show_connection.py --email steve.wilson@dataart.com --write  # save it
```

This prints the endpoint for the **Zephyr Web** workspace and the `claude mcp add` command for it. `--write` saves `.mcp.json` and `.artisyn/config.json` at the root of this repo instead. Then run `/mcp` in Claude Code and choose **Authenticate**. If you're signed in to the portal in that browser, it completes straight away.

**Each reset creates new workspace ids**, so run `show_connection.py --write` again after every reset and re-authenticate in `/mcp`.

## Why a reset rebuilds the whole database

The portal's API can't rebuild Zephyr in place:
- **Deleting an engagement keeps its URL taken.** The portal soft-deletes it, and the slug stays unique, so a new "Zephyr" can't be created at `/zephyr` afterwards. Don't delete Zephyr from the UI; reset instead.
- **Moved items can't be deleted.** A Solution that has left Identified can only be dropped, not deleted.

So the clean way to start over is the portal's own demo reset, followed by a fresh seed.

## Notes

- **Dates are the seed run's.** Events are stamped with the time of the seed run, not backdated the way Example Co's history is. Due dates and target dates come from `engagement.json` (October–December 2026).
- **Why people are added before they sign in.** The local login gives new users a time-based id, and the backend derives `users.id` from its first 8 characters (`backend/app/services/user_service.py:332`). After the first brand-new address, every new email signed in through the local login page fails with a 500. Adding people to a team first creates them with random ids, and signing in then activates them, so the seed does it in that order.
