# 公共预处理

脚本按两位编号表示执行顺序，内部模块不编号。所有操作在服务器 evobrain_mamba 环境执行，执行前确认。

## 产物位置
根目录：`/data/gyx/doc_eeg_analysis/preprocessing`。
- `tables/`：主表、健康组编号登记、文件检查和逐通道明细。
- `reports/`：可阅读的正式报告，包含结论、方法、证据、限制与后续建议；仅提供 Markdown；文件名和正文记录北京时间。
- `logs/`：每次操作的日志、配置、逐文件诊断和来源追溯信息。
- `reference/`：原始参考评分表。

目前不建立 figures/，修复与处理开始时再建 repaired/、processed/。修复数据不设 v1/。

## 01 建立主表
当前主表为 `tables/01_受试者主表_20261010_170859.xlsx`，包含患者组111条测试记录和健康组17条记录，共128条。患者原入组状态保持不变；健康组未提供的临床字段留空。

```bash
conda activate evobrain_mamba
cd /home/guoyanxin/project/doc_eeg_analysis
python preprocessing/01_build_patient_master.py \
  --patient-master /data/gyx/doc_eeg_analysis/preprocessing/tables/01_患者主表_20261010_144336.xlsx \
  --healthy /data/北湖脑电 \
  --healthy-registry /data/gyx/doc_eeg_analysis/preprocessing/tables/01_健康组编号_20261010_150752.csv \
  --output /data/gyx/doc_eeg_analysis/preprocessing/tables \
  --reports /data/gyx/doc_eeg_analysis/preprocessing/reports \
  --logs /data/gyx/doc_eeg_analysis/preprocessing/logs
```

从原始评分表重新构建患者表时改用 `--reference` 和 `--raw`；该模式重新核验同GUID副本。后续健康组重建沿用已有登记表，保持编号稳定。

## 02 检查 EDF
只读检查固定头、通道表、数据区长度及MNE直接读取结果，不修复、不转换。

```bash
python preprocessing/02_inspect_edf.py \
  --master /data/gyx/doc_eeg_analysis/preprocessing/tables/01_受试者主表_20261010_150752.xlsx \
  --tables /data/gyx/doc_eeg_analysis/preprocessing/tables \
  --reports /data/gyx/doc_eeg_analysis/preprocessing/reports \
  --logs /data/gyx/doc_eeg_analysis/preprocessing/logs
```

正式检查报告：`reports/02_EDF格式检查报告_20261010_155547.md`。文件检查和通道明细均在 tables/。历史152829检查曾误判负增益，表格以“历史”标记，后续使用153102结果。

历史快照保留操作发生时的原路径与哈希；迁移映射见 `logs/artifact_relocations_20261010.json`。旧预览仅保留为历史产物，不新建图目录。原始EDF和表格临床内容未变。

## 03 修复 EDF 并转 FIF
`03_repair_edf_to_fif.py` 最小修复头部与被覆盖的F4/C3标签，数据区逐字节保留；EEG使用用户确认的standard_1020模板，辅助通道按眼电、心电、肌电或misc分类。

```bash
python preprocessing/03_repair_edf_to_fif.py \
  --master /data/gyx/doc_eeg_analysis/preprocessing/tables/01_受试者主表_20261010_150752.xlsx \
  --inspection /data/gyx/doc_eeg_analysis/preprocessing/logs/02_inspect_20261010_153102/details.jsonl \
  --base /data/gyx/doc_eeg_analysis/preprocessing
```

先用 `--pilot` 验证代表文件。已验证输出通过同一份 `tables/03_修复对应表.csv` 续接，不覆盖。修复EDF保存到 `repaired/edf/`，FIF到 `repaired/fif/`；日志在logs，仅生成一份Markdown报告。

连续记录转FIF，真实采集间断记录保留EDF+D，FIF处理方案需要用户确认。FIF波形和事件时间遵循MNE格式的float32舍入；中文事件以MNE字符实体编码保存，显示时用html.unescape恢复文字，原始精确事件数据保留在EDF。大文件可能按FIF大小限制分片，所有分片均为同一记录，必须一起保留。

不滤波、不重参考、不分段处理信号；10–20坐标为标准模板，不是个体实测电极位置。

### 主表修订
用户确认338-SXY、352-ZYL、356-GSX可用，已恢复纳入。旧119条记录保持不变，评分表暂缓/排除剩23条。当前EDF修复任务仍基于先前119条批次；新增3条尚未补跑检查和转换。

用户进一步确认301-FBI、303-MWS、307-LJB、308-WFL、314-HAD、344-ZGZ的指定GUID，已恢复纳入。309-ZCH仍待确认GUID。主表原122条保持不变，评分表暂缓/排除剩17条。后续恢复指定记录可使用 `--restore-codes` 与 `--guid-overrides 编号=GUID`，不自动选择其他同名记录。

### 当前修复状态
当前主表128条均已保存修复EDF。114条已转FIF，14条存在真实采集间断，仅保存EDF+D，FIF方案待确认。新增9条均验证通过。修复对应表为 `tables/03_修复对应表.csv`，最新正式报告为 `reports/03_EDF修复与FIF转换报告_20261010_171420.md`。补跑指定记录可使用02/03脚本的 `--codes`，03使用该批次02生成的 `details.jsonl`。
