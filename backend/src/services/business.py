"""管段漏损分诊：可剪枝的决策树与按管段隔离的分层留出验证。

划分口径（升级后）：
- 以 segment_id 的稳定哈希决定管段归属，同一管段的全部复测记录整体进入
  训练侧或验证侧，不会同时出现在两侧，避免复测样本抬高漏点召回率。
- 归属只取决于管段编号本身，与导入顺序、树参数无关；对同一数据批次重复
  试验会得到完全一致的管段归属。
- 训练/验证两侧都必须同时包含漏点与非漏点两类样本，否则拒绝并说明原因。
"""
import hashlib

import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix

FEATURES = ["night_flow", "pressure_drop", "acoustic_db", "pipe_age"]
LABELS = ["夜间流量(m³/h)", "压力降(kPa)", "声学读数(dB)", "管龄(年)"]

SPLIT_VERSION = "segment-hash-v1"
VALID_RATIO = 0.30
# 与历史口径保持一致的 1000 桶门限：哈希值 < 300/1000 的管段进入验证侧。
VALID_HASH_THRESHOLD = 300
HASH_BUCKETS = 1000
SPLIT_NAMESPACE = "water-triage:segment-holdout:v1"

METRIC_LABELS = [
    ("f1", "F1", 4, ""),
    ("recall", "漏点召回率", 2, "%"),
    ("precision", "分诊精确率", 2, "%"),
]


def metadata():
    return {
        "name": "供水漏损分诊实验", "short": "water-triage",
        "tagline": "把历史巡检证据转成可解释分诊规则，先核验漏检代价。",
        "client": "澄川水务 · 城北巡检班12人 · 280个已复核管段样本",
        "workflow": "值班员把夜间流量、压力和听漏记录抄入表格，根据单一声学阈值安排巡查。",
        "pains": ["单阈值遗漏低噪声漏点", "缺少对巡检规则复杂度的控制", "规则好坏只凭训练样本判断"],
        "upstream": "城北分区流量计与人工复核台账 north_zone_segments.csv",
        "downstream": "巡检组长审阅分诊误报和漏检，决定下一轮人工现场检查顺序",
        "entities": ["管段复核样本", "分诊规则试验", "巡检复核简报"],
        "dataset_name": "城北管段夜间流量与已复核标签",
        "columns": [{"key": "segment_id", "label": "管段编号", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)] + [{"key": "confirmed_leak", "label": "复核漏点(1/0)", "type": "number"}],
        "parameters": [{"key": "max_depth", "label": "决策树最大深度", "type": "number", "default": 3, "min": 1, "max": 8}, {"key": "min_leaf", "label": "叶节点最少样本", "type": "number", "default": 5, "min": 2, "max": 20}],
        "workbench_title": "漏损分诊规则试验", "action_label": "训练并核验分诊规则", "unit": "段管线",
        "accent": "oklch(48% 0.10 210)", "style": "blueprint",
        "seed_story": ["07:30 值班员导入 north_zone_segments.csv 的280段历史复核记录", "07:40 检查夜间流量、压力降、声学读数与管龄", "08:00 用深度3、最小叶节点5发起规则试验", "08:01 系统按管段编号固定保留约30%管段独立核验，同一管段复测记录整体同侧", "08:10 组长先看漏检数量，再看特征重要性", "08:20 将深度从3调为5比较训练/验证两侧F1", "08:30 下载管段分诊明细，核对每段归属后选择现场复核清单", "09:00 管理员安排次日07:30规则复核简报"],
        "method": "按管段隔离的分层留出（%s）：对 segment_id 做带盐SHA-256哈希，约30%%管段整体进验证侧、其余进训练侧，同一管段的复测记录不会跨侧；Gini决策树按max_depth和min_samples_leaf剪枝，random_state=42；训练与验证两侧均计算精确率、召回率、F1和混淆矩阵。" % SPLIT_VERSION,
        "limitations": ["模拟历史样本不能替代听漏与开挖确认", "未使用空间邻接关系", "特征重要性反映模型分裂贡献而非因果"],
    }


