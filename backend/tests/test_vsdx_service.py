"""Unit tests for the read-only .vsdx parser.

The fixtures are minimal ZIP packages that follow the OOXML relationship
conventions the parser relies on. They are built in memory, so no real Visio
file or network access is required.
"""
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

import pytest

from services.vsdx_service import VsdxError, VsdxLimits, parse_vsdx

REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TYPE = "http://schemas.microsoft.com/visio/2010/relationships"

DEFAULT_LIMITS = VsdxLimits()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _rels(entries):
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rel_type}" Target="{target}"/>'
        for rid, rel_type, target in entries
    )
    return f'<Relationships xmlns="{PKG_REL_NS}">{body}</Relationships>'


def _pages_xml(page_names):
    entries = "".join(
        f'<Page ID="{i}" Name="{escape(name)}"><Rel r:id="rId{i + 1}"/></Page>'
        for i, name in enumerate(page_names)
    )
    return f'<Pages xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">{entries}</Pages>'


def _page_xml(shapes, width=10.0, height=7.5, page_sheet=True):
    sheet = ""
    if page_sheet:
        sheet = (
            f'<PageSheet><Cell N="PageWidth" V="{width}"/>'
            f'<Cell N="PageHeight" V="{height}"/></PageSheet>'
        )
    return (
        f'<PageContents xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">'
        f"{sheet}<Shapes>{shapes}</Shapes></PageContents>"
    )


def _zip(parts):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in parts.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _single_page_doc(page_body, page_rels_extra=(), extra_parts=None):
    parts = {
        "visio/pages/pages.xml": _pages_xml(["Page-1"]),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [("rId1", REL_TYPE + "/page", "page1.xml")]
        ),
        "visio/pages/page1.xml": page_body,
    }
    if page_rels_extra:
        parts["visio/pages/_rels/page1.xml.rels"] = _rels(page_rels_extra)
    if extra_parts:
        parts.update(extra_parts)
    return _zip(parts)


RECT_SHAPE = (
    '<Shape ID="1">'
    '<Cell N="PinX" V="2"/><Cell N="PinY" V="2"/>'
    '<Cell N="Width" V="3"/><Cell N="Height" V="1"/>'
    '<Cell N="FillPattern" V="1"/><Cell N="FillForegnd" V="#FF0000"/>'
    '<Section N="Geometry" IX="0">'
    '<Row T="Rectangle" IX="1">'
    '<Cell N="X0" V="0"/><Cell N="Y0" V="0"/>'
    '<Cell N="X1" V="3"/><Cell N="Y1" V="1"/>'
    "</Row></Section>"
    "<Text>Hello</Text>"
    "</Shape>"
)

