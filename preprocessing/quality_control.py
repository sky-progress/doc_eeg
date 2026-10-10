"""复用preprogress的滤波前质量检测规则，不滤波、不修复波形。"""
import math
import warnings
from dataclasses import dataclass, asdict
import numpy as np

CHANNELS = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2",
            "F7", "F8", "T3", "T4", "T5", "T6", "Fz", "Cz", "Pz"]
REFERENCE_VERSION = "NOICA-20261009.1"

@dataclass(frozen=True)
class QCConfig:
    # 与参考项目一致；04仅使用滤波前规则，不使用滤波后的高幅/跳变判据。
    qc_window_seconds: int = 10
    flat_ptp_uv: float = 1.0
    high_ptp_uv: float = 500.0
    jump_uv: float = 200.0
    saturation_min_seconds: float = 0.1
    artifact_margin_seconds: float = 4.0

    def as_dict(self):
        return asdict(self)

# 来源：/home/guoyanxin/project/preprogress/noica_signal.py；SHA256：21b50a497c08f87b53a4190d4c8042129b291096e959cb96261b24b4c29b4f8f
def merge_intervals(intervals, n_times):
    result = []
    for start, stop in sorted(intervals):
        start, stop = max(0, int(start)), min(n_times, int(stop))
        if stop <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], stop)
        else:
            result.append([start, stop])
    return result


def complement(intervals, n_times):
    result, cursor = [], 0
    for start, stop in merge_intervals(intervals, n_times):
        if cursor < start:
            result.append([cursor, start])
        cursor = stop
    if cursor < n_times:
        result.append([cursor, n_times])
    return result


def mark_windows(mask, start, stop, window_samples):
    if stop > start:
        mask[max(0, start//window_samples):min(len(mask), math.ceil(stop/window_samples))] = True


def annotations_relative(raw):
    return [{"onset_seconds":float(onset - raw.first_time), "duration_seconds":float(duration),
             "description":str(description)}
            for onset, duration, description in zip(raw.annotations.onset, raw.annotations.duration,
                                                     raw.annotations.description)]


def annotation_intervals(raw):
    sfreq, intervals = float(raw.info["sfreq"]), []
    for annotation in annotations_relative(raw):
        description = annotation["description"].lower()
        if description.startswith("bad") or "boundary" in description or description.startswith("edge"):
            start = math.floor(annotation["onset_seconds"]*sfreq + 1e-7)
            stop = math.ceil((annotation["onset_seconds"]+annotation["duration_seconds"])*sfreq - 1e-7)
            # 零时长边界仍是间断，前后各保护一个样本。
            if stop <= start:
                start, stop = start-1, start+1
            intervals.append([start, stop])
    return merge_intervals(intervals, raw.n_times)


def window_metrics(data, window_samples, excluded=None):
    count = math.ceil(data.shape[1]/window_samples)
    result = {name:np.full((data.shape[0], count), np.nan) for name in ("ptp", "rms", "step")}
    for index in range(count):
        if excluded is not None and excluded[index]:
            continue
        block = data[:, index*window_samples:min((index+1)*window_samples, data.shape[1])]
        finite_channels = np.isfinite(block).all(axis=1)
        block = block[finite_channels]
        if not len(block):
            continue
        result["ptp"][finite_channels,index] = np.ptp(block, axis=1)
        centered = block-block.mean(axis=1, keepdims=True)
        result["rms"][finite_channels,index] = np.sqrt(np.mean(centered**2, axis=1))
        result["step"][finite_channels,index] = np.max(np.abs(np.diff(block, axis=1)), axis=1) if block.shape[1]>1 else 0
    return result


def robust_z(values):
    center = np.nanmedian(values)
    mad = np.nanmedian(np.abs(values-center))
    # 沿用参考规则：MAD过小时相对异常判据不触发。
    return np.zeros_like(values) if not np.isfinite(mad) or mad<1e-12 else .67448975*(values-center)/mad


def fraction_where(values, predicate):
    finite = np.isfinite(values)
    return np.divide(np.sum(predicate(values)&finite,axis=1), np.sum(finite,axis=1),
                     out=np.zeros(values.shape[0]), where=np.sum(finite,axis=1)>0)


def channel_bads(metrics, config, preliminary=False):
    ptp, rms, step = metrics["ptp"], metrics["rms"], metrics["step"]
    if not np.isfinite(rms).any():
        return [], {}
    flat = fraction_where(ptp, lambda x:x<config.flat_ptp_uv*1e-6)
    high = fraction_where(ptp, lambda x:x>(5e-3 if preliminary else config.high_ptp_uv*1e-6))
    jumps = fraction_where(step, lambda x:x>config.jump_uv*1e-6)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median_rms = np.nanmedian(rms,axis=1)
        step_ratio = np.nanmedian(step/np.maximum(rms,1e-15),axis=1)
    amp_z, high_z = robust_z(np.log10(median_rms+1e-15)), robust_z(high)
    step_z = robust_z(np.log10(step_ratio+1e-12))
    reasons = {}
    for i, name in enumerate(CHANNELS):
        why = []
        if flat[i]>=.05 and flat[i]>np.median(flat)+.10:
            why.append("persistent_relative_flat")
        if high[i]>=.20 and high_z[i]>5:
            why.append("relative_frequent_extreme_amplitude")
        if amp_z[i]>(6 if preliminary else 5) and median_rms[i]>(500e-6 if preliminary else 100e-6):
            why.append("relative_high_rms")
        if amp_z[i]<-6 and median_rms[i]<1e-6:
            why.append("relative_low_rms")
        if not preliminary and step_z[i]>6 and jumps[i]>.05:
            why.append("relative_step_noise")
        if why:
            reasons[name] = why
    return list(reasons), reasons


def true_runs(mask, min_samples):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return [[int(a),int(b)] for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1))
            if b-a>=min_samples]


