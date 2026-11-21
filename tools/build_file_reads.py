"""Run each test file in a fresh process, including its imports and pool workers."""
import collections
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

def build(tree,scratch,dependency_index,output):
    git = ["git","-C",str(tree)]
    assert subprocess.check_output(git+["rev-parse","HEAD"],text=True).strip() == "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
    assert not subprocess.check_output(git+["status","--porcelain"])
    scratch.mkdir(exist_ok=False)
    ids = json.loads(gzip.decompress(dependency_index.read_bytes()))["ids"]
    per_file = collections.defaultdict(int)
    for i,node in enumerate(ids):
        per_file[node.split("::")[0]] |= 1 << i
    hooks = Path(__file__).resolve().with_name("file_reads")
    def run(name):
        dest = scratch / name.replace("/","_")
        dest.mkdir()
        env = {**os.environ,"BLAST_SOURCE":str(tree),"BLAST_READ_LOG":str(dest),
               "PYTHONPATH":os.pathsep.join([str(hooks),str(tree)]),"SKIP_INTEGRATION":"0",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1","PYTHONDONTWRITEBYTECODE":"1",
               "PATH":str(Path(sys.executable).parent)+os.pathsep+os.environ["PATH"]}
        with (dest/"pytest.log").open("w") as log:
            proc = subprocess.run([sys.executable,"-m","pytest",name,"-p","pytest_timeout","--timeout=160",
                                   "-q","-p","no:cacheprovider","--tb=short"],cwd=tree,env=env,
                                  stdout=log,stderr=subprocess.STDOUT)
        if proc.returncode:
            raise RuntimeError(f"{name}: pytest exited with {proc.returncode}")
        reads, dirs = set(),set()
        for log in dest.glob("*.json"):
            seen,listed = json.loads(log.read_bytes())
            reads.update(seen)
            dirs.update(listed)
        assert name in reads, name
        return name, reads, dirs
    files, directories = collections.defaultdict(int),collections.defaultdict(int)
    with ThreadPoolExecutor(max_workers=2) as executor:
        for name,observed,listed in executor.map(run,sorted(per_file)):
            for path in observed:
                files[path] |= per_file[name]
            for path in listed:
                directories[path] |= per_file[name]
    packed = [{path:hex(mask) for path,mask in sorted(table.items())} for table in (files,directories)]
    output.write_bytes(gzip.compress(json.dumps(packed,separators=(",",":")).encode(),mtime=0))
    print(f"{len(per_file)} fresh test-file groups, {len(files)} files read, {len(directories)} directories listed")

if __name__ == "__main__":
    build(*(Path(v).resolve() for v in sys.argv[1:]))
