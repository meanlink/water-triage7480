"""分析任务明细导出（纯函数模块，不依赖 ORM/框架，便于离线核对）。"""
import csv
import io
from fastapi import HTTPException


def csv_safe(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    text = str(v)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text


def detail_csv(job, side=None):
    """生成任务结果明细 CSV；逐行带管段归属与指标来源，支持按侧过滤。

    兼容历史结果：旧任务没有 split_side/hash_bucket 等新列时留空，
    并在文件头注明口径版本，旧试验仍可下载核对。
    """
    if job.status != 'completed' or not job.result:
        raise HTTPException(409, '任务尚未计算完成，无明细可下载')
    if side not in (None, '', '训练', '验证'):
        raise HTTPException(422, 'side 仅支持 训练 或 验证')
    result = job.result
    table = result.get('table', {}) or {}
    columns = table.get('columns', []) or []
    rows = table.get('rows', []) or []
    split = result.get('split')
    is_v2 = bool(split)
    if side and is_v2:
        rows = [r for r in rows if r.get('split_side') == side]
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow(['# 任务', job.name])
    writer.writerow(['# 任务ID', job.id])
    writer.writerow(['# 划分口径', result.get('method', '')])
    if is_v2:
        writer.writerow(['# 划分版本', split.get('version', '')])
        writer.writerow(['# 划分规则', split.get('rule', '')])
        cc = split.get('class_counts', {})
        writer.writerow(['# 训练侧管段/记录', f"{split.get('train_segments', '')} 段 / {split.get('train_records', '')} 条（漏点{cc.get('train', {}).get('leak', '')}、非漏点{cc.get('train', {}).get('normal', '')}）"])
        writer.writerow(['# 验证侧管段/记录', f"{split.get('valid_segments', '')} 段 / {split.get('valid_records', '')} 条（漏点{cc.get('valid', {}).get('leak', '')}、非漏点{cc.get('valid', {}).get('normal', '')}）"])
        writer.writerow(['# 说明', '同一管段的全部复测记录整体同侧；归属由管段编号哈希决定，与导入顺序及树参数无关'])
    else:
        writer.writerow(['# 划分版本', 'legacy（升级前历史试验，按旧分层留出口径计算，无管段归属列）'])
    if side:
        writer.writerow(['# 本次导出范围', side + '侧'])
    writer.writerow([c.get('label', c.get('key', '')) for c in columns])
    for r in rows:
        writer.writerow([csv_safe(r.get(c.get('key'), '')) for c in columns])
    side_code = {'训练': 'train', '验证': 'valid'}.get(side, '')
    filename = f"job-{job.id}-segment-detail{'-' + side_code if side_code else ''}.csv"
    return out.getvalue().encode('utf-8'), filename
