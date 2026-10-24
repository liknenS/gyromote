import pytest

from gyromote import macos

POSTERS = ["post_key", "post_mouse_button", "post_modifiers", "post_flags_reset", "post_click",
           "post_scroll", "post_media_key", "post_pointer_move", "switch_space"]


@pytest.fixture
def posted(monkeypatch):
    """Records every input event gyromote would post, instead of posting it."""
    calls = []
    for name in POSTERS:
        monkeypatch.setattr(macos, name, lambda *a, _n=name: calls.append((_n, *a)))
    monkeypatch.setattr(macos, "request_accessibility", lambda: True)
    return calls
