"""Collection normalization helpers."""


def deduplicate(items: list) -> list:
    unique = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return sorted(unique, key=str)
