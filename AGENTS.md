# 项目协作规则

## 项目与服务器
- 项目名称：doc_eeg_analysis。按完整研究项目组织，公共预处理及首组切窗已完成；首轮任务已确认DoC/HC二分类。
- SSH：ssh -p 11419 guoyanxin@16.tcp.vip.cpolar.cn
- 代码目录：/home/guoyanxin/project/doc_eeg_analysis
- 数据及运行产物目录：/data/gyx/doc_eeg_analysis
- 患者组原始数据：/data/DoC/raw_data
- 健康组原始数据：/data/北湖脑电（分组依据用户提供的信息）。
- 运行环境：evobrain_mamba，位置为 /home/guoyanxin/miniconda3/envs/evobrain_mamba。

## 执行约定
- 所有项目命令、数据检查、预处理、训练和评估在服务器执行，禁止在本地运行或下载数据进行处理。
- 执行项目代码时使用 evobrain_mamba；未经用户同意，不安装、升级或修改环境依赖。
- 每次执行前说明目的、涉及路径和预期结果，等待用户明确同意；只读检查也需要确认。
- 一次确认可授权明确列出的操作组，超出范围重新确认。
- 未经明确授权，不覆盖已有文件、不删除原始数据、不修改旧项目、不提交或推送 Git。

## 结构与存储
- preprocessing/ 是独立公共预处理模块；可执行脚本使用两位顺序编号（如 01_build_patient_master.py），内部模块不编号；参数文件为 preprocessing/config.yaml。
- src/ 保存主任务的数据加载、模型、训练和评估代码；configs/ 保存主任务配置；docs/ 保存方法说明和研究记录。
- Home 项目目录仅保存代码、配置和必要的轻量文档。
- 预处理产物按用途保存：preprocessing/tables/ 放主表、编号登记和检查明细；reports/ 放正式中文报告；logs/ 放日志、配置和追溯记录；reference/ 放原始参考表。
- 预处理不使用 manifests/ 或 runs/。暂无图时不创建 figures/；repaired/ 和 processed/ 在实际修复及处理时再创建。
- repaired/ 直接包含 edf/、fif/，不加 v1/；修复对应清单放在 tables/。
- 主任务划分放在数据区域 splits/，实验运行产物放在 runs/。
- 主任务实验可使用独立运行目录；预处理报告和表格使用步骤编号与时间命名，日志按步骤及运行时间保存，避免覆盖；权重放在数据区域。
- 保存每次操作的来源与参数，不静默覆盖旧结果；修复数据维护一套，重新修复已有输出前确认覆盖范围。
- 数据路径集中配置，不散落在实现代码中。

## 代码与研究要求
- 代码尽量精简，避免重复逻辑、冗余文件和不必要的抽象。
- 使用中文注释解释关键步骤、参数依据和易错点，保持注释与实现一致。
- 按实际需要编写脚本和配置，不提前填入未确定的处理参数或占位实现。
- 正式预处理前先建立数据清单、检查元信息、核对重复并评估质量。
- 患者组两个原始目录存在部分重复；不只凭文件名判重，不将同一受试者不同记录自动合并。
- 去重、滤波、重参考、重采样、分段和剔除规则经讨论确认后执行，保留处理状态及剔除原因。
- 不预设标签、分类目标或临床结局；任务相关处理归主任务负责。
- 从数据拟合的归一化或特征选择参数按训练划分拟合，避免验证和测试信息泄漏。

## 健康组编号
- 健康组编号使用 hc_三位序号_姓名拼音首字母（大写），登记表保存在数据区域，新增记录时沿用已有编号。
- 未提供的健康组评分、诊断和入组状态留空，不推定为零或正常诊断。

## 产物精简与报告时间
- 正式报告只生成一份 Markdown（.md），不默认生成 HTML、PDF或预览副本。
- 报告文件名及正文记录生成时间，统一使用北京时间（Asia/Shanghai）；任务时间与报告生成时间分别标注。
- 按实际需要保留主表、必要明细、报告与日志，不默认生成重复格式、额外汇总文件或图片。

## 通道与结构修复
- 用户确认EEG采用国际10–20标准，保持已有通道顺序，按已确认模板恢复被覆盖的F4/C3，标准位置使用standard_1020。
- 辅助通道不统一标为EEG，不在结构修复阶段滤波或重参考。
- 保留负增益与数据区原始字节，核验数据摘要、样本数、标定、通道及事件。
- 用户已确认间断记录可拼接为FIF：不填补缺失数据，保留BAD/EDGE boundary，重映射事件时间并保留原间断时长；后续切窗与滤波不得跨边界。修复EDF+D保持不变。

## 最终FIF通道
- 用户确认最终FIF只保留19导EEG：Fp1、Fp2、F3、F4、C3、C4、P3、P4、O1、O2、F7、F8、T3、T4、T5、T6、Fz、Cz、Pz。
- A1/A2及眼电、心电、肌电等辅助通道不进入最终FIF，修复EDF继续保留完整通道。
- 已有FIF通过03脚本的 --eeg19-only 模式筛选，验证后替换；保留事件、原时间元信息和间断边界。

## 信号质量检测与坏导策略
- 用户确认后续复用preprogress（NOICA-20261009.1）规则，不做ICA、不插值或修复坏导。
- 任一坏导命中检测判据，排除该份完整EEG记录，原文件保留；局部坏段单独标记。
- 04仅执行滤波前粗检测，后续滤波后仍执行参考规则复查；不提前引入最多60段等任务取样规则。

## 05信号预处理
- 05复用参考流程滤波与滤波后质控：50 Hz陷波、0.5–45 Hz FIR带通、19导平均参考，保持250 Hz。
- 滤波前后坏导整份排除；不可用比例>90%排除、>50%复核；保留04复核状态。
- 不套用参考项目最多60段或至少30段的取样门槛，不导出切窗；10秒窗口仅作质控。
- BAD区间保留波形与时间轴，不用零值占位，必须由后续数据加载排除；完整事件及间断extras保留。
- 05真实预处理已完成；后续重跑或覆盖仍须用户确认。

## 首轮任务与数据划分
- 用户确认DoC/HC二分类：DoC=1、HC=0。按唯一受试者分层5折，seed=42。
- 每轮1折测试、下一折验证、其余3折训练；同人全部窗口和重复记录同集合，306/447-LCS保持同一患者。
- 所有模型及后续窗口组合沿用当前受试者分折；归一化、特征选择、类别权重/重采样仅在训练集合内确定。
- 先窗口预测，再记录内概率平均、同人多记录平均，以受试者为主要评价单位；不把窗口数量视作独立患者数量。
- 不默认逐窗归一化；测试折不用于早停、选模型、阈值或调参。
- 划分表位于数据区splits/doc_vs_hc，方案详见docs/modeling.md；当前只完成划分，模型训练须另行确认。

## 数据加载
- 用户确认保留现有src/datasets、models、training、evaluation目录，不执行此前讨论的平铺迁移。
- 数据加载模块为src/datasets/eeg_dataset.py，默认返回µV波形及稳定来源信息，不自动拟合标准化、不默认逐窗归一化。
- 若启用标准化，只在当轮训练受试者拟合；受试者等权，同人记录再等权，并核对训练ID、轮次及输入清单指纹。
- 固定五折元信息及训练/验证/测试小样本读取均已验证；未在真实数据上拟合标准化、未开始模型训练。

## 共用训练评价
- trainer.py与evaluator.py已通过合成验证，尚未训练真实模型；epochs/lr/patience及具体模型须在实际训练前确认。
- 默认验证受试者Macro-F1选最佳模型，阈值0.5；测试集合只在最佳模型确定后评估。
- 窗口概率先记录内平均，再同人记录等权平均；主要指标Macro-F1、Balanced Accuracy、混淆矩阵，补充AUROC及两类Precision/Recall/F1和Accuracy。
- 训练损失按受试者/记录/窗口分配权重，可选训练类平衡；窗口数量不作为独立受试者样本量。
- 真实实验产物放数据区runs，保留当前目录结构，不默认生成图或HTML。

