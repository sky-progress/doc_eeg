"""05：从最终连续FIF均匀选择有效窗口，不重复滤波或参考。"""
import argparse
import csv
import hashlib
import importlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mne
import numpy as np

from config import BASE, CHANNELS, MASTER, QCConfig
from reporting import write_report
initial_qc = importlib.import_module('03_check_signal_quality')
annotation_intervals = initial_qc.annotation_intervals
merge_intervals = initial_qc.merge_intervals


def sample_counts(seconds, overlap, sfreq):
    if (
        not math.isfinite(seconds)
        or not math.isfinite(overlap)
        or seconds <= 0
        or not 0 <= overlap < seconds
    ):
        raise ValueError("窗口长度必须为正，重叠必须非负且小于窗口长度")
    exact_length = seconds * sfreq
    exact_step = (seconds - overlap) * sfreq
    length = round(exact_length)
    step = round(exact_step)
    if (
        length < 2
        or step < 1
        or abs(length - exact_length) > 1e-8
        or abs(step - exact_step) > 1e-8
    ):
        raise ValueError("窗口长度与步长必须对应整数采样点")
    return length, step


def valid_starts(n_times, length, step, intervals):
    values = []
    cursor = 0
    for start in range(0, n_times - length + 1, step):
        while cursor < len(intervals) and intervals[cursor][1] <= start:
            cursor += 1
        if cursor < len(intervals) and intervals[cursor][0] < start + length:
            continue
        values.append(start)
    return values


# 均匀取样不复制凑数，窗口数量不代表独立患者样本量。
def select_evenly(values, maximum):
    if len(values) <= maximum:
        return list(values)
    return [
        values[int(i)]
        for i in np.rint(np.linspace(0, len(values) - 1, maximum)).astype(int)
    ]


def numpy_json_value(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"不能序列化的类型：{type(value).__name__}")


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=numpy_json_value)


def read_inputs(table, master_path, codes):
    with table.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    with master_path.open(encoding="utf-8-sig", newline="") as stream:
        master_rows = list(csv.DictReader(stream))
    master = {row["编号"]: row for row in master_rows}
    if (
        not master
        or not rows
        or len(master) != len(master_rows)
        or len({row["code"] for row in rows}) != len(rows)
    ):
        raise ValueError("预处理清单或主表编号重复")
    accepted_statuses = (
        "processed_pass", "needs_review", "excluded_bad_channels_03",
        "excluded_bad_channels_04", "excluded_bad_fraction",
    )
    for row in rows:
        code = row["code"]
        if code not in master or row["guid"] != master[code]["GUID"]:
            raise ValueError(f"预处理清单与主表对应不一致：{code}")
        if row["status"] not in accepted_statuses:
            raise ValueError(f"预处理清单含未完成或失败记录：{code}")
    if not codes and {row['code'] for row in rows} != set(master):
        missing = sorted(set(master) - {row['code'] for row in rows})
        raise ValueError(f'预处理清单不完整，缺少记录：{missing}')
    selected = [
        row for row in rows
        if row["status"] in ("processed_pass", "needs_review")
    ]
    if codes:
        if set(codes) - {row["code"] for row in selected}:
            raise ValueError("指定编号不是当前保留记录")
        selected = [row for row in selected if row["code"] in codes]
    if not selected:
        raise ValueError("没有可切窗的保留记录")
    return selected, master


def validate_source(raw, row, processed):
    paths = [Path(name) for name in json.loads(row["fif_files"])]
    expected_root = processed.resolve()
    if not paths or any(
        not path.is_file() or path.resolve().parent != expected_root
        for path in paths
    ):
        raise ValueError(f"{row['code']}的处理FIF缺失或来源目录不符")
    if (
        raw.ch_names != CHANNELS
        or raw.info["sfreq"] != QCConfig().target_sfreq
    ):
        raise ValueError("切窗输入不是固定19导、250Hz")
    if not raw.info["custom_ref_applied"] or raw.info["bads"]:
        raise ValueError("切窗输入未平均参考或含坏导")
    intervals = json.loads(row["final_bad_intervals_samples"])
    for start, stop in intervals:
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start < stop <= raw.n_times
        ):
            raise ValueError("最终坏段样本区间不合法")
    return merge_intervals(intervals + annotation_intervals(raw), raw.n_times)


