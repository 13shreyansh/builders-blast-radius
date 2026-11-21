"""Export lines executed before a pytest item was active in the clean collection run."""
import collections
import gzip
import json
from pathlib import Path
import sqlite3
import sys
from coverage.numbits import numbits_to_nums

def build(tree,scratch,output):
    paths = collections.defaultdict(set)
    for path in sorted(scratch.glob("coverage-*")):
        with sqlite3.connect(path) as db:
            query = """select file.path,numbits from line_bits join file on file_id=file.id
                       join context on context_id=context.id where context.context=''"""
            for filename,bits in db.execute(query):
                paths[Path(filename).relative_to(tree).as_posix()].update(numbits_to_nums(bits))
    payload = {k:sorted(v) for k,v in sorted(paths.items())}
    output.write_bytes(gzip.compress(json.dumps(payload,separators=(",",":")).encode(),mtime=0))
    print(f"{len(paths)} modules with executed lines outside item contexts")
if __name__=="__main__":
    build(*(Path(p).resolve() for p in sys.argv[1:]))
