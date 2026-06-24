"""End-to-end MCP tool validation across all languages and servers.

Runs inside the Docker harness built from tests/docker/Dockerfile.mcp-tools-e2e.
Each language is installed and enabled as its own test, then MCP tools are
exercised against real source code.

Languages: Python (pyright), Python (ruff), TypeScript, Rust, C/C++
Tools: lsp_capabilities, lsp_symbols, lsp_doc_symbols, lsp_definition,
       lsp_hover, lsp_references, lsp_type_definition, lsp_implementation,
       lsp_call_hierarchy, lsp_symbol_context, lsp_code_actions,
       lsp_format_preview, lsp_organize_imports_preview, lsp_diagnostics,
       lsp_file_diagnostics, lsp_changed_diagnostics, lsp_rename_preview,
       lsp_inlay_hints, lsp_signature_help, lsp_type_hierarchy, lsp_completion
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from audiagentic.components.coding_lsp import language_registry, lsp_api
from audiagentic.foundation.components.dependencies import build_dependency_workflow
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.features.base import FeatureState, ImplementationState
from audiagentic.foundation.features.state import (
    set_feature_state,
    set_implementation_state,
)
from audiagentic.runtime.lifecycle.components import enable_component, install_component

pytestmark = [
    pytest.mark.slow,
    pytest.mark.mutates_host,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="MCP tools e2e requires Docker harness",
    ),
]

# ── Sample source files per language ──────────────────────────────────────

PYTHON_SAMPLE = '''
from typing import Protocol


class Calculator(Protocol):
    """Protocol for calculator operations."""
    def add(self, a: int, b: int) -> int: ...
    def multiply(self, a: int, b: int) -> int: ...


class SimpleCalculator:
    """A basic calculator implementation."""

    def add(self, a: int, b: int) -> int:
        return a + b

    def multiply(self, a: int, b: int) -> int:
        return a * b


def compute(x: int, y: int) -> int:
    calc = SimpleCalculator()
    result = calc.add(x, y)
    result = calc.multiply(result, 2)
    return result


def main() -> None:
    value = compute(3, 4)
    print(value)
'''

TYPESCRIPT_SAMPLE = '''
interface Shape {
    area(): number;
    perimeter(): number;
}

class Circle implements Shape {
    constructor(public radius: number) {}

    public area(): number {
        return Math.PI * this.radius * this.radius;
    }

    public perimeter(): number {
        return 2 * Math.PI * this.radius;
    }
}

class Rectangle implements Shape {
    constructor(public width: number, public height: number) {}

    public area(): number {
        return this.width * this.height;
    }

    public perimeter(): number {
        return 2 * (this.width + this.height);
    }
}

function describeShape(shape: Shape): string {
    const area = shape.area();
    return `Area: ${area}`;
}

const circle = new Circle(5);
const rect = new Rectangle(3, 4);
describeShape(circle);
describeShape(rect);
'''

RUST_SAMPLE = '''
pub trait Drawable {
    fn draw(&self) -> String;
    fn name(&self) -> &str;
}

pub struct Circle {
    pub radius: f64,
}

impl Circle {
    pub fn new(radius: f64) -> Self {
        Self { radius }
    }
}

impl Drawable for Circle {
    fn draw(&self) -> String {
        format!("Circle(r={})", self.radius)
    }

    fn name(&self) -> &str {
        "Circle"
    }
}

pub struct Rectangle {
    pub width: f64,
    pub height: f64,
}

impl Drawable for Rectangle {
    fn draw(&self) -> String {
        format!("Rectangle(w={}, h={})", self.width, self.height)
    }

    fn name(&self) -> &str {
        "Rectangle"
    }
}

pub fn render(d: &dyn Drawable) -> String {
    let name = d.name();
    let drawing = d.draw();
    format!("{}: {}", name, drawing)
}

fn main() {
    let c = Circle::new(5.0);
    let r = Rectangle { width: 3.0, height: 4.0 };
    println!("{}", render(&c));
    println!("{}", render(&r));
}
'''

CPP_SAMPLE = '''
#include <string>

class Shape {
public:
    virtual ~Shape() = default;
    virtual double area() const = 0;
    virtual double perimeter() const = 0;
    virtual std::string name() const = 0;
};

class Circle : public Shape {
    double radius_;
public:
    explicit Circle(double r) : radius_(r) {}
    double area() const override { return 3.14159 * radius_ * radius_; }
    double perimeter() const override { return 2 * 3.14159 * radius_; }
    std::string name() const override { return "Circle"; }
};

class Rectangle : public Shape {
    double width_, height_;
public:
    Rectangle(double w, double h) : width_(w), height_(h) {}
    double area() const override { return width_ * height_; }
    double perimeter() const override { return 2 * (width_ + height_); }
    std::string name() const override { return "Rectangle"; }
};

std::string describe(const Shape& s) {
    return s.name() + "(area=" + std::to_string(s.area()) + ")";
}

int main() {
    Circle c(5.0);
    Rectangle r(3.0, 4.0);
    return 0;
}
'''

# Workspace config files
TS_WORKSPACE = {
    "tsconfig.json": '{"compilerOptions":{"target":"ES2020","module":"commonjs"}}\n',
    "package.json": '{"name":"lsp-e2e-ts","private":true}\n',
}

RUST_WORKSPACE = {
    "Cargo.toml": '[package]\nname = "lsp-e2e-rust"\nversion = "0.1.0"\nedition = "2021"\n\n[lib]\npath = "sample.rs"\n',
}

CPP_WORKSPACE = {
    "compile_commands.json": '[{"directory":".","command":"clang++ -c -std=c++17 sample.cpp","file":"sample.cpp"}]\n',
}


# ── Language + server configuration ───────────────────────────────────────

LANG_CONFIGS = {
    "python": {
        "file": "sample.py",
        "content": PYTHON_SAMPLE,
        "workspace": {},
    },
    "python-ruff": {
        "file": "sample_ruff.py",
        "content": PYTHON_SAMPLE,
        "workspace": {},
    },
    "typescript": {
        "file": "sample.ts",
        "content": TYPESCRIPT_SAMPLE,
        "workspace": TS_WORKSPACE,
    },
    "rust": {
        "file": "sample.rs",
        "content": RUST_SAMPLE,
        "workspace": RUST_WORKSPACE,
    },
    "cpp": {
        "file": "sample.cpp",
        "content": CPP_SAMPLE,
        "workspace": CPP_WORKSPACE,
    },
}


# ── Error samples with deliberate mistakes for diagnostics testing ─────────

PYTHON_ERROR_SAMPLE = '''
from typing import Protocol

class Calculator(Protocol):
    def add(self, a: int, b: int) -> int: ...

class SimpleCalculator:
    def add(self, a: int, b: int) -> int:
        return a + b

def compute(x: int, y: int) -> int:
    calc = SimpleCalculator()
    result = calc.add(x, y)
    # ERROR: undefined variable 'undefined_var'
    _ = undefined_var
    # ERROR: type mismatch — str instead of int
    return result + "not an int"

# ERROR: unused import
import os

def main() -> None:
    value = compute(3, 4)
    print(value)
'''

TYPESCRIPT_ERROR_SAMPLE = '''
interface Shape {
    area(): number;
}

class Circle implements Shape {
    constructor(public radius: number) {}

    public area(): number {
        return Math.PI * this.radius * this.radius;
    }
}

// ERROR: unused variable
const unused = 42;

// ERROR: type error — string instead of number
const circle = new Circle(5);
const badArea: string = circle.area();

// ERROR: unused import
import * as fs from "fs";

const rect = new Circle(3);
console.log(rect.area());
'''

RUST_ERROR_SAMPLE = '''
pub trait Drawable {
    fn draw(&self) -> String;
    fn name(&self) -> &str;
}

pub struct Circle {
    pub radius: f64,
}

impl Circle {
    pub fn new(radius: f64) -> Self {
        Self { radius }
    }
}

impl Drawable for Circle {
    fn draw(&self) -> String {
        format!("Circle(r={})", self.radius)
    }

    fn name(&self) -> &str {
        "Circle"
    }
}

// ERROR: unused variable
let _unused: i32 = 42;

// ERROR: type mismatch — String instead of f64
let c = Circle::new(5.0);
let bad_type: String = format!("{}", c.radius);

fn main() {
    let r = Circle::new(3.0);
    println!("{}", r.draw());
}
'''

# ── Language server binary cache ────────────────────────────────────────────

_CACHE_MARKER_NAME = ".lsp-bin-cache-ready"


def _ensure_lsp_binaries_on_path(root: Path, languages: list[str] | None = None) -> None:
    """Install language server binaries once and add to PATH.

    Creates a shared temp directory, installs all requested language servers
    into it, and prepends it to PATH so subsequent tests find the binaries
    immediately without re-installing.
    """

    cache_dir = root / ".lsp-bin-cache"
    marker = cache_dir / _CACHE_MARKER_NAME
    if marker.exists():
        cached_bin = str(cache_dir / "bin")
        if cached_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = cached_bin + os.pathsep + os.environ.get("PATH", "")
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "bin").mkdir(exist_ok=True)
    cache_bin = str(cache_dir / "bin")
    os.environ["PATH"] = cache_bin + os.pathsep + os.environ.get("PATH", "")

    # Install each language's dependency
    dep_cfgs = language_registry.dependency_cfgs(languages)
    if dep_cfgs:
        workflow = build_dependency_workflow(
            dep_cfgs,
            workflow_id="coding-lsp-cache",
            action="install",
        )
        result = workflow.run({})
        assert result.status == "ok", f"Failed to cache language servers: {result}"

    marker.touch()


# ── Project provisioning (install coding-lsp component once) ──────────────

@pytest.fixture(scope="module")
def e2e_lsp_cache(tmp_path_factory) -> Path:
    """Install all language server binaries once into a shared temp directory."""
    cache_root = tmp_path_factory.mktemp("lsp-bin-cache-root")
    all_langs = list(LANG_CONFIGS.keys())
    _ensure_lsp_binaries_on_path(cache_root, all_langs)
    return cache_root


_LANG_READINESS_TIMEOUT: dict[str, float] = {
    "rust": 90.0,
    "cpp": 30.0,
    "python": 15.0,
    "python-ruff": 15.0,
    "typescript": 15.0,
}


def _wait_for_lsp_ready(root: Path, sample_file: Path, timeout: float | None = None) -> bool:
    """Poll lsp_capabilities until the server responds or timeout.

    Uses per-language timeouts because rust-analyzer's cargo metadata
    indexing can take 60-90s on first connect.
    """
    if timeout is None:
        timeout = _LANG_READINESS_TIMEOUT.get(sample_file.suffix.lstrip("."), 10.0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = lsp_api.server_capabilities(str(sample_file))
        if "error" not in result and "supported" in result:
            # For rust-analyzer, verify it can actually resolve definitions
            # (server_capabilities and document_symbols return quickly but
            #  cargo metadata / cargo check may still be running)
            if sample_file.suffix == ".rs":
                content = sample_file.read_text(encoding="utf-8")
                lines = content.split("\n")
                for i, line in enumerate(lines, 1):
                    if "Circle::new" in line:
                        try:
                            def_result = lsp_api.definition(str(sample_file), f"{i}:{line.index('Circle') + 1}")
                            if isinstance(def_result, list) and len(def_result) > 0:
                                # Extra delay to allow references/implementation indexing
                                time.sleep(5)
                                return True
                        except Exception:
                            pass
                        break
                time.sleep(2.0)
                continue
            return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def e2e_project(e2e_lsp_cache: Path, tmp_path_factory) -> Path:
    """Provision a project with coding-lsp installed and enabled."""
    root = tmp_path_factory.mktemp("mcp-e2e-project")
    (root / ".audiagentic").mkdir(parents=True, exist_ok=True)

    register_all_components()

    result = install_component("coding-lsp", root)
    assert result["ok"], f"install coding-lsp failed: {result}"
    result = enable_component("coding-lsp", root)
    assert result["ok"], f"enable coding-lsp failed: {result}"

    set_implementation_state(
        root, "coding-lsp", "ag-lsp",
        ImplementationState(enabled=True, options={"mutation-enabled": True}),
    )

    # Write workspace config files and sample sources
    for lang, cfg in LANG_CONFIGS.items():
        for rel, body in cfg["workspace"].items():
            (root / rel).write_text(body, encoding="utf-8")
        (root / cfg["file"]).write_text(cfg["content"], encoding="utf-8")

    return root


# ── Helper: install + enable a single language ────────────────────────────

def _install_and_enable_language(e2e_project: Path, language: str) -> None:
    """Install the language server dependency and enable the language."""
    spec = language_registry.get_language(language)
    if spec is not None:
        binary = spec.command[0]
        if shutil.which(binary) is not None:
            # Already installed — just enable and wait for readiness
            set_feature_state(e2e_project, "coding-lsp", "language", language, FeatureState(enabled=True))
            sample_file = e2e_project / LANG_CONFIGS[language]["file"]
            assert _wait_for_lsp_ready(e2e_project, sample_file), (
                f"Language server for {language} did not become ready"
            )
            return

    set_feature_state(e2e_project, "coding-lsp", "language", language, FeatureState(enabled=True))

    dep_cfgs = language_registry.dependency_cfgs([language])
    if dep_cfgs:
        workflow = build_dependency_workflow(dep_cfgs, workflow_id=f"coding-lsp-{language}", action="install")
        result = workflow.run({})
        assert result.status == "ok", f"Failed to install deps for {language}: {result}"

    # Wait for the language server to become ready
    sample_file = e2e_project / LANG_CONFIGS[language]["file"]
    assert _wait_for_lsp_ready(e2e_project, sample_file), (
        f"Language server for {language} did not become ready"
    )


# ── Per-language install + enable tests ───────────────────────────────────

@pytest.mark.no_parallel
@pytest.mark.parametrize("language", list(LANG_CONFIGS.keys()))
def test_language_install(e2e_project: Path, language: str) -> None:
    """Install the language server binary (do not enable the language yet)."""
    spec = language_registry.get_language(language)
    if spec is None:
        pytest.skip(f"Language spec not found: {language}")

    binary = spec.command[0]
    if shutil.which(binary) is not None:
        # Already installed
        return

    dep_cfgs = language_registry.dependency_cfgs([language])
    if dep_cfgs:
        workflow = build_dependency_workflow(dep_cfgs, workflow_id=f"coding-lsp-{language}", action="install")
        result = workflow.run({})
        assert result.status == "ok", f"Failed to install deps for {language}: {result}"

    path = shutil.which(binary)
    assert path is not None, f"{language} server binary {binary!r} not on PATH after install"


# ── Per-language ready fixture (installs only the requested language) ─────

@pytest.fixture
def language(e2e_project: Path, request) -> str:
    """Install and enable only the specific language being tested."""
    lang = request.param
    _install_and_enable_language(e2e_project, lang)
    spec = language_registry.get_language(lang)
    assert spec is not None, f"Language spec not found: {lang}"
    binary = spec.command[0]
    path = shutil.which(binary)
    assert path is not None, f"{lang} server binary {binary!r} not on PATH after install"
    return lang


# ── lsp_capabilities ──────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust", "cpp"], indirect=["language"])
def test_lsp_capabilities_returns_supported_methods(e2e_project: Path, language: str) -> None:
    """lsp_capabilities should return supported methods for each language."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.server_capabilities(str(sample))
    assert "error" not in result, f"server_capabilities error for {language}: {result}"
    assert "supported" in result
    assert len(result["supported"]) > 0, f"No capabilities reported for {language}"
    assert "definition" in result["supported"], f"definition not supported for {language}"
    assert "hover" in result["supported"], f"hover not supported for {language}"


