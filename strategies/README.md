# 策略库

本目录存放 StockPro 的量化选股策略脚本。每个 `.py` 文件是一个独立策略，由 `manifest.json` 统一管理元数据。

## 策略列表

| 文件 | 策略名称 | 说明 | 执行间隔 |
|------|---------|------|---------|
| `mainboard_top10.py` | 主板涨幅TOP10 | 实时获取主板涨幅前10股票，排除ST/创业板/科创板 | 60s |
| `volume_breakout.py` | 放量突破策略 | 近20天无涨停 + 当日放量1.75倍以上的主板股(30-160亿) | 300s |
| `limit_up_monitor.py` | 涨停板监控 | 实时监控主板涨停股票，按成交额排序 | 30s |
| `flat_volume_breakout.py` | 平底放量突破首板 | 放量突破 + 低开高走，适合做首板 | 300s |
| `consecutive_limit_monitor.py` | 连板股监控 | 实时监控2板及以上的连板股票 | 60s |
| `hot_stocks_top20.py` | 热门股票TOP20 | 东方财富热门股票排行榜 | 120s |
| `ma_convergence_breakout.py` | 平底均线图突破 | MA5/10/20/30四线粘合，寻找横盘后突破机会 | 600s |

## 在新设备上初始化

克隆项目后运行以下命令，将策略导入本地 SQLite 数据库：

```bash
cd StockPro
python scripts/init_strategies.py          # 仅导入缺失的策略
python scripts/init_strategies.py --force   # 覆盖已有同名策略
```

后端启动时也会自动检测并导入缺失的策略，通常无需手动操作。

## 策略脚本规范

每个策略脚本是一段可独立运行的 Python 代码，必须将结果以 JSON 格式输出到 stdout：

```python
import json

# ... 策略逻辑 ...

output = {
    "stocks": [
        {"code": "600519", "name": "贵州茅台", "reason": "放量2.3倍 涨3.5%"},
        # ...
    ]
}
print(json.dumps(output, ensure_ascii=False))
```

**输出格式要求：**

- `stocks`: 数组，每个元素包含 `code`（股票代码）、`name`（名称）、`reason`（命中原因）
- 发生错误时输出 `{"stocks": [], "error": "错误描述"}`

## 添加新策略

1. 在本目录创建 `.py` 策略文件
2. 在 `manifest.json` 中添加对应条目：

```json
{
  "filename": "your_strategy.py",
  "name": "策略显示名称",
  "description": "策略描述",
  "interval_seconds": 300
}
```

3. 运行 `python scripts/init_strategies.py` 导入到数据库
4. 也可以在前端「策略开发」页面直接编写和保存策略
