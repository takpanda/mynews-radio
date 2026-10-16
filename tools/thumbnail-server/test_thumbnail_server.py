import importlib.util
from pathlib import Path

from PIL import Image


SERVER_PATH = Path(__file__).with_name("thumbnail_server.py")
SPEC = importlib.util.spec_from_file_location("thumbnail_server", SERVER_PATH)
thumbnail_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(thumbnail_server)


class _Font:
    def getlength(self, text):
        return len(text) * 10

    def getbbox(self, text):
        return (0, 0, self.getlength(text), 20)


class _DrawSpy:
    def __init__(self):
        self.texts = []
        self.banners = []

    def text(self, position, text, **kwargs):
        self.texts.append((position, text, kwargs))

    def rounded_rectangle(self, bounds, **kwargs):
        self.banners.append((bounds, kwargs))


def _compose(monkeypatch, headline, highlight):
    draw = _DrawSpy()
    monkeypatch.setattr(thumbnail_server, "F", lambda *_args, **_kwargs: _Font())
    monkeypatch.setattr(thumbnail_server.ImageDraw, "Draw", lambda *_args: draw)

    image = thumbnail_server.compose(Image.new("RGB", (960, 540)), headline, highlight)
    return image, draw


def _headline_texts(draw):
    texts = [text for _position, text, _kwargs in draw.texts if text != thumbnail_server.DEFAULT_BRAND]
    return list(dict.fromkeys(texts))


def test_compose_draws_highlight_at_start_when_top_line_is_empty(monkeypatch):
    image, draw = _compose(monkeypatch, "円安ショック！食費が激増", "円安")

    assert image.size == (960, 540)
    assert _headline_texts(draw) == ["円安ショック！食費が激増"]
    assert len(draw.banners) == 1


def test_compose_keeps_two_lines_for_middle_and_trailing_highlights(monkeypatch):
    for headline, highlight, expected_lines in (
        ("物価高の影響", "高", ["物価", "高の影響"]),
        ("物価への影響", "響", ["物価への影", "響"]),
    ):
        _image, draw = _compose(monkeypatch, headline, highlight)

        assert _headline_texts(draw) == expected_lines
        assert len(draw.banners) == 1


def test_compose_centers_single_line_without_highlight(monkeypatch):
    _image, draw = _compose(monkeypatch, "音声合成が使える", "")

    headline_calls = [call for call in draw.texts if call[1] != thumbnail_server.DEFAULT_BRAND]
    assert _headline_texts(draw) == ["音声合成が使える"]
    assert headline_calls[1][0][1] == (540 - 20) // 2
    assert draw.banners == []
