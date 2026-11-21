"""Locate changed deferred code, class members and executable expressions."""

import ast


def classify_members(before, after, path):
    """Return class assignment sites whose changed literals keep their type and dictionary keys."""
    members = []
    module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")

    def visit(left, right, owner=None, member=None, immutable_key=False):
        if type(left) is not type(right):
            return False
        if isinstance(left, list):
            return len(left) == len(right) and all(
                visit(a, b, owner, member, immutable_key) for a, b in zip(left, right)
            )
        if isinstance(left, ast.Constant):
            if repr(left.value) == repr(right.value) and left.kind == right.kind:
                return True
            if (
                member is None
                or immutable_key
                or type(left.value) is not type(right.value)
            ):
                return False
            members.append(member)
            return True
        if not isinstance(left, ast.AST):
            return left == right
        for name, value in ast.iter_fields(left):
            subowner = owner
            submember = member
            protected = immutable_key
            if isinstance(left, ast.ClassDef):
                subowner = (
                    (owner or module) + "." + left.name if name == "body" else None
                )
                submember = None
            elif isinstance(left, (ast.FunctionDef, ast.AsyncFunctionDef)):
                subowner = None
                submember = None
            elif (
                isinstance(left, (ast.Assign, ast.AnnAssign))
                and name == "value"
                and owner
            ):
                targets = (
                    left.targets if isinstance(left, ast.Assign) else [left.target]
                )
                if len(targets) == 1 and isinstance(targets[0], ast.Name):
                    submember = (owner, targets[0].id, left.lineno, left.end_lineno)
            elif isinstance(left, ast.Dict) and name == "keys":
                protected = True
            if not visit(value, getattr(right, name), subowner, submember, protected):
                return False
        return True

    if visit(before, after):
        return sorted(set(members))
    return []


def deferred(before, after):
    """Find edits confined to lambda bodies whose creation and argument lists stay unchanged."""
    changed = []

    def same_bindings(a, b):
        if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
            return True
        if isinstance(a, (ast.cmpop, ast.boolop)) and isinstance(
            b, (ast.cmpop, ast.boolop)
        ):
            return True
        if type(a) != type(b):
            return False
        if isinstance(a, list):
            return len(a) == len(b) and all(same_bindings(x, y) for x, y in zip(a, b))
        if isinstance(a, ast.AST):
            return all(same_bindings(getattr(a, k), getattr(b, k)) for k in a._fields)
        return a == b

    def visit(left, right):
        if type(left) != type(right):
            return False
        if isinstance(left, list):
            return len(left) == len(right) and all(
                visit(a, b) for a, b in zip(left, right)
            )
        if not isinstance(left, ast.AST):
            return left == right
        if isinstance(left, ast.Lambda):
            if ast.dump(left.args) != ast.dump(right.args):
                return False
            if ast.dump(left.body) != ast.dump(right.body):
                if not same_bindings(left.body, right.body):
                    return False
                changed.append((left.lineno, left.end_lineno))
            return True
        return all(visit(getattr(left, k), getattr(right, k)) for k in left._fields)

    return changed if visit(before, after) else []


def executable(before, after):
    """Locate changes confined to previously existing expression evaluation sites."""
    regions = []
    safe_fields = {
        ast.Return: {"value"},
        ast.If: {"test"},
        ast.While: {"test"},
        ast.Assert: {"test", "msg"},
        ast.Expr: {"value"},
        ast.Assign: {"value"},
        ast.AnnAssign: {"value"},
        ast.AugAssign: {"value"},
        ast.For: {"iter"},
        ast.Raise: {"exc", "cause"},
    }
    special = (
        ast.NamedExpr,
        ast.Lambda,
        ast.Yield,
        ast.YieldFrom,
        ast.Await,
        ast.GeneratorExp,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
    )

    def visit(left, right, active=False):
        if type(left) != type(right):
            return False
        if isinstance(left, list):
            return len(left) == len(right) and all(
                visit(a, b, active) for a, b in zip(left, right)
            )
        if not isinstance(left, ast.AST):
            return left == right
        fields = safe_fields.get(type(left), ())
        for key, x in ast.iter_fields(left):
            y = getattr(right, key)
            if (
                active
                and key in fields
                and isinstance(x, ast.expr)
                and isinstance(y, ast.expr)
            ):
                if ast.dump(x) != ast.dump(y):
                    if any(isinstance(n, special) for z in (x, y) for n in ast.walk(z)):
                        return False
                    regions.append((left.lineno, x.end_lineno))
            else:
                inner = active
                if isinstance(left, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner = key == "body"
                elif isinstance(left, ast.ClassDef):
                    inner = False
                if not visit(x, y, inner):
                    return False
        return True

    return sorted(set(regions)) if visit(before, after) else []
