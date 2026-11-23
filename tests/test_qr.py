import pytest

from treetrack import qr, qrgen


def to_image(grid, scale=10):
    from PIL import Image

    size = len(grid) * scale
    image = Image.new("L", (size, size), 255)
    pixels = image.load()
    for row, values in enumerate(grid):
        for col, value in enumerate(values):
            if value:
                for dy in range(scale):
                    for dx in range(scale):
                        pixels[col * scale + dx, row * scale + dy] = 0
    return image


def decode(grid):
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    image = to_image(grid)
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(numpy.array(image))
    return data


def test_matrix_has_a_four_module_quiet_zone():
    grid = qrgen.matrix("http://localhost:8765/t/wattle-1")
    assert len(grid) >= 29
    assert all(value == 0 for value in grid[0])
    assert all(value == 0 for value in grid[-1])
    assert all(row[0] == 0 and row[1] == 0 for row in grid)


def test_svg_is_self_contained():
    markup = qrgen.svg("http://localhost:8765/t/wattle-1", 200)
    assert markup.startswith("<svg")
    assert 'width="200"' in markup
    assert 'role="img"' in markup
    assert "<path" in markup


def test_qr_decodes_with_opencv():
    payload = "https://example.org/t/the-corner-lilly-pilly"
    assert decode(qrgen.matrix(payload)) == payload


def test_long_url_decodes():
    payload = "https://treetrack.example.org/t/a-tree-with-a-long-name-" + "x" * 40
    assert decode(qrgen.matrix(payload)) == payload


def test_pure_python_fallback_for_a_short_payload():
    payload = "http://localhost:8765/t/wattle-1"
    assert decode(qr.matrix(payload)) == payload