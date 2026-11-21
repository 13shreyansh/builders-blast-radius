"""Select regression tests from the clean checkout's observed dependencies."""

import gzip
import json
import re
from pathlib import Path

from import_guard import Imports
from scope import Source, rebuild
from dependencies import Isolated

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def parse_patch(text):
    """Keep both sides of a rename, and retain the original line coordinates."""
    files = []
    current = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = {"old": "", "new": "", "hunks": []}
            files.append(current)
        elif current is not None:
            hunk = HUNK.match(line)
            if hunk:
                current["hunks"].append((int(hunk[1]), int(hunk[2] or "1"), []))
            elif current["hunks"]:
                if line.startswith((" ", "+", "-")):
                    current["hunks"][-1][2].append(line)
            elif line.startswith(("--- ", "+++ ")):
                name = line[4:].split("\t", 1)[0]
                current["old" if line.startswith("---") else "new"] = (
                    name[2:] if name.startswith(("a/", "b/")) else name
                )
            elif line.startswith(("rename from ", "rename to ")):
                old = line.startswith("rename from ")
                current["old" if old else "new"] = line[
                    len("rename from " if old else "rename to ") :
                ]
    return files


class Index:
    def __init__(self, tests):
        payload = json.loads(
            gzip.decompress(
                Path(__file__).with_name("dependencies.json.gz").read_bytes()
            )
        )
        base = Path(__file__).parent
        raw, _ = json.loads(gzip.decompress((base / "file_reads.json.gz").read_bytes()))
        self.file_reads = {k: int(v, 16) for k, v in raw.items()}
        self.imported = json.loads(
            gzip.decompress((base / "import_lines.json.gz").read_bytes())
        )
        self.shared = json.loads(
            gzip.decompress((base / "shared.json.gz").read_bytes())
        )
        self.isolated = Isolated(base)
        self.imports = Imports()
        self.source = Source()
        self.observers = int((base / "observers.txt").read_text(), 16)
        item_data = json.loads(
            gzip.decompress((base / "item_profiles.json.gz").read_bytes())
        )
        self.item_reads = {k: int(v, 16) for k, v in item_data[0].items()}
        self.incomplete = self.isolated.incomplete | sum(1 << i for i in item_data[2])
        self.calls = {
            p: {(line, name): int(mask, 16) for line, name, mask in rows}
            for p, rows in item_data[3].items()
        }
        metadata, startup = json.loads(
            gzip.decompress((base / "source_observers.json.gz").read_bytes())
        )
        self.metadata_startup = set(startup)
        self.metadata = {path: int(mask, 16) for path, mask in metadata.items()}
        traced = 0
        for mask in self.metadata.values():
            traced |= mask
        self.unresolved_metadata = self.observers & (
            ~traced | self.metadata.get("*", 0)
        )
        self.ids = payload["ids"]
        self.rows = payload["lines"]
        self.masks = [int(mask, 16) for mask in payload["masks"]]
        self.reads = {path: self.masks[i] for path, i in payload["fixtures"].items()}
        positions = {node: i for i, node in enumerate(self.ids)}
        self.by_file = {}
        self.by_number = {}
        self.unmeasured = []
        for test in tests:
            node = test["id"]
            if node not in positions:
                self.unmeasured.append(test["number"])
                continue
            i = positions[node]
            self.by_number[i] = test["number"]
            path = test["file"]
            self.by_file[path] = self.by_file.get(path, 0) | (1 << i)
        self.all = (1 << len(self.ids)) - 1

    def file_group(self, path):
        mask = (
            self.file_reads.get(path, 0)
            | self.reads.get(path, 0)
            | self.by_file.get(path, 0)
        )
        for i in set(self.rows.get(path, ())):
            mask |= self.masks[i]
        return mask or self.all

    def select_file(
        self, change, compound_python=False, classified=None, together=None
    ):
        old, new = change["old"], change["new"]
        if old != new or not change["hunks"]:
            return self.all
        wide = self.file_group(old)
        if not old.endswith(".py"):
            cold = self.item_reads.get(old, 0)
            if not cold:
                return wide
            direct = cold | self.reads.get(old, 0)
            grouped = self.file_reads.get(old, 0)
            for module_mask in self.by_file.values():
                if module_mask & grouped and not module_mask & direct:
                    direct |= module_mask
            return direct | self.incomplete
        try:
            mode, spans = classified or self.source.classify(change)
        except RecursionError:
            # Valid diffs can exceed the recursion limit in Python's compiler or AST visitor.
            return self.all
        if mode in ("invalid", "unknown", "structural"):
            return self.all
        if mode == "members":
            metadata = self.observers
        else:
            metadata = self.unresolved_metadata | (
                self.observers & self.metadata.get(old, 0)
            )
        if mode == "defaults":
            if old in self.metadata_startup:
                return self.all
            metadata |= self.metadata.get(old, 0) | self.metadata.get("*", 0)
        selected = (
            self.reads.get(old, 0)
            | self.by_file.get(old, 0)
            | metadata
            | self.incomplete
        )
        if mode == "members":
            if compound_python and not together:
                # Mixed executable changes retain the full import fallback.
                return self.all
            affected, receivers, modules = self.isolated.class_members(old, spans, wide)
            members = selected | affected
            for module in modules:
                members |= self.file_group(module)
                receivers.add(
                    module.removesuffix(".py")
                    .replace("/", ".")
                    .removesuffix(".__init__")
                )
            if members == self.all:
                return members
            original, _ = self.source.original(old)
            patched = rebuild(original, change["hunks"])
            if patched is None or not self.imports.check(
                old, patched, receivers, self.source.names, together
            ):
                return self.all
            return members
        if mode == "deferred":
            seen = 0
            for line, end in spans:
                callers = self.calls.get(old, {}).get((line, "<lambda>"), 0)
                if not callers:
                    callers = self.isolated.span(old, line, end)
                seen |= callers
            return selected | (seen or wide)
        if mode == "class-value":
            return self.all
        if mode == "control":
            return wide | selected
        if mode == "trivia":
            return selected
        rows = self.rows.get(old, ())
        early = self.imported.get(old, ())
        if not rows:
            return wide | selected
        stable = 0
        expressions = []
        if mode in ("expressions", "anchors"):
            spans, expressions, stable = spans
        for lo, hi, first, name in spans:
            cold = self.calls.get(old, {}).get((first, name), 0)
            early_body = any(lo <= line <= hi for line in early)
            if mode in ("defaults", "anchors"):
                shared = any(lo <= line <= hi for line in self.shared.get(old, ()))
                if early_body or shared or compound_python:
                    return self.all if mode == "defaults" else wide | selected
            if early_body and not expressions:
                init_calls = self.isolated.span(old, lo, hi) | cold
                selected |= init_calls or wide
                continue
            seen = 0
            for i in set(rows[lo - 1 : hi]):
                seen |= self.masks[i]
            if not (seen | cold):
                return wide | selected
            if not expressions:
                selected |= seen | cold
                continue
            exact = 0
            for start, end in expressions:
                if not (lo <= start <= end <= hi):
                    continue
                exact |= self.isolated.span(old, start, end)
                for i in set(rows[start - 1 : end]):
                    exact |= self.masks[i]
            can_prune = (
                stable
                if not early_body
                and not any(lo <= line <= hi for line in self.shared.get(old, ()))
                else 0
            )
            selected |= (exact or seen or cold) & ~can_prune
        return selected

    def nearby(self, patch):
        related = 0
        for change in parse_patch(patch):
            related |= self.file_group(change["old"])
        return {
            number
            for position, number in self.by_number.items()
            if (related >> position) & 1
        }

    def select(self, patch):
        changes = parse_patch(patch)
        mask = 0 if changes else self.all
        python = [c for c in changes if c["old"].endswith(".py")]
        classifications = {}
        together = None
        active = python
        if len(python) > 1:
            try:
                classifications = {id(c): self.source.classify(c) for c in python}
            except RecursionError:
                mask = self.all
            if classifications:
                active = [c for c in python if classifications[id(c)][0] != "trivia"]
                if (
                    1 < len(active) <= 3
                    and len({c["old"] for c in active}) == len(active)
                    and all(classifications[id(c)][0] == "members" for c in active)
                ):
                    together = {}
                    overlap = self.all
                    for change in active:
                        path = change["old"]
                        source = rebuild(self.source.original(path)[0], change["hunks"])
                        if source is None:
                            return list(self.by_number.values()) + self.unmeasured
                        together[path] = source
                        overlap &= self.file_group(path)
                    mask |= overlap
        for change in changes:
            mask |= self.select_file(
                change, len(active) > 1, classifications.get(id(change)), together
            )
        selected = self.unmeasured.copy()
        while mask:
            lowest = mask & -mask
            number = self.by_number.get(lowest.bit_length() - 1)
            if number is not None:
                selected.append(number)
            mask ^= lowest
        return selected


