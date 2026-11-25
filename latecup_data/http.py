"""Polite HTTP: one User-Agent, timeouts, retries with backoff."""
import time

import requests

from . import USER_AGENT

_session = None


def session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = USER_AGENT
    return _session


def request(method, url, *, retries=4, timeout=180, backoff=15.0, sleep=time.sleep, **kw):
    """-> bytes. Retries on network errors, 429 and 5xx."""
    last = None
    for attempt in range(retries):
        try:
            r = session().request(method, url, timeout=(15, timeout), **kw)
            if r.status_code == 200:
                return r.content
            last = IOError(f"HTTP {r.status_code}")
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.RequestException as e:
            last = e
        if attempt < retries - 1:
            sleep(backoff * (attempt + 1))
    raise IOError(f"{method} failed: {url}: {last}")


def get(url, **kw):
    return request("GET", url, **kw)