LINE_SHAPE = (
    '<Shape ID="2">'
    '<Cell N="BeginX" V="1"/><Cell N="BeginY" V="5"/>'
    '<Cell N="EndX" V="4"/><Cell N="EndY" V="5"/>'
    '<Cell N="LineColor" V="#0000FF"/>'
    "</Shape>"
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_minimal_document_renders_page():
    data = _single_page_doc(_page_xml(RECT_SHAPE + LINE_SHAPE))
    result = parse_vsdx(data, "diagram.vsdx", DEFAULT_LIMITS)

    assert result["file_name"] == "diagram.vsdx"
    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["index"] == 0
    assert page["name"] == "Page-1"
    assert page["width"] == pytest.approx(960.0)
    assert page["height"] == pytest.approx(720.0)
    assert page["shape_count"] == 2
    assert page["svg"].startswith("<svg ")
    assert 'viewBox="0 0 960 720"' in page["svg"]
    assert "<path " in page["svg"]
    assert "<line " in page["svg"]
    assert "Hello" in page["svg"]


def test_page_dimensions_read_from_page_part():
    # PageSheet lives in pageN.xml, which is where real Visio puts it.
    data = _single_page_doc(_page_xml(RECT_SHAPE, width=8.5, height=11.0))
    page = parse_vsdx(data, "a.vsdx", DEFAULT_LIMITS)["pages"][0]
    assert (page["width"], page["height"]) == pytest.approx((816.0, 1056.0))


def test_master_inheritance_applies_geometry():
    master_shape = (
        '<Shape ID="10">'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<Cell N="FillPattern" V="1"/><Cell N="FillForegnd" V="#00FF00"/>'
        '<Section N="Geometry" IX="0">'
        '<Row T="Ellipse" IX="1"/>'
        "</Section>"
        "</Shape>"
    )
    instance = '<Shape ID="5" Master="1"><Cell N="PinX" V="3"/><Cell N="PinY" V="4"/></Shape>'
    parts = {
        "visio/pages/pages.xml": _pages_xml(["P"]),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [("rId1", REL_TYPE + "/page", "page1.xml")]
        ),
        "visio/pages/page1.xml": _page_xml(instance),
        "visio/masters/masters.xml": (
            f'<Masters xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">'
            '<Master ID="1" NameU="Round"><Rel r:id="rId9"/></Master></Masters>'
        ),
        "visio/masters/_rels/masters.xml.rels": _rels(
            [("rId9", REL_TYPE + "/master", "master1.xml")]
        ),
        "visio/masters/master1.xml": f'<MasterContents xmlns="{VISIO_NS}"><Shapes>{master_shape}</Shapes></MasterContents>',
    }
    page = parse_vsdx(_zip(parts), "m.vsdx", DEFAULT_LIMITS)["pages"][0]

    assert page["shape_count"] == 1
    assert "#00FF00" in page["svg"]
    assert "<path " in page["svg"]


def test_embedded_image_becomes_data_uri():
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    shape = (
        '<Shape ID="7">'
        '<Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId3"/>'
        "</Shape>"
    )
    data = _single_page_doc(
        _page_xml(shape),
        page_rels_extra=[("rId3", REL_TYPE + "/image", "../media/image1.png")],
        extra_parts={"visio/media/image1.png": png},
    )
    svg = parse_vsdx(data, "i.vsdx", DEFAULT_LIMITS)["pages"][0]["svg"]
    assert "data:image/png;base64," in svg


def test_text_is_escaped():
    shape = (
        '<Shape ID="3"><Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="1"/>'
        "<Text>&lt;b&gt;R&amp;D</Text></Shape>"
    )
    svg = parse_vsdx(
        _single_page_doc(_page_xml(shape)), "t.vsdx", DEFAULT_LIMITS
    )["pages"][0]["svg"]
    assert "&lt;b&gt;R&amp;D" in svg
    assert "<b>" not in svg


def test_arc_produces_approximation_warning():
    shape = (
        '<Shape ID="4"><Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<Cell N="LinePattern" V="1"/>'
        '<Section N="Geometry" IX="0">'
        '<Row T="MoveTo" IX="1"><Cell N="X" V="0"/><Cell N="Y" V="0"/></Row>'
        '<Row T="ArcTo" IX="2"><Cell N="X" V="2"/><Cell N="Y" V="2"/><Cell N="A" V="0.5"/></Row>'
        "</Section></Shape>"
    )
    result = parse_vsdx(
        _single_page_doc(_page_xml(shape)), "c.vsdx", DEFAULT_LIMITS
    )
    assert any("近似" in w for w in result["warnings"])
    assert " Q" in result["pages"][0]["svg"]


