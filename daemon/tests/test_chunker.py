"""Tests for contextweave.chunker — semantic code splitting."""

from __future__ import annotations

import textwrap

import pytest

from contextweave.chunker import Chunk, chunk_file


class TestPythonChunker:
    """Python source file chunking via stdlib ast."""

    def test_chunker_splits_python_functions_correctly(self) -> None:
        """Top-level functions become individual 'function' chunks."""
        source: str = textwrap.dedent("""\
            def hello():
                x = 1
                return x

            def world():
                y = 2
                return y
        """)
        chunks: list[Chunk] = chunk_file("/a.py", source, "python")

        assert len(chunks) == 2
        assert chunks[0].chunk_name == "hello"
        assert chunks[0].chunk_type == "function"
        assert chunks[1].chunk_name == "world"
        assert chunks[1].chunk_type == "function"

    def test_chunker_keeps_small_class_as_single_chunk(self) -> None:
        """Classes <= 200 lines are kept as a single 'class' chunk."""
        source: str = textwrap.dedent("""\
            class Greeter:
                def __init__(self):
                    self.name = "world"

                def greet(self):
                    return f"Hello, {self.name}"
        """)
        chunks: list[Chunk] = chunk_file("/b.py", source, "python")

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "class"
        assert chunks[0].chunk_name == "Greeter"

    def test_chunker_splits_python_class_into_methods_when_over_200_lines(self) -> None:
        """Classes > 200 lines are split at method boundaries."""
        methods: list[str] = []
        for i in range(25):
            body_lines = "\n".join(f"        x{j} = {j}" for j in range(9))
            methods.append(f"    def method_{i}(self):\n{body_lines}\n        return x0\n")
        source: str = "class BigClass:\n" + "\n".join(methods)

        chunks: list[Chunk] = chunk_file("/c.py", source, "python")

        assert len(chunks) > 1
        assert all(c.chunk_type == "method" for c in chunks)
        assert chunks[0].chunk_name.startswith("BigClass.")

    def test_chunker_handles_async_functions(self) -> None:
        """Async function definitions are chunked correctly."""
        source: str = textwrap.dedent("""\
            async def fetch_data():
                data = await get()
                return data
        """)
        chunks: list[Chunk] = chunk_file("/d.py", source, "python")

        assert len(chunks) == 1
        assert chunks[0].chunk_name == "fetch_data"
        assert chunks[0].chunk_type == "function"

    def test_chunker_skips_chunks_shorter_than_3_lines(self) -> None:
        """Functions under 3 lines are discarded."""
        source: str = textwrap.dedent("""\
            def tiny():
                pass

            def bigger():
                x = 1
                y = 2
                return x + y
        """)
        chunks: list[Chunk] = chunk_file("/e.py", source, "python")

        names: list[str] = [c.chunk_name for c in chunks]
        assert "tiny" not in names
        assert "bigger" in names

    def test_chunker_chunk_name_includes_class_for_method(self) -> None:
        """Method chunks from large classes use 'ClassName.method_name' format."""
        methods: list[str] = []
        for i in range(25):
            body_lines = "\n".join(f"        x{j} = {j}" for j in range(9))
            methods.append(f"    def method_{i}(self):\n{body_lines}\n        return x0\n")
        source: str = "class MyClass:\n" + "\n".join(methods)

        chunks: list[Chunk] = chunk_file("/f.py", source, "python")

        assert any(c.chunk_name == "MyClass.method_0" for c in chunks)


class TestFallbacks:
    """Fallback and error handling behaviour."""

    def test_chunker_falls_back_on_syntax_error(self) -> None:
        """Syntax errors produce a single 'module' fallback chunk."""
        source: str = "def broken(\n  return ???\n  }"
        chunks: list[Chunk] = chunk_file("/bad.py", source, "python")

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "module"
        assert chunks[0].chunk_name == "__module__"

    def test_chunker_falls_back_on_empty_file(self) -> None:
        """Empty files produce a single fallback chunk."""
        chunks: list[Chunk] = chunk_file("/empty.py", "", "python")

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "module"

    def test_chunker_fallback_caps_at_4000_chars(self) -> None:
        """Fallback chunk content is capped at 4000 characters."""
        long_content: str = "x = 1\n" * 2000
        chunks: list[Chunk] = chunk_file("/bad_syntax.py", "def (\n" + long_content, "python")

        assert len(chunks) == 1
        assert len(chunks[0].content) <= 4000

    def test_chunker_returns_empty_list_for_unsupported_language(self) -> None:
        """Unsupported languages return an empty list without crashing."""
        chunks: list[Chunk] = chunk_file("/a.rb", "def main; end", "ruby")

        assert chunks == []


class TestChunkIdDeterminism:
    """Chunk IDs are deterministic and stable."""

    def test_chunker_chunk_id_is_deterministic(self) -> None:
        """Same file_path + chunk_name always produce the same ID."""
        source: str = textwrap.dedent("""\
            def stable():
                a = 1
                return a
        """)
        chunks_a: list[Chunk] = chunk_file("/s.py", source, "python")
        chunks_b: list[Chunk] = chunk_file("/s.py", source, "python")

        assert chunks_a[0].id == chunks_b[0].id
        assert len(chunks_a[0].id) == 16


