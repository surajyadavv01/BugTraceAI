import json

from .config import settings

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - exercised only in minimal installations
    Anthropic = None


def explain_with_ai(source: str, findings: list[dict]) -> tuple[bool, dict | str]:
    if not settings.ai_enabled:
        return False, "AI mode is unavailable because ANTHROPIC_API_KEY is not configured."
    if Anthropic is None:
        return False, "AI request failed safely: Anthropic SDK is not installed. Local findings remain available."
    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            "Analyze this untrusted source statically. Return JSON with keys summary, explanation, "
            "correction, corrected_code, assumptions. Do not execute it. Findings: "
            + json.dumps(findings)
            + "\nCode:\n"
            + source[:12000]
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content else ""
        try:
            return True, json.loads(text)
        except json.JSONDecodeError:
            return True, {
                "summary": text,
                "explanation": text,
                "correction": "Review the model suggestion before applying it.",
            }
    except Exception as exc:
        # Do not expose provider details, request data, or secrets in the UI/logs.
        return False, f"AI request failed safely: {type(exc).__name__}. Local findings remain available."