def test_svg_and_bmp_images_become_data_uris():
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    bmp = b"BM" + b"\x00" * 40
    shape = (
        '<Shape ID="7"><Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId3"/></Shape>'
        '<Shape ID="8"><Cell N="PinX" V="4"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId4"/></Shape>'
    )
    data = _single_page_doc(
        _page_xml(shape),
        page_rels_extra=[
            ("rId3", REL_TYPE + "/image", "../media/i.svg"),
            ("rId4", REL_TYPE + "/image", "../media/i.bmp"),
        ],
        extra_parts={"visio/media/i.svg": svg, "visio/media/i.bmp": bmp},
    )
    result = parse_vsdx(data, "i.vsdx", DEFAULT_LIMITS)
    rendered = result["pages"][0]["svg"]
    assert "data:image/svg+xml;base64," in rendered
    assert "data:image/bmp;base64," in rendered
    assert result["warnings"] == []


def _emf_record(rec_type, body):
    import struct
    return struct.pack("<II", rec_type, 8 + len(body)) + body


def _minimal_emf():
    """A header-only EMF with one filled bezier path, built to the spec."""
    import struct
    header = bytearray(88)
    struct.pack_into("<II", header, 0, 1, 88)  # EMR_HEADER, nBytes
    struct.pack_into("<4i", header, 8, 0, 0, 100, 100)  # rclBounds
    header[40:44] = b" EMF"
    pts = [(20, 10), (50, 80), (80, 10), (90, 90), (60, 90), (10, 20)]
    bezier_body = (
        struct.pack("<4i", 0, 0, 100, 100)
        + struct.pack("<I", len(pts))
        + b"".join(struct.pack("<2h", *p) for p in pts)
    )
    records = [
        _emf_record(17, struct.pack("<I", 1)),  # SETMAPMODE(MM_TEXT)
        _emf_record(9, struct.pack("<2i", 100, 100)),  # SETWINDOWEXTEX
        _emf_record(11, struct.pack("<2i", 100, 100)),  # SETVIEWPORTEXTEX
        _emf_record(39, struct.pack("<3I", 0, 0, 0xFF)),  # CREATEBRUSHINDIRECT
        _emf_record(37, struct.pack("<I", 0)),  # SELECTOBJECT
        _emf_record(59, b""),  # BEGINPATH
        _emf_record(27, struct.pack("<2i", 10, 10)),  # MOVETOEX
        _emf_record(88, bezier_body),  # POLYBEZIERTO16
        _emf_record(60, b""),  # ENDPATH
        _emf_record(62, struct.pack("<4i", 0, 0, 0, 0)),  # FILLPATH
        _emf_record(14, b"\x00" * 12),  # EOF
    ]
    return bytes(header) + b"".join(records)


def test_emf_image_renders_as_svg_data_uri():
    shape = (
        '<Shape ID="7"><Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId3"/></Shape>'
    )
    data = _single_page_doc(
        _page_xml(shape),
        page_rels_extra=[("rId3", REL_TYPE + "/image", "../media/i.emf")],
        extra_parts={"visio/media/i.emf": _minimal_emf()},
    )
    result = parse_vsdx(data, "i.vsdx", DEFAULT_LIMITS)
    rendered = result["pages"][0]["svg"]
    assert "data:image/svg+xml;base64," in rendered
    assert "stroke-dasharray" not in rendered
    assert result["warnings"] == []


def test_unparseable_emf_falls_back_to_placeholder():
    # A file with the EMF signature but a broken body must still show the shape
    # as a dashed placeholder, with a warning naming the real cause.
    emf = b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"\x00" * 32
    shape = (
        '<Shape ID="7"><Cell N="PinX" V="1"/><Cell N="PinY" V="1"/>'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId3"/></Shape>'
    )
    data = _single_page_doc(
        _page_xml(shape),
        page_rels_extra=[("rId3", REL_TYPE + "/image", "../media/i.emf")],
        extra_parts={"visio/media/i.emf": emf},
    )
    result = parse_vsdx(data, "i.vsdx", DEFAULT_LIMITS)
    rendered = result["pages"][0]["svg"]
    assert "stroke-dasharray" in rendered
    assert any("EMF" in w for w in result["warnings"])


