"""用合成EDF验证结构修复、负增益、事件和间断边界。"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import mne
import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "preprocessing"
SCRIPT = SCRIPT / "02_repair_edf_to_fif.py"
specification = importlib.util.spec_from_file_location("edf_converter", SCRIPT)
converter = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = converter
specification.loader.exec_module(converter)


def signal_bytes(labels: list[str]) -> bytes:
    values = {
        "label": labels, "transducer": [""] * len(labels),
        "unit": ["uV"] * len(labels),
        "physical_min": ["100" if name == "F3" else "-100"
                         for name in labels],
        "physical_max": ["-100" if name == "F3" else "100"
                         for name in labels],
        "digital_min": ["-32768"] * len(labels),
        "digital_max": ["32767"] * len(labels),
        "prefilter": [""] * len(labels),
        "samples": ["64" if name == "EDF Annotations" else "4"
                    for name in labels],
        "reserved": [""] * len(labels),
    }
    return b"".join(
        str(value).encode().ljust(width)
        for name, width in converter.SIGNAL_FIELDS for value in values[name]
    )


def make_header(labels: list[str]) -> bytes:
    fixed = bytearray(b" " * 256)
    fields = {
        (0, 8): b"0", (8, 88): b"TEST X X TEST",
        (88, 168): b"Startdate 01-JAN-2024 X X X",
        (168, 176): b"01.01.24", (176, 184): b"12.00.00",
        (184, 192): str(256 * (len(labels) + 1)).encode(),
        (192, 236): b"EDF+C", (236, 244): b"3",
        (244, 252): b"1", (252, 256): str(len(labels)).encode(),
    }
    for (start, stop), value in fields.items():
        fixed[start:stop] = value.ljust(stop - start)
    return bytes(fixed) + signal_bytes(labels)


def create_edf(path: Path, damaged: bool, discontinuous: bool) -> None:
    labels = list(converter.EEG_CHANNELS) + ["EDF Annotations"]
    header = make_header(labels)
    if damaged:
        header = bytearray(header[:88] + header[168:])
        header[236:244] = b"3".ljust(8)
    with path.open("wb") as stream:
        stream.write(header)
        for record, onset in enumerate([0, 1, 5 if discontinuous else 2]):
            for channel in range(19):
                stream.write((np.arange(4) + channel + record).astype("<i2"))
            marker = f"+{onset}\x14\x14\x00".encode()
            event = f"+{onset}.2\x150.5\x14测试\x14\x00".encode()
            stream.write((marker + event).ljust(128, b"\x00"))


class EDFConversionTests(unittest.TestCase):
    def test_standard_and_missing_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for damaged in (False, True):
                path = Path(directory) / f"source_{damaged}.edf"
                create_edf(path, damaged, False)
                header = converter.inspect_edf(path)
                self.assertEqual(header.missing_bytes, 80 if damaged else 0)
                self.assertEqual(header.record_count, 3)
                self.assertEqual(header.signals[3].label, "F4")
                self.assertEqual(header.signals[4].label, "C3")

    def test_negative_gain_gap_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.edf"
            create_edf(path, True, True)
            original = path.read_bytes()
            output = root / "fif"
            output.mkdir()
            row = {"编号": "TEST_001", "所在服务器位置": str(path)}
            result = converter.convert_record(row, output)
            self.assertEqual(result["gap_count"], 1)
            self.assertEqual(result["n_samples"], 12)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(output.rglob("*.edf")), [])
            raw = mne.io.read_raw_fif(
                output / "TEST_001_raw.fif", verbose="ERROR",
            )
            try:
                self.assertEqual(raw.ch_names, list(converter.EEG_CHANNELS))
                self.assertIn("BAD boundary", raw.annotations.description)
                self.assertIn("EDGE boundary", raw.annotations.description)
                self.assertEqual(len(raw.annotations), 5)
            finally:
                raw.close()

    def test_invalid_file_does_not_leave_temporary_edf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "invalid.edf"
            path.write_bytes(b"not-edf")
            output = root / "fif"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "版本签名"):
                converter.convert_record({
                    "编号": "TEST_002", "所在服务器位置": str(path),
                }, output)
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