# ── lsp_doc_symbols ───────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust", "cpp"], indirect=["language"])
def test_lsp_doc_symbols_returns_outline(e2e_project: Path, language: str) -> None:
    """lsp_doc_symbols should return document outline for each language."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    symbols = lsp_api.document_symbols(str(sample))
    assert isinstance(symbols, list), f"doc_symbols should return list for {language}"
    errors = [s for s in symbols if isinstance(s, dict) and s.get("error")]
    assert not errors, f"doc_symbols errors for {language}: {errors}"
    assert len(symbols) > 0, f"doc_symbols returned empty for {language}"


# ── lsp_symbols (workspace) ───────────────────────────────────────────────

@pytest.mark.no_parallel
@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_workspace_symbols_finds_marker(e2e_project: Path, language: str) -> None:
    """lsp_symbols should find workspace symbols for each language."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    query_map = {
        "python": "Calculator",
        "typescript": "Shape",
        "rust": "Drawable",
    }
    query = query_map[language]
    symbols = lsp_api.workspace_symbols(query, str(e2e_project))
    assert isinstance(symbols, list)
    errors = [s for s in symbols if isinstance(s, dict) and s.get("error")]
    assert not errors, f"workspace_symbols errors for {language}: {errors}"
    names = [s.get("name", "") for s in symbols if isinstance(s, dict)]
    assert any(query in n for n in names), (
        f"workspace_symbols did not find '{query}' in {language}: {names}"
    )


