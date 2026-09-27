"""Cache key construction for localized tenant responses."""


def make_cache_key(url: str, locale: str, tenant: str) -> str:
    return url
