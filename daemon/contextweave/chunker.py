"""Semantic code chunker — splits source files at AST boundaries.

NEVER splits a function or class in half.  Chunk boundaries always
align to AST node boundaries.

Supported languages:

* **Python** — stdlib ``ast`` module
* **TypeScript / JavaScript** — ``tree-sitter`` with grammars
* **Go** — ``tree-sitter-go``
* **Rust** — ``tree-sitter-rust``

On *any* parse failure the chunker falls back to a single whole-file
``"module"`` chunk (capped at 4 000 characters).  It never raises.
"""

from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass
from typing import Literal

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_MAX_FALLBACK_CHARS: int = 4_000
_MIN_CHUNK_LINES: int = 3
_MAX_CHUNK_LINES: int = 200
_MAX_CLASS_LINES: int = _MAX_CHUNK_LINES






@dataclass(frozen=True, slots=True)
class Chunk:
    """A semantic code chunk extracted from a source file."""

    id: str
    file_path: str
    chunk_name: str
    chunk_type: Literal["function", "class", "method", "module"]
    content: str
    language: str
    start_line: int
    end_line: int
    created_at: float






def _chunk_id(file_path: str, chunk_name: str) -> str:
    """Deterministic chunk ID: first 16 hex chars of SHA-256."""
    return hashlib.sha256(f"{file_path}:{chunk_name}".encode()).hexdigest()[:16]


def _fallback_chunk(file_path: str, content: str, language: str) -> list[Chunk]:
    """Return a single whole-file ``module`` chunk, capped at 4 000 chars."""
    capped: str = content[:_MAX_FALLBACK_CHARS]
    lines: list[str] = capped.splitlines()
    end_line: int = max(len(lines), 1)

    return [
        Chunk(
            id=_chunk_id(file_path, "__module__"),
            file_path=file_path,
            chunk_name="__module__",
            chunk_type="module",
            content=capped,
            language=language,
            start_line=1,
            end_line=end_line,
            created_at=time.time(),
        )
    ]






def _chunk_python(file_path: str, content: str) -> list[Chunk]:
    """Parse Python source with ``ast`` and extract function / class chunks."""
    tree: ast.Module = ast.parse(content)
    lines: list[str] = content.splitlines()
    chunks: list[Chunk] = []
    now: float = time.time()

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start: int = node.lineno
            end: int = node.end_lineno or start
            if end - start + 1 < _MIN_CHUNK_LINES:
                continue
            chunk_content: str = "\n".join(lines[start - 1 : end])
            chunks.append(
                Chunk(
                    id=_chunk_id(file_path, node.name),
                    file_path=file_path,
                    chunk_name=node.name,
                    chunk_type="function",
                    content=chunk_content,
                    language="python",
                    start_line=start,
                    end_line=end,
                    created_at=now,
                )
            )

        elif isinstance(node, ast.ClassDef):
            cls_start: int = node.lineno
            cls_end: int = node.end_lineno or cls_start
            cls_lines: int = cls_end - cls_start + 1

            if cls_lines <= _MAX_CLASS_LINES:
                if cls_lines >= _MIN_CHUNK_LINES:
                    chunk_content = "\n".join(lines[cls_start - 1 : cls_end])
                    chunks.append(
                        Chunk(
                            id=_chunk_id(file_path, node.name),
                            file_path=file_path,
                            chunk_name=node.name,
                            chunk_type="class",
                            content=chunk_content,
                            language="python",
                            start_line=cls_start,
                            end_line=cls_end,
                            created_at=now,
                        )
                    )
            else:
                
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_start: int = child.lineno
                        m_end: int = child.end_lineno or m_start
                        if m_end - m_start + 1 < _MIN_CHUNK_LINES:
                            continue
                        method_name: str = f"{node.name}.{child.name}"
                        chunk_content = "\n".join(lines[m_start - 1 : m_end])
                        chunks.append(
                            Chunk(
                                id=_chunk_id(file_path, method_name),
                                file_path=file_path,
                                chunk_name=method_name,
                                chunk_type="method",
                                content=chunk_content,
                                language="python",
                                start_line=m_start,
                                end_line=m_end,
                                created_at=now,
                            )
                        )

    return chunks






def _get_ts_language(language: str) -> object:
    """Return the tree-sitter Language object for *language*."""
    from tree_sitter import Language  

    if language == "javascript":
        import tree_sitter_javascript as tsjs  

        return Language(tsjs.language())

    import tree_sitter_typescript as tsts  

    return Language(tsts.language_typescript())


def _extract_name(node: object) -> str:
    """Extract the identifier name from a tree-sitter node."""
    name_node = node.child_by_field_name("name")  
    if name_node is not None:
        return name_node.text.decode()  
    return "<anonymous>"