# ── lsp_definition ────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust", "cpp"], indirect=["language"])
def test_lsp_definition_resolves_symbol(e2e_project: Path, language: str) -> None:
    """lsp_definition should resolve to the correct location."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    target_col = 1
    for i, line in enumerate(lines, 1):
        if language == "python" and "SimpleCalculator" in line and "class " not in line:
            target_line = i
            target_col = line.index("SimpleCalculator") + 1
            break
        if language == "rust" and "Circle::new" in line:
            target_line = i
            target_col = line.index("Circle") + 1
            break
    if target_line is None:
        for i, line in enumerate(lines, 1):
            if "class " in line or "pub struct " in line or line.strip().startswith("class "):
                target_line = i
                break

    assert target_line is not None, f"Could not find class/struct in {language} sample"

    result = lsp_api.definition(str(sample), f"{target_line}:{target_col}")
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"definition errors for {language}: {errors}"
    if language == "python" and not result:
        pytest.skip("pyright may not resolve definition for constructor calls")
    assert len(result) > 0, f"definition returned empty for {language} at line {target_line}"


# ── lsp_hover ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust", "cpp"], indirect=["language"])
def test_lsp_hover_returns_info(e2e_project: Path, language: str) -> None:
    """lsp_hover should return type/signature info for a symbol."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if "class " in line or "pub struct " in line:
            target_line = i
            break

    assert target_line is not None
    result = lsp_api.hover(str(sample), f"{target_line}:8")
    assert result is not None, f"hover returned None for {language}"
    assert "error" not in result, f"hover error for {language}: {result}"
    assert "contents" in result


