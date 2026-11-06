"""Python extractor: tree-sitter AST -> shared vocabulary."""
import posixpath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from adrgraph.model import Edge, Extraction, RawImport, RawRef, Symbol, Unit, symbol_id

LANG = "python"
_PARSER = Parser(Language(tree_sitter_python.language()))


def _text(node: Node) -> str:
    return node.text.decode("utf-8", "replace")


def _dotted(node: Node) -> str | None:
    """Dotted text of an identifier or attribute chain over identifiers; None for anything else."""
    if node.type == "identifier":
        return _text(node)
    if node.type == "attribute":
        head = _dotted(node.child_by_field_name("object"))
        attr = node.child_by_field_name("attribute")
        return f"{head}.{_text(attr)}" if head and attr is not None else None
    return None


def _imports(node: Node, unit_id: str) -> list[RawImport]:
    line = node.start_point.row + 1
    if node.type == "import_statement":
        out = []
        for target in node.named_children:
            if target.type == "aliased_import":
                out.append(RawImport(unit_id, _text(target.child_by_field_name("name")), 0, line,
                                     alias=_text(target.child_by_field_name("alias"))))
            elif target.type == "dotted_name":
                out.append(RawImport(unit_id, _text(target), 0, line))
        return out
    # import_from_statement: from <module> import <names>
    module_node = node.child_by_field_name("module_name")
    level = 0
    module = ""
    if module_node is not None:
        if module_node.type == "relative_import":
            for c in module_node.children:
                if c.type == "import_prefix":
                    level = len(_text(c))
                elif c.type == "dotted_name":
                    module = _text(c)
        else:
            module = _text(module_node)
    names = []
    for c in node.children_by_field_name("name"):
        if c.type == "aliased_import":
            names.append((_text(c.child_by_field_name("name")), _text(c.child_by_field_name("alias"))))
        else:
            names.append((_text(c), _text(c)))
    if any(c.type == "wildcard_import" for c in node.children):
        names.append(("*", "*"))
    return [RawImport(unit_id, module, level, line, names=tuple(names))]


def extract(rel_path: str, source: bytes, module_name: str) -> Extraction:
    ex = Extraction()
    kind = "package" if posixpath.basename(rel_path) == "__init__.py" else "module"
    ex.units.append(Unit(rel_path, rel_path, module_name, LANG, kind))
    tree = _PARSER.parse(source)

    def symbol(node: Node, qualified: str, kind: str) -> Symbol:
        name = qualified.rsplit(".", 1)[-1]
        return Symbol(symbol_id(rel_path, qualified), name, qualified, kind, LANG, rel_path,
                      node.start_point.row + 1, node.end_point.row + 1, node.type)

    def walk(node: Node, scope: str, owner: str, in_class: bool, in_function: bool) -> None:
        for child in node.children:
            t = child.type
            if t in ("import_statement", "import_from_statement"):
                ex.imports.extend(_imports(child, rel_path))
            elif t == "function_definition" and not in_function:
                qualified = f"{scope}.{_text(child.child_by_field_name('name'))}"
                sym = symbol(child, qualified, "method" if in_class else "function")
                ex.symbols.append(sym)
                ex.edges.append(Edge("CONTAINS", owner, sym.id))
                walk(child.child_by_field_name("body"), qualified, sym.id, False, True)
            elif t == "class_definition" and not in_function:
                qualified = f"{scope}.{_text(child.child_by_field_name('name'))}"
                sym = symbol(child, qualified, "class")
                ex.symbols.append(sym)
                ex.edges.append(Edge("CONTAINS", owner, sym.id))
                walk(child.child_by_field_name("body"), qualified, sym.id, True, False)
            elif t == "expression_statement" and not in_class and not in_function and child.named_children \
                    and child.named_children[0].type == "assignment":
                left = child.named_children[0].child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    sym = symbol(child.named_children[0], f"{scope}.{_text(left)}", "variable")
                    ex.symbols.append(sym)
                    ex.edges.append(Edge("CONTAINS", owner, sym.id))
                walk(child, scope, owner, in_class, in_function)
            elif t == "call":
                name = _dotted(child.child_by_field_name("function"))
                if name:
                    ex.refs.append(RawRef(owner, name, child.start_point.row + 1, True))
                    args = child.child_by_field_name("arguments")
                    if args is not None:
                        walk(args, scope, owner, in_class, in_function)
                else:
                    walk(child, scope, owner, in_class, in_function)
            elif t == "attribute":
                name = _dotted(child)
                if name and name.split(".", 1)[0] not in ("self", "cls"):
                    ex.refs.append(RawRef(owner, name, child.start_point.row + 1, False))
                elif not name:
                    walk(child, scope, owner, in_class, in_function)
            else:
                walk(child, scope, owner, in_class, in_function)

    walk(tree.root_node, module_name, rel_path, False, False)
    return ex
