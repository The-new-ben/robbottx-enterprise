#!/usr/bin/env python3
"""Capture and validate the complete pinned Lighthouse release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import ntpath
import os
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


EXPECTED_LIGHTHOUSE_VERSION = "13.4.1"
EXPECTED_LIGHTHOUSE_URL = (
    "https://registry.npmjs.org/lighthouse/-/lighthouse-13.4.1.tgz"
)
EXPECTED_LIGHTHOUSE_INTEGRITY = (
    "sha512-fDu8lt3QLK/lTqIxtp1HkzQNJ32rsFHhbadYOepcMZFLgA8oINhxutMbMv8XXnpT"
    "OvZ0TXCo4JCk1LDTWaRLnA=="
)
EXPECTED_ORIGIN = "https://robbottx.com"
EXPECTED_BASE_URL = EXPECTED_ORIGIN + "/"
EXPECTED_CATEGORIES = (
    "performance",
    "accessibility",
    "best-practices",
    "seo",
)
CATEGORY_THRESHOLDS = {
    "performance": 0.90,
    "accessibility": 1.0,
    "best-practices": 1.0,
    "seo": 1.0,
}
REQUIRED_BINARY_AUDITS = (
    "color-contrast",
    "errors-in-console",
)
MODES = ("desktop", "mobile")
SAMPLES_PER_MODE = 3
REPORT_FILE_PATTERN = "lighthouse-{mode}-run{sample}.json"
RECEIPT_FILE_NAME = "lighthouse-release-receipt.json"
PROCESS_TIMEOUT_SECONDS = 240
PROFILE_PREFIX = "robbottx-lighthouse-"
FETCH_TIME_TOLERANCE = timedelta(seconds=60)
POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)
SCREEN_EMULATION = {
    "desktop": {
        "disabled": False,
        "mobile": False,
        "width": 1350,
        "height": 940,
        "deviceScaleFactor": 1,
    },
    "mobile": {
        "disabled": False,
        "mobile": True,
        "width": 390,
        "height": 844,
        "deviceScaleFactor": 3,
    },
}
THROTTLING = {
    "desktop": {
        "rttMs": 40,
        "throughputKbps": 10240,
        "requestLatencyMs": 0,
        "downloadThroughputKbps": 0,
        "uploadThroughputKbps": 0,
        "cpuSlowdownMultiplier": 1,
    },
    "mobile": {
        "rttMs": 150,
        "throughputKbps": 1638.4,
        "requestLatencyMs": 562.5,
        "downloadThroughputKbps": 1474.5600000000002,
        "uploadThroughputKbps": 675,
        "cpuSlowdownMultiplier": 4,
    },
}
EMULATED_USER_AGENT = {
    "desktop": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 "
        "Safari/537.36"
    ),
    "mobile": (
        "Mozilla/5.0 (Linux; Android 11; moto g power (2022)) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile "
        "Safari/537.36"
    ),
}
CHROME_VERSION_PATTERN = re.compile(
    r"(?:^|[\s(])(?:HeadlessChrome|Chrome)/"
    r"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)(?=$|[\s;)])"
)
NON_CHROME_BROWSER_PATTERN = re.compile(
    r"(?:^|[\s(])(?:Edg|EdgA|EdgiOS|OPR|Vivaldi)/",
    re.IGNORECASE,
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class LighthouseGateError(RuntimeError):
    """A release-evidence failure safe to expose to the operator."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture three immutable desktop and three immutable mobile "
            "Lighthouse reports, then write one aggregate release receipt."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="A new directory for six raw reports and one aggregate receipt.",
    )
    parser.add_argument("--url", default=EXPECTED_BASE_URL)
    return parser.parse_args()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_base_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        url != EXPECTED_BASE_URL
        or parsed.scheme != "https"
        or parsed.netloc != "robbottx.com"
        or parsed.path != "/"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise LighthouseGateError(
            "Lighthouse URL must be exactly the canonical RobbottX homepage."
        )
    return EXPECTED_BASE_URL


def sample_url(base_url: str, run_id: str, mode: str, sample: int) -> str:
    parsed = urllib.parse.urlsplit(validate_base_url(base_url))
    query = urllib.parse.urlencode(
        {"rbtxlh": f"{run_id}-{mode}-{sample}"}
    )
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, query, "")
    )


def parse_fetch_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def valid_score(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    if not math.isfinite(score) or score < 0 or score > 1:
        return None
    return score


def exact_number(value: object, expected: int | float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) == float(expected)
    )


def chrome_version(environment: object) -> str | None:
    if not isinstance(environment, dict):
        return None
    host_user_agent = environment.get("hostUserAgent")
    if not isinstance(host_user_agent, str):
        return None
    if NON_CHROME_BROWSER_PATTERN.search(host_user_agent):
        return None
    match = CHROME_VERSION_PATTERN.search(host_user_agent)
    return match.group(1) if match else None