# 切窗不再次滤波或参考，逐窗核验与连续源波形一致。
def export_epochs(raw, starts, length, path):
    events = np.zeros((len(starts), 3), dtype=int)
    events[:, 0] = np.asarray(starts) + raw.first_samp
    events[:, 2] = 1
    epochs = mne.Epochs(
        raw, events, {'valid': 1}, tmin=0,
        tmax=(length - 1) / raw.info['sfreq'], baseline=None, proj=False,
        reject_by_annotation=True, preload=True, verbose='ERROR'
    )
    expected = epochs.get_data()
    if expected.shape != (len(starts), len(CHANNELS), length):
        raise ValueError('窗口数量或形状不符，可能触及BAD边缘')
    if not np.isfinite(expected).all():
        raise ValueError('有效窗口包含非有限值')
    for index, start in enumerate(starts):
        if (
            not np.array_equal(
                expected[index], raw.get_data(start=start, stop=start + length)
            )
        ):
            raise ValueError('切窗与连续FIF波形不同')
    if path.exists():
        raise FileExistsError(f'拒绝覆盖已有分段FIF：{path}')
    try:
        epochs.save(path, fmt='single', overwrite=False, verbose='ERROR')
        saved = mne.read_epochs(path, preload=True, verbose='ERROR')
        if not np.array_equal(saved.events, events):
            raise ValueError('分段FIF回读事件不一致')
        if (
            saved.ch_names != raw.ch_names
            or not np.array_equal(saved.get_data(), expected)
        ):
            raise ValueError('分段FIF回读波形或通道不一致')
    except Exception:
        if path.exists():
            path.unlink()
        raise


def make_record(row, folder, seconds, overlap, maximum, processed):
    code = row['code']
    if not re.fullmatch('[A-Za-z0-9_-]+', code):
        raise ValueError(f'记录编号不合法：{code}')
    paths = [Path(name) for name in json.loads(row['fif_files'])]
    if not paths:
        raise ValueError(f'{code}缺少处理FIF路径')
    before = [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
    with mne.io.read_raw_fif(paths[0], preload=False, verbose='ERROR') as raw:
        intervals = validate_source(raw, row, processed)
        length, step = sample_counts(seconds, overlap, raw.info['sfreq'])
        candidates = valid_starts(raw.n_times, length, step, intervals)
        if seconds == QCConfig().qc_window_seconds and overlap == 0:
            if len(candidates) != int(row['final_available_qc_windows']):
                raise ValueError('可用窗口数与最终质控明细不一致')
        selected = select_evenly(candidates, maximum)
        result = dict(
            status='completed' if selected else 'no_valid_windows',
            available_windows=len(candidates), selected_windows=len(selected),
            selected_start_samples=selected,
            selected_start_seconds=[
                start / raw.info['sfreq'] for start in selected
            ],
            window_samples=length, step_samples=step,
            sfreq_hz=raw.info['sfreq'], n_channels=len(CHANNELS),
            source_first_sample=raw.first_samp, epoch_file='',
            selection_policy='按时间近似均匀选择；不足上限不复制凑数'
        )
        if selected:
            output = folder / f'{code}-epo.fif'
            export_epochs(raw, selected, length, output)
            result['epoch_file'] = str(output)
    after = [(path.stat().st_size, path.stat().st_mtime_ns) for path in paths]
    if before != after:
        if result['epoch_file']:
            Path(result['epoch_file']).unlink()
        raise RuntimeError(f'{code}的连续FIF在切窗期间发生变化')
    return result


WINDOW_FIELDS = [
    'code', 'group', 'guid', 'patient_name', 'subject_id', 'session',
    'source_fif_files', 'status', 'available_windows', 'selected_windows',
    'selected_start_samples', 'selected_start_seconds', 'window_samples',
    'step_samples', 'sfreq_hz', 'n_channels', 'source_first_sample',
    'epoch_file', 'selection_policy', 'window_seconds', 'overlap_seconds',
    'maximum_windows', 'input_sha256', 'error'
]


# 精简主表没有患者ID，保持为空；不能把记录编号当独立患者。
def export_one_record(row, master, arguments, output, fingerprints):
    assessment = master[row['code']]
    result = dict(
        code=row['code'], group=row['group'], guid=row['guid'],
        patient_name=assessment['患者'], subject_id=assessment.get('患者ID', ''),
        session=assessment.get('测试序次', ''), source_fif_files=row['fif_files'],
        window_seconds=arguments.window_seconds,
        overlap_seconds=arguments.overlap_seconds,
        maximum_windows=arguments.max_windows, input_sha256=fingerprints
    )
    try:
        result.update(
            make_record(
                row, output, arguments.window_seconds,
                arguments.overlap_seconds, arguments.max_windows,
                arguments.processed_dir
            )
        )
    except Exception as error:
        result.update(
            status='failed', error=f'{type(error).__name__}: {error}'
        )
    return result


def run_export(rows, master, arguments, output, timestamp):
    table = arguments.base / 'tables' / f'05_切窗清单_{timestamp}.csv'
    table.parent.mkdir(parents=True, exist_ok=True)
    fields = WINDOW_FIELDS
    fingerprints = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            arguments.table, arguments.master, Path(__file__),
            Path(__file__).with_name('config.py'),
            Path(__file__).with_name('03_check_signal_quality.py')
        )
    }
    results = []
    with table.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            result = export_one_record(
                row, master, arguments, output, fingerprints
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
            raise RuntimeError(f'切窗期间输入文件变化：{name}')
    return (table, results)


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=BASE)
    parser.add_argument('--table', type=Path, required=True)
    parser.add_argument('--master', type=Path, default=MASTER)
    parser.add_argument('--processed-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--window-seconds', type=float, default=10)
    parser.add_argument('--max-windows', type=int, default=60)
    parser.add_argument('--overlap-seconds', type=float, default=0)
    parser.add_argument('--codes', nargs='+')
    parser.add_argument('--execute', action='store_true')
    arguments = parser.parse_args()
    return arguments


