"""A small QR code encoder with no dependencies.

Byte mode, versions 1 to 5, error correction level L. That covers a URL of
about 100 characters, which is enough for a public tree page. The encoder
builds the matrix directly, so the caller can render SVG or a PNG.
"""

from __future__ import annotations

VERSIONS = {
    1: {"size": 21, "data": 19, "ecc": 7},
    2: {"size": 25, "data": 34, "ecc": 10},
    3: {"size": 29, "data": 55, "ecc": 15},
    4: {"size": 33, "data": 80, "ecc": 20},
    5: {"size": 37, "data": 108, "ecc": 26},
}

ECC_L_BITS = 0b01


def _make_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for index in range(255):
        exp[index] = value
        log[value] = index
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for index in range(255, 512):
        exp[index] = exp[index - 255]
    return exp, log


_EXP, _LOG = _make_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _poly_mul(left: list[int], right: list[int]) -> list[int]:
    out = [0] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        if a == 0:
            continue
        for j, b in enumerate(right):
            out[i + j] ^= _mul(a, b)
    return out


def _generator(count: int) -> list[int]:
    poly = [1]
    for index in range(count):
        poly = _poly_mul(poly, [1, _EXP[index]])
    return poly


def _remainder(data: list[int], count: int) -> list[int]:
    gen = _generator(count)
    work = list(data) + [0] * count
    for i in range(len(data)):
        lead = work[i]
        if lead == 0:
            continue
        for j, coefficient in enumerate(gen):
            work[i + j] ^= _mul(coefficient, lead)
    return work[-count:]


def _choose_version(payload: bytes) -> int:
    need = 4 + 8 + len(payload) * 8
    for version, spec in VERSIONS.items():
        if need <= spec["data"] * 8:
            return version
    raise ValueError("Payload is too long for a version 5 QR code.")


def _data_codewords(payload: bytes, version: int) -> list[int]:
    capacity = VERSIONS[version]["data"] * 8
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    put(0b0100, 4)
    put(len(payload), 8)
    for byte in payload:
        put(byte, 8)
    bits.extend([0] * min(4, max(0, capacity - len(bits))))
    while len(bits) % 8:
        bits.append(0)
    pad = [0xEC, 0x11]
    index = 0
    while len(bits) < capacity:
        put(pad[index % 2], 8)
        index += 1
    return [int("".join(str(bit) for bit in bits[i : i + 8]), 2) for i in range(0, len(bits), 8)]


