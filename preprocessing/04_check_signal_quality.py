"""04：只读检测19导FIF，坏导整份排除；默认仅列计划，--execute才读取波形。"""
import argparse
import csv
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mne
import numpy as np
from mne.io.constants import FIFF
from quality_control import CHANNELS, QCConfig, REFERENCE_VERSION, gross_qc
from reporting import write_report

BASE = Path("/data/gyx/doc_eeg_analysis/preprocessing")


def inspect_record(row, scratch, config):
    files = [Path(p) for p in json.loads(row["fif_files"])]
    if not files or any(not p.is_file() for p in files):
        raise ValueError("FIF主文件或分卷缺失")
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    # 磁盘映射避免整份长记录常驻内存；临时数据随本记录检测结束清理。
    with mne.io.read_raw_fif(files[0], preload=str(scratch / "waveform.dat"), verbose="ERROR") as raw:
        if raw.ch_names != CHANNELS or raw.info["sfreq"] != 250:
            raise ValueError("输入必须是当前固定顺序的19导、250 Hz FIF")
        if any(ch["unit"] != FIFF.FIFF_UNIT_V for ch in raw.info["chs"]):
            raise ValueError("EEG单位不是V")
        if raw.info["custom_ref_applied"] or raw.info["projs"]:
            raise ValueError("输入已重参考或含投影，不能作为04原始信号检测输入")
        intervals, bads, details = gross_qc(raw, {"calibration": None}, config)
        # 输入已有坏导标记时同样整份排除，不通过移除单导继续分析。
        reasons = details["preliminary_channel_reasons"]
        for name in raw.info["bads"]:
            reasons.setdefault(name, []).append("input_marked_bad")
        bads = [name for name in CHANNELS if name in reasons]
        counts = details["window_counts"]
        suspect = any(counts[k] for k in ("nonfinite", "flat_candidate"))
        status = "excluded_bad_channels" if bads else "needs_review" if suspect else "preliminary_pass"
        result = dict(status=status, n_channels=len(raw.ch_names), sfreq_hz=raw.info["sfreq"],
                      n_samples=raw.n_times, duration_seconds=raw.n_times/raw.info["sfreq"],
                      bad_channels=bads, bad_channel_reasons=reasons,
                      window_counts=counts, bad_intervals_samples=intervals,
                      gross_bad_fraction=sum(e-s for s,e in intervals)/raw.n_times,
                      digital_saturation_check_available=False)
    if before != [(p.stat().st_size, p.stat().st_mtime_ns) for p in files]:
        raise RuntimeError("检测期间输入文件大小或修改时间发生变化")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--codes", nargs="+", help="仅检测指定编号")
    parser.add_argument("--execute", action="store_true", help="读取真实波形并生成检测结果")
    args = parser.parse_args()
    registry = args.registry or args.base / "tables/03_修复对应表.csv"
    with registry.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len({r["code"] for r in rows}) != len(rows):
        raise ValueError("修复对应表包含重复编号")
    if args.codes:
        missing = set(args.codes) - {r["code"] for r in rows}
        if missing:
            raise ValueError(f"编号不存在：{sorted(missing)}")
        rows = [r for r in rows if r["code"] in args.codes]
    if not rows or any(r["status"] != "成功" or r["eeg19_status"] != "完成" for r in rows):
        raise ValueError("只接受03已成功完成19导筛选的记录")
    print(f"计划检测{len(rows)}份记录；只读FIF，不滤波、不重参考、不切窗。", flush=True)
    if not args.execute:
        print("未指定--execute，未读取波形或创建结果。")
        return 0
    config = QCConfig()
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")
    tables, reports, logs = [args.base / p for p in ("tables", "reports", "logs")]
    for folder in (tables, reports, logs):
        folder.mkdir(parents=True, exist_ok=True)
    output = tables / f"04_信号质量检测_{stamp}.csv"
    fields = ["code", "group", "guid", "fif_files", "status", "n_channels", "sfreq_hz",
              "n_samples", "duration_seconds", "bad_channels", "bad_channel_reasons",
              "window_counts", "bad_intervals_samples", "gross_bad_fraction",
              "digital_saturation_check_available", "error", "reference_version", "parameters", "script_sha256", "rules_sha256"]
    results = []
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in
              [("script_sha256", Path(__file__)), ("rules_sha256", Path(__file__).with_name("quality_control.py"))]}
    # 逐条落表，异常保留原因并继续；不修改主表、修复对应表或任何FIF。
    with output.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            result = {key: row[key] for key in ("code", "group", "guid", "fif_files")}
            result.update(reference_version=REFERENCE_VERSION, parameters=config.as_dict(), **hashes)
            try:
                with tempfile.TemporaryDirectory(prefix="04_qc_", dir=logs) as scratch:
                    result.update(inspect_record(row, Path(scratch), config))
            except Exception as exc:
                result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            writer.writerow({k: json.dumps(v, ensure_ascii=False, default=lambda x: x.item() if isinstance(x, np.generic) else x) if isinstance(v, (dict, list)) else v
                             for k, v in result.items()})
            handle.flush()
            results.append(result)
            print(f"{len(results)}/{len(rows)} {row['code']} {result['status']}", flush=True)
    counts = Counter(r["status"] for r in results)
    report = write_report(reports, "04_信号质量检测报告_" + stamp[:15], "19导EEG滤波前质量检测报告", [
        ("检测结果", [f"输入：{registry}；明细：{output}。", "坏导整份排除仅为分析状态，原始与修复文件均保留。"],
         ["状态", "记录数"], sorted(counts.items())),
        ("规则与范围", [f"复用preprogress协议{REFERENCE_VERSION}的gross_qc与滤波前channel_bads；参数：{json.dumps(config.as_dict(), ensure_ascii=False)}。",
         "使用10秒质控窗口（不是研究切窗），粗坏段两侧扩展4秒。零时长BAD/EDGE边界仍标记不可用。",
         "相对平直、频繁极高幅、相对高RMS和相对低RMS按参考实现判断；命中任一坏导整份排除。MAD过小时相对判据不触发。",
         "FIF不提供EDF数字量程标定，数字饱和检查不可用；不新增推测量程。",
         "preliminary_pass只代表通过初筛，滤波后仍需再次检测坏导；needs_review表示平直或非有限值候选。间断标记本身不是坏导。",
         "gross_bad_fraction为扩展合并后的不可用比例，不是最终滤波后比例；04不应用最终90%排除规则，不限制片段数量。",
         "不做ICA、插值、滤波、重参考或切窗，不生成处理波形或逐记录报告。"], [], []),
        ("需处理记录", [], ["编号", "状态", "坏导或错误"],
         [[r["code"], r["status"], r.get("error") or r.get("bad_channel_reasons") or "平直/非有限值候选（非坏导整份排除）"]
          for r in results if r["status"] != "preliminary_pass"])
    ])
    print(f"检测明细：{output}\n报告：{report}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
