from functions.crime_query.mo_normalize import extract_mo_concepts, normalize_narrative, split_sentences


def test_normalization_preserves_both_scripts():
    value = normalize_narrative("  ಬಾಗಿಲು ಮುರಿದು  stolen phone. ")
    assert "ಬಾಗಿಲು ಮುರಿದು" in value.normalized
    assert "stolen phone" in value.normalized
    assert value.normalization_version == "mo-normalize-v1"
    assert value.language_flags == ("kn", "en")


def test_sentence_split_supports_kannada_danda():
    assert split_sentences("ಮನೆಗೆ ಪ್ರವೇಶಿಸಿದನು। Phone stolen.") == ["ಮನೆಗೆ ಪ್ರವೇಶಿಸಿದನು।", "Phone stolen."]


def test_concepts_exclude_sensitive_metadata():
    assert "caste" not in extract_mo_concepts("caste mentioned")
    assert "religion" not in extract_mo_concepts("religion mentioned")


def test_concepts_are_versioned_and_deterministic():
    value = normalize_narrative("ಬೀಗ ಮುರಿದು ರಾತ್ರಿ ಬೈಕ್ ತೆಗೆದುಕೊಂಡರು")
    assert value.concepts == ("entry_method", "transport", "timing")
