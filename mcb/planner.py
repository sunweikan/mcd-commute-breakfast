"""早餐搭配引擎。

输入门店可售餐品 + 营养数据，按「预算 / 热量目标 / 蛋白质偏好」
生成 Top N 早餐搭配。

搭配规则（符合大多数人的早餐习惯）：
- 1 份主食（麦满分 / 粥 / 热香饼等）
- 1 份饮品（豆浆 / 咖啡等）
- 可选 1 份小食（薯饼等），仅在预算允许时加入

评分维度：热量贴合度、蛋白质密度、预算贴合度、钠含量惩罚。
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional

from .models import Combo, MenuItem

# 分类关键词（与麦当劳菜单分类/标签对齐的宽松匹配）
_STAPLE_KEYWORDS = ("麦满分", "粥", "热香饼", "卷", "汉堡", "堡")
_DRINK_KEYWORDS = ("豆浆", "咖啡", "牛奶", "橙汁", "可乐", "茶")
_SNACK_KEYWORDS = ("薯饼", "油条", "派")


def classify(item: MenuItem) -> str:
    """把餐品粗分为 staple / drink / snack / other。"""
    text = item.name + " " + item.category + " " + " ".join(item.tags)
    if any(k in text for k in _DRINK_KEYWORDS):
        return "drink"
    if any(k in text for k in _SNACK_KEYWORDS):
        return "snack"
    if any(k in text for k in _STAPLE_KEYWORDS):
        return "staple"
    return "other"


def is_prebuilt_combo(item: MenuItem) -> bool:
    """判断是否为官方套餐（二件套/三件套/组合），套餐本身即完整搭配。"""
    text = item.name + " " + " ".join(item.tags)
    return any(k in text for k in ("件套", "组合", "套餐"))


def filter_breakfast(items: List[MenuItem]) -> List[MenuItem]:
    """筛出早餐餐品（早餐标记 或 名称命中早餐关键词）。"""
    result = [i for i in items if i.is_breakfast]
    if result:
        return result
    keywords = _STAPLE_KEYWORDS + ("早餐",)
    return [i for i in items if any(k in i.name for k in keywords)]


def attach_nutrition(items: List[MenuItem], nutrition_rows: List[dict]) -> int:
    """把 MCP list-nutrition-foods 的营养数据按名称挂到餐品上。

    返回成功挂接的餐品数（覆盖率统计用）。
    """
    table: Dict[str, dict] = {}
    for row in nutrition_rows or []:
        name = str(row.get("name") or row.get("foodName") or "").strip()
        if name:
            table[name] = row

    matched = 0
    for item in items:
        row = table.get(item.name) or _fuzzy_find(table, item.name)
        if not row:
            continue
        item.kcal = _num(row, "energyKcal", "kcal", "energy")
        item.protein_g = _num(row, "protein", "proteinG")
        item.fat_g = _num(row, "fat", "fatG")
        item.carbs_g = _num(row, "carbohydrate", "carbs", "carbsG")
        item.sodium_mg = _num(row, "sodium", "sodiumMg")
        matched += 1
    return matched


def generate_combos(
    items: List[MenuItem],
    budget: float = 15.0,
    kcal_min: float = 300.0,
    kcal_max: float = 650.0,
    top_n: int = 3,
    allow_snack: bool = True,
) -> List[Combo]:
    """生成评分最高的 N 套早餐搭配。"""
    prebuilt = [i for i in items if is_prebuilt_combo(i)]
    singles = [i for i in items if not is_prebuilt_combo(i)]
    staples = [i for i in singles if classify(i) == "staple"]
    drinks = [i for i in singles if classify(i) == "drink"]
    snacks = [i for i in singles if classify(i) == "snack"] if allow_snack else []

    combos: List[Combo] = []
    for item in prebuilt:
        combo = Combo(items=[item])
        combo.label = "官方套餐"
        combos.append(combo)
    for staple in staples:
        for drink in drinks:
            base = [staple, drink]
            combos.append(Combo(items=list(base)))
            for snack in snacks:
                combos.append(Combo(items=[staple, drink, snack]))
        # 主食单独一份也允许（预算特别紧的场景）
        combos.append(Combo(items=[staple]))

    scored = [
        (score_combo(c, budget, kcal_min, kcal_max), c)
        for c in combos
        if c.total_price <= budget * 1.15  # 允许 15% 弹性
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    # 去重：同一主食只保留其最佳搭配，保证推荐多样性
    seen_staples = set()
    result: List[Combo] = []
    for _, combo in scored:
        staple_name = _dedup_key(combo)
        if staple_name in seen_staples:
            continue
        seen_staples.add(staple_name)
        label = _make_label(combo, budget, kcal_min, kcal_max)
        if len(combo.items) == 1 and is_prebuilt_combo(combo.items[0]):
            combo.label = f"官方套餐 · {label}"
        else:
            combo.label = label
        result.append(combo)
        if len(result) >= top_n:
            break
    return result


def score_combo(
    combo: Combo, budget: float, kcal_min: float, kcal_max: float
) -> float:
    """给一套搭配打分（0~100）。"""
    score = 60.0

    # 完整早餐奖励：主食 + 饮品（或官方套餐）是一顿像样的早餐
    kinds = {classify(i) for i in combo.items}
    if "staple" in kinds and "drink" in kinds:
        score += 12
    elif len(combo.items) == 1 and is_prebuilt_combo(combo.items[0]):
        score += 12
    elif len(combo.items) == 1:
        score -= 8  # 光啃一个汉堡不配喝的，体验打折

    # 热量贴合度：落在目标区间 +20，偏离按比例扣分
    kcal = combo.total_kcal
    if kcal > 0:
        if kcal_min <= kcal <= kcal_max:
            score += 20
        else:
            over = max(kcal_min - kcal, kcal - kcal_max, 0)
            score -= min(25.0, over / 20.0)

    # 蛋白质密度：每 100 kcal 的蛋白克数，4g/100kcal 以上视为优秀
    if kcal > 0 and combo.total_protein > 0:
        density = combo.total_protein / kcal * 100
        score += min(15.0, density / 4.0 * 15.0)

    # 预算贴合度：不超过预算加分，越省钱越加分（但不为省钱牺牲太多）
    price = combo.total_price
    if price <= budget:
        score += 5 + (budget - price) / budget * 5

    # 钠含量惩罚：一顿早餐钠超过 800mg 开始扣分
    sodium = sum(i.sodium_mg or 0 for i in combo.items)
    if sodium > 800:
        score -= min(10.0, (sodium - 800) / 100.0)

    return round(score, 2)


def _make_label(combo: Combo, budget: float, kcal_min: float, kcal_max: float) -> str:
    tags = []
    if combo.total_price <= budget * 0.7:
        tags.append("省钱向")
    if combo.total_protein >= 20:
        tags.append("高蛋白")
    if kcal_min <= combo.total_kcal <= kcal_max:
        tags.append("热量适中")
    if len(combo.items) == 1 and not is_prebuilt_combo(combo.items[0]):
        tags.append("极简")
    return " · ".join(tags) if tags else "均衡搭配"


def _dedup_key(combo: Combo) -> str:
    """去重键：同一主食的单品/套餐形态视为同一款，保证推荐多样性。"""
    name = combo.items[0].name
    for suffix in ("组合", "套餐"):
        name = name.replace(suffix, "")
    return name


def _fuzzy_find(table: Dict[str, dict], name: str) -> Optional[dict]:
    """营养表名称与菜单名称常有小差异，做包含式模糊匹配。"""
    for key, row in table.items():
        if key in name or name in key:
            return row
    return None


def _num(row: dict, *keys: str) -> Optional[float]:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