def _node_to_chunk(
    file_path: str,
    node: object,
    chunk_type: Literal["function", "class", "method", "module"],
    language: str,
    name: str,
    now: float,
    max_lines: int | None = None,
) -> Chunk | None:
    """Convert a tree-sitter node to a :class:`Chunk`, or ``None`` if too small."""
    start_line: int = node.start_point[0] + 1  
    end_line: int = node.end_point[0] + 1  
    line_count: int = end_line - start_line + 1
    if line_count < _MIN_CHUNK_LINES:
        return None
    if max_lines is not None and line_count > max_lines:
        return None

    content: str = node.text.decode()  
    return Chunk(
        id=_chunk_id(file_path, name),
        file_path=file_path,
        chunk_name=name,
        chunk_type=chunk_type,
        content=content,
        language=language,
        start_line=start_line,
        end_line=end_line,
        created_at=now,
    )


def _chunk_ts_js(file_path: str, content: str, language: str) -> list[Chunk]:
    """Parse TypeScript / JavaScript with tree-sitter."""
    from tree_sitter import Parser  

    ts_lang = _get_ts_language(language)
    parser = Parser(ts_lang)  
    tree = parser.parse(content.encode())

    chunks: list[Chunk] = []
    now: float = time.time()

    for node in tree.root_node.children:
        actual: object = node

        
        if node.type in ("export_statement", "export_default_declaration"):
            for child in node.children:  
                if child.type in (
                    "function_declaration",
                    "class_declaration",
                    "lexical_declaration",
                ):
                    actual = child
                    break

        if actual.type == "function_declaration":  
            name: str = _extract_name(actual)
            chunk = _node_to_chunk(file_path, actual, "function", language, name, now)
            if chunk is not None:
                chunks.append(chunk)

        elif actual.type == "class_declaration":  
            cls_name: str = _extract_name(actual)
            start_l: int = actual.start_point[0] + 1  
            end_l: int = actual.end_point[0] + 1  
            cls_lines: int = end_l - start_l + 1

            if cls_lines <= _MAX_CLASS_LINES:
                chunk = _node_to_chunk(file_path, actual, "class", language, cls_name, now)
                if chunk is not None:
                    chunks.append(chunk)
            else:
                
                body = actual.child_by_field_name("body")  
                if body is not None:
                    for member in body.children:  
                        if member.type == "method_definition":
                            m_name: str = f"{cls_name}.{_extract_name(member)}"
                            mc = _node_to_chunk(file_path, member, "method", language, m_name, now)
                            if mc is not None:
                                chunks.append(mc)

        elif actual.type == "lexical_declaration":  
            
            for child in actual.children:  
                if child.type == "variable_declarator":
                    value = child.child_by_field_name("value")
                    if value is not None and value.type == "arrow_function":
                        arrow_name: str = _extract_name(child)
                        chunk = _node_to_chunk(
                            file_path, actual, "function", language, arrow_name, now,
                        )
                        if chunk is not None:
                            chunks.append(chunk)

    return chunks






def _get_go_language() -> object:
    """Return the tree-sitter Language object for Go."""
    from tree_sitter import Language  

    import tree_sitter_go as tsgo  

    return Language(tsgo.language())


def _normalize_go_receiver_type(receiver_type: str) -> str:
    """Normalize a Go receiver type for method chunk names."""
    cleaned: str = receiver_type.strip()
    while cleaned.startswith("*"):
        cleaned = cleaned[1:].strip()
    return cleaned or "<receiver>"


def _get_go_receiver_type(receiver: object | None) -> str:
    """Extract the receiver type from a Go method receiver node."""
    if receiver is None:
        return "<receiver>"

    for child in receiver.children:  
        if child.type == "parameter_declaration":
            type_node = child.child_by_field_name("type")
            if type_node is not None:
                return _normalize_go_receiver_type(type_node.text.decode())

    return _normalize_go_receiver_type(receiver.text.decode().strip("()"))  


def _get_go_method_name(node: object) -> str:
    """Return a Go method name in ReceiverType.MethodName form."""
    receiver = node.child_by_field_name("receiver")  
    receiver_type: str = _get_go_receiver_type(receiver)
    method_name: str = _extract_name(node)
    return f"{receiver_type}.{method_name}"


