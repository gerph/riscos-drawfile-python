"""A pure-Python structural decoder for RISC OS DrawFile documents.

Importing this package pulls in only the structural decoder
(drawfile.py) -- no SVG rendering. SVG conversion (riscos_drawfile.svg)
is a separate submodule with its own explicit import, for callers who
only want the decoded object model and would rather not carry the
(admittedly stdlib-only) rendering code along with it -- see
``from riscos_drawfile.svg import drawfile_to_svg``.
"""

from __future__ import annotations

from riscos_drawfile.drawfile import (
    CAP_BUTT,
    CAP_ROUND,
    CAP_TRIANGULAR,
    OPTIONS_TYPE,
    BoundingBox,
    DrawFile,
    DrawGroup,
    DrawJPEG,
    DrawObject,
    DrawPath,
    DrawPathOp,
    DrawPathOpCode,
    DrawSprite,
    DrawTagged,
    DrawText,
    DrawUnknown,
    colour_rgb,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "BoundingBox",
    "CAP_BUTT",
    "CAP_ROUND",
    "CAP_TRIANGULAR",
    "OPTIONS_TYPE",
    "DrawFile",
    "DrawGroup",
    "DrawJPEG",
    "DrawObject",
    "DrawPath",
    "DrawPathOp",
    "DrawPathOpCode",
    "DrawSprite",
    "DrawTagged",
    "DrawText",
    "DrawUnknown",
    "colour_rgb",
]
