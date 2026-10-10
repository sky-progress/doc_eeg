"""生成可阅读的中文报告；报告、表格、日志分别保存。"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter
from pathlib import Path


def write_report(directory, stem, title, sections):
    """仅生成一份Markdown，文件名和正文均记录北京时间。"""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    task_stamp=re.search(r'(\d{8}_\d{6})$',stem)
    stem=re.sub(r'\d{8}_\d{6}$',now.strftime('%Y%m%d_%H%M%S'),stem)
    lines=['# '+title,'',f'报告生成时间：{now:%Y-%m-%d %H:%M:%S}（北京时间，Asia/Shanghai）','']
    if task_stamp:
        started=datetime.strptime(task_stamp.group(1),'%Y%m%d_%H%M%S')
        lines += [f'原始任务开始时间：{started:%Y-%m-%d %H:%M:%S}（北京时间）','']
    for heading,paragraphs,headers,rows in sections:
        lines += ['## '+heading,'']
        for paragraph in paragraphs:lines += [paragraph,'']
        if headers:
            lines += ['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']
            for row in rows:
                lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in row)+' |')
            lines.append('')
    path=directory/(stem+'.md')
    with path.open('x',encoding='utf-8') as handle:handle.write('\n'.join(lines))
    return str(path)


def write_master_report(summary,reports,stamp):
    patients=summary.get('patient_records',summary.get('usable_scoring_rows',0));healthy=summary.get('healthy_records',0)
    total=summary.get('total_records',patients)
    sections=[
        ('构建结果',[f'主表共{total}条测试记录，其中患者组{patients}条、健康组{healthy}条。记录数不等于独立受试者人数；306-LCS和447-LCS属于同一患者的两次测试。'],['项目','数量'],[['患者组测试记录',patients],['健康组记录',healthy],['合计',total],['受试者ID',summary.get('subject_ids',summary.get('usable_subject_ids','见主表'))]]),
        ('纳排与编号规则',['330-SLP、444-JHX、446-LSJ无EDF，排除。保留306-LCS与447-LCS两次测试，其余一份评分对应多个不同记录时暂缓；没有评分对应的EDF暂缓。','相同内容副本仅选择一份供后续读取，所有原始文件保持不变。健康组使用hc_三位序号_姓名拼音首字母，并维护编号登记表。'],[],[]),
        ('字段与限制',['患者组评分、诊断和原入组状态保持不变；健康组未提供的评分、诊断与入组状态留空。主表匹配成功不代表EDF已修复或通过信号质量检查。'],[],[]),
        ('文件位置',[str(summary.get('xlsx','')),str(summary.get('csv','')),str(summary.get('healthy_registry',''))],[],[])]
    return write_report(reports,'01_主表构建报告_'+stamp,'受试者主表构建报告',sections)


def write_edf_report(details,summary,reports,stamp):
    n=len(details);aligned=sum(r.get('remainder_bytes')==0 for r in details);overlap=sum(r.get('record_count_overlaps_channel_labels',False) for r in details)
    shifted=sum(r.get('layout_shift')==-80 for r in details)
    channel_counts=Counter(r.get('n_channels') for r in details)
    channel_text='、'.join(f'{channels}通道文件{count}份' for channels,count in sorted(channel_counts.items(),key=lambda x:str(x[0])))
    fixed_rows=[['采集日期',168,88],['采集时间',176,96],['头部长度',184,104],['原记录数字段',236,156],['记录时长',244,164],['通道数量',252,172],['通道标签起点',256,176]]
    sections=[
        ('结论',[f'本次检查{n}份EDF。其中{shifted}份关键头部字段相对标准位置提前80字节；{overlap}份文件的记录数写入标准偏移，覆盖第4、5通道标签。MNE可直接读取{summary.get('mne_readable_count',0)}份原始文件。',f'按前移80字节的布局解析，{aligned}份文件的数据区均可完整划分为记录，未发现尾部不完整记录。该结果支持结构修复，但不能证明信号没有伪迹或数据内容没有其他问题。'],['检查项','结果'],[['患者组',summary.get('group_counts',{}).get('患者组',0)],['健康组',summary.get('group_counts',{}).get('健康组',0)],['原始MNE可读文件',summary.get('mne_readable_count',0)],['数据区完整对齐',aligned],['记录数覆盖标签',overlap],['通道数字字段解析错误',sum(r['channel_parse_errors'] for r in details)]]),
        ('范围与方法',[f'输入主表：{summary.get("master","")}。仅检查当前主表中的文件，不包含暂缓或排除的其他原始EDF。','读取固定头与逐通道字段，比较标准位置及前后80字节候选布局；按每记录样本数核算数据区长度，抽查首末记录长度，并尝试MNE只读打开。未补字节、未写修复EDF、未转换FIF、未加载整段波形。'],[],[]),
        ('证据一：固定头长度不足',['以下偏移均以文件起点为0，单位为字节。通道表与后续数字字段按实际位置能够一致解析，头部声明长度仍采用标准长度。',channel_text+'。不同通道数不能作为损坏依据。'],['字段','标准偏移','实际偏移'],fixed_rows),
        ('证据二：记录数覆盖通道名',['文件偏移236至243的8字节数字，全部与按数据区大小推算的记录数相符。由于标签区实际从176开始，第4通道标签占224至239，第5通道标签占240至255，记录数因此覆盖两者。','这是F4名称带数字、下一通道名为空或异常的直接结构证据。被覆盖的第5通道名称需要通过设备原始记录或导出模板确认，不仅凭相邻电极顺序恢复。'],[],[]),
        ('标定极性与采样率',['本批信号通道存在物理最小值大于物理最大值的标定。这可能表示负增益，EDF规范允许这种情况，不能直接交换上下限或翻转波形。数字范围和非零物理跨度需要单独检查。','不同通道的每记录样本数可能不同，尤其注释通道不应当作同采样率EEG处理。记录数-1表示未知，不单独作为损坏判据。'],[],[]),
        ('修复前需要确认',['确认缺失的80字节对应哪一固定头身份字段；不能伪造患者或采集信息。确认第5通道原始名称和通道顺序。','确定最小结构修复规则后，先对少量文件验证可读性、样本数、通道顺序、标定极性及事件保留，再经用户确认开展批量修复与FIF转换。'],[],[]),
        ('逐文件检查结果',[],['编号','组别','通道数','数据记录数','剩余字节','检查结论'],[[r['code'],r['group'],r['n_channels'],r['records_by_size'],r['remainder_bytes'],r['status']] for r in details]),
        ('依据与追溯',['EDF+规范：https://www.edfplus.info/specs/edfplus.html（固定头结构及第5项负增益说明）。',f'MNE版本：{summary.get("mne_version","")}。检查时间：{summary.get("created_at","")}。逐通道明细位于tables，原始检查日志与配置位于logs。'],[],[])]
    return write_report(reports,'02_EDF格式检查报告_'+stamp,'EDF格式检查报告',sections)
