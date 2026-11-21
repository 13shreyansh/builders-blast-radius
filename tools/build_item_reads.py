"""Measure file imports, opened fixtures and directory enumeration in fresh test processes."""
import collections
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys


def build(tree,scratch,dependency_index,output):
    if not hasattr(sys,"monitoring"):
        raise RuntimeError("Cold function tracing requires Python 3.12 or newer")
    git = ["git","-C",str(tree)]
    assert subprocess.check_output(git+["rev-parse","HEAD"],text=True).strip() == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    assert not subprocess.check_output(git+["status","--porcelain"])
    scratch.mkdir(exist_ok=False)
    ids = json.loads(gzip.decompress(dependency_index.read_bytes()))["ids"]
    hooks = Path(__file__).resolve().with_name("file_reads")
    env = {**os.environ,"BLAST_SOURCE":str(tree),"BLAST_CAPTURE_FUNCTIONS":"1","PYTHONPATH":os.pathsep.join([str(hooks),str(tree)]),
           "SKIP_INTEGRATION":"0","PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1","PYTHONDONTWRITEBYTECODE":"1",
           "PATH":str(Path(sys.executable).parent)+os.pathsep+os.environ["PATH"]}
    def run(item):
        i,name = item
        dest = scratch / str(i)
        dest.mkdir()
        with (dest/"pytest.log").open("w") as log:
            result = subprocess.run([sys.executable,"-m","pytest",name,"-p","pytest_timeout","--timeout=160",
                                     "-q","-p","no:cacheprovider","--tb=short"],cwd=tree,
                                    env={**env,"BLAST_READ_LOG":str(dest)},stdout=log,stderr=subprocess.STDOUT)
        reads, dirs, functions = set(),set(),set()
        for log in dest.glob("*.json"):
            seen,listed,called = json.loads(log.read_bytes())
            functions.update(tuple(row) for row in called)
            reads.update(seen)
            dirs.update(listed)
        return i,reads,dirs,functions,result.returncode
    files, directories = collections.defaultdict(int),collections.defaultdict(int)
    functions = collections.defaultdict(int)
    incomplete = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for i,observed,listed,called,code in executor.map(run,enumerate(ids)):
            if code or not called or ids[i].split("::")[0] not in observed:
                incomplete.append(i)
            for key in called:
                functions[key] |= 1<<i
            for path in observed:
                files[path] |= 1<<i
            for path in listed:
                directories[path] |= 1<<i
            if (i+1)%100==0:
                print(i+1,"items",len(incomplete),"incomplete",flush=True)
    payload=[{path:hex(mask) for path,mask in sorted(table.items())} for table in (files,directories)]
    # Unmeasured items are selected on every patch by the consumer.
    payload.append(incomplete)
    function_rows = collections.defaultdict(list)
    for (path,line,name),mask in sorted(functions.items()):
        function_rows[path].append([line,name,hex(mask)])
    payload.append(function_rows)
    output.write_bytes(gzip.compress(json.dumps(payload,separators=(",",":")).encode(),mtime=0))
    print(f"{len(ids)} fresh test processes, {len(files)} file paths, {len(incomplete)} incomplete",flush=True)

if __name__=="__main__":
    build(*(Path(v).resolve() for v in sys.argv[1:]))
