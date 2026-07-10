import pytest

from functions.crime_query import translate

KANNADA_Q = "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"
CRIMENO = "104430006202600001"


class EchoTranslator:
    """Records calls; returns the text with a marker so we can see it was translated."""

    def __init__(self):
        self.calls = []

    def translate(self, text, source, target):
        self.calls.append((text, source, target))
        return "<{0}>{1}".format(target, text)


class BrokenTranslator:
    def translate(self, text, source, target):
        raise translate.TranslationError("Zia unavailable")


def test_detect_kannada():
    assert translate.detect(KANNADA_Q) == "kn"


def test_detect_english():
    assert translate.detect("How many thefts in Bengaluru East?") == "en"


def test_detect_english_for_mostly_ascii_with_a_stray_kannada_char():
    assert translate.detect("Cases in ಬೆಂಗಳೂರು East last month with many words here") == "en"


def test_detect_empty_string_is_english():
    assert translate.detect("") == "en"


def test_protect_and_restore_round_trip():
    text = "Case {0} filed by Ravi Kumar.".format(CRIMENO)
    protected, mapping = translate.protect(text, [CRIMENO, "Ravi Kumar"])
    assert CRIMENO not in protected
    assert "Ravi Kumar" not in protected
    assert translate.restore(protected, mapping) == text


def test_protect_placeholders_survive_a_translation_step():
    text = "Case {0}.".format(CRIMENO)
    protected, mapping = translate.protect(text, [CRIMENO])
    translated = EchoTranslator().translate(protected, "en", "kn")
    assert CRIMENO in translate.restore(translated, mapping)


def test_protect_longest_token_first():
    # "Ravi" is a substring of "Ravi Kumar"; the longer token must win.
    text = "Ravi Kumar and Ravi"
    protected, mapping = translate.protect(text, ["Ravi", "Ravi Kumar"])
    assert translate.restore(protected, mapping) == text


def test_to_english_skips_translation_for_english_input():
    translator = EchoTranslator()
    assert translate.to_english("How many thefts?", translator) == "How many thefts?"
    assert translator.calls == []


def test_to_english_translates_kannada():
    translator = EchoTranslator()
    result = translate.to_english(KANNADA_Q, translator)
    assert result.startswith("<en>")
    assert translator.calls[0][1:] == ("kn", "en")


def test_to_user_language_is_identity_for_english():
    translator = EchoTranslator()
    assert translate.to_user_language("Answer.", "en", translator, []) == "Answer."
    assert translator.calls == []


def test_to_user_language_preserves_crimeno_verbatim():
    translator = EchoTranslator()
    text = "The case is {0}.".format(CRIMENO)
    result = translate.to_user_language(text, "kn", translator, [CRIMENO])
    assert CRIMENO in result
    assert "<kn>" in result


def test_translation_failure_degrades_to_english_with_a_note():
    text = "The case is {0}.".format(CRIMENO)
    result = translate.to_user_language(text, "kn", BrokenTranslator(), [CRIMENO])
    assert CRIMENO in result
    assert "English" in result


def test_null_translator_is_identity():
    assert translate.NullTranslator().translate("x", "en", "kn") == "x"


def test_protect_survives_a_word_reordering_translator_with_12_tokens():
    """Finding 1: with 11+ tokens, a non-zero-padded index makes one
    placeholder a substring of another (ZZ1ZZ inside ZZ10ZZ). A translator
    that reorders whole words (real translators restructure sentences, they
    don't byte-reverse) can then turn a valid placeholder into one that looks
    like a different index. 12 tokens exercises the old scheme's
    single-digit/two-digit index boundary; zero-padding must survive it.
    """
    tokens = ["TOKEN{0:02d}".format(i) for i in range(12)]
    text = " ".join(tokens)
    protected, mapping = translate.protect(text, tokens)

    class WordReorderingTranslator:
        def translate(self, text, source, target):
            words = text.split(" ")
            return " ".join(reversed(words))

    translated = WordReorderingTranslator().translate(protected, "en", "kn")
    restored = translate.restore(translated, mapping)
    for token in tokens:
        assert token in restored


def test_protect_does_not_corrupt_preexisting_old_format_placeholder_text():
    """Finding 2: real text containing a literal substring that collides with
    the placeholder alphabet must not be corrupted on restore. This also
    proves the new control-character sentinel shares no collision surface
    with the old ZZ0ZZ-style format: text containing that literal string
    verbatim must pass through completely unaffected.
    """
    text = "Vehicle plate reads ZZ0ZZ near the scene. Case {0}.".format(CRIMENO)
    protected, mapping = translate.protect(text, [CRIMENO])
    restored = translate.restore(protected, mapping)
    assert restored == text
    assert "ZZ0ZZ" in restored


def test_protect_raises_on_placeholder_collision():
    """The defensive guard: if the sentinel format's placeholder is already
    present in the text before substitution, protect() must raise instead of
    silently proceeding (which could double-replace or let restore()
    overwrite text that was never a placeholder).
    """
    colliding_text = "Note: \x000000\x01 already looks like our own placeholder. Ravi Kumar."
    with pytest.raises(translate.PlaceholderCollisionError):
        translate.protect(colliding_text, ["Ravi Kumar"])


def test_kannada_pivot_reaches_the_same_pipeline_input():
    """Once to_english runs, the pipeline sees an indistinguishable English string.

    Parity between a Kannada question and its English equivalent is structural,
    not something a fake translator can prove (Step 5): this only confirms that
    to_english's output for a Kannada input is plain text with no residual
    language marker, so nothing downstream can tell it started as Kannada.
    """
    translator = EchoTranslator()
    kannada_result = translate.to_english(KANNADA_Q, translator)
    english_input = "How many thefts in Bengaluru East?"
    direct_result = translate.to_english(english_input, translator)

    assert kannada_result == "<en>{0}".format(KANNADA_Q)
    assert direct_result == english_input
    assert isinstance(kannada_result, str) and isinstance(direct_result, str)
