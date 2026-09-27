"""Configuration merge helpers."""


def load_settings(defaults: dict, user: dict, environment: dict) -> dict:
    return {**defaults, **environment, **user}
