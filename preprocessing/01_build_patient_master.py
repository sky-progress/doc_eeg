"""把「评分表」和「EDF 脑电文件」按规则对应起来，生成一份可审计的「患者主表」Excel。"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reporting import write_master_report, write_report

GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EXCLUDED = {"330-SLP", "444-JHX", "446-LSJ"}
REPEATED_TESTS = {"306-LCS", "447-LCS"}


def guids(value):
    return set(x.lower() for x in GUID_RE.findall(str(value or "")))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sheet(book, title, headers, rows):
    sheet = book.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "D2" if len(headers) > 3 else "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False
    sheet.row_dimensions[1].height = 30
    for cell in sheet[1]:
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="274060")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=2):
        sheet.row_dimensions[row[0].row].height = 30
        for cell in row:
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="right" if isinstance(cell.value, (int, float)) else "left", vertical="center", wrap_text=True)
            if isinstance(cell.value, str):
                # 源值一律作为文字，避免把备注或路径解释成公式。
                cell.data_type = "s"
    for col, header in enumerate(headers, 1):
        values = [str(sheet.cell(r, col).value or "") for r in range(1, sheet.max_row + 1)]
        width = max(sum(2 if ord(c) > 127 else 1 for c in value) for value in values) + 2
        sheet.column_dimensions[get_column_letter(col)].width = min(max(width, 12), 110)
        if "路径" in str(header):
            sheet.column_dimensions[get_column_letter(col)].width = 95
    # 根据列宽估计行高，让长路径和原始备注完整显示。
    for row in sheet.iter_rows(min_row=2):
        lines = 1
        for cell in row:
            width = sheet.column_dimensions[cell.column_letter].width - 2
            for part in str(cell.value or "").split("\n"):
                units = sum(2 if ord(c) > 127 else 1 for c in part)
                lines = max(lines, math.ceil(units / max(width, 1)))
        sheet.row_dimensions[row[0].row].height = max(30, 16 * lines + 8)
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = "1:1"
    return sheet


# 本批姓名的拼音首字母。使用显式字典，避免新增环境依赖和多音字自动误判。
INITIALS = {"于":"Y","连":"L","忠":"Z","任":"R","秀":"X","红":"H","姜":"J","继":"J","舫":"F","孙":"S","玉":"Y","波":"B","宋":"S","爽":"S","张":"Z","津":"J","铭":"M","曹":"C","桂":"G","香":"X","梁":"L","恩":"E","予":"Y","博":"B","王":"W","巨":"J","松":"S","淑":"S","芹":"Q","立":"L","艾":"A","明":"M","武":"W","藏":"Z","万":"W","兴":"X","袁":"Y","国":"G","梅":"M","费":"F","洪":"H","亮":"L","魏":"W","晓":"X","彤":"T"}


def add_healthy(args):
    """复用已核验患者表，只追加健康组；不重新扫描或改变患者纳排决定。"""
    source = load_workbook(args.patient_master, read_only=True, data_only=True)
    data = {sheet.title: list(sheet.iter_rows(values_only=True)) for sheet in source}
    source.close()
    headers = list(data["患者主表"][0])
    patients = data["患者主表"][1:]
    columns = {name: i for i, name in enumerate(headers)}
    paths = sorted(p for p in args.healthy.glob("*") if p.is_file() and p.suffix.lower() == ".edf")
    assert paths, "健康组没有EDF"
    for row in patients:
        assert Path(row[columns["服务器EDF路径"]]).is_file(), "患者EDF路径不存在"
    # 编号登记表保存到数据区域；后续新增受试者时沿用已有编号，不重新排序。
    registry = []
    if args.healthy_registry:
        with args.healthy_registry.open(encoding="utf-8-sig", newline="") as handle:
            registry = list(csv.DictReader(handle))
    by_guid = {r["记录GUID"]: r for r in registry}
    assert len(by_guid) == len(registry), "健康组登记GUID重复"
    used_numbers = [int(r["编号"].split("_")[1]) for r in registry]
    next_number = max(used_numbers, default=0) + 1
    healthy_rows, healthy_inventory = [], []
    patient_guids = {r[columns["记录GUID"]] for r in patients}
    seen_names, seen_guids = set(), set()
    for path in paths:
        name = re.split(r"[男女~\s]", path.stem)[0]
        ids = guids(path.name)
        assert len(ids) == 1 and name, "健康组姓名或GUID不明确"
        gid = next(iter(ids))
        assert name not in seen_names and gid not in seen_guids and gid not in patient_guids, "健康组存在重复或跨组记录，需人工核对"
        seen_names.add(name); seen_guids.add(gid)
        if gid in by_guid:
            record = by_guid[gid]
            assert record["姓名"] == name, "登记姓名发生变化"
        else:
            assert all(char in INITIALS for char in name), "姓名有未配置拼音首字母：" + name
            abbreviation = "".join(INITIALS[char] for char in name)
            record = {"编号": f"hc_{next_number:03d}_{abbreviation}", "姓名": name, "缩写": abbreviation, "记录GUID": gid, "服务器EDF路径": str(path)}
            registry.append(record); by_guid[gid] = record; next_number += 1
        row = [None] * len(headers)
        values = {"编号": record["编号"], "缩写": record["缩写"], "患者": name, "复核": "待EDF质控", "EDF匹配状态": "服务器文件存在", "EDF信息": path.name, "来源表": str(args.healthy), "患者ID": record["编号"], "测试序次": 1, "记录GUID": gid, "服务器EDF路径": str(path), "同GUID物理文件数": 1, "重复核验状态": "健康组单文件；未核验信号质量", "对应依据": "用户指定健康组目录+文件名", "核对备注": "健康组未提供评分或诊断，留空；入组状态未提供，留空"}
        for key, value in values.items():
            row[columns[key]] = value
        healthy_rows.append(row)
        healthy_inventory.append([hashlib.sha256(str(path).encode()).hexdigest()[:16], gid, str(path), name, None, None, path.stat().st_size, None, 1, "主表使用；待EDF质控"])
    assert len({r[columns["编号"]] for r in healthy_rows}) == len(healthy_rows)
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    run_dir = args.logs / ("01_master_hc_" + stamp)
    run_dir.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=True)
    combined = [["患者组"] + list(r) for r in patients] + [["健康组"] + r for r in healthy_rows]
    result = Workbook(); result.remove(result.active)
    write_sheet(result, "受试者主表", ["组别"] + headers, combined)
    write_sheet(result, "EDF记录清单", ["组别"] + list(data["EDF记录清单"][0]), [["患者组"] + list(r) for r in data["EDF记录清单"][1:]] + [["健康组"] + r for r in healthy_inventory])
    write_sheet(result, "暂缓与排除", ["组别"] + list(data["暂缓与排除"][0]), [["患者组"] + list(r) for r in data["暂缓与排除"][1:]])
    rules = list(data["规则说明"][1:]) + [["健康组来源", str(args.healthy)], ["健康组编号", "hc_三位序号_姓名拼音首字母，首字母大写；首次按文件名排序，后续沿用登记表。"], ["健康组字段", "评分、诊断和入组状态未提供，保持空值；组别依据用户提供的信息。"], ["本次患者依据", str(args.patient_master)], ["继承核验", "患者纳排与副本SHA256沿用已核验主表，本次没有重新计算患者文件哈希。"]]
    write_sheet(result, "规则说明", ["项目", "说明"], rules)
    xlsx = args.output / ("01_受试者主表_" + stamp + ".xlsx")
    assert not xlsx.exists()
    result.save(xlsx)
    csv_path = xlsx.with_suffix(".csv")
    with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["组别"] + headers); writer.writerows(combined)
    registry_path = args.output / ("01_健康组编号_" + stamp + ".csv")
    with registry_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["编号", "姓名", "缩写", "记录GUID", "服务器EDF路径"])
        writer.writeheader(); writer.writerows(registry)
    check = load_workbook(xlsx, read_only=True, data_only=True)
    actual = list(check["受试者主表"].iter_rows(min_row=2, values_only=True))
    assert [r[1:] for r in actual[:len(patients)]] == patients, "患者内容发生变化"
    assert len(actual) == len(patients) + len(paths)
    for row in actual[len(patients):]:
        assert all(row[i+1] is None for i in range(5,13)), "健康组评分或诊断被误填"
    assert not EXCLUDED & {r[1] for r in actual}
    assert REPEATED_TESTS <= {r[1] for r in actual}
    check.close()
    summary = {"patient_records": len(patients), "healthy_records": len(healthy_rows), "total_records": len(combined), "subject_ids": len({r[columns["患者ID"]+1] for r in combined}), "edf_inventory_files": len(data["EDF记录清单"])-1+len(paths), "xlsx": str(xlsx), "csv": str(csv_path), "healthy_registry": str(registry_path), "patient_source": str(args.patient_master), "patient_source_sha256": digest(args.patient_master), "script": str(Path(__file__)), "script_sha256": digest(Path(__file__)), "patient_rows_unchanged": True, "healthy_clinical_fields_blank": True, "healthy_ids": [r[columns["编号"]] for r in healthy_rows], "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_master_report(summary, args.reports, stamp)
    print("FINAL_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)


def normalize_name(value):
    """去除审计患者字段混入的性别年龄等信息，纯姓名保持原样。"""
    return re.split(r'[男女]\d+岁',str(value).strip(),maxsplit=1)[0].strip()


def restore_confirmed(args):
    """只恢复用户明确确认的编号，其他记录和临床值保持不变。"""
    source=load_workbook(args.base_master,read_only=True,data_only=True)
    data={sheet.title:list(sheet.iter_rows(values_only=True)) for sheet in source};source.close()
    header=list(data['受试者主表'][0]);cols={v:i for i,v in enumerate(header)}
    current=[list(r) for r in data['受试者主表'][1:]]
    before={r[cols['编号']]:tuple(r) for r in current}
    requested=set(args.restore_codes)
    overrides=dict(value.split('=',1) for value in (args.guid_overrides or []))
    assert overrides.keys()<=requested,'指定GUID的编号不在恢复列表内'
    old_patient_count=sum(r[0]=='患者组' for r in current)
    old_healthy_count=sum(r[0]=='健康组' for r in current)
    assert not requested & before.keys(),'确认编号已在主表中'
    reference=load_workbook(args.reference,read_only=True,data_only=True)
    rows=list(reference['主表_127条'].iter_rows(values_only=True));reference.close()
    clinical={str(r[0]):(i,list(r)) for i,r in enumerate(rows[1:],2) if r[0]}
    inventory=[list(r) for r in data['EDF记录清单'][1:]]
    ic={v:i for i,v in enumerate(data['EDF记录清单'][0])}
    restored=[]
    for sid in sorted(requested):
        excel_row,row=clinical[sid];mapped=guids(overrides[sid]) if sid in overrides else guids(row[14]);assert len(mapped)==1
        gid=next(iter(mapped));files=[r for r in inventory if str(r[ic['记录GUID']]).lower()==gid]
        assert files and all(Path(r[ic['服务器EDF路径']]).is_file() for r in files)
        hashes={r[ic['内容SHA256']] for r in files}
        assert len(files)==1 or (len(hashes)==1 and None not in hashes),'多个副本未经一致性核验'
        assert gid not in {r[cols['记录GUID']] for r in current},'GUID已被主表其他记录使用'
        expected_name=str(row[2]).strip()
        for file in files:
            names={normalize_name(x) for x in str(file[ic['旧清单姓名']]).split(';')}
            assert names=={expected_name},'姓名规范化后仍不一致'
        canonical=min(files,key=lambda r:(Path(r[ic['服务器EDF路径']]).suffix.lower()!='.edf',str(r[ic['服务器EDF路径']])))
        new=[None]*len(header);new[0]='患者组'
        for col,name in enumerate(rows[0]):
            value=row[col]
            if 5<=col<12 and isinstance(value,str) and re.fullmatch(r'\d+',value.strip()):value=int(value.strip())
            new[cols[name]]=value
        values={'患者ID':'P-'+sid,'测试序次':1,'记录GUID':gid,'服务器EDF路径':canonical[ic['服务器EDF路径']],'同GUID物理文件数':len(files),'重复核验状态':'完整SHA256一致' if len(files)>1 else '单文件，无同GUID副本','内容SHA256':next(iter(hashes)),'旧表行号':excel_row,'对应依据':'用户确认指定GUID' if sid in overrides else '用户确认+纯姓名与旧GUID一致','核对备注':'采用用户指定EDF，其余同名记录暂不使用' if sid in overrides else '审计字段混入性别年龄科室导致旧解析误判，本次恢复纳入'}
        for name,value in values.items():new[cols[name]]=value
        if sid in overrides:
            new[cols['EDF匹配状态']]='用户确认指定EDF'
            new[cols['EDF信息']]=Path(canonical[ic['服务器EDF路径']]).name
        current.append(new);restored.append({'编号':sid,'姓名':expected_name,'GUID':gid})
        for file in files:
            file[ic['旧清单姓名']]=expected_name
            file[ic['使用状态']]='主表使用' if file is canonical else '相同内容副本，不重复使用'
    current.sort(key=lambda r:(r[0]!='患者组',str(r[cols['编号']])))
    assert all(tuple(r)==before[r[cols['编号']]] for r in current if r[cols['编号']] in before)
    deferred=[list(r) for r in data['暂缓与排除'][1:]];dc={v:i for i,v in enumerate(data['暂缓与排除'][0])}
    restored_guids={x['GUID'] for x in restored}
    deferred=[r for r in deferred if not (r[dc['条目类型']]=='评分记录' and str(r[dc['评分编号']]) in requested) and not(r[dc['条目类型']]=='EDF文件' and str(r[dc['关联GUID']]).lower() in restored_guids)]
    stamp=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S')
    out=args.output/('01_受试者主表_'+stamp+'.xlsx');assert not out.exists()
    book=Workbook();book.remove(book.active)
    write_sheet(book,'受试者主表',header,current)
    write_sheet(book,'EDF记录清单',list(data['EDF记录清单'][0]),inventory)
    write_sheet(book,'暂缓与排除',list(data['暂缓与排除'][0]),deferred)
    write_sheet(book,'规则说明',list(data['规则说明'][0]),list(data['规则说明'][1:])+[['本次恢复','用户确认：'+','.join(sorted(requested))+'；使用明确指定或已确认的GUID，其他纳排规则不变。'],['本次修订来源',str(args.base_master)]])
    book.save(out)
    with out.with_suffix('.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(header);writer.writerows(current)
    check=load_workbook(out,read_only=True,data_only=True)
    assert check['受试者主表'].max_row-1==len(current);check.close()
    counts=Counter(r[0] for r in current);remaining=sum(r[dc['条目类型']]=='评分记录' for r in deferred)
    previous_remaining=sum(r[data['暂缓与排除'][0].index('条目类型')]=='评分记录' for r in data['暂缓与排除'][1:])
    assert counts['患者组']==old_patient_count+len(requested) and counts['健康组']==old_healthy_count and remaining==previous_remaining-len(requested)
    sections=[('修订结果',[f"患者组{counts['患者组']}条测试记录，健康组{counts['健康组']}条，共{len(current)}条；原评分表仍有{remaining}条暂缓或排除。原有{len(before)}条内容保持不变。"],['恢复编号','姓名','GUID'],[[r['编号'],r['姓名'],r['GUID']] for r in restored]),('原因与处理',['按用户明确确认的EDF GUID建立一对一映射；未指定GUID时，核对规范化姓名与旧GUID。其余同名候选不自动纳入。','未重新运行其他记录的纳排，未改动评分、诊断及入组状态。本次新增记录尚未补跑EDF格式检查或修复转换。'],[],[]),('文件',[str(out),str(out.with_suffix('.csv')),str(args.base_master)],[],[])]
    report=write_report(args.reports,'01_主表修订报告_'+stamp,'受试者主表修订报告',sections)
    summary={'restored_codes':sorted(requested),'patient_records':counts['患者组'],'healthy_records':counts['健康组'],'total_records':len(current),'subject_ids':len({r[cols['患者ID']] for r in current}),'remaining_scoring_records':remaining,'previous_rows_unchanged':True,'xlsx':str(out),'csv':str(out.with_suffix('.csv')),'report':report}
    (args.logs/('01_主表修订_'+stamp+'.jsonl')).write_text(json.dumps(summary,ensure_ascii=False)+'\n',encoding='utf-8')
    print('FINAL_SUMMARY '+json.dumps(summary,ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--patient-master", type=Path, help="已核验患者主表，提供时只追加健康组")
    parser.add_argument("--healthy", type=Path)
    parser.add_argument("--healthy-registry", type=Path, help="复用已有健康组编号登记表")
    parser.add_argument("--base-master",type=Path,help="已有合并主表，用于恢复确认记录")
    parser.add_argument("--restore-codes",nargs="+",help="仅恢复用户明确确认的评分编号")
    parser.add_argument("--guid-overrides",nargs="+",help="用户确认映射，格式为评分编号=GUID")
    args = parser.parse_args()
    if args.restore_codes:
        if not args.base_master or not args.reference:
            parser.error("恢复记录需要 --base-master 和 --reference")
        restore_confirmed(args)
        return
    if args.patient_master:
        if not args.healthy:
            parser.error("追加健康组需要 --healthy")
        add_healthy(args)
        return
    if not args.reference or not args.raw:
        parser.error("从原始评分表构建需要 --reference 和 --raw")
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    run_dir = args.logs / ("01_master_" + stamp)
    run_dir.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=True)

    book = load_workbook(args.reference, read_only=True, data_only=True)
    source_rows = list(book["主表_127条"].iter_rows(values_only=True))
    headers, scores = list(source_rows[0]), [list(r) for r in source_rows[1:] if r[0]]
    assert len({r[0] for r in scores}) == len(scores), "旧评分编号不唯一"
    # 文件名到姓名的对应仅来自旧清单，不能把审计表建议当作执行指令。
    filename_names = defaultdict(set)
    for sheet_name in ["EDF清单_0830", "EDF清单_0831试实验", "未匹配EDF"]:
        data = list(book[sheet_name].iter_rows(values_only=True))
        cols = {str(v): i for i, v in enumerate(data[0])}
        for row in data[1:]:
            filename, name = row[cols["文件名"]], row[cols["姓名"]]
            if filename and name:
                filename_names[str(filename).replace("\\", "/").split("/")[-1]].add(normalize_name(name))
    audit_rows = list(book["0923补充审计"].iter_rows(values_only=True))
    header_index = next(i for i, r in enumerate(audit_rows) if "EDF文件名" in r and "GUID" in r)
    cols = {str(v): i for i, v in enumerate(audit_rows[header_index])}
    for row in audit_rows[header_index + 1:]:
        filename, name = row[cols["EDF文件名"]], row[cols["患者"]]
        if filename and name:
            filename_names[str(filename).replace("\\", "/").split("/")[-1]].add(normalize_name(name))
    book.close()

    files = sorted(p for p in args.raw.rglob("*") if p.is_file() and (p.suffix.lower() == ".edf" or p.name.lower().endswith(".edf copy")))
    groups, file_names, name_guids = defaultdict(list), {}, defaultdict(set)
    for path in files:
        ids = guids(path.name)
        assert len(ids) == 1, "文件 GUID 缺失或不唯一：" + str(path)
        gid = next(iter(ids))
        groups[gid].append(path)
        filename = path.name[:-5] if path.name.lower().endswith(".edf copy") else path.name
        names = filename_names.get(filename, set())
        file_names[path] = names
        for name in names:
            name_guids[name].add(gid)
    print(json.dumps({"stage": "inventory", "files": len(files), "guid_groups": len(groups), "duplicate_guid_groups": sum(len(v) > 1 for v in groups.values())}), flush=True)

    # 同 GUID 的多个物理文件必须比较完整内容，不能仅凭名称或大小选一个。
    hashes, conflicts, canonical = {}, set(), {}
    duplicate_groups = [(gid, paths) for gid, paths in groups.items() if len(paths) > 1]
    for index, (gid, paths) in enumerate(duplicate_groups, 1):
        for path in paths:
            hashes[path] = digest(path)
        if len({hashes[p] for p in paths}) > 1:
            conflicts.add(gid)
        print(json.dumps({"stage": "duplicate_hash", "done": index, "total": len(duplicate_groups)}), flush=True)
    for gid, paths in groups.items():
        if gid not in conflicts:
            # 内容相同时优先正式 EDF，再按路径排序；所有副本都保留在清单。
            canonical[gid] = sorted(paths, key=lambda p: (p.suffix.lower() != ".edf", str(p)))[0]

    score_names = defaultdict(list)
    for row in scores:
        score_names[str(row[2]).strip()].append(str(row[0]))
    decisions, master, deferred = {}, [], []
    new_headers = ["患者ID", "测试序次", "记录GUID", "服务器EDF路径", "同GUID物理文件数", "重复核验状态", "内容SHA256", "旧表行号", "对应依据", "核对备注"]
    for excel_row, row in enumerate(scores, 2):
        sid, name = str(row[0]), str(row[2]).strip()
        mapped = guids(row[14])
        candidates = name_guids[name] | mapped
        reasons = []
        if sid in EXCLUDED:
            reasons.append("用户指定排除：无EDF")
        elif sid not in REPEATED_TESTS and len(score_names[name]) > 1:
            reasons.append("同名多评分记录，暂不使用")
        if sid not in EXCLUDED:
            if sid not in REPEATED_TESTS and len(candidates) > 1:
                reasons.append("一个评分对应多个不同EDF记录，暂不使用")
            if len(mapped) != 1:
                reasons.append("旧评分映射缺失" if not mapped else "旧评分映射多个GUID，暂不使用")
            elif not mapped <= groups.keys():
                reasons.append("旧映射GUID在服务器不存在")
            if candidates & conflicts:
                reasons.append("同GUID文件内容不同，暂不使用")
            if any(len(file_names[p]) != 1 or name not in file_names[p] for gid in mapped for p in groups.get(gid, [])):
                reasons.append("文件姓名对应不明确，暂不使用")
        decisions[sid] = ";".join(reasons) or "可用"
        if reasons:
            deferred.append(["评分记录", sid, ";".join(sorted(candidates)), ";".join(reasons), "", excel_row])
            continue
        gid = next(iter(mapped))
        path = canonical[gid]
        # 仅将确实为整数的评分字符串转换为数值；缺失符号和临床原文保持原样。
        clinical = row.copy()
        for col in range(5, 12):
            if isinstance(clinical[col], str) and re.fullmatch(r"\d+", clinical[col].strip()):
                clinical[col] = int(clinical[col].strip())
        subject = "P-306-LCS" if sid in REPEATED_TESTS else "P-" + sid
        session = 2 if sid == "447-LCS" else 1
        comment = "用户确认两次测试，沿用各自旧GUID对应；其他候选不使用" if sid in REPEATED_TESTS else "沿用旧评分GUID对应"
        if row[3] != "是":
            comment += "；原入组状态保持不变，是否纳入后续分析另行确认"
        master.append(clinical + [subject, session, gid, str(path), len(groups[gid]), "完整SHA256一致" if len(groups[gid]) > 1 else "单文件，无同GUID副本", hashes.get(path), excel_row, "旧评分GUID+服务器清单核对", comment])

    by_guid_scores = defaultdict(list)
    for row in scores:
        for gid in guids(row[14]):
            by_guid_scores[gid].append(str(row[0]))
    inventory = []
    master_guids = {row[len(headers)+2] for row in master}
    for path in files:
        gid = next(iter(guids(path.name)))
        names = file_names[path]
        linked = by_guid_scores[gid]
        candidate_scores = sorted({sid for name in names for sid in score_names.get(name, [])})
        if gid in conflicts:
            status = "暂缓：同GUID内容冲突"
        elif gid in master_guids:
            status = "主表使用" if path == canonical[gid] else "相同内容副本，不重复使用"
        elif not candidate_scores:
            status = "暂缓：无对应评分或身份未明确"
        elif not linked:
            status = "暂缓：额外记录无独立评分对应"
        else:
            status = "暂缓：" + ";".join(sorted({decisions[s] for s in linked}))
        inventory.append([hashlib.sha256(str(path).encode()).hexdigest()[:16], gid, str(path), ";".join(sorted(names)), ";".join(linked), ";".join(candidate_scores), path.stat().st_size, hashes.get(path), len(groups[gid]), status])
        if gid not in master_guids:
            deferred.append(["EDF文件", ";".join(candidate_scores), gid, status, str(path), None])

    # 主表每一行对应一次评分/测试；全部评分和物理文件均有去向。
    assert len(master) + sum(r[0] == "评分记录" for r in deferred) == len(scores)
    assert len(inventory) == len(files)
    assert not ({r[0] for r in master} & EXCLUDED)
    assert REPEATED_TESTS <= {r[0] for r in master}, "两次测试未能明确匹配，停止输出以防错误纳入"
    assert len(master_guids) == len(master), "同一记录被重复纳入主表"
    assert all(Path(r[len(headers)+3]).is_file() for r in master)
    result = Workbook()
    result.remove(result.active)
    write_sheet(result, "患者主表", headers + new_headers, master)
    write_sheet(result, "EDF记录清单", ["文件ID", "记录GUID", "服务器EDF路径", "旧清单姓名", "旧映射评分编号", "同名候选评分编号", "文件大小_bytes", "内容SHA256", "同GUID物理文件数", "使用状态"], inventory)
    write_sheet(result, "暂缓与排除", ["条目类型", "评分编号", "关联GUID", "原因", "服务器EDF路径", "旧表行号"], deferred)
    rules = [
        ["表格单位", "患者主表每行对应一次评分/测试，不等同于独立患者人数。"],
        ["指定排除", "330-SLP、444-JHX、446-LSJ：无EDF，不进入可用主表。"],
        ["两次测试", "306-LCS、447-LCS保留各自旧GUID，对应同一患者的两次测试。"],
        ["多记录", "除上述两次测试外，一个评分下多份不同GUID记录整组暂缓；完全相同的副本不计作多次采集。"],
        ["无评分", "EDF没有对应评分或额外记录无独立评分对应，暂缓。"],
        ["内容冲突", "同GUID文件完整SHA256不同，暂缓，不自动替换。"],
        ["评分与诊断", "保留原文，仅把可确认的整数评分转成数值；原入组状态不改写。"],
        ["哈希范围", "仅对存在同GUID副本的文件计算完整SHA256；单文件哈希留空，不代表已验证其质量。"],
        ["来源", str(args.reference)],
        ["原始数据", str(args.raw)],
        ["检查范围", "仅核对评分对应和文件副本，尚未检查EDF可读性、信号质量或进行预处理。"],
    ]
    write_sheet(result, "规则说明", ["项目", "说明"], rules)
    result["患者主表"].sheet_properties.tabColor = "274060"
    result["规则说明"].column_dimensions["B"].width = 110
    xlsx = args.output / ("01_患者主表_" + stamp + ".xlsx")
    assert not xlsx.exists()
    result.save(xlsx)
    csv_path = xlsx.with_suffix(".csv")
    with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers + new_headers)
        writer.writerows(master)
    reopened = load_workbook(xlsx, read_only=True, data_only=True)
    assert reopened["患者主表"].max_row - 1 == len(master)
    assert reopened["EDF记录清单"].max_row - 1 == len(files)
    assert sum(1 for row in reopened["患者主表"].iter_rows(min_row=2) for c in row if c.data_type == "e") == 0
    reopened.close()
    commit = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"], capture_output=True, text=True)
    summary = {"source_scoring_rows": len(scores), "usable_scoring_rows": len(master), "usable_subject_ids": len({r[len(headers)] for r in master}), "deferred_scoring_rows": len(scores)-len(master), "edf_files": len(files), "guid_groups": len(groups), "conflicting_guid_groups": len(conflicts), "duplicate_content_groups": len(duplicate_groups)-len(conflicts), "score_decision_counts": dict(Counter(decisions.values())), "master_enrollment_counts": dict(Counter(str(r[3]) for r in master)), "xlsx": str(xlsx), "csv": str(csv_path), "run_directory": str(run_dir), "reference_sha256": digest(args.reference), "script_sha256": digest(Path(__file__)), "git_commit": commit.stdout.strip() if commit.returncode == 0 else None, "git_uncommitted_changes": True, "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "rules.json").write_text(json.dumps(dict(rules), ensure_ascii=False, indent=2), encoding="utf-8")
    write_master_report(summary, args.reports, stamp)
    print("FINAL_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