def gross_qc(raw, source_metadata, config):
    data, sfreq = raw._data, float(raw.info["sfreq"])
    size = int(sfreq*config.qc_window_seconds)
    count = math.ceil(raw.n_times/size)
    metrics = window_metrics(data,size)
    reasons = {name:np.zeros(count,dtype=bool) for name in ("nonfinite", "flat_candidate", "digital_saturation", "inherited_bad")}
    for index in range(count):
        block = data[:,index*size:min((index+1)*size,raw.n_times)]
        reasons["nonfinite"][index] = not np.isfinite(block).all()
        reasons["flat_candidate"][index] = bool(np.any(metrics["ptp"][:,index]<config.flat_ptp_uv*1e-6))
    # 检查至少约1秒的连续常值，避免10秒窗口内短暂脱落被幅度变化掩盖。
    for channel in data:
        for start,stop in true_runs(np.isfinite(channel[:-1]) & np.isfinite(channel[1:]) &
                                   (np.abs(np.diff(channel))<=1e-12), int(sfreq)):
            mark_windows(reasons["flat_candidate"],start,stop+1,size)
    calibration = source_metadata.get("calibration")
    if calibration:
        for index, cal in enumerate(calibration):
            low = np.isclose(data[index],cal["physical_min_v"],rtol=0,atol=1e-12)
            high = np.isclose(data[index],cal["physical_max_v"],rtol=0,atol=1e-12)
            # 饱和要求持续停留在同一数字量程边缘；FIF输入不提供此标定。
            for mask in (low,high):
                for start,stop in true_runs(mask,max(1,math.ceil(config.saturation_min_seconds*sfreq))):
                    mark_windows(reasons["digital_saturation"],start,stop,size)
    for start,stop in annotation_intervals(raw):
        mark_windows(reasons["inherited_bad"],start,stop,size)
    mask = np.logical_or.reduce(list(reasons.values()))
    margin = int(math.ceil(config.artifact_margin_seconds*sfreq))
    intervals = merge_intervals([[i*size-margin,(i+1)*size+margin] for i in np.flatnonzero(mask)],raw.n_times)
    preliminary, channel_reasons = channel_bads(metrics,config,preliminary=True)
    return intervals, preliminary, {"window_counts":{name:int(value.sum()) for name,value in reasons.items()},
                                    "preliminary_channel_reasons":channel_reasons,
                                    "digital_saturation_check_available":bool(calibration)}


