"""Merge original comparison operand observations across the baseline test suite."""

import collections
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys


def build(tree, scratch, dependency_index, output):
    git = ["git", "-C", str(tree)]
    assert (
        subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
        == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    )
    assert not subprocess.check_output(git + ["status", "--porcelain"])
    scratch.mkdir(exist_ok=False)
    tool = Path(__file__).resolve().with_name("attributes")
    env = {
        **os.environ,
        "BLAST_PROFILE": "operands",
        "BLAST_SOURCE": str(tree),
        "BLAST_ATTR_SCRATCH": str(scratch),
        "PYTHONPATH": os.pathsep.join([str(tool), str(tree)]),
        "SKIP_INTEGRATION": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    }
    subprocess.run(
        [sys.executable, str(tool / "collect.py")], env=env, cwd=tree, check=True
    )
    ids = json.loads(gzip.decompress(dependency_index.read_bytes()))["ids"]
    bits = {node: 1 << i for i, node in enumerate(ids)}
    groups = collections.defaultdict(dict)
    for path in sorted(scratch.glob("operands-*.json")):
        for site, entries in json.loads(path.read_bytes()).items():
            if not site.startswith("sqlglot/"):
                continue
            for pair, nodes in entries:
                key = json.dumps(pair, separators=(",", ":"))
                mask = groups[site].get(key, 0)
                for node in nodes:
                    mask |= bits.get(node, 0)
                groups[site][key] = mask
    packed = {
        site: [[json.loads(pair), hex(mask)] for pair, mask in sorted(group.items())]
        for site, group in sorted(groups.items())
        if any(k != "null" for k in group)
    }
    output.write_bytes(
        gzip.compress(json.dumps(packed, separators=(",", ":")).encode(), mtime=0)
    )
    print(f"Stored original operand observations at {len(packed)} comparison sites")


if __name__ == "__main__":
    build(*(Path(arg).resolve() for arg in sys.argv[1:]))