def seed_records():
    rng = np.random.default_rng(1009)
    rows = []
    for i in range(280):
        flow = float(np.clip(rng.normal(23, 10), 2, 60))
        pressure = float(np.clip(rng.gamma(2.2, 5), 0.5, 40))
        sound = float(np.clip(rng.normal(42, 12), 12, 85))
        age = int(rng.integers(1, 46))
        leak = (flow > 26 and pressure > 10) or (sound > 50 and age > 18) or pressure > 25
        if rng.random() < 0.07:
            leak = not leak
        rows.append({"segment_id": f"NC-{i+1:03}", "night_flow": round(flow, 2), "pressure_drop": round(pressure, 2), "acoustic_db": round(sound, 1), "pipe_age": age, "confirmed_leak": int(leak)})
    return rows


def segment_bucket(segment_id):
    """管段编号 -> 确定性 0~999 哈希桶。仅依赖编号文本，与顺序无关。"""
    digest = hashlib.sha256((SPLIT_NAMESPACE + "|" + str(segment_id)).encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % HASH_BUCKETS


def _metric_group(side_name, y_true, prediction):
    precision = float(precision_score(y_true, prediction, zero_division=0))
    recall = float(recall_score(y_true, prediction, zero_division=0))
    f1 = float(f1_score(y_true, prediction, zero_division=0))
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y_true, prediction, labels=[0, 1]).ravel()]
    return {
        "side": side_name,
        "sample_records": int(len(y_true)),
        "class_counts": {"leak": int((y_true == 1).sum()), "normal": int((y_true == 0).sum())},
        "metrics": [
            {"label": side_name + "F1", "value": round(f1, 4)},
            {"label": side_name + "漏点召回率", "value": round(recall * 100, 2), "unit": "%"},
            {"label": side_name + "分诊精确率", "value": round(precision * 100, 2), "unit": "%"},
            {"label": side_name + "漏检", "value": fn, "unit": "段"},
            {"label": side_name + "误报", "value": fp, "unit": "段"},
        ],
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "raw": {"f1": round(f1, 4), "recall_pct": round(recall * 100, 2),
                "precision_pct": round(precision * 100, 2)},
    }