## 训练种子与EvoBrain首轮
- 用户确认后续每个模型使用训练种子42、2026、2029；受试者分折固定seed=42，不随训练种子改变。
- 首个模型EvoBrain，在evobrain_mamba环境，5折×3种子=15任务；用户选择官方默认100轮上限、5轮早停、lr3e-4，batch128已GPU验证。
- 训练Adam、weight_decay5e-4、余弦学习率、clip_grad5；验证受试者Macro-F1选模型，阈值0.5及患者级评价沿用既有方案，首轮不新增数据增强。
- 网络依据官方83b290cb160beca8df65749f2520fb5cd34b2d84源码，183834参数；适配修正批次时间索引、逐窗口边mask及PE符号。输入250→200Hz逐秒FFT100频点，不改FIF；频谱统计仅在训练患者拟合。
- 使用GPU1单任务串行，不停止其他进程；启动不等于训练完成。


## 独立平衡qEEG实验
- 用户另行确认14 DoC+14 HC平衡实验；原全样本划分及EvoBrain结果保留。编号10按seed42抽取具备60窗的唯一患者，每人一份最早session记录，全部14HC纳入。
- 独立5折每类3/3/3/3/2人，各训练/验证/测试集合1:1；数据目录splits/doc_vs_hc_balanced14_seed42。
- 首轮传统模型采用患者特征统计汇总：20项qEEG×全脑及5脑区×median/IQR=240项。窗口特征同时保存，不逐窗归一化、不在全数据上筛选特征。
- 输出features/doc_vs_hc_balanced14_seed42/10s60；仅执行特征提取，随机森林训练待另行确认；详情docs/modeling.md。


## 随机森林首轮完成
- 用户已确认并执行编号11随机森林平衡基线：500树/min_samples_leaf2/max_featuressqrt，5折×3种子15任务；无标准化、筛特征或调参，验证集未并入训练。
- 结果runs/random_forest_balanced14_10s60_20261011_131731，模型和折外预测已回读核验；下一步新实验需另行确认，不能按测试结果选择患者或特征。


## SVM首轮完成与设备信息
- 用户确认补充SVM，编号12已完成：同14+14队列/240特征/五折，训练集StandardScaler+RBF SVC(C1,gammascale,probabilityFalse)，15任务。
- 该SVC优化为确定性，三个种子结果相同是预期；AUROC用决策分数，分类用predict；结果runs/svm_rbf_balanced14_10s60_20261011_132917已回读核验。
- 用户说明HC/DoC使用同一种设备；尚未验证具体采集设置，不能用分类性能高低证明设备影响消除。新增实验仍须确认。


## EvoBrain平衡队列启动
- 用户确认同14+14队列EvoBrain，configs/evobrain_balanced14.yaml，固定五折×三个种子，训练参数沿用100轮/早停5/lr3e-4/batch128。
- 结果目录/data/gyx/doc_eeg_analysis/runs/evobrain_balanced14_10s60_20261011_140557，GPU1串行，显存空闲门槛8192MB；后台PID3447336，目前仅启动。旧实验保留。
- 09按划分动态核验折外人数，现有汇总报告加入Nature日志YAML元信息，不额外生成重复日志。

- 最新：batch128首折OOM未完成一轮；用户明确确认改batch64重启，门槛恢复12288MB。当前运行/data/gyx/doc_eeg_analysis/runs/evobrain_balanced14_10s60_b64_20261011_140755，PID3451198；原失败目录保留。


## GRU-GCN平衡实验
- 用户明确确认新增官方源码、适配、配置及编号13；同14+14、同五折和三种子；100轮/早停5/batch64/lr3e-4，GPU1串行，12GB显存门槛。
- 当前/data/gyx/doc_eeg_analysis/runs/gru_gcn_balanced14_10s60_20261011_152137，后台PID3705516；只启动，不预先宣称完成。先验证真实训练输入、梯度和批次独立性。
- 没有改动已有Dataset、共用训练器、评价及早停；共享EvoBrain确定性输入缓存，官方GRU-GCN全导联对边编码保持原样。

- GRU-GCN用户确认续跑：13新增--resume，8次完成保留，失败折归档；PID3764277，原目录续跑7次。
- 关键：导入EvoBrain/Mamba可能提前初始化CUDA；GPU必须在启动Python前绑定。原GRU-GCN实际GPU0，当前启动环境CUDA_VISIBLE_DEVICES=1，查询与训练GPU1一致。模型/训练参数未改。


## 当前主任务：MCS与UWS
- 用户停止DoC/HC新实验，改做DoC内部MCS/UWS；MCS+/MCS-合并。确认UWS（行为学）归UWS、MCS-（重度）归MCS；eMCS/非DoC/深昏迷/边界待定暂不纳入。
- 编号14名单/划分已生成并核验：87唯一患者，UWS42/MCS45，88记录、5227窗。UWS0/MCS1；306/447同人同集合；303-MWS7窗保留，不抽样凑1:1。
- 数据目录splits/mcs_vs_uws，任务清单14_MCS_UWS任务清单.csv、固定分层五折14_受试者5折划分_seed42.csv；每轮测试1折、验证下一折、训练3折。未训练。
- task_class/label为新任务标签，group保留患者组；后续数据读取/评价须另行适配，不能把所有患者映射为1。模型入口相互独立，公共功能使用通用模块；GPU在启动Python前绑定。
- 修改前说明文件、原因及实验影响，等待用户确认；已有旧任务数据及实验不自动删除/覆盖。


## 公共任务支持已适配
- 用户明确授权公共数据读取/训练器/评价一起适配任务，默认doc_vs_hc(HC0/DoC1)，mcs_vs_uws/uws_vs_mcs(UWS0/MCS1)。任务定义集中src/datasets/task_spec.py；配置class_names顺序须一致。
- 五个模块已兼容适配，网络/FFT/图/损失/优化/早停算法不改；旧指标与数值转换完全一致，旧缓存兼容；各任务标签/指标/报告明确，测试通过。原源码归档于新实验目录，不覆盖旧结果。
- 新任务EvoBrain已启动：/data/gyx/doc_eeg_analysis/runs/evobrain_mcs_uws_10s60_20261011_164955，PID3989700，87人/88记录/5227窗，五折×三个种子，batch64、lr3e-4、100轮/早停5。GPU在依赖导入前绑定且UUID核验；当前仅启动。


## 当前对照实验：旧最优EvoBrain/两套预处理
- 用户明确启动共同74人（UWS/MCS37/37）、75同GUID记录、4500同原始时间窗口，旧/新预处理各15任务共30。编号15入口及独立配置，旧项目只读。
- 旧Dropout优化协议：每折0/0.2/0.1/0/0.2，batch16/lr1e-4/100轮/patience12/均衡16窗每患者/验证患者交叉熵，种子2026/2027/2028；旧82人实际归属限制到74人，双臂相同。网络与输入适配完全旧版，184015参数；用户明确授权本对照采用旧种子。
- 当前/data/gyx/doc_eeg_analysis/runs/evobrain_preprocessing_compare74_20261011_203557，PID237878，GPU1，先只读连续FIF建立两个配对波形缓存，再正式训练；不能把启动/数据缓存当作完成。
- 不修改旧项目/原波形/旧结果；后续任何方案变更须说明确认。


## 原窗口对照（编号16）
- 用户明确启动74人旧预处理/旧最优模型的原60窗对照，与15旧预处理共同窗口组相比仅恢复原窗口。新编号16入口及配置，15及旧项目不改。
- 当前/data/gyx/doc_eeg_analysis/runs/evobrain_original_windows74_20261011_223007，PID363688，计划15任务；4500原窗精确对应旧4980窗缓存，只读索引，74人划分/参数/初始化/抽样指纹保持参照一致。
- 旧种子2026/2027/2028，batch16/lr1e-4/100轮/patience12，GPU1启动前绑定。


