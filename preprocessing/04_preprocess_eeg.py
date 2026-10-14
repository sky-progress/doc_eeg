"""04：滤波、坏导坏段检测、平均参考及最终补标，保存连续FIF。"""
"""
原始 FIF
   |
   |
读取03阶段QC结果
(坏段、坏导候选)
   |
   ↓
复制数据到临时文件
   |
   ↓
分块滤波
(notch 50Hz)
       ↓
(bandpass 0.5-45Hz)
   |
   ↓
滤波后质量检测
   |
   ├──坏导？
   |      |
   |      └──整条记录排除
   |
   ↓
平均参考
(common average reference)
   |
   ↓
参考后再次QC
   |
   ↓
补充BAD_FINAL_QC标记
   |
   ↓
保存 preprocessed_raw.fif

"""
# ============================= 一、导入和配置 ==========================
import argparse
import csv
import hashlib
import html
import importlib                        # 动态加载Python模块，用于在运行时导入其他脚本中的函数和变量
import json
import math
import re                               # 正则表达式，用于字符串匹配和搜索
import tempfile                         # 创建临时目录
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path                # 路径管理
from zoneinfo import ZoneInfo

import mne
import numpy as np

from config import BASE, CHANNELS, MASTER, REFERENCE_VERSION, SignalConfig              # 从config.py读取配置
from reporting import write_report                                                      # 生成报告
initial_qc = importlib.import_module('03_check_signal_quality')                         # 复用质量检测
merge_intervals = initial_qc.merge_intervals                                            # 因为脚本名字是03开头的不能用from xxx import xxx，所以引入动态引用
complement = initial_qc.complement
mark_windows = initial_qc.mark_windows
window_metrics = initial_qc.window_metrics
channel_bads = initial_qc.channel_bads
robust_z = initial_qc.robust_z
annotation_intervals = initial_qc.annotation_intervals

# ==================== 二、滤波器设计 =====================
def filter_specs(config):
    common = dict(
        filter_length='auto',           # 自动选择滤波器长度
        phase=config.fir_phase,         # 滤波器相位类型
        fir_window=config.fir_window,   # FIR滤波器窗函数类型
        fir_design=config.fir_design,   # FIR滤波器设计方法
        verbose='ERROR'                 # 设置日志输出级别为ERROR，减少不必要的输出
    )
    # 调用MNE创建 FIR 滤波器,创建 bandpass 滤波器
    band = mne.filter.create_filter(
        None,
        config.target_sfreq,                # 采样率
        config.highpass_hz,                 # 高通频率
        config.lowpass_hz,                  # 低通频率
        l_trans_bandwidth=config.low_transition_hz,
        h_trans_bandwidth=config.high_transition_hz, 
        **common
    )
    half = config.notch_width_hz / 2 + config.notch_transition_hz / 2
    notch = mne.filter.create_filter(
        None, config.target_sfreq, config.notch_hz + half,
        config.notch_hz - half,
        l_trans_bandwidth=config.notch_transition_hz / 2,
        h_trans_bandwidth=config.notch_transition_hz / 2, **common
    )
    return {
        'bandpass_taps': len(band),
         'notch_taps': len(notch),
        'boundary_guard_seconds': max(
            config.edge_exclude_seconds,
            (len(band) - 1 + (len(notch) - 1)) / (2 * config.target_sfreq) + 0.1
        )
    }


def filter_piece(piece, config):
    common = dict(
        method='fir', phase=config.fir_phase, fir_window=config.fir_window,
        fir_design=config.fir_design, pad=config.filter_pad, verbose='ERROR'
    )
    piece = mne.filter.notch_filter(
        piece, config.target_sfreq, [config.notch_hz],
        notch_widths=config.notch_width_hz,
        trans_bandwidth=config.notch_transition_hz, **common
    )
    return mne.filter.filter_data(
        piece, config.target_sfreq, config.highpass_hz, config.lowpass_hz,
        l_trans_bandwidth=config.low_transition_hz,
        h_trans_bandwidth=config.high_transition_hz, **common
    )

# ====================== 三、数据复制和分块滤波 ====================
def copy_signal(raw, scratch):
    data = np.memmap(
        scratch / 'processed.dat', dtype='float64', mode='w+',
        shape=(len(CHANNELS), raw.n_times)
    )
    for start in range(0, raw.n_times, 250000):
        stop = min(start + 250000, raw.n_times)
        data[:, start:stop] = raw._data[:, start:stop]
    return data


