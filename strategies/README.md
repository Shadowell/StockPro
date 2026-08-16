# StockPro 预置策略

`strategies/` 保存用于首次 bootstrap 的预置策略脚本和 `manifest.json`。运行时的策略事实存储在 PostgreSQL 的策略身份与不可变版本中，而不是直接执行这里的工作树文件。

## 预置目录

| 文件 | 名称 | 研究目的 |
| --- | --- | --- |
| `mainboard_top10.py` | 主板涨幅 TOP10 | 主板强势股观察 |
| `volume_breakout.py` | 放量突破 | 成交量扩张与价格突破 |
| `limit_up_monitor.py` | 涨停板监控 | 涨停生态观察 |
| `flat_volume_breakout.py` | 平底放量突破首板 | 横盘后放量与首板条件 |
| `consecutive_limit_monitor.py` | 连板股监控 | 多日涨停连续性 |
| `hot_stocks_top20.py` | 热门股票 TOP20 | 公开热度排行观察 |
| `ma_convergence_breakout.py` | 均线粘合突破 | 多均线收敛后的突破 |
| `multi_factor_risk_budget.py` | 多因子风险预算 | 动量/反转/低波/非流动性截面加权，周度再平衡 + 日度熔断 |
| `board_*.py`（8） | 日线打板隔日 T | 首板 / 连板 / 炸板回封 / 空间板 / 放量 / 高度板 / 跌停反抽 / 实体板 |
| `t_*.py`（8） | 日线隔日 T | 低开高走 / 高开跟随 / 下影 / 尾盘强势 / 振幅回归 / 放量阳线 / 窄幅突破 / 隔夜高开 |
| `daily_*.py`（4） | 日频方向 | 3 日反转 / 20 日动量 / 均线多头 / 低波动防守 |

这些名称描述筛选逻辑，不代表已验证收益或投资建议。

日线打板 / 隔日 T 策略运行在 A 股日线 T+1 引擎上，用收盘涨幅 ≥ 9.5% 和连板计数近似涨停，不是逐笔高频或当日 T+0。它们需要通过 `POST /api/strategy` 建成 Strategy API v1 版本后才能回测；`init_strategies.py` 只导入脚本，不会自动验证版本。

## 初始化

首次准备数据库时，从仓库根目录执行：

```bash
(cd backend && venv/bin/python bootstrap_runtime.py)
```

该命令应用迁移、安装数据目录、注册研究数据集并导入缺失的预置策略。

也可以只处理策略：

```bash
backend/venv/bin/python scripts/init_strategies.py
backend/venv/bin/python scripts/init_strategies.py --force
```

`--force` 会覆盖同名预置内容，属于数据库写操作；执行前先确认 `DATABASE_URL` 指向目标本地数据库。后端普通启动默认不会自动导入或覆盖策略。

## 新策略的推荐方式

优先在“策略”工作区创建：

1. 编写 `StockPro Strategy API v1` 代码；
2. 配置参数、依赖和运行限制；
3. 静态验证；
4. 保存不可变版本；
5. 绑定快照运行回测；
6. 评审证据后决定是否进入 Paper。

运行时版本不能原地修改。修改已有策略会创建子版本，并保留原回测和 Paper 的引用。

## Strategy API v1

最小策略包含：

```python
def initialize(context):
    context.set_benchmark("SH_000300")


def handle_data(context, data):
    # 通过平台提供的数据和订单 API 研究/交易
    pass
```

可选生命周期函数包括 `before_trading_start`、`after_trading_end` 和 `on_strategy_end`。具体可用 API、参数和示例以策略编辑器中的当前模板与后端验证器为准。

## 运行限制

- 不允许直接访问 TuShare、AKShare、PostgreSQL、文件写入、网络或券商。
- 平台控制模拟时间、数据可用时间、订单、A 股撮合、风控和持久化。
- 回测和 Paper Replay 执行同一个固定策略版本。
- 运行受 CPU、内存、墙钟时间、日志和事件数量限制。
- 数据来自已封存 PG 快照，运行时不访问外部 Provider。
- 遵循 T+1、100 股整数手、涨跌停、停牌、ST、成本和容量规则。

## 旧脚本输出

目录中的部分早期预置脚本仍以 stdout JSON 形式输出候选股票，供兼容导入路径使用：

```json
{
  "stocks": [
    {
      "code": "600000",
      "name": "示例股票",
      "reason": "明确的筛选条件"
    }
  ]
}
```

新策略不要以这个旧格式绕过 Strategy API v1、版本验证和快照证据。
