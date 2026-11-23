"""QR rendering for the tree sign.

OpenCV encodes long URLs reliably. The bundled pure-Python encoder is a
fallback for short payloads on a machine without OpenCV.
"""

from __future__ import annotations

from . import qr as pure

_CV = None
_TRIED = False


def _cv2():
    global _CV, _TRIED
    if not _TRIED:
        _TRIED = True
        try:
            import cv2

            _CV = cv2
        except Exception:
            _CV = None
    return _CV


def _core(payload: str) -> list[list[int]]:
    cv2 = _cv2()
    if cv2 is not None:
        params = cv2.QRCodeEncoder_Params()
        params.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_L
        params.mode = cv2.QRCodeEncoder_MODE_BYTE
        encoder = cv2.QRCodeEncoder_create(params)
        image = encoder.encode(payload)
        dark = (image < 128).astype("uint8")
        rows, cols = dark.nonzero()
        if len(rows):
            top, bottom = int(rows.min()), int(rows.max()) + 1
            left, right = int(cols.min()), int(cols.max()) + 1
            return [[int(value) for value in row] for row in dark[top:bottom, left:right]]
    grid = pure.matrix(payload)
    return [row[4:-4] for row in grid[4:-4]]


def matrix(payload: str) -> list[list[int]]:
    """Return the QR matrix with a four-module quiet zone."""
    core = _core(payload)
    border = 4
    size = len(core) + border * 2
    grid = [[0] * size for _ in range(size)]
    for row_index, row in enumerate(core):
        for col_index, value in enumerate(row):
            grid[row_index + border][col_index + border] = value
    return grid


def svg(payload: str, pixels: int = 220, dark: str = "#14301c", light: str = "#ffffff") -> str:
    grid = matrix(payload)
    size = len(grid)
    parts: list[str] = []
    for row in range(size):
        col = 0
        while col < size:
            if grid[row][col]:
                start = col
                while col < size and grid[row][col]:
                    col += 1
                parts.append(f"M{start} {row}h{col - start}v1H{start}z")
            else:
                col += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" height="{pixels}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code">'
        f'<rect width="{size}" height="{size}" fill="{light}"/>'
        f'<path d="{"".join(parts)}" fill="{dark}"/>'
        "</svg>"
    )