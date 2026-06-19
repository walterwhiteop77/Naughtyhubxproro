"""
bot_cfg.py — Runtime configuration overlay.

DB settings override info.py env-vars at function-call time.
Any plugin calls gcfg(KEY, fallback) to get the live value.
"""
import info as _info

_overrides: dict = {}


def gcfg(key: str, fallback=None):
    """Return DB override if present, else fallback, else info.py value."""
    if key in _overrides:
        return _overrides[key]
    if fallback is not None:
        return fallback
    return getattr(_info, key, None)


def set_cfg(key: str, value):
    """Update a runtime override (persist separately via db.set_bot_config)."""
    _overrides[key] = value


def load(settings_dict: dict):
    """Bulk-load settings from DB at startup."""
    _overrides.clear()
    for k, v in settings_dict.items():
        if v is not None:
            _overrides[k] = v