# ── lsp_references ────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_references_finds_usages(e2e_project: Path, language: str) -> None:
    """lsp_references should find all usages of a symbol."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    target_col = 8
    for i, line in enumerate(lines, 1):
        if language == "rust" and "pub struct Circle" in line:
            target_line = i
            target_col = line.index("Circle") + 1
            break
        if "class " in line or "pub struct " in line or line.strip().startswith("class "):
            target_line = i
            break

    assert target_line is not None
    result = lsp_api.references(str(sample), f"{target_line}:{target_col}")
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"references errors for {language}: {errors}"
    assert len(result) > 0, f"references returned empty for {language}"


# ── lsp_type_definition ───────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_type_definition_resolves_type(e2e_project: Path, language: str) -> None:
    """lsp_type_definition should resolve to type declaration."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if language == "python" and ": int" in line:
            target_line = i
            break
        if language == "typescript" and ": number" in line:
            target_line = i
            break

    if target_line:
        result = lsp_api.type_definition(str(sample), f"{target_line}:1")
        assert isinstance(result, list)
        errors = [r for r in result if isinstance(r, dict) and r.get("error")]
        assert not errors, f"type_definition errors for {language}: {errors}"


# ── lsp_implementation ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["typescript", "rust"], indirect=["language"])
def test_lsp_implementation_finds_implementors(e2e_project: Path, language: str) -> None:
    """lsp_implementation should find concrete implementations of an interface/trait."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    target_col = 8
    for i, line in enumerate(lines, 1):
        if language == "typescript" and "interface " in line:
            target_line = i
            break
        if language == "rust" and "pub trait Drawable" in line:
            target_line = i
            target_col = line.index("Drawable") + 1
            break

    assert target_line is not None
    result = lsp_api.implementation(str(sample), f"{target_line}:{target_col}")
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"implementation errors for {language}: {errors}"
    assert len(result) > 0, f"implementation returned empty for {language}"


# ── lsp_call_hierarchy ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_call_hierarchy_incoming(e2e_project: Path, language: str) -> None:
    """lsp_call_hierarchy should find callers of a function."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if "def " in line or "function " in line or "pub fn " in line:
            target_line = i
            break

    if target_line:
        result = lsp_api.call_hierarchy(str(sample), f"{target_line}:5", direction="incoming")
        assert isinstance(result, list)
        errors = [r for r in result if isinstance(r, dict) and r.get("error")]
        assert not errors, f"call_hierarchy errors for {language}: {errors}"


