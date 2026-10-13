"""Answer the signal API from a local copy of the signal engine, for the screenshot tools.

Some networks block a brand's site from the machine that takes the pictures. With KEEL_SIGNAL_ENGINE set to the path
of the site's engine module (for autotradingbots.ai, backend/core/services/binary_signal.py), the screenshot tools
answer GET /s-api/binary-signal from that module instead of the network. It is the same file the server runs, and a
read depends only on the selection and the candle, so the answer is the one the live site would give. A fast expiry
without a licence key is refused with 403, as the server refuses it. Unset, nothing changes: every read goes live.
"""
import importlib.util
import json
import os
from urllib.parse import parse_qs, urlparse

ENV = "KEEL_SIGNAL_ENGINE"
_module = None


def enabled():
    return bool(os.environ.get(ENV))


def engine():
    global _module
    if _module is None:
        path = os.path.expanduser(os.environ[ENV])
        spec = importlib.util.spec_from_file_location("keel_local_signal_engine", path)
        _module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_module)
    return _module


def answer(url):
    """(status, body) for one /s-api/binary-signal URL, as the server would answer it."""
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    signal = engine()
    broker, tf = q.get("broker", ""), q.get("tf", "")
    if signal.is_premium_tf(tf, broker) and not q.get("key"):
        return 403, {"error": "license_required"}
    read = signal.build_signal(broker, q.get("pair", ""), tf, int(q.get("salt", "0") or 0), q.get("prev"), q.get("mode", "real"),
                               aligned=q.get("entry") == "aligned")
    return 200, read


def route(shift=0, shift_json=None):
    """A Playwright route handler for <site>/s-api/binary-signal*, timestamps moved by `shift` seconds when given."""
    def handler(r, request=None):
        status, body = answer(r.request.url)
        if shift and shift_json:
            body = shift_json(body, shift)
        r.fulfill(status=status, content_type="application/json", body=json.dumps(body))
    return handler
