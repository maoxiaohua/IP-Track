"""
Minimal Enhanced Metafile (EMF) to SVG converter.

Visio stores many stencil icons as embedded EMF vector pictures. Browsers
cannot render EMF, so this module replays the record subset Visio emits
(paths, brushes, pens, rectangles and the window/viewport transform) into a
standalone SVG document.

Only the records needed for drawing are handled. Anything else is reported to
the caller through the ``partial`` flag so the UI can say that part of a
picture was omitted instead of pretending it was complete.

Deliberately dependency-free and side-effect free: it only reads bytes.
"""
from __future__ import annotations

import math
import struct
from typing import Dict, List, Optional, Tuple

# Record types we act on (see [MS-EMF]).
_R_POLYBEZIER = 2
_R_POLYGON = 3
_R_POLYLINE = 4
_R_POLYBEZIERTO = 5
_R_POLYLINETO = 6
_R_POLYPOLYLINE = 7
_R_POLYPOLYGON = 8
_R_SETWINDOWEXTEX = 9
_R_SETWINDOWORGEX = 10
_R_SETVIEWPORTEXTEX = 11
_R_SETVIEWPORTORGEX = 12
_R_EOF = 14
_R_SETPIXELV = 15
_R_SETMAPMODE = 17
_R_SETBKMODE = 18
_R_SETPOLYFILLMODE = 19
_R_SETBKCOLOR = 25
_R_MOVETOEX = 27
_R_SAVEDC = 33
_R_RESTOREDC = 34
_R_SETWORLDTRANSFORM = 35
_R_MODIFYWORLDTRANSFORM = 36
_R_SELECTOBJECT = 37
_R_CREATEPEN = 38
_R_CREATEBRUSHINDIRECT = 39
_R_DELETEOBJECT = 40
_R_ELLIPSE = 42
_R_RECTANGLE = 43
_R_ROUNDRECT = 44
_R_ARC = 45
_R_CHORD = 46
_R_PIE = 47
_R_EXTTEXTOUTA = 53
_R_EXTTEXTOUTW = 54
_R_BEGINPATH = 59
_R_ENDPATH = 60
_R_CLOSEFIGURE = 61
_R_FILLPATH = 62
_R_STROKEANDFILLPATH = 63
_R_STROKEPATH = 64
_R_FLATTENPATH = 65
_R_WIDENPATH = 66
_R_SELECTCLIPPATH = 67
_R_ABORTPATH = 68
_R_GDICOMMENT = 70
_R_FILLRGN = 71
_R_FRAMERGN = 72
_R_INVERTRGN = 73
_R_PAINTRGN = 74
_R_EXTSELECTCLIPRGN = 75
_R_BITBLT = 76
_R_STRETCHBLT = 77
_R_MASKBLT = 78
_R_PLGBLT = 79
_R_SETDIBITSTODEVICE = 80
_R_STRETCHDIBITS = 81
_R_EXTCREATEFONTINDIRECTW = 82
_R_EXTTEXTOUTA_2 = 83
_R_EXTTEXTOUTW_2 = 84
_R_POLYBEZIER16 = 85
_R_POLYGON16 = 86
_R_POLYLINE16 = 87
_R_POLYBEZIERTO16 = 88
_R_POLYLINETO16 = 89
_R_POLYPOLYLINE16 = 90
_R_POLYPOLYGON16 = 91
_R_POLYDRAW16 = 92
_R_CREATEMONOBRUSH = 93
_R_CREATEDIBPATTERNBRUSHPT = 94
_R_EXTCREATEPEN = 95
_R_POLYTEXTOUTA = 96
_R_POLYTEXTOUTW = 97

_PS_NULL = 5
_BS_NULL = 1

# Stock objects selected by SELECTOBJECT with the high bit set.
_STOCK = {
    0: ("brush", 0, "#FFFFFF"),
    1: ("brush", 0, "#C0C0C0"),
    2: ("brush", 0, "#808080"),
    3: ("brush", 0, "#404040"),
    4: ("brush", 0, "#000000"),
    5: ("brush", _BS_NULL, "none"),
    6: ("pen", 0, 1.0, "#FFFFFF"),
    7: ("pen", 0, 1.0, "#000000"),
    8: ("pen", _PS_NULL, 1.0, "none"),
}