# 分块滤波并保护卷积边缘，防止坏段或间断污染相邻可用信号。
def filter_blocks(raw, data, initial_intervals, config, specifications):
    """分块滤波，不能让卷积跨越坏段和采集间断。"""
    guard = math.ceil(
        specifications['boundary_guard_seconds'] * config.target_sfreq
    )
    blocked = list(initial_intervals)
    filtered = []
    minimum = max(
        specifications['bandpass_taps'], specifications['notch_taps'],
        2 * guard
    )
    for start, stop in complement(initial_intervals, raw.n_times):
        if stop - start <= minimum:
            blocked.append([start, stop])
            continue
        piece = raw._data[:, start:stop]
        if not np.isfinite(piece).all():
            raise ValueError('初检后仍有非有限值进入滤波')
        data[:, start:stop] = filter_piece(piece, config)
        blocked.extend([[start, start + guard], [stop - guard, stop]])
        filtered.append([start, stop])
    return (merge_intervals(blocked, raw.n_times), filtered)

# ====================== 四、 滤波后质量控制 =========================
def filtered_quality(data, blocked, preliminary, config):
    size = config.target_sfreq * config.qc_window_seconds
    excluded = np.zeros(math.ceil(data.shape[1] / size), dtype=bool)
    for start, stop in blocked:
        mark_windows(excluded, start, stop, size)
    metrics = window_metrics(data, size, excluded)
    bad_channels, reasons = channel_bads(metrics, config)
    bad_channels = [
        name for name in CHANNELS if name in set(bad_channels + preliminary)
    ]
    finite = np.isfinite(metrics['ptp'])
    amplitude = np.any(
        finite & (metrics['ptp'] > config.high_ptp_uv * 1e-06), axis=0
    )
    jump = np.any(metrics['step'] > config.jump_uv * 1e-06, axis=0)
    flat = np.any(
        finite & (metrics['ptp'] < config.flat_ptp_uv * 1e-06), axis=0
    )
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        global_rms = np.nanmedian(metrics['rms'], axis=0)
    rms_bad = (
        robust_z(np.log10(global_rms + 1e-15)) > config.global_rms_z
    ) & (global_rms > config.global_rms_uv * 1e-06)
    margin = math.ceil(config.artifact_margin_seconds * config.target_sfreq)
    detected = [
        [index * size - margin, (index + 1) * size + margin]
        for index in np.flatnonzero(amplitude | jump | flat | rms_bad)
    ]
    intervals = merge_intervals(blocked + detected, data.shape[1])
    return (
        bad_channels, reasons, intervals,
        dict(
            amplitude=int(amplitude.sum()), jump=int(jump.sum()),
            flat_candidate=int(flat.sum()), global_rms=int(rms_bad.sum())
        )
    )


# ========================== 五、构造处理后的Raw和annotation =================
def build_processed_raw(data, raw, intervals, config):
    result = mne.io.RawArray(
        data, raw.info.copy(), first_samp=raw.first_samp, copy='info',
        verbose='ERROR'
    )
    result.set_annotations(
        mne.Annotations([], [], [], orig_time=raw.annotations.orig_time)
    )
    original = raw.annotations
    result.annotations.append(
        original.onset, original.duration, original.description,
        ch_names=original.ch_names, extras=original.extras
    )
    result.annotations.append(
        [
            raw.first_time + start / config.target_sfreq for start,
            stop in intervals
        ],
        [(stop - start) / config.target_sfreq for start, stop in intervals],
        ['BAD_NOICA_unusable'] * len(intervals)
    )
    with result.info._unlock():
        result.info['highpass'] = config.highpass_hz
        result.info['lowpass'] = config.lowpass_hz
    result.info['line_freq'] = config.notch_hz
    result.info['description'] = (
        'doc_eeg_analysis 04; noICA; average reference; '
        'BAD samples excluded from subsequent analysis.'
    )
    return result

# ==========================六 、平均参考 ======================
def prepare_continuous(raw, initial_intervals, preliminary, config, scratch):
    if raw.ch_names != CHANNELS or raw.info['sfreq'] != config.target_sfreq:
        raise ValueError('只接受固定19导、250Hz输入，不重复重采样')
    initial_intervals = merge_intervals(initial_intervals, raw.n_times)
    data = copy_signal(raw, scratch)
    specifications = filter_specs(config)
    blocked, filtered = filter_blocks(
        raw, data, initial_intervals, config, specifications
    )
    bad_channels, reasons, intervals, counts = filtered_quality(
        data, blocked, preliminary, config
    )
    result = build_processed_raw(data, raw, intervals, config)
    quality = dict(
        bad_channels=bad_channels, final_channel_reasons=reasons,
        filter=specifications, filtered_blocks_samples=filtered,
        bad_intervals_samples=intervals, filtered_window_counts=counts,
        bad_fraction=(
            sum(stop - start for start, stop in intervals) / raw.n_times
        ),
        n_times=raw.n_times,
        duration_seconds=raw.n_times / config.target_sfreq,
        n_samples=raw.n_times
    )
    if not bad_channels:
        result.set_eeg_reference('average', projection=False, verbose='ERROR')
    data.flush()
    return (result, quality)


