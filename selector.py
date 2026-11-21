"""Select regression tests from the clean checkout's observed dependencies."""
import gzip
import json
import re
from pathlib import Path

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
                current["old" if line.startswith("---") else "new"] = name[2:] if name.startswith(("a/", "b/")) else name
            elif line.startswith(("rename from ", "rename to ")):
                old = line.startswith("rename from ")
                current["old" if old else "new"] = line[len("rename from " if old else "rename to "):]
    return files


class Index:
    def __init__(self, tests):
        payload = json.loads(gzip.decompress(Path(__file__).with_name("dependencies.json.gz").read_bytes()))
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

    def select_file(self, change):
        old, new = change["old"], change["new"]
        selected = self.reads.get(old, 0) | self.reads.get(new, 0)
        if old in self.by_file:
            selected |= self.by_file[old]
        if old not in self.rows:
            if old in self.reads or new in self.reads:
                return selected
            return self.all
        rows = self.rows[old]
        if not change["hunks"] or new == "/dev/null":
            return self.all
        for start, count, body in change["hunks"]:
            for value in rows[max(0, start - 1):max(start, start + count - 1)]:
                selected |= self.masks[value]
        return selected

    def select(self, patch):
        changes = parse_patch(patch)
        mask = 0 if changes else self.all
        for change in changes:
            mask |= self.select_file(change)
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


def run(data):
    tests = json.loads((data / "tests.json").read_bytes())["tests"]
    durations = {t["number"]: round(t["seconds"] * 1000) for t in tests}
    index = Index(tests)
    for path in sorted((data / "commits").glob("*.patch")):
        workers = schedule(index.select(path.read_text(errors="replace")), durations)
        print(json.dumps({"commit": path.stem, "workers": workers}, separators=(",", ":")))


if __name__ == "__main__":
    run(Path("/data"))