# ── lsp_symbol_context ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust", "cpp"], indirect=["language"])
def test_lsp_symbol_context_returns_combined_info(e2e_project: Path, language: str) -> None:
    """lsp_symbol_context should return hover + definition + references."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if "class " in line or "pub struct " in line or line.strip().startswith("class "):
            target_line = i
            break

    assert target_line is not None
    result = lsp_api.symbol_context(str(sample), f"{target_line}:8")
    assert isinstance(result, dict)
    assert "hover" in result
    assert "definitions" in result
    assert "references" in result
    assert "referenceCount" in result


# ── lsp_code_actions ──────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_code_actions_returns_actions(e2e_project: Path, language: str) -> None:
    """lsp_code_actions should return available actions."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.code_actions(str(sample))
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"code_actions errors for {language}: {errors}"


# ── lsp_format_preview ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_format_preview_returns_edits_or_none(e2e_project: Path, language: str) -> None:
    """lsp_format_preview should return formatting edits or None."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.format_preview(str(sample))
    assert result is None or isinstance(result, dict)
    if result and "error" in result:
        pytest.skip(f"format_preview not supported for {language}: {result['error']}")


# ── lsp_organize_imports_preview ──────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_organize_imports_preview(e2e_project: Path, language: str) -> None:
    """lsp_organize_imports_preview should return import edits or None."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.organize_imports_preview(str(sample))
    assert result is None or isinstance(result, dict)
    if result and "error" in result:
        pytest.skip(f"organize_imports not supported for {language}: {result['error']}")


