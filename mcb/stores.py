"""顺路门店匹配逻辑。

思路：
- 分别查询「住处附近」与「公司附近」的门店列表
- 同一家门店同时出现在两个列表里 => 它真的在通勤路上（真·顺路）
- 没有交集时，退而求其次选离公司最近的门店（下班后/午高峰也方便）

评分 = 绕行代价（距住处距离 + 距公司距离），越小越好。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .models import Store


def merge_nearby_stores(
    home_stores: Iterable[dict], company_stores: Iterable[dict]
) -> List[Store]:
    """合并两个「附近门店」列表，标记顺路门店并计算绕行代价。

    输入为 MCP query-nearby-stores 返回的原始字典列表。
    已停业（businessStatus=False）的门店会被剔除。
    """
    merged: Dict[str, Store] = {}
    home_stores = [s for s in (home_stores or []) if s.get("businessStatus", True)]
    company_stores = [s for s in (company_stores or []) if s.get("businessStatus", True)]

    def _parse(raw: dict, key: str) -> Optional[Store]:
        store_id = str(
            raw.get("storeCode") or raw.get("storeId") or raw.get("id") or ""
        )
        if not store_id:
            return None
        store = merged.get(store_id)
        if store is None:
            store = Store(
                store_id=store_id,
                name=str(raw.get("storeName") or raw.get("name") or store_id),
                address=str(raw.get("address") or ""),
                supports_locker=bool(
                    raw.get("supportsLocker") or raw.get("locker") or False
                ),
                supports_reservation=bool(raw.get("reservation") or False),
                breakfast_hours=_extract_breakfast_hours(raw),
            )
            merged[store_id] = store
        distance = raw.get("distance") or raw.get("distanceM")
        if distance is not None:
            try:
                setattr(store, key, float(distance))
            except (TypeError, ValueError):
                pass
        return store

    for raw in home_stores or []:
        _parse(raw, "distance_home_m")
    for raw in company_stores or []:
        _parse(raw, "distance_company_m")

    # 真·顺路：两边都出现
    for store in merged.values():
        if store.distance_home_m is not None and store.distance_company_m is not None:
            store.on_the_way = True

    return sorted(merged.values(), key=lambda s: s.detour_score)


def pick_breakfast_store(stores: List[Store]) -> Optional[Store]:
    """选出最适合买早餐的门店。

    优先「真·顺路」，其中支持预约/取餐柜的门店加分（早上不用排队）；
    无顺路门店时取绕行代价最小者。
    """
    if not stores:
        return None

    def rank(store: Store) -> tuple:
        convenient = store.supports_locker or store.supports_reservation
        return (
            0 if store.on_the_way else 1,
            0 if convenient else 1,
            store.detour_score,
        )

    return min(stores, key=rank)


def _extract_breakfast_hours(raw: dict) -> str:
    """从预约时段文案里提取早餐供应时间，如 '早餐(06:44至10:15)' -> '06:44-10:15'。"""
    import re

    for option in raw.get("reservationTimeOptions") or []:
        text = str(option.get("reservationOptionText") or "")
        match = re.search(r"早餐\((\d{1,2}:\d{2})至(\d{1,2}:\d{2})\)", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return ""
