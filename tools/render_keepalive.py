"""Wake the public demo services only during an explicitly configured window."""

import concurrent.futures
import datetime as dt
import json
import os
import re
import sys
import urllib.request


URLS = (
    "https://hiddenchain-platform-review.onrender.com/api/health/ready",
    "https://hiddenchain-electricity-connector.onrender.com/health",
    "https://hiddenchain-electricity-retailer.onrender.com/health",
    "https://hiddenchain-electricity-exchange.onrender.com/health",
    "https://hiddenchain-coal-connector.onrender.com/health",
    "https://hiddenchain-heat-connector.onrender.com/health",
    "https://hiddenchain-gas-connector.onrender.com/health",
    "https://hiddenchain-oil-connector.onrender.com/health",
)


def parse_utc(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ):
        raise ValueError("use UTC format YYYY-MM-DDTHH:MM:SSZ")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid UTC date or time") from exc


def check_window(env, now):
    window = env.get("RENDER_KEEPALIVE_WINDOW", "")
    if not isinstance(window, str) or window.count("/") != 1:
        raise ValueError("set RENDER_KEEPALIVE_WINDOW to START/END in UTC")
    start_text, end_text = window.split("/")
    start = parse_utc(start_text)
    end = parse_utc(end_text)
    if end <= start or end - start > dt.timedelta(hours=72):
        raise ValueError("window must be greater than zero and at most 72 hours")
    return start <= now < end


def run(env, now=None, opener=None):
    try:
        active = check_window(env, now or dt.datetime.now(dt.timezone.utc))
    except ValueError as exc:
        print(f"Keepalive disabled: {exc}", file=sys.stderr)
        return 1
    if not active:
        print("Keepalive inactive: current time is outside the configured window")
        return 0

    opener = opener or urllib.request.urlopen

    def check(url):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "HiddenChain-Competition-Keepalive/1.0"})
            with opener(request, timeout=180) as response:
                status = response.status
                if not 200 <= status < 300:
                    return url, f"HTTP {status}"
                if response.geturl() != url:
                    return url, "unexpected final URL"
                body = response.read(65537)
            if len(body) > 65536:
                return url, "health response exceeds 64 KiB"
            try:
                data = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                return url, "health response is not valid JSON"
            expected = "READY" if url == URLS[0] else "就绪"
            if not isinstance(data, dict) or data.get("status") != expected:
                return url, "unexpected health status"
            return url, None
        except Exception as exc:
            return url, f"{type(exc).__name__}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(URLS)) as pool:
        results = list(pool.map(check, URLS))
    for url, error in results:
        print(f"{'FAIL' if error else 'OK'} {url}" + (f" — {error}" if error else ""))
    return int(any(error for _, error in results))


if __name__ == "__main__":
    raise SystemExit(run(os.environ))
