"""使用合成信号验证重整后的初检、预处理和切窗衔接。"""

import csv
import importlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mne
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "preprocessing"))
initial = importlib.import_module("03_check_signal_quality")
processing = importlib.import_module("04_preprocess_eeg")
windows = importlib.import_module("05_make_windows")
from config import CHANNELS, QCConfig, SignalConfig


def synthetic_raw(seconds=120, first_sample=123):
    generator = np.random.default_rng(2026)
    data = generator.normal(0, 20e-6, (19, seconds * 250))
    info = mne.create_info(CHANNELS, 250, "eeg")
    raw = mne.io.RawArray(data, info, first_samp=first_sample, verbose="ERROR")
    raw.set_montage("standard_1020")
    return raw


class PreprocessingPipelineTests(unittest.TestCase):
    def test_continuous_channel_rules_match_reference(self):
        with synthetic_raw(30, 0) as raw:
            raw._data[0] *= 100
            metrics = initial.window_metrics(raw._data, 2500)
            expected = (["Fp1"], {"Fp1": ["relative_high_rms"]})
            actual = initial.channel_bads(metrics, QCConfig(), True)
            self.assertEqual(actual, expected)
            self.assertIn("Fp1", actual[0])

    def test_configuration_controls_amplitude_decision(self):
        with synthetic_raw(30, 0) as raw:
            raw._data[0] *= 100
            metrics = initial.window_metrics(raw._data, 2500)
            relaxed = replace(
                QCConfig(), preliminary_high_rms_uv=1e9,
                preliminary_high_ptp_uv=1e9,
            )
            self.assertIn(
                "Fp1", initial.channel_bads(metrics, QCConfig(), True)[0]
            )
            self.assertNotIn(
                "Fp1", initial.channel_bads(metrics, relaxed, True)[0]
            )

    def test_boundary_window_not_used_in_channel_statistics(self):
        with synthetic_raw(30, 0) as raw:
            raw.annotations.append([10], [0], ["BAD boundary"])
            observed = []
            original = initial.window_metrics

            def capture(data, size, excluded=None):
                observed.append(excluded.copy())
                return original(data, size, excluded)

            initial.window_metrics = capture
            try:
                initial.gross_qc(raw, {"calibration": None}, QCConfig())
            finally:
                initial.window_metrics = original
            self.assertTrue(observed[0][0])
            self.assertTrue(observed[0][1])
            self.assertFalse(observed[0][2])

    def test_reference_anomaly_marking_preserves_waveform(self):
        with synthetic_raw(60, 0) as raw:
            raw._data[0, 2700] += 2e-3
            raw.set_eeg_reference("average", projection=False, verbose="ERROR")
            before = raw.get_data().copy()
            quality = processing.finalize_reference_segments(
                raw, {"bad_intervals_samples": []}, SignalConfig()
            )
            self.assertTrue(quality["final_bad_intervals_samples"])
            self.assertTrue(any("BAD_FINAL_QC" == value
                                for value in raw.annotations.description))
            np.testing.assert_array_equal(raw.get_data(), before)
            self.assertLess(quality["final_available_qc_windows"], 6)

    def test_full_processing_and_epoch_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            processed = temporary / "processed"
            processed.mkdir()
            scratch = temporary / "scratch"
            scratch.mkdir()
            source = temporary / "source_raw.fif"
            with synthetic_raw() as raw:
                raw.annotations.append(
                    [raw.first_time + 50], [0], ["BAD boundary"],
                    extras=[{"original_gap_seconds": 2.0}],
                )
                raw.save(
                    source, fmt="single", overwrite=False, verbose="ERROR"
                )
                samples = raw.n_times
            row = dict(
                code="TEST", status="preliminary_pass", n_samples=str(samples),
                fif_files=json.dumps([str(source)]), bad_channels="[]",
                bad_intervals_samples="[[12499, 12501]]",
            )
            checked = initial.inspect_record(row, scratch, QCConfig())
            self.assertEqual(checked["status"], "preliminary_pass")
            for key, value in checked.items():
                if isinstance(value, (list, dict)):
                    value = processing.encode(value)
                row[key] = value
            result = processing.process_record(
                row, SignalConfig(), scratch, processed
            )
            self.assertIn(result["status"], ("processed_pass", "needs_review"))
            for key in ("fif_files", "final_bad_intervals_samples"):
                result[key] = processing.encode(result[key])
            result["code"] = "TEST"
            epoch_folder = temporary / "epochs"
            epoch_folder.mkdir()
            exported = windows.make_record(
                result, epoch_folder, 10, 0, 60, processed
            )
            self.assertEqual(exported["status"], "completed")
            self.assertGreater(exported["selected_windows"], 0)
            self.assertEqual(exported["source_first_sample"], 123)

    def test_grouped_window_selection_has_no_duplicates(self):
        selected = windows.select_evenly(list(range(1000)), 60)
        self.assertEqual(len(selected), 60)
        self.assertEqual(len(set(selected)), 60)
        starts = windows.valid_starts(10000, 2500, 2500, [[2500, 5000]])
        self.assertEqual(starts, [0, 5000, 7500])


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reference_sensitive_raw():
    time = np.arange(30000) / 250
    common = np.sqrt(2) * 75e-6 * np.sin(2 * np.pi * time)
    data = np.empty((19, len(time)))
    data[0] = -common
    for channel in range(1, 19):
        data[channel] = common + (1 + channel / 5) * 1e-6 * np.sin(
            2 * np.pi * 5 * time + channel
        )
    info = mne.create_info(CHANNELS, 250, 'eeg')
    return mne.io.RawArray(data, info, verbose='ERROR')