def test_master_embedded_picture_resolves_via_master_rels():
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    master_shape = (
        '<Shape ID="1">'
        '<Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<ForeignData r:id="rId1"/></Shape>'
    )
    instance = '<Shape ID="5" Master="1"><Cell N="PinX" V="3"/><Cell N="PinY" V="4"/></Shape>'
    parts = {
        "visio/pages/pages.xml": _pages_xml(["P"]),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [("rId1", REL_TYPE + "/page", "page1.xml")]
        ),
        "visio/pages/page1.xml": _page_xml(instance),
        "visio/masters/masters.xml": (
            f'<Masters xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">'
            '<Master ID="1" NameU="Icon"><Rel r:id="rId9"/></Master></Masters>'
        ),
        "visio/masters/_rels/masters.xml.rels": _rels(
            [("rId9", REL_TYPE + "/master", "master1.xml")]
        ),
        "visio/masters/master1.xml": (
            f'<MasterContents xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">'
            f"<Shapes>{master_shape}</Shapes></MasterContents>"
        ),
        "visio/masters/_rels/master1.xml.rels": _rels(
            [("rId1", REL_TYPE + "/image", "../media/icon.png")]
        ),
        "visio/media/icon.png": png,
    }
    svg = parse_vsdx(_zip(parts), "m.vsdx", DEFAULT_LIMITS)["pages"][0]["svg"]
    assert "data:image/png;base64," in svg


def test_master_shape_attribute_selects_sub_shape():
    green = (
        '<Shape ID="10"><Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<Cell N="FillPattern" V="1"/><Cell N="FillForegnd" V="#00FF00"/>'
        '<Section N="Geometry" IX="0"><Row T="Ellipse" IX="1"/></Section></Shape>'
    )
    blue = (
        '<Shape ID="11"><Cell N="Width" V="2"/><Cell N="Height" V="2"/>'
        '<Cell N="FillPattern" V="1"/><Cell N="FillForegnd" V="#0000FF"/>'
        '<Section N="Geometry" IX="0"><Row T="Rectangle" IX="1"/></Section></Shape>'
    )
    parts = {
        "visio/pages/pages.xml": _pages_xml(["P"]),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [("rId1", REL_TYPE + "/page", "page1.xml")]
        ),
        # Page shape ID collides with a non-root master shape on purpose: the
        # instance must inherit the root unless MasterShape names another one.
        "visio/pages/page1.xml": _page_xml(
            '<Shape ID="11" Master="1"><Cell N="PinX" V="3"/><Cell N="PinY" V="4"/></Shape>'
            '<Shape ID="12" Master="1" MasterShape="11"><Cell N="PinX" V="6"/><Cell N="PinY" V="4"/></Shape>'
        ),
        "visio/masters/masters.xml": (
            f'<Masters xmlns="{VISIO_NS}" xmlns:r="{REL_NS}">'
            '<Master ID="1" NameU="G"><Rel r:id="rId9"/></Master></Masters>'
        ),
        "visio/masters/_rels/masters.xml.rels": _rels(
            [("rId9", REL_TYPE + "/master", "master1.xml")]
        ),
        "visio/masters/master1.xml": (
            f'<MasterContents xmlns="{VISIO_NS}"><Shapes>{green}{blue}'
            "</Shapes></MasterContents>"
        ),
    }
    svg = parse_vsdx(_zip(parts), "m.vsdx", DEFAULT_LIMITS)["pages"][0]["svg"]
    assert "#00FF00" in svg
    assert "#0000FF" in svg


