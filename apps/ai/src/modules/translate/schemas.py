from pydantic import BaseModel, Field

# code -> language name used in the prompt
LANGUAGES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi (Gurmukhi)",
    "ur": "Urdu",
}


class TranslateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=20000)
    languages: list[str] = Field(min_length=1, max_length=len(LANGUAGES))
    source_language: str = Field(default="en", max_length=8)


class TranslatedText(BaseModel):
    title: str
    body: str
    needs_review: bool = False
    review_reason: str | None = None


class TranslateResponse(BaseModel):
    model: str
    translations: dict[str, TranslatedText]
    failed: list[str] = []
