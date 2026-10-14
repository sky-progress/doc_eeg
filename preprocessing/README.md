# 公共预处理

所有运行在服务器evobrain_mamba环境执行。默认只列计划，真实处理须明确授权。

## 文件职责

| 文件 | 内容 |
| --- | --- |
| config.py | 检测、滤波和可用时长参数；中文说明及单位 |
| 01_build_patient_master.py | 评分读取、GUID匹配、主表导出 |
| 02_repair_edf_to_fif.py | 格式检查、临时修复、19导FIF转换及验收 |
| 03_check_signal_quality.py | 初检及共用检测函数，坏导整份排除 |
| 04_preprocess_eeg.py | 滤波、滤波后质控、平均参考、最终坏段补标及保存 |
| 05_make_windows.py | 根据最终坏段均匀选择窗口，回读核验 |
| reporting.py | 共用Markdown报告格式 |

共用检测函数放在03，04及05通过importlib加载，不复制两套实现。
历史实验辅助入口18、21等保留原编号；历史产物不改名。

## 当前数据

代码：`/home/guoyanxin/project/doc_eeg_analysis`。
数据：`/data/gyx/doc_eeg_analysis/preprocessing`。
主表：`tables/63_主表_20261013_165853.csv`，165条，14列（患者ID用于分组，诊断用于后续任务标签）。
转换清单：`tables/03_FIF转换清单_20261013_190410.csv`，165条均完成。
FIF：`raw_fif/`；原EDF只读，修复EDF不永久保存。
表格、报告、日志分别放`tables/`、`reports/`、`logs/`，报告仅Markdown。

排除308-WFL、313-GSR、359-YSH、462-MWS；保留467-YSH总分15。
303使用e2ee5b31，470使用e4d4b1e4；463-WFL对应cfd46c86、总分4，
464-WFL对应22a33540、总分2。完整GUID和EDF位置以主表为准。
148条患者记录与17条HC不是已确认的独立受试者数量。

## 参数与检测规则

QCConfig保存前后阶段检测阈值；SignalConfig增加滤波参数。
修改config.py影响下一次运行，已完成结果不会自动变化。
每次检测及处理保存parameters快照和输入、源码指纹。

初检检查平直、非有限值、持续异常通道及已有坏段。
含间断或已有BAD的窗口不参与通道统计，数字饱和仅在量程标定明确时可查。
滤波不跨坏段或间断，保留滤波边缘保护区。
滤波后任一坏导排除整份；不做ICA、插值、修复坏导或重采样。
平均参考后先复查持续坏导，再按原规则追加异常窗口及保护范围为BAD。
任一阶段发现坏导均排除整份记录；最后检查全部可用窗口。
最终不可用比例超过90%排除，超过50%保留警告。

## 执行入口

```bash
conda activate evobrain_mamba
cd /home/guoyanxin/project/doc_eeg_analysis

# 只核对当前输入计划，不读取波形。
python preprocessing/03_check_signal_quality.py

# 下列为真实执行命令，运行前须获得授权。
python preprocessing/03_check_signal_quality.py --execute

python preprocessing/04_preprocess_eeg.py \
  --qc-table /data/gyx/doc_eeg_analysis/preprocessing/tables/03_信号质量检测_时间.csv \
  --output-dir /data/gyx/doc_eeg_analysis/preprocessing/processed/新批次 \
  --execute

python preprocessing/05_make_windows.py \
  --table /data/gyx/doc_eeg_analysis/preprocessing/tables/04_预处理明细_时间.csv \
  --processed-dir /data/gyx/doc_eeg_analysis/preprocessing/processed/新批次 \
  --window-seconds 10 --max-windows 60 --execute
```

04/05必须显式指定本次输入清单，避免自动读到旧批次。
已存在处理FIF或相同切窗目录拒绝覆盖。
05必须指定`--processed-dir`；默认切窗目录为
`epochs/<预处理批次>/<窗口参数>/`，也可显式指定`--output-dir`。
新的04已包含原06最终补标，不需要另行改写FIF。
切窗不再次滤波、参考或标准化，不跨BAD/EDGE；不足数量不补齐。
主表已提供患者ID；05将其写入切窗清单的subject_id。
分组使用患者ID，记录编号和GUID用于追溯单次测试。

