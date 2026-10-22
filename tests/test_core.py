"""核心逻辑单元测试：门店匹配 / 搭配生成 / 优惠券 / 营养解析。

运行：python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcb.coupons import effective_value, parse_coupons, pick_best_coupon
from mcb.models import Combo, MenuItem, Store
from mcb.planner import (
    attach_nutrition,
    classify,
    filter_breakfast,
    generate_combos,
    is_prebuilt_combo,
    score_combo,
)
from mcb.service import (
    _extract_breakfast_codes,
    _extract_campaigns,
    _parse_nutrition,
    _split_address,
    build_plan_demo,
    render_markdown,
)
from mcb.stores import merge_nearby_stores, pick_breakfast_store


def _item(name, price, kcal=None, protein=None, tags=None, category=""):
    return MenuItem(
        code=name, name=name, price=price, kcal=kcal, protein_g=protein,
        tags=tags or [], category=category,
    )


class TestStores(unittest.TestCase):
    def test_on_the_way_intersection(self):
        home = [{"storeCode": "A", "storeName": "甲", "distance": 300},
                {"storeCode": "B", "storeName": "乙", "distance": 100}]
        company = [{"storeCode": "B", "storeName": "乙", "distance": 200},
                   {"storeCode": "C", "storeName": "丙", "distance": 50}]
        stores = merge_nearby_stores(home, company)
        by_id = {s.store_id: s for s in stores}
        self.assertTrue(by_id["B"].on_the_way)
        self.assertFalse(by_id["A"].on_the_way)
        self.assertFalse(by_id["C"].on_the_way)

    def test_closed_store_filtered(self):
        home = [{"storeCode": "A", "storeName": "甲", "distance": 100,
                 "businessStatus": False}]
        self.assertEqual(merge_nearby_stores(home, []), [])

    def test_pick_prefers_on_the_way(self):
        home = [{"storeCode": "A", "storeName": "甲", "distance": 10}]
        company = [{"storeCode": "B", "storeName": "乙", "distance": 10,
                    "reservation": True}]
        stores = merge_nearby_stores(home, company)
        picked = pick_breakfast_store(stores)
        # A 绕行 2010m（公司侧未知），B 绕行 2010m；都无交集时取绕行最小
        self.assertIsNotNone(picked)

    def test_breakfast_hours_extracted(self):
        raw = [{
            "storeCode": "A", "storeName": "甲", "distance": 100,
            "reservationTimeOptions": [
                {"reservationOptionText": "早餐(06:44至10:15)，午餐(10:44至14:15)"}
            ],
        }]
        stores = merge_nearby_stores(raw, [])
        self.assertEqual(stores[0].breakfast_hours, "06:44-10:15")


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.items = [
            _item("猪柳蛋麦满分", 9.5, 320, 15, category="早餐"),
            _item("烟肉蛋麦满分", 10.5, 350, 16, category="早餐"),
            _item("优品豆浆", 5.0, 90, 5, category="早餐"),
            _item("鲜煮咖啡", 6.5, 5, 0.3, category="早餐"),
            _item("脆薯饼", 6.0, 150, 1.5, category="早餐"),
            _item("巨无霸", 24.0, 550, 26, category="汉堡"),
        ]

    def test_classify(self):
        self.assertEqual(classify(_item("猪柳蛋麦满分", 9.5)), "staple")
        self.assertEqual(classify(_item("优品豆浆", 5.0)), "drink")
        self.assertEqual(classify(_item("脆薯饼", 6.0)), "snack")

    def test_filter_breakfast_excludes_bigmac(self):
        result = filter_breakfast(self.items)
        names = [i.name for i in result]
        self.assertNotIn("巨无霸", names)

    def test_prebuilt_combo_detected(self):
        combo_item = _item("芝芝火腿扒堡组合", 9.9, tags=["二件套"])
        self.assertTrue(is_prebuilt_combo(combo_item))
        self.assertFalse(is_prebuilt_combo(_item("猪柳蛋麦满分", 9.5)))

    def test_generate_combos_respects_budget(self):
        combos = generate_combos(self.items, budget=12.0, top_n=5)
        self.assertTrue(combos)
        for combo in combos:
            self.assertLessEqual(combo.total_price, 12.0 * 1.15)

    def test_complete_breakfast_scores_higher(self):
        lone = Combo(items=[_item("猪柳蛋麦满分", 9.5, 320, 15)])
        full = Combo(items=[_item("猪柳蛋麦满分", 9.5, 320, 15),
                            _item("优品豆浆", 5.0, 90, 5)])
        self.assertGreater(
            score_combo(full, 15, 300, 650), score_combo(lone, 15, 300, 650)
        )

    def test_top_combos_are_diverse(self):
        items = self.items + [
            _item("猪柳蛋麦满分组合", 13.0, 400, 18, tags=["二件套"]),
        ]
        combos = generate_combos(items, budget=20.0, top_n=3)
        keys = [c.items[0].name.replace("组合", "") for c in combos]
        self.assertEqual(len(keys), len(set(keys)))

    def test_attach_nutrition_fuzzy(self):
        rows = [{"name": "猪柳蛋麦满分", "energyKcal": 387, "protein": 23}]
        matched = attach_nutrition(self.items, rows)
        self.assertEqual(matched, 1)


class TestCoupons(unittest.TestCase):
    def test_threshold_filter(self):
        coupons = parse_coupons([
            {"title": "满30减8", "couponId": "1"},
            {"title": "满15减3", "couponId": "2"},
        ])
        # 13.5 元两张券都不满足门槛
        self.assertIsNone(pick_best_coupon(coupons, 13.5))
        # 16 元只有满15减3可用
        self.assertEqual(pick_best_coupon(coupons, 16.0).coupon_id, "2")
        # 35 元选减免更大的满30减8
        self.assertEqual(pick_best_coupon(coupons, 35.0).coupon_id, "1")

    def test_discount_rate_on_order_amount(self):
        coupons = parse_coupons([{"title": "麦满分单品8折券", "couponId": "9"}])
        best = pick_best_coupon(coupons, 13.5)
        self.assertAlmostEqual(effective_value(best, 13.5), 2.7)

    def test_value_capped_by_order(self):
        coupons = parse_coupons([{"title": "立减20元", "couponId": "3"}])
        best = pick_best_coupon(coupons, 9.5)
        self.assertEqual(effective_value(best, 9.5), 9.5)

    def test_no_coupon_returns_none(self):
        self.assertIsNone(pick_best_coupon([], 10.0))


class TestParsing(unittest.TestCase):
    def test_split_address(self):
        city, keyword = _split_address("北京市朝阳区望京SOHO")
        self.assertEqual(city, "北京")
        self.assertEqual(keyword, "望京SOHO")

    def test_split_address_no_city(self):
        city, keyword = _split_address("望京SOHO")
        self.assertEqual(city, "")
        self.assertEqual(keyword, "望京SOHO")

    def test_parse_nutrition_csv_format(self):
        fake = {"data": "[2]{productName,nutritionDescription,energyKj,energyKcal,"
                        "protein,fat,carbohydrate,sodium,calcium}:\n"
                        "  猪柳麦满分,null,1288,308,16,16,24,781,213\n"
                        "  脆薯饼,null,600,150,1.5,9,16,290,10"}
        rows = _parse_nutrition(fake)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "猪柳麦满分")
        self.assertEqual(rows[0]["energyKcal"], "308")

    def test_extract_breakfast_codes(self):
        result = {"data": {"categories": [
            {"name": "超值早餐", "meals": [{"code": "1", "tags": []}]},
            {"name": "汉堡", "meals": [{"code": "2", "tags": []}]},
            {"name": "小食", "meals": [{"code": "3", "tags": ["早餐卡专享价"]}]},
        ]}}
        codes = _extract_breakfast_codes(result)
        self.assertIn("1", codes)
        self.assertIn("3", codes)
        self.assertNotIn("2", codes)

    def test_extract_campaigns_filters_history(self):
        calendar = {"data": {"dailyList": [
            {"dateText": "2026年10月20日 往期回顾",
             "events": [{"articleDto": {"title": "早餐活动-往期"}}]},
            {"dateText": "2026年10月22日 今日",
             "events": [{"articleDto": {"title": "早餐爆款回归"}},
                        {"articleDto": {"title": "无关活动XYZ"}}]},
        ]}}
        campaigns = _extract_campaigns(calendar)
        self.assertEqual(campaigns, ["早餐爆款回归"])


class TestEndToEndDemo(unittest.TestCase):
    def test_demo_plan(self):
        plan = build_plan_demo()
        self.assertTrue(plan.combos)
        self.assertGreater(plan.original_price, 0)
        self.assertLessEqual(plan.final_price, plan.original_price)
        md = render_markdown(plan)
        self.assertIn("麦麦顺路早餐方案", md)
        self.assertIn(plan.store.name, md)


if __name__ == "__main__":
    unittest.main()
