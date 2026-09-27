"""Parse pipe-delimited counter records."""


def parse_records(lines: list[str]) -> list[tuple[str, int]]:
    records = []
    for line in lines:
        name, raw_count = line.strip().split("|", maxsplit=1)
        records.append((name, int(raw_count)))
    return records
