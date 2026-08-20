# AStock：A 股真实行情、选股与回测数据基础

AStock 使用 BaoStock 同步沪深 A 股、使用 AKShare 的北交所官方列表和新浪历史接口
补齐北交所，使用腾讯行情提供盘中快照。
日线以 Parquet 保存，股票资料、日/周/月特征、形态、支撑压力和筛选记录保存在
DuckDB。筛选条件只接受受控 JSON，不执行用户输入的 Python 或 SQL。

## 安装

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

数据默认写入 `data/`。可用环境变量改变位置：

```bash
export ASTOCK_DATA_DIR=/path/to/astock-data
```

## 建立真实全市场数据库

首次同步默认获取全部在市 A 股最近三年的前复权日线，并在每只股票完成后生成
日、周、月特征、K 线形态及自动支撑压力：

```bash
astock data sync-market --years 3 --end 2026-08-20
```

命令返回 `job_id`。查看进度或重试失败股票：

```bash
astock data sync-status <job-id>
astock data retry-failed <job-id>
```

同步按股票逐个提交，单只失败不会终止整批；重试不会重新下载已有覆盖区间。
免费数据源没有服务等级保证，首次全市场同步的耗时取决于网络、上游限速和股票数量。

## 筛选条件

例如“最近 20 个交易日涨幅不低于 30%，且成交量大于 20 日均量的 1.5 倍”：

```json
{
  "kind": "group",
  "logic": "and",
  "children": [
    {
      "kind": "condition",
      "metric": "return_20",
      "timeframe": "1d",
      "operator": "gte",
      "right": {"kind": "constant", "value": 30, "unit": "percent"}
    },
    {
      "kind": "condition",
      "metric": "volume",
      "timeframe": "1d",
      "operator": "gt",
      "right": {
        "kind": "metric",
        "metric": "volume_ma_20",
        "timeframe": "1d",
        "multiplier": 1.5
      }
    }
  ]
}
```

假设保存为 `screen.json`：

```bash
astock screen catalog
astock screen validate screen.json
astock screen run screen.json --mode close --as-of 2026-08-20
astock screen run screen.json --mode live --as-of 2026-08-20
astock screen results <run-id> --limit 50 --offset 0
```

收盘模式只读取已完成 K 线，可复现；盘中模式临时叠加腾讯实时快照，不会修改历史
K 线或收盘特征。实时源缺失的数据保持 `unknown`，不会当作零。

## 内部 HTTP API

```bash
.venv/bin/uvicorn astock.api.app:create_default_app --factory --host 127.0.0.1 --port 8000
```

主要接口：

- `GET /api/catalog`：前端下拉框的指标、单位、周期和操作符。
- `POST /api/screens/validate`：校验任意嵌套 `AND / OR / NOT` 条件树。
- `POST /api/screens/run`：执行收盘或盘中筛选。
- `GET /api/screens/runs/{run_id}`：排名、特征快照和逐节点解释。
- `GET /api/sync/jobs/{job_id}`：同步状态。
- `GET /api/symbols/{symbol}/bars`：真实 K 线。
- `GET /api/symbols/{symbol}/zones`：最近自动支撑/压力区域和趋势通道。

自动区域的 `zone_kind` 为 `support` 或 `resistance`，`source` 为 `auto`；后续图表
使用绿色显示支撑、红色显示压力，并用虚线和半透明色带区别自动结果。

## 验证

```bash
pytest -q
ruff check src tests
```

测试覆盖同步恢复、技术指标无未来函数、新股/次新股、形态、水平/趋势支撑压力、
条件树三值逻辑、盘中快照隔离、CLI、HTTP API 和端到端筛选流水线。
