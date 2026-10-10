"""05公共信号处理：复用preprogress滤波及质控，固定250 Hz，无ICA和坏导修复。"""
import math
import warnings
from dataclasses import dataclass
import mne
import numpy as np
from quality_control import (CHANNELS, QCConfig, merge_intervals, complement,
                             mark_windows, window_metrics, channel_bads, robust_z,
                             annotation_intervals)

@dataclass(frozen=True)
class SignalConfig(QCConfig):
    target_sfreq: int = 250
    highpass_hz: float = 0.5
    lowpass_hz: float = 45.0
    low_transition_hz: float = 0.5
    high_transition_hz: float = 5.0
    notch_hz: float = 50.0
    notch_width_hz: float = 2.0
    notch_transition_hz: float = 1.0
    edge_exclude_seconds: float = 5.0
    max_bad_fraction: float = 0.90
    review_bad_fraction: float = 0.50

def filter_specs(config):
    common = dict(filter_length="auto",phase="zero",fir_window="hamming",fir_design="firwin",verbose="ERROR")
    band = mne.filter.create_filter(None,config.target_sfreq,config.highpass_hz,config.lowpass_hz,
        l_trans_bandwidth=config.low_transition_hz,h_trans_bandwidth=config.high_transition_hz,**common)
    # 与参考项目的单频带阻设计一致。
    half = config.notch_width_hz/2 + config.notch_transition_hz/2
    notch = mne.filter.create_filter(None,config.target_sfreq,config.notch_hz+half,config.notch_hz-half,
        l_trans_bandwidth=config.notch_transition_hz/2,h_trans_bandwidth=config.notch_transition_hz/2,**common)
    return {"bandpass_taps":len(band),"notch_taps":len(notch),
            "boundary_guard_seconds":max(config.edge_exclude_seconds,
                ((len(band)-1)+(len(notch)-1))/(2*config.target_sfreq)+0.1)}


def filter_piece(piece, config):
    common = dict(method="fir",phase="zero",fir_window="hamming",fir_design="firwin",
                  pad="reflect_limited",verbose="ERROR")
    piece = mne.filter.notch_filter(piece,config.target_sfreq,[config.notch_hz],
        notch_widths=config.notch_width_hz,trans_bandwidth=config.notch_transition_hz,**common)
    return mne.filter.filter_data(piece,config.target_sfreq,config.highpass_hz,config.lowpass_hz,
        l_trans_bandwidth=config.low_transition_hz,h_trans_bandwidth=config.high_transition_hz,**common)