def _chunk_go(file_path: str, content: str) -> list[Chunk]:
    """Parse Go source code using tree-sitter-go."""
    try:
        from tree_sitter import Parser  

        parser = Parser(_get_go_language())  
        tree = parser.parse(content.encode())
        if tree.root_node.has_error:
            log.warning("chunker_go_syntax_error", file_path=file_path)
            return _fallback_chunk(file_path, content, "go")

        chunks: list[Chunk] = []
        now: float = time.time()

        for node in tree.root_node.children:
            if node.type == "function_declaration":
                name: str = _extract_name(node)
                chunk = _node_to_chunk(
                    file_path,
                    node,
                    "function",
                    "go",
                    name,
                    now,
                    max_lines=_MAX_CHUNK_LINES,
                )
                if chunk is not None:
                    chunks.append(chunk)

            elif node.type == "method_declaration":
                method_name: str = _get_go_method_name(node)
                chunk = _node_to_chunk(
                    file_path,
                    node,
                    "method",
                    "go",
                    method_name,
                    now,
                    max_lines=_MAX_CHUNK_LINES,
                )
                if chunk is not None:
                    chunks.append(chunk)

        return chunks or _fallback_chunk(file_path, content, "go")

    except Exception as exc:
        log.warning("chunker_go_failed", file_path=file_path, error=str(exc))
        return _fallback_chunk(file_path, content, "go")






_RUST_FUNCTION_NODE_TYPES: frozenset[str] = frozenset({"function_item", "fn_item"})


def _get_rust_language() -> object:
    """Return the tree-sitter Language object for Rust."""
    from tree_sitter import Language  

    import tree_sitter_rust as tsrust  

    return Language(tsrust.language())


def _get_rust_impl_type(node: object) -> str:
    """Extract the implemented type name from a Rust impl item."""
    type_node = node.child_by_field_name("type")  
    if type_node is None:
        return "<impl>"
    return type_node.text.decode()


def _rust_impl_functions(node: object) -> list[object]:
    """Return function children inside a Rust impl item."""
    body = node.child_by_field_name("body")  
    if body is None:
        return []
    return [
        child
        for child in body.children  
        if child.type in _RUST_FUNCTION_NODE_TYPES
    ]


def _chunk_rust(file_path: str, content: str) -> list[Chunk]:
    """Parse Rust source code using tree-sitter-rust."""
    try:
        from tree_sitter import Parser  

        parser = Parser(_get_rust_language())  
        tree = parser.parse(content.encode())
        if tree.root_node.has_error:
            log.warning("chunker_rust_syntax_error", file_path=file_path)
            return _fallback_chunk(file_path, content, "rust")

        chunks: list[Chunk] = []
        now: float = time.time()

        for node in tree.root_node.children:
            if node.type in _RUST_FUNCTION_NODE_TYPES:
                name: str = _extract_name(node)
                chunk = _node_to_chunk(
                    file_path,
                    node,
                    "function",
                    "rust",
                    name,
                    now,
                    max_lines=_MAX_CHUNK_LINES,
                )
                if chunk is not None:
                    chunks.append(chunk)

            elif node.type == "impl_item":
                impl_type: str = _get_rust_impl_type(node)
                for method in _rust_impl_functions(node):
                    method_name: str = f"{impl_type}::{_extract_name(method)}"
                    chunk = _node_to_chunk(
                        file_path,
                        method,
                        "method",
                        "rust",
                        method_name,
                        now,
                        max_lines=_MAX_CHUNK_LINES,
                    )
                    if chunk is not None:
                        chunks.append(chunk)

        return chunks or _fallback_chunk(file_path, content, "rust")

    except Exception as exc:
        log.warning("chunker_rust_failed", file_path=file_path, error=str(exc))
        return _fallback_chunk(file_path, content, "rust")






_SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "typescript", "javascript", "go", "rust"}
)


def chunk_file(file_path: str, content: str, language: str) -> list[Chunk]:
    """Split file content into semantic chunks.

    Never raises.  On any failure returns a single whole-file fallback chunk.

    Parameters
    ----------
    file_path:
        Absolute path of the source file.
    content:
        Full text content of the file.
    language:
        Programming language (``"python"``, ``"typescript"``, ``"javascript"``,
        ``"go"``, or ``"rust"``).

    Returns
    -------
    list[Chunk]
        Semantic chunks extracted from the file.
    """
    if language not in _SUPPORTED_LANGUAGES:
        return []

    if not content or not content.strip():
        log.warning("chunker_empty_file", file_path=file_path)
        return _fallback_chunk(file_path, content or "", language)

    try:
        if language == "python":
            chunks: list[Chunk] = _chunk_python(file_path, content)
        elif language == "go":
            chunks = _chunk_go(file_path, content)
        elif language == "rust":
            chunks = _chunk_rust(file_path, content)
        else:
            chunks = _chunk_ts_js(file_path, content, language)

        if not chunks:
            return _fallback_chunk(file_path, content, language)

        return chunks

    except Exception:
        log.warning("chunker_parse_failure_fallback", file_path=file_path, exc_info=True)
        return _fallback_chunk(file_path, content, language)
