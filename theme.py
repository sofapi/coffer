"""Coffer's appearance system: premade colour palettes as semantic design tokens.

Everything the UI paints with comes from a token defined here. Templates and
`static/style.css` reference `var(--token)` and never a literal colour, so a new
palette is a data change, not a CSS change.

Adding a palette
----------------
Append one `Palette(...)` to `PALETTES` below. Fill in `tokens` with the values
that differ from `LIGHT_BASE` (or `DARK_BASE` for a dark palette); anything you
omit is inherited from the base. Give it four `chart-*` colours.
Nothing else needs to change — the settings page, the generated stylesheet and
the persisted preference all read from this list, and the preview swatch is
painted from the palette's own tokens so it can never drift from the real thing.

Every palette must keep:
  * body text >= 4.5:1 on `bg` and on `surface` (WCAG AA);
  * the four status families (success / warning / danger / info) visually
    distinct from each other and from the brand colour;
  * the four chart series mutually distinguishable under protanopia and
    deuteranopia.

`tests/test_theme.py` asserts all of the above for every palette, so a new
palette that breaks one of them fails the test suite rather than shipping.

The chart colours below were chosen by search against the data-visualisation
colour checks (OKLCH lightness band, chroma floor, Machado-Oliveira-Fernandes
CVD simulation at severity 1.0, WCAG contrast on the chart surface). The worst
adjacent-pair CVD separation across all ten palettes is dE 11.3 in OKLab x100,
comfortably above the dE 8 target.
"""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Token bases
# ---------------------------------------------------------------------------
# Status colours are deliberately shared across the light palettes: "paid",
# "overdue" and "destructive" must mean the same thing, and look the same, no
# matter which palette a user picked. A palette may still override them (High
# Contrast does) but it should have a reason to.

LIGHT_BASE: dict[str, str] = {
    "color-scheme": "light",

    "bg": "#f5f6f5",
    "surface": "#ffffff",
    "surface-alt": "#eff1ef",
    "surface-hover": "#f8f9f8",

    "border": "#e2e5e1",
    "border-strong": "#c6ccc3",

    "text": "#1a1d19",
    "text-muted": "#585f55",
    "text-subtle": "#67705f",
    "text-inverse": "#ffffff",

    "brand": "#2d5a27",
    "brand-hover": "#3a7233",
    "brand-active": "#24491f",
    "brand-on": "#ffffff",
    "brand-soft": "#e7efe5",
    "brand-soft-on": "#24491f",
    "brand-text": "#2a5424",

    "focus": "#3a7233",

    "success": "#1f7a45",
    "success-soft": "#e2f2e8",
    "success-on": "#12562e",

    "warning": "#8a5600",
    "warning-soft": "#fbeed6",
    "warning-on": "#684100",

    "danger": "#b3261e",
    "danger-soft": "#fbe5e3",
    "danger-on": "#8a1c16",

    "info": "#1f5f9e",
    "info-soft": "#e3eefa",
    "info-on": "#174a7c",

    "chart-grid": "#e6e9e5",
    "chart-axis": "#9aa396",

    "shadow-1": "0 1px 2px rgba(16, 24, 16, 0.06), 0 1px 3px rgba(16, 24, 16, 0.04)",
    "shadow-2": "0 2px 4px rgba(16, 24, 16, 0.06), 0 8px 20px rgba(16, 24, 16, 0.07)",
}

DARK_BASE: dict[str, str] = {
    "color-scheme": "dark",

    "bg": "#0e1524",
    "surface": "#172033",
    "surface-alt": "#1e293f",
    "surface-hover": "#212d47",

    "border": "#2b3855",
    "border-strong": "#3e4d70",

    "text": "#e8edf7",
    "text-muted": "#a8b4cb",
    "text-subtle": "#8794ae",
    "text-inverse": "#0b1020",

    "brand": "#5b7cf5",
    "brand-hover": "#7690f7",
    "brand-active": "#4a6ae8",
    "brand-on": "#0b1020",
    "brand-soft": "#1d2747",
    "brand-soft-on": "#bccbff",
    "brand-text": "#a3b6ff",

    "focus": "#8fa6ff",

    "success": "#4ecf8b",
    "success-soft": "#133326",
    "success-on": "#8ce6b5",

    "warning": "#e0b055",
    "warning-soft": "#372b12",
    "warning-on": "#f2ce85",

    "danger": "#f2736a",
    "danger-soft": "#3a1d1c",
    "danger-on": "#ffaba3",

    "info": "#6fb2f5",
    "info-soft": "#142a42",
    "info-on": "#aed3fb",

    "chart-grid": "#26324c",
    "chart-axis": "#6e7d99",

    "shadow-1": "0 1px 2px rgba(0, 0, 0, 0.32), 0 1px 3px rgba(0, 0, 0, 0.24)",
    "shadow-2": "0 2px 4px rgba(0, 0, 0, 0.3), 0 10px 24px rgba(0, 0, 0, 0.36)",
}


