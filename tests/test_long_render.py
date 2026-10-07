import array
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from censor.audio import FADE, gain_expression
from censor.models import CensorRange


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class LongRenderTests(unittest.TestCase):
    def test_hundreds_of_ranges_preserve_envelope_including_overlapping_fades(self):
        # 350 ranges previously exceeded the parser recursion limit. Include a
        # 4 ms gap so adjacent 7 ms fades overlap, including across tree branches.
        ranges = [CensorRange(i * .03 + .004, i * .03 + .030) for i in range(350)]
        rate = 48000
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "envelope.ffgraph"
            for mode, db, floor in [("mute", -30, 0), ("duck", -30, 10 ** (-30 / 20))]:
                script.write_text(f"aevalsrc='{gain_expression(ranges, mode, db)}':s={rate}:d=10.6")
                result = subprocess.run(["ffmpeg", "-v", "error", "-filter_complex_script", str(script),
                                         "-f", "f32le", "-"], capture_output=True, check=True)
                data = array.array("f", result.stdout)
                for index in range(0, len(data), 71):
                    t = index / rate
                    amount = min(1, sum(max(0, min(1, (t - (r.start - FADE)) / FADE,
                                                          ((r.end + FADE) - t) / FADE)) for r in ranges))
                    self.assertAlmostEqual(data[index], 1 - (1 - floor) * amount, places=6)