def resume_fixture(directory):
    source = directory / 'source_raw.fif'
    with synthetic_raw() as raw:
        raw.save(source, fmt='single', verbose='ERROR')
        samples = raw.n_times
    row = dict(
        code='TEST', group='doc', guid='test-guid',
        status='preliminary_pass', n_samples=str(samples),
        fif_files=processing.encode([str(source)]),
        bad_channels='[]', bad_intervals_samples='[]',
    )
    master = directory / 'master.csv'
    table = directory / 'qc.csv'
    write_csv(master, [{'编号': 'TEST', 'GUID': 'test-guid'}])
    write_csv(table, [row])
    arguments = SimpleNamespace(
        master=master, qc_table=table, output_dir=directory / 'processed',
        resume_table=None,
    )
    arguments.output_dir.mkdir()
    folders = {'logs': directory}
    fingerprints = {str(path): processing.digest(path)
                    for path in (master, table)}
    hashes = {name: name for name in (
        '04_preprocess_eeg.py', '03_check_signal_quality.py', 'config.py'
    )}
    return row, arguments, folders, fingerprints, hashes


class ReviewRegressionTests(unittest.TestCase):
    def test_reference_can_reveal_persistent_bad_channel(self):
        with reference_sensitive_raw() as raw:
            metrics = initial.window_metrics(raw._data, 2500)
            self.assertEqual(initial.channel_bads(metrics, SignalConfig())[0],
                             [])
            raw.set_eeg_reference('average', projection=False, verbose='ERROR')
            quality = processing.finalize_reference_segments(
                raw, {'bad_intervals_samples': []}, SignalConfig()
            )
            self.assertEqual(quality['bad_channels'], ['Fp1'])
            self.assertEqual(quality['final_channel_reasons']['Fp1'],
                             ['relative_high_rms'])

    def test_bad_channel_after_reference_prevents_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'source_raw.fif'
            with reference_sensitive_raw() as raw:
                raw.save(source, fmt='single', verbose='ERROR')
                samples = raw.n_times
            row = dict(
                code='TEST', status='preliminary_pass', n_samples=samples,
                fif_files=processing.encode([str(source)]),
                bad_channels='[]', bad_intervals_samples='[]',
            )
            with patch.object(processing, 'publish_output') as publish:
                result = processing.process_record(
                    row, SignalConfig(), folder, folder
                )
            publish.assert_not_called()
            self.assertEqual(result['status'], 'excluded_bad_channels_04')
            self.assertEqual(result['bad_channels'], ['Fp1'])

    def test_partial_cohort_requires_explicit_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            master = folder / 'master.csv'
            table = folder / 'table.csv'
            write_csv(master, [
                {'编号': 'A', 'GUID': 'a'}, {'编号': 'B', 'GUID': 'b'}
            ])
            row = {'code': 'A', 'guid': 'a', 'status': 'preliminary_pass'}
            write_csv(table, [row])
            with self.assertRaisesRegex(ValueError, '缺少记录'):
                processing.read_qc_rows(table, master, None)
            selected = processing.read_qc_rows(table, master, ['A'])
            self.assertEqual(len(selected), 1)
            row['status'] = 'processed_pass'
            write_csv(table, [row])
            with self.assertRaisesRegex(ValueError, '缺少记录'):
                windows.read_inputs(table, master, None)
            self.assertEqual(len(windows.read_inputs(table, master, ['A'])[0]),
                             1)

    def test_duplicate_master_identifiers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            master = folder / 'master.csv'
            table = folder / 'table.csv'
            write_csv(master, [{'编号': 'A', 'GUID': 'a'}] * 2)
            write_csv(table, [{'code': 'A', 'guid': 'a',
                              'status': 'preliminary_pass'}])
            with self.assertRaisesRegex(ValueError, '编号重复'):
                processing.read_qc_rows(table, master, None)

    def test_verified_resume_reuses_waveform_without_filtering(self):
        with tempfile.TemporaryDirectory() as directory:
            row, arguments, folders, fingerprints, hashes = resume_fixture(
                Path(directory)
            )
            first = processing.process_one_record(
                row, folders, arguments, SignalConfig(), fingerprints, hashes
            )
            self.assertEqual(first['status'], 'processed_pass')
            first['source_fif_files'] = json.loads(first['source_fif_files'])
            waveform = Path(first['fif_files'][0])
            original_digest = processing.digest(waveform)
            processing.validate_resume_result(
                first, row, SignalConfig(), fingerprints, hashes
            )
            arguments.resume_table = Path(directory) / 'previous.csv'
            arguments.resume_table.write_text('test fixture')
            fingerprints[str(arguments.resume_table)] = 'resume-hash'
            with patch.object(processing, 'prepare_continuous') as prepare:
                resumed = processing.process_one_record(
                    row, folders, arguments, SignalConfig(), fingerprints,
                    hashes, first,
                )
            prepare.assert_not_called()
            self.assertEqual(resumed['status'], 'processed_pass')
            self.assertTrue(resumed['reused_filtered_fif'])
            self.assertEqual(processing.digest(waveform), original_digest)

    def test_resume_rejects_identity_parameter_or_input_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            row, arguments, folders, fingerprints, hashes = resume_fixture(
                Path(directory)
            )
            first = processing.process_one_record(
                row, folders, arguments, SignalConfig(), fingerprints, hashes
            )
            first['source_fif_files'] = json.loads(first['source_fif_files'])
            for field, value, reason in (
                ('guid', 'other-guid', 'GUID'),
                ('parameters', {}, '参数变化'),
                ('input_sha256', {}, '清单变化'),
            ):
                changed = dict(first, **{field: value})
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError, reason):
                        processing.validate_resume_result(
                            changed, row, SignalConfig(), fingerprints, hashes
                        )

    def test_resume_csv_roundtrip_preserves_input_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            row, arguments, folders, fingerprints, hashes = resume_fixture(
                Path(directory)
            )
            first = processing.process_one_record(
                row, folders, arguments, SignalConfig(), fingerprints, hashes
            )
            stored = {
                key: processing.encode(value)
                if isinstance(value, (list, dict)) else value
                for key, value in first.items()
            }
            arguments.resume_table = Path(directory) / 'previous.csv'
            write_csv(arguments.resume_table, [stored])
            previous = processing.read_resume_results(
                arguments, [row], SignalConfig(), fingerprints, hashes
            )
            self.assertEqual(previous['TEST']['source_fif_files'],
                             json.loads(row['fif_files']))
            self.assertEqual(previous['TEST']['input_sha256'], fingerprints)

    def test_window_outputs_are_separated_by_processing_batch(self):
        arguments = SimpleNamespace(
            base=Path('/data/example'),
            processed_dir=Path('/data/example/processed/20261014_v1'),
            window_seconds=10, overlap_seconds=0, max_windows=60,
            output_dir=None,
        )
        expected = Path('/data/example/epochs/20261014_v1/10s_60win_step10s')
        self.assertEqual(windows.window_output_directory(arguments), expected)
        arguments.output_dir = Path('/data/explicit_windows')
        self.assertEqual(windows.window_output_directory(arguments),
                         arguments.output_dir)


if __name__ == "__main__":
    unittest.main()
