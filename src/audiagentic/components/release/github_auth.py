"""GitHub OAuth (device flow) authentication for release workflow dispatch.

The device flow is two-phase by design so it works over MCP (where the tool
call must return promptly and the user authorises out-of-band):

  1. ``start_device_flow`` asks GitHub for a device/user code pair and returns
     it to the caller. The caller shows ``user_code`` + ``verification_uri`` to
     the user.
  2. ``poll_device_flow`` is called repeatedly; each call performs a single
     non-blocking check. It returns ``pending`` until the user authorises, then
     ``authorized`` (and persists the token to disk).

``github_authenticate`` is a blocking convenience wrapper (used by the
synchronous dispatch path) built on top of those two primitives.
"""
from __future__ import annotations

import json
import os
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json

# GitHub OAuth device flow endpoints
_DEVICE_AUTH_URL = "https://github.com/login/device/code"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_AGENT = "audiagentic-release"

# Storage location for the token
_CREDENTIALS_DIR = Path.home() / ".audiagentic" / "credentials"
_CREDENTIALS_FILE = _CREDENTIALS_DIR / "github_token.json"

# Environment variables checked before falling back to stored credentials.
_TOKEN_ENV_VARS = ("AUDIAGENTIC_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")

# Default scopes for release workflow dispatch (space-separated per OAuth spec)
_DEFAULT_SCOPES = "repo workflow"


def _get_client_id() -> str:
    """Return the GitHub OAuth app client ID.

    Override with ``AUDIAGENTIC_GITHUB_CLIENT_ID`` to use your own OAuth app.
    The app MUST have the device flow enabled
    (Settings > Developer settings > OAuth Apps > Enable Device Flow).
    """
    return os.environ.get("AUDIAGENTIC_GITHUB_CLIENT_ID", "Ov23liBfQkqTtMqKdRvT")


def _get_credentials_path() -> Path:
    _CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    return _CREDENTIALS_FILE


def _post_form(url: str, fields: dict[str, str], *, timeout: int = 15) -> dict[str, Any]:
    """POST form-encoded ``fields`` and parse a JSON response.

    Sends ``Accept: application/json`` so GitHub returns JSON rather than the
    default form-encoded body.
    """
    data = urlencode(fields).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Token storage
# --------------------------------------------------------------------------- #
def _load_env_token() -> str | None:
    for var in _TOKEN_ENV_VARS:
        token = os.environ.get(var)
        if token:
            return token.strip()
    return None


def load_token() -> str | None:
    """Load a GitHub token from the environment, then from disk."""
    env_token = _load_env_token()
    if env_token:
        return env_token
    path = _get_credentials_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data.get("token")
        if token:
            return token
    except Exception:
        pass
    return None


