"""
Read-only .vsdx (Visio 2013+) parser.

VSDX is a ZIP package of XML parts. This module turns each Visio page into a
standalone SVG document. It only reads bytes from the request; nothing is
written to disk or to the database.

Fidelity: rectangles, lines, polylines, text, images, groups and rotation are
rendered from their ShapeSheet values. Curves (ArcTo / EllipticalArcTo /
NURBSTo / splines) are approximated with Bezier curves or polylines and
reported through ``warnings``.

Design notes:
- Deliberately imports nothing from ``core.config`` / FastAPI so it can be
  unit-tested without booting the app (settings are injected via VsdxLimits).
- All untrusted text is escaped; DOCTYPE / ENTITY declarations are rejected.
- Coordinates are flattened with 2D affine matrices before SVG output, so the
  result never nests transforms (nested transforms mirror text).
"""
from __future__ import annotations

import base64
import io
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from services.emf_service import emf_to_svg

PX_PER_INCH = 96.0
_NS_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

_PAGES_PART = "visio/pages/pages.xml"
_PAGES_RELS = "visio/pages/_rels/pages.xml.rels"
_MASTERS_PART = "visio/masters/masters.xml"
_MASTERS_RELS = "visio/masters/_rels/masters.xml.rels"

_RE_PAGE = re.compile(r"visio/pages/page\d+\.xml")
_RE_PAGE_REL = re.compile(r"visio/pages/_rels/page\d+\.xml\.rels")
_RE_MASTER = re.compile(r"visio/masters/master\d+\.xml")
_RE_MASTER_REL = re.compile(r"visio/masters/_rels/master\d+\.xml\.rels")
_RE_MEDIA = re.compile(r"visio/media/[^/]+")
_RE_UNSAFE = re.compile(r"[\\\x00]")


@dataclass(frozen=True)
class VsdxLimits:
    """Hard caps that keep parsing bounded and safe."""

    max_file_bytes: int = 20 * 1024 * 1024
    max_total_uncompressed: int = 80 * 1024 * 1024
    max_entries: int = 5000
    max_entry_bytes: int = 20 * 1024 * 1024
    max_pages: int = 100
    max_shapes_per_page: int = 5000
    max_depth: int = 20
    max_image_bytes: int = 5 * 1024 * 1024
    max_svg_bytes: int = 8 * 1024 * 1024
    max_warnings: int = 200

    @classmethod
    def from_settings(cls, s: Any) -> "VsdxLimits":
        """Build limits from the application Settings object (attribute names)."""
        mb = 1024 * 1024

        def _get(name: str, default: int) -> int:
            try:
                return int(getattr(s, name, default))
            except (TypeError, ValueError):
                return default

        return cls(
            max_file_bytes=_get("VSDX_MAX_FILE_MB", 20) * mb,
            max_total_uncompressed=_get("VSDX_MAX_TOTAL_MB", 80) * mb,
            max_entries=_get("VSDX_MAX_ENTRIES", 5000),
            max_pages=_get("VSDX_MAX_PAGES", 100),
            max_shapes_per_page=_get("VSDX_MAX_SHAPES_PER_PAGE", 5000),
            max_image_bytes=_get("VSDX_MAX_IMAGE_MB", 5) * mb,
            max_svg_bytes=_get("VSDX_MAX_SVG_MB", 8) * mb,
        )


class VsdxError(Exception):
    """User-facing parse failure; ``message`` is shown directly to the user."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    """Local XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


def _fmt(value: Any) -> str:
    """Format a number for SVG; never uses locale separators."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(f):
        return "0"
    text = f"{f:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _num(cells: Dict[str, str], name: str, default: float = 0.0) -> float:
    raw = cells.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _color(value: Optional[str], default: str) -> Tuple[str, bool]:
    """Convert a Visio color cell to #RRGGBB. Returns (color, used_theme)."""
    if not value:
        return default, False
    v = value.strip()
    if v.startswith("#"):
        return (v.upper(), False) if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else (default, False)
    m = re.fullmatch(r"RGB\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v, re.IGNORECASE)
    if m:
        r, g, b = (min(255, int(x)) for x in m.groups())
        return f"#{r:02X}{g:02X}{b:02X}", False
    if re.fullmatch(r"\d+", v):
        return default, True
    if re.fullmatch(r"[0-9A-Fa-f]{6}", v):
        return f"#{v.upper()}", False
    return default, False


def _opacity(cells: Dict[str, str], name: str) -> float:
    trans = _num(cells, name, 0.0)
    return max(0.0, min(1.0, 1.0 - trans / 100.0))


# ---------------------------------------------------------------------------
# Affine matrices: (a, b, c, d, e, f) == SVG matrix(a,b,c,d,e,f)
# ---------------------------------------------------------------------------

_Mat = Tuple[float, float, float, float, float, float]


def _mat_mul(a: _Mat, b: _Mat) -> _Mat:
    """Return a·b (b is applied first)."""
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


_IDENT: _Mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _translate(tx: float, ty: float) -> _Mat:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def _scale(sx: float, sy: float) -> _Mat:
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def _rotate(angle: float) -> _Mat:
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)