## 最新窗口及当前74人任务
- 用户确认直接替换新预处理窗口：共同74人75记录，旧原窗口位置+新BAD剔除，4108窗，每份33–60；75 Epochs及6索引已替换、备份和独立核验，连续FIF/旧项目/原数据/模型结果未改。
- 当前模型入组按用户确认共同74人UWS/MCS37/37：/data/gyx/doc_eeg_analysis/splits/mcs_vs_uws/18_共同74人任务清单.csv、/data/gyx/doc_eeg_analysis/splits/mcs_vs_uws/18_共同74人固定划分.csv，固定旧15患者归属；不要默认使用原14的87人清单。原87人登记表留存（4835窗），不等同当前入组。
- 历史输入缓存/特征表保持旧版本，不得静默用于新窗口实验；新实验重建缓存/特征。备份preprocessing/logs/18_窗口替换_20261011_232809/backup，全库117记录6575窗。


## 新窗口单种子检测（编号19）
- 用户明确授权：当前共同74人（UWS/MCS37/37）、75记录、4108个替换后的10秒窗口，单种子2026×旧固定五折；旧最优Dropout协议、batch16/lr1e-4/100轮上限/早停12保持不变。
- 新增独立19入口/config，直接读取新Epochs并重建输入缓存，旧项目及实验只读；GPU1提前绑定，初始权重对照16核验。
- 本次运行/data/gyx/doc_eeg_analysis/runs/evobrain_replaced_windows74_seed2026_20261012_094945，PID736233；只记录已启动，不预先宣称完成。


## 旧预处理相同4108窗对照（编号20）
- 用户明确授权使用旧预处理波形、与19完全相同4108原始时间窗口及順序、74人固定五折、旧最优模型协议、单种子2026；不重选窗口。
- 新增20入口/config；只读旧4980窗缓存并追溯到16原4500窗再索引4108窗，核验与19初始化/首轮抽样指纹一致；不修改19、旧项目或已有结果。
- GPU1提前绑定，独立运行目录/data/gyx/doc_eeg_analysis/runs/evobrain_old_matched4108_seed2026_20261012_101045，PID746743；记录已启动，尚未完成。完成后单份Markdown比较旧4500/旧4108/新4108。


## 最终窗口质量审计（编号21）
- 用户明确同意参考旧05做只读质控；当前范围74人75记录，旧/新相同4108窗，直接读取未裁剪物理电压、复用旧绝对幅值/平直/持续RMS/工频规则；不要求60窗、不修改波形或窗口、不自动排除。
- 新21独立入口，表格4份、Markdown单份、来源与参数在日志区；连续FIF检查文件头及选中区间，不宣称全记录扫描；当前无ICA，ICA检查不适用，旧before/afterPSD不单独归因ICA。
- 已在服务器合成信号验证平直/超幅/非有限值判据；运行tag 20261012_103620，PID764624，日志/data/gyx/doc_eeg_analysis/preprocessing/logs/21_最终窗口质控运行_20261012_103620.log；目前只启动。

- 21已完成：每组4108窗，旧75份通过；新68通过/7幅值警告（13窗），两组均无平直、非有限、≥500µV、持续RMS、工频阈值警告。旧323处BAD_QC_GAP均位于窗口起点，没有内部跨界；初版边界误判已修订，初版代码/汇总/报告存日志区boundary_review_backup。新Epochs与连续FIF逐窗核对一致，产物位于preprocessing/tables/21_*_20261012_103620.csv和reports/21_最终窗口质量审计报告_20261012_103620.md；没有自动剔除或改数据。


## 全库窗口统一（编号22/23）
- 用户明确授权继续替换全部新预处理文件并完成全库质量检查；共同75记录不改，其余42：12按同GUID旧60窗位置去新BAD不补齐，30在新BAD-free候选池按旧linspace(dtype=int)全时程均匀取最多60。没有旧对应者不声称恢复旧ICA/QC候选池；300µV警告不自动替换。
- 预检通过：41份Epochs实际改变，303-MWS7窗不改；全库6575→6509窗。22备份、暂存回读、事务回滚，同步07/08/10/14当前索引；18共同74人任务表与历史结果不改。
- 22后台PID797238，日志/data/gyx/doc_eeg_analysis/preprocessing/logs/22_全库窗口替换运行_20261012_111018.log；先替换核验，再全库Epochs只读质控。未宣称完成。

- 22/23已完成（2026-10-12北京时间）：全库117记录/116受试者（患者103记录102人+健康14记录14人），6509窗（患者5669/健康840）。41个Epochs实际替换，原共同75记录摘要及18共同74人两份任务表摘要未改；07/08/10/14数量逐行核验一致，平衡任务1630窗、原87人MCS任务4835窗。
- 全库23质量：81记录通过、36幅值警告（患者23/健康13）；221窗≥300µV且无≥500µV，未检出平直、非有限值、持续RMS异常、工频/高频规则警告、参考错误或BAD重叠；386-YJI60窗均幅值警告，仅记录不排除。
- 备份preprocessing/logs/22_全库窗口替换_20261012_111019/backup；正式报告reports/22_全库窗口替换报告_20261012_111019.md和reports/23_全库窗口质量报告_20261012_111509.md；23窗口/通道/记录明细在tables。旧特征/缓存不代表新窗口，后续新实验重建或核对指纹；本次未训练/推Git。


## 当前87人EvoBrain检测（编号24）
- 用户明确要求使用当前80+DoC做UWS/MCS二分类，并确认仅种子2026；本次使用14全87人固定五折（UWS42/MCS45，88记录4835窗），不是共同74人限制旧归属；303-MWS7窗及幅值警告按当前规则保留。
- 新24入口/config，直接读取当前新Epochs重建输入；沿用旧最优EvoBrain184015参数、Dropout各折0/0.2/0.1/0/0.2、batch16/lr1e-4/100轮上限/早停12、验证患者交叉熵选模及旧窗口平均汇聚；不改公共训练器/74人结果。
- GPU1被占用，使用空闲GPU0，在导入前绑定并核对实际UUID；后台PID809895，运行/data/gyx/doc_eeg_analysis/runs/evobrain_current87_seed2026_20261012_112317；目前只启动，不能宣称完成。


## 当前87人qEEG / RF / SVM（编号25/26/27）
- 用户明确补充RF/SVM，并确认种子2026；同24的87人（UWS42/MCS45）、88记录4835新窗和14原五折。25提取全部窗口120项、同患者全部记录窗口汇总median/IQR为240项；不选单次记录、不默认逐窗归一化/裁剪。
- 25已完成特征及回读，输出/data/gyx/doc_eeg_analysis/features/mcs_vs_uws/current87_10s_20261012_113029；无NaN/Inf，固定20指标×6脑区，沿用10纯计算函数，来源FIF/清单摘要核验。旧14+14特征保留。
- 新26/27相互独立，仅共用通用qeeg_baseline.py；复用RF500树/min_leaf2/max_featuressqrt、不标准化，SVM训练折StandardScaler+RBF(C1,gammascale,probabilityFalse)；不筛特征/插补/调参、不合并验证集，class_weightNone保持旧参数；SVM决策分数不宣称概率。
- 两者CPU训练，单种子五折，AUROC五折平均及折外汇总分别保留；模型回读验证。当前刚启动[{"model": "random_forest", "pid": 819392, "run_dir": "/data/gyx/doc_eeg_analysis/runs/random_forest_current87_seed2026_20261012_113424"}, {"model": "svm", "pid": 819393, "run_dir": "/data/gyx/doc_eeg_analysis/runs/svm_current87_seed2026_20261012_113424"}]；未宣称完成。