# 向外加入FIF时间精度保护，避免舍入后漏出边缘样本。
def append_reference_annotations(raw, final, config):
    end_time = raw.first_time + (raw.n_times - 1) / config.target_sfreq
    precision_guard = max(1e-06, 2 * float(np.spacing(np.float32(end_time))))
    anomalies = final['anomaly_windows']
    margin = config.artifact_margin_seconds
    for anomaly in anomalies:
        start = max(
            0.0, anomaly['start_sample'] / config.target_sfreq - margin
        )
        stop = min(
            raw.n_times / config.target_sfreq,
            anomaly['stop_sample'] / config.target_sfreq + margin
        )
        raw.annotations.append(
            [raw.first_time + start - precision_guard],
            [stop - start + 2 * precision_guard], ['BAD_FINAL_QC'],
            extras=[
                dict(
                    start_sample=anomaly['start_sample'],
                    stop_sample=anomaly['stop_sample']
                )
            ]
        )


def reference_channel_quality(raw, intervals, config):
    """参考会改变各导幅值，必须在补标局部异常前复查持续坏导。"""
    size = config.target_sfreq * config.qc_window_seconds
    excluded = np.zeros(math.ceil(raw.n_times / size), dtype=bool)
    for start, stop in intervals:
        mark_windows(excluded, start, stop, size)
    # 末尾不足一个完整窗口，不用于持续异常的比例统计。
    if raw.n_times % size:
        excluded[-1] = True
    metrics = window_metrics(raw._data, size, excluded)
    bad_channels, reasons = channel_bads(metrics, config)
    return dict(
        bad_channels=bad_channels,
        reasons=reasons,
        checked_windows=int(np.sum(~excluded)),
    )

# ========================== 七、最终QC和补标 =========================
def finalize_reference_segments(raw, quality, config):
    """把原06的定位与补标合入保存前流程，不再二次改写FIF。"""
    channel_quality = reference_channel_quality(
        raw, quality['bad_intervals_samples'], config
    )
    quality['post_reference_channel_qc'] = channel_quality
    if channel_quality['bad_channels']:
        quality['bad_channels'] = channel_quality['bad_channels']
        quality['final_channel_reasons'] = channel_quality['reasons']
        return quality
    final = scan_raw(raw, quality['bad_intervals_samples'], config)
    size = config.target_sfreq * config.qc_window_seconds
    append_reference_annotations(raw, final, config)
    intervals = merge_intervals(
        final['new_bad_intervals_samples'] + annotation_intervals(raw),
        raw.n_times
    )
    remaining = list(candidate_starts(raw.n_times, size, intervals))
    for start in remaining:
        if window_reasons(raw._data[:, start:start + size], config):
            raise RuntimeError('参考后最终可用窗口仍命中异常规则')
    quality.update(
        bad_intervals_samples=intervals,
        bad_fraction=(
            sum(stop - start for start, stop in intervals) / raw.n_times
        ),
        final_bad_intervals_samples=intervals,
        final_bad_fraction=(
            sum(stop - start for start, stop in intervals) / raw.n_times
        ),
        final_available_qc_windows=len(remaining),
        clean_duration_seconds=(
            raw.n_times - sum((stop - start for start, stop in intervals))
        ) / config.target_sfreq,
        post_reference_qc=final
    )
    return quality


def window_reasons(block, config):
    if not np.isfinite(block).all():
        return {"nonfinite": []}
    peak_to_peak = np.ptp(block, axis=1)
    maximum_step = np.max(np.abs(np.diff(block, axis=1)), axis=1)
    masks = {
        "flat_candidate": peak_to_peak < config.flat_ptp_uv * 1e-6,
        "high_amplitude": peak_to_peak > config.high_ptp_uv * 1e-6,
        "jump": maximum_step > config.jump_uv * 1e-6,
    }
    reasons = {}
    for reason, mask in masks.items():
        if mask.any():
            reasons[reason] = [
                CHANNELS[channel_index]
                for channel_index in np.flatnonzero(mask)
            ]
    if np.max(np.abs(block)) <= 1e-12:
        reasons["all_channels_zero"] = list(CHANNELS)
    return reasons


def candidate_starts(n_times, size, intervals):
    cursor = 0
    for start in range(0, n_times - size + 1, size):
        while cursor < len(intervals) and intervals[cursor][1] <= start:
            cursor += 1
        if cursor < len(intervals) and intervals[cursor][0] < start + size:
            continue
        yield start