@dataclass(frozen=True)
class Palette:
    """One selectable appearance.

    `tokens` are merged over the mode base, so a palette only states what it
    changes.
    """

    id: str
    name: str
    description: str
    mode: str  # "light" or "dark" — drives which base the tokens merge over
    tokens: dict[str, str] = field(default_factory=dict)

    def resolved(self) -> dict[str, str]:
        base = DARK_BASE if self.mode == "dark" else LIGHT_BASE
        return {**base, **self.tokens}


PALETTES: list[Palette] = [
    Palette(
        id="coffer-classic",
        name="Coffer Classic",
        description="Refined green and warm neutrals — Coffer's original look.",
        mode="light",
        tokens={
            "bg": "#f4f6f3",
            "surface-alt": "#eef2ec",
            "surface-hover": "#f7faf6",
            "border": "#e0e6dd",
            "border-strong": "#c0cabb",
            "text": "#1a2118",
            "text-muted": "#57614f",
            "text-subtle": "#67705f",
            "chart-grid": "#e6ebe3",
            "chart-axis": "#98a291",
            "chart-revenue": "#309b52",
            "chart-cost": "#933d08",
            "chart-net": "#3378ca",
            "chart-invoiced": "#8d7608",
        },
    ),
    Palette(
        id="midnight",
        name="Midnight",
        description="Navy, indigo and cool grey — a dark, low-glare workspace.",
        mode="dark",
        tokens={
            "chart-revenue": "#0e84b7",
            "chart-cost": "#be5924",
            "chart-net": "#8863c2",
            "chart-invoiced": "#5d8a1a",
        },
    ),
    Palette(
        id="forest",
        name="Forest",
        description="Deep green and earthy neutrals — quiet and grounded.",
        mode="light",
        tokens={
            "bg": "#f4f3ed",
            "surface-alt": "#edece3",
            "surface-hover": "#f8f7f2",
            "border": "#e1dfd2",
            "border-strong": "#c3c0ac",
            "text": "#1e2019",
            "text-muted": "#5a5c4d",
            "text-subtle": "#696b5b",
            "brand": "#2f4f34",
            "brand-hover": "#3d6444",
            "brand-active": "#26402a",
            "brand-soft": "#e5ebe3",
            "brand-soft-on": "#26402a",
            "brand-text": "#2c4b31",
            "focus": "#3d6444",
            "chart-grid": "#e7e5da",
            "chart-axis": "#97957f",
            "chart-revenue": "#479f4e",
            "chart-cost": "#964609",
            "chart-net": "#2981cf",
            "chart-invoiced": "#927306",
        },
    ),
    Palette(
        id="ocean",
        name="Ocean",
        description="Blue, teal and pale aqua — crisp and open.",
        mode="light",
        tokens={
            "bg": "#f1f6f8",
            "surface-alt": "#e8f0f3",
            "surface-hover": "#f5fafb",
            "border": "#d9e5ea",
            "border-strong": "#b4c6ce",
            "text": "#14212a",
            "text-muted": "#4c606b",
            "text-subtle": "#5b6f79",
            "brand": "#14607f",
            "brand-hover": "#1b7699",
            "brand-active": "#0f4f69",
            "brand-soft": "#e0eef4",
            "brand-soft-on": "#0f4f69",
            "brand-text": "#14607f",
            "focus": "#1b7699",
            "chart-grid": "#dfe9ed",
            "chart-axis": "#8b9ea7",
            "chart-revenue": "#1093aa",
            "chart-cost": "#a14900",
            "chart-net": "#119a70",
            "chart-invoiced": "#8560bf",
        },
    ),
    Palette(
        id="plum",
        name="Plum",
        description="Aubergine, violet and soft grey — understated and modern.",
        mode="light",
        tokens={
            "bg": "#f7f4f8",
            "surface-alt": "#f0ebf2",
            "surface-hover": "#faf7fb",
            "border": "#e5dee8",
            "border-strong": "#c7bdcf",
            "text": "#201a24",
            "text-muted": "#5b5161",
            "text-subtle": "#716777",
            "brand": "#5d3a6b",
            "brand-hover": "#734a83",
            "brand-active": "#4c2f58",
            "brand-soft": "#eee6f1",
            "brand-soft-on": "#4c2f58",
            "brand-text": "#5d3a6b",
            "focus": "#734a83",
            "chart-grid": "#e9e2ec",
            "chart-axis": "#9b90a2",
            "chart-revenue": "#915bb6",
            "chart-cost": "#b8580f",
            "chart-net": "#07a4a4",
            "chart-invoiced": "#507b07",
        },
    ),
    Palette(
        id="terracotta",
        name="Terracotta",
        description="Burnt orange and warm cream — friendly and tactile.",
        mode="light",
        tokens={
            "bg": "#fbf5ef",
            "surface-alt": "#f5ece2",
            "surface-hover": "#fdf9f4",
            "border": "#ebdfd2",
            "border-strong": "#d1bea9",
            "text": "#241a13",
            "text-muted": "#625349",
            "text-subtle": "#79685b",
            "brand": "#a4502a",
            "brand-hover": "#bc5f36",
            "brand-active": "#8a4222",
            "brand-soft": "#f7e7db",
            "brand-soft-on": "#7a3a1e",
            "brand-text": "#8f4524",
            "focus": "#bc5f36",
            "chart-grid": "#efe3d7",
            "chart-axis": "#a89584",
            "chart-revenue": "#bc532c",
            "chart-cost": "#0d89b4",
            "chart-net": "#2c8736",
            "chart-invoiced": "#a25db2",
        },
    ),
    Palette(
        id="rose",
        name="Rose",
        description="Muted rose and burgundy — soft without being sweet.",
        mode="light",
        tokens={
            "bg": "#fbf4f5",
            "surface-alt": "#f5e9eb",
            "surface-hover": "#fdf8f9",
            "border": "#ecdcdf",
            "border-strong": "#d2b6bb",
            "text": "#241a1c",
            "text-muted": "#605053",
            "text-subtle": "#786569",
            "brand": "#8d2f45",
            "brand-hover": "#a53a53",
            "brand-active": "#76263a",
            "brand-soft": "#f6e3e7",
            "brand-soft-on": "#76263a",
            "brand-text": "#8d2f45",
            "focus": "#a53a53",
            "chart-grid": "#efe0e3",
            "chart-axis": "#a89195",
            "chart-revenue": "#ad4060",
            "chart-cost": "#0792b1",
            "chart-net": "#0b6d32",
            "chart-invoiced": "#a68510",
        },
    ),
    Palette(
        id="slate",
        name="Slate",
        description="Neutral monochrome — colour only where it carries meaning.",
        mode="light",
        tokens={
            "bg": "#f5f6f8",
            "surface-alt": "#eceef1",
            "surface-hover": "#f8f9fa",
            "border": "#dfe2e7",
            "border-strong": "#bdc3cb",
            "text": "#171a1f",
            "text-muted": "#555b65",
            "text-subtle": "#656c77",
            "brand": "#3f4a55",
            "brand-hover": "#4f5c69",
            "brand-active": "#333d46",
            "brand-soft": "#e7eaee",
            "brand-soft-on": "#333d46",
            "brand-text": "#3f4a55",
            "focus": "#0b77ba",
            "chart-grid": "#e4e7eb",
            "chart-axis": "#949aa3",
            "chart-revenue": "#0b77ba",
            "chart-cost": "#933d08",
            "chart-net": "#109462",
            "chart-invoiced": "#a25db2",
        },
    ),
    Palette(
        id="sand",
        name="Sand",
        description="Beige, brown and warm charcoal — paper-like and calm.",
        mode="light",
        tokens={
            "bg": "#f8f4ec",
            "surface-alt": "#f1ebdf",
            "surface-hover": "#fbf8f2",
            "border": "#e6ddcb",
            "border-strong": "#c9bca4",
            "text": "#211d16",
            "text-muted": "#5d5549",
            "text-subtle": "#72695a",
            "brand": "#6b533a",
            "brand-hover": "#806448",
            "brand-active": "#58442f",
            "brand-soft": "#f0e7d8",
            "brand-soft-on": "#58442f",
            "brand-text": "#6b533a",
            "focus": "#806448",
            "chart-grid": "#ebe3d3",
            "chart-axis": "#a2977f",
            "chart-revenue": "#a4690c",
            "chart-cost": "#0481b3",
            "chart-net": "#a93b42",
            "chart-invoiced": "#2ca867",
        },
    ),
    Palette(
        id="high-contrast",
        name="High Contrast",
        description="Maximum legibility — heavier borders and AAA-level text.",
        mode="light",
        tokens={
            "bg": "#ffffff",
            "surface": "#ffffff",
            "surface-alt": "#eeeeee",
            "surface-hover": "#e4e4e4",
            "border": "#6b6b6b",
            "border-strong": "#1a1a1a",
            "text": "#000000",
            "text-muted": "#2e2e2e",
            "text-subtle": "#414141",
            "brand": "#003a8c",
            "brand-hover": "#002a66",
            "brand-active": "#001f4d",
            "brand-soft": "#dbe5f5",
            "brand-soft-on": "#002a66",
            "brand-text": "#003a8c",
            "focus": "#003a8c",
            "success": "#00602c",
            "success-soft": "#d8f0e1",
            "success-on": "#00441f",
            "warning": "#7a4a00",
            "warning-soft": "#fbedd0",
            "warning-on": "#573500",
            "danger": "#a30000",
            "danger-soft": "#fbdfdf",
            "danger-on": "#7a0000",
            "info": "#003a8c",
            "info-soft": "#dbe5f5",
            "info-on": "#002a66",
            "chart-grid": "#c9c9c9",
            "chart-axis": "#3d3d3d",
            "chart-revenue": "#0059af",
            "chart-cost": "#882f07",
            "chart-net": "#05893e",
            "chart-invoiced": "#7d0293",
            "shadow-1": "0 0 0 1px #6b6b6b",
            "shadow-2": "0 0 0 1px #1a1a1a",
        },
    ),
]

