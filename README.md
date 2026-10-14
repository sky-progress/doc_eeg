# doc_eeg_analysis

基于医院EEG数据开展研究。所有数据处理和训练在服务器的
`evobrain_mamba`环境执行；代码放home，数据及实验产物放数据区域。

## 当前进度

本批次主表165条测试记录，包含患者ID和可修正的诊断字段。
预处理完成：152份记录保留，13份因坏导排除，无失败。
切窗完成：152份记录各60个10秒窗口，共9120窗、139个患者ID。

旧建模代码及配置已清理。新的任务定义、患者划分、数据加载、训练和评价
尚未实现，也没有启动本批次模型训练。旧实验结果保留在数据区域，
其标签和划分不能直接作为本批次实验方案。

## 代码结构

- `preprocessing/`：当前01–05预处理及切窗脚本，详见其中的README。
- `tests/`：当前主表、EDF转换和预处理的回归测试。
- `src/datasets/`：预留任务定义、患者划分和数据加载位置。
- `src/models/`：预留各模型的独立适配位置。
- `src/training/`：预留共用训练流程位置。
- `src/evaluation/`：预留共用评价位置。
- `configs/`：预留任务及实验配置位置。
- `third_party/`：预留官方源码及许可证位置。
- `docs/modeling.md`：建模重建范围和已讨论的设计约定。

## 数据与输出

代码：`/home/guoyanxin/project/doc_eeg_analysis`。
数据：`/data/gyx/doc_eeg_analysis`。

当前主表：`preprocessing/tables/63_主表_20261013_165853.csv`。
连续FIF：`preprocessing/processed/20261014_v1/`。
窗口：`preprocessing/epochs/20261014_v1/10s_60win_step10s/`。
表格、报告和日志分别放数据区的`tables/`、`reports/`、`logs/`。
未来建模产物放数据区`runs/`，不在home保存数据或模型权重。

原始DoC数据：`/data/DoC/raw_data/`；HC来源数据：`/data/北湖脑电/`。
原始EDF只读，修复EDF不永久保存。运行规范见`AGENTS.md`，
环境记录见`environment.yaml`。
