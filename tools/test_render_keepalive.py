import contextlib
import datetime as dt
import io
import json
import unittest
from unittest.mock import Mock

from tools import render_keepalive as keepalive


START = "2026-11-01T00:00:00Z"
END = "2026-11-04T00:00:00Z"
ENV = {"RENDER_KEEPALIVE_WINDOW": f"{START}/{END}"}


def at(value):
    return keepalive.parse_utc(value)


class Response:
    status = 200

    def __init__(self, url, *, body=None, final_url=None):
        self.url = url
        self.body = body if body is not None else json.dumps(
            {"status": "READY" if url == keepalive.URLS[0] else "就绪"}
        ).encode()
        self.final_url = final_url or url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.final_url

    def read(self, limit):
        return self.body[:limit]


def ok_response(request, timeout):
    return Response(request.full_url)


class KeepaliveTests(unittest.TestCase):
    def run_quietly(self, env, now, opener):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return keepalive.run(env, now, opener)

    def test_missing_invalid_and_disallowed_windows_never_send(self):
        invalid = [
            {},
            {"RENDER_KEEPALIVE_WINDOW": ""},
            {"RENDER_KEEPALIVE_WINDOW": START},
            {"RENDER_KEEPALIVE_WINDOW": f"{START}/{END}/extra"},
            {"RENDER_KEEPALIVE_WINDOW": f"2026-11-01T00:00:00+00:00/{END}"},
            {"RENDER_KEEPALIVE_WINDOW": f"2026-02-30T00:00:00Z/{END}"},
            {"RENDER_KEEPALIVE_WINDOW": f"{START}/{START}"},
            {"RENDER_KEEPALIVE_WINDOW": f"{START}/2026-10-31T23:59:59Z"},
            {"RENDER_KEEPALIVE_WINDOW": f"{START}/2026-11-04T00:00:01Z"},
        ]
        for env in invalid:
            with self.subTest(env=env):
                opener = Mock()
                self.assertEqual(self.run_quietly(env, at(START), opener), 1)
                opener.assert_not_called()

    def test_window_start_inclusive_end_exclusive(self):
        for time in ("2026-10-31T23:59:59Z", END):
            opener = Mock()
            self.assertEqual(self.run_quietly(ENV, at(time), opener), 0)
            opener.assert_not_called()
        for time in (START, "2026-11-03T23:59:59Z"):
            opener = Mock(side_effect=ok_response)
            self.assertEqual(self.run_quietly(ENV, at(time), opener), 0)
            self.assertEqual(opener.call_count, 8)

    def test_requests_only_the_fixed_expected_health_urls(self):
        opener = Mock(side_effect=ok_response)
        self.assertEqual(self.run_quietly(ENV, at(START), opener), 0)
        requested = {call.args[0].full_url for call in opener.call_args_list}
        self.assertEqual(requested, set(keepalive.URLS))
        self.assertEqual(len(requested), 8)
        self.assertTrue(all(call.kwargs["timeout"] == 180 for call in opener.call_args_list))

    def test_http_failure_and_network_error_report_failure(self):
        class BadResponse(Response):
            status = 503

        def open_url(request, timeout):
            if "coal" in request.full_url:
                return BadResponse(request.full_url)
            if "gas" in request.full_url:
                raise TimeoutError("timeout")
            return Response(request.full_url)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(keepalive.run(ENV, at(START), open_url), 1)
        self.assertIn("HTTP 503", output.getvalue())
        self.assertIn("TimeoutError", output.getvalue())
        self.assertEqual(output.getvalue().count("FAIL "), 2)

    def test_invalid_health_payloads_and_redirect_are_rejected(self):
        cases = [
            ({"body": b"<html>loading</html>"}, "not valid JSON"),
            ({"body": b'{"status":"NOT_READY"}'}, "unexpected health status"),
            ({"body": b'[]'}, "unexpected health status"),
            ({"body": b"x" * 65537}, "exceeds 64 KiB"),
            ({"final_url": "https://example.com/"}, "unexpected final URL"),
        ]
        for kwargs, message in cases:
            with self.subTest(message=message):
                def open_url(request, timeout):
                    return Response(request.full_url, **(kwargs if request.full_url == keepalive.URLS[0] else {}))

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(keepalive.run(ENV, at(START), open_url), 1)
                self.assertIn(message, output.getvalue())
                self.assertEqual(output.getvalue().count("FAIL "), 1)
                self.assertNotIn("<html>", output.getvalue())

    def test_connector_ready_must_use_connector_status(self):
        def open_url(request, timeout):
            if request.full_url == keepalive.URLS[1]:
                return Response(request.full_url, body=b'{"status":"READY"}')
            return Response(request.full_url)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(keepalive.run(ENV, at(START), open_url), 1)


if __name__ == "__main__":
    unittest.main()