_DASH = {
    1: "3 2",
    2: "1 2",
    3: "3 2 1 2",
    4: "3 2 1 2 1 2",
}


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        value = 0.0
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _colorref(value: int) -> str:
    """COLORREF is 0x00BBGGRR."""
    return "#%02X%02X%02X" % (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def _i32(data: bytes, off: int, default: int = 0) -> int:
    if off + 4 > len(data):
        return default
    return struct.unpack_from("<i", data, off)[0]


def _points16(data: bytes, off: int, count: int) -> List[Tuple[int, int]]:
    pts: List[Tuple[int, int]] = []
    for _ in range(count):
        if off + 4 > len(data):
            break
        x, y = struct.unpack_from("<hh", data, off)
        pts.append((x, y))
        off += 4
    return pts


def _points32(data: bytes, off: int, count: int) -> List[Tuple[int, int]]:
    pts: List[Tuple[int, int]] = []
    for _ in range(count):
        if off + 8 > len(data):
            break
        x, y = struct.unpack_from("<ii", data, off)
        pts.append((x, y))
        off += 8
    return pts


class _Replay:
    """One EMF drawing pass."""

    def __init__(self, bx0: int, by0: int) -> None:
        self.bx0 = bx0
        self.by0 = by0
        self.output: List[str] = []
        self.partial = False
        self.win_org = (0, 0)
        self.win_ext = (0, 0)
        self.vp_org = (0, 0)
        self.vp_ext = (0, 0)
        # x' = a*x + c*y + e ; y' = b*x + d*y + f
        self.world = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.stack: List[Tuple[Tuple[float, ...], tuple, int]] = []
        self.objects: Dict[int, tuple] = {}
        self.pen: Optional[tuple] = None
        self.brush: Optional[tuple] = None
        self.fill_mode = 1
        self.bk_mode = 1
        self.bk_color = "#FFFFFF"
        self.path: List[tuple] = []
        self.in_path = False
        self.cur: Optional[Tuple[float, float]] = None
        self.start: Optional[Tuple[float, float]] = None
        self.drew = False

    # -- geometry ---------------------------------------------------------
    def to_device(self, x: float, y: float) -> Tuple[float, float]:
        a, b, c, d, e, f = self.world
        wx = a * x + c * y + e
        wy = b * x + d * y + f
        if self.win_ext[0] and self.vp_ext[0]:
            wx = (wx - self.win_org[0]) * self.vp_ext[0] / self.win_ext[0] + self.vp_org[0]
        if self.win_ext[1] and self.vp_ext[1]:
            wy = (wy - self.win_org[1]) * self.vp_ext[1] / self.win_ext[1] + self.vp_org[1]
        return wx, wy

    def _dev(self, pts: List[Tuple[int, int]]) -> List[Tuple[float, float]]:
        return [self.to_device(x, y) for x, y in pts]

    def move_to(self, x: float, y: float) -> None:
        pt = self.to_device(x, y)
        self.path.append(("M", pt))
        self.cur = pt
        self.start = pt

    def line_to(self, x: float, y: float) -> None:
        pt = self.to_device(x, y)
        if self.cur is None:
            self.path.append(("M", pt))
            self.start = pt
        else:
            self.path.append(("L", pt))
        self.cur = pt

    def close_figure(self) -> None:
        if self.cur is not None:
            self.path.append(("Z",))
            if self.start is not None:
                self.cur = self.start

    def bezier_to(self, pts: List[Tuple[int, int]]) -> None:
        dev = self._dev(pts)
        if self.cur is None and dev:
            self.path.append(("M", dev[0]))
            self.start = dev[0]
            self.cur = dev[0]
            dev = dev[1:]
        i = 0
        while i + 2 < len(dev):
            self.path.append(("C", dev[i], dev[i + 1], dev[i + 2]))
            self.cur = dev[i + 2]
            i += 3
        while i < len(dev):
            self.path.append(("L", dev[i]))
            self.cur = dev[i]
            i += 1

    def poly(self, pts: List[Tuple[int, int]], close: bool) -> None:
        dev = self._dev(pts)
        if not dev:
            return
        self.path.append(("M", dev[0]))
        self.start = dev[0]
        for pt in dev[1:]:
            self.path.append(("L", pt))
        self.cur = dev[-1]
        if close:
            self.path.append(("Z",))
            self.cur = self.start

    # -- painting ---------------------------------------------------------
    def _path_d(self) -> str:
        parts: List[str] = []
        value = ""
        for cmd in self.path:
            if cmd[0] in ("M", "L"):
                x, y = cmd[1]
                parts.append(f"{cmd[0]} {_fmt(x)} {_fmt(y)}")
            elif cmd[0] == "C":
                (x1, y1), (x2, y2), (x3, y3) = cmd[1], cmd[2], cmd[3]
                parts.append(
                    f"C {_fmt(x1)} {_fmt(y1)} {_fmt(x2)} {_fmt(y2)} {_fmt(x3)} {_fmt(y3)}"
                )
            elif cmd[0] == "Z":
                parts.append("Z")
        return " ".join(parts)

    def _style_attrs(self, fill: bool, stroke: bool) -> List[str]:
        attrs: List[str] = []
        brush = self.brush
        if fill and brush and brush[1] != _BS_NULL:
            attrs.append(f'fill="{brush[2]}"')
            if self.fill_mode == 2:
                attrs.append('fill-rule="evenodd"')
        else:
            attrs.append('fill="none"')
        pen = self.pen
        if stroke and pen and pen[1] != _PS_NULL:
            attrs.append(f'stroke="{pen[3]}"')
            attrs.append(f'stroke-width="{_fmt(pen[2])}"')
            dash = _DASH.get(pen[1])
            if dash:
                attrs.append(f'stroke-dasharray="{dash}"')
        else:
            attrs.append('stroke="none"')
        return attrs

    def paint_path(self, fill: bool, stroke: bool) -> None:
        if not self.path:
            return
        d = self._path_d()
        if d:
            attrs = self._style_attrs(fill, stroke)
            self.output.append(f'<path d="{d}" {" ".join(attrs)}/>')
            self.drew = True
        self.path = []
        self.cur = None
        self.start = None

    def paint_shape(self, bounds: Tuple[int, int, int, int], kind: str, extra: str = "") -> None:
        left, top, right, bottom = bounds
        x, y = self.to_device(left, top)
        x2, y2 = self.to_device(right, bottom)
        w = x2 - x
        h = y2 - y
        attrs = self._style_attrs(True, True)
        if kind == "rect":
            self.output.append(
                f'<rect x="{_fmt(min(x, x2))}" y="{_fmt(min(y, y2))}" '
                f'width="{_fmt(abs(w))}" height="{_fmt(abs(h))}" '
                f'{" ".join(attrs)}/>'
            )
        elif kind == "roundrect":
            self.output.append(
                f'<rect x="{_fmt(min(x, x2))}" y="{_fmt(min(y, y2))}" '
                f'width="{_fmt(abs(w))}" height="{_fmt(abs(h))}" '
                f'rx="{extra}" ry="{extra}" {" ".join(attrs)}/>'
            )
        else:
            self.output.append(
                f'<ellipse cx="{_fmt((x + x2) / 2)}" cy="{_fmt((y + y2) / 2)}" '
                f'rx="{_fmt(abs(w) / 2)}" ry="{_fmt(abs(h) / 2)}" '
                f'{" ".join(attrs)}/>'
            )
        self.drew = True

    def finish_direct(self, fill: bool) -> None:
        """Poly records paint immediately unless they sit inside a path bracket."""
        if not self.in_path:
            self.paint_path(fill, True)
    def select(self, raw: int) -> None:
        index = raw & 0x7FFFFFFF if raw < 0 else raw
        if raw < 0:
            obj = _STOCK.get(index)
        else:
            obj = self.objects.get(index)
        if obj is None:
            return
        if obj[0] == "brush":
            self.brush = obj
        else:
            self.pen = obj

    def save(self) -> None:
        self.stack.append(
            (
                self.world,
                self.brush,
                self.fill_mode,
            )
        )
        if self.pen is not None:
            self.stack[-1] = self.stack[-1] + (self.pen,)

    def restore(self) -> None:
        if not self.stack:
            return
        saved = self.stack.pop()
        self.world = saved[0]  # type: ignore[assignment]
        self.brush = saved[1]
        self.fill_mode = saved[2]
        if len(saved) > 3:
            self.pen = saved[3]


def _poly_poly_counts(
    body: bytes, npg: int, is16: bool
) -> Tuple[List[int], int]:
    """Locate the per-subpath point counts of a POLYPOLY* record.

    Visio writes an extra total-point-count DWORD after ``NumberOfPolygons``
    that the documented layout does not have, so pick whichever of the two
    candidate offsets makes the record size add up exactly.
    """
    step = 4 if is16 else 8
    fallback: Optional[Tuple[List[int], int]] = None
    for counts_off in (20, 24):
        counts = [_i32(body, counts_off + 4 * i) for i in range(npg)]
        if any(n < 0 for n in counts):
            continue
        pts_off = counts_off + 4 * npg
        total = sum(counts)
        if pts_off + step * total == len(body):
            return counts, pts_off
        if fallback is None and pts_off + step * total <= len(body):
            fallback = (counts, pts_off)
    if fallback is not None:
        return fallback
    return [], 20 + 4 * npg


def _apply_world(state: _Replay, data: bytes, off: int, mode: Optional[int]) -> None:
    if off + 24 > len(data):
        return
    m11, m12, m21, m22, dx, dy = struct.unpack_from("<6f", data, off)
    new = (m11, m12, m21, m22, dx, dy)
    a, b, c, d, e, f = state.world
    if mode is None or mode == 4:
        state.world = new
    elif mode == 1:
        state.world = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    elif mode == 2:
        # left multiply: new * world
        state.world = (
            m11 * a + m21 * b,
            m12 * a + m22 * b,
            m11 * c + m21 * d,
            m12 * c + m22 * d,
            m11 * e + m21 * f + dx,
            m12 * e + m22 * f + dy,
        )
    elif mode == 3:
        # right multiply: world * new
        state.world = (
            a * m11 + c * m12,
            b * m11 + d * m12,
            a * m21 + c * m22,
            b * m21 + d * m22,
            a * dx + c * dy + e,
            b * dx + d * dy + f,
        )


def emf_to_svg(raw: bytes) -> Tuple[Optional[str], bool]:
    """Convert EMF bytes to an SVG document.

    Returns ``(svg, partial)``. ``svg`` is ``None`` when the bytes are not an
    EMF this converter can replay. ``partial`` is True when records outside the
    supported subset were skipped, so the caller can warn honestly.
    """
    if len(raw) < 88:
        return None, False
    i_type, hdr_size = struct.unpack_from("<II", raw, 0)
    if i_type != 1 or raw[40:44] != b" EMF":
        return None, False
    bx0, by0, bx1, by1 = struct.unpack_from("<4i", raw, 8)
    width = bx1 - bx0
    height = by1 - by0
    if width <= 0 or height <= 0:
        return None, False

    state = _Replay(bx0, by0)
    off = hdr_size if 88 <= hdr_size <= len(raw) else 88

    while off + 8 <= len(raw):
        rtype, size = struct.unpack_from("<II", raw, off)
        if size < 8 or off + size > len(raw):
            break
        body = raw[off + 8 : off + size]

        if rtype == _R_EOF:
            break
        elif rtype == _R_SETMAPMODE:
            pass
        elif rtype == _R_SETWINDOWORGEX:
            state.win_org = (_i32(body, 0), _i32(body, 4))
        elif rtype == _R_SETWINDOWEXTEX:
            state.win_ext = (_i32(body, 0), _i32(body, 4))
        elif rtype == _R_SETVIEWPORTORGEX:
            state.vp_org = (_i32(body, 0), _i32(body, 4))
        elif rtype == _R_SETVIEWPORTEXTEX:
            state.vp_ext = (_i32(body, 0), _i32(body, 4))
        elif rtype == _R_SETPOLYFILLMODE:
            state.fill_mode = _i32(body, 0)
        elif rtype == _R_SETBKMODE:
            state.bk_mode = _i32(body, 0)
        elif rtype == _R_SETBKCOLOR:
            state.bk_color = _colorref(_i32(body, 0))
        elif rtype == _R_SELECTOBJECT:
            state.select(_i32(body, 0))
        elif rtype == _R_CREATEBRUSHINDIRECT:
            ih, style = _i32(body, 0), _i32(body, 4)
            state.objects[ih] = ("brush", style, _colorref(_i32(body, 8)))
        elif rtype == _R_DELETEOBJECT:
            state.objects.pop(_i32(body, 0), None)
        elif rtype == _R_CREATEPEN:
            ih, style, wx = _i32(body, 0), _i32(body, 4), _i32(body, 8)
            state.objects[ih] = ("pen", style, _pen_width(state, wx), _colorref(_i32(body, 16)))
        elif rtype == _R_EXTCREATEPEN:
            ih, style, wx = _i32(body, 0), _i32(body, 20), _i32(body, 24)
            color = _colorref(_i32(body, 32))
            state.objects[ih] = ("pen", style, _pen_width(state, wx), color)
        elif rtype in (_R_CREATEMONOBRUSH, _R_CREATEDIBPATTERNBRUSHPT):
            state.partial = True
        elif rtype == _R_SAVEDC:
            state.save()
        elif rtype == _R_RESTOREDC:
            state.restore()
        elif rtype == _R_SETWORLDTRANSFORM:
            _apply_world(state, body, 0, None)
        elif rtype == _R_MODIFYWORLDTRANSFORM:
            _apply_world(state, body, 0, _i32(body, 24))
        elif rtype == _R_MOVETOEX:
            state.move_to(_i32(body, 0), _i32(body, 4))
        elif rtype == _R_BEGINPATH:
            state.path = []
            state.cur = None
            state.start = None
            state.in_path = True
        elif rtype == _R_ENDPATH or rtype == _R_FLATTENPATH or rtype == _R_WIDENPATH:
            state.in_path = False
        elif rtype == _R_SELECTCLIPPATH:
            state.in_path = False
        elif rtype == _R_CLOSEFIGURE:
            state.close_figure()
        elif rtype == _R_FILLPATH:
            state.paint_path(True, False)
        elif rtype == _R_STROKEPATH:
            state.paint_path(False, True)
        elif rtype == _R_STROKEANDFILLPATH:
            state.paint_path(True, True)
        elif rtype == _R_ABORTPATH:
            state.path = []
            state.cur = None
            state.in_path = False
        elif rtype in (_R_POLYLINE16, _R_POLYLINETO16, _R_POLYLINE, _R_POLYLINETO):
            is16 = rtype in (_R_POLYLINE16, _R_POLYLINETO16)
            count = _i32(body, 16)
            pts = (
                _points16(body, 20, count)
                if is16
                else _points32(body, 20, count)
            )
            if rtype in (_R_POLYLINETO16, _R_POLYLINETO):
                for pt in pts:
                    state.line_to(*pt)
            else:
                state.poly(pts, False)
            state.finish_direct(False)
        elif rtype in (_R_POLYBEZIERTO16, _R_POLYBEZIERTO):
            is16 = rtype == _R_POLYBEZIERTO16
            count = _i32(body, 16)
            pts = _points16(body, 20, count) if is16 else _points32(body, 20, count)
            state.bezier_to(pts)
            state.finish_direct(False)
        elif rtype in (_R_POLYBEZIER16, _R_POLYBEZIER):
            is16 = rtype == _R_POLYBEZIER16
            count = _i32(body, 16)
            pts = _points16(body, 20, count) if is16 else _points32(body, 20, count)
            state.bezier_to(pts)
            state.finish_direct(False)
        elif rtype in (_R_POLYGON16, _R_POLYGON):
            is16 = rtype == _R_POLYGON16
            count = _i32(body, 16)
            pts = _points16(body, 20, count) if is16 else _points32(body, 20, count)
            state.poly(pts, True)
            state.finish_direct(True)
        elif rtype in (_R_POLYPOLYLINE16, _R_POLYPOLYGON16, _R_POLYPOLYLINE, _R_POLYPOLYGON):
            is16 = rtype in (_R_POLYPOLYLINE16, _R_POLYPOLYGON16)
            close = rtype in (_R_POLYPOLYGON16, _R_POLYPOLYGON)
            count = _i32(body, 16)
            counts, pts_off = _poly_poly_counts(body, max(0, min(count, 4096)), is16)
            p = 0
            for n in counts:
                if n < 0:
                    continue
                chunk = (
                    _points16(body, pts_off + p * 4, n)
                    if is16
                    else _points32(body, pts_off + p * 8, n)
                )
                p += n
                state.poly(chunk, close)
            state.finish_direct(close)
        elif rtype == _R_RECTANGLE:
            state.paint_shape(
                tuple(_i32(body, i * 4) for i in range(4)),  # type: ignore[arg-type]
                "rect",
            )
        elif rtype == _R_ELLIPSE:
            state.paint_shape(
                tuple(_i32(body, i * 4) for i in range(4)),  # type: ignore[arg-type]
                "ellipse",
            )
        elif rtype == _R_ROUNDRECT:
            corner = _fmt(abs(_i32(body, 16)))
            state.paint_shape(
                tuple(_i32(body, i * 4) for i in range(4)),  # type: ignore[arg-type]
                "roundrect",
                corner,
            )
        elif rtype in (_R_ARC, _R_CHORD, _R_PIE):
            state.partial = True
        elif rtype in (
            _R_SETPIXELV,
            _R_EXTTEXTOUTA,
            _R_EXTTEXTOUTW,
            _R_EXTTEXTOUTA_2,
            _R_EXTTEXTOUTW_2,
            _R_POLYTEXTOUTA,
            _R_POLYTEXTOUTW,
            _R_EXTCREATEFONTINDIRECTW,
            _R_FILLRGN,
            _R_FRAMERGN,
            _R_INVERTRGN,
            _R_PAINTRGN,
            _R_EXTSELECTCLIPRGN,
            _R_BITBLT,
            _R_STRETCHBLT,
            _R_MASKBLT,
            _R_PLGBLT,
            _R_SETDIBITSTODEVICE,
            _R_STRETCHDIBITS,
            _R_POLYDRAW16,
        ):
            state.partial = True
        # Everything else is bookkeeping (text colours, ROP codes, comments)
        # and does not change what is drawn.

        off += size

    if not state.drew:
        return None, state.partial

    background = ""
    if state.bk_mode == 2:
        background = (
            f'<rect x="{_fmt(bx0)}" y="{_fmt(by0)}" width="{_fmt(width)}" '
            f'height="{_fmt(height)}" fill="{state.bk_color}"/>'
        )
    # EMF device space is y-down while the picture is embedded by the page
    # renderer with a y-up flip, so mirror here to keep the icon upright.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'viewBox="{_fmt(bx0)} {_fmt(by0)} {_fmt(width)} {_fmt(height)}">'
        f'<g transform="translate(0,{_fmt(by0 + by1)}) scale(1,-1)">'
        f"{background}{''.join(state.output)}</g></svg>"
    )
    return svg, state.partial


def _pen_width(state: _Replay, logical: int) -> float:
    """Convert a LOGPEN width from logical units to device pixels."""
    wx = abs(logical)
    if not wx:
        return 1.0
    if state.win_ext[0] and state.vp_ext[0]:
        return max(0.05, wx * abs(state.vp_ext[0] / state.win_ext[0]))
    return float(wx)