def reference_scan_summary(
    n_times, size, old, candidates, candidate_set, anomalies, counts, config
):
    margin = round(config.artifact_margin_seconds * config.target_sfreq)
    detected_intervals = [
        [window["start_sample"] - margin, window["stop_sample"] + margin]
        for window in anomalies
    ]
    final = merge_intervals(old + detected_intervals, n_times)
    previous_bad_samples = sum(stop - start for start, stop in old)
    final_bad_samples = sum(stop - start for start, stop in final)
    added_samples = final_bad_samples - previous_bad_samples
    fraction = final_bad_samples / n_times
    remaining = list(candidate_starts(n_times, size, final))
    flagged = {window["start_sample"] for window in anomalies}
    if not set(remaining) <= candidate_set - flagged:
        raise RuntimeError("最终可用窗口未完成检测或仍包含异常")
    status = "retain"
    if fraction > config.max_bad_fraction:
        status = "exclude_bad_fraction"
    return dict(
        status=status,
        n_samples=n_times,
        sfreq_hz=250,
        duration_seconds=n_times / 250,
        old_bad_intervals_samples=old,
        new_bad_intervals_samples=final,
        reference_checked_windows=len(candidates),
        reference_window_counts=counts,
        anomaly_windows=anomalies,
        anomaly_window_count=len(anomalies),
        added_bad_seconds=added_samples / 250,
        old_bad_fraction=previous_bad_samples / n_times,
        final_bad_fraction=fraction,
        clean_duration_seconds=(n_times - final_bad_samples) / 250,
        final_available_qc_windows=len(remaining),
        final_usable_intervals_samples=complement(final, n_times),
        needs_annotation_update=bool(added_samples),
    )


def scan_reference_windows(raw, n_times, size, candidate_set, config):
    anomalies = []
    counts = {
        k: 0
        for k in (
            'nonfinite', 'flat_candidate', 'high_amplitude', 'jump',
            'all_channels_zero'
        )
    }
    for first in range(0, n_times, 100 * size):
        last = min(first + 100 * size, n_times)
        selected = [
            start
            for start in range(first, last - size + 1, size)
            if start in candidate_set
        ]
        if not selected:
            continue
        data = raw[:, first:last][0]
        for start in selected:
            reasons = window_reasons(
                data[:, start - first:start - first + size], config
            )
            if reasons:
                for name in reasons:
                    counts[name] += 1
                anomalies.append(
                    dict(
                        start_sample=start, stop_sample=start + size,
                        reasons=reasons
                    )
                )
    return (anomalies, counts)


def scan_raw(raw, old_intervals, config):
    if (
        raw.ch_names != CHANNELS
        or raw.info["sfreq"] != 250
        or not raw.info["custom_ref_applied"]
    ):
        raise ValueError("只接受19导、250Hz、已平均参考的FIF")
    if raw.info["bads"]:
        raise ValueError("输入含坏导，不能作为保留记录")
    n_times = raw.n_times
    size = config.target_sfreq * config.qc_window_seconds
    for start, stop in old_intervals:
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start < stop <= n_times
        ):
            raise ValueError("坏段样本区间不合法")
    old = merge_intervals(old_intervals + annotation_intervals(raw), n_times)
    candidates = list(candidate_starts(n_times, size, old))
    candidate_set = set(candidates)
    anomalies, counts = scan_reference_windows(
        raw, n_times, size, candidate_set, config
    )
    return reference_scan_summary(
        n_times, size, old, candidates, candidate_set, anomalies, counts,
        config,
    )

# ======================== 八、保存FIF和验证 =========================
def verify_waveform(raw, expected, qc):
    for start in range(0, raw.n_times, 250000):
        stop = min(start + 250000, raw.n_times)
        actual_block = raw.get_data(start=start, stop=stop)
        expected_block = expected.get_data(start=start, stop=stop)
        matches = np.allclose(
            actual_block, expected_block,
            rtol=2e-6, atol=1e-12, equal_nan=True,
        )
        if not matches:
            raise ValueError("输出波形回读不一致")
    for start, stop in complement(qc["bad_intervals_samples"], raw.n_times):
        for first in range(start, stop, 250000):
            block = raw.get_data(start=first, stop=min(first + 250000, stop))
            if not np.isfinite(block).all():
                raise ValueError("可用区间含非有限值或不满足平均参考")
            if np.max(np.abs(block.mean(axis=0))) > 1e-9:
                raise ValueError("可用区间含非有限值或不满足平均参考")


