"""Measure isolated line coverage and constructor dependencies on the pinned base tree."""

import collections
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def collect(tree, scratch, index, output):
    args = ["git", "-C", str(tree)]
    assert (
        subprocess.check_output(args + ["rev-parse", "HEAD"], text=True).strip() == PIN
    )
    assert not subprocess.check_output(args + ["status", "--porcelain"])
    observe_verified_checkout(tree, scratch, index, output)


def observe_verified_checkout(tree, scratch, index, output, workers=4):
    scratch.mkdir(exist_ok=False)
    ids = json.loads(gzip.decompress(index.read_bytes()))["ids"]
    hooks = Path(__file__).resolve().with_name("cold_lines")
    environment = {
        **os.environ,
        "BLAST_SOURCE": str(tree),
        "PYTHONPATH": os.pathsep.join([str(hooks), str(tree)]),
        "SKIP_INTEGRATION": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
    }

    def run(item):
        number, node = item
        dest = scratch / str(number)
        dest.mkdir()
        with (dest / "pytest.log").open("w") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    node,
                    "-q",
                    "-p",
                    "pytest_timeout",
                    "--timeout=240",
                    "-p",
                    "no:cacheprovider",
                    "--tb=short",
                ],
                cwd=tree,
                env={**environment, "BLAST_LINE_DIR": str(dest)},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        coverage = collections.defaultdict(int)
        classes = set()
        for path in dest.glob("*.json"):
            paths, names = json.loads(path.read_bytes())
            classes.update(names)
            for name, packed in paths.items():
                coverage[name] |= int.from_bytes(bytes.fromhex(packed), "little")
        return number, coverage, classes, result.returncode

    unique = collections.defaultdict(dict)
    classes = collections.defaultdict(int)
    incomplete = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for n, paths, names, code in executor.map(run, enumerate(ids)):
            bit = 1 << n
            if code or ids[n].partition("::")[0] not in paths:
                incomplete.append(n)
            for name, lines in paths.items():
                unique[name][lines] = unique[name].get(lines, 0) | bit
            for name in names:
                classes[name] |= bit
            if (n + 1) % 100 == 0:
                print(n + 1, "fresh items;", len(incomplete), "incomplete", flush=True)
    pool = {0: 0}
    rows = {}
    for name, groups in sorted(unique.items()):
        result = [0] * max((bits.bit_length() for bits in groups), default=0)
        for bits, mask in groups.items():
            while bits:
                low = bits & -bits
                result[low.bit_length() - 1] |= mask
                bits ^= low
        rows[name] = [pool.setdefault(v, len(pool)) for v in result]
    output.write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "lines": rows,
                    "masks": [hex(m) for m in pool],
                    "classes": {k: hex(v) for k, v in sorted(classes.items())},
                    "incomplete": incomplete,
                },
                separators=(",", ":"),
            ).encode(),
            mtime=0,
        )
    )
    print(
        len(ids),
        "items",
        len(rows),
        "files",
        len(classes),
        "classes",
        len(incomplete),
        "incomplete",
        flush=True,
    )


if __name__ == "__main__":
    collect(*(Path(arg).resolve() for arg in sys.argv[1:]))
