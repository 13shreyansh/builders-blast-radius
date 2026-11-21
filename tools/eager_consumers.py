"""Observe destinations of eager member reads while importing the pristine package."""

from collections import defaultdict
from pathlib import Path
import sys


class Consumers:
    def __init__(self, tree, members):
        self.tree = tree
        self.assignments = {}
        self.class_lines = {}
        self.cache = {}
        self.fields = defaultdict(set)
        self.classes = defaultdict(set)
        self.modules = defaultdict(set)
        for name, (path, first, last, *_) in members.items():
            owner = name.rpartition(".")[0]
            if last - first > 4000:
                continue
            for line in range(first, last + 1):
                self.assignments[path, owner, line] = name

    def locate(self, frame):
        # Class-body frames identify copies even when the receiver belongs to another class.
        while frame is not None:
            code = frame.f_code
            path = self.cache.get(code.co_filename)
            if path is None:
                filename = Path(code.co_filename)
                path = (
                    filename.relative_to(self.tree).as_posix()
                    if filename.is_relative_to(self.tree)
                    else ""
                )
                self.cache[code.co_filename] = path
            if path.startswith("sqlglot/"):
                namespace = frame.f_locals
                if "__qualname__" in namespace and "__module__" in namespace:
                    owner = (
                        str(namespace["__module__"])
                        + "."
                        + str(namespace["__qualname__"])
                    )
                    assignment = self.assignments.get((path, owner, frame.f_lineno))
                    return ("field", assignment) if assignment else ("class", owner)
                if code.co_name == "<module>":
                    # A class statement invokes its metaclass after executing the body.
                    owner = self.class_lines.get((path, frame.f_lineno))
                    return ("class", owner) if owner else ("module", path)
            frame = frame.f_back
        return None

    def install(self, hook):
        from ast import ClassDef, parse

        for path in (self.tree / "sqlglot").rglob("*.py"):
            relative = path.relative_to(self.tree).as_posix()
            module = (
                relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            )

            def index(body, prefix):
                for statement in body:
                    if isinstance(statement, ClassDef):
                        name = prefix + "." + statement.name
                        self.class_lines[relative, statement.lineno] = name
                        index(statement.body, name)

            index(parse(path.read_bytes()).body, module)
        original = hook.observe

        def observe(obj, name):
            original(obj, name)
            if not isinstance(name, str):
                return
            cls = obj if isinstance(obj, type) else type(obj)
            source = hook.resolved.get((cls, name))
            if not source:
                return
            # The same reader code can run under different module/class initializers.
            frame = sys._getframe(2)
            destination = self.locate(frame)
            if destination is None:
                return
            kind, target = destination
            table = {
                "field": self.fields,
                "class": self.classes,
                "module": self.modules,
            }[kind]
            table[source].add(target)

        hook.observe = observe
