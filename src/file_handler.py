from pathlib import Path

SUPPORTED = {
    ".py": "Python",
    ".js": "JavaScript",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
}

def validate_upload(name: str, data: bytes, max_mb: int = 2) -> tuple[bool, str]:
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        extensions = ", ".join(sorted(SUPPORTED))
        return False, f"Unsupported extension '{suffix or '(none)'}'. Supported extensions: {extensions}."
    if not data:
        return False, "The uploaded file is empty."
    if len(data) > max_mb * 1024 * 1024:
        return False, f"File exceeds the {max_mb} MB upload limit."
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False, "The file is not valid UTF-8 text."
    return True, "Valid upload."

def read_upload(name: str, data: bytes, max_mb: int = 2) -> tuple[str, str]:
    ok, message = validate_upload(name, data, max_mb)
    if not ok:
        raise ValueError(message)
    return data.decode("utf-8"), SUPPORTED[Path(name).suffix.lower()]
