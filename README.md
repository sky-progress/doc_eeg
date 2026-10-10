# doc_eeg_analysis

基于医院提供的EEG数据开展完整研究项目，当前优先完成公共预处理。具体主任务仍待讨论。

## 环境与执行
全部在服务器执行，使用已有 `evobrain_mamba` 环境，不在本地处理数据。环境记录为 environment.yaml，执行约定见 AGENTS.md。

## 代码结构
- preprocessing/：独立公共预处理；编号脚本01建立主表、02检查EDF，reporting.py生成正式报告。
- src/：主任务的数据加载、模型、训练和评估代码，按需编写。
- configs/：主任务配置。
- docs/：研究方案、方法和实验记录。

## 数据与输出
- 患者原始数据：/data/DoC/raw_data。
- 健康原始数据：/data/北湖脑电，分组依据用户提供的信息。
- 预处理产物：/data/gyx/doc_eeg_analysis/preprocessing。

预处理按用途分为 tables（表格）、reports（正式报告）、logs（日志与追溯）、reference（原始参考表）。不使用 manifests 或 runs；其余产物目录在实际需要时建立。

运行命令和当前主表、报告位置见 preprocessing/README.md。原始文件保持不变，已完成128条EDF结构修复；114条已转FIF，14条间断记录的FIF方案待确认。尚未进行滤波、重参考或切窗。