- 25/26/27已完成：特征88记录4835窗→87患者×240项；RF/SVM各5折、模型保存回读预测一致、87人折外预测完整，与24输入清单和划分摘要一致。RF BA0.679365/AUROC五折平均0.695679/MacroF1 0.678118；SVM BA0.655556/AUC0.725000/MacroF1 0.655127；仅种子2026无种子SD。运行分别runs/random_forest_current87_seed2026_20261012_113424和runs/svm_current87_seed2026_20261012_113424。
- 24 EvoBrain同87人已5折完成：BA0.606349/AUROC五折平均0.615123/MacroF1 0.604968，折外AUC0.623280。RF/SVM直接患者汇总特征，Evo窗口概率汇总，比较不单独代表网络架构；不按测试分数调参或更改窗口。


## 同门noica预处理对照（编号28）
- 用户提供/home/lukaige/eeg_project/DoC_EEG_step_by_step/data/processed/eeg/03_epochs/noica及data/metadata/02_patient_master.csv，明确要求EvoBrain单种子；两者现可读。借助a1_records.json的EDF GUID逐一对应同24的87人/88记录，标签一致，306/447同患者；不扩大到同门其他患者或其他原始记录。
- 同门5229窗（303-MWS9窗、其余87记录每份60），19导/250Hz/10秒/平均参考；通道名称集合相同、顺序不同，内存重排为当前模型顺序，不写源文件、不重滤波/重参考。
- 种子2026，完全复用24患者角色与旧最优EvoBrain协议（batch16/lr1e-4/100轮上限/早停12，折Dropout0/0.2/0.1/0/0.2）；新增28入口/config及独立缓存，保持源数据与旧结果只读。窗口时间和数量与本项目4835窗不同，比较是预处理与选窗联合差异，不能单独归因。
- GPU1导入前绑定、空闲显存门槛12GB，不停止其他任务；后台PID952071，运行/data/gyx/doc_eeg_analysis/runs/evobrain_external_noica87_seed2026_20261012_124453；已启动，未宣称完成。


## 当前任务重新均匀选满60窗（编号29）
- 用户明确要求87人任务重新平均/均匀选窗，每EEG恰好60窗，少于60暂不纳入。预检只有303-MWS7窗不足；最终86患者（UWS41/MCS45）/87记录/5220窗，306/447同患者两记录保留。
- 新29入口，全新BAD-free候选池均匀整数linspace选60，保留剩余患者原seed42五折归属；独立Epochs版本，不改旧4835窗/74人旧窗口/全库07。更新当前14任务清单及14患者划分数量，原任务表完整备份。
- 直接源波形、事件/头信息/float32逐样本回读、质量与最终摘要核验；幅值警告不自动额外剔除；旧模型/手工特征缓存代表旧窗口，不可用于新实验。历史24/25硬编码87，后续须适配新86人入口，不默认为87或74。
- 后台PID966551，日志/data/gyx/doc_eeg_analysis/preprocessing/logs/29_均匀重选运行_20261012_132022.log；当前仅启动，未宣称完成。

- 29已完成（2026-10-12 13:29北京时间）：当前任务86患者UWS41/MCS45、87EEG×60=5220窗；303-MWS不足60暂不纳入，306/447同人共120窗；当前14清单/划分指向独立preprocessing/epochs/10s_60win_uniform_complete_20261012_132022。数量与原患者折号独立复核通过。
- 原两张14任务表在preprocessing/logs/29_均匀满60窗_20261012_132022/backup；报告reports/29_均匀满60窗重选报告_20261012_132022.md。旧87人/74人Epochs摘要均逐一核验未改。
- 新窗口质控：11记录通过/76幅值警告，372窗≥300µV、0≥500µV，平直/非有限/BAD交叠/持续RMS等严重失败0；仅标记警告，不自动修改。下一次训练/特征提取应使用当前86人5220新窗，不沿用旧4835窗缓存，原87人硬编码实验入口需要适配。当前未训练或推Git。


## 当前重复嵌套交叉验证（编号30）
- 用户提供截图并明确要求按图划分：外层Stratified Group5-fold重复10次，内层Group4-fold，分组键Subject_ID；患者级bootstrap1000–5000次算95%CI。已生成独立方案，旧14单次五折表不覆盖。
- 当前86患者（UWS41/MCS45）、87EEG、5220均匀60窗，303不足不纳入，306/447同患者；基于唯一患者表分层再映射全部记录/窗口，避免窗口数重复计数患者。
- 新src/datasets/30_make_nested_cv_splits.py及configs/mcs_uws_nested_cv.yaml；数据/splits/mcs_vs_uws/nested_cv_86_uniform60（完整路径/data/gyx/doc_eeg_analysis/splits/mcs_vs_uws/nested_cv_86_uniform60）。外层seed42–51，内层GroupKFold(shuffle=True) seed2026+(repeat-1)*5+outer_fold；严格Group4，不偷偷改内层分层。
- 50外层、200内层均已通过无患者交叠/外层测试不进入内层、每患者每重复测试一次、每外层训练患者内层验证一次、两类齐全、重复记录同组、10不同划分、逆序重现及CSV回读核验。
- 2000次患者块bootstrap(seed2026)及95%百分位CI仅为预设，当前无新外层预测，尚未执行；每患者全部重复OOF预测一块，所有模型共用患者抽样，不能把860条重复预测/窗口当独立患者；区间不包含全部重训不确定性。
- 后续模型应共用30冻结外/内层表；标准化/插补/特征选择/调参/阈值/早停只在内层，最终冻结参数在全部外层训练患者重训后测试一次；训练器需适配，旧单验证入口不代表已嵌套训练。旧每折Dropout不能当作本方案已内层调优；具体候选参数、最终重训轮数规则在训练前确定。仅划分完成，未训练/算CI/推Git。


## 重复嵌套RF/SVM训练（编号31/32/33）
- 用户明确要求先跑RF/SVM，确认小范围内层搜索、训练seed2026。31基于当前86人87记录5220均匀新窗重提特征完成，路径features/mcs_vs_uws/nested86_uniform60_20261012_134822（固定每窗120项、患者全部记录median/IQR240项）；未复用旧4835窗特征。
- 新32 RF、33 SVM独立入口，公共nested_traditional.py，configs/traditional_nested86.yaml，完全共用30冻结外层5×10/内层Group4。RF固定500树/sqrt，候选leaf1/2/4；SVM候选C0.1/1/10×gammascale/0.01/0.1，StandardScaler每内层训练/最终外层训练拟合。没有筛特征/插补或额外重采样。
- 内层合并患者OOF，Macro-F1联合选择候选与阈值；并列优先BA/最接近原默认阈值/候选声明顺序。阈值网格RF0.3–0.7步0.05，SVM原decision−1–1步0.25；不称SVM分数为校准概率。冻结选择后全部外层训练患者重训，测试一次。RF650/SVM1850次拟合。
- 患者级2000次块bootstrap(seed2026)：同患者10次OOF作为一块保留，先每重复算指标再平均，95%百分位CI条件于固定已训练OOF，不包含全套重训不确定性；同ID/seed抽样RF/SVM一致。已验证计数加权指标与显式抽样/sklearn完全一致，并验证完美预测边界；预检所有集合无交叠。
- CPU后台已启动[{"model": "random_forest", "pid": 1005311, "run_dir": "/data/gyx/doc_eeg_analysis/runs/random_forest_nested86_seed2026_20261012_135616"}, {"model": "svm", "pid": 1005312, "run_dir": "/data/gyx/doc_eeg_analysis/runs/svm_nested86_seed2026_20261012_135616"}]。每外层保存一个最终模型及搜索/OOF/患者角色追溯，progress.csv记录可核查进度，旧数据/分折/结果不改。本次刚启动，未宣称完整训练或CI已结束。