# FIF事件起止时间为float32，核验其存储精度而非原双精度值。
def verify_annotations(raw, expected):
    if len(raw.annotations) != len(expected.annotations):
        raise ValueError("输出事件数量变化")
    stored_onset = expected.annotations.onset.astype(np.float32)
    stored_end = (
        expected.annotations.onset + expected.annotations.duration
    ).astype(np.float32)
    stored_duration = stored_end - stored_onset
    for actual, target in (
        (raw.annotations.onset, stored_onset),
        (raw.annotations.duration, stored_duration),
    ):
        if not np.allclose(actual, target, rtol=0, atol=2e-6):
            raise ValueError("输出事件时间变化（超出FIF存储精度）")
    actual_descriptions = [
        html.unescape(value) for value in raw.annotations.description
    ]
    expected_descriptions = [
        html.unescape(value) for value in expected.annotations.description
    ]
    if (
        actual_descriptions != expected_descriptions
        or raw.annotations.extras != expected.annotations.extras
    ):
        raise ValueError("输出事件文字或原间断信息变化")


def verify_output(raw, expected, qc, config):
    if (
        raw.ch_names != CHANNELS
        or raw.info["sfreq"] != config.target_sfreq
        or raw.n_times != expected.n_times
    ):
        raise ValueError("输出通道、采样率或样本数变化")
    if not raw.info["custom_ref_applied"] or raw.info["bads"]:
        raise ValueError("输出平均参考或坏导状态错误")
    if (
        raw.first_samp != expected.first_samp
        or raw.info["meas_date"] != expected.info["meas_date"]
    ):
        raise ValueError("输出采集时间轴变化")
    if (
        not np.isclose(raw.info["highpass"], config.highpass_hz)
        or not np.isclose(raw.info["lowpass"], config.lowpass_hz)
    ):
        raise ValueError("输出频带元信息错误")
    verify_annotations(raw, expected)
    for actual_channel, expected_channel in zip(
        raw.info["chs"], expected.info["chs"]
    ):
        matches = np.allclose(
            actual_channel["loc"], expected_channel["loc"],
            rtol=0, atol=1e-7, equal_nan=True,
        )
        if not matches:
            raise ValueError("电极坐标变化")
    verify_waveform(raw, expected, qc)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_stats(paths):
    return [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]


# 先暂存并验收，再发布；异常只清理本次创建的派生文件。
def publish_output(raw, quality, config, code, scratch, processed):
    staging = scratch / 'fif'
    staging.mkdir()
    name = f'{code}_preprocessed_raw.fif'
    published = []
    try:
        raw.save(
            staging / name, fmt='single', overwrite=False,
            split_naming='neuromag', verbose='ERROR'
        )
        with mne.io.read_raw_fif(staging / name, verbose='ERROR') as saved:
            verify_output(saved, raw, quality, config)
        for path in sorted(staging.glob('*.fif')):
            target = processed / path.name
            if target.exists():
                raise FileExistsError(f'拒绝覆盖已有处理文件：{target}')
            path.rename(target)
            published.append(target)
        with mne.io.read_raw_fif(processed / name, verbose='ERROR') as saved:
            verify_output(saved, raw, quality, config)
        return [
            str(processed / name)
        ] + [str(path) for path in published if path.name != name]
    except Exception:
        for path in published:
            path.unlink()
        raise


def process_loaded_source(
    source, row, config, scratch, processed, paths, before
):
    code = row['code']
    if (
        source.info['custom_ref_applied']
        or source.info['projs']
        or source.info['bads']
    ):
        raise ValueError(f'{code}的输入已参考、含投影或已有坏导')
    if source.n_times != int(row['n_samples']):
        raise ValueError(f'{code}的样本数与初检不一致')
    output, quality = prepare_continuous(
        source, json.loads(row['bad_intervals_samples']),
        json.loads(row['bad_channels']), config, scratch
    )
    try:
        if quality['bad_channels']:
            return dict(
                status='excluded_bad_channels_04', fif_files=[], **quality
            )
        quality = finalize_reference_segments(output, quality, config)
        if quality['bad_channels']:
            return dict(
                status='excluded_bad_channels_04', fif_files=[], **quality
            )
        if quality['bad_fraction'] > config.max_bad_fraction:
            return dict(
                status='excluded_bad_fraction', fif_files=[], **quality
            )
        if file_stats(paths) != before:
            raise RuntimeError(f'{code}的输入在处理期间发生变化')
        files = publish_output(
            output, quality, config, code, scratch, processed
        )
        review = (quality['bad_fraction'] > config.review_bad_fraction
                      or row['status'] == 'needs_review')
        status = 'needs_review' if review else 'processed_pass'
        return dict(status=status, fif_files=files, **quality)
    finally:
        output.close()