def prepare_continuous(raw, initial_intervals, preliminary, config, scratch):
    if raw.ch_names != CHANNELS or raw.info["sfreq"] != config.target_sfreq:
        raise ValueError("只接受当前19导、250 Hz输入，不重复重采样")
    n_times, sfreq = raw.n_times, config.target_sfreq
    # 输出磁盘映射先复制原信号；不可用区间保留原值，不填零或拼接时间。
    data = np.memmap(scratch / "processed.dat", dtype="float64", mode="w+", shape=(19,n_times))
    for start in range(0,n_times,250000):
        stop=min(start+250000,n_times)
        data[:,start:stop]=raw.get_data(start=start,stop=stop)
    initial_intervals = merge_intervals(initial_intervals,n_times)
    specs = filter_specs(config)
    guard = math.ceil(specs["boundary_guard_seconds"]*sfreq)
    blocked, filtered_blocks = list(initial_intervals), []
    for start,stop in complement(initial_intervals,n_times):
        if stop-start <= max(specs["bandpass_taps"],specs["notch_taps"],2*guard):
            blocked.append([start,stop])
            continue
        piece=raw.get_data(start=start,stop=stop)
        if not np.isfinite(piece).all():
            raise ValueError("粗质控后仍有非有限值进入滤波")
        data[:,start:stop]=filter_piece(piece,config)
        blocked.extend([[start,start+guard],[stop-guard,stop]])
        filtered_blocks.append([start,stop])
    blocked=merge_intervals(blocked,n_times)
    size=sfreq*config.qc_window_seconds
    excluded=np.zeros(math.ceil(n_times/size),dtype=bool)
    for start,stop in blocked:mark_windows(excluded,start,stop,size)
    metrics=window_metrics(data,size,excluded)
    final,reasons=channel_bads(metrics,config)
    final=[name for name in CHANNELS if name in set(final+preliminary)]
    finite=np.isfinite(metrics["ptp"])
    amplitude=np.any(finite & (metrics["ptp"]>config.high_ptp_uv*1e-6),axis=0)
    jump=np.any(np.isfinite(metrics["step"]) & (metrics["step"]>config.jump_uv*1e-6),axis=0)
    flat=np.any(finite & (metrics["ptp"]<config.flat_ptp_uv*1e-6),axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        global_rms=np.nanmedian(metrics["rms"],axis=0)
    rms_bad=(robust_z(np.log10(global_rms+1e-15))>8) & (global_rms>100e-6)
    margin=math.ceil(config.artifact_margin_seconds*sfreq)
    final_intervals=merge_intervals(blocked+[[i*size-margin,(i+1)*size+margin]
                                  for i in np.flatnonzero(amplitude|jump|flat|rms_bad)],n_times)
    result=mne.io.RawArray(data,raw.info.copy(),first_samp=raw.first_samp,copy="info",verbose="ERROR")
    # 直接追加注释，避免set_annotations裁掉原来保存的超范围事件或丢失extras。
    result.set_annotations(mne.Annotations([],[],[],orig_time=raw.annotations.orig_time))
    original=raw.annotations
    result.annotations.append(original.onset,original.duration,original.description,
                              ch_names=original.ch_names,extras=original.extras)
    result.annotations.append([raw.first_time+s/sfreq for s,e in final_intervals],
                              [(e-s)/sfreq for s,e in final_intervals],
                              ["BAD_NOICA_unusable"]*len(final_intervals))
    with result.info._unlock():
        result.info["highpass"],result.info["lowpass"]=config.highpass_hz,config.lowpass_hz
    result.info["line_freq"]=config.notch_hz
    result.info["description"]="doc_eeg_analysis 05; offline noICA; average reference; BAD samples never usable; unfiltered BAD samples retain source values before reference."
    qc=dict(bad_channels=final,final_channel_reasons=reasons,filter=specs,
            filtered_blocks_samples=filtered_blocks,bad_intervals_samples=final_intervals,
            filtered_window_counts=dict(amplitude=int(amplitude.sum()),jump=int(jump.sum()),
                                        flat_candidate=int(flat.sum()),global_rms=int(rms_bad.sum())),
            bad_fraction=sum(e-s for s,e in final_intervals)/n_times,
            n_times=n_times,duration_seconds=n_times/sfreq)
    if not final:result.set_eeg_reference("average",projection=False,verbose="ERROR")
    data.flush()
    return result,qc

def candidate_samples(raw, config):
    size = config.target_sfreq*config.qc_window_seconds
    bad = annotation_intervals(raw)
    cursor, values = 0, []
    for start in range(0,raw.n_times-size+1,size):
        while cursor<len(bad) and bad[cursor][1]<=start:
            cursor+=1
        if cursor<len(bad) and bad[cursor][0]<start+size:
            continue
        if not np.isfinite(raw.get_data(start=start,stop=start+size)).all():
            raise ValueError("清洁片段中存在非有限值")
        values.append(start)
    return values


def quality_on_locked_samples(raw, selected, config):
    """参考后复核全部完整可用10秒质控窗口，不抽样、不改变坏段。"""
    counts = {name:0 for name in ("nonfinite", "flat_candidate", "high_amplitude", "jump", "all_channels_zero")}
    for start in selected:
        block = raw.get_data(start=start,stop=start+2500)
        if not np.isfinite(block).all():
            counts["nonfinite"]+=1
            continue
        ptp = np.ptp(block,axis=1)
        counts["flat_candidate"]+=int(np.any(ptp<config.flat_ptp_uv*1e-6))
        counts["high_amplitude"]+=int(np.any(ptp>config.high_ptp_uv*1e-6))
        counts["jump"]+=int(np.any(np.max(np.abs(np.diff(block,axis=1)),axis=1)>config.jump_uv*1e-6))
        counts["all_channels_zero"]+=int(np.max(np.abs(block))<=1e-12)
    return {"checked_epochs":len(selected),"window_counts":counts,
            "selection_changed":False,"note":"候选只要求复核，不自动重新选段或修复"}