def validate_report(
    payload: dict[str, Any],
    *,
    mode: str,
    requested_url: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    failures: list[str] = []

    if mode not in MODES:
        raise ValueError("Unsupported Lighthouse mode.")
    if payload.get("lighthouseVersion") != EXPECTED_LIGHTHOUSE_VERSION:
        failures.append("lighthouse_version")
    if payload.get("runtimeError", None) is not None:
        failures.append("runtime_error")
    if payload.get("requestedUrl") != requested_url:
        failures.append("requested_url")
    if payload.get("finalUrl") != requested_url:
        failures.append("final_url")

    fetch_time_value = payload.get("fetchTime")
    parsed_fetch_time = parse_fetch_time(fetch_time_value)
    if parsed_fetch_time is None:
        failures.append("fetch_time")
    elif started_at is not None and finished_at is not None:
        lower_bound = started_at.astimezone(timezone.utc) - FETCH_TIME_TOLERANCE
        upper_bound = finished_at.astimezone(timezone.utc) + FETCH_TIME_TOLERANCE
        if not lower_bound <= parsed_fetch_time <= upper_bound:
            failures.append("fetch_time_window")

    detected_chrome_version = chrome_version(payload.get("environment"))
    if detected_chrome_version is None:
        failures.append("chrome_version")

    settings = payload.get("configSettings")
    if not isinstance(settings, dict):
        settings = {}
        failures.append("config_settings")
    if settings.get("formFactor") != mode:
        failures.append("config_form_factor")
    if settings.get("emulatedUserAgent") != EMULATED_USER_AGENT[mode]:
        failures.append("config_emulated_user_agent")
    if settings.get("throttlingMethod") != "simulate":
        failures.append("config_throttling_method")
    throttling = settings.get("throttling")
    expected_throttling = THROTTLING[mode]
    if not isinstance(throttling, dict):
        failures.append("config_throttling")
    else:
        if set(throttling) != set(expected_throttling):
            failures.append("config_throttling_fields")
        for field, expected in expected_throttling.items():
            if not exact_number(throttling.get(field), expected):
                failures.append(f"config_throttling_{field}")
    if settings.get("locale") != "en-US":
        failures.append("config_locale")

    configured_categories = settings.get("onlyCategories")
    if (
        not isinstance(configured_categories, list)
        or not all(
            isinstance(category, str)
            for category in configured_categories
        )
        or len(configured_categories) != len(EXPECTED_CATEGORIES)
        or set(configured_categories) != set(EXPECTED_CATEGORIES)
    ):
        failures.append("config_category_set")

    screen = settings.get("screenEmulation")
    expected_screen = SCREEN_EMULATION[mode]
    if not isinstance(screen, dict):
        failures.append("config_screen_emulation")
    else:
        if screen.get("disabled") is not False:
            failures.append("config_screen_disabled")
        if screen.get("mobile") is not expected_screen["mobile"]:
            failures.append("config_screen_mobile")
        for field in ("width", "height", "deviceScaleFactor"):
            if not exact_number(screen.get(field), expected_screen[field]):
                failures.append(f"config_screen_{field}")

    categories = payload.get("categories")
    if not isinstance(categories, dict):
        categories = {}
        failures.append("categories")
    if set(categories) != set(EXPECTED_CATEGORIES):
        failures.append("category_set")

    category_scores: dict[str, float | None] = {}
    for category, threshold in CATEGORY_THRESHOLDS.items():
        record = categories.get(category)
        score = (
            valid_score(record.get("score"))
            if isinstance(record, dict)
            else None
        )
        category_scores[category] = (
            round(score * 100, 2) if score is not None else None
        )
        if score is None or score < threshold:
            failures.append(f"category_{category}")

    audits = payload.get("audits")
    if not isinstance(audits, dict):
        audits = {}
        failures.append("audits")
    audit_scores: dict[str, float | None] = {}
    for audit_id in REQUIRED_BINARY_AUDITS:
        record = audits.get(audit_id)
        score = (
            valid_score(record.get("score"))
            if isinstance(record, dict)
            else None
        )
        audit_scores[audit_id] = (
            round(score * 100, 2) if score is not None else None
        )
        if score != 1.0:
            failures.append(f"audit_{audit_id}")

    return {
        "status": "PASS" if failures == [] else "FAIL",
        "failures": sorted(set(failures)),
        "category_scores": category_scores,
        "audit_scores": audit_scores,
        "fetch_time": fetch_time_value,
        "final_url": payload.get("finalUrl"),
        "requested_url": payload.get("requestedUrl"),
        "lighthouse_version": payload.get("lighthouseVersion"),
        "chrome_version": detected_chrome_version,
    }


def find_chrome() -> Path:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise LighthouseGateError("A supported Chrome executable was not found.")


def lighthouse_binary(repository_root: Path) -> Path:
    suffix = "lighthouse.cmd" if os.name == "nt" else "lighthouse"
    binary = repository_root / "node_modules" / ".bin" / suffix
    if not binary.is_file():
        raise LighthouseGateError(
            "Pinned Lighthouse is absent. Run npm ci before auditing."
        )
    return binary


def read_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LighthouseGateError(f"{context} is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise LighthouseGateError(f"{context} has an unexpected shape.")
    return payload


def verify_lighthouse_pin(repository_root: Path) -> dict[str, str]:
    package = read_json_object(
        repository_root / "package.json",
        "package.json",
    )
    lock = read_json_object(
        repository_root / "package-lock.json",
        "package-lock.json",
    )
    package_dependencies = package.get("devDependencies")
    dependency = (
        package_dependencies.get("lighthouse")
        if isinstance(package_dependencies, dict)
        else None
    )
    lock_packages = lock.get("packages")
    if not isinstance(lock_packages, dict):
        raise LighthouseGateError("package-lock.json has no packages map.")
    root_record = lock_packages.get("")
    lighthouse_record = lock_packages.get("node_modules/lighthouse")
    if not isinstance(root_record, dict) or not isinstance(
        lighthouse_record,
        dict,
    ):
        raise LighthouseGateError(
            "package-lock.json has no pinned Lighthouse records."
        )
    root_dependencies = root_record.get("devDependencies")
    root_dependency = (
        root_dependencies.get("lighthouse")
        if isinstance(root_dependencies, dict)
        else None
    )
    integrity = lighthouse_record.get("integrity")
    if (
        dependency != EXPECTED_LIGHTHOUSE_VERSION
        or root_dependency != EXPECTED_LIGHTHOUSE_VERSION
        or lighthouse_record.get("version") != EXPECTED_LIGHTHOUSE_VERSION
        or lighthouse_record.get("resolved") != EXPECTED_LIGHTHOUSE_URL
        or integrity != EXPECTED_LIGHTHOUSE_INTEGRITY
    ):
        raise LighthouseGateError(
            "The Lighthouse dependency is not exactly lockfile-pinned."
        )
    return {
        "version": EXPECTED_LIGHTHOUSE_VERSION,
        "resolved": EXPECTED_LIGHTHOUSE_URL,
        "integrity": integrity,
    }


def normalize_windows_path(value: Path | str) -> str:
    normalized = ntpath.normpath(str(value).replace("/", "\\"))
    return normalized.rstrip("\\").lower()


def windows_path_has_traversal(value: Path | str) -> bool:
    return any(
        component in {".", ".."}
        for component in str(value).replace("/", "\\").split("\\")
    )


def known_windows_cleanup_error(
    stderr: str,
    *,
    returncode: int,
    owned_temp_root: Path,
    platform_name: str | None = None,
) -> bool:
    platform_name = os.name if platform_name is None else platform_name
    if platform_name != "nt" or returncode != 1:
        return False

    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return False

    root = normalize_windows_path(owned_temp_root)
    disallowed_diagnostics = (
        "fatal:",
        "navigation failed",
        "errored_document_request",
        "unable to connect",
        "chrome killed",
    )
    if any(
        token in stderr.lower()
        for token in disallowed_diagnostics
    ):
        return False
    primary_pattern = re.compile(
        r"^(?:error:\s*)?eperm(?:[:,]\s*)"
        r"(?:permission denied|operation not permitted),?\s*"
        r"(rmdir|unlink)\s+['\"]?([^'\"]+)['\"]?$",
        re.IGNORECASE,
    )
    primary_failure: tuple[str, str] | None = None
    structured_paths: list[str] = []
    structured_syscalls: list[str] = []
    launcher_seen = False
    for line in lines:
        normalized = line.replace("/", "\\").lower()
        primary_match = primary_pattern.fullmatch(line)
        if primary_match is not None:
            syscall = primary_match.group(1).lower()
            raw_failed_path = primary_match.group(2)
            if windows_path_has_traversal(raw_failed_path):
                return False
            failed_path = normalize_windows_path(raw_failed_path)
            owned_prefix = root + "\\"
            relative_path = (
                failed_path[len(owned_prefix):]
                if failed_path.startswith(owned_prefix)
                else ""
            )
            if not (
                relative_path.startswith("lighthouse.")
                or relative_path == "chrome-profile"
                or relative_path.startswith("chrome-profile\\")
            ):
                return False
            failure = (syscall, failed_path)
            if primary_failure is not None and failure != primary_failure:
                return False
            primary_failure = failure
            continue
        if re.fullmatch(
            r"at .*(?:node:internal|node_modules\\"
            r"(?:chrome-launcher|lighthouse)\\).*",
            normalized,
        ):
            launcher_seen = launcher_seen or "chrome-launcher" in normalized
            continue
        if normalized in {"{", "}"}:
            continue
        if re.fullmatch(r"errno:\s*-?[0-9]+,?", normalized):
            continue
        if re.fullmatch(r"code:\s*['\"]eperm['\"],?", normalized):
            continue
        syscall_match = re.fullmatch(
            r"syscall:\s*['\"](rmdir|unlink)['\"],?",
            normalized,
        )
        if syscall_match is not None:
            structured_syscalls.append(syscall_match.group(1))
            continue
        path_match = re.fullmatch(
            r"path:\s*['\"](.+)['\"],?",
            line,
            re.IGNORECASE,
        )
        if path_match is not None:
            if windows_path_has_traversal(path_match.group(1)):
                return False
            structured_paths.append(
                normalize_windows_path(path_match.group(1))
            )
            continue
        return False

    if primary_failure is None or not launcher_seen:
        return False
    syscall, failed_path = primary_failure
    return (
        all(value == syscall for value in structured_syscalls)
        and all(value == failed_path for value in structured_paths)
    )


def cleanup_owned_temp(path: Path, *, attempts: int = 5) -> None:
    if not path.name.startswith(PROFILE_PREFIX):
        raise LighthouseGateError("Refused to clean an unowned profile path.")
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            if path.exists():
                shutil.rmtree(path)
            if not path.exists():
                return
        except OSError as error:
            failures.append(type(error).__name__)
        if attempt < attempts:
            time.sleep(attempt)
    summary = ",".join(failures) if failures else "path_still_exists"
    raise LighthouseGateError(
        f"Owned Chrome profile cleanup failed after retries: {summary}."
    )


PosixProcessTable = dict[int, tuple[int, str, str]]


def posix_process_table() -> PosixProcessTable:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            [
                "ps",
                "-e",
                "-ww",
                "-o",
                "pid=",
                "-o",
                "ppid=",
                "-o",
                "lstart=",
                "-o",
                "args=",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise LighthouseGateError(
            "Could not inspect the owned Lighthouse process tree."
        ) from error
    if result.returncode != 0:
        raise LighthouseGateError(
            "Could not inspect the owned Lighthouse process tree."
        )

    table: PosixProcessTable = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) != 8 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        started = " ".join(parts[2:7])
        args = parts[7]
        table[pid] = (ppid, started, args)
    if not table:
        raise LighthouseGateError(
            "Could not inspect the owned Lighthouse process tree."
        )
    return table


def has_owned_profile_argument(args: str, chrome_profile: Path) -> bool:
    profile = re.escape(str(chrome_profile))
    return (
        re.search(
            rf"(?:^|\s)--user-data-dir=(?:{profile}|['\"]{profile}['\"])"
            rf"(?=$|\s)",
            args,
        )
        is not None
    )


def owned_posix_processes(
    *,
    root_pid: int,
    root_identity: tuple[str, str] | None,
    chrome_profile: Path,
    table: PosixProcessTable,
) -> dict[int, tuple[str, str]]:
    children: dict[int, set[int]] = {}
    for pid, (ppid, _started, _args) in table.items():
        children.setdefault(ppid, set()).add(pid)

    profile_pids = {
        pid
        for pid, (_ppid, _started, args) in table.items()
        if pid != os.getpid()
        and has_owned_profile_argument(args, chrome_profile)
    }
    descendants: set[int] = set()
    root_record = table.get(root_pid)
    root_matches = (
        root_identity is not None
        and root_record is not None
        and (root_record[1], root_record[2]) == root_identity
    )
    pending = list(profile_pids)
    if root_matches:
        pending.extend(children.get(root_pid, set()))
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, set()))

    owned: dict[int, tuple[str, str]] = {}
    for pid, (_ppid, started, args) in table.items():
        if pid == os.getpid() or pid == root_pid:
            continue
        if pid in descendants:
            owned[pid] = (started, args)
    return owned


