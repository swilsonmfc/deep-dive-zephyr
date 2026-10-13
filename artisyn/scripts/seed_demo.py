#!/usr/bin/env python3
"""Create the Zephyr demo engagement in a local Artisyn portal.

Replays ``engagement.json`` through the portal's REST API: the engagement, its
workspaces and teams, the demo people, then Connect content (Initiatives, Goals,
Problems, Solutions, Milestones, Feedback, tags, comments, Questions and Tasks),
moved through their lifecycles so every board has items in several stages.

Each step is done by the person the portal requires for it: Management work by the
operator or Priya, delivery acceptance by the delivery team's lead, so the
activity history reads like a real engagement. Everything lands in the portal's
database, so it survives restarts.

Usage (the portal must be running with ``npm run dev``):

    python3 scripts/seed_demo.py --email you@dataart.com

``--email`` is your own portal user. It must have signed in once and hold the
global ``admin`` role; the script adds ``engagement-creator`` if it is missing.

It refuses to run when the engagement already exists. The API cannot rebuild it in
place: a deleted engagement keeps its URL (the portal soft-deletes it and the slug
stays unique), and a Solution that has left Identified can only be dropped, not
deleted. ``scripts/reset_demo.sh`` starts over instead, by rebuilding the portal's
whole local database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from artisyn_api import DEFAULT_PORTAL_URL, ArtisynClient  # noqa: E402

DATA_FILE = Path(__file__).resolve().parent.parent / "engagement.json"


def ref(on: dict[str, str]) -> tuple[str, str]:
    """``{"solution": "s-x"}`` → ``("solution", "s-x")``."""
    ((kind, key),) = on.items()
    return kind, key


class Seeder:
    def __init__(self, operator: ArtisynClient, data: dict[str, Any]) -> None:
        self.operator = operator
        self.data = data
        self.base_url = operator.base_url
        self.clients: dict[str, ArtisynClient] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.ids: dict[str, str] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.team_lead: dict[str, str] = {}
        self.engagement: dict[str, Any] = {}
        self.people = {person["key"]: person for person in data["people"]}

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def path(self) -> str:
        return f"/api/engagements/{self.engagement['id']}"

    @property
    def connect(self) -> str:
        return f"{self.path}/connect"

    def who(self, person: str | None) -> ArtisynClient:
        return self.operator if person in (None, "operator") else self.clients[person]

    def id_of(self, key: str) -> str:
        return self.ids[key]

    def step(self, message: str) -> None:
        print(f"• {message}")

    # ── setup ────────────────────────────────────────────────────────────────

    def create_engagement(self) -> None:
        spec = self.data["engagement"]
        body = {k: v for k, v in spec.items() if k not in ("slug", "sizeBudgetUnit")}
        self.engagement = self.operator.post("/api/engagements", body)
        if self.engagement["slug"] != spec["slug"]:
            print(f"  note: the portal gave this engagement /{self.engagement['slug']}, not /{spec['slug']}")
        self.step(f"Engagement {self.engagement['name']} ({self.engagement['id']}, /{self.engagement['slug']})")
        if spec.get("sizeBudgetUnit"):
            self.operator.put(f"{self.connect}/settings", {"sizeBudgetUnit": spec["sizeBudgetUnit"]})

    def sign_in_people(self) -> None:
        """Sign each demo person in; they act in their own name from here on."""
        for person in self.data["people"]:
            client = ArtisynClient(self.base_url)
            self.users[person["key"]] = client.sign_in_person(person["email"], person["firstName"], person["lastName"])
            self.clients[person["key"]] = client
            if person.get("globalRoles"):
                # The operator is a global admin, so it can grant platform roles.
                self.operator.patch(f"/api/admin/users/{self.users[person['key']]['id']}", {"roles": person["globalRoles"]})
        self.step(f"{len(self.clients)} demo people signed in: {', '.join(p['email'] for p in self.data['people'])}")

    def create_workspaces(self) -> None:
        for ws in self.data["workspaces"]:
            body = {k: v for k, v in ws.items() if k != "key"}
            self.ids[ws["key"]] = self.operator.post(f"{self.path}/workspaces", body)["id"]
        self.step(f"{len(self.data['workspaces'])} workspaces")

    def create_teams(self) -> None:
        """Staff the teams.

        The engagement comes with its Management team, and each new workspace with a
        team of its own ("<workspace> Team", the operator its admin). Those are reused
        and renamed rather than duplicated; the operator then leaves every team but
        Management, so the demo people hold the seats.
        """
        existing = self.operator.get(f"{self.path}/teams")
        me = self.operator.user["id"]
        for team in self.data["teams"]:
            if team.get("management"):
                team_id = next(t["id"] for t in existing if t["type"] == "management")
            else:
                workspace_id = self.id_of(team["workspace"])
                created = next(
                    (t for t in existing if t["workspaceId"] == workspace_id and t["type"] == team["type"]), None
                )
                if created is None:
                    body = {"name": team["name"], "type": team["type"], "workspaceId": workspace_id}
                    team_id = self.operator.post(f"{self.path}/teams", body)["id"]
                else:
                    team_id = created["id"]
                    self.operator.put(f"{self.path}/teams/{team_id}", {"name": team["name"]})
            self.ids[team["key"]] = team_id
            for member in team.get("members", []):
                email = self.people[member["person"]]["email"]
                self.operator.post(f"{self.path}/teams/{team_id}/members", {"email": email, "role": member.get("role")})
                if member.get("role") == "admin" and team["key"] not in self.team_lead:
                    self.team_lead[team["key"]] = member["person"]
            if not team.get("management"):
                seated = self.operator.get(f"{self.path}/teams")
                if any(m["userId"] == me for t in seated if t["id"] == team_id for m in t["members"]):
                    self.operator.delete(f"{self.path}/teams/{team_id}/members/{me}")
        self.step(f"{len(self.data['teams'])} teams with their members")

    def create_initiatives(self) -> None:
        for initiative in self.data["initiatives"]:
            body = {"name": initiative["name"], "description": initiative.get("description", "")}
            if initiative.get("ownerTeam"):
                body["ownerTeamId"] = self.id_of(initiative["ownerTeam"])
            self.ids[initiative["key"]] = self.operator.post(f"{self.connect}/initiatives", body)["id"]
        for tag in self.data.get("tags", []):
            self.ids[tag["key"]] = self.operator.post(f"{self.connect}/tags", {"name": tag["name"], "lists": tag["lists"]})["id"]
        self.step(f"{len(self.data['initiatives'])} Initiatives and {len(self.data.get('tags', []))} tags")

    # ── Connect content ──────────────────────────────────────────────────────

    def create_goals(self) -> None:
        for goal in self.data["goals"]:
            body = {"title": goal["title"], "description": goal.get("description", "")}
            if goal.get("initiative"):
                body["ownerInitiativeId"] = self.id_of(goal["initiative"])
            created = self.who(goal.get("as", "priya")).post(f"{self.connect}/goals", body)
            self.ids[goal["key"]] = created["id"]
        self.step(f"{len(self.data['goals'])} Goals")

    def create_milestones(self) -> None:
        for milestone in self.data["milestones"]:
            body = {k: milestone[k] for k in ("title", "description", "targetDate") if k in milestone}
            self.ids[milestone["key"]] = self.who(milestone.get("as", "priya")).post(f"{self.connect}/milestones", body)["id"]
        self.step(f"{len(self.data['milestones'])} Milestones")

    def create_problems(self) -> None:
        for problem in self.data["problems"]:
            body: dict[str, Any] = {
                "title": problem["title"],
                "description": problem.get("description", ""),
                "ownerInitiativeId": self.id_of(problem["initiative"]),
                "submit": not problem.get("draft", False),
            }
            if problem.get("triage"):
                body["triage"] = True
            created = self.who(problem.get("as", "priya")).post(f"{self.connect}/problems", body)
            self.ids[problem["key"]] = created["id"]
            self.records[problem["key"]] = created
            for tag in problem.get("tags", []):
                self.operator.post(f"{self.connect}/problems/{created['id']}/tags", {"tagId": self.id_of(tag)})
            for goal in problem.get("goals", []):
                self.operator.post(f"{self.connect}/problems/{created['id']}/links", {"type": "goal", "id": self.id_of(goal)})
        self.step(f"{len(self.data['problems'])} Problems")

    def create_solutions(self) -> None:
        for solution in self.data["solutions"]:
            body: dict[str, Any] = {
                "title": solution["title"],
                "description": solution.get("description", ""),
                "priority": solution.get("priority"),
            }
            if solution.get("origin"):
                body["originProblemId"] = self.id_of(solution["origin"])
            if solution.get("team"):
                body["teamId"] = self.id_of(solution["team"])
            author = self.who(solution.get("as", "priya"))
            created = author.post(f"{self.connect}/solutions", body)
            sid = created["id"]
            self.ids[solution["key"]] = sid
            if solution.get("milestone"):
                author.put(f"{self.connect}/solutions/{sid}", {"milestoneId": self.id_of(solution["milestone"])})
            for problem in solution.get("problems", []):
                author.post(f"{self.connect}/solutions/{sid}/links", {"type": "problem", "id": self.id_of(problem)})
            for goal in solution.get("goals", []):
                author.post(f"{self.connect}/solutions/{sid}/links", {"type": "goal", "id": self.id_of(goal)})
            for tag in solution.get("tags", []):
                author.post(f"{self.connect}/solutions/{sid}/tags", {"tagId": self.id_of(tag)})
        for solution in self.data["solutions"]:
            for blocker in solution.get("blockedBy", []):
                self.who("priya").post(
                    f"{self.connect}/solutions/{self.id_of(solution['key'])}/blockers",
                    {"blockedBySolutionId": self.id_of(blocker)},
                )
        self.step(f"{len(self.data['solutions'])} Solutions")

    def create_feedback(self) -> None:
        for item in self.data.get("feedback", []):
            body = {
                k: item[k]
                for k in ("title", "description", "priority", "externalId", "submittedBy", "dateAdded", "feedbackType")
                if k in item
            }
            fid = self.who(item.get("as", "priya")).post(f"{self.connect}/feedback", body)["id"]
            self.ids[item["key"]] = fid
            for link in item.get("links", []):
                kind, key = ref(link)
                self.who("priya").post(f"{self.connect}/feedback/{fid}/links", {"type": kind, "id": self.id_of(key)})
            for tag in item.get("tags", []):
                self.who("priya").post(f"{self.connect}/feedback/{fid}/tags", {"tagId": self.id_of(tag)})
        self.step(f"{len(self.data.get('feedback', []))} Feedback items")

    def create_conversation(self) -> None:
        for thread in self.data.get("comments", []):
            kind, key = ref(thread["on"])
            body = {"parentType": kind, "parentId": self.id_of(key), "body": thread["body"]}
            created = self.who(thread.get("as")).post(f"{self.connect}/comments", body)
            for reply in thread.get("replies", []):
                self.who(reply.get("as")).post(f"{self.connect}/comments/{created['id']}/replies", {"body": reply["body"]})
            if thread.get("resolve"):
                self.who(thread["resolve"]).post(f"{self.connect}/comments/{created['id']}/resolve")
        for question in self.data.get("questions", []):
            kind, key = ref(question["on"])
            body = {"text": question["text"], "parentType": kind, "parentId": self.id_of(key)}
            if question.get("assignee"):
                body["assigneeUserId"] = self.users[question["assignee"]]["id"]
            created = self.who(question.get("as")).post(f"{self.connect}/questions", body)
            if question.get("resolve"):
                self.who(question.get("assignee")).post(f"{self.connect}/questions/{created['id']}/resolve")
        for task in self.data.get("tasks", []):
            body = {k: task[k] for k in ("title", "description", "priority", "status", "dueDate") if k in task}
            if task.get("assignee"):
                body["assigneeUserId"] = self.users[task["assignee"]]["id"]
            if task.get("on"):
                kind, key = ref(task["on"])
                body["parentType"], body["parentId"] = kind, self.id_of(key)
            self.who(task.get("as", "priya")).post(f"{self.path}/tasks", body)
        self.step(
            f"{len(self.data.get('comments', []))} comment threads, {len(self.data.get('questions', []))} Questions, "
            f"{len(self.data.get('tasks', []))} Tasks"
        )

    # ── lifecycles ───────────────────────────────────────────────────────────

    def move_problems(self) -> None:
        for problem in self.data["problems"]:
            pid = self.id_of(problem["key"])
            stage = self.records[problem["key"]]["stage"]
            base = f"{self.connect}/problems/{pid}"
            if problem.get("decline"):
                self.operator.post(f"{base}/decline", {"reason": problem["decline"]})
                continue
            if stage == "new" and not problem.get("triage"):
                stage = self.operator.post(f"{base}/accept")["stage"]
            if problem.get("section") and stage == "open":
                body = {"initiativeId": self.id_of(problem["initiative"]), "section": problem["section"]}
                self.operator.post(f"{base}/section", body)

    def merge_problems(self) -> None:
        for problem in self.data["problems"]:
            if problem.get("merge"):
                merge = problem["merge"]
                self.operator.post(
                    f"{self.connect}/problems/{self.id_of(problem['key'])}/merge",
                    {"targetId": self.id_of(merge["into"]), "reason": merge["reason"]},
                )

    def move_solutions(self) -> None:
        order = ["identified", "shaped", "accepted", "committed", "delivered"]
        for solution in self.data["solutions"]:
            sid = self.id_of(solution["key"])
            base = f"{self.connect}/solutions/{sid}"
            if solution.get("drop"):
                self.who("priya").post(f"{base}/drop", {"reason": solution["drop"]})
                continue
            target = order.index(solution.get("stage", "identified"))
            if target == 0:
                continue
            lead = self.who(self.team_lead[solution["team"]])
            self.who("priya").post(f"{base}/shape")
            if target >= 2:
                # Accepting takes the budget; dates are only allowed once accepted.
                lead.post(f"{base}/accept", {"deliveryBudget": solution.get("budget")})
                if solution.get("indicativeDate"):
                    lead.put(base, {"indicativeDeliveryDate": solution["indicativeDate"]})
            if target >= 3:
                lead.post(f"{base}/commit", {"committedDeliveryDate": solution["committedDate"]})
            if target >= 4:
                lead.post(f"{base}/deliver")

    def move_feedback(self) -> None:
        for item in self.data.get("feedback", []):
            base = f"{self.connect}/feedback/{self.id_of(item['key'])}"
            flow = item.get("flow", "new")
            actor = self.who(item.get("as", "priya"))
            if flow == "proposed":
                actor.post(f"{base}/propose-outcome", item["proposal"])
                continue
            if flow == "new":
                continue
            actor.post(f"{base}/done-triaging")
            if flow in ("ready_to_send", "acknowledged"):
                actor.post(f"{base}/verify")
            if flow == "acknowledged":
                actor.post(f"{base}/mark-sent")
                actor.post(f"{base}/acknowledge", {"signOffDate": item.get("signOffDate")})

    def close_things(self) -> None:
        for problem in self.data["problems"]:
            if problem.get("close"):
                self.operator.post(f"{self.connect}/problems/{self.id_of(problem['key'])}/close", problem["close"])
        for milestone in self.data["milestones"]:
            if milestone.get("close"):
                self.who("priya").post(f"{self.connect}/milestones/{self.id_of(milestone['key'])}/close", milestone["close"])
        for goal in self.data["goals"]:
            if goal.get("close"):
                self.who("priya").post(f"{self.connect}/goals/{self.id_of(goal['key'])}/close", goal["close"])

    def run(self) -> None:
        self.create_engagement()
        self.create_workspaces()
        # Adding people to teams first creates their users (pending); signing in then
        # activates them. Signing in a brand-new address directly hits a portal bug: the
        # local login derives users.id from the first 8 characters of a time-based oid,
        # so a second new address in the same epoch range collides (500).
        self.create_teams()
        self.sign_in_people()
        self.create_initiatives()
        self.create_goals()
        self.create_milestones()
        self.create_problems()
        self.create_solutions()
        self.create_feedback()
        self.create_conversation()
        self.step("Moving items through their lifecycles")
        self.move_problems()
        self.move_solutions()
        self.merge_problems()
        self.move_feedback()
        self.close_things()


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--email", default=os.environ.get("ARTISYN_EMAIL"), help="your portal user (or ARTISYN_EMAIL)")
    parser.add_argument("--portal", default=os.environ.get("ARTISYN_PORTAL_URL", DEFAULT_PORTAL_URL), help="portal API base URL")
    parser.add_argument("--data", type=Path, default=DATA_FILE, help="demo content file")
    args = parser.parse_args()
    if not args.email:
        parser.error("--email is required (or set ARTISYN_EMAIL)")

    data = json.loads(args.data.read_text(encoding="utf-8"))
    slug = data["engagement"]["slug"]

    operator = ArtisynClient(args.portal)
    operator.sign_in(args.email)
    print(f"• Signed in as {operator.user['email']} on {args.portal}")
    operator.ensure_global_roles("engagement-creator")

    if operator.find_engagement(slug) is not None:
        print(
            f"An engagement /{slug} already exists, so nothing was changed. To start over, run "
            "scripts/reset_demo.sh: it rebuilds the portal's local database with `npm run demo:reset` "
            "and seeds Zephyr again."
        )
        return 1

    seeder = Seeder(operator, data)
    seeder.run()

    engagement = seeder.engagement
    print()
    print(f"Done. Open http://localhost:5173/engagements/{engagement['slug']}")
    print("Connect an MCP client to a workspace with: python3 scripts/show_connection.py --email", args.email)
    return 0


if __name__ == "__main__":
    sys.exit(main())
