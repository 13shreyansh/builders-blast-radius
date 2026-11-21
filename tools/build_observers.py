"""Find clean test contexts that inspect source positions or code objects."""
import ast
import gzip
import json
from pathlib import Path
import sys

ATTRIBUTES = {"__code__","__doc__","co_code","co_consts","co_firstlineno","co_lines","co_positions",
              "co_linetable","tb_lineno","f_lineno","getsource","getsourcelines","getdoc","getframeinfo"}

def build(tree,index,output):
    data=json.loads(gzip.decompress(index.read_bytes()))
    masks=[int(m,16) for m in data["masks"]]
    observer=0
    for name,rows in data["lines"].items():
        for node in ast.walk(ast.parse((tree/name).read_bytes())):
            if isinstance(node,ast.Attribute) and node.attr in ATTRIBUTES or isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in ATTRIBUTES:
                if 0<node.lineno<=len(rows):
                    observer |= masks[rows[node.lineno-1]]
    output.write_text(hex(observer)+"\n")
    print(observer.bit_count(),"source/position observers")
if __name__=="__main__":
    build(*(Path(arg).resolve() for arg in sys.argv[1:]))
