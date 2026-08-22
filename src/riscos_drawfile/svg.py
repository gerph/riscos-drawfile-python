"""Renders a decoded RISC OS DrawFile (via drawfile.py's structural
decoder) as a standalone SVG document.

Ported from riscos-impression's own output/html_base.py and
output/extract.py (`_drawfile_svg_object` and everything under it,
plus extract.py's own `_drawfile_native_svg`/`_drawfile_effective_bounds`
-- the "at the drawing's own native size, no picture-frame placement"
variant, since that's the only one meaningful outside a document that
places DrawFile pictures inside its own frames). Deliberately
self-contained: this module imports nothing beyond drawfile.py itself
and the standard library, matching this project's own convention (see
drawfile.py's module docstring) of a dependency-free structural
decoder plus an optional rendering layer.

Colour, dash pattern, join style, and triangular-cap handling are
carried over unchanged from that source -- see the individual methods
below for the same notes (dash patterns/join styles are parsed but not
honoured; triangular caps -- SVG has no native equivalent -- are drawn
as an explicit filled triangle at the subpath's own start/end). Text
with a non-square x/y font-size ratio is rendered at its plain
y-based size rather than reproduced skewed (SVG has no direct
equivalent of a horizontal-scaling text operator without first
knowing the glyphs' own natural width).

This module has no logging dependency, matching drawfile.py -- a
caller wanting to know what wasn't fully reproduced (an undecoded
object type, a Sprite object with no `sprite_to_png` callback given, a
rotated/sheared JPEG) should inspect the second element of the tuple
`drawfile_to_svg` returns.
"""

from __future__ import annotations

import base64
import html as _html
import math
import struct
from typing import Callable, Optional

from riscos_drawfile.drawfile import (
    CAP_TRIANGULAR,
    OPTIONS_TYPE,
    BoundingBox,
    DrawFile,
    DrawGroup,
    DrawJPEG,
    DrawPath,
    DrawPathOpCode,
    DrawSprite,
    DrawTagged,
    DrawText,
    colour_rgb,
)

#: Draw units (1/256 OS unit, itself 1/180 inch) to CSS/SVG points.
DRAW_UNIT_TO_PT = 72.0 / (180.0 * 256.0)

#: A raw native sprite header+pixel record (bytes -> PNG bytes), or
#: None if it couldn't be decoded -- e.g. riscos_sprites.SpriteFile
#: wired up by a caller; this module has no pixel-decoding capability
#: of its own. See wrap_single_sprite_as_area().
SpriteToPng = Callable[[bytes], Optional[bytes]]

#: The 12-byte sprite-area header size a real ,ff9 file/single-sprite
#: record needs wrapping in before a full sprite-file decoder (e.g.
#: riscos_sprites.SpriteFile) will accept it -- see
#: wrap_single_sprite_as_area().
_AREA_HEADER_SIZE = 12


def wrap_single_sprite_as_area(sprite_record: bytes) -> bytes:
    """Synthesise a minimal, valid sprite-area byte blob (a 12-byte
    header: sprite_count, first_sprite_offset, free_offset, each of
    the latter two stored 4 bytes larger than their own real file
    offset -- an artefact of the in-memory OS_SpriteOp control-block
    convention the on-disk format also uses) wrapping just
    *sprite_record* -- a single native sprite header+pixel record with
    no area header of its own.

    Needed because a DrawFile's own Sprite object body is exactly that
    bare kind of record (see drawfile.DrawSprite's own docstring), but
    a full sprite-file decoder like riscos_sprites.SpriteFile expects
    the wrapped, multi-sprite area form every real ,ff9 file actually
    has."""
    first_offset = _AREA_HEADER_SIZE + 4
    free_offset = first_offset + len(sprite_record)
    return struct.pack("<III", 1, first_offset, free_offset) + sprite_record


