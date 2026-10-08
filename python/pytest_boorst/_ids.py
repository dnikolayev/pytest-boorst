"""Python comparison implementation for the parameter ID benchmark."""

from collections import Counter, defaultdict


def unique_ids_pytest7(ids: list[str]) -> list[str]:
    """Preserve pytest 7's suffixes, including collisions with existing IDs."""
    result = list(ids)
    counts = Counter(ids)
    suffixes: dict[str, int] = defaultdict(int)
    for index, value in enumerate(ids):
        if counts[value] > 1:
            result[index] = f"{value}{suffixes[value]}"
            suffixes[value] += 1
    return result


def unique_ids(ids: list[str]) -> list[str]:
    """Match pytest suffixing while maintaining the live ID counts."""
    result = list(ids)
    counts = Counter(ids)
    if len(counts) == len(ids):
        return result
    occupied = counts.copy()
    suffixes: dict[str, int] = defaultdict(int)
    for index, value in enumerate(ids):
        if counts[value] < 2:
            continue
        separator = "_" if value and value[-1].isdigit() else ""
        suffix = suffixes[value]
        candidate = f"{value}{separator}{suffix}"
        while candidate in occupied:
            suffix += 1
            candidate = f"{value}{separator}{suffix}"
        occupied[value] -= 1
        if not occupied[value]:
            del occupied[value]
        occupied[candidate] += 1
        result[index] = candidate
        suffixes[value] = suffix + 1
    return result
