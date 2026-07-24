from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import signal
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-lighthouse.py"
SPEC = importlib.util.spec_from_file_location("run_lighthouse", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
lighthouse = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lighthouse
SPEC.loader.exec_module(lighthouse)


def iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        timeout_once: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timeout_once = timeout_once
        self.communicate_calls = 0
        self.pid = 4242
        self.killed = False

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.timeout_once and self.communicate_calls == 1:
            raise subprocess.TimeoutExpired("lighthouse", timeout)
        return self.stdout, self.stderr

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class RunLighthouseTests(unittest.TestCase):
    def valid_payload(
        self,
        *,
        mode: str = "desktop",
        url: str = "https://robbottx.com/?rbtxlh=run-desktop-1",
        performance: float = 0.95,
    ) -> dict:
        return {
            "lighthouseVersion": "13.4.1",
            "runtimeError": None,
            "requestedUrl": url,
            "finalUrl": url,
            "fetchTime": iso_now(),
            "environment": {
                "hostUserAgent": (
                    "Mozilla/5.0 Chrome/150.0.7339.0 Safari/537.36"
                )
            },
            "configSettings": {
                "formFactor": mode,
                "emulatedUserAgent": lighthouse.EMULATED_USER_AGENT[mode],
                "throttlingMethod": "simulate",
                "locale": "en-US",
                "onlyCategories": list(lighthouse.EXPECTED_CATEGORIES),
                "throttling": dict(lighthouse.THROTTLING[mode]),
                "screenEmulation": dict(
                    lighthouse.SCREEN_EMULATION[mode]
                ),
            },
            "categories": {
                "performance": {"score": performance},
                "accessibility": {"score": 1.0},
                "best-practices": {"score": 1.0},
                "seo": {"score": 1.0},
            },
            "audits": {
                "color-contrast": {"score": 1.0},
                "errors-in-console": {"score": 1.0},
            },
        }

    def report_record(
        self,
        output: Path,
        *,
        mode: str,
        sample: int,
        requested_url: str,
        performance: float = 95.0,
        status: str = "PASS",
        cleanup_warning: bool = False,
    ) -> dict:
        output.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "sample": sample,
                    "url": requested_url,
                    "performance": performance,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return {
            "status": status,
            "mode": mode,
            "sample": sample,
            "report_file": output.name,
            "report_bytes": output.stat().st_size,
            "report_sha256": digest,
            "requested_url": requested_url,
            "final_url": requested_url,
            "fetch_time": iso_now(),
            "chrome_version": "150.0.7339.0",
            "lighthouse_version": "13.4.1",
            "category_scores": {
                "performance": performance,
                "accessibility": 100.0,
                "best-practices": 100.0,
                "seo": 100.0,
            },
            "audit_scores": {
                "color-contrast": 100.0,
                "errors-in-console": 100.0,
            },
            "failures": [] if status == "PASS" else ["category_performance"],
            "process_return_code": 1 if cleanup_warning else 0,
            "launcher_cleanup_warning": cleanup_warning,
            "stderr_sha256": "a" * 64,
            "stdout_sha256": "b" * 64,
            "started_at": iso_now(),
            "finished_at": iso_now(),
        }

    def test_exact_desktop_and_mobile_reports_pass(self):
        for mode in lighthouse.MODES:
            url = f"https://robbottx.com/?rbtxlh=run-{mode}-1"
            summary = lighthouse.validate_report(
                self.valid_payload(mode=mode, url=url),
                mode=mode,
                requested_url=url,
            )
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["category_scores"]["performance"], 95.0)
            self.assertEqual(summary["chrome_version"], "150.0.7339.0")
            self.assertEqual(summary["failures"], [])

    def test_report_identity_runtime_and_configuration_fail_closed(self):
        base = self.valid_payload()
        invalid_cases = []

        wrong_version = copy.deepcopy(base)
        wrong_version["lighthouseVersion"] = "13.4.0"
        invalid_cases.append((wrong_version, "lighthouse_version"))

        runtime_error = copy.deepcopy(base)
        runtime_error["runtimeError"] = {}
        invalid_cases.append((runtime_error, "runtime_error"))

        wrong_requested = copy.deepcopy(base)
        wrong_requested["requestedUrl"] = "https://robbottx.com/?wrong=1"
        invalid_cases.append((wrong_requested, "requested_url"))

        wrong_final = copy.deepcopy(base)
        wrong_final["finalUrl"] = "https://robbottx.com/"
        invalid_cases.append((wrong_final, "final_url"))

        invalid_fetch_time = copy.deepcopy(base)
        invalid_fetch_time["fetchTime"] = "not-a-time"
        invalid_cases.append((invalid_fetch_time, "fetch_time"))

        no_chrome = copy.deepcopy(base)
        no_chrome["environment"]["hostUserAgent"] = "Example/1.0"
        invalid_cases.append((no_chrome, "chrome_version"))

        false_chrome_token = copy.deepcopy(base)
        false_chrome_token["environment"]["hostUserAgent"] = (
            "Mozilla/5.0 NotChrome/150.0.7339.0 Safari/537.36"
        )
        invalid_cases.append((false_chrome_token, "chrome_version"))

        edge_user_agent = copy.deepcopy(base)
        edge_user_agent["environment"]["hostUserAgent"] = (
            "Mozilla/5.0 Chrome/150.0.7339.0 Safari/537.36 "
            "Edg/150.0.7339.0"
        )
        invalid_cases.append((edge_user_agent, "chrome_version"))

        wrong_form_factor = copy.deepcopy(base)
        wrong_form_factor["configSettings"]["formFactor"] = "mobile"
        invalid_cases.append((wrong_form_factor, "config_form_factor"))

        wrong_emulated_user_agent = copy.deepcopy(base)
        wrong_emulated_user_agent["configSettings"][
            "emulatedUserAgent"
        ] = "Example/1.0"
        invalid_cases.append(
            (
                wrong_emulated_user_agent,
                "config_emulated_user_agent",
            )
        )

        wrong_viewport = copy.deepcopy(base)
        wrong_viewport["configSettings"]["screenEmulation"]["width"] = 390
        invalid_cases.append((wrong_viewport, "config_screen_width"))

        disabled_viewport = copy.deepcopy(base)
        disabled_viewport["configSettings"]["screenEmulation"][
            "disabled"
        ] = True
        invalid_cases.append(
            (disabled_viewport, "config_screen_disabled")
        )

        wrong_throttling = copy.deepcopy(base)
        wrong_throttling["configSettings"]["throttlingMethod"] = "provided"
        invalid_cases.append(
            (wrong_throttling, "config_throttling_method")
        )

        wrong_throttling_profile = copy.deepcopy(base)
        wrong_throttling_profile["configSettings"]["throttling"][
            "rttMs"
        ] = 41
        invalid_cases.append(
            (
                wrong_throttling_profile,
                "config_throttling_rttMs",
            )
        )

        wrong_locale = copy.deepcopy(base)
        wrong_locale["configSettings"]["locale"] = "en"
        invalid_cases.append((wrong_locale, "config_locale"))

        wrong_config_categories = copy.deepcopy(base)
        wrong_config_categories["configSettings"]["onlyCategories"] = [
            "performance"
        ]
        invalid_cases.append(
            (wrong_config_categories, "config_category_set")
        )

        malformed_config_categories = copy.deepcopy(base)
        malformed_config_categories["configSettings"]["onlyCategories"] = [
            {}
        ]
        invalid_cases.append(
            (malformed_config_categories, "config_category_set")
        )

        wrong_report_categories = copy.deepcopy(base)
        del wrong_report_categories["categories"]["seo"]
        invalid_cases.append((wrong_report_categories, "category_set"))

        for payload, expected_failure in invalid_cases:
            with self.subTest(expected_failure=expected_failure):
                summary = lighthouse.validate_report(
                    payload,
                    mode="desktop",
                    requested_url=base["requestedUrl"],
                )
                self.assertEqual(summary["status"], "FAIL")
                self.assertIn(expected_failure, summary["failures"])

    def test_scores_must_be_finite_non_boolean_and_within_unit_interval(self):
        invalid_values = (True, False, -0.01, 1.01, float("inf"), float("nan"))
        for value in invalid_values:
            with self.subTest(value=value):
                payload = self.valid_payload()
                payload["categories"]["performance"]["score"] = value
                summary = lighthouse.validate_report(
                    payload,
                    mode="desktop",
                    requested_url=payload["requestedUrl"],
                )
                self.assertEqual(summary["status"], "FAIL")
                self.assertIn(
                    "category_performance",
                    summary["failures"],
                )

        payload = self.valid_payload()
        payload["audits"]["color-contrast"]["score"] = True
        summary = lighthouse.validate_report(
            payload,
            mode="desktop",
            requested_url=payload["requestedUrl"],
        )
        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("audit_color-contrast", summary["failures"])

    def test_fetch_time_must_match_the_process_window(self):
        payload = self.valid_payload()
        started_at = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)
        finished_at = datetime(2026, 7, 24, 10, 5, tzinfo=timezone.utc)
        payload["fetchTime"] = "2026-07-24T09:00:00.000Z"
        summary = lighthouse.validate_report(
            payload,
            mode="desktop",
            requested_url=payload["requestedUrl"],
            started_at=started_at,
            finished_at=finished_at,
        )
        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("fetch_time_window", summary["failures"])

    def test_base_url_is_exact_and_sample_queries_are_unique(self):
        self.assertEqual(
            lighthouse.validate_base_url("https://robbottx.com/"),
            "https://robbottx.com/",
        )
        for invalid in (
            "http://robbottx.com/",
            "https://www.robbottx.com/",
            "https://robbottx.com",
            "https://robbottx.com/?existing=1",
            "https://robbottx.com/#fragment",
            "https://user@robbottx.com/",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(lighthouse.LighthouseGateError):
                    lighthouse.validate_base_url(invalid)

        urls = {
            lighthouse.sample_url(
                "https://robbottx.com/",
                "batch",
                mode,
                sample,
            )
            for mode in lighthouse.MODES
            for sample in range(1, 4)
        }
        self.assertEqual(len(urls), 6)
        self.assertTrue(
            all(url.startswith("https://robbottx.com/?rbtxlh=") for url in urls)
        )

    def test_lighthouse_pin_matches_package_and_lock_integrity(self):
        pin = lighthouse.verify_lighthouse_pin(ROOT)
        self.assertEqual(pin["version"], "13.4.1")
        self.assertEqual(
            pin["resolved"],
            lighthouse.EXPECTED_LIGHTHOUSE_URL,
        )
        self.assertEqual(
            pin["integrity"],
            lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps(
                    {"devDependencies": {"lighthouse": "^13.4.1"}}
                ),
                encoding="utf-8",
            )
            (root / "package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "": {
                                "devDependencies": {
                                    "lighthouse": "13.4.1"
                                }
                            },
                            "node_modules/lighthouse": {
                                "version": "13.4.1",
                                "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                                "integrity": "sha512-" + ("A" * 86) + "==",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(lighthouse.LighthouseGateError):
                lighthouse.verify_lighthouse_pin(root)
            (root / "package.json").write_text(
                json.dumps(
                    {"devDependencies": {"lighthouse": "13.4.1"}}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(lighthouse.LighthouseGateError):
                lighthouse.verify_lighthouse_pin(root)

    def test_known_windows_cleanup_warning_is_narrow_and_owned(self):
        owned = Path(
            r"C:\Users\example\AppData\Local\Temp"
            r"\robbottx-lighthouse-owned"
        )
        reviewed = (
            "Error: EPERM, permission denied, rmdir "
            f"'{owned}\\lighthouse.12345'\n"
            "at ChromeLauncher.destroyTmp "
            r"(C:\repo\node_modules\chrome-launcher\dist\launcher.js:10:2)"
            "\n"
            "at node:internal/process/task_queues:95:5\n"
        )
        self.assertTrue(
            lighthouse.known_windows_cleanup_error(
                reviewed,
                returncode=1,
                owned_temp_root=owned,
                platform_name="nt",
            )
        )
        self.assertTrue(
            lighthouse.known_windows_cleanup_error(
                reviewed
                + "code: 'EPERM',\n"
                + "syscall: 'rmdir',\n"
                + f"path: '{owned}\\lighthouse.12345'\n",
                returncode=1,
                owned_temp_root=owned,
                platform_name="nt",
            )
        )
        for invalid in (
            reviewed + "FATAL: navigation failed\n",
            reviewed.replace(
                "permission denied,",
                "permission denied, FATAL:",
            ),
            reviewed.replace("robbottx-lighthouse-owned", "other-profile"),
            reviewed.replace(
                "robbottx-lighthouse-owned",
                "robbottx-lighthouse-owned-other",
            ),
            reviewed.replace("chrome-launcher", "unrelated-module"),
            reviewed + r"path: 'C:\outside\other'" + "\n",
            reviewed + "syscall: 'unlink'\n",
            reviewed.replace(
                r"\lighthouse.12345",
                r"\chrome-profile\..\..\outside",
            ),
        ):
            with self.subTest(invalid=invalid[-80:]):
                self.assertFalse(
                    lighthouse.known_windows_cleanup_error(
                        invalid,
                        returncode=1,
                        owned_temp_root=owned,
                        platform_name="nt",
                    )
                )
        self.assertFalse(
            lighthouse.known_windows_cleanup_error(
                reviewed,
                returncode=2,
                owned_temp_root=owned,
                platform_name="nt",
            )
        )

    def test_aggregate_requires_all_six_reports_and_computes_medians(self):
        reports = []
        scores = {
            "desktop": (91.0, 95.0, 93.0),
            "mobile": (90.0, 96.0, 92.0),
        }
        for mode in lighthouse.MODES:
            for sample, performance in enumerate(scores[mode], start=1):
                requested_url = (
                    "https://robbottx.com/"
                    f"?rbtxlh=batch-{mode}-{sample}"
                )
                reports.append(
                    {
                        "status": "PASS",
                        "mode": mode,
                        "sample": sample,
                        "report_file": (
                            f"lighthouse-{mode}-run{sample}.json"
                        ),
                        "report_bytes": 100,
                        "report_sha256": (
                            f"{mode}-{sample}".encode().hex().ljust(64, "0")
                        )[:64],
                        "requested_url": requested_url,
                        "final_url": requested_url,
                        "fetch_time": iso_now(),
                        "started_at": iso_now(),
                        "finished_at": iso_now(),
                        "chrome_version": "150.0.7339.0",
                        "lighthouse_version": "13.4.1",
                        "category_scores": {
                            "performance": performance,
                            "accessibility": 100.0,
                            "best-practices": 100.0,
                            "seo": 100.0,
                        },
                        "audit_scores": {
                            "color-contrast": 100.0,
                            "errors-in-console": 100.0,
                        },
                        "failures": [],
                        "process_return_code": 0,
                        "launcher_cleanup_warning": False,
                        "stderr_sha256": "a" * 64,
                        "stdout_sha256": "b" * 64,
                    }
                )
        receipt = lighthouse.aggregate_receipt(
            base_url="https://robbottx.com/",
            run_id="batch",
            pin={
                "version": "13.4.1",
                "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                "integrity": lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY,
            },
            reports=reports,
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["report_count"], 6)
        self.assertEqual(len(receipt["report_hashes"]), 6)
        self.assertEqual(
            receipt["modes"]["desktop"]["median_performance"],
            93.0,
        )
        self.assertEqual(
            receipt["modes"]["mobile"]["median_performance"],
            92.0,
        )

        incomplete = lighthouse.aggregate_receipt(
            base_url="https://robbottx.com/",
            run_id="batch",
            pin=receipt["tool"],
            reports=reports[:-1],
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(incomplete["status"], "FAIL")
        self.assertFalse(
            incomplete["modes"]["mobile"]["all_reports_pass"]
        )

        malformed_hash = copy.deepcopy(reports)
        malformed_hash[0]["report_sha256"] = "not-a-sha256"
        duplicate_hash = copy.deepcopy(reports)
        duplicate_hash[0]["report_sha256"] = duplicate_hash[1][
            "report_sha256"
        ]
        missing_hash = copy.deepcopy(reports)
        del missing_hash[0]["report_sha256"]
        missing_performance = copy.deepcopy(reports)
        del missing_performance[0]["category_scores"]["performance"]
        nonfinite_performance = copy.deepcopy(reports)
        nonfinite_performance[0]["category_scores"]["performance"] = float(
            "nan"
        )
        inconsistent_chrome = copy.deepcopy(reports)
        inconsistent_chrome[0]["chrome_version"] = "151.0.7339.0"
        misbound_url = copy.deepcopy(reports)
        misbound_url[0]["requested_url"] = (
            "https://robbottx.com/?rbtxlh=other"
        )
        misbound_url[0]["final_url"] = misbound_url[0]["requested_url"]
        misbound_filename = copy.deepcopy(reports)
        misbound_filename[0]["report_file"] = "other.json"
        for invalid_reports in (
            malformed_hash,
            duplicate_hash,
            missing_hash,
            missing_performance,
            nonfinite_performance,
            inconsistent_chrome,
            misbound_url,
            misbound_filename,
        ):
            with self.subTest(report_hashes=invalid_reports):
                invalid_receipt = lighthouse.aggregate_receipt(
                    base_url="https://robbottx.com/",
                    run_id="batch",
                    pin=receipt["tool"],
                    reports=invalid_reports,
                    created_at=datetime.now(timezone.utc),
                )
                self.assertEqual(invalid_receipt["status"], "FAIL")

        invalid_pin = lighthouse.aggregate_receipt(
            base_url="https://robbottx.com/",
            run_id="batch",
            pin={
                "version": "13.4.1",
                "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                "integrity": "sha512-value",
            },
            reports=reports,
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(invalid_pin["status"], "FAIL")

    def test_release_run_creates_six_immutable_reports_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"
            calls = []

            def fake_runner(**kwargs):
                calls.append(kwargs)
                performance = {
                    "desktop": (91.0, 95.0, 93.0),
                    "mobile": (90.0, 96.0, 92.0),
                }[kwargs["mode"]][kwargs["sample"] - 1]
                return self.report_record(
                    kwargs["output"],
                    mode=kwargs["mode"],
                    sample=kwargs["sample"],
                    requested_url=kwargs["requested_url"],
                    performance=performance,
                    cleanup_warning=(
                        kwargs["mode"] == "mobile"
                        and kwargs["sample"] == 2
                    ),
                )

            args = argparse.Namespace(
                output_dir=output_dir,
                url="https://robbottx.com/",
            )
            with (
                patch.object(
                    lighthouse,
                    "verify_lighthouse_pin",
                    return_value={
                        "version": "13.4.1",
                        "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                        "integrity": (
                            lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY
                        ),
                    },
                ),
                patch.object(
                    lighthouse.secrets,
                    "token_hex",
                    return_value="fixedrun",
                ),
            ):
                exit_code, receipt, receipt_path = (
                    lighthouse.run_release(
                        args,
                        sample_runner=fake_runner,
                    )
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(len(calls), 6)
            self.assertEqual(len(receipt["report_hashes"]), 6)
            self.assertEqual(receipt["cleanup_warning_count"], 1)
            self.assertEqual(
                receipt["modes"]["desktop"]["median_performance"],
                93.0,
            )
            self.assertEqual(
                receipt["modes"]["mobile"]["median_performance"],
                92.0,
            )
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(
                len(list(output_dir.glob("lighthouse-*-run*.json"))),
                6,
            )
            requested_urls = {
                call["requested_url"] for call in calls
            }
            self.assertEqual(len(requested_urls), 6)
            self.assertTrue(
                all("rbtxlh=fixedrun-" in url for url in requested_urls)
            )

            with self.assertRaises(lighthouse.LighthouseGateError):
                lighthouse.run_release(
                    args,
                    sample_runner=fake_runner,
                )

    def test_one_failing_report_runs_all_samples_and_fails_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"
            calls = []

            def fake_runner(**kwargs):
                calls.append(kwargs)
                is_failure = (
                    kwargs["mode"] == "desktop"
                    and kwargs["sample"] == 2
                )
                return self.report_record(
                    kwargs["output"],
                    mode=kwargs["mode"],
                    sample=kwargs["sample"],
                    requested_url=kwargs["requested_url"],
                    performance=89.0 if is_failure else 95.0,
                    status="FAIL" if is_failure else "PASS",
                )

            args = argparse.Namespace(
                output_dir=output_dir,
                url="https://robbottx.com/",
            )
            with patch.object(
                lighthouse,
                "verify_lighthouse_pin",
                return_value={
                    "version": "13.4.1",
                    "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                    "integrity": lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY,
                },
            ):
                exit_code, receipt, _ = lighthouse.run_release(
                    args,
                    sample_runner=fake_runner,
                )
            self.assertEqual(exit_code, 1)
            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(len(calls), 6)
            self.assertEqual(receipt["report_count"], 6)
            self.assertFalse(
                receipt["modes"]["desktop"]["all_reports_pass"]
            )

    def test_release_rejects_a_misbound_sample_record(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"

            def misbound_runner(**kwargs):
                record = self.report_record(
                    kwargs["output"],
                    mode=kwargs["mode"],
                    sample=kwargs["sample"],
                    requested_url=kwargs["requested_url"],
                )
                record["sample"] = 3
                return record

            args = argparse.Namespace(
                output_dir=output_dir,
                url="https://robbottx.com/",
            )
            with patch.object(
                lighthouse,
                "verify_lighthouse_pin",
                return_value={
                    "version": "13.4.1",
                    "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                    "integrity": lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY,
                },
            ):
                exit_code, receipt, _ = lighthouse.run_release(
                    args,
                    sample_runner=misbound_runner,
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(receipt["status"], "ERROR")
            self.assertEqual(receipt["reports"][0]["status"], "ERROR")
            self.assertEqual(len(receipt["report_hashes"]), 1)

    def test_execution_error_receipt_hashes_any_preserved_raw_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"

            def failing_runner(**kwargs):
                kwargs["output"].write_text(
                    '{"partial":"preserved"}\n',
                    encoding="utf-8",
                )
                raise lighthouse.LighthouseGateError(
                    "unreviewed process status"
                )

            args = argparse.Namespace(
                output_dir=output_dir,
                url="https://robbottx.com/",
            )
            with patch.object(
                lighthouse,
                "verify_lighthouse_pin",
                return_value={
                    "version": "13.4.1",
                    "resolved": lighthouse.EXPECTED_LIGHTHOUSE_URL,
                    "integrity": lighthouse.EXPECTED_LIGHTHOUSE_INTEGRITY,
                },
            ):
                exit_code, receipt, receipt_path = (
                    lighthouse.run_release(
                        args,
                        sample_runner=failing_runner,
                    )
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(receipt["status"], "ERROR")
            self.assertEqual(receipt["report_count"], 1)
            self.assertEqual(len(receipt["report_hashes"]), 1)
            self.assertEqual(
                receipt["reports"][0]["status"],
                "ERROR",
            )
            self.assertTrue(receipt_path.is_file())
            self.assertTrue(
                (output_dir / "lighthouse-desktop-run1.json").is_file()
            )

    def run_sample_with_fake_process(
        self,
        *,
        directory: str,
        process: FakeProcess,
        mode: str = "desktop",
        patch_cleanup_warning=None,
        deterministic_profile: Path | None = None,
    ):
        root = Path(directory)
        chrome = root / "chrome.exe"
        binary = root / "lighthouse.cmd"
        chrome.write_text("chrome", encoding="utf-8")
        binary.write_text("lighthouse", encoding="utf-8")
        output = root / "report.json"
        requested_url = f"https://robbottx.com/?rbtxlh=sample-{mode}-1"
        payload = self.valid_payload(mode=mode, url=requested_url)

        def fake_popen(command, **kwargs):
            output_argument = next(
                item for item in command if item.startswith("--output-path=")
            )
            report_path = Path(output_argument.split("=", 1)[1])
            report_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            return process

        patches = [
            patch.object(lighthouse, "find_chrome", return_value=chrome),
            patch.object(
                lighthouse,
                "lighthouse_binary",
                return_value=binary,
            ),
            patch.object(
                lighthouse.subprocess,
                "Popen",
                side_effect=fake_popen,
            ),
        ]
        if patch_cleanup_warning is not None:
            patches.append(
                patch.object(
                    lighthouse,
                    "known_windows_cleanup_error",
                    return_value=patch_cleanup_warning,
                )
            )
        if deterministic_profile is not None:
            deterministic_profile.mkdir()
            patches.append(
                patch.object(
                    lighthouse.tempfile,
                    "mkdtemp",
                    return_value=str(deterministic_profile),
                )
            )

        entered = []
        try:
            for manager in patches:
                entered.append(manager)
                manager.start()
            result = lighthouse.run_lighthouse_sample(
                repository_root=root,
                mode=mode,
                sample=1,
                requested_url=requested_url,
                output=output,
            )
        finally:
            for manager in reversed(entered):
                manager.stop()
        return result, output

    def test_sample_process_success_and_warning_metadata_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            result, output = self.run_sample_with_fake_process(
                directory=directory,
                process=FakeProcess(returncode=0),
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["process_return_code"], 0)
            self.assertFalse(result["launcher_cleanup_warning"])
            self.assertEqual(
                result["report_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )

        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_sample_with_fake_process(
                directory=directory,
                process=FakeProcess(
                    returncode=1,
                    stderr="reviewed cleanup warning",
                ),
                patch_cleanup_warning=True,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["process_return_code"], 1)
            self.assertTrue(result["launcher_cleanup_warning"])
            self.assertNotEqual(result["stderr_sha256"], "0" * 64)

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                lighthouse.LighthouseGateError,
                "unreviewed nonzero",
            ):
                self.run_sample_with_fake_process(
                    directory=directory,
                    process=FakeProcess(
                        returncode=1,
                        stdout="FATAL: navigation failed",
                        stderr="reviewed cleanup warning",
                    ),
                    patch_cleanup_warning=True,
                )

    def test_unreviewed_nonzero_exit_fails_but_preserves_raw_report(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                lighthouse.LighthouseGateError,
                "unreviewed nonzero",
            ):
                self.run_sample_with_fake_process(
                    directory=directory,
                    process=FakeProcess(
                        returncode=1,
                        stderr="FATAL: navigation failed",
                    ),
                    patch_cleanup_warning=False,
                )
            self.assertTrue((Path(directory) / "report.json").is_file())

    def test_timeout_terminates_tree_and_cleans_owned_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chrome = root / "chrome.exe"
            binary = root / "lighthouse.cmd"
            chrome.write_text("chrome", encoding="utf-8")
            binary.write_text("lighthouse", encoding="utf-8")
            profile = root / "robbottx-lighthouse-timeout"
            process = FakeProcess(returncode=-9, timeout_once=True)
            output = root / "report.json"
            requested_url = (
                "https://robbottx.com/?rbtxlh=timeout-desktop-1"
            )

            with (
                patch.object(lighthouse, "find_chrome", return_value=chrome),
                patch.object(
                    lighthouse,
                    "lighthouse_binary",
                    return_value=binary,
                ),
                patch.object(
                    lighthouse.tempfile,
                    "mkdtemp",
                    return_value=str(profile),
                ),
                patch.object(
                    lighthouse.subprocess,
                    "Popen",
                    return_value=process,
                ),
                patch.object(
                    lighthouse,
                    "terminate_process_tree",
                ) as terminate,
            ):
                profile.mkdir()
                with self.assertRaisesRegex(
                    lighthouse.LighthouseGateError,
                    "timed out",
                ):
                    lighthouse.run_lighthouse_sample(
                        repository_root=root,
                        mode="desktop",
                        sample=1,
                        requested_url=requested_url,
                        output=output,
                        timeout=1,
                    )

            terminate.assert_called_once_with(
                process,
                chrome_profile=profile / "chrome-profile",
            )
            self.assertFalse(profile.exists())

    def test_pre_spawn_failure_still_cleans_owned_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "robbottx-lighthouse-pre-spawn"
            profile.mkdir()
            output = root / "report.json"
            with (
                patch.object(
                    lighthouse.tempfile,
                    "mkdtemp",
                    return_value=str(profile),
                ),
                patch.object(
                    lighthouse,
                    "find_chrome",
                    side_effect=lighthouse.LighthouseGateError(
                        "Chrome missing"
                    ),
                ),
                patch.object(lighthouse.subprocess, "Popen") as popen,
                self.assertRaisesRegex(
                    lighthouse.LighthouseGateError,
                    "Chrome missing",
                ),
            ):
                lighthouse.run_lighthouse_sample(
                    repository_root=root,
                    mode="desktop",
                    sample=1,
                    requested_url=(
                        "https://robbottx.com/?rbtxlh=pre-spawn-desktop-1"
                    ),
                    output=output,
                )
            popen.assert_not_called()
            self.assertFalse(profile.exists())

    def test_posix_timeout_owns_detached_profile_processes(self):
        profile = Path("/tmp/robbottx-lighthouse-owned/chrome-profile")
        started = "Thu Jul 24 00:00:00 2026"
        table = {
            100: (1, started, "node lighthouse"),
            101: (100, started, "node chrome-launcher"),
            102: (
                1,
                started,
                f"chrome --user-data-dir={profile} --headless=new",
            ),
            103: (1, started, "unrelated-service"),
            104: (102, started, "chrome --type=renderer"),
        }
        owned = lighthouse.owned_posix_processes(
            root_pid=100,
            root_identity=(started, "node lighthouse"),
            chrome_profile=profile,
            table=table,
        )
        self.assertEqual(set(owned), {101, 102, 104})
        reused_root_table = dict(table)
        reused_root_table[100] = (
            1,
            "Thu Jul 24 00:01:00 2026",
            "unrelated-reused-root",
        )
        reused_root_table[105] = (
            100,
            "Thu Jul 24 00:01:01 2026",
            "unrelated-child",
        )
        reused_owned = lighthouse.owned_posix_processes(
            root_pid=100,
            root_identity=(started, "node lighthouse"),
            chrome_profile=profile,
            table=reused_root_table,
        )
        self.assertNotIn(105, reused_owned)
        self.assertFalse(
            lighthouse.has_owned_profile_argument(
                f"chrome --user-data-dir={profile}-other",
                profile,
            )
        )

        process = FakeProcess(returncode=-9)
        process.pid = 100
        with (
            patch.object(lighthouse.os, "name", "posix"),
            patch.object(
                lighthouse,
                "posix_process_table",
                return_value=table,
            ),
            patch.object(
                lighthouse,
                "surviving_owned_posix_processes",
                return_value=owned,
            ),
            patch.object(
                lighthouse,
                "wait_for_owned_posix_exit",
                side_effect=({}, {}),
            ),
            patch.object(
                lighthouse,
                "signal_posix_processes",
            ) as signal_owned,
            patch.object(
                lighthouse.os,
                "killpg",
                create=True,
            ) as kill_group,
        ):
            lighthouse.terminate_process_tree(
                process,
                chrome_profile=profile,
            )

        kill_group.assert_called_once_with(100, signal.SIGINT)
        self.assertEqual(
            signal_owned.call_args_list,
            [
                call(owned, signal.SIGTERM),
                call({}, lighthouse.POSIX_SIGKILL),
            ],
        )

    def test_windows_timeout_requires_successful_tree_termination(self):
        profile = Path(r"C:\Temp\robbottx-lighthouse-owned\chrome-profile")
        process = FakeProcess(returncode=-9)
        with (
            patch.object(lighthouse.os, "name", "nt"),
            patch.object(
                lighthouse.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["taskkill"],
                    returncode=0,
                ),
            ) as taskkill,
        ):
            lighthouse.terminate_process_tree(
                process,
                chrome_profile=profile,
            )
        self.assertIn("/T", taskkill.call_args.args[0])
        self.assertIn("/F", taskkill.call_args.args[0])

        with (
            patch.object(lighthouse.os, "name", "nt"),
            patch.object(
                lighthouse.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["taskkill"],
                    returncode=1,
                ),
            ),
            self.assertRaisesRegex(
                lighthouse.LighthouseGateError,
                "Could not terminate",
            ),
        ):
            lighthouse.terminate_process_tree(
                process,
                chrome_profile=profile,
            )

    def test_report_and_receipt_overwrite_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "report.json"
            output.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(
                lighthouse.LighthouseGateError,
                "already exists",
            ):
                lighthouse.run_lighthouse_sample(
                    repository_root=root,
                    mode="desktop",
                    sample=1,
                    requested_url=(
                        "https://robbottx.com/?rbtxlh=existing-desktop-1"
                    ),
                    output=output,
                )
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "preserve",
            )

            receipt = root / "receipt.json"
            receipt.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(
                lighthouse.LighthouseGateError,
                "receipt already exists",
            ):
                lighthouse.write_json_new(
                    receipt,
                    {"status": "PASS"},
                )
            self.assertEqual(
                receipt.read_text(encoding="utf-8"),
                "preserve",
            )


if __name__ == "__main__":
    unittest.main()