def process_record(row, config, scratch, processed):
    code = row['code']
    if not re.fullmatch('[A-Za-z0-9_-]+', code):
        raise ValueError(f'不合法的记录编号：{code}')
    if row['status'] == 'excluded_bad_channels':
        return dict(
            status='excluded_bad_channels_03', fif_files=[],
            bad_channels=json.loads(row['bad_channels'])
        )
    paths = [Path(name) for name in json.loads(row['fif_files'])]
    if not paths or any((not path.is_file() for path in paths)):
        raise FileNotFoundError(f'{code}的输入FIF缺失')
    if list(processed.glob(f'{code}_preprocessed_raw*.fif')):
        raise FileExistsError(f'{code}已有处理FIF，拒绝覆盖')
    before = file_stats(paths)
    with mne.io.read_raw_fif(
        paths[0], preload=str(scratch / 'source.dat'), verbose='ERROR'
    ) as source:
        return process_loaded_source(
            source, row, config, scratch, processed, paths, before
        )


def read_qc_rows(path, master_path, codes):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    with master_path.open(encoding='utf-8-sig', newline='') as stream:
        master_rows = list(csv.DictReader(stream))
    master = {row['编号']: row for row in master_rows}
    if not master or len(master) != len(master_rows):
        raise ValueError('主表为空或编号重复')
    if not rows or len({row['code'] for row in rows}) != len(rows):
        raise ValueError('初检明细为空或编号重复')
    for row in rows:
        if (
            row['code'] not in master
            or row['guid'] != master[row['code']]['GUID']
        ):
            raise ValueError(f"初检记录与当前主表不一致：{row['code']}")
        if (
            row['status'] not in (
                'preliminary_pass', 'needs_review', 'excluded_bad_channels'
            )
        ):
            raise ValueError(f"初检记录尚未解决：{row['code']} {row['status']}")
    if codes:
        if set(codes) - {row['code'] for row in rows}:
            raise ValueError('指定编号不在初检明细中')
        rows = [row for row in rows if row['code'] in codes]
    elif {row['code'] for row in rows} != set(master):
        missing = sorted(set(master) - {row['code'] for row in rows})
        raise ValueError(f'初检明细不完整，缺少记录：{missing}')
    return rows


def numpy_json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"不能序列化的类型：{type(value).__name__}")


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=numpy_json_value)


PROCESSING_FIELDS = [
    'code', 'group', 'guid', 'source_fif_files', 'status', 'n_samples',
    'duration_seconds', 'bad_channels', 'final_channel_reasons', 'filter',
    'bad_fraction', 'bad_intervals_samples', 'filtered_window_counts',
    'filtered_blocks_samples', 'n_times', 'post_reference_qc',
    'final_bad_intervals_samples', 'final_bad_fraction',
    'final_available_qc_windows', 'clean_duration_seconds', 'fif_files',
    'error', 'parameters', 'reference_version', 'input_sha256', 'code_sha256',
    'post_reference_channel_qc', 'processing_code_sha256',
    'resume_source_table', 'resume_source_sha256', 'reused_filtered_fif',
]


RESUME_JSON_FIELDS = {
    'source_fif_files', 'bad_channels', 'final_channel_reasons', 'filter',
    'bad_intervals_samples', 'filtered_window_counts',
    'filtered_blocks_samples', 'post_reference_qc',
    'final_bad_intervals_samples', 'fif_files', 'parameters',
    'input_sha256', 'code_sha256', 'post_reference_channel_qc',
    'processing_code_sha256',
}


def read_resume_results(arguments, rows, config, fingerprints, code_hashes):
    if arguments.resume_table is None:
        return {}
    with arguments.resume_table.open(
        encoding='utf-8-sig', newline=''
    ) as stream:
        previous = list(csv.DictReader(stream))
    expected = {row['code']: row for row in rows}
    results = {}
    for stored in previous:
        code = stored['code']
        if code in results or code not in expected:
            raise ValueError(f'续跑清单编号重复或不在本次队列：{code}')
        result = {key: value for key, value in stored.items() if value != ''}
        for field in RESUME_JSON_FIELDS & result.keys():
            result[field] = json.loads(result[field])
        validate_resume_result(
            result, expected[code], config, fingerprints, code_hashes
        )
        if result['status'] != 'failed':
            results[code] = result
    return results


def validate_resume_result(result, row, config, fingerprints, code_hashes):
    code = row['code']
    identity_matches = (
        result['guid'] == row['guid']
        and result['group'] == row['group']
        and result['source_fif_files'] == json.loads(row['fif_files'])
    )
    if not identity_matches:
        raise ValueError(f'{code}的续跑GUID、组别或源文件不一致')
    if result['parameters'] != config.as_dict():
        raise ValueError(f'{code}的续跑参数变化，必须重新处理')
    if result['input_sha256'] != fingerprints:
        raise ValueError(f'{code}的主表或初检清单变化，拒绝复用')
    if result['reference_version'] != REFERENCE_VERSION:
        raise ValueError(f'{code}的参考流程版本变化，拒绝复用')
    for name in ('03_check_signal_quality.py', 'config.py'):
        if result['code_sha256'].get(name) != code_hashes[name]:
            raise ValueError(f'{code}的检测或参数源码变化：{name}')
    accepted = {
        'processed_pass', 'needs_review', 'excluded_bad_channels_03',
        'excluded_bad_channels_04', 'excluded_bad_fraction', 'failed',
    }
    if result['status'] not in accepted:
        raise ValueError(f'{code}的续跑状态不可识别：{result["status"]}')


