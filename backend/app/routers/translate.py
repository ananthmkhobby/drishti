"""
POST /v1/translate — batch-translate educational content via GPT-4o-mini.
Accepts a list of strings + target language; returns translated strings in the
same order.  Returns the originals unchanged when target == "english".
"""
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["translate"])

SUPPORTED = {"hindi", "kannada", "telugu", "tamil", "english"}
LANG_DISPLAY = {
    "hindi":   "Hindi (हिन्दी)",
    "kannada": "Kannada (ಕನ್ನಡ)",
    "telugu":  "Telugu (తెలుగు)",
    "tamil":   "Tamil (தமிழ்)",
    "english": "English",
}


class TranslateRequest(BaseModel):
    texts: list[str]
    target_language: str   # "hindi" | "kannada" | "telugu" | "tamil" | "english"


class TranslateResponse(BaseModel):
    translations: list[str]
    target_language: str


@router.post("/translate", response_model=TranslateResponse)
async def translate_texts(body: TranslateRequest) -> TranslateResponse:
    lang = body.target_language.lower().strip()
    if lang not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")

    # Return originals for English — no API call needed
    if lang == "english":
        return TranslateResponse(translations=body.texts, target_language=lang)

    settings = get_settings()
    if not settings.openai_api_key:
        # Fallback: return originals when OpenAI not configured
        logger.warning("translate called but OPENAI_API_KEY is not set — returning originals")
        return TranslateResponse(translations=body.texts, target_language=lang)

    # Filter out empty strings but preserve positions
    indexed = [(i, t) for i, t in enumerate(body.texts) if t and t.strip()]
    if not indexed:
        return TranslateResponse(translations=body.texts, target_language=lang)

    import openai   # lazy import — not in startup path

    lang_name = LANG_DISPLAY[lang]
    numbered = "\n".join(f"{i+1}. {t}" for i, (_, t) in enumerate(indexed))

    prompt = (
        f"Translate the following educational content into {lang_name}.\n"
        "Return ONLY a JSON object with key \"translations\" containing an array of translated strings "
        "in the same order. Keep mathematical expressions, chemical formulas, and proper nouns unchanged. "
        "Do not add explanations or extra text.\n\n"
        f"{numbered}"
    )

    try:
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model_mini,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=4096,
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        translated = data.get("translations", [t for _, t in indexed])
    except Exception as exc:
        logger.error("Translation API error: %s", exc)
        # Graceful fallback — return originals
        translated = [t for _, t in indexed]

    # Rebuild full list, keeping empty strings in their original positions
    result = list(body.texts)
    for pos, (orig_idx, _) in enumerate(indexed):
        if pos < len(translated):
            result[orig_idx] = translated[pos]

    return TranslateResponse(translations=result, target_language=lang)