def schedule(numbers, durations, fixed=None):
    ordered = sorted(numbers, key=lambda n: (-durations[n], n))
    if not ordered:
        return []
    total = sum(durations[n] for n in ordered)
    longest = durations[ordered[0]]
    best_cost = None
    best = []
    counts = [min(fixed, len(numbers))] if fixed else range(1, min(8, len(numbers)) + 1)
    for count in counts:
        floor = max(longest, (total + count - 1) // count) + 2000 * count
        if best_cost is not None and floor >= best_cost:
            continue
        loads = [0] * count
        workers = [[] for _ in loads]
        for n in ordered:
            i = loads.index(min(loads))
            workers[i].append(n)
            loads[i] += durations[n]
        cost = max(loads) + 2000 * sum(bool(w) for w in workers)
        if best_cost is None or cost < best_cost:
            best_cost, best = cost, workers
    return [w for w in best if w]


def fill_slack(workers, durations, names, nearby):
    if not workers:
        return
    loads = [sum(durations[n] for n in group) for group in workers]
    deadline = max(loads)
    if min(loads) == deadline:
        return
    waiting = set(durations).difference(n for group in workers for n in group)
    order = sorted(waiting, key=lambda n: (n not in nearby, -durations[n], names[n]))
    worker = loads.index(min(loads))
    for n in order:
        if loads[worker] + durations[n] <= deadline:
            workers[worker].append(n)
            loads[worker] += durations[n]
            worker = loads.index(min(loads))
            if loads[worker] == deadline:
                break


def run(data):
    tests = json.loads((data / "tests.json").read_bytes())["tests"]
    durations = {t["number"]: round(t["seconds"] * 1000) for t in tests}
    names = {t["number"]: t["id"] for t in tests}
    index = Index(tests)
    for path in sorted((data / "commits").glob("*.patch")):
        patch = path.read_text(errors="replace")
        workers = schedule(index.select(patch), durations)
        if len(workers) > 1 and sum(map(len, workers)) < len(tests):
            fill_slack(workers, durations, names, index.nearby(patch))
        print(
            json.dumps({"commit": path.stem, "workers": workers}, separators=(",", ":"))
        )


if __name__ == "__main__":
    run(Path("/data"))
