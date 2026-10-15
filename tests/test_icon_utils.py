"""Unit tests for icon_utils module."""

import unittest
from src.core.icon_utils import create_ico_from_pngs


class TestIconUtils(unittest.TestCase):
    def test_create_ico_from_pngs(self):
        # Minimal dummy PNG payload (8 bytes PNG signature + dummy data)
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        entries = [(32, dummy_png), (16, dummy_png)]
        
        ico_bytes = create_ico_from_pngs(entries)
        # Header must be 6 bytes (idReserved=0, idType=1, idCount=2)
        self.assertEqual(ico_bytes[:4], b"\x00\x00\x01\x00")
        self.assertEqual(ico_bytes[4:6], b"\x02\x00")
        # Total size: 6 (header) + 2*16 (dir entries) + 2*len(dummy_png)
        expected_size = 6 + 32 + len(dummy_png) * 2
        self.assertEqual(len(ico_bytes), expected_size)

    def test_qimage_to_ico_dib(self):
        try:
            from PySide6.QtGui import QImage, QColor
            from src.core.icon_utils import qimage_to_ico_dib
        except ImportError:
            self.skipTest("PySide6 not available")

        # Create a small 16x16 transparent image
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        dib = qimage_to_ico_dib(img)

        # Expected size: 40 (BITMAPINFOHEADER) + 16*16*4 (XOR mask) + 16*4 (AND mask) = 1128
        self.assertEqual(len(dib), 40 + 1024 + 64)
        # biSize must be 40
        import struct
        bi_size, width, height, planes, bit_count = struct.unpack("<IIIHH", dib[:16])
        self.assertEqual(bi_size, 40)
        self.assertEqual(width, 16)
        self.assertEqual(height, 32)  # Doubled in ICO format
        self.assertEqual(planes, 1)
        self.assertEqual(bit_count, 32)


if __name__ == "__main__":
    unittest.main()