def validate_saved_record(raw, result, row, processed, config):
    code = row['code']
    expected_root = processed.resolve()
    paths = [Path(name) for name in result['fif_files']]
    if not paths or any(
        not path.is_file() or path.resolve().parent != expected_root
        for path in paths
    ):
        raise ValueError(f'{code}的续跑FIF缺失或输出目录不一致')
    actual_paths = [Path(name).resolve() for name in raw.filenames]
    if actual_paths != [path.resolve() for path in paths]:
        raise ValueError(f'{code}的FIF分卷与续跑清单不一致')
    if raw.n_times != int(row['n_samples']):
        raise ValueError(f'{code}的续跑FIF样本数变化')
    if raw.ch_names != CHANNELS or raw.info['sfreq'] != config.target_sfreq:
        raise ValueError(f'{code}的续跑FIF通道或采样率错误')
    if not raw.info['custom_ref_applied'] or raw.info['bads']:
        raise ValueError(f'{code}的续跑FIF未参考或已有坏导')
    if (
        not np.isclose(raw.info['highpass'], config.highpass_hz)
        or not np.isclose(raw.info['lowpass'], config.lowpass_hz)
    ):
        raise ValueError(f'{code}的续跑FIF频带元信息错误')
    source_path = Path(json.loads(row['fif_files'])[0])
    with mne.io.read_raw_fif(source_path, verbose='ERROR') as original:
        if (
            raw.first_samp != original.first_samp
            or raw.info['meas_date'] != original.info['meas_date']
        ):
            raise ValueError(f'{code}的续跑FIF采集时间轴变化')
    expected_intervals = result['final_bad_intervals_samples']
    actual_intervals = annotation_intervals(raw)
    if len(expected_intervals) != len(actual_intervals):
        raise ValueError(f'{code}的续跑FIF坏段数量与清单不一致')
    if not np.allclose(expected_intervals, actual_intervals, rtol=0, atol=2):
        raise ValueError(f'{code}的续跑FIF坏段范围与清单不一致')


def verify_saved_signal(raw, intervals):
    for start, stop in complement(intervals, raw.n_times):
        for first in range(start, stop, 250000):
            block = raw.get_data(start=first, stop=min(first + 250000, stop))
            if not np.isfinite(block).all():
                raise ValueError('续跑FIF可用区间含非有限值')
            if np.max(np.abs(block.mean(axis=0))) > 1e-9:
                raise ValueError('续跑FIF可用区间不满足平均参考')


def recheck_saved_quality(raw, result, config):
    intervals = annotation_intervals(raw)
    verify_saved_signal(raw, intervals)
    # 使用补标前的窗口范围，与新处理记录的参考后坏导检查保持一致。
    channel_intervals = result.get('post_reference_qc', {}).get(
        'old_bad_intervals_samples', intervals
    )
    channels = reference_channel_quality(raw, channel_intervals, config)
    result['post_reference_channel_qc'] = channels
    if channels['bad_channels']:
        result.update(
            status='excluded_bad_channels_04',
            bad_channels=channels['bad_channels'],
            final_channel_reasons=channels['reasons'],
        )
        return result
    final = scan_raw(raw, intervals, config)
    if final['anomaly_windows']:
        raise ValueError('续跑FIF可用区间存在异常窗口，需要重新补标后保存')
    fraction = sum(stop - start for start, stop in intervals) / raw.n_times
    result.update(
        bad_intervals_samples=intervals,
        final_bad_intervals_samples=intervals,
        bad_fraction=fraction,
        final_bad_fraction=fraction,
        clean_duration_seconds=final['clean_duration_seconds'],
        final_available_qc_windows=final['final_available_qc_windows'],
    )
    return result


def resume_record(result, row, config, scratch, processed):
    if result['status'].startswith('excluded_'):
        return result
    paths = [Path(name) for name in result['fif_files']]
    before = file_stats(paths)
    with mne.io.read_raw_fif(
        paths[0], preload=str(scratch / 'resume.dat'), verbose='ERROR'
    ) as raw:
        validate_saved_record(raw, result, row, processed, config)
        result = recheck_saved_quality(raw, result, config)
    if file_stats(paths) != before:
        raise RuntimeError(f'{row["code"]}的续跑FIF在复查期间变化')
    result['reused_filtered_fif'] = True
    return result