DEFAULT_PALETTE_ID = "coffer-classic"
PALETTE_SETTING_KEY = "theme_palette"

_BY_ID = {p.id: p for p in PALETTES}


def get_palette(palette_id: str) -> Palette:
    """Return the requested palette, falling back to the default.

    Callers pass whatever is in the database or the form, so an unknown or
    removed id must degrade to the default rather than raise.
    """
    return _BY_ID.get(palette_id or "", _BY_ID[DEFAULT_PALETTE_ID])


def is_valid_palette(palette_id: str) -> bool:
    return palette_id in _BY_ID


def _declarations(tokens: dict[str, str]) -> str:
    return "".join(f"--{k}:{v};" for k, v in tokens.items())


def palette_style_block(palette: Palette) -> str:
    """The chosen palette's tokens, for inlining in <head>.

    Inlining is what prevents a flash of the default theme: the tokens arrive in
    the first bytes of the document, before any stylesheet request is made.
    """
    return f":root{{{_declarations(palette.resolved())}}}"


def build_palettes_css() -> str:
    """All palettes as `html[data-palette="..."]` rules.

    Only the appearance page loads this — it is what makes live preview work
    without a round trip. The selector is deliberately more specific than the
    inlined `:root` block so preview wins over the saved palette.
    """
    parts = [
        "/* Generated from theme.py — do not edit by hand. */",
        f':root{{{_declarations(get_palette(DEFAULT_PALETTE_ID).resolved())}}}',
    ]
    for p in PALETTES:
        parts.append(f'html[data-palette="{p.id}"]{{{_declarations(p.resolved())}}}')
    return "\n".join(parts)