def _unit_vector(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0, 0.0
    return dx / length, dy / length


def _subpath_cap_directions(
    ops: list, to_svg
) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """For each open subpath in *ops*, (start_point, start_outward_dir,
    end_point, end_outward_dir) in the final SVG point space."""
    subpaths: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    closed = False

    def flush() -> None:
        if len(current) >= 2 and not closed:
            subpaths.append(list(current))
        current.clear()

    for op in ops:
        if op.code in (DrawPathOpCode.MOVE, DrawPathOpCode.MOVE_INTERNAL):
            flush()
            closed = False
            current.append((op.x, op.y))
        elif op.code in (DrawPathOpCode.LINE, DrawPathOpCode.GAP, DrawPathOpCode.CURVE):
            current.append((op.x, op.y))
        elif op.code in (DrawPathOpCode.CLOSE_LINE, DrawPathOpCode.CLOSE_GAP):
            closed = True
    flush()

    results = []
    for verts in subpaths:
        p0 = to_svg(*verts[0])
        p1 = to_svg(*verts[1])
        pn = to_svg(*verts[-1])
        pn1 = to_svg(*verts[-2])
        start_dir = _unit_vector(p0[0] - p1[0], p0[1] - p1[1])
        end_dir = _unit_vector(pn[0] - pn1[0], pn[1] - pn1[1])
        results.append((p0, start_dir, pn, end_dir))
    return results


def _triangular_cap_polygon(
    point: tuple[float, float], direction: tuple[float, float], width_pt: float, length_pt: float
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    px, py = point
    dx, dy = direction
    nx, ny = -dy, dx
    half = width_pt / 2.0
    base_left = (px + nx * half, py + ny * half)
    base_right = (px - nx * half, py - ny * half)
    apex = (px + dx * length_pt, py + dy * length_pt)
    return base_left, apex, base_right


#: Substrings of a RISC OS font name that identify its family for CSS
#: purposes; matched case-insensitively, first match wins. Homerton
#: (and anything unrecognised) falls through to the sans-serif stack.
#: Single-quoted, not double -- these values are embedded inside a
#: double-quoted SVG style="..." attribute.
_FAMILY_HINTS = [
    ("courier", "'Courier New', Courier, monospace"),
    ("corpus", "'Courier New', Courier, monospace"),
    ("system", "'Courier New', Courier, monospace"),
    ("mono", "'Courier New', Courier, monospace"),
    ("times", "Times, 'Times New Roman', serif"),
    ("trinity", "Times, 'Times New Roman', serif"),
    ("serif", "Times, 'Times New Roman', serif"),
]
_DEFAULT_FONT_STACK = "'Helvetica Neue', Helvetica, Arial, sans-serif"


def _font_family_css_for_name(font_style_name: Optional[str]) -> str:
    name = (font_style_name or "").lower()
    for hint, stack in _FAMILY_HINTS:
        if hint in name:
            return stack
    return _DEFAULT_FONT_STACK


def _draw_colour_to_css(word: Optional[int]) -> Optional[str]:
    """A CSS "#rrggbb" colour for a raw Draw palette word (see
    drawfile.colour_rgb), or None for "no colour"."""
    if word is None:
        return None
    r, g, b = colour_rgb(word)
    return f"#{r:02x}{g:02x}{b:02x}"


def _escape_svg_text(text: str) -> str:
    return _html.escape(text, quote=False)


def drawfile_effective_bounds(draw: DrawFile) -> BoundingBox:
    """*draw*'s own declared header bounds, unioned with every actual
    DrawPath/DrawText object's own bounds -- a real DrawFile's own
    header bounds can be smaller than its content (confirmed against a
    real document), while DrawSprite/DrawUnknown objects often carry
    meaningless dummy bounds that must NOT be unioned in."""
    x0, y0, x1, y1 = draw.bounds.x0, draw.bounds.y0, draw.bounds.x1, draw.bounds.y1

    def visit(obj) -> None:
        nonlocal x0, y0, x1, y1
        if isinstance(obj, (DrawPath, DrawText)):
            b = obj.bounds
            x0, y0 = min(x0, b.x0), min(y0, b.y0)
            x1, y1 = max(x1, b.x1), max(y1, b.y1)
        elif isinstance(obj, DrawGroup):
            for child in obj.objects:
                visit(child)
        elif isinstance(obj, DrawTagged) and obj.inner is not None:
            visit(obj.inner)

    for obj in draw.objects:
        visit(obj)
    return BoundingBox(x0, y0, x1, y1)


def drawfile_to_svg(draw: DrawFile, sprite_to_png: Optional[SpriteToPng] = None) -> tuple[str, list[str]]:
    """*draw*'s own content as a standalone SVG document, at its own
    native size (100% scale, no shift or rotation -- a DrawFile has no
    single "owning" placement of its own). Returns (svg_text, notes) --
    *notes* lists anything not fully reproduced (an undecoded object
    type, a Sprite object left as a placeholder because no
    *sprite_to_png* was given or it failed to decode, a rotated/sheared
    JPEG), each note listed once even if it applies to more than one
    object.

    *sprite_to_png* converts a Sprite object's own raw native
    header+pixel bytes to PNG bytes (or None on failure) -- e.g.
    ``lambda data: riscos_sprites_png.sprite_area_to_png(wrap_single_sprite_as_area(data))``
    for a caller with the optional riscos_sprites decoder installed.
    With none given, embedded sprites render as a labelled placeholder
    box."""
    bounds = drawfile_effective_bounds(draw)
    width_pt = max(0.0, bounds.width * DRAW_UNIT_TO_PT)
    height_pt = max(0.0, bounds.height * DRAW_UNIT_TO_PT)

    def to_svg(dx: int, dy: int) -> tuple[float, float]:
        return (dx - bounds.x0) * DRAW_UNIT_TO_PT, height_pt - (dy - bounds.y0) * DRAW_UNIT_TO_PT

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_pt:.1f}pt" '
        f'height="{height_pt:.1f}pt" viewBox="0 0 {width_pt:.1f} {height_pt:.1f}">'
    ]
    notes: list[str] = []
    for obj in draw.objects:
        _drawfile_svg_object(obj, draw.fonts, to_svg, (DRAW_UNIT_TO_PT, DRAW_UNIT_TO_PT), parts, notes, sprite_to_png)
    parts.append("</svg>")
    return "".join(parts), list(dict.fromkeys(notes))  # de-duplicate, keep first-seen order


