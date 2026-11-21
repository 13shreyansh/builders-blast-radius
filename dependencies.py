"""Look up clean isolated execution by line, class construction and observed member access."""

import gzip
import json


class Isolated:
    def __init__(self, folder):
        raw = json.loads(gzip.decompress((folder / "cold_lines.json.gz").read_bytes()))
        self.lines = raw["lines"]
        self.masks = [int(m, 16) for m in raw["masks"]]
        self.classes = {k: int(v, 16) for k, v in raw["classes"].items()}
        warm_types = json.loads(
            gzip.decompress((folder / "types.json.gz").read_bytes())
        )
        for cls, tests in warm_types.items():
            self.classes[cls] = self.classes.get(cls, 0) | int(tests, 16)
        self.incomplete = sum(1 << n for n in raw["incomplete"])
        usage = json.loads(
            gzip.decompress((folder / "class_usage.json.gz").read_bytes())
        )
        self.members = {
            k: (path, lo, hi, int(mask, 16), startup)
            for k, (path, lo, hi, mask, startup) in usage.items()
        }

        self.eager, self.aliases, self.consumers, self.modules = json.loads(
            gzip.decompress((folder / "initialization.json.gz").read_bytes())
        )
        observers, early = json.loads(
            gzip.decompress((folder / "namespaces.json.gz").read_bytes())
        )
        self.namespace_readers = {k: int(v, 16) for k, v in observers.items()}
        self.early_namespaces = set(early)

    def span(self, path, first, last):
        rows = self.lines.get(path, ())
        result = 0
        for i in set(rows[first : last + 1]):
            result |= self.masks[i]
        return result

    def class_members(self, path, assignments, fallback):
        pending = []
        receivers = set()
        modules = set()
        for owner, name, start, end in assignments:
            field = owner + "." + name
            row = self.members.get(field)
            if row is None or row[:3] != (path, start, end):
                return fallback, receivers, modules
            pending.append(field)

        mask = 0
        visited = set()
        unknown = False
        while pending:
            field = pending.pop()
            if field in visited:
                continue
            visited.add(field)
            row = self.members.get(field)
            if row is None:
                unknown = True
                continue
            owner, _, name = field.rpartition(".")
            readers, warm_startup = row[3:]
            startup = set(warm_startup).union(self.eager.get(field, ()))
            startup.update(self.consumers.get(field, ()))
            receivers.update(startup)
            modules.update(self.modules.get(field, ()))
            mask |= readers | self.namespace_readers.get(owner, 0)
            if not readers:
                unknown = True
            if startup or owner in self.early_namespaces or name.startswith("_"):
                mask |= self.classes.get(owner, 0)
            for receiver in startup:
                consumers = self.classes.get(receiver, 0)
                if not consumers:
                    unknown = True
                mask |= consumers
            pending.extend(self.aliases.get(field, ()))
        return (fallback if unknown else mask), receivers, modules
