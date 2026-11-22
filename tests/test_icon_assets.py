import struct
import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]


class IconAssetTests(unittest.TestCase):
    def test_png_is_a_512_by_512_image(self):
        image = (ROOT / "openclaw-icon.png").read_bytes()

        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreaterEqual(len(image), 24)
        self.assertEqual(struct.unpack(">II", image[16:24]), (512, 512))

    def test_svg_is_well_formed_and_has_matching_dimensions(self):
        svg = ElementTree.parse(ROOT / "openclaw-icon.svg").getroot()

        self.assertEqual(
            svg.tag,
            "{http://www.w3.org/2000/svg}svg",
        )
        self.assertEqual(svg.attrib.get("width"), "512")
        self.assertEqual(svg.attrib.get("height"), "512")
        self.assertEqual(svg.attrib.get("viewBox"), "0 0 512 512")


if __name__ == "__main__":
    unittest.main()