def _drawfile_svg_object(
    obj, fonts: dict, to_svg, scale, parts: list[str], notes: list[str], sprite_to_png: Optional[SpriteToPng]
) -> None:
    if isinstance(obj, DrawPath):
        _drawfile_svg_path(obj, to_svg, scale, parts)
    elif isinstance(obj, DrawText):
        _drawfile_svg_text(obj, fonts, to_svg, scale, parts)
    elif isinstance(obj, DrawGroup):
        for child in obj.objects:
            _drawfile_svg_object(child, fonts, to_svg, scale, parts, notes, sprite_to_png)
    elif isinstance(obj, DrawTagged):
        if obj.inner is not None:
            _drawfile_svg_object(obj.inner, fonts, to_svg, scale, parts, notes, sprite_to_png)
    elif isinstance(obj, DrawJPEG):
        _drawfile_svg_jpeg(obj, to_svg, parts, notes)
    elif isinstance(obj, DrawSprite):
        _drawfile_svg_sprite(obj, to_svg, parts, notes, sprite_to_png)
    elif obj.type != OPTIONS_TYPE:  # DrawUnknown -- text area, transformed text/sprite, or unrecognised
        notes.append(
            "one or more DrawFile object types (e.g. text area, transformed "
            "text/sprite) within this picture were not decoded and are omitted"
        )
    # else: an Options object -- no rendering component of its own, so
    # nothing was actually omitted; not worth logging (see OPTIONS_TYPE).


def _drawfile_svg_jpeg(jpeg: DrawJPEG, to_svg, parts: list[str], notes: list[str]) -> None:
    """A JPEG's own bytes are already a complete, standalone JPEG file
    (see drawfile.DrawJPEG) -- embedded directly as a base64 data:
    URI, no re-encoding needed. Positioned/sized from the object's own
    bounding box; the object's own transform matrix (a/b/c/d/e/f)
    isn't applied beyond that -- every real file seen so far has an
    identity a/d (1.0) and zero b/c (no rotation/shear), matching the
    bounding box exactly."""
    px0, py0 = to_svg(jpeg.bounds.x0, jpeg.bounds.y0)
    px1, py1 = to_svg(jpeg.bounds.x1, jpeg.bounds.y1)
    rx0, rx1 = sorted((px0, px1))
    ry0, ry1 = sorted((py0, py1))
    encoded = base64.b64encode(jpeg.data).decode("ascii")
    parts.append(
        f'<image x="{rx0:.2f}" y="{ry0:.2f}" width="{rx1 - rx0:.2f}" height="{ry1 - ry0:.2f}" '
        f'preserveAspectRatio="none" href="data:image/jpeg;base64,{encoded}"/>'
    )
    _a, b, c, _d, _e, _f = jpeg.matrix
    if b or c:
        notes.append(
            "a JPEG image with a rotated/sheared transform is rendered axis-aligned "
            "to its own bounding box; rotation/shear is not reproduced"
        )


