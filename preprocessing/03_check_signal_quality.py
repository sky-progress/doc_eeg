"""03：检查原始19导FIF，确认坏导则排除整份，局部坏段只记录。"""
import argparse
import csv
import hashlib
import json
import math
import tempfile
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mne
import numpy as np
from mne.io.constants import FIFF

from config import (
    BASE, CHANNELS, CONVERSION_MANIFEST, MASTER, QCConfig, REFERENCE_VERSION
)
from reporting import write_report


def merge_intervals(intervals, n_times):
    n_times = int(n_times)
    result = []
    for start, stop in sorted(intervals):
        start, stop = (max(0, int(start)), min(n_times, int(stop)))
        if stop <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], stop)
        else:
            result.append([start, stop])
    return result


def complement(intervals, n_times):
    result, cursor = ([], 0)
    for start, stop in merge_intervals(intervals, n_times):
        if cursor < start:
            result.append([cursor, start])
        cursor = stop
    if cursor < n_times:
        result.append([cursor, n_times])
    return result


def mark_windows(mask, start, stop, window_samples):
    if stop <= start:
        return
    first_window = max(0, start // window_samples)
    last_window = min(len(mask), math.ceil(stop / window_samples))
    mask[first_window:last_window] = True


def annotations_relative(raw):
    annotations = []
    for onset, duration, description in zip(
        raw.annotations.onset,
        raw.annotations.duration,
        raw.annotations.description,
    ):
        annotations.append({
            "onset_seconds": float(onset - raw.first_time),
            "duration_seconds": float(duration),
            "description": str(description),
        })
    return annotations


def annotation_intervals(raw):
    sampling_frequency = float(raw.info["sfreq"])
    intervals = []
    for annotation in annotations_relative(raw):
        description = annotation["description"].lower()
        is_unusable = (
            description.startswith("bad")
            or description.startswith("edge")
            or "boundary" in description
        )
        if not is_unusable:
            continue
        onset = annotation["onset_seconds"]
        end = onset + annotation["duration_seconds"]
        start = math.floor(onset * sampling_frequency + 1e-7)
        stop = math.ceil(end * sampling_frequency - 1e-7)
        # 零时长边界也阻止窗口跨越采集间断。
        if stop <= start:
            start, stop = start - 1, start + 1
        intervals.append([start, stop])
    return merge_intervals(intervals, raw.n_times)


def window_metrics(data, window_samples, excluded=None):
    window_count = math.ceil(data.shape[1] / window_samples)
    metrics = {
        name: np.full((data.shape[0], window_count), np.nan)
        for name in ("ptp", "rms", "step")
    }
    for window_index in range(window_count):
        if excluded is not None and excluded[window_index]:
            continue
        start = window_index * window_samples
        stop = min(start + window_samples, data.shape[1])
        block = data[:, start:stop]
        finite_channels = np.isfinite(block).all(axis=1)
        block = block[finite_channels]
        if len(block) == 0:
            continue
        centered = block - block.mean(axis=1, keepdims=True)
        root_mean_square = np.sqrt(np.mean(centered ** 2, axis=1))
        maximum_step = 0
        if block.shape[1] > 1:
            maximum_step = np.max(np.abs(np.diff(block, axis=1)), axis=1)
        metrics["ptp"][finite_channels, window_index] = np.ptp(block, axis=1)
        metrics["rms"][finite_channels, window_index] = root_mean_square
        metrics["step"][finite_channels, window_index] = maximum_step
    return metrics


# MAD近零时不触发相对判据，避免稳定记录出现数值放大。
def robust_z(values):
    center = np.nanmedian(values)
    median_deviation = np.nanmedian(np.abs(values - center))
    if not np.isfinite(median_deviation) or median_deviation < 1e-12:
        return np.zeros_like(values)
    return 0.67448975 * (values - center) / median_deviation


def fraction_where(values, predicate):
    finite = np.isfinite(values)
    eligible_counts = np.sum(finite, axis=1)
    matched_counts = np.sum(predicate(values) & finite, axis=1)
    return np.divide(
        matched_counts,
        eligible_counts,
        out=np.zeros(values.shape[0]),
        where=eligible_counts > 0,
    )


def channel_reason_map(
    flat, high, jumps, median_rms, amp_z, high_z, step_z, config, preliminary
):
    high_score_limit = config.high_rms_z
    high_rms_limit = config.high_rms_uv
    if preliminary:
        high_score_limit = config.preliminary_high_rms_z
        high_rms_limit = config.preliminary_high_rms_uv
    high_rms_limit *= 1e-6
    relative_flat_limit = np.median(flat) + config.flat_relative_fraction
    reasons = {}
    for channel_index, channel_name in enumerate(CHANNELS):
        channel_reasons = []
        is_relative_flat = (
            flat[channel_index] >= config.flat_min_fraction
            and flat[channel_index] > relative_flat_limit
        )
        is_frequent_extreme = (
            high[channel_index] >= config.high_min_fraction
            and high_z[channel_index] > config.high_fraction_z
        )
        if is_relative_flat:
            channel_reasons.append("persistent_relative_flat")
        if is_frequent_extreme:
            channel_reasons.append("relative_frequent_extreme_amplitude")
        if (
            amp_z[channel_index] > high_score_limit
            and median_rms[channel_index] > high_rms_limit
        ):
            channel_reasons.append("relative_high_rms")
        if (
            amp_z[channel_index] < config.low_rms_z
            and median_rms[channel_index] < config.low_rms_uv * 1e-6
        ):
            channel_reasons.append("relative_low_rms")
        if (
            not preliminary
            and step_z[channel_index] > config.step_noise_z
            and jumps[channel_index] > config.jump_min_fraction
        ):
            channel_reasons.append("relative_step_noise")
        if channel_reasons:
            reasons[channel_name] = channel_reasons
    return reasons


def channel_statistics(ptp, rms, step, config, preliminary):
    flat = fraction_where(ptp, lambda value: value < config.flat_ptp_uv * 1e-6)
    amplitude_limit = config.high_ptp_uv
    if preliminary:
        amplitude_limit = config.preliminary_high_ptp_uv
    high = fraction_where(ptp, lambda value: value > amplitude_limit * 1e-6)
    jumps = fraction_where(step, lambda value: value > config.jump_uv * 1e-6)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median_rms = np.nanmedian(rms, axis=1)
        step_ratio = np.nanmedian(step / np.maximum(rms, 1e-15), axis=1)
    amplitude_score = robust_z(np.log10(median_rms + 1e-15))
    high_fraction_score = robust_z(high)
    step_score = robust_z(np.log10(step_ratio + 1e-12))
    return (
        flat, high, jumps, median_rms,
        amplitude_score, high_fraction_score, step_score,
    )


def channel_bads(metrics, config, preliminary=False):
    peak_to_peak = metrics["ptp"]
    root_mean_square = metrics["rms"]
    maximum_step = metrics["step"]
    if not np.isfinite(root_mean_square).any():
        return [], {}
    statistics = channel_statistics(
        peak_to_peak, root_mean_square, maximum_step, config, preliminary
    )
    reasons = channel_reason_map(*statistics, config, preliminary)
    return list(reasons), reasons


def true_runs(mask, min_samples):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    return [
        [int(start), int(stop)]
        for start, stop in zip(starts, stops)
        if stop - start >= min_samples
    ]


# 只有源数字标定明确时才能判断饱和，FIF输入不推测量程。
def mark_saturation(data, source_metadata, config, sfreq, size, reasons):
    calibration = source_metadata.get('calibration')
    if calibration:
        for index, cal in enumerate(calibration):
            low = np.isclose(
                data[index], cal['physical_min_v'], rtol=0, atol=1e-12
            )
            high = np.isclose(
                data[index], cal['physical_max_v'], rtol=0, atol=1e-12
            )
            for mask in (low, high):
                for start, stop in true_runs(
                    mask,
                    max(1, math.ceil(config.saturation_min_seconds * sfreq))
                ):
                    mark_windows(
                        reasons['digital_saturation'], start, stop, size
                    )
    return calibration


def mark_flat_candidates(data, metrics, config, sfreq, size, count, reasons):
    for window_index in range(count):
        start = window_index * size
        stop = min(start + size, data.shape[1])
        block = data[:, start:stop]
        peak_to_peak = metrics["ptp"][:, window_index]
        reasons["nonfinite"][window_index] = not np.isfinite(block).all()
        reasons["flat_candidate"][window_index] = bool(
            np.any(peak_to_peak < config.flat_ptp_uv * 1e-6)
        )
    minimum_samples = int(sfreq * config.flat_run_seconds)
    for channel in data:
        adjacent_finite = (
            np.isfinite(channel[:-1]) & np.isfinite(channel[1:])
        )
        constant_samples = np.abs(np.diff(channel)) <= 1e-12
        for start, stop in true_runs(
            adjacent_finite & constant_samples, minimum_samples
        ):
            mark_windows(reasons["flat_candidate"], start, stop + 1, size)


# 间断或已有BAD窗口不参加通道统计；局部坏段仍保留位置。
def gross_qc(raw, source_metadata, config):
    data = raw._data
    sampling_frequency = float(raw.info["sfreq"])
    window_samples = int(sampling_frequency * config.qc_window_seconds)
    window_count = math.ceil(raw.n_times / window_samples)
    inherited_intervals = annotation_intervals(raw)
    excluded = np.zeros(window_count, dtype=bool)
    for start, stop in inherited_intervals:
        mark_windows(excluded, start, stop, window_samples)
    metrics = window_metrics(data, window_samples, excluded)
    reasons = {
        name: np.zeros(window_count, dtype=bool)
        for name in (
            "nonfinite", "flat_candidate", "digital_saturation",
            "inherited_bad",
        )
    }
    mark_flat_candidates(
        data, metrics, config, sampling_frequency,
        window_samples, window_count, reasons,
    )
    calibration = mark_saturation(
        data, source_metadata, config, sampling_frequency, window_samples,
        reasons,
    )
    for start, stop in inherited_intervals:
        mark_windows(reasons["inherited_bad"], start, stop, window_samples)
    mask = np.logical_or.reduce(list(reasons.values()))
    margin = int(
        math.ceil(config.artifact_margin_seconds * sampling_frequency)
    )
    intervals = merge_intervals(
        [
            [index * window_samples - margin,
             (index + 1) * window_samples + margin]
            for index in np.flatnonzero(mask)
        ],
        raw.n_times,
    )
    preliminary, channel_reasons = channel_bads(
        metrics, config, preliminary=True
    )
    details = {
        "window_counts": {
            name: int(value.sum()) for name, value in reasons.items()
        },
        "preliminary_channel_reasons": channel_reasons,
        "digital_saturation_check_available": bool(calibration),
    }
    return intervals, preliminary, details


def read_records(registry, master_path, codes=None):
    """主表限定当前队列，不通过扫描目录扩大纳入范围。"""
    with master_path.open(encoding='utf-8-sig', newline='') as stream:
        master_rows = list(csv.DictReader(stream))
    with registry.open(encoding='utf-8-sig', newline='') as stream:
        records = list(csv.DictReader(stream))
    master = {row['编号']: row for row in master_rows}
    converted = {row['code']: row for row in records}
    if len(master) != len(master_rows) or len(converted) != len(records):
        raise ValueError('主表或转换清单含重复编号')
    if set(master) != set(converted):
        raise ValueError('主表与转换清单编号集合不同，请先同步')
    for code, row in converted.items():
        if row['status'] != 'complete':
            raise ValueError(f'{code}未完成FIF转换')
        if row['guid'] != master[code]['GUID']:
            raise ValueError(f'{code}的GUID与主表不一致')
        if row['source_edf'] != master[code]['所在服务器位置']:
            raise ValueError(f'{code}的EDF来源与主表不一致')
        row['group'] = 'hc' if code.upper().startswith('HC_') else 'doc'
    if codes:
        missing = set(codes) - set(converted)
        if missing:
            raise ValueError(f'指定编号不在当前主表：{sorted(missing)}')
        records = [row for row in records if row['code'] in codes]
    if not records:
        raise ValueError('没有可检查的记录')
    return records


def inspection_result(raw, intervals, reasons, bad_channels, counts, status):
    bad_samples = sum(stop - start for start, stop in intervals)
    return dict(
        status=status,
        n_channels=len(raw.ch_names),
        sfreq_hz=raw.info["sfreq"],
        n_samples=raw.n_times,
        duration_seconds=raw.n_times / raw.info["sfreq"],
        bad_channels=bad_channels,
        bad_channel_reasons=reasons,
        window_counts=counts,
        bad_intervals_samples=intervals,
        gross_bad_fraction=bad_samples / raw.n_times,
        digital_saturation_check_available=False,
    )


def inspect_record(row, scratch, config):
    paths = [Path(name) for name in json.loads(row['fif_files'])]
    if not paths or any((not path.is_file() for path in paths)):
        raise FileNotFoundError(f"{row['code']}的FIF主文件或分卷缺失")
    before = [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
    with mne.io.read_raw_fif(
        paths[0], preload=str(scratch / 'waveform.dat'), verbose='ERROR'
    ) as raw:
        if (
            raw.ch_names != CHANNELS
            or raw.info['sfreq'] != config.target_sfreq
        ):
            raise ValueError('输入必须为固定顺序的19导、250Hz FIF')
        if (
            any(
                (
                    channel['unit'] != FIFF.FIFF_UNIT_V
                    for channel in raw.info['chs']
                )
            )
        ):
            raise ValueError('EEG单位必须为V')
        if raw.info['custom_ref_applied'] or raw.info['projs']:
            raise ValueError('初检输入不能已重参考或包含投影')
        intervals, bad_channels, details = gross_qc(
            raw, {'calibration': None}, config
        )
        reasons = details['preliminary_channel_reasons']
        for name in raw.info['bads']:
            reasons.setdefault(name, []).append('input_marked_bad')
        bad_channels = [name for name in CHANNELS if name in reasons]
        counts = details['window_counts']
        status = 'preliminary_pass'
        if bad_channels:
            status = 'excluded_bad_channels'
        elif counts['nonfinite'] or counts['flat_candidate']:
            status = 'needs_review'
        result = inspection_result(
            raw, intervals, reasons, bad_channels, counts, status
        )
    after = [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
    if before != after:
        raise RuntimeError(f"{row['code']}的输入在检查期间发生变化")
    return result


def numpy_json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"不能序列化的类型：{type(value).__name__}")


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=numpy_json_value)


QC_FIELDS = [
    'code', 'group', 'guid', 'fif_files', 'status', 'n_channels', 'sfreq_hz',
    'n_samples', 'duration_seconds', 'bad_channels', 'bad_channel_reasons',
    'window_counts', 'bad_intervals_samples', 'gross_bad_fraction',
    'digital_saturation_check_available', 'error', 'reference_version',
    'parameters', 'input_sha256', 'code_sha256'
]


def check_one_record(row, folders, config, fingerprints, code_hashes):
    result = {key: row[key] for key in ('code', 'group', 'guid', 'fif_files')}
    result.update(
        reference_version=REFERENCE_VERSION, parameters=config.as_dict(),
        input_sha256=fingerprints, code_sha256=code_hashes
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix='03_qc_', dir=folders[1]
        ) as scratch:
            result.update(inspect_record(row, Path(scratch), config))
    except Exception as error:
        result.update(
            status='failed', error=f'{type(error).__name__}: {error}'
        )
    return result


# 每条结果立即落表，保留参数和源码指纹，失败不吞掉原因。
def run_checks(rows, arguments, config, timestamp):
    folders = [arguments.base / name for name in ('tables', 'logs', 'reports')]
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
    output = folders[0] / f'03_信号质量检测_{timestamp}.csv'
    fields = QC_FIELDS
    fingerprints = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (arguments.master, arguments.registry)
    }
    code_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__), Path(__file__).with_name('config.py'))
    }
    results = []
    with output.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            result = check_one_record(
                row, folders, config, fingerprints, code_hashes
            )
            serialized = {}
            for key, value in result.items():
                if isinstance(value, (dict, list)):
                    value = encode(value)
                serialized[key] = value
            writer.writerow(serialized)
            stream.flush()
            results.append(result)
            print(
                f"{len(results)}/{len(rows)} {row['code']} {result['status']}",
                flush=True
            )
    for name, expected in fingerprints.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'运行期间输入清单发生变化：{name}')
    return (output, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--registry', type=Path, default=CONVERSION_MANIFEST)
    parser.add_argument('--master', type=Path, default=MASTER)
    parser.add_argument('--codes', nargs='+')
    parser.add_argument('--execute', action='store_true')
    arguments = parser.parse_args()
    rows = read_records(arguments.registry, arguments.master, arguments.codes)
    print(f'计划检查{len(rows)}条；原始FIF只读，不滤波、不参考。')
    if not arguments.execute:
        print('未指定--execute，未读取波形或创建检查产物。')
        return 0
    config = QCConfig()
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    output, results = run_checks(rows, arguments, config, timestamp)
    counts = Counter((row['status'] for row in results))
    report = write_report(
        arguments.base / 'reports', f'03_初检报告_{timestamp}', '19导EEG滤波前粗检查',
        [
            ('结果', [f'明细：{output}'], ['状态', '记录数'], sorted(counts.items())),
            (
                '方法',
                [
                    '参数集中于config.py，运行快照保存在明细parameters列。',
                    '坏导整份排除，局部坏段记录精确样本区间；原始FIF不修改。', '含采集间断或已有BAD的窗口不参与坏导统计。',
                    'FIF无EDF数字量程信息，不推测数字饱和阈值。', '初检通过仅表示可继续滤波，后续仍需质控。'
                ],
                [], []
            )
        ]
    )
    print(f'明细：{output}\n报告：{report}')
    return int(bool(counts['failed']))


if __name__ == '__main__':
    raise SystemExit(main())
