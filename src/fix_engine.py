from dataclasses import dataclass
import difflib
import ast
import re
from .analyzer import Finding, analyze


@dataclass
class CorrectionResult:
    corrected: str | None
    applied: list[Finding]
    remaining: list[Finding]
    verified: bool


def _apply_missing_colons(source: str, findings: list[Finding]) -> tuple[str, list[Finding]]:
    lines = source.splitlines(True)
    applied = []
    for finding in sorted((f for f in findings if f.code == "MISSING_COLON" and f.line), key=lambda f: f.line or 0, reverse=True):
        index = (finding.line or 1) - 1
        if not 0 <= index < len(lines):
            continue
        raw = lines[index]
        ending = "\n" if raw.endswith("\n") else ""
        body = raw.rstrip("\n")
        if not body.rstrip().endswith(":"):
            lines[index] = body.rstrip() + ":" + ending
            applied.append(Finding(finding.severity, finding.code, finding.message, finding.line, finding.column, finding.explanation, finding.suggestion, "local", True))
    return "".join(lines), applied


def _apply_undefined_corrections(source: str, findings: list[Finding]) -> tuple[str, list[Finding]]:
    replacements = {}
    for finding in findings:
        if finding.code != "UNDEFINED_NAME":
            continue
        match = re.search(r"Undefined name: '([^']+)'", finding.message)
        candidate = re.search(r"with '([^']+)'", finding.suggestion)
        if match and candidate:
            replacements[match.group(1)] = candidate.group(1)
    if not replacements:
        return source, []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in replacements:
            line = source.splitlines(True)[node.lineno - 1]
            start = sum(len(x) for x in source.splitlines(True)[: node.lineno - 1]) + node.col_offset
            edits.append((start, start + len(node.id), replacements[node.id]))
    corrected = source
    for start, end, replacement in sorted(edits, reverse=True):
        corrected = corrected[:start] + replacement + corrected[end:]
    applied = [Finding(f.severity, f.code, f.message, f.line, f.column, f.explanation, f.suggestion, "local", True) for f in findings if f.code == "UNDEFINED_NAME" and any(f"with '{r}'" in f.suggestion for r in replacements.values())]
    return corrected, applied