class TestTypeScriptChunker:
    """TypeScript / JavaScript chunking via tree-sitter."""

    def test_chunker_splits_typescript_functions(self) -> None:
        """Top-level function declarations are chunked."""
        source: str = textwrap.dedent("""\
            function greet(name: string): string {
                const msg = `Hello, ${name}`;
                return msg;
            }

            function farewell(name: string): string {
                const msg = `Goodbye, ${name}`;
                return msg;
            }
        """)
        chunks: list[Chunk] = chunk_file("/app.ts", source, "typescript")

        assert len(chunks) == 2
        names: list[str] = [c.chunk_name for c in chunks]
        assert "greet" in names
        assert "farewell" in names

    def test_chunker_splits_javascript_arrow_functions(self) -> None:
        """Arrow functions assigned via const are chunked as functions."""
        source: str = textwrap.dedent("""\
            const add = (a, b) => {
                const result = a + b;
                return result;
            };
        """)
        chunks: list[Chunk] = chunk_file("/util.js", source, "javascript")

        assert len(chunks) >= 1
        assert any(c.chunk_name == "add" for c in chunks)


class TestGoChunker:
    """Go chunking via tree-sitter-go."""

    def test_chunker_splits_go_functions(self) -> None:
        """Top-level Go function declarations are chunked."""
        source: str = textwrap.dedent("""\
            package main

            func Add(a int, b int) int {
                total := a + b
                return total
            }

            func Greet(name string) string {
                message := "Hello, " + name
                return message
            }
        """)
        chunks: list[Chunk] = chunk_file("/main.go", source, "go")

        assert len(chunks) == 2
        names: list[str] = [c.chunk_name for c in chunks]
        assert "Add" in names
        assert "Greet" in names
        assert all(c.chunk_type == "function" for c in chunks)
        assert all(c.language == "go" for c in chunks)

    def test_chunker_splits_go_methods_with_receiver_type(self) -> None:
        """Go method chunks include the receiver type in their names."""
        source: str = textwrap.dedent("""\
            package main

            type Counter struct {
                value int
            }

            func (c *Counter) Inc(delta int) int {
                c.value += delta
                return c.value
            }
        """)
        chunks: list[Chunk] = chunk_file("/counter.go", source, "go")

        assert len(chunks) == 1
        assert chunks[0].chunk_name == "Counter.Inc"
        assert chunks[0].chunk_type == "method"
        assert chunks[0].language == "go"

    def test_chunker_go_fallback_on_syntax_error(self) -> None:
        """Go parse errors produce a whole-file module fallback chunk."""
        source: str = textwrap.dedent("""\
            package main

            func Broken( {
                return 1
        """)
        chunks: list[Chunk] = chunk_file("/broken.go", source, "go")

        assert len(chunks) == 1
        assert chunks[0].chunk_name == "__module__"
        assert chunks[0].chunk_type == "module"
        assert chunks[0].language == "go"


class TestRustChunker:
    """Rust chunking via tree-sitter-rust."""

    def test_chunker_splits_rust_functions(self) -> None:
        """Top-level Rust function items are chunked."""
        source: str = textwrap.dedent("""\
            fn add(a: i32, b: i32) -> i32 {
                let total = a + b;
                total
            }

            fn greet(name: &str) -> String {
                let message = format!("Hello, {}", name);
                message
            }
        """)
        chunks: list[Chunk] = chunk_file("/lib.rs", source, "rust")

        assert len(chunks) == 2
        names: list[str] = [c.chunk_name for c in chunks]
        assert "add" in names
        assert "greet" in names
        assert all(c.chunk_type == "function" for c in chunks)
        assert all(c.language == "rust" for c in chunks)

    def test_chunker_splits_rust_impl_methods(self) -> None:
        """Rust impl methods use StructName::method_name chunk names."""
        source: str = textwrap.dedent("""\
            struct Counter {
                value: i32,
            }

            impl Counter {
                fn inc(&mut self, delta: i32) -> i32 {
                    self.value += delta;
                    self.value
                }

                fn current(&self) -> i32 {
                    let value = self.value;
                    value
                }
            }
        """)
        chunks: list[Chunk] = chunk_file("/counter.rs", source, "rust")

        assert len(chunks) == 2
        names: list[str] = [c.chunk_name for c in chunks]
        assert "Counter::inc" in names
        assert "Counter::current" in names
        assert all(c.chunk_type == "method" for c in chunks)
        assert all(c.language == "rust" for c in chunks)

    def test_chunker_rust_fallback_on_syntax_error(self) -> None:
        """Rust parse errors produce a whole-file module fallback chunk."""
        source: str = textwrap.dedent("""\
            fn broken( {
                let value = 1;
                value
        """)
        chunks: list[Chunk] = chunk_file("/broken.rs", source, "rust")

        assert len(chunks) == 1
        assert chunks[0].chunk_name == "__module__"
        assert chunks[0].chunk_type == "module"
        assert chunks[0].language == "rust"
