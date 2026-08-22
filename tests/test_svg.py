from riscos_drawfile.drawfile import DrawFile
from riscos_drawfile.svg import drawfile_to_svg, wrap_single_sprite_as_area
from tests.fixtures.drawfile_builders import (
    build_drawfile,
    build_path,
    build_sprite,
    build_text,
    build_unknown,
    end_path,
    line,
    move,
)


def test_filled_path_renders_as_svg_path_with_fill_and_no_stroke():
    ops = move(0, 0) + line(1000, 0) + line(1000, 1000) + end_path()
    data = build_drawfile(build_path(ops=ops, bounds=(0, 0, 1000, 1000), fill_colour=0x0000FF00, stroke_colour=0xFFFFFFFF))
    draw = DrawFile.from_bytes(data)
    svg, notes = drawfile_to_svg(draw)
    assert "<svg" in svg
    assert 'fill="#ff0000"' in svg
    assert 'stroke="none"' in svg
    assert notes == []


def test_text_object_renders_as_svg_text_element():
    data = build_drawfile(build_text(text="Hello", bounds=(0, 0, 1000, 1000), size_y=640))
    draw = DrawFile.from_bytes(data)
    svg, _notes = drawfile_to_svg(draw)
    assert "<text" in svg
    assert "Hello" in svg


def test_undecoded_object_type_produces_a_note():
    data = build_drawfile(build_unknown(99, bounds=(0, 0, 10, 10)))
    draw = DrawFile.from_bytes(data)
    svg, notes = drawfile_to_svg(draw)
    assert "<svg" in svg
    assert len(notes) == 1
    assert "not decoded" in notes[0]


def test_sprite_object_without_callback_renders_placeholder_and_note():
    data = build_drawfile(build_sprite(bounds=(0, 0, 100, 100), body=b"\x00" * 44))
    draw = DrawFile.from_bytes(data)
    svg, notes = drawfile_to_svg(draw)
    assert "[Sprite]" in svg
    assert len(notes) == 1


def test_sprite_object_with_callback_embeds_returned_png():
    data = build_drawfile(build_sprite(bounds=(0, 0, 100, 100), body=b"\x00" * 44))
    draw = DrawFile.from_bytes(data)
    svg, notes = drawfile_to_svg(draw, sprite_to_png=lambda _data: b"PNGDATA")
    assert "data:image/png;base64," in svg
    assert notes == []


def test_wrap_single_sprite_as_area_prefixes_a_12_byte_header():
    record = b"\x01\x02\x03\x04"
    wrapped = wrap_single_sprite_as_area(record)
    assert len(wrapped) == 12 + len(record)
    assert wrapped[12:] == record
