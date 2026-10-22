"""编排层：串联 MCP 调用 -> 门店匹配 -> 搭配生成 -> 优惠计算 -> 方案输出。

真实模式走麦当劳 MCP Server；演示模式读取 data/ 下的样本数据，
方便没有 MCP Token 的用户一键体验。

真实接口结构（2026-10 实测）：
- query-nearby-stores: 入参 {beType:1, city, keyword, searchType:2}
  返回 data[].{storeCode, storeName, address, distance(米), businessStatus,
  reservation, reservationTimeOptions}
- query-meals: 入参 {storeCode, orderType:1, beType:1}
  返回 data.categories[].meals[].{code, tags}（无名称无价格）
- calculate-price: 入参 {storeCode, orderType, beType, items:[{productCode, quantity}]}
  返回 data.productList[].{productCode, productName, subtotal(单位:分)}
- list-nutrition-foods: 返回 data 为 CSV 风格字符串
  "[N]{productName,...,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n 行..."
- query-my-coupons: 返回 data.coupons[]
- campaign-calendar: 返回 data.dailyList[].events[]
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple

from .coupons import effective_value, parse_coupons, pick_best_coupon
from .models import BreakfastPlan, MenuItem, Store
from .planner import attach_nutrition, filter_breakfast, generate_combos
from .stores import merge_nearby_stores, pick_breakfast_store

_MCD_MCP_URL = "https://mcp.mcd.cn"
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# 早餐相关分类关键词（query-meals 的分类名是多行文本，做宽松匹配）
_BREAKFAST_CATEGORY_KEYWORDS = (
    "早餐", "麦满分", "松饼", "粥", "咖啡", "饮", "豆浆", "小食", "热卖",
)
# 但即使分类命中，也要排除明显是正餐的名字
_NON_BREAKFAST_NAME_KEYWORDS = ("巨无霸", "麦辣鸡腿堡套餐", "安格斯")


def build_plan_demo(
    budget: float = 15.0,
    kcal_min: float = 300.0,
    kcal_max: float = 650.0,
    top_n: int = 3,
) -> BreakfastPlan:
    """演示模式：用内置样本数据生成方案（无需 Token）。"""
    home_stores = _load_sample("sample_stores_home.json")
    company_stores = _load_sample("sample_stores_company.json")
    meals = _load_sample("sample_meals.json")
    nutrition = _load_sample("sample_nutrition.json")
    coupons_raw = _load_sample("sample_coupons.json")
    campaigns = _extract_campaigns({"dailyList": _load_sample("sample_campaigns.json")})
    return _assemble(
        home_stores, company_stores, meals, nutrition, coupons_raw, campaigns,
        budget, kcal_min, kcal_max, top_n,
    )


def build_plan_live(
    token: str,
    home: str,
    company: str,
    budget: float = 15.0,
    kcal_min: float = 300.0,
    kcal_max: float = 650.0,
    top_n: int = 3,
) -> BreakfastPlan:
    """真实模式：调用麦当劳 MCP Server 生成方案。"""
    from .mcp_client import MCPClient

    client = MCPClient(_MCD_MCP_URL, token)
    client.connect()

    home_stores = _query_stores(client, home)
    company_stores = _query_stores(client, company)

    stores = merge_nearby_stores(home_stores, company_stores)
    store = pick_breakfast_store(stores)
    if store is None:
        raise RuntimeError("住处和公司附近都没有找到可用门店，换个更具体的地址试试？")

    # 1) 拿菜单：分类 -> 餐品 code 列表
    meals_result = client.call_tool(
        "query-meals", {"storeCode": store.store_id, "orderType": 1, "beType": 1}
    )
    code_tags = _extract_breakfast_codes(meals_result)
    if not code_tags:
        raise RuntimeError("当前门店菜单里没有找到早餐餐品（可能不在供应时段）。")

    # 2) 批量算价：一次调用拿到所有餐品的名称和单价（单位：分 -> 元）
    price_map = _batch_prices(client, store.store_id, list(code_tags.keys()))

    # 3) 营养数据（CSV 风格字符串）
    nutrition = _parse_nutrition(client.call_tool("list-nutrition-foods", {}))

    # 4) 组装餐品对象
    items: List[MenuItem] = []
    for code, meta in code_tags.items():
        info = price_map.get(code)
        if not info:
            continue  # 无法计价的餐品跳过（可能已售罄）
        name, price = info
        if any(k in name for k in _NON_BREAKFAST_NAME_KEYWORDS):
            continue
        items.append(
            MenuItem(
                code=code, name=name, price=price,
                category=meta.get("category", ""), tags=meta.get("tags", []),
                is_breakfast=True,
            )
        )
    if not items:
        raise RuntimeError("早餐餐品计价失败，请稍后再试。")

    # 5) 官方套餐的营养 = 默认组成单品营养之和（只对套餐类发详情请求）
    coverage = attach_nutrition(items, nutrition)
    _fill_combo_nutrition(client, store.store_id, items, nutrition)

    # 6) 优惠券：先一键领券，再查我的券和门店券
    try:
        client.call_tool("auto-bind-coupons", {})
    except Exception:
        pass
    coupons_raw: List[dict] = []
    for tool, args in (
        ("query-my-coupons", {}),
        ("query-store-coupons", {"storeCode": store.store_id, "orderType": 1, "beType": 1}),
        ("available-coupons", {}),
    ):
        try:
            coupons_raw.extend(_extract_coupon_list(client.call_tool(tool, args)))
        except Exception:
            continue

    # 7) 活动日历
    campaigns: List[str] = []
    try:
        campaigns = _extract_campaigns(client.call_tool("campaign-calendar", {}))
    except Exception:
        pass

    breakfast_only = filter_breakfast(items)
    combos = generate_combos(
        breakfast_only, budget=budget, kcal_min=kcal_min, kcal_max=kcal_max,
        top_n=top_n,
    )
    if not combos:
        raise RuntimeError("当前门店没有可搭配的早餐餐品。")

    top = combos[0]
    coupons = parse_coupons(coupons_raw)
    coupon = pick_best_coupon(coupons, top.total_price)
    saved = effective_value(coupon, top.total_price) if coupon else 0.0
    final = max(0.0, round(top.total_price - saved, 2))

    plan = BreakfastPlan(
        store=store,
        combos=combos,
        coupon=coupon,
        original_price=top.total_price,
        final_price=final,
        saved=saved,
        campaigns=campaigns,
        pickup_hint=_make_pickup_hint(store),
    )
    plan.coverage = coverage  # type: ignore[attr-defined]
    return plan


def render_markdown(plan: BreakfastPlan, home: str = "", company: str = "") -> str:
    """生成 Markdown 方案报告。"""
    lines = [
        "# 🍔 麦麦顺路早餐方案",
        "",
        f"- 取餐门店：**{plan.store.name}**"
        + ("（真·顺路 ✅）" if plan.store.on_the_way else ""),
        f"- 门店地址：{plan.store.address or '—'}",
    ]
    if plan.store.breakfast_hours:
        lines.append(f"- 早餐供应：{plan.store.breakfast_hours}")
    if plan.store.distance_home_m is not None:
        lines.append(f"- 距住处约 {plan.store.distance_home_m:.0f} 米")
    if plan.store.distance_company_m is not None:
        lines.append(f"- 距公司约 {plan.store.distance_company_m:.0f} 米")
    lines += ["", "## 推荐搭配", ""]
    for idx, combo in enumerate(plan.combos, 1):
        names = " + ".join(i.name for i in combo.items)
        kcal = f"{combo.total_kcal:.0f} kcal" if combo.total_kcal else "热量未知"
        lines.append(
            f"{idx}. **{names}**（{combo.label}）—— ¥{combo.total_price}，"
            f"约 {kcal}，蛋白质 {combo.total_protein}g"
        )
    lines += ["", "## 价格", ""]
    lines.append(f"- 餐品原价：¥{plan.original_price:.2f}")
    if plan.coupon:
        lines.append(f"- 使用优惠券：{plan.coupon.title}（-¥{plan.saved:.2f}）")
    lines.append(f"- **预计实付：¥{plan.final_price:.2f}**")
    if plan.campaigns:
        lines += ["", "## 近期相关活动", ""]
        lines += [f"- {c}" for c in plan.campaigns]
    lines += ["", f"💡 {plan.pickup_hint}", ""]
    lines.append("> 价格与供应以麦当劳官方渠道实时结果为准。")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 演示模式内部组装
# ----------------------------------------------------------------------

def _assemble(
    home_stores: List[dict],
    company_stores: List[dict],
    meals: List[dict],
    nutrition: List[dict],
    coupons_raw: List[dict],
    campaigns: List[str],
    budget: float,
    kcal_min: float,
    kcal_max: float,
    top_n: int,
) -> BreakfastPlan:
    stores = merge_nearby_stores(home_stores, company_stores)
    store = pick_breakfast_store(stores)
    if store is None:
        raise RuntimeError("附近没有找到可用门店。")

    items = [i for i in (_parse_meal(m) for m in meals or []) if i is not None]
    coverage = attach_nutrition(items, nutrition)
    breakfast_items = filter_breakfast(items)

    combos = generate_combos(
        breakfast_items, budget=budget, kcal_min=kcal_min, kcal_max=kcal_max,
        top_n=top_n,
    )
    if not combos:
        raise RuntimeError("当前门店没有可搭配的早餐餐品。")

    top = combos[0]
    coupons = parse_coupons(coupons_raw)
    coupon = pick_best_coupon(coupons, top.total_price)
    saved = effective_value(coupon, top.total_price) if coupon else 0.0
    final = max(0.0, round(top.total_price - saved, 2))

    plan = BreakfastPlan(
        store=store,
        combos=combos,
        coupon=coupon,
        original_price=top.total_price,
        final_price=final,
        saved=saved,
        campaigns=campaigns,
        pickup_hint=_make_pickup_hint(store),
    )
    plan.coverage = coverage  # type: ignore[attr-defined]
    return plan


# ----------------------------------------------------------------------
# MCP 真实数据解析
# ----------------------------------------------------------------------

def _query_stores(client, address: str) -> List[dict]:
    """按地址查询附近门店（自动从地址里拆城市和关键词）。"""
    city, keyword = _split_address(address)
    result = client.call_tool(
        "query-nearby-stores",
        {"beType": 1, "city": city, "keyword": keyword, "searchType": 2},
    )
    return _as_list((result or {}).get("data") if isinstance(result, dict) else result)


def _split_address(address: str) -> Tuple[str, str]:
    """把 '北京市朝阳区望京SOHO' 拆成 ('北京', '望京SOHO')。"""
    address = address.strip()
    city = ""
    match = re.match(r"^(.+?市)", address)
    if match:
        city = match.group(1)[:-1]  # 去掉「市」
    keyword = address
    parts = re.split(r"[市区县]", address)
    parts = [p for p in parts if p]
    if parts:
        keyword = parts[-1]
    return city, keyword or address


def _extract_breakfast_codes(meals_result) -> Dict[str, dict]:
    """从 query-meals 结果中挑出早餐相关分类下的餐品 code。"""
    data = (meals_result or {}).get("data") if isinstance(meals_result, dict) else None
    categories = (data or {}).get("categories") or []
    result: Dict[str, dict] = {}
    for cat in categories:
        cat_name = str(cat.get("name") or "").replace("\n", "")
        is_breakfast_cat = any(k in cat_name for k in _BREAKFAST_CATEGORY_KEYWORDS)
        for meal in cat.get("meals") or []:
            code = str(meal.get("code") or "")
            if not code:
                continue
            tags = [str(t) for t in (meal.get("tags") or [])]
            tag_breakfast = any("早餐" in t for t in tags)
            if is_breakfast_cat or tag_breakfast:
                result[code] = {"category": cat_name, "tags": tags}
    return result


def _batch_prices(client, store_code: str, codes: List[str]) -> Dict[str, Tuple[str, float]]:
    """批量计算餐品价格，返回 {code: (名称, 单价元)}。

    calculate-price 一次可传多个商品；为稳妥每批最多 25 个。
    """
    price_map: Dict[str, Tuple[str, float]] = {}
    for start in range(0, len(codes), 25):
        batch = codes[start:start + 25]
        items = [{"productCode": code, "quantity": 1} for code in batch]
        try:
            result = client.call_tool(
                "calculate-price",
                {"storeCode": store_code, "orderType": 1, "beType": 1, "items": items},
            )
        except Exception:
            continue
        data = (result or {}).get("data") if isinstance(result, dict) else None
        for product in (data or {}).get("productList") or []:
            code = str(product.get("productCode") or "")
            name = str(product.get("productName") or code)
            subtotal = product.get("subtotal")
            try:
                price = round(float(subtotal) / 100.0, 2)  # 单位：分 -> 元
            except (TypeError, ValueError):
                continue
            if code:
                price_map[code] = (name, price)
    return price_map


def _parse_nutrition(result) -> List[dict]:
    """解析 list-nutrition-foods 返回的 CSV 风格字符串。

    格式：[N]{productName,nutritionDescription,energyKj,energyKcal,protein,
    fat,carbohydrate,sodium,calcium}:\n  行1\n  行2...
    """
    data = (result or {}).get("data") if isinstance(result, dict) else result
    if isinstance(data, list):
        return data
    if not isinstance(data, str):
        return []
    rows: List[dict] = []
    header: List[str] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        header_match = re.search(r"\{([^}]+)\}", line)
        if header_match:
            header = [h.strip() for h in header_match.group(1).split(",")]
            continue
        if not header or line.startswith("["):
            continue
        values = [v.strip() for v in line.split(",")]
        if len(values) < len(header):
            continue
        row = dict(zip(header, values))
        row["name"] = row.get("productName", "")
        rows.append(row)
    return rows


def _fill_combo_nutrition(client, store_code: str, items: List[MenuItem],
                          nutrition: List[dict]) -> None:
    """为没有营养数据的官方套餐补充营养：取默认组成单品的营养之和。"""
    from .planner import is_prebuilt_combo

    table = {str(r.get("name") or ""): r for r in nutrition or [] if r.get("name")}
    for item in items:
        if not is_prebuilt_combo(item) or item.kcal is not None:
            continue
        try:
            detail = client.call_tool(
                "query-meal-detail",
                {"storeCode": store_code, "orderType": 1, "beType": 1, "code": item.code},
            )
        except Exception:
            continue
        data = (detail or {}).get("data") if isinstance(detail, dict) else None
        if not data:
            continue
        kcal = protein = fat = carbs = sodium = 0.0
        found = False
        for round_group in data.get("rounds") or []:
            choice = _default_choice(round_group)
            if not choice:
                continue
            row = table.get(str(choice.get("name") or ""))
            if not row:
                continue
            found = True
            kcal += _f(row.get("energyKcal"))
            protein += _f(row.get("protein"))
            fat += _f(row.get("fat"))
            carbs += _f(row.get("carbohydrate"))
            sodium += _f(row.get("sodium"))
        if found:
            item.kcal = kcal
            item.protein_g = round(protein, 1)
            item.fat_g = round(fat, 1)
            item.carbs_g = round(carbs, 1)
            item.sodium_mg = sodium


def _default_choice(round_group: dict) -> Optional[dict]:
    """取套餐某一轮的默认选项。"""
    choices = round_group.get("choices") or []
    for choice in choices:
        if choice.get("isDefault"):
            return choice
    return choices[0] if choices else None


def _extract_coupon_list(result) -> List[dict]:
    data = (result or {}).get("data") if isinstance(result, dict) else result
    if isinstance(data, dict):
        for key in ("coupons", "list", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data] if data else []
    if isinstance(data, list):
        return data
    return []


def _extract_campaigns(calendar) -> List[str]:
    """从活动日历里挑出与早餐/优惠相关的活动，剔除往期。"""
    data = (calendar or {}).get("data") if isinstance(calendar, dict) else calendar
    daily_list = (data or {}).get("dailyList") if isinstance(data, dict) else data
    result: List[str] = []
    keywords = ("早餐", "麦满分", "优惠", "券", "会员", "早餐卡", "咖啡")
    for day in daily_list or []:
        date_text = str(day.get("dateText") or "") if isinstance(day, dict) else ""
        if "往期" in date_text:
            continue
        events = day.get("events") if isinstance(day, dict) else None
        if events is None and isinstance(day, dict):  # 兼容演示样本的扁平结构
            events = [day]
        for event in events or []:
            title = str(
                event.get("activityTitle")
                or (event.get("articleDto") or {}).get("title")
                or event.get("title")
                or event.get("name")
                or ""
            ).strip()
            status = str(event.get("status") or "")
            if status and status not in ("进行中", "ongoing", "ACTIVE", "active"):
                continue
            if title and any(k in title for k in keywords) and title not in result:
                result.append(title)
    return result[:5]


def _make_pickup_hint(store: Store) -> str:
    hours = f"早餐供应时段 {store.breakfast_hours}，" if store.breakfast_hours else ""
    if store.supports_reservation:
        return (
            f"{hours}该门店支持预约下单：出门前在麦当劳 App 下预约单，"
            "到店出示取餐码即取，全程不排队，顺路拿了就走。"
        )
    if store.supports_locker:
        return (
            f"{hours}该门店支持取餐柜：提前下单，到店扫取餐柜二维码即取，不用排队。"
        )
    if store.on_the_way:
        return f"{hours}门店正好在通勤路上，建议提前 10 分钟下单，到店即取。"
    return f"{hours}这是离公司最近的门店，建议提前下单预约到店自取，避开早高峰。"


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------

def _load_sample(filename: str) -> list:
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _as_list(data) -> List[dict]:
    """MCP 返回结构各异，尽力提取列表。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "items", "data", "stores", "meals", "coupons", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def _parse_meal(raw: dict) -> Optional[MenuItem]:
    """解析演示模式样本中的餐品。"""
    code = str(raw.get("code") or raw.get("mealCode") or raw.get("id") or "")
    name = str(raw.get("name") or raw.get("mealName") or "")
    if not name:
        return None
    price = raw.get("price") or raw.get("salePrice") or 0
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0
    category = str(raw.get("category") or raw.get("categoryName") or "")
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    is_breakfast = bool(
        raw.get("isBreakfast")
        or "早餐" in category
        or any("早餐" in str(t) for t in tags)
    )
    return MenuItem(
        code=code or name, name=name, price=price, category=category,
        tags=list(tags), is_breakfast=is_breakfast,
    )


def _f(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
