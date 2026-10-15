#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in VM HTTP assertions. Credentials stay in process memory, never output."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

COUNTERS = ("read_requests", "write_requests", "read_bytes", "write_bytes", "integrity_failures")
VERSION = "0.8.0" if os.environ.get("SR_MILESTONE") in ("8", "9", "10", "11") else "0.6.0"
FEATURES = 31 if VERSION == "0.8.0" else 15


def request(path, method="GET", body=None, headers=None):
    origin = os.environ["M7_ORIGIN"]
    address = urlsplit(origin)
    assert address.scheme == "http" and address.hostname == "127.0.0.1" and address.port
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", os.environ["M7_TOKEN"])
    values = {"Authorization": "Bearer " + os.environ["M7_TOKEN"], "Origin": origin}
    values.update(headers or {})
    if method == "POST":
        values.setdefault("Content-Type", "application/json")
        body = "{}" if body is None else body
    conn = http.client.HTTPConnection("127.0.0.1", address.port, timeout=20)
    try:
        conn.request(method, path, body=body, headers=values)
        response = conn.getresponse()
        raw = response.read()
        assert os.environ["M7_TOKEN"].encode() not in raw, "token returned in response"
        assert b"Traceback" not in raw and b"/home/" not in raw
        return response.status, dict(response.getheaders()), raw
    finally:
        conn.close()


def get(command):
    status, _, raw = request("/api/" + command)
    assert status == 200, f"HTTP {command} returned {status}"
    result = json.loads(raw)
    assert type(result["abi"]) is int and result["abi"] == 1
    if command == "stats":
        assert set(result) == {"abi", *COUNTERS}
        for field in COUNTERS:
            value = result[field]
            assert type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,19}", value)
            result[field] = int(value)
            assert result[field] < 2**64
    return result


def status(state, generation, capacity):
    result = get("status")
    names = {0: "NO_KEY", 1: "PREPARING", 2: "ACTIVE", 3: "LOCKED", 4: "INTEGRITY_FAILED"}
    assert (result["state"], result["state_name"], result["generation"], result["capacity_bytes"]) == (
        state, names[state], str(generation), str(capacity))
    assert result["version"] == result["cli_version"] == VERSION
    assert result["dashboard_version"] == "0.8.0"
    assert result["features"] == FEATURES and result["unit_bytes"] == 4096
    assert result["compatible"] is True
    assert all(result[key] is True for key in ("xts", "lock", "integrity", "stats"))


def action(command, busy=False):
    assert command in ("load-random", "lock", "unlock", "destroy")
    body = '{"confirm":"DESTROY"}' if command == "destroy" else "{}"
    code, _, raw = request("/api/actions/" + command, "POST", body)
    result = json.loads(raw)
    if busy:
        assert code == 409 and result["error"]["code"] == "device_busy"
        assert result["error"]["cli_exit"] == 1
    else:
        assert code == 200, f"HTTP action {command} returned {code}"
        assert result == dict(ok=True, action=command, refresh_required=True)
    print(f"PASS: HTTP {command} {'EBUSY' if busy else 'completed'}")


def observe(mode, *args):
    if mode == "status":
        status(*map(int, args))
    elif mode == "baseline":
        assert all(get("stats")[field] == 0 for field in COUNTERS)
    elif mode == "save":
        # M6 already wrote its snapshot. Save an HTTP baseline alongside it.
        Path(args[0] + ".http").write_text(json.dumps(get("stats")))
    elif mode in ("equal", "increased", "retained"):
        before = json.loads(Path(args[0] + ".http").read_text())
        after = get("stats")
        if mode == "equal":
            assert before == after
        else:
            assert all(after[k] >= before[k] for k in COUNTERS)
            if mode == "increased":
                assert all(after[k] > before[k] for k in COUNTERS[:4])
    elif mode == "accounting":
        assert all(get("stats")[key] > 0 for key in COUNTERS[:4])
    else:
        raise RuntimeError("unknown observation")
    print(f"PASS: HTTP observation {mode}")


def security():
    # Run after production unload: even authorized metadata must report absent.
    for route in ("/api/status", "/api/stats"):
        code, _, raw = request(route)
        assert code == 503 and json.loads(raw)["error"]["code"] == "module_absent"
        for token in ("", "Bearer ", "Bearer wrong"):
            assert request(route, headers={"Authorization": token})[0] == 401
    for route in ("/", "/app.js", "/styles.css"):
        code, headers, raw = request(route)
        assert code == 200 and raw
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "same-origin"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "Access-Control-Allow-Origin" not in headers
        if route == "/":
            assert b'<meta name="referrer" content="same-origin">' in raw
    for route in ("/../README.md", "/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/dev/secureramctl", "/dev/secureram0"):
        assert request(route)[0] == 404
    for command in ("load-random", "lock", "unlock", "destroy"):
        assert request("/api/actions/" + command)[0] == 405
        assert request("/api/actions/" + command, "POST", headers={"Authorization": ""})[0] == 401
    action_route = "/api/actions/load-random"
    assert request(action_route, "POST", headers={"Origin": "null"})[0] == 403
    assert request(action_route, "POST", headers={"Origin": "http://evil.example"})[0] == 403
    assert request(action_route, "POST", headers={"Host": "evil.example"})[0] == 403
    assert request(action_route, "POST", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    for command in ("tamper", "run-command", "lock;id", "$(id)"):
        assert request("/api/actions/" + command, "POST")[0] == 404
    assert request("/api/actions/destroy", "POST")[0] == 400
    assert request("/api/actions/lock", "POST", "[")[0] == 400
    assert request("/api/actions/lock", "POST", "x" * 129)[0] == 413
    assert request("/api/actions/lock", "POST", headers={"Content-Type": "text/plain"})[0] == 415
    assert request("/api/status", headers={"Host": "evil.example"})[0] == 403
    assert request("/api/status", headers={"Origin": "http://evil.example"})[0] == 403
    assert request("/api/status", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    print("PASS: HTTP auth, static assets, reload survival, adversarial routes and cross-origin checks")


def rapid_invalid_actions():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda command: request("/api/actions/" + command, "POST"),
                                ["unlock", "lock", "load-random"] * 3))
    for code, _, raw in results:
        assert code in (409, 503)
        assert json.loads(raw)["error"]["code"] in ("device_busy", "controller_busy")
    assert get("status")["state"] == 4


def main():
    mode, *args = sys.argv[1:]
    if mode == "action":
        action(*args)
    elif mode == "busy":
        action(*args, busy=True)
    elif mode == "observe":
        observe(*args)
    elif mode == "security":
        security()
    else:
        raise RuntimeError("unknown HTTP test mode")


if __name__ == "__main__":
    main()
