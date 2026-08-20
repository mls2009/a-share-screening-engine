# AStock：A 股选股、K 线、回测与实时监控工作台

AStock 使用 BaoStock 同步沪深 A 股、使用 AKShare 的北交所官方列表和新浪历史接口
补齐北交所，使用腾讯行情提供盘中快照。
日线以 Parquet 保存，股票资料、日/周/月特征、形态、支撑压力和筛选记录保存在
DuckDB。筛选条件只接受受控 JSON，不执行用户输入的 Python 或 SQL。

前端包含四个工作区：全市场条件选股、七周期 K 线研究、策略回测、实时点位监控。

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

全市场任务默认同步日线；分钟线按需要为回测或图表中的股票同步。15/30/60 分钟由
5 分钟线本地合成，因此只需同步 5 分钟基础数据：

```bash
astock data sync --symbol 600519.SH --timeframe 5m \
  --start 2026-07-01 --end 2026-08-20 --adjustment qfq
```

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

先构建前端，再启动一体化服务：

```bash
cd web
npm install
npm run build
cd ..
uvicorn astock.api.app:create_default_app --factory --host 127.0.0.1 --port 8888
```

浏览器打开 [http://127.0.0.1:8888](http://127.0.0.1:8888)。开发模式可分别运行
`uvicorn` 和 `cd web && npm run dev`。

```bash
.venv/bin/uvicorn astock.api.app:create_default_app --factory --host 127.0.0.1 --port 8888
```

主要接口：

- `GET /api/catalog`：前端下拉框的指标、单位、周期和操作符。
- `POST /api/screens/validate`：校验任意嵌套 `AND / OR / NOT` 条件树。
- `POST /api/screens/run`：执行收盘或盘中筛选。
- `GET /api/screens/runs/{run_id}`：排名、特征快照和逐节点解释。
- `GET /api/sync/jobs/{job_id}`：同步状态。
- `GET /api/symbols/{symbol}/bars`：真实 K 线。
- `GET /api/symbols/{symbol}/zones`：最近自动支撑/压力区域和趋势通道。
- `POST /api/backtests/run`：用两棵条件树运行单股或组合回测。
- `GET /api/backtests/{run_id}`：读取持久化回测报告。
- `GET/POST/PATCH/DELETE /api/monitor/tasks`：管理实时点位规则。
- `POST /api/monitor/start`、`POST /api/monitor/stop`：启停后台扫描。
- `POST /api/monitor/scan`：手动执行一次扫描。
- `GET /api/monitor/signals`：读取最近触发记录。

自动区域的 `zone_kind` 为 `support` 或 `resistance`，`source` 为 `auto`。图表使用
绿色显示支撑、红色显示压力；自动结果使用虚线和半透明色带，手动画线使用实线。
水平区间和趋势区间都支持，默认返回离现价最近的 3 个支撑和 3 个压力。

## 策略回测

回测页直接复用选股条件树，可分别配置任意嵌套的入场和离场条件，支持
`5m / 15m / 30m / 60m / 日 / 周 / 月`。信号在已完成 K 线收盘后产生，下一根
K 线开盘撮合，避免未来函数。

“A 股规则近似”模式包含 100 股整手、T+1、滑点、佣金、最低佣金、印花税和过户费；
数据库存在对应交易日的证券状态时，也会检查停牌和一字涨跌停。当前默认全市场库使用
前复权行情，不处理分红送转的逐笔现金与持仓变化，因此它适合策略研究，不应视为券商级
成交复现。回测请求、权益曲线、交易明细和指标都保存在 DuckDB。

## 实时点位监控与飞书

监控页支持“价格达到上方、价格达到下方、向上突破、向下跌破”，可设置多个股票、
冷却时间、暂停/启用任务和手动扫描。自选股任务每 5 秒扫描；全市场任务每 5 分钟
读取数据库内全部在市 A 股并按 60 只一批请求。后台调度只在数据库交易日的
`09:30–11:30`、`13:00–15:00` 运行；手动扫描不受此限制。

在飞书群中添加“自定义机器人”，把 Webhook（以及启用签名校验时的密钥）放入环境变量：

```bash
export ASTOCK_FEISHU_WEBHOOK='https://open.feishu.cn/open-apis/bot/v2/hook/你的地址'
export ASTOCK_FEISHU_SECRET='你的签名密钥'  # 未启用签名校验时可省略
```

重启服务后，可在实时监控页点击“测试飞书”。触发记录与通知发件箱先原子写入
DuckDB，再发送飞书；网络失败按 5 秒起步指数退避，最多重试 8 次，不会重复告警。

## 验证

```bash
pytest -q
ruff check src tests
cd web && npm test -- --run && npm run build && npm run test:e2e
```

测试覆盖同步恢复、技术指标无未来函数、新股/次新股、形态、水平/趋势支撑压力、
条件树三值逻辑、盘中快照隔离、真实撮合、监控幂等、飞书重试、CLI、HTTP API 和
四工作区浏览器端到端流水线。