def _validate_and_group(records):
    """校验管段编号与标签一致性，返回按管段聚合后的分组信息。

    失败时抛出 ValueError，调用方据此把任务置为 failed，不生成成功结果。
    """
    if len(records) < 40:
        raise ValueError("至少需要40条管段复核样本。")
    segment_labels = {}
    segment_rows = {}
    for index, row in enumerate(records):
        sid = row.get("segment_id")
        if sid is None or str(sid).strip() == "":
            raise ValueError(f"第 {index + 1} 行缺失管段编号(segment_id)，无法按管段隔离划分。")
        sid = str(sid)
        label_raw = row.get("confirmed_leak")
        try:
            label = int(float(label_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"管段 {sid}（第 {index + 1} 行）复核标签须为0/1。") from exc
        if sid in segment_labels and segment_labels[sid] != label:
            raise ValueError(
                f"同一管段 {sid} 存在标签冲突：既有 confirmed_leak={segment_labels[sid]} "
                f"又出现 confirmed_leak={label}，请先核对复测台账。"
            )
        segment_labels[sid] = label
        segment_rows.setdefault(sid, []).append(index)

    groups = []  # (segment_id, label, [record indexes], bucket, side)
    for sid, label in segment_labels.items():
        bucket = segment_bucket(sid)
        side = "valid" if bucket < VALID_HASH_THRESHOLD else "train"
        groups.append((sid, label, segment_rows[sid], bucket, side))
    return groups, segment_labels


def analyze(records, params):
    try:
        depth_raw = float(params.get("max_depth", 3))
        leaf_raw = float(params.get("min_leaf", 5))
        depth, leaf = int(depth_raw), int(leaf_raw)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("树深度与最小叶节点须为整数。") from exc
    if depth != depth_raw or leaf != leaf_raw or not 1 <= depth <= 8 or not 2 <= leaf <= 20:
        raise ValueError("树深度须为1~8，最小叶节点须为2~20，且都为整数。")
    if len(records) < 40:
        raise ValueError("至少需要40条管段复核样本。")
    try:
        x = np.asarray([[float(row[k]) for k in FEATURES] for row in records])
        y_raw = np.asarray([float(row["confirmed_leak"]) for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("管段字段必须完整且为数值。") from exc
    if not np.isfinite(x).all() or (x < 0).any() or not np.isin(y_raw, [0, 1]).all():
        raise ValueError("测量值须非负有限，复核标签须为0/1。")
    y = y_raw.astype(int)
    if np.bincount(y, minlength=2).min() < 8:
        raise ValueError("漏点与非漏点样本各至少8条。")

    groups, segment_labels = _validate_and_group(records)

    train_idx, valid_idx = [], []
    train_segments, valid_segments = set(), set()
    for sid, label, row_indexes, bucket, side in groups:
        if side == "valid":
            valid_idx.extend(row_indexes)
            valid_segments.add(sid)
        else:
            train_idx.extend(row_indexes)
            train_segments.add(sid)
    train_idx = np.asarray(sorted(train_idx), dtype=int)
    valid_idx = np.asarray(sorted(valid_idx), dtype=int)

    # 两类样本在两侧都可评估：每侧都必须同时出现漏点与非漏点。
    side_class_counts = {}
    for side_name, idx in (("train", train_idx), ("valid", valid_idx)):
        if len(idx) == 0:
            raise ValueError(f"按管段哈希划分后{('训练' if side_name == 'train' else '验证')}侧为空，无法划分。")
        counts = np.bincount(y[idx], minlength=2)
        side_class_counts[side_name] = {"leak": int(counts[1]), "normal": int(counts[0])}
    missing = []
    for side_name, zh in (("train", "训练"), ("valid", "验证")):
        for cls, cls_zh in (("leak", "漏点"), ("normal", "非漏点")):
            if side_class_counts[side_name][cls] < 1:
                missing.append(f"{zh}侧缺少{cls_zh}样本")
    if missing:
        raise ValueError(
            "无法按管段隔离划分：" + "、".join(missing) +
            "。请补充覆盖该类别的管段后重试；本任务未生成结果。"
        )

    model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=leaf, random_state=42)
    model.fit(x[train_idx], y[train_idx])

    train_pred = model.predict(x[train_idx])
    valid_prob = model.predict_proba(x[valid_idx])[:, 1]
    valid_pred = model.predict(x[valid_idx])

    train_group = _metric_group("训练", y[train_idx], train_pred)
    valid_group = _metric_group("验证", y[valid_idx], valid_pred)

    # 明细覆盖全部记录（训练+验证），逐行给出管段归属与指标来源侧。
    detail = {}
    for j, idx in enumerate(valid_idx):
        detail[int(idx)] = (float(valid_prob[j]), int(valid_pred[j]), "验证")
    train_prob_all = model.predict_proba(x[train_idx])[:, 1]
    for j, idx in enumerate(train_idx):
        detail[int(idx)] = (float(train_prob_all[j]), int(train_pred[j]), "训练")

    rows = []
    # 验证侧在前（组长复核重点），训练侧在后；同侧按风险降序。
    ordered = sorted(detail.items(), key=lambda item: (0 if item[1][2] == "验证" else 1, -item[1][0], item[0]))
    for record_idx, (prob, pred, side) in ordered:
        row = records[record_idx]
        sid = str(row.get("segment_id", f"row-{record_idx + 1}"))
        rows.append({
            "row_no": record_idx + 1,
            "segment_id": sid,
            "split_side": side,
            "hash_bucket": segment_bucket(sid),
            "sample_class": "漏点" if y[record_idx] == 1 else "非漏点",
            "risk_pct": round(prob * 100, 1),
            "triage": "优先听漏复核" if pred else "常规巡查",
            "actual": "已确认漏点" if y[record_idx] else "已确认正常",
        })

    important = int(np.argmax(model.feature_importances_))
    first_rule = export_text(model, feature_names=FEATURES).splitlines()[0].strip()
    v_cm, t_cm = valid_group["confusion"], train_group["confusion"]
    split = {
        "version": SPLIT_VERSION,
        "rule": f"segment_id 带盐SHA-256取模{HASH_BUCKETS}，桶号<{VALID_HASH_THRESHOLD}进验证侧（约{int(VALID_RATIO * 100)}%），其余进训练侧",
        "namespace": SPLIT_NAMESPACE,
        "threshold": VALID_HASH_THRESHOLD,
        "buckets": HASH_BUCKETS,
        "order_independent": True,
        "param_independent": True,
        "total_records": len(records),
        "total_segments": len(groups),
        "duplicate_segment_records": len(records) - len(groups),
        "train_segments": len(train_segments),
        "valid_segments": len(valid_segments),
        "train_records": int(len(train_idx)),
        "valid_records": int(len(valid_idx)),
        "class_counts": side_class_counts,
    }
    return {
        "schema_version": 2,
        "split": split,
        "summary": (
            f"按管段隔离划分：{len(train_segments)}段/{len(train_idx)}条记录训练、"
            f"{len(valid_segments)}段/{len(valid_idx)}条记录独立验证，同管段复测不跨侧；"
            f"实际树深{model.get_depth()}，生成{model.get_n_leaves()}个可复核叶节点。"
        ),
        # 顶层保留验证侧指标，兼容旧页面与历史消费方。
        "metrics": valid_group["metrics"],
        "metric_groups": [train_group, valid_group],
        "table": {
            "columns": [
                {"key": "row_no", "label": "记录序号"},
                {"key": "segment_id", "label": "管段编号"},
                {"key": "split_side", "label": "划分归属"},
                {"key": "hash_bucket", "label": "哈希桶(0-999)"},
                {"key": "sample_class", "label": "样本类别"},
                {"key": "risk_pct", "label": "叶节点漏点率(%)"},
                {"key": "triage", "label": "分诊建议"},
                {"key": "actual", "label": "复核结果"},
            ],
            "rows": rows,
        },
        "chart": {"type": "bar", "labels": LABELS, "series": [{"name": "Gini分裂重要性", "values": [round(float(v), 4) for v in model.feature_importances_]}]},
        "findings": [
            f"验证侧混淆矩阵：命中漏点{v_cm['tp']}、误报{v_cm['fp']}、漏检{v_cm['fn']}、正确排除{v_cm['tn']}；训练侧对应为命中{t_cm['tp']}、误报{t_cm['fp']}、漏检{t_cm['fn']}、正确排除{t_cm['tn']}。",
            f"管段归属由编号哈希固定（{SPLIT_VERSION}）：训练{len(train_segments)}段、验证{len(valid_segments)}段，调换导入顺序或调整树参数均不改变归属，同管段{len(records) - len(groups)}条复测记录整体同侧。",
            f"模型最重视{LABELS[important]}；根节点规则：{first_rule}。",
            f"两侧指标可对照：训练F1 {train_group['raw']['f1']} vs 验证F1 {valid_group['raw']['f1']}；训练召回 {train_group['raw']['recall_pct']}% vs 验证召回 {valid_group['raw']['recall_pct']}%，差距过大提示对训练管段过拟合。",
            "调高树深可能拟合局部噪声；只依据两侧F1和漏检率选择规则复杂度。",
        ],
        "method": metadata()["method"],
        "warnings": ["分诊规则仅辅助现场巡检，不作为自动停水或施工决策。", "管段归属与指标来源侧逐行见结果明细及下载CSV，可按管段编号复核。"],
    }
