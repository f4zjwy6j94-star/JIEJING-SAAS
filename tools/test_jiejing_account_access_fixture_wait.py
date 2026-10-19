"""Pure fixture-wait unit tests; no original suite, process, network or real sleep.

Run this unit module directly or discover with -s tools. Import the original
module by alias, never its TestCase class into module globals: unittest must
not discover AccountAccessLifecycleTests or run its real setUpClass here.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from email.message import Message
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# Isolated Python (-I) omits the script directory; add only this known tools path.
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import test_jiejing_account_access_lifecycle as lifecycle


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if not 0 < seconds <= 0.1:
            raise AssertionError("invalid virtual retry sleep")
        if len(self.sleeps) >= 1000:
            raise AssertionError("virtual retry ceiling exceeded")
        self.sleeps.append((self.now, seconds))
        self.now += seconds


class _Response(io.BytesIO):
    def __init__(self, body=b'{"ok":true}', *, status=200):
        super().__init__(body)
        self.status = status
        self.headers = Message()


class AccountAccessFixtureWaitTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.process = mock.Mock()
        self.process.poll.return_value = None
        self.owner = SimpleNamespace(
            process=self.process, base="http://127.0.0.1:54321")
        # Bind the real request implementation, not a copy or mocked replacement.
        self.owner.request = partial(
            lifecycle.AccountAccessLifecycleTests.request.__func__, self.owner)
        self._patch(lifecycle.time, "monotonic", self.clock.monotonic)
        self._patch(lifecycle.time, "sleep", self.clock.sleep)
        self.urlopen = self._patch(
            lifecycle.urllib.request, "urlopen",
            side_effect=AssertionError("unconfigured synthetic HTTP response"))
        # Defensive tripwires: an accidental call to original setup cannot launch.
        self._patch(lifecycle.subprocess, "Popen",
                    side_effect=AssertionError("real process prohibited"))
        self._patch(lifecycle.socket, "socket",
                    side_effect=AssertionError("real socket prohibited"))
        self._patch(lifecycle.tempfile, "TemporaryDirectory",
                    side_effect=AssertionError("real temporary directory prohibited"))

    def _patch(self, target, name, *args, **kwargs):
        patcher = mock.patch.object(target, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def _wait(self, phase="initial"):
        # No TestCase construction, suite loading, setUpClass or helper reimplementation.
        return lifecycle.AccountAccessLifecycleTests._wait_for_server.__func__(
            self.owner, phase=phase)

    def test_alive_fixture_ready_after_old_ten_second_budget_is_accepted(self):
        def probe(request, *, timeout):
            self.assertEqual(request.full_url, self.owner.base + "/health")
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.get_header("Authorization"))
            self.assertIsNone(request.get_header("Cookie"))
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, min(1.0, 60.0 - self.clock.now))
            if self.clock.now < 12.05:
                raise ConnectionRefusedError("synthetic not-yet-ready")
            return _Response()

        self.urlopen.side_effect = probe
        self.assertIsNone(self._wait())
        self.assertGreater(self.clock.now, 10.0)
        self.assertLess(self.clock.now, 60.0)
        self.assertIsNone(self.process.poll())

    def test_oserror_and_non_200_reach_deadline_without_false_success(self):
        for last_probe in ("ConnectionRefusedError", "HTTP 503"):
            with self.subTest(last_probe=last_probe):
                self.clock.now = 0.0
                self.clock.sleeps.clear()
                self.urlopen.reset_mock()

                def probe(request, *, timeout):
                    self.assertGreater(timeout, 0)
                    self.assertLessEqual(timeout, min(1.0, 60.0 - self.clock.now))
                    if last_probe == "ConnectionRefusedError":
                        raise ConnectionRefusedError("synthetic not-yet-ready")
                    return _Response(status=503)

                self.urlopen.side_effect = probe
                with self.assertRaisesRegex(AssertionError, "initial:.*readiness deadline") as caught:
                    self._wait()
                self.assertIn("last_probe=" + last_probe, str(caught.exception))
                self.assertAlmostEqual(self.clock.now, 60.0)
                self.assertTrue(self.clock.sleeps)
                for before, delay in self.clock.sleeps:
                    self.assertLessEqual(delay, min(0.1, 60.0 - before))

    def test_exit_before_first_probe_fails_with_no_http_or_sleep(self):
        for code in (0, 7):
            with self.subTest(code=code):
                self.process.poll.return_value = code
                with self.assertRaisesRegex(AssertionError, f"owned fixture exited {code}"):
                    self._wait()
                self.urlopen.assert_not_called()
                self.assertEqual(self.clock.sleeps, [])

    def test_child_exit_during_200_probe_cannot_be_accepted(self):
        def probe(request, *, timeout):
            self.process.poll.return_value = 3
            return _Response()

        self.urlopen.side_effect = probe
        with self.assertRaisesRegex(AssertionError, "owned fixture exited 3"):
            self._wait()
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_200_at_exact_deadline_or_after_deadline_is_rejected(self):
        for observed_at in (60.0, 60.1):
            with self.subTest(observed_at=observed_at):
                self.clock.now = 0.0
                self.urlopen.reset_mock()

                def probe(request, *, timeout):
                    self.clock.now = observed_at
                    return _Response()

                self.urlopen.side_effect = probe
                with self.assertRaisesRegex(AssertionError, "readiness deadline"):
                    self._wait()
                self.assertEqual(self.urlopen.call_count, 1)
                self.assertEqual(self.clock.sleeps, [])

    def test_remaining_time_caps_final_probe_timeout(self):
        timeouts = []

        def probe(request, *, timeout):
            timeouts.append(timeout)
            if len(timeouts) == 1:
                self.clock.now = 59.85
                raise ConnectionRefusedError("synthetic slow probe")
            self.assertEqual(len(timeouts), 2)
            self.clock.now += 0.01
            return _Response()

        self.urlopen.side_effect = probe
        self.assertIsNone(self._wait())
        self.assertEqual(timeouts[0], 1.0)
        self.assertAlmostEqual(timeouts[1], 0.05)
        self.assertGreater(timeouts[1], 0)
        self.assertLess(self.clock.now, 60.0)
        self.assertEqual(len(self.clock.sleeps), 1)
        before, delay = self.clock.sleeps[0]
        self.assertLessEqual(delay, min(0.1, 60.0 - before))

    def test_final_sleep_is_capped_and_does_not_start_another_probe(self):
        def probe(request, *, timeout):
            self.clock.now = 59.96
            return _Response(status=503)

        self.urlopen.side_effect = probe
        with self.assertRaisesRegex(AssertionError, "readiness deadline"):
            self._wait()
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(len(self.clock.sleeps), 1)
        self.assertAlmostEqual(self.clock.sleeps[0][1], 0.04)
        self.assertAlmostEqual(self.clock.now, 60.0)

    def test_malformed_health_json_is_not_swallowed(self):
        self.urlopen.side_effect = lambda request, timeout: _Response(b"{")
        with self.assertRaises(json.JSONDecodeError):
            self._wait()
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_unexpected_programming_error_is_not_swallowed(self):
        error = TypeError("synthetic programming error")
        self.urlopen.side_effect = error
        with self.assertRaises(TypeError) as caught:
            self._wait()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.urlopen.call_count, 1)
        self.assertEqual(self.clock.sleeps, [])

    def test_restart_polls_replacement_process_not_retired_process(self):
        retired = self.process
        retired.poll.return_value = 9
        replacement = mock.Mock()
        replacement.poll.return_value = None
        self.owner.process = replacement
        self.urlopen.side_effect = lambda request, timeout: _Response()
        self.assertIsNone(self._wait(phase="restart"))
        retired.poll.assert_not_called()
        replacement.poll.assert_called()
        self.assertEqual(self.urlopen.call_count, 1)

    def test_normal_business_request_keeps_default_fifteen_second_timeout(self):
        self.urlopen.side_effect = lambda request, timeout: _Response()
        status, body, cookies = self.owner.request("/me")
        self.assertEqual((status, body, cookies), (200, {"ok": True}, {}))
        self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 15)
        self.assertEqual(self.urlopen.call_args.args[0].full_url, self.owner.base + "/me")


if __name__ == "__main__":
    unittest.main()
