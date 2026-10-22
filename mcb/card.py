"""生成可截图分享的单文件 HTML 早餐卡。"""

from __future__ import annotations

import datetime
import html
from typing import Optional

from .models import BreakfastPlan

_CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦麦顺路早餐卡</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f7f3ea; display: flex; justify-content: center;
    padding: 24px 12px; color: #33302a;
  }}
  .card {{
    width: 420px; background: #fffdf7; border-radius: 20px;
    box-shadow: 0 8px 30px rgba(120, 80, 20, .12); overflow: hidden;
  }}
  .head {{
    background: linear-gradient(135deg, #ffc72c, #ffb200);
    padding: 22px 24px 18px;
  }}
  .head h1 {{ font-size: 20px; color: #5b3a00; }}
  .head .sub {{ font-size: 12px; color: #7a5200; margin-top: 4px; }}
  .store {{ padding: 14px 24px; border-bottom: 1px dashed #e8ddc4; font-size: 13px; }}
  .store b {{ color: #c00; }}
  .store .badge {{
    display: inline-block; background: #c00; color: #fff; border-radius: 4px;
    font-size: 11px; padding: 1px 6px; margin-left: 6px;
  }}
  .combo {{ padding: 14px 24px; border-bottom: 1px dashed #e8ddc4; }}
  .combo .label {{ font-size: 11px; color: #b8860b; margin-bottom: 6px; }}
  .combo .name {{ font-size: 15px; font-weight: 600; margin-bottom: 4px; }}
  .combo .meta {{ font-size: 12px; color: #8a7d5f; }}
  .combo .meta span {{ margin-right: 12px; }}
  .price {{ padding: 16px 24px; background: #fff8e6; }}
  .price .row {{ display: flex; justify-content: space-between; font-size: 13px; margin: 3px 0; }}
  .price .final {{ font-size: 18px; font-weight: 700; color: #c00; }}
  .hint {{ padding: 12px 24px; font-size: 12px; color: #6b5d3f; line-height: 1.7; }}
  .foot {{
    padding: 10px 24px 16px; font-size: 11px; color: #b3a680; text-align: center;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="head">
    <h1>🍔 麦麦顺路早餐卡</h1>
    <div class="sub">{date} · 通勤早餐，顺路不绕路</div>
  </div>
  <div class="store">
    取餐门店：<b>{store_name}</b>{store_badges}<br>
    <span style="color:#8a7d5f">{store_addr}{distance_line}</span>
  </div>
  {combos_html}
  <div class="price">
    <div class="row"><span>餐品原价</span><span>¥{original_price}</span></div>
    {coupon_row}
    <div class="row final"><span>预计实付</span><span>¥{final_price}</span></div>
  </div>
  <div class="hint">💡 {pickup_hint}</div>
  <div class="foot">由 mcd-commute-breakfast 生成 · 价格与供应以麦当劳官方渠道为准</div>
</div>
</body>
</html>
"""


def render_card(plan: BreakfastPlan, out_path: str, date: Optional[str] = None) -> str:
    """把早餐方案渲染成 HTML 卡片并写入文件，返回文件路径。"""
    date = date or datetime.date.today().isoformat()

    combos_html = []
    for combo in plan.combos:
        names = " + ".join(html.escape(i.name) for i in combo.items)
        kcal = f"{combo.total_kcal:.0f} kcal" if combo.total_kcal else "热量未知"
        protein = (
            f"{combo.total_protein:.0f}g 蛋白质" if combo.total_protein else ""
        )
        combos_html.append(
            f"""  <div class="combo">
    <div class="label">{html.escape(combo.label)}</div>
    <div class="name">{names}</div>
    <div class="meta"><span>🔥 {kcal}</span><span>💪 {protein}</span><span>¥{combo.total_price}</span></div>
  </div>"""
        )

    store = plan.store
    badges = ""
    if store.on_the_way:
        badges += '<span class="badge">真·顺路</span>'
    if store.supports_locker:
        badges += '<span class="badge" style="background:#2a7d2a">取餐柜</span>'

    distance_parts = []
    if store.distance_home_m is not None:
        distance_parts.append(f"距住处 {store.distance_home_m:.0f}m")
    if store.distance_company_m is not None:
        distance_parts.append(f"距公司 {store.distance_company_m:.0f}m")
    distance_line = (" · " + " · ".join(distance_parts)) if distance_parts else ""

    if plan.coupon:
        coupon_row = (
            f'<div class="row"><span>优惠券：{html.escape(plan.coupon.title)}</span>'
            f"<span>-¥{plan.saved:.2f}</span></div>"
        )
    else:
        coupon_row = ""

    page = _CARD_TEMPLATE.format(
        date=html.escape(date),
        store_name=html.escape(store.name),
        store_addr=html.escape(store.address or ""),
        store_badges=badges,
        distance_line=html.escape(distance_line),
        combos_html="\n".join(combos_html),
        original_price=f"{plan.original_price:.2f}",
        coupon_row=coupon_row,
        final_price=f"{plan.final_price:.2f}",
        pickup_hint=html.escape(plan.pickup_hint or "到店出示取餐码即可取餐。"),
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path
