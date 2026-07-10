"""Kannada bridge: detect -> pivot to English -> reason -> render back.

`protect`/`restore` swap any given token for an opaque placeholder before
translation and back after, so it survives the round trip unmangled. This
module doesn't decide what to protect -- main.py gathers names and crime
numbers from the answer text and result rows and passes them in, because a
crime number or accused name rendered in Kannada is an uncitable answer.
"""
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


class ZiaTranslator(object):
    """Catalyst Zia. Confirm the SDK call against docs/catalyst-zcql-findings.md."""

    def __init__(self, app):
        self._zia = app.zia()

    def translate(self, text, source, target):
        try:
            result = self._zia.translate(text, source_language=source, target_language=target)
        except Exception as err:
            raise TranslationError(str(err))
        translated = result.get("translated_text") if isinstance(result, dict) else result
        if not translated:
            raise TranslationError("Zia returned an empty translation")
        return translated


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
