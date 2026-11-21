"""Recognize edits to passive class data while preserving the surrounding class structure."""

import ast
from collections import Counter


def bindings(tree, module):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            collect(node, module, result)
    return result


def collect(node, prefix, result):
    owner = prefix + "." + node.name
    names = Counter()
    for item in node.body:
        if isinstance(item, ast.ClassDef):
            collect(item, owner, result)
        elif isinstance(item, (ast.AnnAssign, ast.Assign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            if len(targets) == 1 and isinstance(targets[0], ast.Name):
                name = targets[0].id
                names[name] += 1
                result[owner, name] = (node, item)
    for name, count in names.items():
        if count != 1:
            result.pop((owner, name), None)


def passive(node):
    """An entry can contain constants and built-in literal collections."""
    return isinstance(node, ast.Constant) or (
        isinstance(node, (ast.Set, ast.List, ast.Tuple))
        and all(passive(value) for value in node.elts)
    )


def passive_dict_change(left, right):
    # Keep order and content of every executable entry, including dict unpacking.
    def active_entries(node):
        entries = []
        for key, value in zip(node.keys, node.values):
            if key is None or not (passive(key) and passive(value)):
                entries.append(
                    (ast.dump(key) if key is not None else None, ast.dump(value))
                )
        return entries

    return active_entries(left) == active_entries(right)


def class_data_changes(before, after, path, shadowed):
    """Return old binding spans only when all other executable syntax stays identical."""
    module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    old, new = bindings(before, module), bindings(after, module)
    changed = []
    for (owner, name), (scope, item) in old.items():
        other = new.get((owner, name))
        if other is None:
            if (
                owner + "." + name not in shadowed
                or not isinstance(item, ast.Assign)
                or not isinstance(item.value, ast.Constant)
            ):
                continue
            scope.body.remove(item)
        else:
            value, replacement = item.value, other[1].value
            if value is None or type(value) is not type(replacement):
                continue
            if ast.dump(value) == ast.dump(replacement):
                continue
            if isinstance(value, ast.Dict):
                if not passive_dict_change(value, replacement):
                    continue
            elif not (
                isinstance(value, (ast.Set, ast.Tuple, ast.List))
                and passive(value)
                and passive(replacement)
            ):
                continue
            item.value = other[1].value = ast.Constant(None)
        changed.append((owner, name, item.lineno, item.end_lineno))
    if not changed or ast.dump(before) != ast.dump(after):
        return []
    return changed
