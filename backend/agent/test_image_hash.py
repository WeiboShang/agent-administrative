"""Tests for the perceptual image hash (offline — Pillow only, no key/model)."""
import io

from PIL import Image

from backend.agent.image_hash import dhash, hamming
from backend.evals.receipt_data import make_receipt_case


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _striped(size: tuple[int, int]) -> Image.Image:
    """A high-frequency vertical-stripe pattern — structurally unlike any receipt."""
    img = Image.new("L", size, "white")
    px = img.load()
    for x in range(size[0]):
        if (x // 8) % 2 == 0:
            for y in range(size[1]):
                px[x, y] = 0
    return img.convert("RGB")


def test_identical_image_zero_distance():
    img, _, _ = make_receipt_case("clean", 0)
    b = _png(img)
    h1, h2 = dhash(b), dhash(b)
    assert h1 is not None and hamming(h1, h2) == 0


def test_reframed_receipt_stays_within_threshold():
    """A re-photograph (small reframe/rescale) must land within a few Hamming bits — the
    near-duplicate the exact field-match rule misses."""
    img, _, _ = make_receipt_case("clean", 0)
    w, h = img.size
    reframed = img.crop((3, 3, w - 3, h - 3)).resize((w, h))
    d = hamming(dhash(_png(img)), dhash(_png(reframed)))
    assert d <= 6


def test_structurally_different_image_is_far():
    receipt, _, _ = make_receipt_case("clean", 1)
    near = receipt.crop((3, 3, receipt.width - 3, receipt.height - 3)).resize(receipt.size)
    d_near = hamming(dhash(_png(receipt)), dhash(_png(near)))
    d_diff = hamming(dhash(_png(receipt)), dhash(_png(_striped(receipt.size))))
    assert d_diff > 6 and d_diff > d_near


def test_unreadable_bytes_return_none():
    assert dhash(b"not an image") is None