- 31/32/33已全部完成：RF650次拟合/SVM1850次拟合，各50最终外层模型回读通过；每模型860条重复患者OOF（每次86人）完整，各折内层OOF仅含外层训练患者；2000次患者块bootstrap均有效，两模型患者ID顺序及抽样索引SHA一致。
- RF重复嵌套结果（10次OOF均值±重复SD）：BA0.700759±0.029889，AUROC0.722900±0.014761，MacroF1 0.692687±0.029473；BA95%患者bootstrapCI[0.617138,0.783107]。
- SVM结果：BA0.703496±0.031408，AUROC0.777019±0.027548，MacroF1 0.700120±0.031392；BA95%CI[0.624276,0.776290]。平均混淆矩阵RF[[33.5,7.5],[18.7,26.3]]、SVM[[30.9,10.1],[15.6,29.4]]，行真实UWS/MCS，平均计数合计86，不是860独立患者。
- 结果路径runs/random_forest_nested86_seed2026_20261012_135616与runs/svm_nested86_seed2026_20261012_135616，各自单份Markdown报告、summary.json、参数来源、进度与内外层预测/搜索表。AUROC现为每重复合并OOF计算再平均，区别于旧五折直接AUC平均；SD为分折重复，不是3种子SD；CI条件于已训练OOF，不含全套重训不确定性。新窗口/队列与嵌套搜索协议一起变化，不能把与旧分数差异仅归因选窗。旧数据/划分/结果未改，未推Git。


## 文件变更说明与runs编号约定
- 用户要求每轮说明新增/修改文件及数据产物影响；只读/讨论须注明未修改文件。
- 用户明确选择仅本次及以后runs目录编号，旧目录原名保留；所有新运行目录用对应入口两位编号_模型/任务_参数/时间，例如34_evobrain_nested86_nodrop_seed2026_*，不静默重命名旧目录或旧路径。

## 无Dropout EvoBrain重复嵌套（编号34）
- 用户明确要求接着跑EvoBrain，确认先不用Dropout；固定Dropout=0，无Dropout搜索。种子2026、当前86人5220均匀新窗、完全复用30外5×10/内Group4冻结患者划分；200内层+50最终重训共250次训练。
- 新src/training/34_run_evobrain_nested.py、configs/evobrain_nested86.yaml、src/evaluation/repeated_patient_summary.py；旧模型/旧训练入口/旧runs不修改。汇总模块与既有SVM均值/CI/抽样索引已逐项重现验证。
- 旧官方适配器184015参数，检查所有nn.Dropout模块p=0；batch16/lr1e-4/Adam/weight_decay5e-4/均衡16窗每患者每轮/clip5/cosineTmax100。内层最多100轮/早停12，以验证患者损失选最佳权重，只构造内层验证预测，不读外层测试预测。
- 内层四折患者OOF选择概率阈值0.3–0.7步0.05（MacroF1、BA、离0.5最近）；最终重训epochs=ceil(median(4个内层best_epoch))，不再早停、不按外层测试选轮数，schedulerTmax仍100；全部外层训练患者重训后测试一次。
- GPU1显存不足，GPU0有空闲，导入前绑定GPU0并核对UUID、12GB门槛，不停止其他任务。新输入缓存不复用旧4835窗或qEEG特征；仅保留50最终权重、200内层结果，不保存大量内层临时权重；可核查进度/已完成内层复用。
- 后台PID1034180，结果/data/gyx/doc_eeg_analysis/runs/34_evobrain_nested86_nodrop_seed2026_20261012_141647；当前仅启动，未宣称训练完成或新CI已计算。

- 用户明确要求暂停当前34 EvoBrain任务；已核对PID及完整命令后发送SIGSTOP，进程状态T(stopped)，内存中当前epoch/模型及已完成磁盘结果保留，未改重复数或训练参数。运行目录新增pause_status.json记录暂停方式；恢复需用户明确授权SIGCONT。该暂停方式仍占用已分配显存，不宣称释放GPU。


## EvoBrain只保留一次重复（编号35汇总）
- 用户明确改为只跑一次；第一次外层5折已经完整完成，无需重训。已核验暂停进程PID1034180身份，SIGTERM+SIGCONT终止后续训练并确认退出，清理该PID运行锁，更新34目录pause_status.json及progress.csv；额外第二次完成结果保留但不纳入当前评价。
- 新src/evaluation/35_summarize_evobrain_once.py直接读取34的repeat01五个最终模型/结果；当前协议仍外层分层Group5折+内层Group4，训练seed2026/Dropout0，20内层+5重训共25次，86患者5220窗；外层分折seed42。旧训练代码/配置/权重/分折不改。
- 单次患者OOF汇总及2000患者bootstrap已完成，结果/data/gyx/doc_eeg_analysis/runs/35_evobrain_nested86_once_seed2026_20261012_152350；无重复SD，AUROC主口径为86人OOF，另存五折平均AUROC，不混用。RF/SVM配对比较要取同repeat1，不用10次平均冒充同方案。


## EEGPT原版单次嵌套（编号36）
- 用户要求跑EEGPT并明确选择旧项目原版及原训练参数；使用旧16全参数微调，不是旧14冻结编码器、不用token适配版。当前86人5220均匀新窗，30第一次外层分层Group5/内Group4，seed2026，20内层+5最终重训，不重复10次。
- 新src/models/eegpt.py只读加载旧EEGPT模型，src/training/36_run_eegpt_nested_once.py独立入口和configs/eegpt_nested86_once.yaml；旧EEGPT源码、预训练权重、旧Evo/RF/SVM脚本及数据不改。新入口生成语法检查问题已修复，未启动错误版本。
- 参数原版batch32/lr1e-4/AdamW/weight_decay0.01/max20/patience4/clip1/均衡16窗每患者每轮/seed_offset500。内层ReduceLROnPlateau按验证损失；原mean分类头Dropout0.3保留，关闭Dropout只适用于Evo实验；编码器全量微调，input_norm none，10秒窗取1–5/5–9秒双片段到256Hz。
- 内层患者OOF选阈值0.3–0.7步0.05；最终epochs=ceil median内层best_epoch，逐epoch学习率取四条内层历史轨迹中位数（epoch1使用初始lr），外层测试不参与轮数/调度。正式输入仍旧100µV缩放及±500µV裁剪，非qEEG特征。
- 已仅用内层训练患者batch32做前后向/优化步检查：权重SHA验证通过，可训练25420674参数、102组编码器梯度有限、峰值3.67GiB。GPU0导入前绑定，16GB门槛，不停止其他任务。
- 后台PID1103341，编号运行/data/gyx/doc_eeg_analysis/runs/36_eegpt_full_nested86_once_seed2026_20261012_153805；目前只启动，未宣称25次训练/新CI完成。


## EEGPT最多50轮/验证患者BA早停（编号37）
- 用户提出50轮和ACC早停，经确认选择验证患者级Balanced Accuracy(BA)，不是普通ACC或窗口/训练ACC。新独立实验，旧36已完成保留（BA0.638211、OOF AUROC0.762602、MacroF1 0.638312）。
- 新src/training/eegpt_ba_trainer.py、src/training/37_run_eegpt_ba50_nested_once.py、configs/eegpt_nested86_ba50.yaml；旧训练器/旧36入口/模型源码/数据与分折不改。新控制器独立导入缺失pandas问题已在预检修复，未启动错误版本。
- 上限50，patience4，BA最大化，min_delta0.001，持平不算改善，保留最佳BA权重；BA由验证患者窗口概率平均后默认0.5分类计算。ReduceLROnPlateau mode=max也使用验证BA，日志val_patient_loss仍真实患者损失，不用负BA伪装损失。
- 已合成验证BA第二轮最佳后持平4轮第6轮停止，即使验证loss继续下降也不覆盖BA最佳；新入口数据/权重/分折预检通过。其他参数同36，mean头Dropout0.3、batch32/lr1e-4/AdamW/wd0.01/clip1；当前86人5220窗，seed2026，1次外5/内Group4共25训练。最终重训轮数及逐轮lr由内层历史确定，外层测试不参与选择。
- GPU0提前绑定，编号运行/data/gyx/doc_eeg_analysis/runs/37_eegpt_full_ba50_nested86_once_seed2026_20261012_155437，PID1115561；仅启动，未宣称完成。


