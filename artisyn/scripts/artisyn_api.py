"""A small client for the Artisyn portal's REST API (standard library only).

It signs in the way the portal's local login page does: it looks the user up by
email (``GET /api/qa/check-email``), opens a session (``POST /api/qa/session``),
then sends the ``artisyn_csrf`` cookie back as ``X-CSRF-Token`` on every write.
Those sign-in routes exist only when the portal runs with
``ENVIRONMENT=development``, which is what ``npm run dev`` uses.
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_PORTAL_URL = "http://localhost:3001"


class ArtisynError(RuntimeError):
    """A request the portal refused; the message carries the status and body."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"{method} {path} -> {status}: {body}")
        self.status = status
        self.body = body


class ArtisynClient:
    """Cookie-session client for one signed-in user."""

    def __init__(self, base_url: str = DEFAULT_PORTAL_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self.user: dict[str, Any] = {}

    # ── transport ────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, body: Any = None, attempt: int = 0) -> Any:
        """Send one request and return the response's ``data`` (or the whole body)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, method=method, data=data)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        csrf = next((c.value for c in self._jar if c.name == "artisyn_csrf"), None)
        if csrf:
            req.add_header("X-CSRF-Token", csrf)
        try:
            with self._opener.open(req) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 3:
                # The sign-in routes are rate limited (10 a minute); wait it out.
                wait = int(err.headers.get("Retry-After") or 30)
                print(f"  rate limited on {path}; waiting {wait}s")
                time.sleep(wait)
                return self.request(method, path, body, attempt=attempt + 1)
            raise ArtisynError(method, path, err.code, err.read().decode(errors="replace")) from None
        except urllib.error.URLError as err:
            raise SystemExit(
                f"Cannot reach the portal at {self.base_url} ({err.reason}). "
                "Start it with `npm run dev` in the artisyn-portal checkout."
            ) from None
        if not raw:
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, {} if body is None else body)

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, body)

    def patch(self, path: str, body: Any) -> Any:
        return self.request("PATCH", path, body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # ── sign-in ──────────────────────────────────────────────────────────────

    def sign_in(self, email: str) -> dict[str, Any]:
        """Open a session as an existing user (local development portals only)."""
        query = urllib.parse.urlencode({"email": email})
        try:
            found = self.request("GET", f"/api/qa/check-email?{query}")
        except ArtisynError as err:
            if err.status == 404:
                raise SystemExit(
                    "The portal has no local sign-in route. Run it with ENVIRONMENT=development "
                    "(the backend/.env default for `npm run dev`)."
                ) from None
            raise
        if not found.get("exists"):
            raise SystemExit(
                f"No signed-in user {email} on this portal. Sign in once at http://localhost:5173 "
                "with that address, then run this script again."
            )
        user = found["user"]
        self.request("POST", "/api/qa/session", {"oid": user["oid"], "name": user["fullName"], "email": user["email"]})
        self.user = self.get("/api/users/me")
        return self.user

    def sign_in_person(self, email: str, first_name: str, last_name: str) -> dict[str, Any]:
        """Sign a demo person in, creating or activating their user the way a first login would.

        Uses the local login page's ``POST /api/qa/create-test-user``, which accepts a
        platform-domain address (or one already added to a team) and returns the
        existing user unchanged when it has signed in before.
        """
        created = self.request(
            "POST", "/api/qa/create-test-user", {"email": email, "firstName": first_name, "lastName": last_name}
        )
        user = created["user"]
        self.request("POST", "/api/qa/session", {"oid": user["oid"], "name": user["fullName"], "email": user["email"]})
        self.user = self.get("/api/users/me")
        return self.user

    def ensure_global_roles(self, *roles: str) -> None:
        """Give the signed-in user these global roles (needs ``admin``)."""
        held = list(self.user.get("roles") or [])
        missing = [role for role in roles if role not in held]
        if not missing:
            return
        if "admin" not in held:
            raise SystemExit(
                f"{self.user.get('email')} needs the global roles {', '.join(missing)}. Make them an admin first, "
                "from artisyn-portal/backend:\n"
                f"  ./venv/bin/python scripts/grant_global_admin.py --email {self.user.get('email')}"
            )
        self.user = self.patch(f"/api/admin/users/{self.user['id']}", {"roles": held + missing})

    # ── lookups ──────────────────────────────────────────────────────────────

    def find_engagement(self, slug: str) -> dict[str, Any] | None:
        try:
            return self.get(f"/api/engagements/by-slug/{urllib.parse.quote(slug)}")
        except ArtisynError as err:
            if err.status in (403, 404):
                return None
            raise