def save_token(token: str) -> None:
    """Store GitHub token on disk with restrictive permissions (best effort)."""
    path = _get_credentials_path()
    data = {
        "token": token,
        "saved-at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_json(path, data, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_token() -> None:
    """Remove the stored GitHub token (does not affect environment vars)."""
    path = _get_credentials_path()
    if path.exists():
        path.unlink()


# --------------------------------------------------------------------------- #
# Device flow primitives (non-blocking)
# --------------------------------------------------------------------------- #
def start_device_flow(open_browser: bool = True) -> dict[str, Any]:
    """Request a device/user code pair from GitHub.

    Returns a dict the caller relays to the user:
    ``device_code`` (pass back to :func:`poll_device_flow`), ``user_code``,
    ``verification_uri``, ``interval``, ``expires_in``.
    """
    try:
        resp = _post_form(
            _DEVICE_AUTH_URL,
            {"client_id": _get_client_id(), "scope": _DEFAULT_SCOPES},
        )
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise AudiaGenticError(
            code="INT-RELEASE-003",
            kind="release",
            message=f"GitHub device-code request failed: {e.code}",
            details={"response": body},
        )
    except Exception as e:  # network/parse errors
        raise AudiaGenticError(
            code="INT-RELEASE-003",
            kind="release",
            message="GitHub device-code request failed",
            details={"error": str(e)},
        )

    if "device_code" not in resp:
        # GitHub returns {"error": ...} e.g. when device flow is not enabled.
        raise AudiaGenticError(
            code="VAL-RELEASE-005",
            kind="release",
            message=f"GitHub device-code request rejected: {resp.get('error', 'unknown')}",
            details={"error_description": resp.get("error_description")},
        )

    verification_uri = resp.get("verification_uri", "https://github.com/login/device")
    if open_browser:
        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

    return {
        "device_code": resp["device_code"],
        "user_code": resp["user_code"],
        "verification_uri": verification_uri,
        "interval": resp.get("interval", 5),
        "expires_in": resp.get("expires_in", 900),
    }


def poll_device_flow(device_code: str) -> dict[str, Any]:
    """Perform a single (non-blocking) token poll.

    Returns ``{"status": "pending"}`` while waiting, ``{"status": "slow_down",
    "interval": N}`` if GitHub asks us to back off, or
    ``{"status": "authorized", "token": "..."}`` once granted (the token is
    also persisted to disk). Raises on terminal errors (denied/expired).
    """
    try:
        resp = _post_form(
            _TOKEN_URL,
            {
                "client_id": _get_client_id(),
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except Exception as e:
        raise AudiaGenticError(
            code="INT-RELEASE-003",
            kind="release",
            message="GitHub token poll failed",
            details={"error": str(e)},
        )

    # GitHub returns HTTP 200 with an `error` field while the flow is in progress.
    error = resp.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        return {"status": "slow_down", "interval": resp.get("interval", 10)}
    if error:
        raise AudiaGenticError(
            code="VAL-RELEASE-005",
            kind="release",
            message=f"GitHub OAuth failed: {error}",
            details={"error_description": resp.get("error_description")},
        )

    token = resp.get("access_token")
    if not token:
        raise AudiaGenticError(
            code="VAL-RELEASE-005",
            kind="release",
            message="GitHub OAuth returned no access token",
            details={"response": resp},
        )
    save_token(token)
    return {"status": "authorized", "token": token}


# --------------------------------------------------------------------------- #
# Blocking convenience wrapper
# --------------------------------------------------------------------------- #
def github_authenticate(interactive: bool = True, *, timeout: int | None = None) -> str:
    """Obtain a GitHub token, blocking until the device flow completes.

    Used by the synchronous dispatch path. Returns a stored/env token when one
    is available; otherwise (``interactive=True``) drives the device flow to
    completion, printing the user code for terminal users.
    """
    existing = load_token()
    if existing:
        return existing

    if not interactive:
        raise AudiaGenticError(
            code="VAL-RELEASE-007",
            kind="release",
            message="No GitHub token stored and interactive auth disabled",
        )

    flow = start_device_flow(open_browser=True)
    print(
        f"To authorise, open {flow['verification_uri']} and enter code: "
        f"{flow['user_code']}",
        flush=True,
    )

    interval = flow["interval"]
    deadline = time.time() + (timeout if timeout is not None else flow["expires_in"])
    while time.time() < deadline:
        time.sleep(interval)
        result = poll_device_flow(flow["device_code"])
        status = result["status"]
        if status == "authorized":
            print("GitHub token obtained successfully.", flush=True)
            return result["token"]
        if status == "slow_down":
            interval = result["interval"]

    raise AudiaGenticError(
        code="VAL-RELEASE-006",
        kind="release",
        message="GitHub OAuth device flow timed out — please try again",
    )


def github_auth_status() -> dict[str, Any]:
    """Return authentication status."""
    token = load_token()
    if token:
        source = "env" if _load_env_token() else "file"
        return {
            "authenticated": True,
            "token-saved": source == "file",
            "token-source": source,
            "token-preview": token[:8] + "..." + token[-4:],
        }
    return {"authenticated": False, "token-saved": False}