## BIOT验证患者loss早停（编号38）
- 用户表示仍按loss早停并要求BIOT，确认最多50轮（不是旧20上限）。默认后续早停用验证患者loss，除非另行明确更改；旧EEGPT BA实验和旧训练代码/结果不重跑或修改。
- 新src/models/biot.py只读加载旧BIOT/PREST16适配器；src/training/38_run_biot_loss50_nested_once.py及configs/biot_nested86_loss50.yaml；GPU1，当前86人5220均匀新窗，30第一次外Group5/内Group4，seed2026，共20内层+5重训。
- 参数batch8/lr1e-4/AdamW/wd0.01/gradclip1/max50/patience4/min_delta0.001；验证患者loss最低保存权重，Plateau也按loss min；内层OOF定阈值，最终轮数/逐epoch lr由内层确定，外层测试不参与选择。19导在模型内转16条PREST双极导联，250→200Hz、整10秒、µV单位；原STFT矩形窗和编码器Dropout设置保留，不改FIF。
- 权重摘要b58921441964b0e791a4f916d72ee09411ec18067af4cc466cc49c6dda20a16b通过；作者index是固定整型通道编号，无梯度是原设计，检查仅要求所有浮点权重可学习。真实训练批次8前后向通过，55组编码器梯度有限，3186690可训练参数，峰值0.22GiB。
- 编号运行/data/gyx/doc_eeg_analysis/runs/38_biot_prest16_loss50_nested86_once_seed2026_20261012_161334，PID1130779；目前已启动，不宣称25次训练/CI已完成。


## GRU-GCN单次嵌套loss早停（编号39）
- 用户要求GRU-GCN，并确认最多50/早停4，使用验证患者loss。当前86人5220均匀新窗，30第一次外Group5/内Group4，seed2026，20内层+5重训。
- 新src/models/gru_gcn_original.py只读加载旧双logits GRU-GCN及第三方源码，src/training/39_run_gru_gcn_loss50_nested_once.py和configs/gru_gcn_nested86_loss50.yaml；现有src/models/gru_gcn.py单logit实现、旧GRU及其他模型入口/权重/数据/划分不改，不调用EvoBrain/Mamba模型。
- 旧节点/边GRU、两层GCN/19导频谱动态图，BN仅训练更新；随机初始化不使用预训练。batch32/lr1e-4/Adam/wd5e-4/clip5/均衡16窗每患者每轮，cosineTmax50，loss下降>0.001保存权重、连续4轮未改善停止。内层OOF定阈值，最终轮数ceil中位best_epoch，重训同余弦Tmax50，无测试调度。
- 仅训练患者真实batch32前后向检查通过：114959可训练参数、核心16组梯度有限、GPU峰值1.21GiB。GPU1导入前绑定，实际UUID核验，当前空闲显存约3.5GiB，门槛2.5GiB；不满足等待，不停止其他进程。
- 编号运行/data/gyx/doc_eeg_analysis/runs/39_gru_gcn_loss50_nested86_once_seed2026_20261012_163334，PID1147899；已启动，尚未宣称完成。


## 旧流程DoC/HC补充（步骤40）
- 用户决定回到旧项目完整预处理，包括ICA；当前只授权补HC主表，转换/QC/ICA/切窗尚未启动。
- /home/guoyanxin/project/doc_eeg/pipeline/scripts/40_build_doc_hc_master.py生成/home/guoyanxin/project/doc_eeg/data/metadata/40_DOC_HC主表.csv；保留旧v3_2 analysis_master的129行及全部原字段，补入17个HC，沿用既有hc_001_姓名缩写编号登记。HC无CRS-R评分，留空；主表登记不代表质控后入组。
- DoC原表canonical_raw_path包含历史本地路径，新增server_raw_path保存本项目已核对服务器路径；后续服务器处理使用该列。未核对到的路径留空，不猜测。
- /data/doc_pre/doc当前98个文件均为*_clean_raw.fif；仅按文件名匹配已有连续FIF，未确认切窗产物或波形头信息，不将其当Epochs。已有文件不移动、不覆盖。
- 新HC转换FIF放/data/doc_pre/raw_fif，ICA后连续FIF放/data/doc_pre/processed/hc，未来切窗结果放/data/doc_pre/hc；修复EDF只用临时副本，转换后删除，不长期保留。
- 新代码要求精简规范、职责明确；中文注释解释必要规则，不写冗余模板、重复封装或大段流水说明。每轮列出实际新增/修改文件。

- 用户明确要求本次旧流程补HC脚本放在旧项目/home/guoyanxin/project/doc_eeg/pipeline/scripts；步骤40已移到该目录，原新项目脚本位置不保留副本。后续复用旧入口，路径适配及实际处理需在授权范围内说明后执行。

- 用户要求本次补HC主表等轻量元数据归旧项目；40_DOC_HC主表.csv已移到旧项目data/metadata，步骤40输出路径已同步。旧项目原v3_2主表不覆盖。波形仍按用户指定放/data/doc_pre。

- 用户授权17个HC重新修复EDF转FIF。旧pipeline/scripts/02_convert_edf_to_fif.py新增--group hc，默认DoC入口保留；HC读取旧项目data/metadata/40_DOC_HC主表.csv，原始只读、临时修复后删除。FIF放/data/doc_pre/raw_fif；检查/转换清单放旧项目data/metadata/02_HC_*，报告和日志放旧项目outputs/hc。没有启动QC/ICA。后台PID1201528。

- 17个HC的02转换全部完成（19导250Hz，17个缺80字节临时修复，约10.98GiB，临时EDF清理），用户同意继续原始信号QC。旧03_signal_qc.py新增--group hc，检测算法/旧配置阈值保持；HC清单放旧项目data/metadata/hc，单份带时间QC报告及日志放outputs/hc，不额外复制统计表。后台PID1203794。FIF只读，ICA/预处理未启动。

- 用户授权安装python-picard；evobrain_mamba已安装0.8.2，原numpy/scipy/sklearn未升级，MNE Picard拟合调用验收通过。继续11份HC旧04 ICA预处理；旧04新增--group hc，旧core仅output_paths增加HC存储支持（AST验证其余函数不变）。连续FIF和ICA模型放/data/doc_pre/processed/hc，临时矩阵在同目录.runtime；清单旧项目data/metadata/hc，报告/日志outputs/hc。原ICA和10秒残余QC/均匀最多60窗选择完整保留，未导出Epochs。后台PID1207657。

- HC最终QC及切窗完成：旧05新增--group hc，HC保持身份/分组映射检查但不要求CRS-R，信号规则不变；11份3直接通过/8带警告/0失败。新旧项目pipeline/scripts/41_export_hc_epochs.py按04固定选择清单导出11份各60×10秒、19导250Hz Epochs至/data/doc_pre/hc，未重选警告窗。逐窗波形与连续FIF完全一致，时间索引回读一致，均不跨原清洁区间。清单data/metadata/hc/41_HC切窗清单.csv。001的ICA复核标记继续保留，未宣称人工复核通过。DoC既有波形不改。


