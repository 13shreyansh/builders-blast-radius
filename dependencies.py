"""Look up clean isolated execution by line and class initialization dependencies."""

import gzip
import json


class Isolated:
    def __init__(self, folder):
        raw = json.loads(gzip.decompress((folder / "cold_lines.json.gz").read_bytes()))
        self.lines = raw["lines"]
        self.masks = [int(m, 16) for m in raw["masks"]]
        self.incomplete = sum(1 << n for n in raw["incomplete"])
        usage = json.loads(
            gzip.decompress((folder / "class_usage.json.gz").read_bytes())
        )
        self.startup = {name: row[4] for name, row in usage.items() if row[4]}

    def span(self, path, first, last):
        rows = self.lines.get(path, ())
        result = 0
        for i in set(rows[first : last + 1]):
            result |= self.masks[i]
        return result