def process_one_record(
    row, folders, arguments, config, fingerprints, code_hashes, previous=None
):
    result = {key: row[key] for key in ('code', 'group', 'guid')}
    result.update(
        source_fif_files=row['fif_files'], parameters=config.as_dict(),
        reference_version=REFERENCE_VERSION,
        input_sha256={
            str(path): fingerprints[str(path)]
            for path in (arguments.qc_table, arguments.master)
        },
        code_sha256=code_hashes, processing_code_sha256=code_hashes,
        reused_filtered_fif=False,
    )
    try:
        with tempfile.TemporaryDirectory(
            prefix='04_work_', dir=folders['logs']
        ) as scratch:
            if previous is None:
                computed = process_record(
                    row, config, Path(scratch), arguments.output_dir
                )
            else:
                computed = resume_record(
                    previous.copy(), row, config, Path(scratch),
                    arguments.output_dir,
                )
                computed['processing_code_sha256'] = previous.get(
                    'processing_code_sha256', previous['code_sha256']
                )
                computed['code_sha256'] = code_hashes
                computed['resume_source_table'] = str(arguments.resume_table)
                computed['resume_source_sha256'] = fingerprints[
                    str(arguments.resume_table)
                ]
            result.update(computed)
    except Exception as error:
        result.update(
            status='failed', error=f'{type(error).__name__}: {error}'
        )
    return result


def processing_code_hashes():
    paths = (
        Path(__file__),
        Path(__file__).with_name('03_check_signal_quality.py'),
        Path(__file__).with_name('config.py'),
    )
    return {path.name: digest(path) for path in paths}


def run_processing(rows, arguments, config, timestamp):
    folders = {
        name: arguments.base / name for name in ('tables', 'logs', 'reports')
    }
    for folder in [*folders.values(), arguments.output_dir]:
        folder.mkdir(parents=True, exist_ok=True)
    table = folders['tables'] / f'04_预处理明细_{timestamp}.csv'
    fields = PROCESSING_FIELDS
    fingerprints = {
        str(path): digest(path)
        for path in (arguments.qc_table, arguments.master)
    }
    code_hashes = processing_code_hashes()
    previous = read_resume_results(
        arguments, rows, config, fingerprints, code_hashes
    )
    if arguments.resume_table is not None:
        fingerprints[str(arguments.resume_table)] = digest(
            arguments.resume_table
        )
    results = []
    with table.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            result = process_one_record(
                row, folders, arguments, config, fingerprints, code_hashes,
                previous.get(row['code']),
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
        if digest(Path(name)) != expected:
            raise RuntimeError(f'输入清单在执行期间变化：{name}')
    return (table, results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--qc-table', type=Path, required=True)
    parser.add_argument('--master', type=Path, default=MASTER)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--resume-table', type=Path)
    parser.add_argument('--codes', nargs='+')
    parser.add_argument('--execute', action='store_true')
    arguments = parser.parse_args()
    arguments.output_dir = arguments.output_dir or arguments.base / 'processed'
    rows = read_qc_rows(arguments.qc_table, arguments.master, arguments.codes)
    print(f'计划处理{len(rows)}条；保存至{arguments.output_dir}。')
    if not arguments.execute:
        print('未指定--execute，未读取波形或创建处理产物。')
        return 0
    config = SignalConfig()
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    logs = arguments.base / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    lock = logs / '04_preprocessing.lock'
    with lock.open('x') as stream:
        stream.write(timestamp)
    try:
        table, results = run_processing(rows, arguments, config, timestamp)
        counts = Counter((row['status'] for row in results))
        report = write_report(
            arguments.base / 'reports', f'04_预处理报告_{timestamp}', '19导EEG信号预处理',
            [
                ('结果', [f'明细：{table}'], ['状态', '记录数'], sorted(counts.items())),
                (
                    '流程',
                    [
                        '有效块滤波→滤波后质控→平均参考→参考后坏导检测及补标→保存。',
                        '续跑先核验已保存FIF并全量复查，不重复滤波；保留原处理源码指纹。',
                        '参数集中于config.py，并记录在明细parameters列。',
                        '坏导整份排除，不做ICA、插值或坏导修复。', '最终坏段比例超过90%排除，超过50%保留警告。',
                        '完整事件及间断extras保留；保存后核验全量波形和元信息。',
                        '最终坏段已写入FIF，切窗读取本次04明细，不再运行补标脚本。'
                    ],
                    [], []
                )
            ]
        )
        print(f'明细：{table}\n报告：{report}')
        return int(bool(counts['failed']))
    finally:
        lock.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