# ── lsp_file_diagnostics ──────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_file_diagnostics_returns_list(e2e_project: Path, language: str) -> None:
    """lsp_file_diagnostics should return diagnostics for a file."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.file_diagnostics(str(sample), min_severity=4, timeout=10.0)
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"file_diagnostics errors for {language}: {errors}"


# ── lsp_diagnostics (workspace) ───────────────────────────────────────────

@pytest.mark.no_parallel
@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_workspace_diagnostics(e2e_project: Path, language: str) -> None:
    """lsp_diagnostics should return workspace-wide diagnostics."""
    result = lsp_api.diagnostics(str(e2e_project), min_severity=4, limit=50)
    assert isinstance(result, dict)


# ── lsp_changed_diagnostics ───────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_changed_diagnostics(e2e_project: Path, language: str) -> None:
    """lsp_changed_diagnostics should batch diagnostics for changed files."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.changed_diagnostics([str(sample)], min_severity=4, limit=50)
    assert isinstance(result, dict)


# ── lsp_rename_preview ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_rename_preview_returns_edit(e2e_project: Path, language: str) -> None:
    """lsp_rename_preview should return a workspace edit for renaming."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    target_col = 8
    for i, line in enumerate(lines, 1):
        if language == "rust" and "pub struct Circle" in line:
            target_line = i
            target_col = line.index("Circle") + 1
            break
        if "class " in line or "pub struct " in line or line.strip().startswith("class "):
            target_line = i
            break

    assert target_line is not None
    result = lsp_api.rename_preview(str(sample), f"{target_line}:{target_col}", "RenamedSymbol")
    assert result is not None, f"rename_preview returned None for {language}"
    assert "error" not in result, f"rename_preview error for {language}: {result}"


# ── lsp_inlay_hints ───────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_inlay_hints_returns_hints(e2e_project: Path, language: str) -> None:
    """lsp_inlay_hints should return inlay hints for a range."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.inlay_hints(str(sample), "1:1", "10:1")
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"inlay_hints errors for {language}: {errors}"


