"""数据模型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Store:
    """麦当劳门店。"""

    store_id: str
    name: str
    address: str = ""
    distance_home_m: Optional[float] = None      # 距住处（米）
    distance_company_m: Optional[float] = None   # 距公司（米）
    on_the_way: bool = False                     # 是否同时在住处与公司附近（真·顺路）
    supports_locker: bool = False                # 是否支持取餐柜
    supports_reservation: bool = False           # 是否支持预约下单
    breakfast_hours: str = ""                    # 早餐供应时段，如 "06:44至10:15"

    @property
    def detour_score(self) -> float:
        """绕行代价：距两边距离之和，越小越顺路。缺失值按 2000 米计。"""
        home = self.distance_home_m if self.distance_home_m is not None else 2000.0
        company = (
            self.distance_company_m if self.distance_company_m is not None else 2000.0
        )
        return home + company


@dataclass
class MenuItem:
    """餐品。"""

    code: str
    name: str
    price: float
    category: str = ""
    tags: List[str] = field(default_factory=list)
    is_breakfast: bool = False
    # 营养信息（每份）
    kcal: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carbs_g: Optional[float] = None
    sodium_mg: Optional[float] = None


@dataclass
class Combo:
    """一份早餐搭配。"""

    items: List[MenuItem]
    label: str = ""

    @property
    def total_price(self) -> float:
        return round(sum(i.price for i in self.items), 2)

    @property
    def total_kcal(self) -> float:
        return sum(i.kcal or 0 for i in self.items)

    @property
    def total_protein(self) -> float:
        return round(sum(i.protein_g or 0 for i in self.items), 1)


@dataclass
class Coupon:
    """优惠券。"""

    coupon_id: str
    title: str
    discount_desc: str = ""
    threshold: float = 0.0        # 使用门槛（元）
    value: float = 0.0            # 立减面额（元）
    expires: str = ""
    discount_rate: float = 0.0    # 折扣率（如 0.8 表示 8 折），0 表示非折扣券


@dataclass
class BreakfastPlan:
    """最终早餐方案。"""

    store: Store
    combos: List[Combo]                # 推荐搭配（按评分降序）
    coupon: Optional[Coupon] = None
    original_price: float = 0.0
    final_price: float = 0.0
    saved: float = 0.0
    campaigns: List[str] = field(default_factory=list)   # 进行中的相关活动
    pickup_hint: str = ""              # 取餐建议文案