def _drawfile_svg_sprite(
    sprite: DrawSprite, to_svg, parts: list[str], notes: list[str], sprite_to_png: Optional[SpriteToPng]
) -> None:
    """A Sprite object's own body is a single native sprite record with
    no area wrapper of its own (see drawfile.DrawSprite's own
    docstring) -- wrapped via wrap_single_sprite_as_area before handing
    it to *sprite_to_png*. Falls back to a placeholder box (with a
    note) when no *sprite_to_png* was given, or it fails to decode."""
    px0, py0 = to_svg(sprite.bounds.x0, sprite.bounds.y0)
    px1, py1 = to_svg(sprite.bounds.x1, sprite.bounds.y1)
    rx0, rx1 = sorted((px0, px1))
    ry0, ry1 = sorted((py0, py1))
    png = sprite_to_png(wrap_single_sprite_as_area(sprite.data)) if sprite_to_png and sprite.data else None
    if png is not None:
        encoded = base64.b64encode(png).decode("ascii")
        parts.append(
            f'<image x="{rx0:.2f}" y="{ry0:.2f}" width="{rx1 - rx0:.2f}" height="{ry1 - ry0:.2f}" '
            f'preserveAspectRatio="none" href="data:image/png;base64,{encoded}"/>'
        )
        return
    parts.append(
        f'<rect x="{rx0:.1f}" y="{ry0:.1f}" width="{rx1 - rx0:.1f}" height="{ry1 - ry0:.1f}" '
        f'fill="none" stroke="#999999" stroke-width="1"/>'
        f'<text x="{(rx0 + rx1) / 2:.1f}" y="{(ry0 + ry1) / 2:.1f}" font-size="9" fill="#666666" '
        f'text-anchor="middle" dominant-baseline="middle">[Sprite]</text>'
    )
    notes.append(
        "a Sprite object embedded within this picture is drawn as a placeholder box; "
        "no sprite_to_png callback was given, or the sprite failed to decode"
    )


def _drawfile_svg_path(path: DrawPath, to_svg, scale, parts: list[str]) -> None:
    has_fill = path.fill_colour is not None
    has_stroke = path.stroke_colour is not None
    if (not has_fill and not has_stroke) or not path.ops:
        return

    d_parts = []
    for op in path.ops:
        if op.code in (DrawPathOpCode.MOVE, DrawPathOpCode.MOVE_INTERNAL, DrawPathOpCode.GAP):
            x, y = to_svg(op.x, op.y)
            d_parts.append(f"M {x:.2f} {y:.2f}")
        elif op.code is DrawPathOpCode.LINE:
            x, y = to_svg(op.x, op.y)
            d_parts.append(f"L {x:.2f} {y:.2f}")
        elif op.code is DrawPathOpCode.CURVE:
            cx1, cy1 = to_svg(op.cx1, op.cy1)
            cx2, cy2 = to_svg(op.cx2, op.cy2)
            ex, ey = to_svg(op.x, op.y)
            d_parts.append(f"C {cx1:.2f} {cy1:.2f} {cx2:.2f} {cy2:.2f} {ex:.2f} {ey:.2f}")
        elif op.code is DrawPathOpCode.CLOSE_LINE:
            d_parts.append("Z")
        # CLOSE_GAP: no direct SVG equivalent needed -- the next M starts a fresh subpath.
    if not d_parts:
        return

    fill = _draw_colour_to_css(path.fill_colour) if has_fill else "none"
    stroke = _draw_colour_to_css(path.stroke_colour) if has_stroke else "none"
    attrs = [f'd="{" ".join(d_parts)}"', f'fill="{fill}"', f'stroke="{stroke}"']
    width_pt = 0.0
    if has_stroke:
        # scale[i] is already "target points per source Draw unit".
        line_scale = (abs(scale[0]) + abs(scale[1])) / 2.0
        width_pt = path.line_width * line_scale if path.line_width else 0.3
        attrs.append(f'stroke-width="{max(0.1, width_pt):.2f}"')
        if path.dashed and path.dash_elements:
            # line_scale converts Draw units -> pt the same way width_pt
            # above does; SVG's own stroke-dasharray takes a plain list
            # of on/off lengths in the current coordinate system, so no
            # odd-element-count sense-inversion handling is needed here
            # (SVG already repeats/alternates the array itself).
            dasharray = " ".join(f"{e * line_scale:.2f}" for e in path.dash_elements)
            attrs.append(f'stroke-dasharray="{dasharray}"')
            if path.dash_offset:
                attrs.append(f'stroke-dashoffset="{path.dash_offset * line_scale:.2f}"')
    if has_fill and path.even_odd:
        attrs.append('fill-rule="evenodd"')
    parts.append(f"<path {' '.join(attrs)}/>")

    if has_stroke and (path.start_cap == CAP_TRIANGULAR or path.end_cap == CAP_TRIANGULAR):
        _draw_svg_triangular_caps(path, to_svg, width_pt, parts)