## 验证

`tests/test_preprocessing_pipeline.py`覆盖原阈值迁移、参数生效、间断避让、
参考后补标不改波形、初检到预处理及切窗的合成FIF回读。
原主表和EDF转换测试继续保留。历史研究操作见`docs/preprocessing.md`。

## 本批次续跑与复查

当前连续FIF保存在`processed/20261014_v1`。04新增`--resume-table`，
只在参数、主表、初检清单、GUID及源路径一致时复用已完成结果。
全量执行04/05时输入清单必须覆盖完整主表；小样本调试需显式指定`--codes`。

续跑会核验已保存FIF的分卷、通道、采样率、时间轴、频带、坏段及平均参考，
再检查全部可用窗口与参考后坏导。核验通过的FIF不重复滤波、不改写波形；
参考后发现坏导的记录标为排除，已有FIF保留，05不会导出该记录的窗口。
复查若发现可用窗口仍异常，标记失败并停止将其纳入切窗，不静默复用。
原滤波源码指纹保存在`processing_code_sha256`，本次复查源码指纹
保存在`code_sha256`，续跑来源与清单SHA256分别记录。

```bash
python preprocessing/04_preprocess_eeg.py \
  --qc-table /data/gyx/doc_eeg_analysis/preprocessing/tables/03_信号质量检测_20261013_210842.csv \
  --resume-table /data/gyx/doc_eeg_analysis/preprocessing/tables/04_预处理明细_20261014_131554.csv \
  --output-dir /data/gyx/doc_eeg_analysis/preprocessing/processed/20261014_v1 \
  --execute
```

## 患者ID与重复测试（2026-10-14）

当前主表165条测试记录，对应152个患者ID；12组有多次测试。
患者ID使用稳定记录锚点，例如306-LCS和447-LCS均为`doc_306`，
钟慧仁三份记录399/472/473均为`doc_399`。关联关系集中在01的
`DEFAULT_PATIENT_LINKS`，未来明确的新关联可用`--patient-link 编号=锚点编号`。
既有ID可通过`--previous-master`复用，不随主表排序、增删记录而重新编号。
姓名或缩写只是核对线索，不自动作为身份分组依据。

424-WLI和HC_011_WAN经用户确认是王立康复前后的记录，均为`doc_424`。
HC_011_WAN属于康复后记录；文件位于HC目录不代表其是无患病史的健康对照。
后续任务必须明确是否纳入该记录及其标签，不能从患者ID前缀自动生成标签。
同一患者全部测试及窗口必须留在同一划分，包含内层和外层交叉验证。
不同阶段标签不同的记录不能未经任务约定直接平均为一个患者标签。

本次只更新主表身份字段，不改评分、GUID、EDF路径或FIF波形，不重跑03/04。
03/04明细中记录的主表SHA256仍保留执行时的真实值；原12列主表已归档，
不把历史输入指纹替换成新增字段后的指纹。05将读取更新后的13列主表。
本次身份核验报告：`reports/01_主表更新_20261014_171253.md`。

## 诊断标签维护（2026-10-14）

主表新增“诊断”，位于“总分”之后；一行仍对应一次测试。
首次按编号从评分表读取，核对姓名、评分及GUID，不依据总分推算诊断。
MCS+、MCS-、eMCS及边界诊断保留；具体二分类映射由建模任务定义。
470-MZH仅去掉误粘的科室和GUID，保留“昏迷-UWS边界”。

后续可直接修改当前主表的诊断列。01重建时通过`--previous-master`
保留同一测试已有诊断，包括主动留空；不被旧Excel标签覆盖。
新增记录才使用来源诊断；姓名或GUID变化时拒绝自动复用标签。
默认旧主表仍为`tables/63_主表_20261013_165853.csv`，路径不变。
若后续改用新的主表文件，重建时应显式传入该文件。

HC_011_WAN照录来源HC标签，但其为已确认的康复后记录。
DoC/HC纳排需单独确认，不能只按该标签将其作为普通健康对照。
修改诊断不需要重做FIF或切窗；后续实验应固定执行时的标签版本。
