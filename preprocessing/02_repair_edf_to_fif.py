"""
    修复EDF并转换为FIF
    现场检查EDF，临时修复已知缺80字节模式，验收后仅保留19导FIF。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mne
import numpy as np
from mne.io.edf.edf import _read_annotations_edf

EEG_CHANNELS = (
    "Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2",
    "F7", "F8", "T3", "T4", "T5", "T6", "Fz", "Cz", "Pz",
)
SIGNAL_FIELDS = (
    ("label", 16), ("transducer", 80), ("unit", 8),
    ("physical_min", 8), ("physical_max", 8),
    ("digital_min", 8), ("digital_max", 8),
    ("prefilter", 80), ("samples", 8), ("reserved", 32),
)
TIME_MARKER = re.compile(rb"^([+-]\d+(?:\.\d*)?)\x14\x14\x00")
MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
MANIFEST_COLUMNS = (
    "code", "guid", "source_edf", "source_bytes", "source_mtime_ns",
    "status", "error", "header_layout", "fif_files", "fif_bytes",
    "n_channels", "n_samples", "sfreq_hz", "annotation_count",
    "gap_count", "data_sha256", "processed_at",
)


@dataclass(frozen=True)
class SignalHeader:
    label: str
    unit: str
    physical_min: float
    physical_max: float
    digital_min: float
    digital_max: float
    samples: int


@dataclass(frozen=True)
class EDFHeader:
    fixed: bytes
    signal_bytes: bytes
    signals: tuple[SignalHeader, ...]
    missing_bytes: int
    data_offset: int
    record_bytes: int
    record_count: int
    record_seconds: float
    annotation_index: int | None


@dataclass(frozen=True)
class TimeGap:
    record_index: int
    gap_seconds: float
    next_onset: float


@dataclass(frozen=True)
class DataScan:
    digest: str
    annotation_payload: bytes
    first_onset: float
    gaps: tuple[TimeGap, ...]


def read_signal_headers(data: bytes, count: int) -> tuple[SignalHeader, ...]:
    fields = {}
    offset = 0
    for name, width in SIGNAL_FIELDS:
        fields[name] = [
            data[offset + index * width:offset + (index + 1) * width]
            .decode("latin1").strip()
            for index in range(count)
        ]
        offset += count * width
    return tuple(
        SignalHeader(
            fields["label"][index], fields["unit"][index],
            float(fields["physical_min"][index]),
            float(fields["physical_max"][index]),
            float(fields["digital_min"][index]),
            float(fields["digital_max"][index]),
            int(fields["samples"][index]),
        )
        for index in range(count)
    )


def restore_signal_labels(data: bytes, count: int) -> bytes:
    labels = [
        data[index * 16:(index + 1) * 16].decode("latin1").strip()
        for index in range(count)
    ]
    if count < 6 or labels[:3] != ["Fp1", "Fp2", "F3"]:
        raise ValueError("缺80字节文件不符合已确认的前导联模板")
    if labels[5] != "C4" or not labels[3].startswith("F4"):
        raise ValueError("缺80字节文件的F4/C4位置不符合已知损坏模式")
    if not re.fullmatch(r"[\d\s]*", labels[4]):
        raise ValueError("C3位置不是已知的记录数覆盖模式，停止猜测修复")
    restored = bytearray(data)
    restored[48:64] = b"F4".ljust(16)
    restored[64:80] = b"C3".ljust(16)
    return bytes(restored)


def inspect_layout(path: Path, prefix: bytes, missing: int) -> EDFHeader:
    count = int(prefix[252 - missing:256 - missing])
    declared_bytes = int(prefix[184 - missing:192 - missing])
    seconds = float(prefix[244 - missing:252 - missing])
    if not 1 <= count <= 256 or declared_bytes != 256 * (count + 1):
        raise ValueError("通道数与EDF声明头长度不一致")
    if not np.isfinite(seconds) or seconds <= 0:
        raise ValueError("EDF记录时长无效")
    offset = declared_bytes - missing
    with path.open("rb") as stream:
        header_bytes = stream.read(offset)
    if len(header_bytes) != offset:
        raise ValueError("EDF头被截断")
    signal_bytes = header_bytes[256 - missing:]
    if missing:
        signal_bytes = restore_signal_labels(signal_bytes, count)
    signals = read_signal_headers(signal_bytes, count)
    if any(signal.samples <= 0 for signal in signals):
        raise ValueError("通道每记录采样点数无效")
    record_bytes = 2 * sum(signal.samples for signal in signals)
    records, remainder = divmod(path.stat().st_size - offset, record_bytes)
    if remainder or records <= 0:
        raise ValueError("数据区长度不能整除记录大小，文件可能截断")
    if not missing and int(prefix[236:244]) not in (-1, records):
        raise ValueError("EDF声明记录数与数据长度不符")
    annotation_indices = [
        index for index, signal in enumerate(signals)
        if signal.label == "EDF Annotations"
    ]
    if len(annotation_indices) > 1:
        raise ValueError("存在多个注释通道，需要单独确认")
    return EDFHeader(
        header_bytes[:256 - missing], signal_bytes, signals,
        missing, offset, record_bytes, records, seconds,
        annotation_indices[0] if annotation_indices else None,
    )


def inspect_edf(path: Path) -> EDFHeader:
    with path.open("rb") as stream:
        prefix = stream.read(256)
    if prefix[:8] != b"0       ":
        raise ValueError("EDF版本签名异常，不属于支持的修复格式")
    errors = []
    for missing in (0, 80):
        try:
            return inspect_layout(path, prefix, missing)
        except (ValueError, UnicodeDecodeError) as error:
            errors.append(f"缺失{missing}字节模式：{error}")
    raise ValueError("；".join(errors))


def repaired_fixed_header(header: EDFHeader) -> bytes:
    fixed = header.fixed
    if header.missing_bytes:
        date_text = fixed[88:96].decode("ascii")
        day, month, year = map(int, date_text.split("."))
        year += 2000 if year < 85 else 1900
        datetime(year, month, day)
        date = f"{day:02d}-{MONTHS[month - 1]}-{year:04d}"
        # 原文件缺失的采集者和设备信息不能虚构。
        recording = f"Startdate {date} X X X".encode().ljust(80)
        fixed = fixed[:88] + recording + fixed[88:]
    if len(fixed) != 256:
        raise ValueError("修复后EDF固定头长度不是256字节")
    if header.record_count > 99999999:
        raise ValueError("记录数超过EDF字段可表示范围")
    restored = bytearray(fixed)
    restored[236:244] = str(header.record_count).encode().ljust(8)
    if header.annotation_index is not None:
        restored[192:236] = b"EDF+C".ljust(44)
    return bytes(restored)


def annotation_bytes(record: bytes, header: EDFHeader) -> bytes:
    index = header.annotation_index
    if index is None:
        return b""
    offset = 2 * sum(signal.samples for signal in header.signals[:index])
    length = 2 * header.signals[index].samples
    return record[offset:offset + length]


def scan_time_marker(
    payload: bytes, index: int, previous: float | None,
    header: EDFHeader,
) -> tuple[float, TimeGap | None]:
    payload.decode("utf8")
    match = TIME_MARKER.match(payload)
    if match is None:
        raise ValueError(f"第{index}条EDF记录缺少有效时间标记")
    onset = float(match.group(1))
    if previous is None:
        return onset, None
    difference = onset - previous - header.record_seconds
    if difference < -1e-6:
        raise ValueError(f"第{index}条EDF记录时间倒退")
    gap = TimeGap(index, difference, onset) if difference > 1e-6 else None
    return onset, gap


def copy_data_records(
    source: Path, temporary: Path, header: EDFHeader,
) -> DataScan:
    hasher = hashlib.sha256()
    payload = bytearray()
    gaps = []
    previous = None
    first_onset = 0.0
    record_index = 0
    batch_size = max(1, 8 * 1024 * 1024 // header.record_bytes)
    with source.open("rb") as reader, temporary.open("xb") as writer:
        reader.seek(header.data_offset)
        writer.write(repaired_fixed_header(header))
        writer.write(header.signal_bytes)
        for block in iter(
            lambda: reader.read(batch_size * header.record_bytes), b"",
        ):
            if len(block) % header.record_bytes:
                raise ValueError("复制时遇到不完整EDF记录")
            if header.annotation_index is not None:
                for start in range(0, len(block), header.record_bytes):
                    annotation = annotation_bytes(
                        block[start:start + header.record_bytes], header,
                    )
                    onset, gap = scan_time_marker(
                        annotation, record_index, previous, header,
                    )
                    if record_index == 0:
                        first_onset = onset
                    if gap is not None:
                        gaps.append(gap)
                    previous = onset
                    payload.extend(annotation)
                    record_index += 1
            hasher.update(block)
            writer.write(block)
    if header.annotation_index is not None:
        if record_index != header.record_count:
            raise ValueError("注释时间标记数量与EDF记录数不符")
    return DataScan(
        hasher.hexdigest(), bytes(payload), first_onset, tuple(gaps),
    )


def verify_temporary_data(path: Path, header: EDFHeader, scan: DataScan):
    expected_size = 256 * (len(header.signals) + 1)
    expected_size += header.record_bytes * header.record_count
    if path.stat().st_size != expected_size:
        raise ValueError("临时修复EDF的大小核验失败")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(256 * (len(header.signals) + 1))
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != scan.digest:
        raise ValueError("临时EDF数据区与原始数据不一致")
    if scan.gaps:
        with path.open("r+b") as stream:
            stream.seek(192)
            stream.write(b"EDF+D".ljust(44))


def compress_times(values: np.ndarray, scan: DataScan) -> np.ndarray:
    original = np.asarray(values, dtype=float)
    compressed = original.copy()
    for gap in scan.gaps:
        end = gap.next_onset - scan.first_onset
        start = end - gap.gap_seconds
        compressed -= np.clip(original - start, 0, end - start)
    return compressed


def restore_annotations(raw, header: EDFHeader, scan: DataScan) -> None:
    if not scan.annotation_payload:
        return
    annotations = _read_annotations_edf(
        np.frombuffer(scan.annotation_payload, dtype="<i2"),
        ch_names=raw.ch_names,
    )
    onsets = compress_times(annotations.onset, scan)
    ends = compress_times(annotations.onset + annotations.duration, scan)
    extras = [
        {
            "original_onset_seconds": float(onset),
            "original_duration_seconds": float(duration),
            "outside_signal_span": bool(
                new_onset < 0 or new_onset > raw.n_times / raw.info["sfreq"]
            ),
        }
        for onset, duration, new_onset in zip(
            annotations.onset, annotations.duration, onsets,
        )
    ]
    # append保留原始范围外事件；暂停不填零，事件映射到拼接时间轴。
    raw.set_annotations(mne.Annotations(
        [], [], [], orig_time=raw.info["meas_date"],
    ))
    raw.annotations.append(
        onsets, np.maximum(0, ends - onsets), annotations.description,
        ch_names=annotations.ch_names, extras=extras,
    )
    for gap in scan.gaps:
        extra = {
            "original_gap_seconds": gap.gap_seconds,
            "original_next_onset_seconds": gap.next_onset,
            "record_index": gap.record_index,
        }
        raw.annotations.append(
            [gap.record_index * header.record_seconds] * 2, [0, 0],
            ["BAD boundary", "EDGE boundary"], extras=[extra, extra],
        )


def prepare_eeg_channels(raw, header: EDFHeader) -> None:
    missing = sorted(set(EEG_CHANNELS) - set(raw.ch_names))
    if missing:
        raise ValueError(f"缺少目标EEG通道：{', '.join(missing)}")
    sample_counts = {
        signal.samples for signal in header.signals
        if signal.label in EEG_CHANNELS
    }
    if len(sample_counts) != 1:
        raise ValueError("19导EEG的源采样率不一致")
    descriptions = raw.annotations.description.copy()
    raw.pick(list(EEG_CHANNELS))
    np.testing.assert_array_equal(raw.annotations.description, descriptions)
    raw.set_channel_types(
        {channel: "eeg" for channel in EEG_CHANNELS}, verbose="ERROR",
    )
    raw.set_montage(
        mne.channels.make_standard_montage("standard_1020"),
        match_case=False, on_missing="raise", verbose="ERROR",
    )
    if not all(np.isfinite(channel["loc"][:3]).all()
               for channel in raw.info["chs"]):
        raise ValueError("19导标准电极坐标缺失")


def physical_record(
    source: Path, header: EDFHeader, record: int,
) -> np.ndarray:
    with source.open("rb") as stream:
        stream.seek(header.data_offset + record * header.record_bytes)
        digital = np.frombuffer(stream.read(header.record_bytes), dtype="<i2")
    expected = {}
    offset = 0
    units = {"uV": 1e-6, "µV": 1e-6, "μV": 1e-6, "mV": 1e-3, "V": 1.0}
    for signal in header.signals:
        if signal.label in EEG_CHANNELS:
            if signal.unit not in units:
                raise ValueError(f"EEG物理单位不支持：{signal.unit}")
            span = signal.digital_max - signal.digital_min
            if not np.isfinite(span) or span == 0:
                raise ValueError("EEG数字标定范围无效")
            # 保留有符号增益，不交换physical_min/max。
            values = digital[offset:offset + signal.samples].astype(float)
            physical = signal.physical_min + (
                values - signal.digital_min
            ) * (signal.physical_max - signal.physical_min) / span
            expected[signal.label] = physical * units[signal.unit]
        offset += signal.samples
    return np.stack([expected[channel] for channel in EEG_CHANNELS])


def verify_source_calibration(source: Path, raw, header: EDFHeader) -> None:
    samples = int(round(raw.info["sfreq"] * header.record_seconds))
    if raw.n_times != header.record_count * samples:
        raise ValueError("源EDF与MNE样本数不一致")
    records = {0, header.record_count // 2, header.record_count - 1}
    for record in sorted(records):
        expected = physical_record(source, header, record)
        actual = raw.get_data(start=record * samples,
                              stop=(record + 1) * samples)
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def verify_fif(path: Path, raw, scan: DataScan) -> None:
    check = mne.io.read_raw_fif(path, preload=False, verbose="ERROR")
    try:
        if check.ch_names != list(EEG_CHANNELS):
            raise ValueError("FIF通道名称或顺序错误")
        if (check.n_times, check.info["sfreq"]) != (
            raw.n_times, raw.info["sfreq"],
        ):
            raise ValueError("FIF采样率或样本数错误")
        if check.info["meas_date"] != raw.info["meas_date"]:
            raise ValueError("FIF采集时间元信息改变")
        np.testing.assert_array_equal(
            [html.unescape(text) for text in check.annotations.description],
            raw.annotations.description,
        )
        expected_starts = raw.annotations.onset.astype("float32").astype(float)
        expected_ends = (
            raw.annotations.onset + raw.annotations.duration
        ).astype("float32").astype(float)
        np.testing.assert_allclose(
            check.annotations.onset, expected_starts, rtol=0, atol=1e-6,
        )
        np.testing.assert_allclose(
            check.annotations.duration, expected_ends - expected_starts,
            rtol=0, atol=1e-6,
        )
        if list(check.annotations.extras) != list(raw.annotations.extras):
            raise ValueError("FIF事件追溯信息改变")
        for start in sorted({0, raw.n_times // 2, max(0, raw.n_times - 750)}):
            stop = min(raw.n_times, start + 750)
            expected = raw.get_data(start=start, stop=stop).astype("float32")
            np.testing.assert_array_equal(
                check.get_data(start=start, stop=stop), expected.astype(float),
            )
    finally:
        check.close()


def publish_fifs(files: list[Path], output_root: Path) -> list[Path]:
    targets = [output_root / path.name for path in files]
    if any(path.exists() for path in targets):
        raise FileExistsError("目标FIF已存在，禁止覆盖")
    published = []
    try:
        for source, target in zip(files, targets):
            source.rename(target)
            published.append(target)
        return targets
    except OSError:
        for target in published:
            target.rename(files[targets.index(target)])
        raise


def conversion_metadata(header, raw, scan, published: list[Path]) -> dict:
    return {
    "header_layout": (
        "missing_80" if header.missing_bytes else "standard"
    ),
    "fif_files": json.dumps([str(path) for path in published]),
    "fif_bytes": sum(path.stat().st_size for path in published),
    "n_channels": 19, "n_samples": raw.n_times,
    "sfreq_hz": raw.info["sfreq"],
    "annotation_count": len(raw.annotations),
    "gap_count": len(scan.gaps), "data_sha256": scan.digest,
}


def verify_source_unchanged(source: Path, original_stat) -> None:
    current = source.stat()
    if (current.st_size, current.st_mtime_ns) != (
        original_stat.st_size, original_stat.st_mtime_ns,
    ):
        raise ValueError("原始EDF在转换期间发生变化")


def convert_record(row: dict, output_root: Path) -> dict:
    code = row["编号"]
    source = Path(row["所在服务器位置"])
    if not re.fullmatch(r"[A-Za-z0-9_-]+", code):
        raise ValueError(f"编号不能作为安全文件名：{code}")
    if list(output_root.glob(f"{code}_raw*.fif")):
        raise FileExistsError(f"已有本记录FIF，需核对转换清单：{code}")
    source_stat = source.stat()
    header = inspect_edf(source)
    with tempfile.TemporaryDirectory(prefix=f".edf_{code}_",
                                     dir=output_root) as directory:
        work = Path(directory)
        temporary = work / "repaired.edf"
        scan = copy_data_records(source, temporary, header)
        verify_temporary_data(temporary, header, scan)
        raw = mne.io.read_raw_edf(temporary, preload=False, verbose="ERROR")
        published = []
        try:
            restore_annotations(raw, header, scan)
            prepare_eeg_channels(raw, header)
            verify_source_calibration(source, raw, header)
            files = raw.save(
                work / f"{code}_raw.fif", fmt="single", overwrite=False,
                split_size="2GB", buffer_size_sec=30, verbose="ERROR",
            )
            files = [Path(path) for path in files]
            verify_fif(files[0], raw, scan)
            verify_source_unchanged(source, source_stat)
            published = publish_fifs(files, output_root)
            verify_fif(published[0], raw, scan)
            verify_source_unchanged(source, source_stat)
            metadata = conversion_metadata(header, raw, scan, published)
        except Exception:
            for path in published:
                path.unlink()
            raise
        finally:
            raw.close()
    return metadata


def read_master(path: Path, codes: list[str] | None) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"编号", "GUID", "所在服务器位置"} <= set(reader.fieldnames or []):
            raise ValueError("主表缺少编号、GUID或服务器位置字段")
        rows = list(reader)
    if len({row["编号"] for row in rows}) != len(rows):
        raise ValueError("主表编号重复")
    selected = [row for row in rows if not codes or row["编号"] in codes]
    if codes and set(codes) != {row["编号"] for row in selected}:
        raise ValueError("指定编号不全在主表中")
    for row in selected:
        if not row["GUID"] or not Path(row["所在服务器位置"]).is_file():
            raise ValueError(f"主表GUID或EDF路径无效：{row['编号']}")
    if len({row["GUID"] for row in selected}) != len(selected):
        raise ValueError("主表同GUID多行，需先明确单次转换队列")
    return selected


def save_manifest(records: dict[str, dict], path: Path) -> None:
    temporary = path.with_suffix(".writing.csv")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(records.values())
    temporary.replace(path)


def load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["code"]: row for row in csv.DictReader(stream)}


def verify_completed(row: dict, previous: dict) -> None:
    source = Path(row["所在服务器位置"])
    stat = source.stat()
    if (previous["guid"], previous["source_edf"]) != (
        row["GUID"], str(source),
    ):
        raise ValueError("已有FIF的GUID或源路径与主表不一致")
    if int(previous["source_bytes"]) != stat.st_size:
        raise ValueError("已有FIF对应的原始EDF大小改变")
    if int(previous["source_mtime_ns"]) != stat.st_mtime_ns:
        raise ValueError("已有FIF对应的原始EDF修改时间改变")
    files = [Path(path) for path in json.loads(previous["fif_files"])]
    if not files or not all(path.is_file() for path in files):
        raise FileNotFoundError("已有FIF或分卷缺失")
    raw = mne.io.read_raw_fif(files[0], preload=False, verbose="ERROR")
    try:
        if raw.ch_names != list(EEG_CHANNELS):
            raise ValueError("已有FIF的19导顺序错误")
        if raw.n_times != int(previous["n_samples"]):
            raise ValueError("已有FIF的样本数与清单不一致")
        if raw.info["sfreq"] != float(previous["sfreq_hz"]):
            raise ValueError("已有FIF的采样率与清单不一致")
    finally:
        raw.close()


def record_result(row: dict, output_root: Path) -> dict:
    source = Path(row["所在服务器位置"])
    stat = source.stat()
    result = dict.fromkeys(MANIFEST_COLUMNS, "")
    result.update(
        code=row["编号"], guid=row["GUID"], source_edf=str(source),
        source_bytes=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
        status="failed",
    )
    try:
        result.update(convert_record(row, output_root), status="complete")
    except Exception as error:
        # 单条结构或转换失败保留原因，继续检查其余录音。
        result["error"] = f"{type(error).__name__}: {error}"
        logging.exception("转换失败：%s", row["编号"])
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    result["processed_at"] = now.isoformat()
    return result


def write_report(records: dict, path: Path, master: Path) -> None:
    complete = [row for row in records.values() if row["status"] == "complete"]
    failed = [row for row in records.values() if row["status"] == "failed"]
    size = sum(int(row["fif_bytes"]) for row in complete)
    lines = [
        "# EDF临时修复与FIF转换", "",
        f"时间：{datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}",
        f"主表：{master}",
        f"完成{len(complete)}条，失败{len(failed)}条，FIF共{size / 1024**3:.2f}GiB。",
        "19导、原采样率、standard_1020坐标；未滤波、重参考或ICA。",
        "原始EDF只读；修复副本及失败的临时FIF在记录处理后清理。",
        "数据区SHA256、源数字标定、FIF首中末波形及事件回读验收。",
        "间断暂停压缩为BAD/EDGE边界，原暂停时长存于事件extras。",
        "", "## 失败记录", "",
    ]
    lines.extend(f"- {row['code']}：{row['error']}" for row in failed)
    if not failed:
        lines.append("无。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--codes", nargs="+", help="仅转换指定编号")
    parser.add_argument("--resume-manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    rows = read_master(arguments.master, arguments.codes)
    for name in ("raw_fif", "tables", "logs", "reports"):
        (arguments.base / name).mkdir(parents=True, exist_ok=True)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    manifest = arguments.resume_manifest or (
        arguments.base / "tables" / f"02_FIF转换清单_{timestamp}.csv"
    )
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                arguments.base / "logs" / f"02_转换_{timestamp}.log",
                encoding="utf-8",
            ),
        ],
    )
    records = load_manifest(manifest)
    for position, row in enumerate(rows, start=1):
        code = row["编号"]
        previous = records.get(code)
        if previous and previous["status"] == "complete":
            verify_completed(row, previous)
            logging.info("[%d/%d] %s 已验收，沿用", position, len(rows), code)
            continue
        records[code] = record_result(row, arguments.base / "raw_fif")
        save_manifest(records, manifest)
        logging.info(
            "[%d/%d] %s %s %s", position, len(rows), code,
            records[code]["status"], records[code]["error"],
        )
    # 续接旧03清单时保留原报告位置，避免产生重复报告。
    report_step = "03" if manifest.stem.startswith("03_") else "02"
    report_stamp = manifest.stem.removeprefix(f"{report_step}_FIF转换清单_")
    report_name = f"{report_step}_EDF转FIF_{report_stamp}.md"
    report = arguments.base / "reports" / report_name
    write_report(records, report, arguments.master)
    logging.info("转换结束，清单：%s；报告：%s", manifest, report)
    if any(row["status"] == "failed" for row in records.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
