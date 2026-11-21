"""Identify old executable spans for restricted in-place expression substitutions."""

import ast


def matching_spans(before, after):
    """Return old statement spans when only scalar literals or truth operators differ."""
    affected = set()

    def compare(left, right, statement=None, in_function=False):
        if isinstance(left, (ast.cmpop, ast.boolop)) and isinstance(
            right, (ast.cmpop, ast.boolop)
        ):
            if type(left) == type(right):
                return True
            if statement and in_function:
                affected.add(statement)
                return True
            return False
        if type(left) != type(right):
            return False
        if isinstance(left, list):
            return len(left) == len(right) and all(
                compare(a, b, statement, in_function) for a, b in zip(left, right)
            )
        if not isinstance(left, ast.AST):
            return left == right
        if isinstance(left, ast.Constant):
            if repr(left.value) == repr(right.value) and left.kind == right.kind:
                return True
            if (
                statement
                and in_function
                and isinstance(left.value, (bool, int, str, bytes, type(None)))
            ):
                affected.add(statement)
                return True
            return False
        if isinstance(
            left,
            (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp),
        ):
            return ast.dump(left) == ast.dump(right)
        for name, old in ast.iter_fields(left):
            region = statement
            active = in_function
            if isinstance(left, (ast.FunctionDef, ast.AsyncFunctionDef)):
                active = name == "body"
                region = None
            elif isinstance(left, ast.ClassDef):
                active = False
                region = None
            elif isinstance(left, ast.stmt):
                if isinstance(old, ast.expr):
                    region = (left.lineno, old.end_lineno)
                else:
                    region = None
            if not compare(old, getattr(right, name), region, active):
                return False
        return True

    if compare(ast.parse(before), ast.parse(after)):
        return sorted(affected)
    return []


def class_value_edit(before, after):
    """Accept changes confined to constants inside assignments directly in a class."""

    def compare(left, right, inside_class=False, inside_value=False):
        if type(left) is not type(right):
            return False
        if isinstance(left, list):
            return len(left) == len(right) and all(
                compare(a, b, inside_class, inside_value) for a, b in zip(left, right)
            )
        if isinstance(left, ast.Constant):
            return inside_value or ast.dump(left) == ast.dump(right)
        if not isinstance(left, ast.AST):
            return left == right
        for name, member in ast.iter_fields(left):
            in_class = inside_class
            in_value = inside_value
            if isinstance(left, ast.ClassDef):
                in_class = name == "body"
                in_value = False
            elif isinstance(left, (ast.FunctionDef, ast.AsyncFunctionDef)):
                in_class = in_value = False
            elif isinstance(left, (ast.Assign, ast.AnnAssign)):
                in_value = inside_class and name == "value"
            if not compare(member, getattr(right, name), in_class, in_value):
                return False
        return True

    return compare(ast.parse(before), ast.parse(after))
