"""优惠券选择逻辑。

麦当劳早餐券通常不多，用贪心策略即可：
1. 过滤掉门槛高于订单金额的券
2. 在可用券里选预估减免最大的一张
（多数场景下同一张订单只能用一张券，故不做组合爆炸搜索）
"""

from __future__ import annotations

import re
from typing import List, Optional

from .models import Coupon


def parse_coupons(raw_list: List[dict]) -> List[Coupon]:
    """把 MCP 返回的券列表解析为 Coupon 对象。"""
    coupons: List[Coupon] = []
    for raw in raw_list or []:
        title = str(raw.get("title") or raw.get("couponName") or raw.get("name") or "")
        coupon_id = str(raw.get("couponId") or raw.get("id") or title)
        desc = str(raw.get("description") or raw.get("desc") or "")
        threshold = _extract_threshold(title + " " + desc)
        value = _extract_value(raw, title + " " + desc)
        expires = str(raw.get("validEndTime") or raw.get("expireTime") or "")
        coupons.append(
            Coupon(
                coupon_id=coupon_id,
                title=title,
                discount_desc=desc,
                threshold=threshold,
                value=value,
                expires=expires,
                discount_rate=_extract_discount_rate(title + " " + desc),
            )
        )
    return coupons


def effective_value(coupon: Coupon, order_amount: float) -> float:
    """一张券对给定订单的实际减免金额。

    - 立减券：直接取面额，但不超过订单金额
    - 折扣券：按订单金额 × (1 - 折扣) 计算
    """
    if coupon.discount_rate and 0 < coupon.discount_rate < 1:
        return round(order_amount * (1 - coupon.discount_rate), 2)
    return min(coupon.value, order_amount)


def pick_best_coupon(coupons: List[Coupon], order_amount: float) -> Optional[Coupon]:
    """为给定订单金额挑选最优券。"""
    usable = [
        c
        for c in coupons
        if c.threshold <= order_amount and effective_value(c, order_amount) > 0
    ]
    if not usable:
        return None
    return max(usable, key=lambda c: effective_value(c, order_amount))


def _extract_threshold(text: str) -> float:
    """从「满 20 减 5」类文案中提取门槛金额。"""
    match = re.search(r"满\s*(\d+(?:\.\d+)?)\s*元?", text)
    return float(match.group(1)) if match else 0.0


def _extract_value(raw: dict, text: str) -> float:
    """优先取结构化字段，其次从文案解析「减 X 元」。"""
    for key in ("discountAmount", "denomination", "value", "amount"):
        value = raw.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    match = re.search(r"减\s*(\d+(?:\.\d+)?)\s*元?", text)
    if match:
        return float(match.group(1))
    return 0.0


def _extract_discount_rate(text: str) -> float:
    """从「8 折 / 85 折」类文案中解析折扣率，无折扣返回 0。"""
    match = re.search(r"(\d(?:\.\d)?)\s*折", text)
    if not match:
        return 0.0
    digits = match.group(1)
    rate = float(digits) / 10.0 if float(digits) < 10 else float(digits) / 100.0
    return rate if 0 < rate < 1 else 0.0
