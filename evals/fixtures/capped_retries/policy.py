"""Retry policy calculations."""


def retry_delays(retries: int, base: int = 1, cap: int = 30) -> list[int]:
    return [base * (2 ** attempt) for attempt in range(retries)]