def test_hidden_geometry_and_style_rows_are_not_warned():
    visible = (
        '<Shape ID="9"><Cell N="PinX" V="2"/><Cell N="PinY" V="2"/>'
        '<Cell N="Width" V="3"/><Cell N="Height" V="2"/>'
        '<Section N="Geometry" IX="0">'
        '<Row T="MoveTo" IX="1"><Cell N="X" V="0"/><Cell N="Y" V="0"/></Row>'
        '<Row T="LineTo" IX="2"><Cell N="X" V="3"/><Cell N="Y" V="0"/></Row>'
        '<Row T="NoLine" IX="3"/>'
        "</Section></Shape>"
    )
    hidden = (
        '<Shape ID="10"><Cell N="PinX" V="6"/><Cell N="PinY" V="4"/>'
        '<Cell N="Width" V="3"/><Cell N="Height" V="2"/>'
        '<Cell N="FillPattern" V="1"/>'
        '<Section N="Geometry" IX="1">'
        '<Cell N="NoShow" V="1"/>'
        '<Row T="Rectangle" IX="1"><Cell N="X0" V="0"/><Cell N="Y0" V="0"/>'
        '<Cell N="X1" V="3"/><Cell N="Y1" V="2"/></Row>'
        "</Section></Shape>"
    )
    result = parse_vsdx(
        _single_page_doc(_page_xml(visible + hidden)), "g.vsdx", DEFAULT_LIMITS
    )
    svg = result["pages"][0]["svg"]
    assert "<path " in svg
    # The NoShow section must not be drawn, and style rows must not warn.
    assert 'd="M 48 624 L 336 624"' in svg
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_empty_file_rejected():
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(b"", "e.vsdx", DEFAULT_LIMITS)
    assert exc.value.status_code == 400


def test_non_zip_rejected():
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(b"not a zip file at all", "e.vsdx", DEFAULT_LIMITS)
    assert exc.value.status_code == 400


def test_missing_pages_index_rejected():
    data = _zip({"visio/pages/page1.xml": _page_xml(RECT_SHAPE)})
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(data, "e.vsdx", DEFAULT_LIMITS)
    assert "页面索引" in exc.value.message


def test_no_pages_rejected():
    data = _zip(
        {
            "visio/pages/pages.xml": f'<Pages xmlns="{VISIO_NS}"/>',
            "visio/pages/_rels/pages.xml.rels": _rels([]),
        }
    )
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(data, "e.vsdx", DEFAULT_LIMITS)
    assert exc.value.status_code == 400


def test_page_count_limit():
    names = ["P1", "P2"]
    parts = {
        "visio/pages/pages.xml": _pages_xml(names),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [
                ("rId1", REL_TYPE + "/page", "page1.xml"),
                ("rId2", REL_TYPE + "/page", "page2.xml"),
            ]
        ),
        "visio/pages/page1.xml": _page_xml(RECT_SHAPE),
        "visio/pages/page2.xml": _page_xml(RECT_SHAPE),
    }
    limits = VsdxLimits(max_pages=1)
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(_zip(parts), "e.vsdx", limits)
    assert exc.value.status_code == 413


def test_doctype_rejected():
    body = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "y">]>' + _page_xml(RECT_SHAPE)
    data = _single_page_doc(body)
    with pytest.raises(VsdxError) as exc:
        parse_vsdx(data, "e.vsdx", DEFAULT_LIMITS)
    assert "不安全的 XML" in exc.value.message


def test_path_traversal_target_ignored():
    # A malicious relationship pointing outside visio/pages must not resolve;
    # that page is skipped with a warning while the valid page still renders.
    parts = {
        "visio/pages/pages.xml": _pages_xml(["Bad", "Good"]),
        "visio/pages/_rels/pages.xml.rels": _rels(
            [
                ("rId1", REL_TYPE + "/page", "../../../etc/passwd"),
                ("rId2", REL_TYPE + "/page", "page2.xml"),
            ]
        ),
        "visio/pages/page2.xml": _page_xml(RECT_SHAPE),
    }
    result = parse_vsdx(_zip(parts), "e.vsdx", DEFAULT_LIMITS)
    assert len(result["pages"]) == 1
    assert result["pages"][0]["name"] == "Good"
    assert any("已跳过" in w for w in result["warnings"])
