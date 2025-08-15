#!/usr/bin/env python3
# tools/dc_mutable_defaults_fix.py
import ast, sys, pathlib, re

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
APPLY = "--fix" in sys.argv
DRY = not APPLY

mutable_literals = (ast.List, ast.Dict, ast.Set)
mutable_calls = {"list", "dict", "set", "defaultdict"}  # расширяем по желанию

def is_dataclass(cls: ast.ClassDef) -> bool:
    for d in cls.decorator_list:
        if isinstance(d, ast.Name) and d.id == "dataclass":
            return True
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "dataclass":
            return True
    return False

def iter_fields(cls: ast.ClassDef):
    for node in cls.body:
        # assignment with annotation: a: T = value
        if isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            yield node
        # multiple targets (rare inside dataclasses, but handle)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            # could be: a = ...
            # but without annotation — мы не трогаем
            pass

def detect_default(node: ast.AnnAssign):
    v = node.value
    # literal mutable
    if isinstance(v, mutable_literals):
        return "literal", None
    # call like X() or list() / dict()
    if isinstance(v, ast.Call):
        if isinstance(v.func, ast.Name):
            fn = v.func.id
            if fn in mutable_calls:
                return "call_mutable", fn
            # любой конструктор вида TypeName()
            return "call_ctor", fn
        if isinstance(v.func, ast.Attribute):
            # e.g. collections.defaultdict()
            fn = v.func.attr
            return "call_ctor", fn
    return None, None

def patch_text(src: str, cls: ast.ClassDef, node: ast.AnnAssign, kind: str, ctor: str):
    lines = src.splitlines(keepends=True)
    start, end = node.value.lineno-1, node.value.end_lineno-1
    line = lines[end]
    # Вставим field(...) вместо RHS. Грубый, но практичный патч на основе исходного текста.
    # Меняем "= Something()" → "= field(default_factory=Something)"
    # или "= []" → "= field(default_factory=list)" и т.п.
    rhs = src[node.value.lineno-1: node.value.end_lineno].splitlines()
    # Получим исходное RHS как текст
    offset_start = node.value.col_offset
    offset_end = node.value.end_col_offset
    full_line = lines[start]
    old_rhs = full_line[offset_start:offset_end] if start==end else "".join(lines[start:end+1])
    replacement = None
    if kind == "literal":
        # map [] {} set() to list/dict/set
        if isinstance(node.value, ast.List):
            replacement = "field(default_factory=list)"
        elif isinstance(node.value, ast.Dict):
            replacement = "field(default_factory=dict)"
        elif isinstance(node.value, ast.Set):
            replacement = "field(default_factory=set)"
        else:
            replacement = "field(default_factory=list)"
    elif kind in ("call_mutable", "call_ctor"):
        name = ctor or "list"
        replacement = f"field(default_factory={name})"

    if not replacement:
        return src, False

    new_src = src[:]
    new_src = new_src[: (node.value.lineno-1)*len(lines[0]):]  # noop safeguard

    # Простая текстовая замена: в строке(ах) где RHS — меняем на replacement
    if start == end:
        lines[start] = full_line[:offset_start] + replacement + full_line[offset_end:]
    else:
        # многострочный RHS — упростим: заменим первую строку с начала RHS до конца строки и удалим середину, затем вставим replacement и остаток последней
        lines[start] = lines[start][:offset_start] + replacement + "\n"
        for i in range(start+1, end+1):
            lines[i] = ""
    new_src = "".join(lines)

    # ensure `field` is imported
    if "from dataclasses import dataclass, field" not in new_src:
        if "from dataclasses import dataclass" in new_src:
            new_src = new_src.replace("from dataclasses import dataclass",
                                      "from dataclasses import dataclass, field")
        elif "import dataclasses" in new_src:
            # оставим как есть – пользователь сам добавит field, или добавим отдельной строкой
            new_src = new_src.replace("import dataclasses", "from dataclasses import dataclass, field")
        else:
            # добавим общий импорт рядом с первым импортом dataclasses/в начале файла
            new_src = "from dataclasses import dataclass, field\n" + new_src
    return new_src, True

def process_file(path: pathlib.Path):
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"SKIP (syntax): {path} -> {e}")
        return

    edits = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and is_dataclass(node):
            for ann in iter_fields(node):
                kind, ctor = detect_default(ann)
                if kind:
                    field_name = ann.target.id if isinstance(ann.target, ast.Name) else "?"
                    edits.append((node, ann, kind, ctor, field_name))

    if not edits:
        return

    print(f"\n{path}:")
    for _, _, kind, ctor, fname in edits:
        print(f"  - field '{fname}' uses mutable default ({kind}{':'+ctor if ctor else ''}) -> use field(default_factory=...)")

    if not APPLY:
        return

    new_src = src
    # применяем патчи с конца файла к началу (чтобы не сдвигались координаты) — проще пересобирать из AST, но оставим так
    for cls, ann, kind, ctor, _ in reversed(edits):
        new_src, changed = patch_text(new_src, cls, ann, kind, ctor)

    path.write_text(new_src, encoding="utf-8")
    print("  -> fixed")

for p in ROOT.rglob("*.py"):
    process_file(p)
print("\nDone.", "(dry-run)" if DRY else "(fixed)")
