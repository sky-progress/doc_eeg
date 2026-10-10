"""05：复用参考流程，滤波、滤波后质控、平均参考；默认计划，--execute执行。"""
import argparse
import csv
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import mne
import numpy as np
from quality_control import CHANNELS, REFERENCE_VERSION
from signal_processing import (SignalConfig, prepare_continuous, candidate_samples,
                               quality_on_locked_samples, complement)
from reporting import write_report

BASE=Path("/data/gyx/doc_eeg_analysis/preprocessing")


def encode(value):
    return json.dumps(value,ensure_ascii=False,default=lambda x:x.item() if isinstance(x,np.generic) else x)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_output(raw,expected,qc,config):
    if raw.ch_names!=CHANNELS or raw.info["sfreq"]!=250 or raw.n_times!=expected.n_times:
        raise ValueError("输出通道、采样率或样本数变化")
    if not raw.info["custom_ref_applied"] or raw.info["bads"]:
        raise ValueError("输出平均参考或坏导状态错误")
    if raw.first_samp!=expected.first_samp or raw.info["meas_date"]!=expected.info["meas_date"]:
        raise ValueError("输出采集时间轴变化")
    if not np.isclose(raw.info["highpass"],.5) or not np.isclose(raw.info["lowpass"],45):
        raise ValueError("输出频带元信息错误")
    if len(raw.annotations)!=len(expected.annotations):raise ValueError("输出事件数量变化")
    for actual,target in [(raw.annotations.onset,expected.annotations.onset),
                          (raw.annotations.duration,expected.annotations.duration)]:
        if not np.allclose(actual,target,rtol=0,atol=1e-5):raise ValueError("输出事件时间变化")
    if raw.annotations.description.tolist()!=expected.annotations.description.tolist() or raw.annotations.extras!=expected.annotations.extras:
        raise ValueError("输出事件文字或原间断信息变化")
    for a,b in zip(raw.info["chs"],expected.info["chs"]):
        if not np.allclose(a["loc"],b["loc"],rtol=0,atol=1e-7,equal_nan=True):raise ValueError("电极坐标变化")
    # 全量回读比较，仅允许FIF单精度舍入；可用区间另查有限值和平均参考。
    for start in range(0,raw.n_times,250000):
        stop=min(start+250000,raw.n_times)
        if not np.allclose(raw.get_data(start=start,stop=stop),expected.get_data(start=start,stop=stop),rtol=2e-6,atol=1e-12,equal_nan=True):
            raise ValueError("输出波形回读不一致")
    for start,stop in complement(qc["bad_intervals_samples"],raw.n_times):
        for first in range(start,stop,250000):
            block=raw.get_data(start=first,stop=min(first+250000,stop))
            if not np.isfinite(block).all() or np.max(np.abs(block.mean(axis=0)))>1e-9:
                raise ValueError("可用区间含非有限值或不满足平均参考")


