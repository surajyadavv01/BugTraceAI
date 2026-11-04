# BugTrace AI

BugTrace AI is a Streamlit mini-project for safe, beginner-friendly code analysis. It supports pasted/uploaded Python, JavaScript, Java, C, and C++ source; Python AST syntax checks; optional Ruff diagnostics; GCC/G++ or Clang/Clang++ compiler diagnostics; local explanations and conservative fixes; optional Anthropic AI; unified diffs; and JSON/TXT/corrected-code downloads.

## Quick start on Windows

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Run the automated tests with:

```bash
pytest -q
```

## Supported extensions and compiler setup

| Language | Extensions | Analysis method |
|---|---|---|
| Python | `.py` | Python AST, optional Ruff, local rules |
| JavaScript | `.js` | Basic availability notice |
| Java | `.java` | Basic availability notice |
| C | `.c` | GCC first, then Clang, using syntax-only compilation |
| C++ | `.cpp`, `.cc`, `.cxx` | G++ first, then Clang++, using C++17 syntax-only compilation |

For Windows, install a compiler toolchain separately and ensure it is on `PATH` before starting Streamlit. A beginner-friendly option is [MSYS2](https://www.msys2.org/). In the MSYS2 UCRT64 terminal, install GCC/G++ with:

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc
```

Add the corresponding `bin` directory, commonly `C:\msys64\ucrt64\bin`, to the Windows user or system `PATH`. Verify in PowerShell:

```powershell
gcc --version
g++ --version
```

BugTrace AI uses fixed compiler arguments, temporary source files, `-fsyntax-only`, warning flags, and a timeout. It never runs the resulting executable. If no suitable compiler is found, C/C++ analysis reports a setup finding while the other language analyzers continue to work.

For C/C++, the local correction engine applies semicolons only to statement-like lines. It will not append semicolons to `if`, `else`, loop, brace, function, or preprocessor lines. Corrections are applied iteratively: after each safe edit, the source is compiled again so cascading diagnostics can be handled. Undeclared variables such as `total` are reported with a suggested declaration, but BugTrace does not invent a C/C++ type when the type cannot be determined reliably.

## How multi-error correction works

BugTrace first preserves the original source and reports every finding it can identify. For Python, it recovers from multiple obvious missing-colon errors, then performs local AST checks for undefined names, missing required arguments, and unused variables. Ruff diagnostics are included when Ruff is installed.

Only conservative local corrections are applied automatically:

- Missing colons are added to recognizable Python block headers.
- An undefined name is renamed only when a close, unambiguous local name is available.
- A missing function argument is added only when a same-named value is already available in the analyzed code.
- Unused variables are reported but are not silently removed because removing an assignment can change behavior.

The proposed code is re-analyzed after local edits. The UI shows remaining errors and warnings instead of claiming success. Every deterministic edit is labeled as a verified local fix. AI-generated corrections remain unverified suggestions and require human review. The original source is never overwritten.

## AI configuration

The app works without an API key in clearly labeled local fallback mode. To enable AI, copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`, optionally set `ANTHROPIC_MODEL`, and restart Streamlit. Never commit `.env`.

```env
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

## Security and limitations

Submitted code is statically analyzed and never executed. C/C++ compilation is safer than execution but compiling untrusted source can still consume resources or expose compiler vulnerabilities; use isolated environments for sensitive work. Do not upload passwords, API keys, personal data, or confidential source code. JavaScript and Java support is intentionally basic unless compatible external tooling is added. Static analysis cannot detect every logical or runtime bug. AI output may be incorrect and must be reviewed. See `docs/PROJECT_REPORT.md`, `docs/ARCHITECTURE.md`, and `docs/DEMO_SCRIPT.md`.

### Troubleshooting C/C++ analysis

- **Compiler unavailable:** install GCC/G++, Clang/Clang++, or add its directory to `PATH`, then restart the terminal and Streamlit.
- **Compiler timeout:** reduce the uploaded source or use an isolated local toolchain; BugTrace stops waiting after its safety timeout.
- **Warnings remain after a correction:** warnings are not automatically removed because a warning may require a design decision.
- **No executable is produced:** this is intentional; BugTrace uses syntax-only compilation and never runs uploaded programs.
