"""Reconstruct changed source and distinguish function-body edits from structural edits."""
import ast
import io
import re
import tokenize
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

CODING = re.compile(r"coding[=:]\s*[-.\w]+")


def rebuild(source, hunks):
    original = source.splitlines(keepends=True)
    result = []
    previous = 0
    for start, count, body in hunks:
        offset = start - 1 if count else start
        if offset < previous or offset > len(original):
            return None
        result.extend(original[previous:offset])
        pos = offset
        for line in body:
            char, value = line[0], line[1:]
            if char != "+":
                if pos >= len(original) or original[pos].rstrip("\r\n") != value:
                    return None
                pos += 1
            if char != "-":
                result.append(value + "\n")
        if pos != offset + count:
            return None
        previous = pos
    return "".join(result + original[previous:])


class Functions(ast.NodeTransformer):
    def __init__(self,source):
        self.lines = source.splitlines(keepends=True)
        self.bodies = []

    def visit_FunctionDef(self,node):
        lo = node.body[0].lineno
        hi = node.end_lineno
        body_text = "".join(self.lines[lo-1:hi])
        # Accessing a function's docstring has no enclosing call context.
        self.bodies.append((lo,hi,body_text,ast.get_docstring(node,clean=False)))
        node.body = [ast.Pass()]
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


def structure(source):
    tree = ast.parse(source)
    visitor = Functions(source)
    skeleton = ast.dump(visitor.visit(tree))
    return skeleton, visitor.bodies


def tokens(source):
    ignored = {tokenize.COMMENT,tokenize.NL,tokenize.ENDMARKER}
    return [(t.type,t.string) for t in tokenize.generate_tokens(io.StringIO(source).readline) if t.type not in ignored]


class Source:
    def __init__(self):
        self.archive = ZipFile(Path(__file__).with_name("source.zip"))
        self.names = set(self.archive.namelist())

    @lru_cache(maxsize=24)
    def original(self,path):
        text = self.archive.read(path).decode()
        return text, structure(text)

    def classify(self,change):
        path = change["old"]
        if path not in self.names or path != change["new"] or not change["hunks"]:
            return "unknown", []
        before, old = self.original(path)
        after = rebuild(before,change["hunks"])
        if after is None:
            return "unknown", []
        try:
            compile(after,path,"exec",dont_inherit=True)
        except (SyntaxError,ValueError,OverflowError):
            return "invalid", []
        if CODING.findall("".join(before.splitlines(keepends=True)[:2])) != CODING.findall("".join(after.splitlines(keepends=True)[:2])):
            return "unknown", []
        edits = [line[1:] for _,_,body in change["hunks"] for line in body if line[0] in "+-"]
        if edits and all(not s.strip() or s.lstrip().startswith("#") for s in edits) and tokens(before)==tokens(after):
            return "trivia", []
        new = structure(after)
        if old[0] != new[0] or len(old[1]) != len(new[1]):
            return "structural", []
        spans = []
        for a,b in zip(old[1],new[1]):
            if a[3] != b[3]:
                return "structural", []
            if a[2] != b[2]:
                spans.append(a[:2])
        return ("bodies",spans) if spans else ("structural",[])
