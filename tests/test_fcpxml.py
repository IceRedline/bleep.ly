import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from censor.fcpxml import build_xml, rational_time
from censor.ffmpeg import timecode_seconds
from censor.models import MediaInfo, CensorRange


class FCPXMLTests(unittest.TestCase):
    def test_rational_time(self):
        self.assertEqual(rational_time(0.1), "1/10s")
        self.assertEqual(rational_time(Fraction(1001, 30000)), "1001/30000s")
        self.assertEqual(rational_time(12345 / 24000), "823/1600s")

    def test_xml_structure_and_timecode_offsets(self):
        info = MediaInfo(10, 0, 1, 1, 1920, 1080, Fraction(25), timecode=Fraction(3600))
        tree = build_xml(Path('/tmp/видео & "test".mov'), info, Path('/tmp/censor media'), [CensorRange(1.25, 1.75)])
        root = ET.fromstring(ET.tostring(tree.getroot()))
        primary = root.find(".//spine/asset-clip")
        self.assertEqual(primary.get("srcEnable"), "video")
        self.assertEqual(primary.get("start"), "3600/1s")
        clips = primary.findall("asset-clip")
        self.assertEqual([c.get("lane") for c in clips], ["-1", "-2"])
        self.assertEqual(clips[1].get("offset"), "14405/4s")
        self.assertEqual(clips[1].get("duration"), "1/2s")
        ids = {r.get("id") for r in root.find("resources")}
        self.assertTrue(all(c.get("ref") in ids for c in root.iter("asset-clip")))
        self.assertIn("%26", root.find("resources/asset/media-rep").get("src"))

    def test_ntsc_and_drop_frame(self):
        fps = Fraction(30000, 1001)
        self.assertEqual(timecode_seconds("01:00:00:00", Fraction(25)), 3600)
        self.assertEqual(timecode_seconds("00:01:00;02", fps), Fraction(1800, 1) / fps)
        info = MediaInfo(1001 / 300, 0, 1, 1, 1920, 1080, fps)
        root = build_xml(Path('/tmp/a.mov'), info, Path('/tmp/media'), []).getroot()
        self.assertEqual(root.find('resources/format').get('frameDuration'), "1001/30000s")