def _draw_svg_triangular_caps(path: DrawPath, to_svg, width_pt: float, parts: list[str]) -> None:
    """PDF/SVG have no triangular line-cap style, so a triangular cap
    (the mechanism real Draw files use for arrowhead/pointer line ends)
    is drawn here as an explicit filled triangle at the subpath's own
    start/end, matching the real RISC OS DrawFile module's own
    Draw_Stroke-based rendering."""
    fill = _draw_colour_to_css(path.stroke_colour)
    for start_pt, start_dir, end_pt, end_dir in _subpath_cap_directions(path.ops, to_svg):
        if path.start_cap == CAP_TRIANGULAR:
            _append_svg_triangular_cap(start_pt, start_dir, path, width_pt, fill, parts)
        if path.end_cap == CAP_TRIANGULAR:
            _append_svg_triangular_cap(end_pt, end_dir, path, width_pt, fill, parts)


def _append_svg_triangular_cap(
    point: tuple[float, float],
    direction: tuple[float, float],
    path: DrawPath,
    width_pt: float,
    fill: Optional[str],
    parts: list[str],
) -> None:
    if direction == (0.0, 0.0):
        return
    cap_width_pt = (path.triangle_cap_width / 16.0) * width_pt
    cap_length_pt = (path.triangle_cap_length / 16.0) * width_pt
    if cap_width_pt <= 0 or cap_length_pt <= 0:
        return
    (x0, y0), (x1, y1), (x2, y2) = _triangular_cap_polygon(point, direction, cap_width_pt, cap_length_pt)
    parts.append(
        f'<path d="M {x0:.2f} {y0:.2f} L {x1:.2f} {y1:.2f} L {x2:.2f} {y2:.2f} Z" '
        f'fill="{fill}" stroke="none"/>'
    )


def _drawfile_svg_text(text: DrawText, fonts: dict, to_svg, scale, parts: list[str]) -> None:
    if not text.text.strip() or text.size_y <= 0:
        return
    _sx, sy = scale
    # Ignores any x/y font-size skew the DrawFile itself declares (a
    # rare case, and SVG has no equally direct equivalent without
    # first knowing the glyphs' own natural width) -- a deliberate
    # simplification.
    #
    # text.size_y is already in points (1/640 point); dividing by
    # DRAW_UNIT_TO_PT turns sy (points per Draw unit) into the
    # dimensionless magnification the picture is actually being drawn
    # at.
    size_pt = (text.size_y / 640.0) * (abs(sy) / DRAW_UNIT_TO_PT)
    if size_pt <= 0.5:
        return
    x, y = to_svg(text.baseline_x, text.baseline_y)
    font_name = fonts.get(text.font_number)
    name_lower = (font_name or "").lower()
    style_bits = [f"font-family:{_font_family_css_for_name(font_name)}", f"font-size:{size_pt:.2f}pt"]
    if "bold" in name_lower:
        style_bits.append("font-weight:bold")
    if "italic" in name_lower or "oblique" in name_lower:
        style_bits.append("font-style:italic")
    style_bits.append(f"fill:{_draw_colour_to_css(text.colour) or '#000000'}")
    parts.append(f'<text x="{x:.2f}" y="{y:.2f}" style="{"; ".join(style_bits)}">{_escape_svg_text(text.text)}</text>')
