from typing import Optional
import logging
import json

from httpx import AsyncClient

from constants import LM_STUDIO_URL, GEMMA_TEMPERATURE

logger = logging.getLogger(__name__)
FALLBACK_SCORE = 50.0
RISK_ENDPOINT = f"{LM_STUDIO_URL}/chat/completions"


def build_signal_dict(
    face_similarity: float,
    ip_address: str,
    ip_changed: bool,
    hour_of_day: int,
    failed_attempts_today: int,
    privilege_requested: bool,
    session_age_minutes: int,
    actions_per_minute: float,
) -> dict:
    """Typed constructor for the risk signal dict.

    Assembles all signals into a plain dict so callers never have to
    remember key names. No logic, no validation — just key assembly.
    """
    return {
        "face_similarity": face_similarity,
        "ip_address": ip_address,
        "ip_changed": ip_changed,
        "hour_of_day": hour_of_day,
        "failed_attempts_today": failed_attempts_today,
        "privilege_requested": privilege_requested,
        "session_age_minutes": session_age_minutes,
        "actions_per_minute": actions_per_minute,
    }


def build_prompt(signals: dict) -> str:
    """Build the full risk-analysis prompt to send to Gemma."""
    return (
        "You are a senior security risk analysis system for a biometric "
        "authentication platform. Analyze the following authentication "
        "signals and produce a single risk score. And be very sensitive to factors most suspicious.\n"
        "\n"
        "SIGNALS:\n"
        f"- face_similarity: {signals['face_similarity']}\n"
        f"- ip_address: {signals['ip_address']}\n"
        f"- ip_changed: {signals['ip_changed']}\n"
        f"- hour_of_day: {signals['hour_of_day']}\n"
        f"- failed_attempts_today: {signals['failed_attempts_today']}\n"
        f"- privilege_requested: {signals['privilege_requested']}\n"
        f"- session_age_minutes: {signals['session_age_minutes']}\n"
        f"- actions_per_minute: {signals['actions_per_minute']}\n"
        "\n"
        "SCORING GUIDANCE (what raises vs. lowers the score):\n"
        "- face_similarity < 0.7 is concerning and raises the score.\n"
        "- ip_changed=True is a red flag and raises the score.\n"
        "- failed_attempts_today >= 2 is suspicious and raises the score.\n"
        "- hour_of_day between 1-5 (AM) is unusual and raises the score.\n"
        "- privilege_requested=True combined with other flags = high risk.\n"
        "- actions_per_minute > 10 suggests scripted access and raises the score.\n"
        "- Strong similarity, stable IP, no failed attempts, and normal hours "
        "lower the score.\n"
        "\n"
        "risk_score MUST be a number from 0 to 100, where 0 = completely safe "
        "and 100 = definite threat.\n"
        "\n"
        "Respond with ONLY a single JSON object — no prose, no markdown, no "
        "explanation, no backticks. Use exactly this format:\n"
        '{"risk_score": <float 0-100>, "reason": "<short string>"}\n'
        "\n"
        "Respond with JSON only, nothing else."
    )


async def query_gemma(prompt: str) -> Optional[dict]:
    """POST the prompt to the LM Studio endpoint and parse the JSON reply.

    Returns the parsed dict, or None on any error (network, JSON, missing keys).
    """
    body = {
        "model": "gemma",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a security risk scoring system. "
                    "You respond only with valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": GEMMA_TEMPERATURE,
        "max_tokens": 150,
    }

    try:
        async with AsyncClient(timeout=30.0) as client:
            response = await client.post(RISK_ENDPOINT, json=body)
            data = response.json()

        content = data["choices"][0]["message"]["content"]

        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        return json.loads(content)
    except Exception as exc:
        logger.warning("query_gemma failed: %s", exc)
        return None


def validate_score(raw: dict) -> float:
    """Extract and validate risk_score from a raw model reply.

    Falls back to FALLBACK_SCORE if the value is missing, non-numeric,
    or outside [0.0, 100.0].
    """
    value = raw.get("risk_score", FALLBACK_SCORE)
    try:
        score = float(value)
    except (TypeError, ValueError):
        logger.warning("validate_score: could not convert %r to float", value)
        return FALLBACK_SCORE

    if not (0.0 <= score <= 100.0):
        logger.warning("validate_score: %s out of range [0, 100]", score)
        return FALLBACK_SCORE

    return score


async def evaluate_risk(signals: dict) -> tuple[float, str]:
    """Evaluate a signal dict and return (risk_score, reason).

    Receives a plain dict only — never raw face images, embeddings, or
    JWT tokens. Falls back to a neutral score if the engine is unavailable.
    """
    prompt = build_prompt(signals)
    result = await query_gemma(prompt)

    if result is None:
        return (FALLBACK_SCORE, "Risk engine unavailable")

    score = validate_score(result)
    reason = str(result.get("reason", "No reason provided"))
    logger.info("Risk score: %.1f | %s", score, reason)
    return (score, reason)
