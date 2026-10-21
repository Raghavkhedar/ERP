from .templatetags.chat_tags import avatar_hue


def test_avatar_hue_is_stable_and_in_range():
    assert avatar_hue("alice") == avatar_hue("alice")
    assert 0 <= avatar_hue("alice") < 360


def test_avatar_hue_differs_between_names():
    assert avatar_hue("alice") != avatar_hue("bob")
