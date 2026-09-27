"""Return log-safe copies of configuration values."""

SENSITIVE_KEYS = {"password", "token", "secret"}


def redact(value):
    if not isinstance(value, dict):
        return value
    return {
        key: "***" if key.lower() in SENSITIVE_KEYS else item
        for key, item in value.items()
    }