# ── lsp_signature_help ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_signature_help_returns_signatures(e2e_project: Path, language: str) -> None:
    """lsp_signature_help should return function signatures at cursor."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if "(" in line and ")" in line and not line.strip().startswith("def ") and not line.strip().startswith("function "):
            target_line = i
            break

    if target_line:
        result = lsp_api.signature_help(str(sample), f"{target_line}:5")
        assert result is None or isinstance(result, dict)


# ── lsp_type_hierarchy ────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["typescript"], indirect=["language"])
def test_lsp_type_hierarchy_supertypes(e2e_project: Path, language: str) -> None:
    """lsp_type_hierarchy should find supertypes for a class."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    content = sample.read_text(encoding="utf-8")
    lines = content.split("\n")

    target_line = None
    for i, line in enumerate(lines, 1):
        if "class " in line and "implements" in line:
            target_line = i
            break

    if target_line:
        result = lsp_api.type_hierarchy(str(sample), f"{target_line}:8", direction="supertypes")
        assert isinstance(result, list)
        errors = [r for r in result if isinstance(r, dict) and r.get("error")]
        assert not errors, f"type_hierarchy errors for {language}: {errors}"


# ── lsp_completion ────────────────────────────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_completion_returns_items(e2e_project: Path, language: str) -> None:
    """lsp_completion should return completion items at a position."""
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    result = lsp_api.completion(str(sample), "1:1")
    assert isinstance(result, list)
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"completion errors for {language}: {errors}"


# ── Diagnostics: detect deliberate errors ─────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript", "rust"], indirect=["language"])
def test_lsp_diagnostics_detects_errors(e2e_project: Path, language: str) -> None:
    """file_diagnostics should report errors in code with deliberate mistakes."""
    error_samples = {
        "python": PYTHON_ERROR_SAMPLE,
        "typescript": TYPESCRIPT_ERROR_SAMPLE,
        "rust": RUST_ERROR_SAMPLE,
    }
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    sample.write_text(error_samples[language], encoding="utf-8")

    # Wait for the language server to re-index the file
    assert _wait_for_lsp_ready(e2e_project, sample), (
        f"Language server for {language} did not become ready after file write"
    )

    result = lsp_api.file_diagnostics(str(sample), min_severity=1, timeout=15.0)
    assert isinstance(result, list), f"file_diagnostics should return list for {language}"

    # Filter out API errors (not code diagnostics)
    diagnostics = [d for d in result if not isinstance(d, dict) or "error" not in d]
    assert len(diagnostics) > 0, (
        f"Expected diagnostics for {language} error sample, got none: {result}"
    )

    # Verify at least one diagnostic is an error (severity 1 or 2)
    errors = [d for d in diagnostics if d.get("severity", 4) <= 2]
    assert len(errors) > 0, (
        f"Expected at least one error diagnostic for {language}, got severity {errors}"
    )


# ── Code actions: offer fixes for errors ──────────────────────────────────

@pytest.mark.parametrize("language", ["python", "typescript"], indirect=["language"])
def test_lsp_code_actions_offers_fixes(e2e_project: Path, language: str) -> None:
    """lsp_code_actions should return quick fixes for code errors."""
    error_samples = {
        "python": PYTHON_ERROR_SAMPLE,
        "typescript": TYPESCRIPT_ERROR_SAMPLE,
    }
    sample = e2e_project / LANG_CONFIGS[language]["file"]
    sample.write_text(error_samples[language], encoding="utf-8")

    assert _wait_for_lsp_ready(e2e_project, sample), (
        f"Language server for {language} did not become ready after file write"
    )

    result = lsp_api.code_actions(str(sample))
    assert isinstance(result, list), f"code_actions should return list for {language}"
    errors = [r for r in result if isinstance(r, dict) and r.get("error")]
    assert not errors, f"code_actions errors for {language}: {errors}"


# ── Multi-server diagnostics merge (pyright + ruff) ───────────────────────

@pytest.mark.no_parallel
def test_multi_server_diagnostics_merge_python(e2e_project: Path) -> None:
    """When both pyright and ruff are configured for Python, diagnostics should merge."""
    # Install both python and python-ruff
    _install_and_enable_language(e2e_project, "python")
    _install_and_enable_language(e2e_project, "python-ruff")
    py_file = e2e_project / "sample.py"
    result = lsp_api.file_diagnostics(str(py_file), min_severity=4, timeout=10.0)
    assert isinstance(result, list)
    seen_keys = set()
    for d in result:
        key = (d.get("source"), str(d.get("range", {})), d.get("message", "")[:80])
        assert key not in seen_keys, f"Duplicate diagnostic: {key}"
        seen_keys.add(key)


# ── Shutdown cleanup ──────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _shutdown_sessions():
    """Ensure all LSP sessions are shut down after the test module."""
    yield
    lsp_api.shutdown_all_sessions()
