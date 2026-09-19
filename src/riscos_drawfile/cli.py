"""Command line interface for riscos-drawfile.

A single job, matching riscos-dumpsprites' own original (pre-subcommand)
shape: decode a DrawFile and convert it to SVG. See
https://gitlab.gerph.org/notriscos/gerph/riscos-dumpsprites for the
sibling tool this one's flag/error-handling conventions (``-o``/
``--output`` defaulting from the input path, printing "riscos-drawfile:
<message>" to stderr and returning 1 on failure) are modelled on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from riscos_drawfile import __version__
from riscos_drawfile.drawfile import DrawFile
from riscos_drawfile.svg import drawfile_to_svg

try:
    # Optional: if riscos_sprites (see
    # https://gitlab.gerph.org/notriscos/gerph/riscos-dumpsprites) is
    # installed, Sprite objects embedded within the DrawFile are
    # rendered as real pixels instead of a placeholder box. Not a hard
    # dependency of this package -- see svg.py's own module docstring.
    from riscos_sprites import SpriteFile
    from riscos_sprites.png import build_png_image, encode_png

    def _sprite_to_png(data: bytes) -> "bytes | None":
        try:
            sprite_file = SpriteFile.from_bytes(data)
            if not sprite_file.sprites:
                return None
            return encode_png(build_png_image(sprite_file.sprites[0]))
        except Exception:
            return None

except ImportError:  # pragma: no cover - exercised by CI without the extra
    _sprite_to_png = None


def parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="riscos-drawfile",
        description="Convert a RISC OS DrawFile to a standalone SVG document.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("input", type=Path, help="Path to the DrawFile (e.g. a ',aff' file)")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Path to write the SVG to (default: INPUT with its suffix replaced by '.svg')",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Don't print notes about anything that couldn't be fully reproduced",
    )
    return parser.parse_args(argv)


def main(argv: "list[str] | None" = None) -> int:
    args = parse_args(argv)
    output = args.output if args.output is not None else args.input.with_suffix(".svg")

    try:
        data = args.input.read_bytes()
    except OSError as exc:
        print(f"riscos-drawfile: {exc}", file=sys.stderr)
        return 1

    draw = DrawFile.from_bytes(data)
    if draw is None:
        print(f"riscos-drawfile: {args.input}: not a DrawFile", file=sys.stderr)
        return 1

    svg_text, notes = drawfile_to_svg(draw, sprite_to_png=_sprite_to_png)

    try:
        output.write_text(svg_text, encoding="utf-8")
    except OSError as exc:
        print(f"riscos-drawfile: {exc}", file=sys.stderr)
        return 1

    print(f"Converted {args.input} to {output}")
    if notes and not args.quiet:
        for note in notes:
            print(f"riscos-drawfile: note: {note}", file=sys.stderr)
    return 0
