"""Identify isolated edits to plain function bodies and immutable defaults."""

import ast


def ordinary(node):
    """Code inspected by decorators, class hooks and generator protocols stays broad."""
    if node.decorator_list or node.name.startswith("__"):
        return False
    return not any(
        isinstance(
            item, (ast.Yield, ast.YieldFrom, ast.Await, ast.Global, ast.Nonlocal)
        )
        for item in ast.walk(node)
    )


def methods(tree):
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield item
        elif isinstance(item, ast.ClassDef):
            yield from methods(item)


def signature_changes(before, after):
    left, right = list(methods(before)), list(methods(after))
    if len(left) != len(right):
        return []
    spans = []
    for original, changed in zip(left, right):
        a, b = original.args, changed.args
        defaults = [*a.defaults, *a.kw_defaults]
        replacements = [*b.defaults, *b.kw_defaults]
        if len(defaults) != len(replacements):
            return []
        touched = False
        for old, new in zip(defaults, replacements):
            if old is None or new is None:
                if old is not new:
                    return []
                continue
            if ast.dump(old) == ast.dump(new):
                continue
            if not (
                ordinary(original)
                and ordinary(changed)
                and isinstance(old, ast.Constant)
                and isinstance(new, ast.Constant)
                and type(old.value) is type(new.value)
                and type(old.value) in (int, float, bool, str, bytes)
            ):
                return []
            old.value = new.value
            touched = True
        if touched:
            spans.append(
                (
                    original.body[0].lineno,
                    original.end_lineno,
                    original.lineno,
                    original.name,
                )
            )
    return spans if spans and ast.dump(before) == ast.dump(after) else []


def same_without_pass(before, after):
    """A standalone pass only changes source and location metadata in a plain body."""

    class IgnorePass(ast.NodeTransformer):
        def visit_Pass(self, node):
            return None

    for tree in (before, after):
        for node in methods(tree):
            if ordinary(node):
                for statement in node.body:
                    if any(
                        isinstance(
                            child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                        )
                        for child in ast.walk(statement)
                    ):
                        break
                else:
                    node.body = [s for s in node.body if not isinstance(s, ast.Pass)]
                    for statement in node.body:
                        IgnorePass().visit(statement)
    return ast.dump(before) == ast.dump(after)


def execution_anchors(before, after, before_tree, after_tree):
    """Find the old entry statement for edits at the same point in a statement list."""
    anchors = []
    simple = (ast.Return, ast.Raise, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr)

    def same(a, b):
        if isinstance(a, ast.AST) and isinstance(b, ast.AST):
            return ast.dump(a) == ast.dump(b)
        return a == b

    def visit(a, b):
        if same(a, b):
            return True
        if isinstance(a, list) and isinstance(b, list):
            start = 0
            while start < min(len(a), len(b)) and same(a[start], b[start]):
                start += 1
            end_a, end_b = len(a), len(b)
            while end_a > start and end_b > start and same(a[end_a - 1], b[end_b - 1]):
                end_a -= 1
                end_b -= 1
            left, right = a[start:end_a], b[start:end_b]
            if len(left) == len(right) == 1 and type(left[0]) is type(right[0]):
                return visit(left[0], right[0])
            if start < len(a) and len(left) <= 1 and isinstance(a[start], simple):
                if not all(isinstance(n, ast.stmt) for n in [*left, *right]):
                    return False
                anchor = a[start]
                if isinstance(anchor, ast.Expr) and not isinstance(
                    anchor.value, ast.Call
                ):
                    return False
                anchors.append((anchor.lineno, anchor.end_lineno))
                return True
            return False
        if type(a) is not type(b) or not isinstance(a, ast.AST):
            return False
        return all(visit(getattr(a, f), getattr(b, f)) for f in a._fields)

    if not visit(before_tree, after_tree) or not anchors:
        return []
    from types import CodeType

    def lexical_shape(code):
        children = [
            lexical_shape(item) for item in code.co_consts if isinstance(item, CodeType)
        ]
        return (
            code.co_name,
            code.co_flags,
            code.co_varnames,
            code.co_cellvars,
            code.co_freevars,
            code.co_argcount,
            code.co_kwonlyargcount,
            children,
        )

    a = compile(before, "<source>", "exec", dont_inherit=True)
    b = compile(after, "<source>", "exec", dont_inherit=True)
    return anchors if lexical_shape(a) == lexical_shape(b) else []
