from dataclasses import dataclass, asdict
import ast
import builtins
import difflib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    explanation: str = ""
    suggestion: str = ""
    source: str = "local"
    verified: bool = False

    def to_dict(self):
        return asdict(self)


def _syntax_finding(exc: SyntaxError) -> Finding:
    msg = str(exc).splitlines()[0] if str(exc) else "Python syntax error"
    explanation = "Python could not parse this code. Check the indicated line and nearby punctuation or indentation."
    suggestion = "Review brackets, colons, quotes, and indentation around this line."
    if "indent" in msg.lower():
        explanation = "This block's indentation does not match Python's block structure."
        suggestion = "Use consistent spaces and align statements inside the same block."
    return Finding("error", "SYNTAX", msg, getattr(exc, "lineno", None), getattr(exc, "offset", None), explanation, suggestion)


def _ruff(source: str) -> list[Finding]:
    if not shutil.which("ruff"):
        return []
    try:
        proc = subprocess.run(
            ["ruff", "check", "--output-format", "json", "-"],
            input=source,
            text=True,
            capture_output=True,
            timeout=8,
        )
        items = json.loads(proc.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    findings = []
    for item in items:
        code = item.get("code", "RUFF")
        msg = item.get("message", "Ruff finding")
        sev = "warning" if code.startswith(("F", "E", "W")) else "info"
        loc = item.get("location") or {}
        findings.append(Finding(
            sev, code, msg, loc.get("row"), loc.get("column"),
            f"Ruff reported {code}: {msg}",
            "Review the surrounding code and apply the lint correction if appropriate.",
            "ruff",
        ))
    return findings


def _missing_colon_candidates(source: str) -> list[Finding]:
    """Find obvious block headers even when Python cannot parse the file."""
    findings = []
    pattern = re.compile(r"^(?P<indent>\s*)(?P<header>(?:if|elif|else|for|while|try|except|finally|with|def|class|match|case)\b.*?)(?P<comment>\s*#.*)?$")
    for number, line in enumerate(source.splitlines(), 1):
        match = pattern.match(line)
        if match and not match.group("header").rstrip().endswith(":"):
            findings.append(Finding(
                "error", "MISSING_COLON", "Expected ':' at the end of this block header.", number,
                len(line.rstrip()) + 1,
                "Python block headers must end with a colon before their indented body.",
                "Add ':' to the end of this block header.",
            ))
    return findings


def _parse_with_recovery(source: str) -> tuple[ast.AST | None, str, list[Finding]]:
    """Parse source and recover from multiple independent missing-colon errors."""
    working = source
    recovered: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for _ in range(30):
        try:
            return ast.parse(working), working, recovered
        except (SyntaxError, ValueError, TypeError) as exc:
            line = getattr(exc, "lineno", None)
            msg = str(exc)
            candidates = [f for f in _missing_colon_candidates(working) if (f.line, f.code) not in seen]
            if not candidates:
                return None, working, recovered or [_syntax_finding(exc)]
            candidate = candidates[0]
            seen.add((candidate.line, candidate.code))
            lines = working.splitlines(True)
            index = candidate.line - 1
            if not 0 <= index < len(lines):
                return None, working, recovered or [_syntax_finding(exc)]
            ending = "\n" if lines[index].endswith("\n") else ""
            raw = lines[index].rstrip("\n")
            comment = ""
            if "#" in raw:
                code_part, comment_part = raw.split("#", 1)
                raw, comment = code_part.rstrip(), "  #" + comment_part
            lines[index] = raw.rstrip() + ":" + comment + ending
            working = "".join(lines)
            candidate.verified = True
            recovered.append(candidate)
    return None, working, recovered


def _walk_names(tree: ast.AST) -> tuple[set[str], set[str], dict[str, ast.FunctionDef]]:
    defined: set[str] = set()
    loaded: set[str] = set()
    functions: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            functions[node.name] = node
            defined.update(arg.arg for arg in node.args.args + node.args.kwonlyargs)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loaded.add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
    return defined, loaded, functions


def _semantic_findings(tree: ast.AST) -> list[Finding]:
    defined, loaded, functions = _walk_names(tree)
    builtins_set = set(dir(builtins))
    findings: list[Finding] = []
    for name in sorted(loaded - defined - builtins_set):
        uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == name]
        node = uses[0] if uses else None
        candidates = difflib.get_close_matches(name, sorted(defined), n=1, cutoff=0.78)
        if candidates:
            suggestion = f"Replace '{name}' with '{candidates[0]}' if that is the intended variable."
            explanation = f"'{name}' is not defined; it may be a typo for '{candidates[0]}'."
        else:
            suggestion = f"Define '{name}' before it is used, or correct the name."
            explanation = f"'{name}' is read before any local definition was found."
        findings.append(Finding("error", "UNDEFINED_NAME", f"Undefined name: '{name}'", getattr(node, "lineno", None), getattr(node, "col_offset", None), explanation, suggestion))

    assigned: dict[str, ast.Name] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id not in assigned:
            assigned[node.id] = node
    for name, node in sorted(assigned.items()):
        if name.startswith("_") or name in loaded or name in {"self", "cls"}:
            continue
        findings.append(Finding("warning", "UNUSED_VARIABLE", f"Local variable '{name}' is assigned but never used.", node.lineno, node.col_offset, "The assignment is not read later in the analyzed code.", "Remove it if it is unnecessary, or use it where intended."))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in functions:
            continue
        fn = functions[node.func.id]
        positional = [a for a in fn.args.args if a.arg not in {"self", "cls"}]
        defaults = len(fn.args.defaults)
        required = positional[: max(0, len(positional) - defaults)]
        supplied = len(node.args) + len(node.keywords)
        missing = required[supplied:]
        if missing:
            names = ", ".join(arg.arg for arg in missing)
            suggestion = f"Supply argument(s): {names}." 
            available = set()
            for top_level in getattr(tree, "body", []):
                if isinstance(top_level, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                available.update(n.id for n in ast.walk(top_level) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
            if all(arg.arg in available for arg in missing):
                suggestion = f"Add {', '.join(arg.arg for arg in missing)} to the call if those variables are intended."
            findings.append(Finding("error", "MISSING_ARGUMENT", f"Call to '{node.func.id}' is missing required argument(s): {names}.", node.lineno, node.col_offset, "The local function signature requires more values than this call supplies.", suggestion))
    return findings


def analyze_python(source: str) -> list[Finding]:
    if not source.strip():
        return [Finding("info", "EMPTY", "The source file is empty.", explanation="There is no code to analyze.", suggestion="Paste or upload source code to begin.")]
    tree, recovered_source, recovered = _parse_with_recovery(source)
    findings = list(recovered)
    if tree is None:
        if not findings:
            try:
                ast.parse(source)
            except (SyntaxError, ValueError, TypeError) as exc:
                findings.append(_syntax_finding(exc))
        return findings
    findings.extend(_semantic_findings(tree))
    # Ruff on the recovered parseable form exposes multiple independent diagnostics.
    ruff_findings = _ruff(recovered_source)
    local_undefined = {(f.line, f.message.split("'")[1]) for f in findings if f.code == "UNDEFINED_NAME" and "'" in f.message}
    findings.extend(f for f in ruff_findings if not (f.code == "F821" and (f.line, f.message.split("'")[1] if "'" in f.message else "") in local_undefined))
    return _dedupe(findings)


def _dedupe(findings: list[Finding]) -> list[Finding]:
    result = []
    seen = set()
    for finding in findings:
        key = (finding.code, finding.line, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def _compiler_for(language: str) -> tuple[str | None, str]:
    candidates = [("gcc", "GCC"), ("clang", "Clang")] if language == "C" else [("g++", "G++"), ("clang++", "Clang++")]
    for executable, label in candidates:
        path = shutil.which(executable)
        if path:
            return path, label
    return None, " or ".join(label for _, label in candidates)


def _compiler_finding(language: str, tool_label: str) -> Finding:
    names = "gcc or clang" if language == "C" else "g++ or clang++"
    return Finding(
        "warning", "COMPILER_UNAVAILABLE", f"No {names} compiler was found on PATH.",
        explanation=f"{language} analysis requires {names}. Other language analyzers remain available.",
        suggestion=f"Install {names} and add the compiler directory to PATH, then restart BugTrace AI.",
        source="compiler",
    )


def _compiler_diagnostic(line: str, language: str, filename: str) -> Finding | None:
    # GCC/Clang format: file:line:column: severity: diagnostic text
    match = re.match(r"^(.*?):(\d+):(\d+):\s*(fatal error|error|warning|note):\s*(.*)$", line.strip())
    if not match:
        return None
    _path, row, column, severity, message = match.groups()
    level = "warning" if severity == "warning" else ("info" if severity == "note" else "error")
    category = "COMPILER_WARNING" if level == "warning" else ("COMPILER_NOTE" if level == "info" else "COMPILER_ERROR")
    lower = message.lower()
    if "expected ';'" in lower or "before" in lower and "return" in lower:
        suggestion = "Check the previous statement for a missing semicolon."
    elif "undeclared" in lower or "not declared" in lower:
        suggestion = "Declare the identifier or include the header that defines it before use."
    elif "expected" in lower:
        suggestion = "Review the indicated line for missing punctuation, brackets, or delimiters."
    else:
        suggestion = "Review the compiler diagnostic and surrounding source before editing."
    return Finding(
        level, category, f"{filename}:{row}:{column}: {severity}: {message}", int(row), int(column),
        f"The {language} compiler reported a {severity}: {message}", suggestion, "compiler",
    )


def analyze_compiled(source: str, language: str, filename: str = "source") -> list[Finding]:
    compiler, tool_label = _compiler_for(language)
    if not compiler:
        return [_compiler_finding(language, tool_label)]
    suffix = ".c" if language == "C" else ".cpp"
    try:
        with tempfile.TemporaryDirectory(prefix="bugtrace-compiler-") as workspace:
            path = Path(workspace) / (Path(filename).name or f"source{suffix}")
            if path.suffix.lower() not in {".c", ".cpp", ".cc", ".cxx"}:
                path = path.with_suffix(suffix)
            path.write_text(source, encoding="utf-8")
            standard = "c11" if language == "C" else "c++17"
            proc = subprocess.run(
                [compiler, f"-std={standard}", "-Wall", "-Wextra", "-Wpedantic", "-fsyntax-only", str(path)],
                capture_output=True, text=True, timeout=10, check=False,
            )
    except subprocess.TimeoutExpired:
        return [Finding("warning", "COMPILER_TIMEOUT", f"{tool_label} analysis timed out after 10 seconds.", explanation="The compiler did not finish within the safety timeout.", suggestion="Reduce the source size or complexity and try again.", source="compiler")]
    except (OSError, UnicodeError) as exc:
        return [Finding("warning", "COMPILER_FAILURE", f"Unable to run {tool_label}: {type(exc).__name__}.", explanation="The compiler could not be invoked safely.", suggestion="Check the compiler installation and PATH configuration.", source="compiler")]
    output = (proc.stderr or "") + (proc.stdout or "")
    findings = [_compiler_diagnostic(line, language, filename) for line in output.splitlines()]
    findings = [finding for finding in findings if finding is not None]
    if not findings and proc.returncode != 0:
        findings.append(Finding("error", "COMPILER_FAILURE", f"{tool_label} exited with status {proc.returncode}.", explanation="The compiler failed without a parseable diagnostic.", suggestion="Review the compiler installation and source file.", source="compiler"))
    return _dedupe(findings)


def analyze(source: str, language: str, filename: str = "source") -> list[Finding]:
    if language == "Python":
        return analyze_python(source)
    if language in {"C", "C++"}:
        if not source.strip():
            return [Finding("info", "EMPTY", "The source file is empty.", explanation="There is no code to compile or analyze.", suggestion="Paste or upload source code to begin.")]
        return analyze_compiled(source, language, filename)
    if not source.strip():
        return [Finding("info", "EMPTY", "The source file is empty.", explanation="There is no code to analyze.", suggestion="Paste or upload source code to begin.")]
    return [Finding("info", "LIMITED", f"{language} validation is limited in this installation.", explanation=f"Basic input handling is enabled for {language}, but a full compiler/linter is not bundled.", suggestion=f"Install a {language} compiler or linter for deeper diagnostics.")]
