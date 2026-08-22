# riscos-drawfile

A pure-Python structural decoder for RISC OS [DrawFile](https://www.riscos.com/support/developers/prm/fileformats.html)
documents (`,aff`), plus an SVG converter built on top of it.

The decoder was originally written for, and lived inside,
[`riscos-impression`](https://gitlab.gerph.org/notriscos/gerph/riscos-impression)
(a decoder/converter for Impression DTP documents, which embed DrawFile
pictures); it's general RISC OS DrawFile knowledge rather than anything
specific to Impression, so it's been lifted out into its own package --
mirroring [`riscos-artworks`](https://gitlab.gerph.org/notriscos/gerph/riscos-artworks),
which did the same thing for the ArtWorks format.

## What it does

* **Structural decode** (`riscos_drawfile`) -- reads a DrawFile's header
  and walks its object stream into a class-structured Python object
  model: font tables, paths (fill/stroke colour, width, winding rule,
  dash pattern, join/cap style, and their move/line/curve/close
  elements), single-line text, JPEG images (the JPEG's own bytes,
  standalone and ready to embed -- no pixel decompression), Sprite
  objects (kept as raw bytes -- pixel decoding is a caller's own job,
  e.g. via [`riscos-dumpsprites`](https://gitlab.gerph.org/notriscos/gerph/riscos-dumpsprites)),
  groups, and tagged objects (recursing into both). Anything else
  (text areas, transformed text/sprite, or a genuinely unrecognised
  object type) is captured only as a bounding box.

  This half of the package has no dependencies beyond the Python
  standard library, and importing `riscos_drawfile` pulls in only
  this -- not the SVG converter below.

* **SVG conversion** (`riscos_drawfile.svg`) -- renders a decoded
  DrawFile as a standalone SVG document at its own native size: paths
  (fill/stroke/dash, with triangular line caps -- SVG has no native
  equivalent -- drawn as an explicit filled triangle), text, and
  embedded JPEG images. This is a separate submodule with its own
  explicit import, so a caller that only wants the object model isn't
  required to import it. It's also self-contained -- no dependency
  beyond the standard library and `riscos_drawfile` itself -- but it
  can't decode a Sprite object's own pixels on its own; pass a
  `sprite_to_png` callback (raw native sprite bytes -> PNG bytes, or
  `None`) if you want those rendered rather than left as a labelled
  placeholder box. `wrap_single_sprite_as_area()` in the same module
  does the one bit of format-adjacent work a real sprite decoder
  needs first (see its own docstring).

## Command line

```sh
riscos-drawfile <input> [output] [--quiet]
```

Converts a DrawFile to SVG. `output` defaults to `<input>` with its
suffix replaced by `.svg`. Exits `0` on success, `1` if the input
couldn't be read or isn't a DrawFile. Anything not fully reproduced (an
undecoded object type, a Sprite object left as a placeholder) is
reported as a `note:` line on stderr unless `--quiet` is given.

If the optional `riscos-dumpsprites` package is installed (see the
`sprites` extra), embedded Sprite objects are rendered as real pixels
instead of a placeholder box.

```sh
pip install 'riscos-drawfile[sprites]'
riscos-drawfile MyPicture,aff MyPicture.svg
```

## Library usage

```python
from riscos_drawfile import DrawFile

data = open("MyPicture,aff", "rb").read()
draw = DrawFile.from_bytes(data)
if draw is not None:
    for obj in draw.objects:
        ...  # DrawPath, DrawText, DrawSprite, DrawJPEG, DrawGroup, DrawTagged, DrawUnknown
```

To convert to SVG as well:

```python
from riscos_drawfile.svg import drawfile_to_svg

svg_text, notes = drawfile_to_svg(draw)
```

## Development

```sh
pip install -e '.[dev]'
pytest
```

## Licence

MIT; see [`LICENSE`](LICENSE).