def surviving_owned_posix_processes(
    *,
    root_pid: int,
    root_identity: tuple[str, str] | None,
    chrome_profile: Path,
    identities: dict[int, tuple[str, str]],
) -> dict[int, tuple[str, str]]:
    table = posix_process_table()
    identities.update(
        owned_posix_processes(
            root_pid=root_pid,
            root_identity=root_identity,
            chrome_profile=chrome_profile,
            table=table,
        )
    )
    survivors: dict[int, tuple[str, str]] = {}
    for pid, identity in identities.items():
        current = table.get(pid)
        if current is None:
            continue
        _ppid, started, args = current
        if (started, args) == identity or has_owned_profile_argument(
            args,
            chrome_profile,
        ):
            survivors[pid] = (started, args)
    return survivors


def signal_posix_processes(
    processes: dict[int, tuple[str, str]],
    requested_signal: int,
) -> None:
    for pid in processes:
        try:
            os.kill(pid, requested_signal)
        except ProcessLookupError:
            continue
        except OSError as error:
            raise LighthouseGateError(
                "Could not terminate an owned Lighthouse child process."
            ) from error


def wait_for_owned_posix_exit(
    *,
    root_pid: int,
    root_identity: tuple[str, str] | None,
    chrome_profile: Path,
    identities: dict[int, tuple[str, str]],
    timeout: float,
) -> dict[int, tuple[str, str]]:
    deadline = time.monotonic() + timeout
    while True:
        survivors = surviving_owned_posix_processes(
            root_pid=root_pid,
            root_identity=root_identity,
            chrome_profile=chrome_profile,
            identities=identities,
        )
        if not survivors or time.monotonic() >= deadline:
            return survivors
        time.sleep(0.2)