def process_record(row,config,scratch,processed):
    if not re.fullmatch(r"[A-Za-z0-9_-]+",row["code"]):raise ValueError("记录编号不合法")
    if row["status"]=="excluded_bad_channels":
        return dict(status="excluded_bad_channels_04",bad_channels=json.loads(row["bad_channels"]),
                    bad_channel_reasons=json.loads(row["bad_channel_reasons"]),fif_files=[])
    if row["status"] not in ("preliminary_pass","needs_review"):raise ValueError("04记录状态不可用于05")
    sources=[Path(p) for p in json.loads(row["fif_files"])]
    if not sources or any(not p.is_file() for p in sources):raise ValueError("输入FIF或分卷缺失")
    if any(processed.glob(row["code"]+"_preprocessed_raw*.fif")):
        raise FileExistsError("已有该记录的处理FIF，拒绝覆盖；需另行确认续跑或重跑方案")
    before=[(p.stat().st_size,p.stat().st_mtime_ns) for p in sources]
    output=None;published=[]
    try:
        with mne.io.read_raw_fif(sources[0],preload=str(scratch/"source.dat"),verbose="ERROR") as source:
            if source.info["custom_ref_applied"] or source.info["projs"] or source.info["bads"]:
                raise ValueError("输入已参考、有投影或已有坏导")
            if source.n_times!=int(row["n_samples"]):raise ValueError("04样本数与输入不一致")
            if source.info["highpass"]>.5 or source.info["lowpass"]<45:raise ValueError("输入带宽不符合参考流程")
            output,qc=prepare_continuous(source,json.loads(row["bad_intervals_samples"]),
                                         json.loads(row["bad_channels"]),config,scratch)
            result=dict(n_samples=output.n_times,duration_seconds=qc["duration_seconds"],
                        bad_channels=qc["bad_channels"],bad_channel_reasons=qc["final_channel_reasons"],
                        bad_fraction=qc["bad_fraction"],bad_intervals_samples=qc["bad_intervals_samples"],
                        filter=qc["filter"],filtered_window_counts=qc["filtered_window_counts"],
                        filtered_blocks_samples=qc["filtered_blocks_samples"],fif_files=[])
            if qc["bad_channels"]:result["status"]="excluded_bad_channels_05"
            elif qc["bad_fraction"]>config.max_bad_fraction:result["status"]="excluded_bad_fraction"
            else:
                reviews=[]
                if row["status"]=="needs_review":reviews.append("04平直或非有限值候选待复核")
                if qc["bad_fraction"]>config.review_bad_fraction:reviews.append("不可用比例超过50%")
                if qc["filtered_window_counts"]["amplitude"] or qc["filtered_window_counts"]["global_rms"]:
                    reviews.append("滤波后高幅候选待复核")
                available=candidate_samples(output,config)
                post=quality_on_locked_samples(output,available,config)
                if post["window_counts"]["nonfinite"]:raise ValueError("参考后可用窗口含非有限值")
                if any(post["window_counts"].values()):reviews.append("平均参考后信号候选待复核")
                result.update(post_reference_qc=post,review_reasons=reviews,
                              available_qc_windows=len(available),status="needs_review" if reviews else "processed_pass")
                # 不导出10秒片段，也不限制数量；仅保存带BAD标记的连续FIF。
                name=row["code"]+"_preprocessed_raw.fif"
                staging=scratch/"fif";staging.mkdir()
                output.save(staging/name,fmt="single",overwrite=False,split_naming="neuromag",verbose="ERROR")
                with mne.io.read_raw_fif(staging/name,preload=False,verbose="ERROR") as saved:verify_output(saved,output,qc,config)
                for file in sorted(staging.glob("*.fif")):
                    target=processed/file.name
                    if target.exists():raise FileExistsError(target)
                    file.rename(target);published.append(target)
                with mne.io.read_raw_fif(processed/name,preload=False,verbose="ERROR") as saved:verify_output(saved,output,qc,config)
                result["fif_files"]=[str(processed/name)]+[str(p) for p in published if p.name!=name]
        if before!=[(p.stat().st_size,p.stat().st_mtime_ns) for p in sources]:raise RuntimeError("输入文件大小或修改时间变化")
        return result
    except Exception:
        # 仅清理本次尚未成功发布的派生文件，绝不删除输入或既有结果。
        for path in published:path.unlink()
        raise
    finally:
        if output is not None:output.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",type=Path,default=BASE)
    parser.add_argument("--qc-table",type=Path,default=BASE/"tables/04_信号质量检测_20261010_200606_236687.csv")
    parser.add_argument("--codes",nargs="+")
    parser.add_argument("--execute",action="store_true")
    args=parser.parse_args()
    with args.qc_table.open(encoding="utf-8-sig",newline="") as handle:rows=list(csv.DictReader(handle))
    if not rows or len({r["code"] for r in rows})!=len(rows):raise ValueError("04明细为空或有重复编号")
    if args.codes:
        if set(args.codes)-{r["code"] for r in rows}:raise ValueError("指定编号不在04明细中")
        rows=[r for r in rows if r["code"] in args.codes]
    if any(r["status"] not in ("preliminary_pass","needs_review","excluded_bad_channels") for r in rows):raise ValueError("04含异常状态，先解决后执行")
    excluded=sum(r["status"]=="excluded_bad_channels" for r in rows)
    print(f"计划{len(rows)}份：跳过04坏导{excluded}份，处理{len(rows)-excluded}份。",flush=True)
    if not args.execute:
        print("未指定--execute，不读取波形、不创建结果。");return 0
    config=SignalConfig()
    stamp=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")
    tables,reports,logs,processed=[args.base/x for x in ("tables","reports","logs","processed")]
    for folder in (tables,reports,logs,processed):folder.mkdir(parents=True,exist_ok=True)
    # 单一执行锁避免同一结果目录并发写入；异常结束保留已写入明细。
    lock=logs/"05_preprocessing.lock"
    with lock.open("x",encoding="utf-8") as handle:handle.write(stamp)
    table=tables/f"05_预处理明细_{stamp}.csv"
    fields=["code","group","guid","source_fif_files","status","n_samples","duration_seconds",
            "bad_channels","bad_channel_reasons","bad_fraction","bad_intervals_samples","filter",
            "filtered_window_counts","filtered_blocks_samples","post_reference_qc","review_reasons",
            "available_qc_windows","fif_files","error","reference_version","parameters","qc_table_sha256","code_sha256"]
    hashes={p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name("signal_processing.py"),Path(__file__).with_name("quality_control.py")]}
    qc_hash=digest(args.qc_table);results=[]
    try:
        with table.open("x",encoding="utf-8-sig",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
            for row in rows:
                result={k:row[k] for k in ("code","group","guid")}
                result.update(source_fif_files=row["fif_files"],reference_version=REFERENCE_VERSION,
                              parameters=config.as_dict(),qc_table_sha256=qc_hash,code_sha256=hashes)
                try:
                    with tempfile.TemporaryDirectory(prefix="05_work_",dir=logs) as tmp:
                        result.update(process_record(row,config,Path(tmp),processed))
                except Exception as exc:result.update(status="failed",error=f"{type(exc).__name__}: {exc}")
                writer.writerow({k:encode(v) if isinstance(v,(dict,list)) else v for k,v in result.items()})
                handle.flush();results.append(result)
                print(f"{len(results)}/{len(rows)} {row['code']} {result['status']}",flush=True)
        if digest(args.qc_table)!=qc_hash:raise RuntimeError("执行期间04明细发生变化")
        counts=Counter(r["status"] for r in results)
        report=write_report(reports,"05_预处理报告_"+stamp[:15],"19导EEG信号预处理报告",[
            ("处理结果",[f"04明细：{args.qc_table}。结果明细：{table}。波形：{processed}。"],
             ["状态","记录数"],sorted(counts.items())),
            ("流程与限制",["复用preprogress：各有效连续块分别50 Hz陷波、0.5–45 Hz零相位FIR带通，滤波后质控，19导普通平均参考；保持250 Hz，不做ICA、插值或坏导修复。",
             "滤波前后任一坏导整份排除；不可用比例严格超过90%整份排除，超过50%复核。保留04复核状态。",
             "滤波保护范围按实际核长计算；不跨粗坏段或间断滤波。BAD区间保留原波形（平均参考可能改变数值），绝不能忽略标注送入模型。",
             "保存连续时间轴、事件与原间断extras，不切窗、不限制60段、不采用30段最低数量。10秒窗口仅用于质控。",
             "排除记录不发布处理波形，原始EDF和修复FIF全部保留。已保存波形不等于完成临床评分对齐或可直接训练。",
             "输出经全量波形回读、通道/时间轴/电极位置/事件核验；单精度FIF存在正常舍入。"],[],[]),
            ("排除与异常记录",[],["编号","状态","原因"],
             [[r["code"],r["status"],r.get("bad_channel_reasons") or r.get("error") or "不可用比例超过90%"]
              for r in results if r["status"].startswith("excluded") or r["status"]=="failed"])
        ])
        print(f"明细：{table}\n报告：{report}")
        return 1 if counts["failed"] else 0
    finally:lock.unlink()


if __name__=="__main__":raise SystemExit(main())
