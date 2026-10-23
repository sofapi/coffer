"""Palette integrity.

These are the guard rails described in theme.py: a new palette that is missing
tokens, fails WCAG AA, or collapses two status colours together fails here
rather than shipping. Contrast is computed, not eyeballed.
"""

import re

import pytest

import theme

REQUIRED_TOKENS = {
    "color-scheme",
    "bg", "surface", "surface-alt", "surface-hover",
    "border", "border-strong",
    "text", "text-muted", "text-subtle", "text-inverse",
    "brand", "brand-hover", "brand-active", "brand-on",
    "brand-soft", "brand-soft-on", "brand-text",
    "focus",
    "success", "success-soft", "success-on",
    "warning", "warning-soft", "warning-on",
    "danger", "danger-soft", "danger-on",
    "info", "info-soft", "info-on",
    "chart-revenue", "chart-cost", "chart-net", "chart-invoiced",
    "chart-grid", "chart-axis",
    "shadow-1", "shadow-2",
}

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

AA_NORMAL = 4.5   # WCAG AA, body text
AA_LARGE = 3.0    # WCAG AA, large/bold text and UI component boundaries


# --------------------------------------------------------------------------
# contrast maths (WCAG 2.1 relative luminance) — kept local so the test suite
# needs no extra dependency
# --------------------------------------------------------------------------

def _channel(value):
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_helper_matches_known_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.02)


# --------------------------------------------------------------------------
# registry shape
# --------------------------------------------------------------------------

def test_ten_palettes_with_unique_ids():
    ids = [p.id for p in theme.PALETTES]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 10
    assert theme.DEFAULT_PALETTE_ID in ids


def test_default_palette_is_the_original_look():
    """Coffer Classic keeps the pre-existing green so upgrades look unchanged."""
    default = theme.get_palette(theme.DEFAULT_PALETTE_ID)
    assert default.id == "coffer-classic"
    assert default.resolved()["brand"] == "#2d5a27"


def test_unknown_or_empty_palette_ids_fall_back_to_the_default():
    for bad in ("", None, "does-not-exist", "../etc/passwd"):
        assert theme.get_palette(bad).id == theme.DEFAULT_PALETTE_ID
    assert theme.is_valid_palette("does-not-exist") is False
    assert theme.is_valid_palette("midnight") is True


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_palette_defines_every_token(palette):
    missing = REQUIRED_TOKENS - set(palette.resolved())
    assert not missing, f"{palette.id} is missing {sorted(missing)}"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_colour_tokens_are_plain_hex(palette):
    resolved = palette.resolved()
    for key, value in resolved.items():
        if key.startswith("shadow") or key == "color-scheme":
            continue
        assert HEX.match(value), f"{palette.id}.{key} = {value!r} is not a 6-digit hex"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_palette_has_a_name_and_a_description(palette):
    """Both are user-facing on the settings page."""
    assert palette.name and palette.name[0].isupper()
    assert palette.description.endswith(".")


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_mode_is_declared(palette):
    assert palette.mode in ("light", "dark")
    assert palette.resolved()["color-scheme"] == palette.mode


# --------------------------------------------------------------------------
# accessibility
# --------------------------------------------------------------------------

@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_body_text_meets_aa_on_both_grounds(palette):
    t = palette.resolved()
    for ground in ("bg", "surface", "surface-alt", "surface-hover"):
        ratio = contrast(t["text"], t[ground])
        assert ratio >= AA_NORMAL, f"{palette.id}: text on {ground} is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_secondary_text_meets_aa_on_surfaces(palette):
    t = palette.resolved()
    for key in ("text-muted", "text-subtle"):
        for ground in ("bg", "surface", "surface-alt"):
            ratio = contrast(t[key], t[ground])
            assert ratio >= AA_NORMAL, f"{palette.id}: {key} on {ground} is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_brand_surfaces_are_legible(palette):
    t = palette.resolved()
    # Nav bar and primary buttons.
    assert contrast(t["brand-on"], t["brand"]) >= AA_NORMAL, palette.id
    assert contrast(t["brand-on"], t["brand-hover"]) >= AA_LARGE, palette.id
    assert contrast(t["brand-on"], t["brand-active"]) >= AA_LARGE, palette.id
    # Tinted brand areas (total rows, tags).
    assert contrast(t["brand-soft-on"], t["brand-soft"]) >= AA_NORMAL, palette.id
    # Links and headings sit on the page ground.
    assert contrast(t["brand-text"], t["bg"]) >= AA_NORMAL, palette.id
    assert contrast(t["brand-text"], t["surface"]) >= AA_NORMAL, palette.id


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
@pytest.mark.parametrize("status", ["success", "warning", "danger", "info"])
def test_status_badges_are_legible(palette, status):
    t = palette.resolved()
    ratio = contrast(t[f"{status}-on"], t[f"{status}-soft"])
    assert ratio >= AA_NORMAL, f"{palette.id}: {status} badge is {ratio:.2f}:1"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