def terminate_process_tree(
    process: subprocess.Popen[str],
    *,
    chrome_profile: Path,
) -> None:
    if os.name == "nt":
        try:
            taskkill = subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise LighthouseGateError(
                "Could not terminate the owned Lighthouse process tree."
            ) from error
        if taskkill.returncode != 0:
            raise LighthouseGateError(
                "Could not terminate the owned Lighthouse process tree."
            )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise LighthouseGateError(
                "Owned Lighthouse processes survived timeout termination."
            ) from error
        if process.poll() is None:
            raise LighthouseGateError(
                "Owned Lighthouse processes survived timeout termination."
            )
        return

    initial_table = posix_process_table()
    root_record = initial_table.get(process.pid)
    root_identity = (
        (root_record[1], root_record[2])
        if root_record is not None
        else None
    )
    identities = owned_posix_processes(
        root_pid=process.pid,
        root_identity=root_identity,
        chrome_profile=chrome_profile,
        table=initial_table,
    )
    try:
        os.killpg(process.pid, signal.SIGINT)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass

    survivors = surviving_owned_posix_processes(
        root_pid=process.pid,
        root_identity=root_identity,
        chrome_profile=chrome_profile,
        identities=identities,
    )
    signal_posix_processes(survivors, signal.SIGTERM)
    survivors = wait_for_owned_posix_exit(
        root_pid=process.pid,
        root_identity=root_identity,
        chrome_profile=chrome_profile,
        identities=identities,
        timeout=3,
    )

    if process.poll() is None:
        try:
            os.killpg(process.pid, POSIX_SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    signal_posix_processes(survivors, POSIX_SIGKILL)
    survivors = wait_for_owned_posix_exit(
        root_pid=process.pid,
        root_identity=root_identity,
        chrome_profile=chrome_profile,
        identities=identities,
        timeout=2,
    )
    if process.poll() is None or survivors:
        raise LighthouseGateError(
            "Owned Lighthouse processes survived timeout termination."
        )


def process_group_arguments() -> dict[str, Any]:
    if os.name == "nt":
        return {
            "creationflags": getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        }
    return {"start_new_session": True}


def build_command(
    *,
    binary: Path,
    chrome_profile: Path,
    mode: str,
    requested_url: str,
    output: Path,
) -> list[str]:
    chrome_flags = (
        "--headless=new --disable-gpu --no-first-run "
        f'--user-data-dir="{chrome_profile}"'
    )
    command = [
        str(binary),
        requested_url,
        "--throttling-method=simulate",
        "--only-categories=" + ",".join(EXPECTED_CATEGORIES),
        "--locale=en-US",
        f"--chrome-flags={chrome_flags}",
        "--output=json",
        f"--output-path={output}",
        "--quiet",
    ]
    if mode == "desktop":
        command.append("--preset=desktop")
    elif mode == "mobile":
        command.extend(
            [
                "--form-factor=mobile",
                "--screenEmulation.mobile=true",
                "--screenEmulation.width=390",
                "--screenEmulation.height=844",
                "--screenEmulation.deviceScaleFactor=3",
            ]
        )
    else:
        raise ValueError("Unsupported Lighthouse mode.")
    return command


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_lighthouse_sample(
    *,
    repository_root: Path,
    mode: str,
    sample: int,
    requested_url: str,
    output: Path,
    timeout: int = PROCESS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if mode not in MODES or sample not in range(1, SAMPLES_PER_MODE + 1):
        raise ValueError("Invalid Lighthouse sample identity.")
    if output.exists():
        raise LighthouseGateError(
            "Lighthouse report already exists; evidence is immutable."
        )

    owned_temp_root = Path(tempfile.mkdtemp(prefix=PROFILE_PREFIX))
    chrome_profile = owned_temp_root / "chrome-profile"
    process: subprocess.Popen[str] | None = None
    stdout = ""
    stderr = ""
    started_at = utc_now()
    pending_error: Exception | None = None
    try:
        chrome_profile.mkdir()
        environment = os.environ.copy()
        environment["CHROME_PATH"] = str(find_chrome())
        environment["TEMP"] = str(owned_temp_root)
        environment["TMP"] = str(owned_temp_root)
        environment["TMPDIR"] = str(owned_temp_root)
        command = build_command(
            binary=lighthouse_binary(repository_root),
            chrome_profile=chrome_profile,
            mode=mode,
            requested_url=requested_url,
            output=output,
        )
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_group_arguments(),
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            terminate_process_tree(
                process,
                chrome_profile=chrome_profile,
            )
            try:
                stdout, stderr = process.communicate(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                pass
            pending_error = LighthouseGateError(
                "Lighthouse timed out and its process tree was terminated."
            )
    except Exception as error:
        pending_error = error
    finished_at = utc_now()

    try:
        cleanup_owned_temp(owned_temp_root)
    except Exception as cleanup_error:
        if pending_error is None:
            pending_error = cleanup_error
        else:
            pending_error = LighthouseGateError(
                "Lighthouse failed and owned Chrome profile cleanup failed."
            )

    if pending_error is not None:
        if isinstance(pending_error, LighthouseGateError):
            raise pending_error
        raise LighthouseGateError(
            f"Lighthouse process failed with {type(pending_error).__name__}."
        ) from pending_error
    if process is None:
        raise LighthouseGateError("Lighthouse process was not created.")
    if not output.is_file():
        raise LighthouseGateError("Lighthouse produced no JSON report.")

    payload = read_json_object(output, "Lighthouse report")
    summary = validate_report(
        payload,
        mode=mode,
        requested_url=requested_url,
        started_at=started_at,
        finished_at=finished_at,
    )
    returncode = process.returncode
    if not isinstance(returncode, int):
        raise LighthouseGateError("Lighthouse returned no process status.")

    cleanup_warning = False
    if returncode != 0:
        cleanup_warning = (
            stdout.strip() == ""
            and known_windows_cleanup_error(
                stderr,
                returncode=returncode,
                owned_temp_root=owned_temp_root,
            )
        )
        if not cleanup_warning:
            raise LighthouseGateError(
                "Lighthouse returned an unreviewed nonzero process status."
            )
        if summary["status"] != "PASS":
            raise LighthouseGateError(
                "A cleanup warning cannot waive a failing Lighthouse report."
            )

    return {
        "status": summary["status"],
        "mode": mode,
        "sample": sample,
        "report_file": output.name,
        "report_bytes": output.stat().st_size,
        "report_sha256": sha256_file(output),
        "requested_url": requested_url,
        "final_url": summary["final_url"],
        "fetch_time": summary["fetch_time"],
        "chrome_version": summary["chrome_version"],
        "lighthouse_version": summary["lighthouse_version"],
        "category_scores": summary["category_scores"],
        "audit_scores": summary["audit_scores"],
        "failures": summary["failures"],
        "process_return_code": returncode,
        "launcher_cleanup_warning": cleanup_warning,
        "stderr_sha256": hashlib.sha256(
            stderr.encode("utf-8")
        ).hexdigest(),
        "stdout_sha256": hashlib.sha256(
            stdout.encode("utf-8")
        ).hexdigest(),
        "started_at": isoformat_utc(started_at),
        "finished_at": isoformat_utc(finished_at),
    }


def prepare_output_directory(path: Path) -> Path:
    output = path.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise LighthouseGateError(
            "Lighthouse evidence directory already exists; use a new path."
        ) from error
    return output


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as error:
        raise LighthouseGateError(
            "Lighthouse receipt already exists; evidence is immutable."
        ) from error


def validate_sample_record(
    record: object,
    *,
    mode: str,
    sample: int,
    requested_url: str,
    output: Path,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise LighthouseGateError(
            "Lighthouse sample returned an unexpected evidence shape."
        )
    if (
        record.get("mode") != mode
        or record.get("sample") != sample
        or record.get("requested_url") != requested_url
        or record.get("report_file") != output.name
        or record.get("status") not in {"PASS", "FAIL"}
        or not output.is_file()
    ):
        raise LighthouseGateError(
            "Lighthouse sample identity or raw report is inconsistent."
        )
    actual_sha256 = sha256_file(output)
    if (
        record.get("report_bytes") != output.stat().st_size
        or record.get("report_sha256") != actual_sha256
    ):
        raise LighthouseGateError(
            "Lighthouse sample hash or byte size is inconsistent."
        )
    return record


def valid_percent(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    percent = float(value)
    if not math.isfinite(percent) or percent < 0 or percent > 100:
        return None
    return percent


def valid_sample_requested_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urllib.parse.urlsplit(value)
    try:
        query = urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc == "robbottx.com"
        and parsed.path == "/"
        and parsed.fragment == ""
        and set(query) == {"rbtxlh"}
        and len(query["rbtxlh"]) == 1
        and query["rbtxlh"][0] != ""
    )


def report_record_passes_release_gate(
    report: dict[str, Any],
    *,
    expected_requested_url: str,
) -> bool:
    requested_url = report.get("requested_url")
    if (
        report.get("status") != "PASS"
        or not valid_sample_requested_url(requested_url)
        or requested_url != expected_requested_url
        or report.get("final_url") != requested_url
        or report.get("report_file")
        != REPORT_FILE_PATTERN.format(
            mode=report.get("mode"),
            sample=report.get("sample"),
        )
        or report.get("lighthouse_version")
        != EXPECTED_LIGHTHOUSE_VERSION
        or re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+",
            report.get("chrome_version", ""),
        )
        is None
        or report.get("failures") != []
    ):
        return False

    categories = report.get("category_scores")
    if not isinstance(categories, dict) or set(categories) != set(
        EXPECTED_CATEGORIES
    ):
        return False
    performance = valid_percent(categories.get("performance"))
    if performance is None or performance < 90:
        return False
    for category in ("accessibility", "best-practices", "seo"):
        if valid_percent(categories.get(category)) != 100:
            return False

    audits = report.get("audit_scores")
    if not isinstance(audits, dict) or set(audits) != set(
        REQUIRED_BINARY_AUDITS
    ):
        return False
    if any(
        valid_percent(audits.get(audit_id)) != 100
        for audit_id in REQUIRED_BINARY_AUDITS
    ):
        return False

    returncode = report.get("process_return_code")
    cleanup_warning = report.get("launcher_cleanup_warning")
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        return False
    if not isinstance(cleanup_warning, bool) or not (
        (returncode == 0 and cleanup_warning is False)
        or (returncode == 1 and cleanup_warning is True)
    ):
        return False

    if (
        not isinstance(report.get("report_bytes"), int)
        or isinstance(report.get("report_bytes"), bool)
        or report["report_bytes"] <= 0
        or SHA256_PATTERN.fullmatch(report.get("report_sha256", "")) is None
        or SHA256_PATTERN.fullmatch(report.get("stderr_sha256", "")) is None
        or SHA256_PATTERN.fullmatch(report.get("stdout_sha256", "")) is None
    ):
        return False
    fetch_time = parse_fetch_time(report.get("fetch_time"))
    started_at = parse_fetch_time(report.get("started_at"))
    finished_at = parse_fetch_time(report.get("finished_at"))
    return (
        fetch_time is not None
        and started_at is not None
        and finished_at is not None
        and started_at <= finished_at
        and started_at - FETCH_TIME_TOLERANCE
        <= fetch_time
        <= finished_at + FETCH_TIME_TOLERANCE
    )


def aggregate_receipt(
    *,
    base_url: str,
    run_id: str,
    pin: dict[str, str],
    reports: list[dict[str, Any]],
    created_at: datetime,
    error_type: str | None = None,
) -> dict[str, Any]:
    mode_receipts: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        mode_reports = [
            report for report in reports if report.get("mode") == mode
        ]
        sample_numbers = {
            report.get("sample") for report in mode_reports
        }
        performance_scores: list[float] = []
        for report in mode_reports:
            categories = report.get("category_scores")
            performance = (
                valid_percent(categories.get("performance"))
                if isinstance(categories, dict)
                else None
            )
            if performance is not None:
                performance_scores.append(performance)
        complete = (
            len(mode_reports) == SAMPLES_PER_MODE
            and sample_numbers == set(range(1, SAMPLES_PER_MODE + 1))
        )
        all_reports_pass = complete and all(
            report_record_passes_release_gate(
                report,
                expected_requested_url=sample_url(
                    base_url,
                    run_id,
                    mode,
                    report["sample"],
                ),
            )
            for report in mode_reports
        )
        median_performance = (
            round(float(statistics.median(performance_scores)), 2)
            if len(performance_scores) == SAMPLES_PER_MODE
            else None
        )
        mode_receipts[mode] = {
            "status": (
                "PASS"
                if all_reports_pass
                else "FAIL"
            ),
            "report_count": len(mode_reports),
            "all_reports_pass": all_reports_pass,
            "median_performance": median_performance,
        }

    expected_identities = {
        (mode, sample)
        for mode in MODES
        for sample in range(1, SAMPLES_PER_MODE + 1)
    }
    report_identities = {
        (report.get("mode"), report.get("sample"))
        for report in reports
    }
    report_hashes = [
        report["report_sha256"]
        for report in reports
        if isinstance(report.get("report_sha256"), str)
    ]
    valid_report_hashes = [
        report_hash
        for report_hash in report_hashes
        if SHA256_PATTERN.fullmatch(report_hash) is not None
    ]
    chrome_versions = [
        report["chrome_version"]
        for report in reports
        if isinstance(report.get("chrome_version"), str)
    ]
    complete_release = (
        len(reports) == len(MODES) * SAMPLES_PER_MODE
        and report_identities == expected_identities
        and pin
        == {
            "version": EXPECTED_LIGHTHOUSE_VERSION,
            "resolved": EXPECTED_LIGHTHOUSE_URL,
            "integrity": EXPECTED_LIGHTHOUSE_INTEGRITY,
        }
        and len(report_hashes) == len(MODES) * SAMPLES_PER_MODE
        and len(valid_report_hashes) == len(MODES) * SAMPLES_PER_MODE
        and len(set(report_hashes)) == len(MODES) * SAMPLES_PER_MODE
        and len(chrome_versions) == len(MODES) * SAMPLES_PER_MODE
        and len(set(chrome_versions)) == 1
    )
    status = (
        "ERROR"
        if error_type is not None
        else (
            "PASS"
            if complete_release
            and all(
                mode_receipts[mode]["status"] == "PASS"
                for mode in MODES
            )
            else "FAIL"
        )
    )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "created_at": isoformat_utc(created_at),
        "target": base_url,
        "run_id": run_id,
        "samples_per_mode": SAMPLES_PER_MODE,
        "expected_report_count": len(MODES) * SAMPLES_PER_MODE,
        "report_count": len(reports),
        "tool": {
            "name": "Lighthouse",
            **pin,
        },
        "modes": mode_receipts,
        "reports": reports,
        "report_hashes": report_hashes,
        "chrome_version": (
            chrome_versions[0]
            if len(chrome_versions) == len(MODES) * SAMPLES_PER_MODE
            and len(set(chrome_versions)) == 1
            else None
        ),
        "cleanup_warning_count": sum(
            1
            for report in reports
            if report.get("launcher_cleanup_warning") is True
        ),
    }
    if error_type is not None:
        receipt["error_type"] = error_type
    return receipt


SampleRunner = Callable[..., dict[str, Any]]


def run_release(
    args: argparse.Namespace,
    *,
    sample_runner: SampleRunner = run_lighthouse_sample,
) -> tuple[int, dict[str, Any], Path]:
    repository_root = Path(__file__).resolve().parents[1]
    base_url = validate_base_url(args.url)
    pin = verify_lighthouse_pin(repository_root)
    output_dir = prepare_output_directory(args.output_dir)
    receipt_path = output_dir / RECEIPT_FILE_NAME
    run_id = secrets.token_hex(12)
    reports: list[dict[str, Any]] = []
    error_type: str | None = None

    for mode in MODES:
        if error_type is not None:
            break
        for sample in range(1, SAMPLES_PER_MODE + 1):
            output = output_dir / REPORT_FILE_PATTERN.format(
                mode=mode,
                sample=sample,
            )
            requested_url = sample_url(base_url, run_id, mode, sample)
            try:
                report = sample_runner(
                    repository_root=repository_root,
                    mode=mode,
                    sample=sample,
                    requested_url=requested_url,
                    output=output,
                )
                report = validate_sample_record(
                    report,
                    mode=mode,
                    sample=sample,
                    requested_url=requested_url,
                    output=output,
                )
            except Exception as error:
                error_type = type(error).__name__
                error_report: dict[str, Any] = {
                    "status": "ERROR",
                    "mode": mode,
                    "sample": sample,
                    "report_file": output.name,
                    "requested_url": requested_url,
                    "category_scores": {},
                    "failures": ["sample_execution"],
                    "launcher_cleanup_warning": False,
                    "error_type": error_type,
                }
                if output.is_file():
                    error_report.update(
                        {
                            "report_bytes": output.stat().st_size,
                            "report_sha256": sha256_file(output),
                        }
                    )
                reports.append(error_report)
                break
            reports.append(report)

    receipt = aggregate_receipt(
        base_url=base_url,
        run_id=run_id,
        pin=pin,
        reports=reports,
        created_at=utc_now(),
        error_type=error_type,
    )
    write_json_new(receipt_path, receipt)
    if receipt["status"] == "PASS":
        return 0, receipt, receipt_path
    if receipt["status"] == "FAIL":
        return 1, receipt, receipt_path
    return 2, receipt, receipt_path


def main() -> int:
    args = parse_args()
    try:
        exit_code, receipt, receipt_path = run_release(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path),
                "report_count": receipt["report_count"],
                "desktop_median_performance": receipt["modes"][
                    "desktop"
                ]["median_performance"],
                "mobile_median_performance": receipt["modes"][
                    "mobile"
                ]["median_performance"],
                "cleanup_warning_count": receipt[
                    "cleanup_warning_count"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
