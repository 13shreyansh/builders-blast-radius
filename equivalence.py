"""Compare changed expressions using operand values observed on the pinned tree."""

import ast
import gzip
import hashlib
import json
import operator
from pathlib import Path

ORDER = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
UNKNOWN = object()


def equal(left, right, identical):
    if left[0] == right[0] == "o":
        return identical
    return left == right


def evaluate(op, left, right, identical):
    if op in (ast.Is, ast.IsNot):
        if identical is UNKNOWN:
            return UNKNOWN
        return identical if op is ast.Is else not identical
    if op in (ast.Eq, ast.NotEq):
        result = equal(left, right, identical)
        return result if op is ast.Eq else not result
    if op in ORDER and left[0] == right[0] and left[0] in ("i", "t"):
        return ORDER[op](left[1:], right[1:])
    return UNKNOWN


def as_literal(node):
    if not isinstance(node, ast.Constant):
        return UNKNOWN
    value = node.value
    if value is None:
        return ["n"]
    if type(value) in (int, bool):
        return ["i", int(value)]
    if type(value) is str:
        return ["s", hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()]
    return UNKNOWN


def operand(old, new):
    if ast.dump(old) == ast.dump(new):
        return None
    if as_literal(old) is UNKNOWN:
        return UNKNOWN
    return as_literal(new)


def changed_comparisons(before, after):
    changes = []

    def visit(a, b, in_body=False):
        if type(a) is not type(b):
            return False
        if isinstance(a, list):
            return len(a) == len(b) and all(visit(x, y, in_body) for x, y in zip(a, b))
        if not isinstance(a, ast.AST):
            return a == b
        if in_body and isinstance(a, ast.Compare) and len(a.ops) == len(b.ops) == 1:
            if ast.dump(a) != ast.dump(b):
                left = operand(a.left, b.left)
                right = operand(a.comparators[0], b.comparators[0])
                if left is UNKNOWN or right is UNKNOWN:
                    return False
                changes.append(
                    (
                        a.lineno,
                        a.col_offset,
                        type(a.ops[0]),
                        type(b.ops[0]),
                        left,
                        right,
                    )
                )
            return True
        return all(
            visit(
                getattr(a, key),
                getattr(b, key),
                in_body
                or (
                    key == "body"
                    and isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef))
                ),
            )
            for key in a._fields
        )

    return changes if visit(before, after) else []


class Comparisons:
    def __init__(self):
        self.data = None

    def unchanged(self, path, before, after):
        changes = changed_comparisons(ast.parse(before), ast.parse(after))
        if not changes:
            return 0
        if self.data is None:
            self.data = json.loads(
                gzip.decompress(
                    Path(__file__).with_name("operands.json.gz").read_bytes()
                )
            )
        result = None
        for line, column, old, new, replace_left, replace_right in changes:
            observed = self.data.get(f"{path}:{line}:{column}")
            if not observed:
                return 0
            same = 0
            uncertain = 0
            for pair, nodes in observed:
                mask = int(nodes, 16)
                if pair is None:
                    uncertain |= mask
                    continue
                a, b, identical = pair
                previous = evaluate(old, a, b, identical)
                changed_operand = replace_left is not None or replace_right is not None
                current = evaluate(
                    new,
                    replace_left or a,
                    replace_right or b,
                    UNKNOWN if changed_operand else identical,
                )
                if previous is UNKNOWN or current is UNKNOWN or previous != current:
                    uncertain |= mask
                else:
                    same |= mask
            proof = same & ~uncertain
            result = proof if result is None else result & proof
        return result or 0