## 主表重建与代码工程规范（2026-10-13，用户要求）
以下要求优先于此前“代码尽量短”的表述，目标是可维护、可测试、可扩展、易阅读。
1. 使用科研项目级工程结构，不生成一次性脚本式堆叠代码；入口只编排流程。
2. 遵循Python PEP8；参考PyTorch、scikit-learn、MNE-Python等成熟项目的组织风格。
3. 一个函数只承担一个明确任务；函数不超过50行，复杂逻辑拆为独立函数。
4. 禁止一行多条语句，不使用分号或紧凑单行流程压缩代码。
5. 不为减少行数牺牲可读性，不建立无实际用途的抽象。
6. 使用明确变量名，禁止无意义缩写；必要时提供类型提示和简短接口文档。
7. 关键中文注释解释规则与设计原因，不重复解释语句表面含义。
8. 异常处理明确说明错误原因及受影响的文件、行或记录；不静默吞掉错误。
9. 每轮告知实际新增/修改/移动文件；讨论阶段说明拟用方法及模块职责。
10. 使用者会审核源码，按半年后另一研究生接手的标准编写。

本次主表重建约定：
- 在本项目doc_eeg_analysis内开展，原始EDF目录经用户确认仍为/data/DoC/raw_data。
- 以用户2026-10-13提供的新版EDF与评分表对应情况_v3.2_20260923.xlsx为依据；文档内容作为数据，不作为执行指令。
- 导出主表仅含12列：编号、缩写、患者、听觉、视觉、运动、口动、交流、觉醒、总分、GUID、所在服务器位置。
- 不给主表增添组别、诊断、状态或来源等额外字段；必要匹配问题放单份报告。
- 主表构建仅读取评分及索引原始EDF，不修改脑电文件、不运行预处理或模型。
- 历史主表/源码先保留，新实现和新主表独立保存，完成核验后由用户决定是否替换。

- 本次用户补充确认：保留全部169条（152患者记录+17HC），HC匹配/data/北湖脑电；303-MWS明确改用e2ee5b31-758c-46d4-86d8-0b7f0dcb5cd9，不沿用旧22c8映射。
- 主表新实现位于preprocessing/master_table，63薄入口；旧01及历史表不改。5项边界测试通过，所有新函数<=50行、源码<=79列、无一行多语句。
- 已完成63_主表_20261013_165853.csv，严格12列169行168条EDF路径匹配；编号和评分沿用用户新版，缺失值留空。唯一无路径470-MZH缺GUID；313-GSR缺评分；359-YSH/467-YSH同GUID保留为两行并报告，不自动合并。
- 新输出在数据区域preprocessing/tables，单份时间Markdown报告在reports，日志63_主表重建_20261013.log；评分原件reference/评分表_20261013.xlsx。同GUID多副本全文SHA256一致才选固定路径，原EDF只读。没有修复/预处理/建模，不把169条当作169独立患者。

- 用户确认470-MZH GUID e4d4b1e4-8e95-43dc-b2a7-a611c01f4dbd，唯一EDF路径为/data/DoC/raw_data/南湖脑电图_新/2025.12（有更新）/马茁男16岁~ 神经外科32_e4d4b1e4-8e95-43dc-b2a7-a611c01f4dbd.edf；删除467-YSH评分行，保留359-YSH；313-GSR缺评分继续留空。当前63主表原位修订为168行（151患者记录+17HC），168条路径全匹配，原169行表/报告备份在logs。63入口默认记录303/470的人工GUID和467排除，pipeline增加可选排除编号，报告同步。用户此前只要求讨论代码合并，本轮未覆盖旧01或合并模块，等待进一步明确执行。

- 用户明确授权合并主表入口：已覆盖preprocessing/01_build_patient_master.py，将类型/读取/匹配/校验/导出函数集中于单文件，不再拆master_table模块；保持每函数<=50行、79列和无一行多语句。新增tests/test_patient_master.py，原5边界测试及CLI人工规则/12列集成测试共6项通过。移除63入口及本次master_table目录，旧01和合并前模块在日志目录备份。更新preprocessing/README。当前168行主表SHA合并前后不变，不重新生成，未来输出使用01编号。

- 用户授权当前168记录重新EDF转FIF，含313缺评分记录，不转换主表外数据。03已单文件重写适配12列CSV，函数<=50行、79列，原03在logs备份。原始EDF只读；167份缺80模式/1标准，现场头结构预检均可识别；临时修复补recording80字节及已知F4/C3，原数据区全SHA一致。保留19导/原采样率/负增益/standard_1020/采集时间，源数字标定与FIF首中末样本、事件起止及extras回读核验；间断压缩为BAD/EDGE并保留原间断秒数，未滤波/参考/ICA。临时EDF及临时FIF在记录结束清理；不改旧repaired目录。
- 新tests/test_edf_conversion.py三项合成测试覆盖标准/缺80、负增益+间断事件、无效文件及清理，全部通过。真实301/304/HC_001代表验收3份成功，无临时EDF残留。全表已后台启动PID1454619，复用这3份，清单tables/03_FIF转换清单_20261013_190410.csv，单份报告reports/03_EDF转FIF_20261013_190410.md持续更新；FIF位置/data/gyx/doc_eeg_analysis/preprocessing/raw_fif。当前未宣称168全部完成。

- 2026-10-13用户更正焉石：删除359-YSH，保留467-YSH；听觉3、视觉2、运动3、口动3、交流1、觉醒3，总分15，诊断MCS+（主表不增添诊断列），GUID为7e0cdb97-bf04-4e9b-98d5-1b2180a7758f。此规则覆盖此前删除467的约定。当前主表仍168行，01默认排除359。进行中的03已读取旧359编号，待其结束后同步FIF名称及转换清单，波形不重新转换。

- 最新用户更正：删除462-MWS（马文帅）和308-WFL（王凤玲）。463-WFL评分0/0/2/2/0/0，总分4，UWS，GUID cfd46c86-009a-4b85-903a-334ed69bc0ef；464-WFL评分0/0/2/0/0/0，总分2，UWS，GUID 22a33540-f0d9-4a2c-8f88-ee36eb24a0c7。主表166条，149患者记录+17HC，源码默认GUID及排除同步。转换已缓存旧对应，待转换及焉石同步结束后，复用原308的FIF作为464、原464作为463，原463及462移入日志备份，转换清单同步为166条；不删除原EDF。

- 用户明确授权入口编号合并：删除preprocessing/02_inspect_edf.py，原03改名为preprocessing/02_repair_edf_to_fif.py；转换内部执行本次必需的格式检查，不再依赖独立检查产物。新批次清单/报告/日志使用02编号，续接已有03清单仍保留原03报告路径，旧数据/报告/清单不改名。测试及README入口引用同步；04及以后暂保持原编号。本次仅源码编号调整，不重跑转换。旧源码和修改前文档在数据区logs备份。

- 2026-10-13T19:49:26.604137+08:00用户确认313-GSR缺评分不再使用：当前主表及转换清单移除313，01默认排除313，FIF归档至/data/gyx/doc_eeg_analysis/preprocessing/logs/313_GSR停用备份_20261013_194926。当前165条（148条患者记录+17HC），不纳入后续信号预处理、切窗和建模；本条覆盖此前313评分留空但继续处理的约定。报告及README统计同步，原EDF只读。

- 2026-10-13用户授权模块合并及连续编号：config.py集中原检测/滤波参数，03_check_signal_quality.py含初检及共用检测函数，04_preprocess_eeg.py合并滤波、参考和原06最终BAD补标，05_make_windows.py切窗。旧04/05/06/07入口及quality_control.py、signal_processing.py删除，备份在logs/03_结构整理备份_20261013_201734；辅助窗口脚本引用同步。04/05必须指定本次清单，已有波形拒绝覆盖；精简主表没有患者ID，切窗不猜测分组。原阈值沿用，初检通道统计明确避开BAD/间断窗口；参考后异常在04保存前补标。本次只运行合成测试和165条输入计划核对，没有启动真实初检、预处理、切窗或模型训练。此前旧04–07编号仅指历史操作。

