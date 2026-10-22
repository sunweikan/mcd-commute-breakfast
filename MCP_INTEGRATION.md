# MCP 集成说明

本项目基于**麦当劳中国官方 MCP Server**（`https://mcp.mcd.cn`，Streamable HTTP 协议）开发，
认证方式为请求头携带 `Authorization: Bearer <MCP_TOKEN>`（Token 通过环境变量 `MCD_MCP_TOKEN` 注入，不落盘、不进仓库）。

## 实际使用的 MCP Server 与 Tool

| MCP Tool | 用途 | 调用时机 |
|---|---|---|
| `query-nearby-stores` | 分别查询住处、公司附近的门店（`beType=1` 到店自提，`searchType=2` 按位置搜索） | 第 1 步，调用 2 次 |
| `query-meals` | 获取选中门店当前可售菜单的分类与餐品 code | 第 2 步 |
| `calculate-price` | 批量计算全部早餐候选餐品的名称与单价（分→元），并为最终方案核价 | 第 3 步 |
| `list-nutrition-foods` | 获取麦当劳餐品营养成分表（能量/蛋白质/脂肪/碳水/钠/钙） | 第 3 步 |
| `query-meal-detail` | 查询官方套餐（二件套/三件套）的默认组成单品，用于估算套餐营养 | 第 4 步（仅套餐类餐品） |
| `auto-bind-coupons` | 麦麦省一键领券，先把能领的券都领了 | 第 5 步 |
| `query-my-coupons` | 查询用户账户下已有优惠券 | 第 5 步 |
| `query-store-coupons` | 查询当前门店可用优惠券 | 第 5 步 |
| `available-coupons` | 查询麦麦省可领取优惠券列表 | 第 5 步 |
| `campaign-calendar` | 查询当月营销活动日历，挑出与早餐/优惠相关的进行中活动 | 第 6 步 |

共使用 **10 个 MCP Tool**，覆盖门店、菜单、价格、营养、优惠、活动六大域。

## 调用流程

```
用户输入：住处地址 + 公司地址 + 预算 + 热量目标
        │
        ▼
① query-nearby-stores(住处) ──┐
                              ├─► 门店交集：两边都出现的店 = 真·顺路
② query-nearby-stores(公司) ──┘    无交集则取绕行代价（距离之和）最小者
        │
        ▼
③ query-meals(storeCode) ──► 按分类名/标签筛出早餐餐品 code
        │
        ▼
④ calculate-price(批量) ──► 拿到每个 code 的名称与单价
   list-nutrition-foods ──► 解析 CSV 风格营养表，按名称挂到餐品上
   query-meal-detail(仅套餐) ──► 套餐营养 = 默认组成单品营养之和
        │
        ▼
⑤ auto-bind-coupons → query-my-coupons / query-store-coupons / available-coupons
   ──► 为 Top1 搭配挑最优券（折扣券按实际订单金额折算，立减券不超订单金额）
        │
        ▼
⑥ campaign-calendar ──► 过滤往期活动，挑出早餐/优惠相关的进行中活动
        │
        ▼
输出：Markdown 方案报告 + 单文件 HTML 早餐卡
```

## 业务价值

- **场景真实**：通勤顺路买早餐是高频刚需；门店「早餐供应时段」「预约下单」能力均来自 MCP 真实返回。
- **数据真实**：菜单、价格、营养、优惠券、活动全部来自 MCP 实时数据，不写死。
- **决策闭环**：从「在哪买」→「吃什么」→「多少钱」→「怎么取」一次跑通；支付环节由用户在官方 App 完成，安全边界清晰。

## 容错与限流设计

- MCP 调用频率远低于 600 次/分钟的限额（单次完整运行约 10–15 次调用）。
- 券查询、活动日历等非关键链路全部 `try/except` 降级，任一失败不影响主流程。
- 401/429 错误有明确的中文提示。
- 批量计价每批最多 25 个商品，避免超长请求。

## 演示模式

为方便没有 MCP Token 的开发者体验，`--demo` 模式使用 `data/` 目录下的样本数据
（数据结构按 2026-10-22 真实 MCP 返回编写），可完整跑通门店匹配、搭配、优惠、出卡全流程。
