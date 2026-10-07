import pytest
from fastapi import HTTPException

from fastapi_app.services.appearance_service import theme_css, validate


def test_defaults():
    css = theme_css({})
    assert "family=IBM+Plex+Sans+Arabic" in css and "family=IBM+Plex+Mono" in css
    assert "--ids-ic: #64748b;" in css and "--ids-ic-bad: #dc2626;" in css
    assert css.count("@import") == 1


def test_valid_values_picked_up():
    css = theme_css({"appearance.font_en": "Inter", "appearance.icon_color_ok": "#112233"})
    assert '--ids-ff: "Inter"' in css and "family=Inter:wght@400;500;600;700" in css
    assert "--ids-ic-ok: #112233;" in css


def test_invalid_falls_back():
    css = theme_css({"appearance.font_en": "x;}body{", "appearance.icon_color": "red"})
    assert "body{" not in css and "--ids-ic: #64748b;" in css


def test_case_insensitive_font():
    assert '"Cairo"' in theme_css({"appearance.font_ar": "cAiRo"})


def test_no_import_when_all_system():
    css = theme_css({"appearance.font_en": "System", "appearance.font_ar": "x", "appearance.font_mono": "System mono"})
    assert "family=IBM+Plex+Sans+Arabic" in css  # arabic default is a web font
    css = theme_css({"appearance.font_mono": "System mono"})
    assert "IBM+Plex+Mono" not in css


def test_validate():
    validate("appearance.font_en", "inter")
    validate("appearance.icon_color", "#AbCdEf")
    validate("other.key", "anything")
    for k, v in [("appearance.font_en", "Comic"), ("appearance.icon_color", "#fff"), ("appearance.nope", "x")]:
        with pytest.raises(HTTPException) as e:
            validate(k, v)
        assert e.value.status_code == 400


def test_scroll_ms():
    assert "--ids-glide-ms: 420;" in theme_css({})
    assert "--ids-glide-ms: 600;" in theme_css({"appearance.scroll_ms": "600"})
    assert "--ids-glide-ms: 0;" in theme_css({"appearance.scroll_ms": "0"})
    assert "--ids-glide-ms: 420;" in theme_css({"appearance.scroll_ms": "99999"})
    assert "--ids-glide-ms: 420;" in theme_css({"appearance.scroll_ms": "1;}x{"})
    validate("appearance.scroll_ms", "800")
    for v in ("-1", "2001", "abc", "", "1.5"):
        with pytest.raises(HTTPException):
            validate("appearance.scroll_ms", v)
