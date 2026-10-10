"""A weekday clock for store screenshots.

The signal apps close the real market at weekends from the visitor's own clock, so a picture taken on a Saturday says
"real market shut". Store pictures show what the product does, not today's date, so the screenshot tools move the
page's clock forward to the next weekday at the same time of day (no shift on a weekday), and move every timestamp
the signal API returns by the same amount, so countdowns and candle times still agree with the page.
"""
import time

DAY = 86400
TIMESTAMP_KEYS = ("server_time",)


def shift_seconds(now=None):
    """Whole days from now to the next moment the real market is open (Mon to Thu, or Friday before 20:00 UTC)."""
    now = time.time() if now is None else now
    days = 0
    while True:
        t = time.gmtime(now + days * DAY)
        if t.tm_wday <= 3 or (t.tm_wday == 4 and t.tm_hour < 20):
            return days * DAY
        days += 1


def init_script(shift):
    """Page script: Date runs `shift` seconds ahead, still ticking."""
    return """(() => {
    const shift = %d, Real = Date;
    class Shifted extends Real {
        constructor(...a) { if (a.length) super(...a); else super(Real.now() + shift); }
        static now() { return Real.now() + shift; }
    }
    window.Date = Shifted;
})();""" % (shift * 1000)


def shift_json(data, shift):
    """Every epoch-seconds timestamp in an API answer (keys ending in _at, and server_time) moved by `shift`."""
    if not shift:
        return data
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 1e9 and (k.endswith("_at") or k in TIMESTAMP_KEYS):
                out[k] = v + shift
            else:
                out[k] = shift_json(v, shift)
        return out
    if isinstance(data, list):
        return [shift_json(v, shift) for v in data]
    return data