class _Matrix:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = VERSIONS[version]["size"]
        self.mod = [[0] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set(self, row: int, col: int, dark: int, function: bool = True) -> None:
        if 0 <= row < self.size and 0 <= col < self.size:
            self.mod[row][col] = 1 if dark else 0
            self.fn[row][col] = function

    def add_finder(self, top: int, left: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                row, col = top + dr, left + dc
                if not (0 <= row < self.size and 0 <= col < self.size):
                    continue
                inner = 0 <= dr <= 6 and 0 <= dc <= 6
                dark = inner and (
                    dr in (0, 6)
                    or dc in (0, 6)
                    or (2 <= dr <= 4 and 2 <= dc <= 4)
                )
                self.set(row, col, dark)

    def add_alignment(self, center: int) -> None:
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                dark = max(abs(dr), abs(dc)) != 1
                self.set(center + dr, center + dc, dark)

    def add_timing(self) -> None:
        for index in range(8, self.size - 8):
            dark = index % 2 == 0
            self.set(6, index, dark)
            self.set(index, 6, dark)

    def add_patterns(self) -> None:
        self.add_finder(0, 0)
        self.add_finder(0, self.size - 7)
        self.add_finder(self.size - 7, 0)
        self.add_timing()
        if self.version >= 2:
            self.add_alignment(self.size - 7)
        # Reserve the format area, then the fixed dark module.
        for i in range(9):
            self.set(8, i, 0)
            self.set(i, 8, 0)
        for i in range(8):
            self.set(8, self.size - 1 - i, 0)
            self.set(self.size - 1 - i, 8, 0)
        self.set(self.size - 8, 8, 1)

    def add_format(self, mask: int) -> None:
        data = (ECC_L_BITS << 3) | mask
        value = data << 10
        while value.bit_length() - 1 >= 10:
            value ^= 0x537 << (value.bit_length() - 11)
        bits = ((data << 10) | value) ^ 0x5412
        for i in range(15):
            dark = (bits >> i) & 1
            if i < 6:
                self.set(i, 8, dark)
            elif i < 8:
                self.set(i + 1, 8, dark)
            else:
                self.set(self.size - 15 + i, 8, dark)
            if i < 8:
                self.set(8, self.size - 1 - i, dark)
            elif i < 9:
                self.set(8, 15 - i - 1 + 1, dark)
            else:
                self.set(8, 15 - i - 1, dark)

    def add_data(self, codewords: list[int], mask: int) -> None:
        bits: list[int] = []
        for word in codewords:
            for shift in range(7, -1, -1):
                bits.append((word >> shift) & 1)
        index = 0
        upward = True
        col = self.size - 1
        while col > 0:
            if col == 6:
                col -= 1
            row = self.size - 1 if upward else 0
            while 0 <= row < self.size:
                for c in (col, col - 1):
                    if self.fn[row][c]:
                        continue
                    dark = bits[index] if index < len(bits) else 0
                    index += 1
                    if _mask_bit(mask, row, c):
                        dark ^= 1
                    self.mod[row][c] = dark
                row += -1 if upward else 1
            upward = not upward
            col -= 2


def _mask_bit(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _penalty(modules: list[list[int]]) -> int:
    size = len(modules)
    score = 0
    # Rule 1: runs of five or more.
    for row in range(size):
        run = 1
        for col in range(1, size):
            if modules[row][col] == modules[row][col - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + run - 5
                run = 1
        if run >= 5:
            score += 3 + run - 5
    for col in range(size):
        run = 1
        for row in range(1, size):
            if modules[row][col] == modules[row - 1][col]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + run - 5
                run = 1
        if run >= 5:
            score += 3 + run - 5
    # Rule 2: two by two blocks.
    for row in range(size - 1):
        for col in range(size - 1):
            value = modules[row][col]
            if (
                modules[row][col + 1] == value
                and modules[row + 1][col] == value
                and modules[row + 1][col + 1] == value
            ):
                score += 3
    # Rule 3: finder-like patterns.
    pattern_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pattern_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for row in range(size):
        line = modules[row]
        for col in range(size - 10):
            window = line[col : col + 11]
            if window == pattern_a or window == pattern_b:
                score += 40
    for col in range(size):
        line = [modules[row][col] for row in range(size)]
        for start in range(size - 10):
            window = line[start : start + 11]
            if window == pattern_a or window == pattern_b:
                score += 40
    # Rule 4: balance of dark modules.
    dark = sum(sum(row) for row in modules)
    percent = dark * 100.0 / (size * size)
    score += 10 * int(abs(percent - 50) // 5)
    return score


def matrix(payload: str) -> list[list[int]]:
    """Return the QR matrix, including the quiet zone."""
    raw = payload.encode("utf-8")
    version = _choose_version(raw)
    spec = VERSIONS[version]
    codewords = _data_codewords(raw, version)
    ecc = _remainder(codewords, spec["ecc"])
    best: list[list[int]] | None = None
    best_score = None
    for mask in range(8):
        candidate = _Matrix(version)
        candidate.add_patterns()
        candidate.add_data(codewords + ecc, mask)
        candidate.add_format(mask)
        score = _penalty(candidate.mod)
        if best_score is None or score < best_score:
            best_score = score
            best = candidate.mod
    assert best is not None
    border = 4
    size = len(best) + border * 2
    out = [[0] * size for _ in range(size)]
    for row in range(len(best)):
        for col in range(len(best)):
            out[row + border][col + border] = best[row][col]
    return out


def svg(payload: str, pixels: int = 220, dark: str = "#14301c", light: str = "#ffffff") -> str:
    """Render the QR code as an SVG string."""
    grid = matrix(payload)
    size = len(grid)
    path: list[str] = []
    for row in range(size):
        col = 0
        while col < size:
            if grid[row][col]:
                start = col
                while col < size and grid[row][col]:
                    col += 1
                path.append(f"M{start} {row}h{col - start}v1H{start}z")
            else:
                col += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" height="{pixels}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code">'
        f'<rect width="{size}" height="{size}" fill="{light}"/>'
        f'<path d="{"".join(path)}" fill="{dark}"/>'
        "</svg>"
    )