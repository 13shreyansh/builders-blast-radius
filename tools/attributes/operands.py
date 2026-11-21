"""Capture bounded, non-identifying operand observations from the pristine suite."""

import collections
import enum
import hashlib
from functools import lru_cache
import json
import operator

OPS = {
    k: getattr(operator, v)
    for k, v in {
        "Is": "is_",
        "IsNot": "is_not",
        "Eq": "eq",
        "NotEq": "ne",
        "Lt": "lt",
        "LtE": "le",
        "Gt": "gt",
        "GtE": "ge",
    }.items()
}
events = collections.defaultdict(dict)


@lru_cache(maxsize=16384)
def digest(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


@lru_cache(maxsize=4096)
def identity_equality(cls):
    return cls.__eq__ is object.__eq__ and cls.__ne__ is object.__ne__


def encode(x):
    cls = type(x)
    if x is None:
        return ("n",)
    if cls in (bool, int) and abs(x) <= 1000000:
        return ("i", int(x))
    if (
        isinstance(x, str)
        and cls.__eq__ is str.__eq__
        and cls.__ne__ is str.__ne__
        and len(x) <= 96
    ):
        return ("s", digest(str.__str__(x)))
    if (
        cls is tuple
        and len(x) <= 4
        and all(type(i) is int and abs(i) <= 1000000 for i in x)
    ):
        return ("t", *x)
    if identity_equality(cls):
        return ("o",)
    return None


def compare(context, site, name, left, right):
    if context:
        group = events[site]
        a, b = encode(left), encode(right)
        pair = (a, b, left is right) if a is not None and b is not None else None
        if pair not in group and len(group) >= 48:
            pair = None
        group.setdefault(pair, set()).add(context)
    return OPS[name](left, right)


def save(path):
    if events:
        with path.open("w") as stream:
            json.dump(
                {
                    site: [[pair, sorted(ids)] for pair, ids in group.items()]
                    for site, group in events.items()
                },
                stream,
                separators=(",", ":"),
            )
