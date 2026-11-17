from datetime import datetime, timezone
import json


def _finding_dicts(findings):
    return [finding.to_dict() if hasattr(finding, "to_dict") else dict(finding) for finding in (findings or [])]


def report_payload(
    file_name,
    language,
    findings,
    mode,
    *,
    original_code: str | None = None,
    corrected_code: str | None = None,
    reanalysis_findings=None,
    fixes_proposed: bool | None = None,
    fix_verified: bool = False,
):
    remaining = _finding_dicts(reanalysis_findings)
    proposed = corrected_code is not None if fixes_proposed is None else fixes_proposed
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file_name": file_name,
        "language": language,
        "mode": mode,
        "findings": _finding_dicts(findings),
        "fix_proposed": proposed,
        "fix_verified": bool(fix_verified),
        "corrected_code": corrected_code,
        "reanalysis": {
            "performed": corrected_code is not None,
            "remaining_findings": remaining,
            "remaining_errors": sum(f.get("severity") == "error" for f in remaining),
            "remaining_warnings": sum(f.get("severity") == "warning" for f in remaining),
        },
    }


def json_report(payload):
    return json.dumps(payload, indent=2)


def text_report(payload):
    lines = [
        "BUGTRACE AI ANALYSIS REPORT",
        "=" * 28,
        f"File: {payload['file_name']}",
        f"Language: {payload['language']}",
        f"Mode: {payload['mode']}",
        f"Timestamp: {payload['timestamp']}",
        f"Fix proposed: {'yes' if payload.get('fix_proposed') else 'no'}",
        f"Fix verified: {'yes' if payload.get('fix_verified') else 'no'}",
        "",
    ]
    if not payload["findings"]:
        lines.append("No findings were reported in the original source.")
    for i, finding in enumerate(payload["findings"], 1):
        lines += [
            f"{i}. [{finding['severity'].upper()}] {finding['code']} (line {finding.get('line') or 'n/a'}, column {finding.get('column') or 'n/a'})",
            f"Message: {finding['message']}",
            f"Explanation: {finding.get('explanation', '')}",
            f"Suggestion: {finding.get('suggestion', '')}",
            f"Verified fix for this finding: {'yes' if finding.get('verified') else 'no'}",
            "",
        ]
    reanalysis = payload.get("reanalysis", {})
    lines += [
        "RE-ANALYSIS",
        "----------",
        f"Performed: {'yes' if reanalysis.get('performed') else 'no'}",
        f"Remaining errors: {reanalysis.get('remaining_errors', 0)}",
        f"Remaining warnings: {reanalysis.get('remaining_warnings', 0)}",
    ]
    remaining = reanalysis.get("remaining_findings", [])
    if remaining:
        lines.append("Remaining findings:")
        for finding in remaining:
            lines.append(f"- [{finding['severity'].upper()}] {finding['code']} (line {finding.get('line') or 'n/a'}): {finding['message']}")
    else:
        lines.append("No remaining findings were reported after re-analysis.")
    return "\n".join(lines)