def _apply_missing_arguments(source: str, findings: list[Finding]) -> tuple[str, list[Finding]]:
    """Add an argument only when a same-named variable is already available."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source, []
    lines = source.splitlines(True)
    edits = []
    applied = []
    for finding in findings:
        if finding.code != "MISSING_ARGUMENT" or not finding.line:
            continue
        names_match = re.search(r"argument\(s\): (.+?)\.", finding.message)
        if not names_match:
            continue
        names = [n.strip() for n in names_match.group(1).split(",")]
        available = set()
        for top_level in getattr(tree, "body", []):
            if isinstance(top_level, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            available.update(n.id for n in ast.walk(top_level) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
        if not all(name in available for name in names):
            continue
        # Find the call on the reported line and append names before its closing paren.
        line_index = finding.line - 1
        if not 0 <= line_index < len(lines):
            continue
        line = lines[line_index]
        close = line.rfind(")")
        if close < 0:
            continue
        prefix = ", " if "(" in line[:close] and line[line.find("(") + 1:close].strip() else ""
        absolute = sum(len(x) for x in lines[:line_index]) + close
        edits.append((absolute, absolute, prefix + ", ".join(names)))
        applied.append(Finding(finding.severity, finding.code, finding.message, finding.line, finding.column, finding.explanation, finding.suggestion, "local", True))
    corrected = source
    for start, end, replacement in sorted(edits, reverse=True):
        corrected = corrected[:start] + replacement + corrected[end:]
    return corrected, applied


def _apply_cpp_semicolon(source: str, findings: list[Finding]) -> tuple[str, list[Finding]]:
    lines = source.splitlines(True)
    applied = []

    def is_statement_candidate(raw_line: str) -> bool:
        text = raw_line.strip().rstrip(";")
        if not text or text.startswith(("#", "//", "/*", "*")):
            return False
        if text.endswith(("{", "}")):
            return False
        if re.match(r"^(if|else|for|while|switch|case|default|do|try|catch)\b", text):
            return False
        return True

    for finding in findings:
        lower_message = finding.message.lower()
        semicolon_hint = (
            "semicolon" in lower_message
            or ("expected" in lower_message and ";" in lower_message)
            or ("before" in lower_message and "return" in lower_message)
        )
        if finding.code != "COMPILER_ERROR" or not finding.line or not semicolon_hint:
            continue
        index = finding.line - 1
        # GCC/Clang commonly point to the next token. Prefer the previous non-empty statement.
        candidates = [index, index - 1, index - 2]
        target = next(
            (
                candidate for candidate in candidates
                if 0 <= candidate < len(lines)
                and is_statement_candidate(lines[candidate])
                and not lines[candidate].rstrip().rstrip("\n").rstrip().endswith(";")
            ),
            None,
        )
        if target is None:
            continue
        raw = lines[target]
        ending = "\n" if raw.endswith("\n") else ""
        body = raw.rstrip("\n").rstrip()
        if body.endswith((";", "{", "}", ":")) or body.startswith(("#", "//")):
            continue
        lines[target] = body + ";" + ending
        applied.append(Finding(finding.severity, "MISSING_SEMICOLON", finding.message, finding.line, finding.column, finding.explanation, "Add the missing semicolon to the affected statement.", "local", True))
    return "".join(lines), applied


def _apply_cpp_declaration(source: str, findings: list[Finding]) -> tuple[str, list[Finding]]:
    """Declare an undeclared variable only when its assignment type is clear."""
    lines = source.splitlines(True)
    applied = []
    for finding in findings:
        if finding.code != "COMPILER_ERROR" or not finding.line:
            continue
        lower = finding.message.lower()
        if "undeclared" not in lower and "not declared" not in lower:
            continue
        quoted = re.search(r"[‘'\"]([A-Za-z_]\w*)[’'\"]", finding.message)
        if not quoted:
            continue
        name = quoted.group(1)
        index = finding.line - 1
        if not 0 <= index < len(lines):
            continue
        raw = lines[index]
        match = re.match(r"^(\s*)([A-Za-z_]\w*)\s*=\s*(.+?);\s*(?://.*)?$", raw.rstrip("\n"))
        if not match or match.group(2) != name:
            continue
        expression = match.group(3).strip()
        if re.search(r"[\"'].*[\"']", expression):
            inferred = "const char *"
        elif re.search(r"\d+\.\d+", expression):
            inferred = "double"
        elif re.fullmatch(r"[A-Za-z0-9_+\-*/%()\s.]+", expression):
            inferred = "int"
        else:
            continue
        indentation = raw[: len(raw) - len(raw.lstrip())]
        rest = raw.lstrip()[len(name):]
        lines[index] = f"{indentation}{inferred} {name}{rest}"
        applied.append(Finding(
            finding.severity, "DECLARE_IDENTIFIER", finding.message, finding.line, finding.column,
            finding.explanation, f"Declare '{name}' as {inferred} because its assignment expression has a clear type.",
            "local", True,
        ))
        break
    return "".join(lines), applied


def build_correction(source: str, findings: list[Finding], language: str = "Python", filename: str = "source") -> CorrectionResult:
    """Apply independent safe local fixes, then re-analyze the exact proposal."""
    current = source
    applied: list[Finding] = []
    if language in {"C", "C++"}:
        # Compiler diagnostics are often cascading. Repair one safe statement,
        # recompile, then inspect the next diagnostic rather than editing all
        # guessed lines at once.
        for _ in range(12):
            current_findings = analyze(current, language, filename)
            current, new = _apply_cpp_semicolon(current, current_findings)
            applied.extend(new)
            if new:
                continue
            current, new = _apply_cpp_declaration(current, current_findings)
            applied.extend(new)
            if not new:
                break
        if current == source:
            return CorrectionResult(None, [], analyze(source, language, filename), False)
        remaining = analyze(current, language, filename)
        verified = not any(f.severity == "error" for f in remaining)
        return CorrectionResult(current, applied, remaining, verified)
    # Repeat because syntax repair enables semantic analysis and each pass may expose another safe fix.
    for _ in range(3):
        changed = False
        current, new = _apply_missing_colons(current, analyze(current, "Python", filename))
        applied.extend(new); changed |= bool(new)
        current, new = _apply_undefined_corrections(current, analyze(current, "Python", filename))
        applied.extend(new); changed |= bool(new)
        current, new = _apply_missing_arguments(current, analyze(current, "Python", filename))
        applied.extend(new); changed |= bool(new)
        if not changed:
            break
    if current == source:
        return CorrectionResult(None, [], analyze(source, "Python", filename), False)
    remaining = analyze(current, "Python", filename)
    verified = not any(f.severity == "error" for f in remaining)
    return CorrectionResult(current, applied, remaining, verified)


def local_fix(source: str, findings: list[Finding]) -> str | None:
    return build_correction(source, findings).corrected


def unified_diff(original: str, corrected: str) -> str:
    return "".join(difflib.unified_diff(
        original.splitlines(True), corrected.splitlines(True),
        fromfile="original", tofile="suggested", lineterm="\n"
    ))
