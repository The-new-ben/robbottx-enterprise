#!/usr/bin/env python3
"""Deploy a reviewed plugin through a temporary Code Snippets REST route."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


USER_AGENT = "RobbottX-Agent-Deploy/0.1"


class DeployFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--zip-url", required=True)
    parser.add_argument("--plugin-slug", default="robbottx-core")
    parser.add_argument("--plugin-main-file", default="robbottx-core.php")
    parser.add_argument(
        "--health-path",
        default="/wp-json/robbottx/v1/healthcheck",
    )
    parser.add_argument("--render-path", default="/")
    parser.add_argument(
        "--new-body-marker",
        default="<!-- robbottx-core:0.1.2 -->",
    )
    parser.add_argument("--old-body-marker", default="Welcome to RobbottX")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise DeployFailure(f"Required environment variable {name} is absent.")
    return value


def make_auth(user: str, password: str) -> str:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {encoded}"


def request(
    url: str,
    *,
    method: str = "GET",
    auth: str | None = None,
    payload: dict | None = None,
    timeout: int = 60,
) -> tuple[int, str, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json, text/html;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = auth

    request_object = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request_object, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, error.headers.get("Content-Type", ""), body
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        host = urllib.parse.urlsplit(url).netloc
        raise DeployFailure(
            f"Transport failure while requesting {host}."
        ) from error


def json_body(status: int, content_type: str, body: str, context: str) -> dict:
    if status < 200 or status >= 300:
        kind = "managed-host HTML/WAF response" if "html" in content_type else "JSON/API response"
        raise DeployFailure(f"{context} failed with HTTP {status} ({kind}).")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise DeployFailure(f"{context} returned invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise DeployFailure(f"{context} returned an unexpected JSON shape.")
    return parsed


def add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}rbtxcb={int(time.time())}"


def delete_temporary_snippet(
    base_url: str,
    snippet_id: int,
    auth: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, _, _ = request(
                (
                    f"{base_url}/wp-json/code-snippets/v1/snippets/"
                    f"{snippet_id}?_method=DELETE"
                ),
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            if 200 <= status < 300 or status == 404:
                return True, failures
            failures.append(f"delete attempt {attempt} returned HTTP {status}")
        except Exception as error:  # cleanup must continue to the absence proof
            failures.append(
                f"delete attempt {attempt} raised {type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def prove_deploy_route_absent(
    base_url: str,
    auth: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, _, _ = request(
                f"{base_url}/wp-json/agentdeploy/v1/run",
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            if status == 404:
                return True, failures
            failures.append(f"absence attempt {attempt} returned HTTP {status}")
        except Exception as error:  # retry independently of deletion outcome
            failures.append(
                f"absence attempt {attempt} raised {type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def main() -> int:
    args = parse_args()
    base_url = required_env("WP_BASE_URL").rstrip("/")
    user = required_env("WP_USER")
    password = required_env("WP_APP_PASSWORD")
    auth = make_auth(user, password)

    status, content_type, body = request(
        f"{base_url}/wp-json/wp/v2/users/me?context=edit&_fields=id,roles,capabilities",
        auth=auth,
    )
    identity = json_body(status, content_type, body, "Application Password verification")
    if (
        "administrator" not in identity.get("roles", [])
        or identity.get("capabilities", {}).get("update_plugins") is not True
    ):
        raise DeployFailure(
            "Authenticated WordPress user lacks administrator/update_plugins authority."
        )

    zip_status, zip_content_type, _ = request(args.zip_url, timeout=90)
    if zip_status != 200 or "html" in zip_content_type:
        raise DeployFailure(
            f"Raw ZIP preflight failed with HTTP {zip_status}."
        )

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "preflight_ok",
                    "wordpress_user_id": identity.get("id"),
                    "zip_http_status": zip_status,
                    "execute": False,
                },
                sort_keys=True,
            )
        )
        return 0

    template_path = (
        Path(__file__).resolve().parent
        / "templates"
        / "deploy-route.php.txt"
    )
    route_code = template_path.read_text(encoding="utf-8")
    route_code = (
        route_code.replace("{{PLUGIN_SLUG}}", args.plugin_slug)
        .replace("{{PLUGIN_MAIN_FILE}}", args.plugin_main_file)
        .replace("{{RAW_ZIP_URL}}", args.zip_url)
    )

    snippet_id: int | None = None
    route_removed = False
    failure: Exception | None = None

    try:
        snippet_name = f"tmp-robbottx-deploy-{args.version}-{int(time.time())}"
        status, content_type, body = request(
            f"{base_url}/wp-json/code-snippets/v1/snippets",
            method="POST",
            auth=auth,
            payload={
                "name": snippet_name,
                "code": route_code,
                "scope": "global",
                "active": True,
            },
        )
        created = json_body(status, content_type, body, "Temporary route creation")
        snippet_id = int(created["id"])

        status, content_type, body = request(
            f"{base_url}/wp-json/agentdeploy/v1/run",
            method="POST",
            auth=auth,
            payload={},
            timeout=180,
        )
        deployed = json_body(status, content_type, body, "Plugin_Upgrader deployment")
        if deployed.get("active") is not True:
            raise DeployFailure("Deployment response did not confirm active plugin.")

        status, content_type, body = request(
            add_cache_buster(f"{base_url}{args.health_path}"),
            timeout=60,
        )
        health = json_body(status, content_type, body, "Healthcheck verification")
        if health.get("status") != "ok" or health.get("version") != args.version:
            raise DeployFailure("Healthcheck did not return the requested version.")

        status, _, rendered = request(
            add_cache_buster(f"{base_url}{args.render_path}"),
            timeout=90,
        )
        if status != 200:
            raise DeployFailure(f"Rendered page returned HTTP {status}.")
        body_start = rendered.lower().find("<body")
        if body_start < 0:
            raise DeployFailure("Rendered page has no body element.")
        rendered_body = rendered[body_start:]
        if args.new_body_marker not in rendered_body:
            raise DeployFailure("New rendered-body marker is absent.")
        if args.old_body_marker and args.old_body_marker in rendered_body:
            raise DeployFailure("Old rendered-body marker is still present.")
    except Exception as exception:  # deletion must still execute
        failure = exception
    finally:
        cleanup_failures: list[str] = []
        snippet_deleted = snippet_id is None
        if snippet_id is not None:
            snippet_deleted, delete_failures = delete_temporary_snippet(
                base_url,
                snippet_id,
                auth,
            )
            cleanup_failures.extend(delete_failures)

        route_absent, absence_failures = prove_deploy_route_absent(
            base_url,
            auth,
        )
        cleanup_failures.extend(absence_failures)
        route_removed = snippet_deleted and route_absent

        if not route_removed:
            cleanup_summary = "; ".join(cleanup_failures)
            cleanup_error = "Temporary deploy route cleanup was not proven."
            if cleanup_summary:
                cleanup_error = f"{cleanup_error} {cleanup_summary}."
            if failure is None:
                failure = DeployFailure(cleanup_error)
            else:
                failure = DeployFailure(f"{failure} {cleanup_error}")

    if failure is not None:
        raise DeployFailure(str(failure))

    print(
        json.dumps(
            {
                "status": "deployed",
                "version": args.version,
                "plugin": args.plugin_slug,
                "route_removed": route_removed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployFailure as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        sys.exit(1)
