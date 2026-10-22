# 🍔 麦麦顺路早餐管家（mcd-commute-breakfast）

> 1024 程序员节 · 麦当劳程序员创意开发大赛参赛作品
> 输入住处和公司，帮你找到**通勤路上**的麦当劳门店，按预算和营养目标搭配好早餐、算清优惠——每天早上顺路拿了就走。

## 它解决什么问题？

打工人的早餐日常是：想多睡 10 分钟，又不想排队买早餐。

这个 Skill 做的是一件小事，但做得很完整：

1. **顺路门店匹配**：分别查询住处和公司附近的麦当劳，同一家店同时出现在两边 = 真·顺路；没有交集就取绕行代价最小的门店。
2. **早餐科学搭配**：读取门店当前可售早餐，按你的预算（默认 ¥15）和热量目标（默认 300–650 kcal），用「热量贴合度 + 蛋白质密度 + 预算贴合度 + 钠含量惩罚」打分，给出 Top 3 搭配（主食+饮品，或直接推荐官方套餐）。
3. **优惠自动算**：先调 `auto-bind-coupons` 一键领券，再汇总我的券 + 门店券 + 可领券，为推荐搭配挑出最划算的一张。
4. **早餐卡分享**：生成一张单文件 HTML 早餐卡，截图就能发朋友圈/群里安利同事。

## 快速开始

**零依赖，Python 3.9+ 即可。**

### 演示模式（无需 Token，30 秒体验）

```bash
python -m mcb.cli --demo
```

### 真实模式（接入你自己的麦当劳账号）

1. 到 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 手机号登录，控制台激活领取 MCP Token（免费）。
2. 设置环境变量：

```bash
# Windows (cmd)
set MCD_MCP_TOKEN=你的Token
# Windows (PowerShell)
$env:MCD_MCP_TOKEN="你的Token"
# macOS / Linux
export MCD_MCP_TOKEN=你的Token
```

3. 运行：

```bash
python -m mcb.cli --home "北京市朝阳区xx小区" --company "北京市海淀区xx大厦" --budget 15
```

输出：
- 终端打印 Markdown 早餐方案
- `breakfast_card.html`：可截图分享的早餐卡
- `breakfast_plan.md`：完整方案报告

### 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--home` | 住处地址（真实模式必填） | — |
| `--company` | 公司地址（真实模式必填） | — |
| `--budget` | 早餐预算（元） | 15 |
| `--kcal-min` / `--kcal-max` | 热量目标区间 | 300 / 650 |
| `--top` | 推荐搭配数量 | 3 |
| `--demo` | 演示模式，用内置样本数据 | 关 |
| `--card` / `--md` | 输出文件路径 | breakfast_card.html / breakfast_plan.md |

## 演示效果

真实模式实测输出（2026-10-22，北京）：

```
- 取餐门店：麦当劳北京阜安西路餐厅（距住处约 167 米）
- 早餐供应：07:14-10:15

1. 大脆鸡扒麦满分组合（官方套餐 · 热量适中）—— ¥13.5，约 361 kcal
2. 猪柳麦满分组合（官方套餐 · 热量适中）—— ¥17.0，约 308 kcal
3. 烟肉蛋麦满分 + 优品豆浆（高蛋白 · 热量适中）—— ¥15.5，约 350 kcal

💡 该门店支持预约下单：出门前在 App 下预约单，到店出示取餐码即取。
```

## 项目结构

```
mcd-commute-breakfast/
├── mcb/
│   ├── mcp_client.py   # 极简 MCP Streamable HTTP 客户端（纯标准库）
│   ├── models.py       # 数据模型
│   ├── stores.py       # 顺路门店匹配（住处∩公司）
│   ├── planner.py      # 早餐搭配引擎（打分 + 去重 + 套餐识别）
│   ├── coupons.py      # 优惠券解析与最优选择
│   ├── card.py         # 单文件 HTML 早餐卡生成
│   ├── service.py      # MCP 调用编排 + 真实数据结构解析
│   └── cli.py          # 命令行入口
├── data/               # 演示模式样本数据
├── tests/              # 21 个单元测试（python -m unittest discover -s tests）
├── examples/           # 演示输出样例
├── MCP_INTEGRATION.md  # MCP 集成说明
├── CONTEST_DECLARATION.md  # 参赛声明
└── workbuddy.md        # WorkBuddy 开发过程记录
```

## 目标用户

- 每天通勤、想多睡 10 分钟的打工人
- 想吃早餐但不想踩雷高热量组合的健康党
- 想知道「今天我这单能用哪张券」的精打细算党

## 免责声明

本项目为麦当劳程序员节创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。项目输出仅供参考，不构成医疗、营养或其他专业建议；餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。

## License

MIT