@pytest.mark.parametrize("status", ["success", "warning", "danger", "info"])
def test_status_fills_carry_readable_labels(palette, status):
    """Solid status buttons put --text-inverse-ish ink on the status colour."""
    t = palette.resolved()
    best = max(contrast(t[status], t["text-inverse"]), contrast(t[status], t["text"]))
    assert best >= AA_NORMAL, f"{palette.id}: no readable ink for a solid {status} button"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_borders_and_focus_ring_are_visible(palette):
    t = palette.resolved()
    assert contrast(t["border-strong"], t["surface"]) >= 1.6, palette.id
    assert contrast(t["focus"], t["surface"]) >= AA_LARGE, palette.id
    assert contrast(t["focus"], t["bg"]) >= AA_LARGE, palette.id


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_chart_series_are_visible_on_the_chart_surface(palette):
    t = palette.resolved()
    for key in ("chart-revenue", "chart-cost", "chart-net", "chart-invoiced"):
        ratio = contrast(t[key], t["surface"])
        assert ratio >= AA_LARGE, f"{palette.id}.{key} is {ratio:.2f}:1 on the card"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_status_colours_stay_distinguishable_from_each_other(palette):
    """success / warning / danger / info must never collapse into one another —
    'paid' and 'overdue' looking alike is a financial reporting bug."""
    t = palette.resolved()
    keys = ["success", "warning", "danger", "info"]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            ca, cb = t[a], t[b]
            assert ca != cb, f"{palette.id}: {a} and {b} are the same colour"
            # Distinguishable by hue or lightness: allow either a clear
            # luminance step or a clear channel difference.
            ra = tuple(int(ca.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
            rb = tuple(int(cb.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
            spread = max(abs(x - y) for x, y in zip(ra, rb, strict=True))
            assert spread >= 40, f"{palette.id}: {a} vs {b} differ by only {spread}"


@pytest.mark.parametrize("palette", theme.PALETTES, ids=lambda p: p.id)
def test_chart_series_are_mutually_distinct(palette):
    t = palette.resolved()
    series = [t["chart-revenue"], t["chart-cost"], t["chart-net"], t["chart-invoiced"]]
    assert len(set(series)) == 4, f"{palette.id} reuses a chart colour"


# --------------------------------------------------------------------------
# generated CSS
# --------------------------------------------------------------------------

def test_inline_block_defines_the_chosen_palette_only():
    block = theme.palette_style_block(theme.get_palette("midnight"))
    assert block.startswith(":root{")
    assert "--bg:#0e1524" in block
    assert "coffer-classic" not in block


def test_generated_css_covers_every_palette():
    css = theme.build_palettes_css()
    for p in theme.PALETTES:
        assert f'html[data-palette="{p.id}"]' in css
        for token, value in p.resolved().items():
            assert f"--{token}:{value};" in css


def test_generated_css_has_a_root_fallback():
    """An unknown data-palette value still renders in the default colours."""
    css = theme.build_palettes_css()
    assert css.count(":root{") == 1
    default = theme.get_palette(theme.DEFAULT_PALETTE_ID).resolved()
    root_block = css.split(":root{", 1)[1].split("}", 1)[0]
    assert f"--brand:{default['brand']};" in root_block
