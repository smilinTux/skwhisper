"""Role and self words must not become sacred name keys (SKMEM-P1-20)."""

import pytest

from skwhisper.sensitive_names import mentions, name_keys, sensitive_name_keys


@pytest.mark.parametrize(
    "name",
    [
        "the user",
        "The Assistant",
        "Chef",
        "Queen Lumina",
        "an agent",
        "King Opus",
        "Claude",
    ],
)
def test_role_and_self_names_yield_no_keys(name):
    assert name_keys([name]) == set()


def test_stoplisted_words_do_not_hide_ordinary_topics():
    keys = name_keys(["the user", "Chef", "Queen Lumina", "the assistant"])
    assert not mentions("the weekly plan for chef and the agent", keys)


def test_homoglyph_and_case_variants_are_dropped():
    # Cyrillic te look-alikes and fullwidth letters fold to the plain word
    assert (
        name_keys(["\u0442he", "\uff34\uff28\uff25", "CHEF", "Qu\u0435\u0435n"])
        == set()
    )


def test_real_name_keeps_both_keys_and_loses_only_stopwords():
    assert name_keys(["Quillan Marrowby"]) == {"quillan", "marrowby"}
    assert name_keys(["the Quillan Marrowby"]) == {"quillan", "marrowby"}


def test_relation_words_are_still_keys():
    assert {"wife", "late", "mother"} <= name_keys(["the late wife", "mother"])


def test_known_person_the_user_hides_nothing_via_sensitive_name_keys():
    keys = sensitive_name_keys(["quillan-marrowby"], ["the user"], ["Chef", "Quillan"])
    assert keys == {"quillan"}