- 2026-10-14用户授权清理旧表、旧报告、旧日志：191份历史元数据（tables30、reports20、logs141）已归档至/data/gyx/doc_eeg_analysis/archive/preprocessing_history_20261014_134738.zip，逐成员大小/SHA256核验后移除原文件。当前tables保留4份、reports保留3份；当前04明细/日志/锁/04_work临时目录保留。旧波形及含FIF的4个日志备份目录未删除；原始EDF、raw_fif、processed/20261014_v1均保留。历史实验入口若引用已归档表，应从归档恢复或适配本批次，不自动重建旧清单。


## 2026-10-14 预处理review修复
- 用户授权先改review问题，再继续本批次预处理。旧04 PID1550062已停止；47条登记结果保留，未登记的355-MXC输出移至数据区archive/preprocessing_review_20261014_135848/interrupted_output，不删除原始数据。
- 修改04：平均参考后补充全量持续坏导检测，任一坏导整份排除；新增--resume-table，核验参数、主表/初检指纹、GUID、源路径及FIF元信息后复查，不重新滤波已完成部分。复查和原处理源码指纹分开保存，不能把旧波形声明为重新滤波的结果。
- 修改04/05：全量执行时输入清单必须覆盖完整主表，显式--codes允许调试子集。修改05：--processed-dir必填，默认epochs/<预处理批次>/<窗口参数>，支持--output-dir，避免混用旧切窗。
- 03及config.py、01/02没有改动，滤波、平均参考及局部坏段窗口检测函数与备份AST一致。输出仍processed/20261014_v1。患者ID列尚未增加，须等本次处理结束再同步，以免运行中改变主表指纹。
- 修改前源码和中断明细已核验备份至/data/gyx/doc_eeg_analysis/archive/preprocessing_review_20261014_135848/before_review.zip。当前真实处理只续跑04，不自动启动05切窗或模型训练。

- review修复后23项服务器回归测试通过。04续跑已启动PID1557080，日志/data/gyx/doc_eeg_analysis/preprocessing/logs/04_预处理续跑_20261014_140846.log；以47条旧结果核验复查后续处理完整165条清单，尚未宣称完成。

- 2026-10-14T16:59:19.472376+08:00用户授权补跑418-WHB已完成，结果needs_review，坏段比例2.76%。完整165条明细原位更新/data/gyx/doc_eeg_analysis/preprocessing/tables/04_预处理明细_20261014_140846.csv，保留152（通过60、带警告92），坏导排除13，失败0。其余164条未重做。新完整报告/data/gyx/doc_eeg_analysis/preprocessing/reports/04_预处理报告_20261014_165919.md，补跑日志/data/gyx/doc_eeg_analysis/preprocessing/logs/04_418-WHB补跑_20261014_165044.log，元数据归档/data/gyx/doc_eeg_analysis/archive/preprocessing_418_retry_20261014_165919.zip。04当前SHA256为0024f346f3c9ef3516b251c1cc5171ae05c8c698c7dbbe3a8683bb7e55007a42，仅新增流程说明、注释和排版，还原后精确匹配原批次1468b9d9d9561b2997aec02494bbfed30f4601c1e6eb1ec1e815e856f2f3a3e7；保留实际指纹，不改写用户注释。未修改预处理代码或参数，未执行05。


## 2026-10-14 主表增加患者ID
- 用户授权在主表增加身份分组字段，并确认全部11组DoC同名记录是同一人的多次测试。明确王立HC_011_WAN是424-WLI康复后的记录，同一患者。
- 当前tables/63_主表_20261013_165853.csv原位更新为13列：编号、患者ID、缩写、患者、听觉、视觉、运动、口动、交流、觉醒、总分、GUID、所在服务器位置。原165行顺序与原12列所有单元格完全不变。当前152个患者ID，12组重复测试；不合并或删除测试记录。
- 01_build_patient_master.py集成DEFAULT_PATIENT_LINKS、锚点ID生成、旧ID复用、循环及姓名冲突检查。患者ID如doc_306；健康组ID沿其记录编号小写，王立康复后的HC记录ID为doc_424。新增同名或同缩写记录不自动合并，需明确确认。
- 所有窗口与重复记录按患者ID分组，内外层训练/验证/测试均不得跨集合；患者ID不作为特征，也不据其前缀推断任务标签。不同阶段评分和标签各自保留，聚合方式由具体任务另定。
- HC_011_WAN是康复后记录，后续DoC/HC任务不能仅凭文件来源目录自动当作无患病史健康对照；应先确定研究纳排和标签。当前QC清单group字段只保留原数据来源分组，不回写信号处理历史。
- 05已支持读取患者ID并写为subject_id，本次不修改05。03/04和全部FIF没有重跑或改写；历史输入SHA256保留执行时值，原12列主表及源码、报告备份位于/data/gyx/doc_eeg_analysis/archive/patient_identity_before_20261014_170828.zip。
- 新身份报告reports/01_主表更新_20261014_171253.md；原主表报告已归档后移除，正式目录保留最新完整主表报告。29项服务器测试通过，新增函数不超过50行、行宽不超过79列。

- 用户授权10秒、每份60窗，已启动05，PID1595340，日志/data/gyx/doc_eeg_analysis/preprocessing/logs/05_切窗运行_20261014_173249.log。按时间均匀选取、不重叠、不跨BAD；152份保留记录中可用10秒窗最少112个，均足60。输出/data/gyx/doc_eeg_analysis/preprocessing/epochs/20261014_v1/10s_60win_step10s，切窗清单带患者ID。HC_011_WAN康复后记录仅作为来源记录导出，不在本步确定健康对照标签。未修改05或参数代码，未重跑滤波，尚未宣称切窗完成。


## 2026-10-14 主表诊断维护
- 用户授权主表新增诊断列，此条覆盖此前不增加诊断字段的约定。
- 当前63主表165行、14列，诊断位于总分之后；原13列单元格及顺序不变。
- 来源为preprocessing/reference/评分表_20261013.xlsx，按测试编号对应，核对姓名、评分及GUID；不由总分推断诊断。
- 保留MCS+、MCS-、eMCS与边界类别；470-MZH仅清除误粘的科室/GUID，诊断仍为昏迷-UWS边界。
- 后续允许人工修正主表诊断；01重建时同一编号、姓名和GUID优先保留已有诊断（包括主动留空），新记录才取来源标签。
- HC_011_WAN暂照录来源HC，仍是已确认的康复后记录；DoC/HC任务需明确纳排，不自动当作无患病史健康对照。
- 不改FIF、切窗清单或历史输入SHA256，不重跑预处理；未来实验必须固定执行时标签版本。
- 修改前主表、源码、测试、文档和报告归档：/data/gyx/doc_eeg_analysis/archive/master_diagnosis_before_20261014_192744.zip。
- 最新报告：/data/gyx/doc_eeg_analysis/preprocessing/reports/01_主表更新_20261014_192924.md；36项服务器测试通过。


## 2026-10-14 建模代码清理与重建
- 用户明确授权清除本项目旧建模代码，重新设计；本条覆盖此前沿用旧建模模块和入口的要求。
- 已清空src中的旧数据、模型、训练、评价代码，删除configs中的旧建模配置及third_party中的旧模型源码，共64个文件；保留目录和已有.gitkeep。
- 删除前完整源码与旧README、docs/modeling.md、AGENTS.md已归档并回读核验：/data/gyx/doc_eeg_analysis/archive/modeling_code_before_reset_20261014_195232.zip。
- 当前preprocessing源码、三个预处理测试、主表、切窗清单及数据区域的波形、划分、特征、历史实验结果不清理。
- 更新README和docs/modeling.md，明确建模尚未重新实现；尚未创建run.py、模型适配或新配置，未启动训练。
- 拟采用共用入口、任务定义与模型选择分离；官方源码放third_party，模型独立适配。具体任务、划分和训练参数另行讨论，不自动沿用旧结果。
