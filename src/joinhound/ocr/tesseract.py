# SPDX-License-Identifier: Apache-2.0

"""Read a page image with Tesseract."""

from __future__ import annotations

import io

import pytesseract
from PIL import Image


class TesseractOcrEngine:
    """OCR through the tesseract binary."""

    def recognize(self, image: bytes) -> str:
        """Return the text Tesseract reads from a PNG or JPEG page."""
        with Image.open(io.BytesIO(image)) as picture:
            return str(pytesseract.image_to_string(picture))