def _apply(m: _Mat, x: float, y: float) -> Tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _to_px(m_world: _Mat, page_height_in: float) -> _Mat:
    """Visio y-up inches -> SVG y-down px."""
    flipped = _mat_mul((1.0, 0.0, 0.0, -1.0, 0.0, page_height_in), m_world)
    return tuple(v * PX_PER_INCH for v in flipped)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ZIP / XML access (bounded)
# ---------------------------------------------------------------------------

def _is_allowed_part(name: str) -> bool:
    if name in (_PAGES_PART, _PAGES_RELS, _MASTERS_PART, _MASTERS_RELS):
        return True
    return bool(
        _RE_PAGE.fullmatch(name)
        or _RE_PAGE_REL.fullmatch(name)
        or _RE_MASTER.fullmatch(name)
        or _RE_MASTER_REL.fullmatch(name)
        or _RE_MEDIA.fullmatch(name)
    )


def _entry_name_ok(name: str) -> bool:
    if not name or name.startswith("/") or _RE_UNSAFE.search(name):
        return False
    return ".." not in name.split("/")


def _check_zip(zf: zipfile.ZipFile, limits: VsdxLimits) -> None:
    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        raise VsdxError("压缩包条目过多，无法安全预览", 413)
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > limits.max_entry_bytes:
            raise VsdxError("文件中的单个部件过大，无法安全预览", 413)
        if info.compress_size == 0 and info.file_size > 1024 * 1024:
            raise VsdxError("检测到异常的压缩数据，无法安全预览", 413)
        if total > limits.max_total_uncompressed:
            raise VsdxError("解压后体积过大，无法安全预览", 413)


