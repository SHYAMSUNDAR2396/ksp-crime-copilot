"""Kannada bridge: detect -> pivot to English -> reason -> render back.

`protect`/`restore` swap any given token for an opaque placeholder before
translation and back after, so it survives the round trip unmangled. This
module doesn't decide what to protect -- main.py gathers names and crime
numbers from the answer text and result rows and passes them in, because a
crime number or accused name rendered in Kannada is an uncitable answer.
"""
try:
    from .llm import LLMError
except ImportError:
    from llm import LLMError

KANNADA_RANGE = (0x0C80, 0x0CFF)
KANNADA_SHARE_THRESHOLD = 0.15

DEGRADE_NOTE = " (Kannada translation unavailable; answer shown in English.)"


class TranslationError(Exception):
    """Raised when the translation service cannot be reached."""


def detect(text):
    """'kn' if a meaningful share of letters are Kannada, else 'en'."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    low, high = KANNADA_RANGE
    kannada = sum(1 for c in letters if low <= ord(c) <= high)
    return "kn" if kannada / len(letters) >= KANNADA_SHARE_THRESHOLD else "en"


# Delimited by ASCII control characters (never legitimate in police narrative
# text, names, or crime numbers) and zero-padded to a fixed width, so no
# placeholder can ever be a substring of another regardless of token count.
PLACEHOLDER_FORMAT = "\x00{0:04d}\x01"


class PlaceholderCollisionError(Exception):
    """Raised when a placeholder we're about to insert already appears in the
    text. This means the sentinel isn't actually unique -- fail loudly rather
    than silently corrupt a citation."""


def protect(text, tokens):
    """Replace each token with an opaque placeholder. Longest token first."""
    mapping = {}
    for index, token in enumerate(sorted(set(tokens), key=len, reverse=True)):
        if not token or token not in text:
            continue
        placeholder = PLACEHOLDER_FORMAT.format(index)
        if placeholder in text:
            raise PlaceholderCollisionError(
                "Placeholder {0!r} already present in text before substitution".format(placeholder)
            )
        mapping[placeholder] = token
        text = text.replace(token, placeholder)
    return text, mapping


def restore(text, mapping):
    for placeholder, token in mapping.items():
        text = text.replace(placeholder, token)
    return text


class NullTranslator(object):
    """Used when Zia is unavailable, and in tests."""

    def translate(self, text, source, target):
        return text


_LANGUAGE_NAMES = {"kn": "Kannada", "en": "English"}

_TRANSLATE_PROMPT = (
    "Translate the following text from {source} to {target}. "
    "Return only the translated text, with no explanation, quotes, or markdown.\n\n"
    "{text}"
)


class QuickMLTranslator(object):
    """Catalyst QuickML, prompted to translate.

    Catalyst's Zia Services has no translation capability (confirmed against
    docs.catalyst.zoho.com: Zia Services is Face Analytics/OCR/Identity
    Scanner/Image Moderation/Object Recognition/Barcode Scanner/Text
    Analytics only -- translation as a Zia feature exists in separate Zoho
    products like Writer/WorkDrive, not in Catalyst). QuickML is already a
    sanctioned Catalyst service and already wired up for NL->SQL and answer
    composition, so it does double duty here via a plain prompt rather than
    pulling in a non-Catalyst translation API.
    """

    def __init__(self, llm):
        self._llm = llm

    def translate(self, text, source, target):
        prompt = _TRANSLATE_PROMPT.format(
            source=_LANGUAGE_NAMES.get(source, source),
            target=_LANGUAGE_NAMES.get(target, target),
            text=text,
        )
        try:
            return self._llm.complete(prompt).strip()
        except LLMError as err:
            raise TranslationError(str(err))


def to_english(text, translator):
    if detect(text) == "en":
        return text
    return translator.translate(text, "kn", "en")


def to_user_language(text, language, translator, protected_tokens):
    """Render the English answer back, leaving protected tokens untouched."""
    if language == "en":
        return text
    protected, mapping = protect(text, protected_tokens)
    try:
        translated = translator.translate(protected, "en", language)
    except TranslationError:
        return text + DEGRADE_NOTE
    return restore(translated, mapping)
