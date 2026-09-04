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

一体化服务启动后，会在每个工作日北京时间 16:10 自动执行一次全市场增量同步，
更新日线以及日、周、月特征。服务重启时会读取已完成的同步任务，避免同一天重复执行。

全市场任务默认同步日线；分钟线按需要为回测或图表中的股票同步。15/30/60 分钟由
5 分钟线本地合成，因此只需同步 5 分钟基础数据：

```bash
astock data sync --symbol 600519.SH --timeframe 5m \
  --start 2026-07-01 --end 2026-08-20 --adjustment qfq
```

## 筛选条件

前端按“价格行情、成交活跃度、技术指标、股票属性、交易状态、K 线形态、
趋势与点位”分层选择条件。上涨幅度和下跌幅度严格分开，界面都输入正数；
例如“20 周期下跌幅度至少 30%”会转为 `return_20 <= -30`。成交量增加/减少
使用相同语义。

板块、上市阶段和 K 线形态可多选，同一条件内任一选项命中即成立。上市阶段中，
新股为 0–30 个交易日，次新股为 31–250 个交易日，老股为超过 250 个交易日。
多选内部是 OR，多个条件之间仍可使用 AND / OR / NOT 任意组合。

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

选股工作台支持直接粘贴上述条件树 JSON，或选择本地 `.json` 文件导入。导入内容会
先经过结构、指标、周期、操作符和单位校验，校验失败不会覆盖当前正在编辑的条件。
当前条件可以命名保存为模板；模板持久化在 DuckDB 中，支持同名覆盖、加载和删除。

“近3个月任意5日最多涨停次数”会在最近 60 个交易日内枚举所有连续
5 日窗口，取窗口内收盘涨停次数的最大值。“近3个月任意10日最大涨幅”
会取同一 60 日范围内所有完整 10 日窗口的最大涨幅。涨停优先使用
当日证券状态和涨停价规则；状态数据缺失时，按 ST、主板、创业板、科创板、
北交所的对应涨停幅度近似判定。
“近3个月5日双涨停事件次数”把连续命中的重叠5日窗口合并为同一事件，
只有命中中断后再次出现才累加次数。

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
- `GET /api/symbols/{symbol}/zones`：返回最近的自动水平支撑/压力，以及所有处于
  `active` 状态的手动水平线和趋势线。
- `DELETE /api/symbols/{symbol}/zones/{zone_id}`：删除任意支撑压力线并记录点位。
- `POST /api/backtests/run`：用两棵条件树运行单股或组合回测。
- `GET /api/backtests/{run_id}`：读取持久化回测报告。
- `GET/POST/PATCH/DELETE /api/monitor/tasks`：管理实时点位规则。
- `POST /api/monitor/start`、`POST /api/monitor/stop`：启停后台扫描。
- `POST /api/monitor/scan`：手动执行一次扫描。
- `GET /api/monitor/signals`：读取最近触发记录。

图表只绘制区域中心线：绿色显示支撑，红色显示压力。自动线仅包含水平支撑/压力，
按现价归类；图上不常驻显示名称或数值，直接悬停到自动水平线上才显示价格。
手动画线支持水平线和趋势线，并始终保留用户选择的支撑/压力角色。自动水平线和手动
画线都能删除；普通结果统一使用实线，被删除点位以后落入原价格容差并再次生成时
使用虚线。默认选取离现价最近的 3 条自动水平支撑和 3 条自动水平压力。

`5m / 15m / 30m / 60m / 日 / 周 / 月` 的点位都依据各自周期的 K 线独立增量计算；
某个周期的数据更新不会直接复用其他周期的检测结果。

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

测试覆盖同步恢复、技术指标无未来函数、新股/次新股、形态、自动水平支撑压力与手动画线、
条件树三值逻辑、盘中快照隔离、真实撮合、监控幂等、飞书重试、CLI、HTTP API 和
四工作区浏览器端到端流水线。
