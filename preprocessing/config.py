"""预处理参数集中定义；幅值单位为微伏，时间单位为秒。

先沿用preprogress的数值。修改参数会改变纳入记录及可用片段，
因此每次执行必须将完整参数写入输出清单。
"""

from dataclasses import asdict, dataclass
from pathlib import Path

BASE = Path("/data/gyx/doc_eeg_analysis/preprocessing")
MASTER = BASE / "tables/63_主表_20261013_165853.csv"
CONVERSION_MANIFEST = BASE / "tables/03_FIF转换清单_20261013_190410.csv"
CHANNELS = [
    "Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2",
    "F7", "F8", "T3", "T4", "T5", "T6", "Fz", "Cz", "Pz",
]
REFERENCE_VERSION = "NOICA-20261009.1"


@dataclass(frozen=True)
class QCConfig:
    """粗检和后续质控参数，前后阶段使用不同幅值门槛。"""

    target_sfreq: int = 250
    qc_window_seconds: int = 10
    flat_ptp_uv: float = 1.0
    # 后两项用于滤波后及参考后检查，不用于初检的超幅判断。
    high_ptp_uv: float = 500.0
    jump_uv: float = 200.0
    saturation_min_seconds: float = 0.1
    artifact_margin_seconds: float = 4.0
    flat_run_seconds: float = 1.0
    # 同时满足绝对幅值和相对异常条件才判定坏导。
    preliminary_high_ptp_uv: float = 5000.0
    preliminary_high_rms_uv: float = 500.0
    preliminary_high_rms_z: float = 6.0
    high_rms_uv: float = 100.0
    high_rms_z: float = 5.0
    low_rms_uv: float = 1.0
    low_rms_z: float = -6.0
    flat_min_fraction: float = 0.05
    flat_relative_fraction: float = 0.10
    high_min_fraction: float = 0.20
    high_fraction_z: float = 5.0
    step_noise_z: float = 6.0
    jump_min_fraction: float = 0.05
    global_rms_z: float = 8.0
    global_rms_uv: float = 100.0

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SignalConfig(QCConfig):
    """滤波和可用时长规则；不做ICA、重采样或坏导插值。"""

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
    fir_phase: str = "zero"
    fir_window: str = "hamming"
    fir_design: str = "firwin"
    filter_pad: str = "reflect_limited"
