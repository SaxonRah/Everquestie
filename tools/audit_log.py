from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from eqquest.parser import EQLogParser


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit an EverQuest log against EverQuestie's parser.")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()

    eq = EQLogParser()
    counts: Counter[str] = Counter()
    other: list[str] = []

    with args.log.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            event = eq.parse(raw.rstrip("\r\n"))
            kind = event.kind if event else "OTHER"
            counts[kind] += 1
            if kind == "OTHER":
                other.append(raw.rstrip("\r\n"))

    for kind, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{kind}: {count}")

    if other:
        print("\nOTHER samples:")
        for line in other[:50]:
            print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