def _read_entry(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    chunks: List[bytes] = []
    read_bytes = 0
    try:
        with zf.open(name) as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                read_bytes += len(chunk)
                if read_bytes > limit:
                    raise VsdxError("文件中的单个部件过大，无法安全预览", 413)
                chunks.append(chunk)
    except KeyError:
        raise VsdxError("文件缺少必要的内部部件")
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
        raise VsdxError("文件已损坏或使用了不支持的压缩方式")
    return b"".join(chunks)


def _load_xml(zf: zipfile.ZipFile, name: str, limits: VsdxLimits) -> ET.Element:
    raw = _read_entry(zf, name, limits.max_entry_bytes)
    head = raw[:65536].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise VsdxError("文件中包含不安全的 XML 声明，已拒绝解析")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise VsdxError("文件内部结构无法解析，可能不是有效的 .vsdx")


def _resolve_target(base_dir: str, target: str) -> Optional[str]:
    target = target.strip()
    if not target:
        return None
    if target.startswith("/"):
        name = target.lstrip("/")
    else:
        name = posixpath.normpath(posixpath.join(base_dir, target))
    if not _entry_name_ok(name) or not _is_allowed_part(name):
        return None
    return name


def _rel_map(
    zf: zipfile.ZipFile,
    rels_name: str,
    base_dir: str,
    names: set,
    limits: VsdxLimits,
) -> Dict[str, str]:
    if rels_name not in names:
        return {}
    root = _load_xml(zf, rels_name, limits)
    out: Dict[str, str] = {}
    for rel in root.iter():
        if _local(rel.tag) != "Relationship":
            continue
        rid, target = rel.get("Id"), rel.get("Target")
        if not rid or not target:
            continue
        name = _resolve_target(base_dir, target)
        if name and name in names:
            out[rid] = name
    return out


# ---------------------------------------------------------------------------
# ShapeSheet parsing
# ---------------------------------------------------------------------------

def _children(el: ET.Element, name: str) -> List[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _child(el: ET.Element, name: str) -> Optional[ET.Element]:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _cells(el: ET.Element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in el:
        if _local(c.tag) != "Cell":
            continue
        key = c.get("N")
        if key:
            out[key] = c.get("V") or ""
    return out


def _row_cells(row: ET.Element) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in row:
        if _local(c.tag) != "Cell":
            continue
        key = c.get("N")
        if key:
            out[key] = c.get("V") or ""
    return out


def _section_rows(el: ET.Element, section: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for sec in el:
        if _local(sec.tag) != "Section" or sec.get("N") != section:
            continue
        for row in sec:
            if _local(row.tag) == "Row":
                rows.append(_row_cells(row))
    return rows


def _geometry_rows(el: ET.Element) -> List[Tuple[str, Dict[str, str]]]:
    rows: List[Tuple[str, Dict[str, str]]] = []
    for sec in el:
        if _local(sec.tag) != "Section":
            continue
        if not (sec.get("N") or "").startswith("Geometry"):
            continue
        # Geometry sections flagged NoShow are construction/reference rows
        # Visio does not draw.
        if _num(_cells(sec), "NoShow") >= 0.5:
            continue
        for row in sec:
            if _local(row.tag) == "Row":
                rows.append((row.get("T") or "", _row_cells(row)))
    return rows


def _text_content(node: ET.Element) -> str:
    out: List[str] = []

    def walk(n: ET.Element) -> None:
        if n.text:
            out.append(n.text)
        for c in n:
            if _local(c.tag) == "pp":
                out.append("\n")
                if c.tail:
                    out.append(c.tail)
                continue
            walk(c)
            if c.tail:
                out.append(c.tail)

    walk(node)
    return "".join(out).strip()


def _shape_text(el: ET.Element) -> Optional[str]:
    node = _child(el, "Text")
    return None if node is None else _text_content(node)


def _foreign_rid(el: ET.Element) -> Optional[str]:
    node = _child(el, "ForeignData")
    if node is None:
        return None
    rid = node.get(_NS_R_ID) or node.get("r:id")
    if not rid:
        for c in node:
            if _local(c.tag) == "Rel":
                rid = c.get(_NS_R_ID) or c.get("r:id")
                break
    return rid


def _rel_rid(el: ET.Element) -> Optional[str]:
    for c in el:
        if _local(c.tag) == "Rel":
            return c.get(_NS_R_ID) or c.get("r:id")
    return None


@dataclass
class _ShapeData:
    cells: Dict[str, str]
    geo: List[Tuple[str, Dict[str, str]]]
    char: Dict[str, str]
    para: Dict[str, str]
    text: Optional[str]
    children: List[ET.Element]
    foreign: Optional[str]
    # Which relationship file resolves ``foreign``: None = the page rels,
    # otherwise the master ID whose rels file owns the image.
    foreign_scope: Optional[str] = None


def _read_shape(el: ET.Element) -> _ShapeData:
    chars = _section_rows(el, "Character")
    paras = _section_rows(el, "Paragraph")
    kids: List[ET.Element] = []
    shapes = _child(el, "Shapes")
    if shapes is not None:
        kids = [c for c in shapes if _local(c.tag) == "Shape"]
    return _ShapeData(
        cells=_cells(el),
        geo=_geometry_rows(el),
        char=chars[0] if chars else {},
        para=paras[0] if paras else {},
        text=_shape_text(el),
        children=kids,
        foreign=_foreign_rid(el),
    )


def _merge_shape(base: Optional[_ShapeData], inst: _ShapeData) -> _ShapeData:
    if base is None:
        return inst
    cells = dict(base.cells)
    for key, value in inst.cells.items():
        if value != "":
            cells[key] = value
    return _ShapeData(
        cells=cells,
        geo=inst.geo or base.geo,
        char=inst.char or base.char,
        para=inst.para or base.para,
        text=inst.text if inst.text else base.text,
        children=base.children + inst.children,
        foreign=inst.foreign or base.foreign,
        foreign_scope=inst.foreign_scope if inst.foreign else base.foreign_scope,
    )


# ---------------------------------------------------------------------------
# Rendering context
# ---------------------------------------------------------------------------

class _Ctx:
    def __init__(
        self,
        zf: zipfile.ZipFile,
        names: set,
        limits: VsdxLimits,
        warnings: List[str],
        page_rels: Dict[str, str],
        masters: Dict[str, str],
        page_height_in: float,
    ):
        self.zf = zf
        self.names = names
        self.limits = limits
        self.warnings = warnings
        self.page_rels = page_rels
        self.masters = masters
        self.page_height_in = page_height_in
        self.count = 0
        self.depth = 0
        self._master_parts: Dict[str, Dict[str, _ShapeData]] = {}
        self._master_rels: Dict[str, Dict[str, str]] = {}
        self._media: Dict[str, Optional[str]] = {}
        self._warned_theme = False
        self._warned_curve = False
        self._warned_depth = False

    def warn(self, message: str) -> None:
        if len(self.warnings) < self.limits.max_warnings:
            self.warnings.append(message)

    def warn_once(self, message: str) -> None:
        if message not in self.warnings:
            self.warn(message)

    def master_rels(self, master_id: str) -> Dict[str, str]:
        """Relationships of masterN.xml, so pictures inside a stencil resolve."""
        if master_id in self._master_rels:
            return self._master_rels[master_id]
        rels: Dict[str, str] = {}
        part = self.masters.get(master_id) or ""
        m = _RE_MASTER.fullmatch(part)
        if m:
            rels_name = f"visio/masters/_rels/{posixpath.basename(part)}.rels"
            if _RE_MASTER_REL.fullmatch(rels_name) and rels_name in self.names:
                try:
                    rels = _rel_map(
                        self.zf, rels_name, "visio/masters", self.names, self.limits
                    )
                except VsdxError:
                    rels = {}
        self._master_rels[master_id] = rels
        return rels

    def master_shapes(self, master_id: str) -> Dict[str, _ShapeData]:
        if master_id in self._master_parts:
            return self._master_parts[master_id]
        result: Dict[str, _ShapeData] = {}
        part = self.masters.get(master_id)
        if part and part in self.names:
            try:
                root = _load_xml(self.zf, part, self.limits)
            except VsdxError:
                root = None
            if root is not None:
                container = _child(root, "Shapes")
                if container is not None:
                    first = True
                    for shape in container:
                        if _local(shape.tag) != "Shape":
                            continue
                        data = _read_shape(shape)
                        if data.foreign:
                            data.foreign_scope = master_id
                        sid = shape.get("ID") or ""
                        if sid:
                            result[sid] = data
                        if first:
                            result["__first__"] = data
                            first = False
        self._master_parts[master_id] = result
        return result

    def media_data_uri(
        self, rid: str, scope: Optional[str] = None
    ) -> Optional[str]:
        rels = self.page_rels if scope is None else self.master_rels(scope)
        part = rels.get(rid) or self.page_rels.get(rid)
        if not part or part not in self.names:
            return None
        if part in self._media:
            return self._media[part]
        uri: Optional[str] = None
        try:
            raw = _read_entry(self.zf, part, self.limits.max_image_bytes)
        except VsdxError:
            raw = b""
            self.warn("部分嵌入图片过大或无法读取，已跳过")
        mime = _sniff_image(raw) if raw else None
        if mime:
            uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        elif raw:
            kind = _unsupported_image_kind(raw)
            if kind == "emf":
                # Visio stores most stencil icons as EMF vector pictures; replay
                # them as SVG so browsers can show the real drawing.
                converted, partial = emf_to_svg(raw)
                if converted:
                    uri = (
                        "data:image/svg+xml;base64,"
                        + base64.b64encode(converted.encode("utf-8")).decode("ascii")
                    )
                    if partial:
                        self.warn_once(
                            "部分 EMF 矢量图含文字或位图层，已按可解析的矢量图形显示"
                        )
                else:
                    self.warn_once(
                        "部分 EMF 矢量图无法解析，已用虚线占位框标出"
                    )
            elif kind == "wmf":
                self.warn_once(
                    "部分图片为 WMF 矢量图，浏览器无法直接显示，已用虚线占位框标出"
                )
            elif kind == "tiff":
                self.warn_once(
                    "部分图片为 TIFF 格式，浏览器无法直接显示，已用虚线占位框标出"
                )
            else:
                self.warn_once("部分嵌入图片格式不受支持，已用虚线占位框标出")
        self._media[part] = uri
        return uri


def _sniff_image(raw: bytes) -> Optional[str]:
    """Return a browser-renderable MIME type for the embedded picture."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:2] == b"BM" and len(raw) > 26:
        return "image/bmp"
    head = raw[:4096].decode("utf-8", "ignore").lstrip("﻿ \t\r\n")
    if head.startswith("<svg") or "<svg" in head[:256]:
        return "image/svg+xml"
    return None


def _unsupported_image_kind(raw: bytes) -> str:
    """Classify pictures the browser cannot render, for an accurate warning."""
    if raw[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if raw[:4] == b"\x01\x00\x00\x00" and raw[40:44] == b" EMF":
        return "emf"
    if raw[:4] in (b"\x01\x00\x09\x00", b"\x02\x00\x09\x00"):
        return "emf"
    if raw[:4] == b"\xd7\xcd\xc6\x9a":
        return "wmf"
    return ""


# ---------------------------------------------------------------------------
# Path building
# ---------------------------------------------------------------------------

class _Path:
    def __init__(self, m: _Mat):
        self.m = m
        self.parts: List[str] = []
        self.cur: Optional[Tuple[float, float]] = None
        self.start: Optional[Tuple[float, float]] = None
        self.base: Optional[Tuple[float, float]] = None

    def _pt(self, x: float, y: float) -> Tuple[float, float]:
        return _apply(self.m, x, y)

    def move(self, x: float, y: float) -> None:
        px, py = self._pt(x, y)
        self.parts.append(f"M {_fmt(px)} {_fmt(py)}")
        self.cur = (x, y)
        if self.start is None:
            self.start = (x, y)
            self.base = (x, y)

    def line(self, x: float, y: float) -> None:
        if self.cur is None:
            self.move(x, y)
            return
        px, py = self._pt(x, y)
        self.parts.append(f"L {_fmt(px)} {_fmt(py)}")
        self.cur = (x, y)

    def quad(self, cx: float, cy: float, x: float, y: float) -> None:
        if self.cur is None:
            self.move(x, y)
            return
        c_px = self._pt(cx, cy)
        p_px = self._pt(x, y)
        self.parts.append(
            f"Q {_fmt(c_px[0])} {_fmt(c_px[1])} {_fmt(p_px[0])} {_fmt(p_px[1])}"
        )
        self.cur = (x, y)

    def close(self) -> None:
        if self.start is not None:
            px, py = self._pt(*self.start)
            self.parts.append(f"L {_fmt(px)} {_fmt(py)} Z")

    def d(self) -> str:
        return " ".join(self.parts)


def _bow_point(
    cur: Tuple[float, float], end: Tuple[float, float], bow: float
) -> Tuple[float, float]:
    """Quadratic control point that bulges ``bow`` inches from the chord mid."""
    mx, my = (cur[0] + end[0]) / 2.0, (cur[1] + end[1]) / 2.0
    dx, dy = end[0] - cur[0], end[1] - cur[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return mx, my
    nx, ny = -dy / length, dx / length
    return mx + 2.0 * bow * nx, my + 2.0 * bow * ny


def _build_geometry(
    rows: List[Tuple[str, Dict[str, str]]],
    cells: Dict[str, str],
    path: _Path,
    ctx: _Ctx,
) -> None:
    width = _num(cells, "Width", 1.0)
    height = _num(cells, "Height", 1.0)

    for kind, row in rows:
        if kind == "MoveTo":
            path.move(_num(row, "X"), _num(row, "Y"))
        elif kind == "LineTo":
            path.line(_num(row, "X"), _num(row, "Y"))
        elif kind == "PolylineTo":
            raw = row.get("A") or ""
            for token in raw.split(";"):
                token = token.strip()
                if not token:
                    continue
                bits = [b for b in re.split(r"[,\s]+", token) if b]
                if len(bits) >= 2:
                    try:
                        path.line(float(bits[0]), float(bits[1]))
                    except ValueError:
                        continue
            path.line(_num(row, "X"), _num(row, "Y"))
        elif kind == "ArcTo":
            end = (_num(row, "X"), _num(row, "Y"))
            if path.cur is None:
                path.move(*end)
                continue
            cx, cy = _bow_point(path.cur, end, _num(row, "A"))
            path.quad(cx, cy, end[0], end[1])
            if not ctx._warned_curve:
                ctx._warned_curve = True
                ctx.warn("部分图形为近似显示（弧线与样条曲线）")
        elif kind in ("EllipticalArcTo", "RelEllipticalArcTo"):
            end = (_num(row, "X"), _num(row, "Y"))
            if kind.startswith("Rel") and path.base is not None:
                end = (path.base[0] + end[0], path.base[1] + end[1])
            if path.cur is None:
                path.move(*end)
                continue
            cx, cy = _bow_point(path.cur, end, _num(row, "C"))
            path.quad(cx, cy, end[0], end[1])
            if not ctx._warned_curve:
                ctx._warned_curve = True
                ctx.warn("部分图形为近似显示（弧线与样条曲线）")
        elif kind == "NURBSTo":
            end = (_num(row, "X"), _num(row, "Y"))
            path.line(*end)
            if not ctx._warned_curve:
                ctx._warned_curve = True
                ctx.warn("部分图形为近似显示（弧线与样条曲线）")
        elif kind == "SplineStart":
            start = (_num(row, "X"), _num(row, "Y"))
            if path.cur is None:
                path.move(*start)
            else:
                path.line(*start)
            if not ctx._warned_curve:
                ctx._warned_curve = True
                ctx.warn("部分图形为近似显示（弧线与样条曲线）")
        elif kind == "SplineKnot":
            path.line(_num(row, "X"), _num(row, "Y"))
        elif kind == "SplineEnd":
            continue
        elif kind in ("RelMoveTo", "RelLineTo", "RelQuadBezTo", "RelCubBezTo"):
            base = path.base or (0.0, 0.0)
            point = (base[0] + _num(row, "X"), base[1] + _num(row, "Y"))
            if kind == "RelMoveTo" and path.cur is None:
                path.move(*point)
            else:
                path.line(*point)
        elif kind == "Rectangle":
            x0, y0 = _num(row, "X0"), _num(row, "Y0")
            x1, y1 = _num(row, "X1", width), _num(row, "Y1", height)
            path.move(x0, y0)
            path.line(x1, y0)
            path.line(x1, y1)
            path.line(x0, y1)
            path.close()
        elif kind == "Ellipse":
            cx = _num(row, "X", width / 2.0)
            cy = _num(row, "Y", height / 2.0)
            rx = _num(row, "A", width / 2.0)
            ry = _num(row, "B", height / 2.0)
            first = True
            for i in range(49):
                theta = 2.0 * math.pi * i / 48.0
                x = cx + rx * math.cos(theta)
                y = cy + ry * math.sin(theta)
                if first:
                    path.move(x, y)
                    first = False
                else:
                    path.line(x, y)
            path.close()
        elif kind in ("NoFill", "NoLine", "NoShow"):
            # Style markers on a sub-path, not drawable segments.
            continue
        elif kind:
            ctx.warn(f"未知的图形类型 {kind} 已跳过")


# ---------------------------------------------------------------------------
# Shape rendering
# ---------------------------------------------------------------------------

def _render_shape(
    el: ET.Element, parent_m: _Mat, ctx: _Ctx, scope: Optional[str] = None
) -> str:
    if ctx.depth >= ctx.limits.max_depth:
        if not ctx._warned_depth:
            ctx._warned_depth = True
            ctx.warn("图形嵌套层级过深，部分内容已跳过")
        return ""

    ctx.count += 1
    if ctx.count > ctx.limits.max_shapes_per_page:
        raise VsdxError("单页图形数量超过上限，无法安全预览", 413)

    inst = _read_shape(el)
    if scope is not None:
        inst.foreign_scope = scope
    data = inst
    master_id = el.get("Master")
    if master_id:
        masters = ctx.master_shapes(master_id)
        # MasterShape names the sub-shape the instance inherits from; without
        # it the master's first (root) shape is the definition.
        base = masters.get(el.get("MasterShape") or "") or masters.get("__first__")
        data = _merge_shape(base, inst)
    page_child_ids = {id(c) for c in inst.children}

    cells = data.cells
    pin_x = _num(cells, "PinX")
    pin_y = _num(cells, "PinY")
    width = _num(cells, "Width", 1.0)
    height = _num(cells, "Height", 1.0)
    loc_x = _num(cells, "LocPinX", width / 2.0)
    loc_y = _num(cells, "LocPinY", height / 2.0)
    angle = _num(cells, "Angle")
    flip_x = -1.0 if _num(cells, "FlipX") >= 0.5 else 1.0
    flip_y = -1.0 if _num(cells, "FlipY") >= 0.5 else 1.0

    local = _mat_mul(
        _translate(pin_x, pin_y),
        _mat_mul(
            _rotate(angle),
            _mat_mul(_scale(flip_x, flip_y), _translate(-loc_x, -loc_y)),
        ),
    )
    world = _mat_mul(parent_m, local)
    px = _to_px(world, ctx.page_height_in)

    svg: List[str] = []

    has_begin = all(k in cells for k in ("BeginX", "BeginY", "EndX", "EndY"))
    if has_begin and not data.geo:
        bx = _num(cells, "BeginX") * PX_PER_INCH
        by = (ctx.page_height_in - _num(cells, "BeginY")) * PX_PER_INCH
        ex = _num(cells, "EndX") * PX_PER_INCH
        ey = (ctx.page_height_in - _num(cells, "EndY")) * PX_PER_INCH
        stroke, stroke_theme = _color(cells.get("LineColor"), "#000000")
        if stroke_theme and not ctx._warned_theme:
            ctx._warned_theme = True
            ctx.warn("部分颜色使用 Visio 主题配色，已用默认颜色显示")
        width_px = max(0.5, _num(cells, "LineWeight", 0.01) * PX_PER_INCH)
        if _num(cells, "LinePattern", 1.0) != 0:
            svg.append(
                f'<line x1="{_fmt(bx)}" y1="{_fmt(by)}" x2="{_fmt(ex)}" y2="{_fmt(ey)}" '
                f'stroke="{stroke}" stroke-width="{_fmt(width_px)}" '
                f'stroke-opacity="{_fmt(_opacity(cells, "LineColorTrans"))}"/>'
            )
    elif data.geo:
        path = _Path(px)
        _build_geometry(data.geo, cells, path, ctx)
        d = path.d()
        if d:
            fill_pattern = _num(cells, "FillPattern", 0.0)
            fill = "none"
            if fill_pattern != 0:
                color, theme = _color(cells.get("FillForegnd"), "#FFFFFF")
                if theme and not ctx._warned_theme:
                    ctx._warned_theme = True
                    ctx.warn("部分颜色使用 Visio 主题配色，已用默认颜色显示")
                fill = color
            line_pattern = _num(cells, "LinePattern", 1.0)
            stroke = "none"
            stroke_px = 0.0
            if line_pattern != 0:
                stroke, theme = _color(cells.get("LineColor"), "#000000")
                if theme and not ctx._warned_theme:
                    ctx._warned_theme = True
                    ctx.warn("部分颜色使用 Visio 主题配色，已用默认颜色显示")
                stroke_px = max(0.5, _num(cells, "LineWeight", 0.01) * PX_PER_INCH)
            if fill != "none" or stroke != "none":
                attrs = [f'd="{d}"', f'fill="{fill}"']
                if fill != "none":
                    attrs.append(f'fill-opacity="{_fmt(_opacity(cells, "FillForegndTrans"))}"')
                attrs.append(f'stroke="{stroke}"')
                if stroke != "none":
                    attrs.append(f'stroke-width="{_fmt(stroke_px)}"')
                    attrs.append(f'stroke-opacity="{_fmt(_opacity(cells, "LineColorTrans"))}"')
                svg.append(f"<path {' '.join(attrs)}/>")

    if data.foreign:
        uri = ctx.media_data_uri(data.foreign, data.foreign_scope)
        m = ", ".join(_fmt(v) for v in px)
        if uri:
            svg.append(
                f'<g transform="matrix({m})">'
                f'<g transform="translate(0,{_fmt(height)}) scale(1,-1)">'
                f'<image x="0" y="0" width="{_fmt(width)}" height="{_fmt(height)}" '
                f'preserveAspectRatio="none" href={quoteattr(uri)} xlink:href={quoteattr(uri)}/>'
                f"</g></g>"
            )
        else:
            # Keep the picture's footprint visible instead of silently dropping it.
            svg.append(
                f'<g transform="matrix({m})">'
                f'<rect x="0" y="0" width="{_fmt(width)}" height="{_fmt(height)}" '
                f'fill="none" stroke="#9CA3AF" stroke-width="0.02" '
                f'stroke-dasharray="0.08 0.06"/>'
                f"</g>"
            )

    if data.text:
        svg.append(_render_text(data, px, width, height))

    if data.children:
        ctx.depth += 1
        try:
            for child in data.children:
                # Shapes copied from the master resolve pictures against the
                # master's rels; shapes authored on the page keep the page rels.
                child_scope = (
                    scope if id(child) in page_child_ids else (master_id or scope)
                )
                svg.append(_render_shape(child, world, ctx, child_scope))
        finally:
            ctx.depth -= 1

    return "".join(svg)


def _render_text(data: _ShapeData, m: _Mat, width: float, height: float) -> str:
    text = data.text or ""
    if not text:
        return ""
    color, _ = _color(data.char.get("Color"), "#000000")
    size_px = max(6.0, _num(data.char, "Size", 0.1666) * PX_PER_INCH)
    style = int(_num(data.char, "Style"))
    # HorzAlign belongs to the Paragraph section; fall back to Character for
    # files that (incorrectly) place it there.
    align = int(_num(data.para, "HorzAlign", _num(data.char, "HorzAlign", 1.0)))
    angle = _num(data.cells, "TxtAngle")

    if align == 0:
        anchor, lx = "start", 0.02
    elif align == 2:
        anchor, lx = "end", width - 0.02
    else:
        anchor, lx = "middle", width / 2.0

    cx, cy = _apply(m, lx, height / 2.0)
    lines = text.split("\n")
    if not lines:
        return ""
    start_y = cy - (len(lines) - 1) * 0.6 * size_px

    attrs = [
        f'x="{_fmt(cx)}"',
        f'y="{_fmt(start_y)}"',
        f'fill="{color}"',
        f'font-size="{_fmt(size_px)}"',
        f'text-anchor="{anchor}"',
        'font-family="Microsoft YaHei, Arial, Helvetica, sans-serif"',
    ]
    if style & 1:
        attrs.append('font-weight="bold"')
    if style & 2:
        attrs.append('font-style="italic"')
    if style & 4:
        attrs.append('text-decoration="underline"')
    if abs(angle) > 1e-6:
        deg = -angle * 180.0 / math.pi
        attrs.append(f'transform="rotate({_fmt(deg)} {_fmt(cx)} {_fmt(start_y)})"')

    spans = []
    for i, line in enumerate(lines):
        dy = "0" if i == 0 else "1.2em"
        spans.append(f'<tspan x="{_fmt(cx)}" dy="{dy}">{escape(line)}</tspan>')
    return f"<text {' '.join(attrs)}>{''.join(spans)}</text>"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _page_dimensions(page: ET.Element) -> Tuple[float, float, bool]:
    sheet = _child(page, "PageSheet")
    if sheet is None:
        return 8.5, 11.0, True
    cells = _cells(sheet)
    width = _num(cells, "PageWidth", 8.5)
    height = _num(cells, "PageHeight", 11.0)
    if width <= 0 or height <= 0:
        return 8.5, 11.0, True
    return width, height, False


def _render_page(
    zf: zipfile.ZipFile,
    page: ET.Element,
    part: str,
    names: set,
    limits: VsdxLimits,
    warnings: List[str],
    masters: Dict[str, str],
) -> Dict[str, Any]:
    root = _load_xml(zf, part, limits)
    # Real Visio files carry PageSheet in pageN.xml; older/normalized files may
    # inline it on the <Page> element in pages.xml. Accept both.
    dims_source = page if _child(page, "PageSheet") is not None else root
    width_in, height_in, fallback = _page_dimensions(dims_source)
    if fallback:
        warnings.append("部分页面缺少页面尺寸，已按 A4 纵向显示")

    page_rels = _rel_map(
        zf, f"visio/pages/_rels/{posixpath.basename(part)}.rels", "visio/pages", names, limits
    )
    container = _child(root, "Shapes")

    ctx = _Ctx(zf, names, limits, warnings, page_rels, masters, height_in)
    body: List[str] = []
    if container is not None:
        for shape in container:
            if _local(shape.tag) != "Shape":
                continue
            body.append(_render_shape(shape, _IDENT, ctx))

    width_px = width_in * PX_PER_INCH
    height_px = height_in * PX_PER_INCH
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {_fmt(width_px)} {_fmt(height_px)}" '
        f'width="{_fmt(width_px)}" height="{_fmt(height_px)}" '
        'preserveAspectRatio="xMidYMid meet">'
        f'<rect x="0" y="0" width="{_fmt(width_px)}" height="{_fmt(height_px)}" fill="#FFFFFF"/>'
        + "".join(body)
        + "</svg>"
    )
    if len(svg.encode("utf-8")) > limits.max_svg_bytes:
        raise VsdxError("单页图形过大，无法安全预览", 413)

    return {
        "width": width_px,
        "height": height_px,
        "shape_count": ctx.count,
        "svg": svg,
    }


def _dedupe(items: List[str], cap: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_vsdx(data: bytes, file_name: str, limits: VsdxLimits) -> Dict[str, Any]:
    """Parse .vsdx bytes into ``{file_name, pages, warnings}``. Read-only."""
    if not data:
        raise VsdxError("文件为空")
    if len(data) > limits.max_file_bytes:
        raise VsdxError("文件超过大小上限", 413)
    if len(data) < 22 or data[:4] != b"PK\x03\x04":
        raise VsdxError("文件不是有效的 .vsdx（压缩包）文档")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError, EOFError):
        raise VsdxError("文件已损坏或不是有效的 .vsdx")

    warnings: List[str] = []
    try:
        _check_zip(zf, limits)
        names = {info.filename for info in zf.infolist()}
        if _PAGES_PART not in names:
            raise VsdxError("文件不是有效的 .vsdx：缺少页面索引")

        masters: Dict[str, str] = {}
        if _MASTERS_PART in names and _MASTERS_RELS in names:
            try:
                mroot = _load_xml(zf, _MASTERS_PART, limits)
                mrels = _rel_map(zf, _MASTERS_RELS, "visio/masters", names, limits)
            except VsdxError:
                mroot, mrels = None, {}
            if mroot is not None:
                for master in mroot:
                    if _local(master.tag) != "Master":
                        continue
                    mid, rid = master.get("ID"), _rel_rid(master)
                    if mid and rid and rid in mrels:
                        masters[mid] = mrels[rid]

        root = _load_xml(zf, _PAGES_PART, limits)
        page_els = [c for c in root if _local(c.tag) == "Page"]
        if not page_els:
            raise VsdxError("文件中没有可显示的页面")
        if len(page_els) > limits.max_pages:
            raise VsdxError("页面数量超过上限，无法安全预览", 413)

        page_rels = _rel_map(zf, _PAGES_RELS, "visio/pages", names, limits)

        pages: List[Dict[str, Any]] = []
        for index, page in enumerate(page_els):
            name = page.get("Name") or page.get("NameU") or f"第 {index + 1} 页"
            rid = _rel_rid(page)
            part = page_rels.get(rid) if rid else None
            if not part or part not in names:
                warnings.append(f"第 {index + 1} 页缺少页面数据，已跳过")
                continue
            rendered = _render_page(
                zf, page, part, names, limits, warnings, masters
            )
            pages.append(
                {
                    "index": len(pages),
                    "name": name,
                    "width": round(rendered["width"], 2),
                    "height": round(rendered["height"], 2),
                    "shape_count": rendered["shape_count"],
                    "svg": rendered["svg"],
                }
            )

        if not pages:
            raise VsdxError("文件中没有可显示的页面")
    finally:
        zf.close()

    return {
        "file_name": file_name,
        "pages": pages,
        "warnings": _dedupe(warnings, limits.max_warnings),
    }