def export_report(arguments, timestamp, table, output, counts):
    report = write_report(
        arguments.base / 'reports', f'05_切窗报告_{timestamp}', '有效EEG切窗',
        [
            (
                '结果', [f'清单：{table}', f'输出：{output}'], ['状态', '记录数'],
                sorted(counts.items())
            ),
            (
                '方法',
                [
                    '按时间近似均匀选取，不跨BAD/EDGE或间断，不复制补齐。',
                    '不再次滤波、参考或标准化；窗口波形与连续FIF逐样本核验。',
                    '主表未提供患者ID时留空；建模前必须另行确定患者分组映射。'
                ],
                [], []
            )
        ]
    )
    return report


def window_output_directory(arguments):
    step_seconds = arguments.window_seconds - arguments.overlap_seconds
    label = (
        f"{arguments.window_seconds:g}s_{arguments.max_windows}win_"
        f"step{step_seconds:g}s"
    )
    if arguments.output_dir is not None:
        return arguments.output_dir
    # 不同预处理批次不能共享同一切窗目录，避免误读历史结果。
    batch = arguments.processed_dir.resolve().name
    return arguments.base / 'epochs' / batch / label


def main():
    arguments = parse_arguments()
    sample_counts(
        arguments.window_seconds, arguments.overlap_seconds,
        QCConfig().target_sfreq,
    )
    if arguments.max_windows < 1:
        raise ValueError("窗口数量上限必须为正整数")
    rows, master = read_inputs(
        arguments.table, arguments.master, arguments.codes
    )
    output = window_output_directory(arguments)
    print(f"计划{len(rows)}条，输出：{output}")
    if not arguments.execute:
        print("未指定--execute，未读取波形或创建切窗产物。")
        return 0
    if output.exists():
        raise FileExistsError(f"参数组合目录已存在，拒绝覆盖：{output}")
    output.mkdir(parents=True)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    table, results = run_export(rows, master, arguments, output, timestamp)
    counts = Counter(row["status"] for row in results)
    report = export_report(arguments, timestamp, table, output, counts)
    print(f"清单：{table}\n报告：{report}")
    return int(bool(counts["failed"]))


if __name__ == '__main__':
    raise SystemExit(main())
