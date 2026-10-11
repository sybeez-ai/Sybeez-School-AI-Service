"""Age-appropriate gate for the AI teacher.

Harmful requests get a fixed refusal. The student's words are not repeated.
Benign off-topic chat is redirected to school work. A check answer skips the
off-topic redirect so "2" can be a fraction answer.
"""

import re
from dataclasses import dataclass

REFUSAL = "I can't help with that. Let's get back to a school subject. What would you like to learn?"
SELF_HARM = "I'm glad you said something. Please tell a trusted adult now, or call or text 988."
REDIRECT = "Let's stay on your school work. Tell me a topic from class and I'll teach it on the board."

_SELF_HARM = re.compile(r"\b(kill myself|suicide|self[-\s]?harm|cut myself|end my life)\b", re.IGNORECASE)
_EXPLICIT = re.compile(r"\b(porn|xxx|nude|nudes|naked|sext|erotic)\b", re.IGNORECASE)
_HOWTO_HARM = re.compile(
    r"\b(how (do|to|can) i|how to|steps to|teach me how to)\b.{0,48}\b("
    r"bomb|explosive|weapon|gun|poison|meth|hack|steal|rob|break into)\b",
    re.IGNORECASE,
)
_MAKE_WEAPON = re.compile(r"\b(make|build|assemble) (a |an )?(bomb|explosive|weapon|gun|poison)\b", re.IGNORECASE)
_CRIME = re.compile(r"\bhow to (steal|rob|hack|break into)\b", re.IGNORECASE)
_BIOLOGY = re.compile(r"\b(reproduction|reproductive system|puberty|cell)\b", re.IGNORECASE)
_OFF_TOPIC = re.compile(
    r"\b(fortnite|minecraft|roblox|video games?|netflix|tiktok|celebrity gossip|dating app)\b",
    re.IGNORECASE,
)
_ACADEMIC = re.compile(
    r"\b(teach|explain|why|how does|what is|what's|what was|homework|math|science|history|english|"
    r"fraction|equation|photosynthesis|grammar|essay|chapter|class|lesson|solve|calculate|diagram|"
    r"graph|cell|planet|poem|novel|triangle|algebra|geometry|physics|chemistry|biology|geography|"
    r"spelling|denominator|numerator)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    redirect: bool
    category: str
    student_message: str


def normalise_grade_band(value: str | None) -> str:
    if not value:
        return "elementary"
    text = value.strip().lower()
    if text in {"elementary", "middle", "secondary"}:
        return text
    digits = re.findall(r"\d+", text)
    if digits:
        grade = int(digits[0])
        if grade <= 5:
            return "elementary"
        if grade <= 8:
            return "middle"
        return "secondary"
    if any(word in text for word in ("primary", "kg", "junior")):
        return "elementary"
    if any(word in text for word in ("high", "senior", "secondary")):
        return "secondary"
    return "elementary"


def assess(message: str, *, grade_band: str, awaiting_check: bool) -> SafetyDecision:
    text = message or ""
    band = normalise_grade_band(grade_band)
    if _SELF_HARM.search(text):
        return SafetyDecision(False, False, "self_harm", SELF_HARM)
    if _EXPLICIT.search(text):
        return SafetyDecision(False, False, "sexual", REFUSAL)
    if _HOWTO_HARM.search(text) or _MAKE_WEAPON.search(text) or _CRIME.search(text):
        return SafetyDecision(False, False, "harmful", REFUSAL)
    if re.search(r"\bsexual\b", text, re.IGNORECASE) and (band != "secondary" or not _BIOLOGY.search(text)):
        return SafetyDecision(False, False, "age", REFUSAL)
    if band == "elementary" and re.search(
        r"\b(dating|boyfriend|girlfriend|alcohol|beer|drugs?|weed|vape)\b", text, re.IGNORECASE
    ):
        return SafetyDecision(False, False, "age", REFUSAL)
    if band == "secondary" and re.search(r"\bsex\b", text, re.IGNORECASE) and _BIOLOGY.search(text):
        return SafetyDecision(True, False, "biology", "")
    if not awaiting_check and _OFF_TOPIC.search(text) and not _ACADEMIC.search(text):
        return SafetyDecision(True, True, "off_topic", REDIRECT)
    return SafetyDecision(True, False, "ok", "")
