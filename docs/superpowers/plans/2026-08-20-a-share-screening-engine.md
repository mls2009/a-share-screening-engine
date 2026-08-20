# A 股全市场筛选引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有真实行情基础上建立可恢复的全市场日线数据库、日/周/月特征仓库和可解释的任意嵌套条件筛选引擎，并提供 CLI 与内部 HTTP API。

**Architecture:** Parquet 继续保存标准化 K 线，DuckDB 保存股票池、同步任务、宽表特征、形态、支撑压力及筛选运行记录。条件树先经过目录和单位校验，再由解释器对按日期读取的特征快照执行三值逻辑；盘中模式用实时快照覆盖允许实时计算的字段，不改写历史日线。

**Tech Stack:** Python 3.12、Pandas、PyArrow、DuckDB、Pydantic 2、BaoStock、腾讯行情、FastAPI、Typer、pytest、Ruff。

---

## 执行原则

- 每一项严格执行 RED → GREEN → REFACTOR；先运行新增测试并确认因缺少功能失败。
- 每项完成后运行该项测试和 `pytest -q`，再提交独立 commit。
- 不使用模拟行情填充真实筛选结果；缺失值保持未知，并在解释中显示。
- 首次建库默认最近 3 年，逐股落盘和记录进度，单股失败不终止整批。
- 阶段一只提供图表所需的 bars/zones 数据合同，不实现前端和手动画线 UI。

### Task 1: 扩展 DuckDB 模型和仓储

**Files:**
- Modify: `src/astock/storage/schema.sql`
- Create: `src/astock/storage/jobs.py`
- Create: `tests/storage/test_screening_schema.py`
- Create: `tests/storage/test_jobs.py`

**Steps:**

1. 写失败测试，断言迁移后存在 `market_features`、`pattern_events`、
   `support_resistance_zones`、`data_sync_jobs`、`sync_job_failures`、
   `screen_definitions`、`screen_runs`、`screen_matches`，并验证 `symbols`
   包含 `board` 和 `is_listed`。
2. 运行 `pytest tests/storage/test_screening_schema.py -q`，确认因表/列不存在失败。
3. 在 `schema.sql` 增加幂等 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 和表定义。
   `market_features` 主键为 `(symbol, timeframe, feature_date, feature_version)`；
   常用数字指标用明确列，其余可版本化值放 `extra JSON`。
4. 写 `SyncJobRepository` 失败测试，覆盖 create、progress、failure、complete 和
   `failed_symbols(job_id)`。
5. 实现最小仓储并运行 `pytest tests/storage/test_screening_schema.py tests/storage/test_jobs.py -q`。
6. 运行全套测试与 Ruff，提交 `feat: add screening storage schema`。

### Task 2: 建立全市场股票池和上市属性

**Files:**
- Modify: `src/astock/data/providers/baostock.py`
- Modify: `src/astock/data/service.py`
- Create: `src/astock/domain/security.py`
- Modify: `tests/data/providers/test_baostock.py`
- Modify: `tests/data/test_service.py`

**Steps:**

1. 先测试 BaoStock 股票基础资料标准化为 `Security`：代码、名称、交易所、板块、
   上市日、退市日、是否在市；板块规则覆盖主板、创业板、科创板、北交所。
2. 运行新增测试，确认 `Security`/`securities_on()` 缺失。
3. 实现不可变 `Security` 模型和 `BaoStockProvider.securities_on(date)`；一次会话内
   获取交易股票列表与基础资料，不静默丢弃 ST、停牌、新股或北交所。
4. 测试 `MarketDataService.sync_reference()` 幂等 upsert 全部属性，并实现对应 SQL。
5. 运行 provider/service 测试、全套测试与 Ruff，提交
   `feat: sync complete A-share universe metadata`。

### Task 3: 可恢复的全市场历史同步

**Files:**
- Create: `src/astock/data/market_sync.py`
- Modify: `src/astock/storage/coverage.py`
- Create: `tests/data/test_market_sync.py`

**Steps:**

1. 写 `MarketSyncService.start(end, years=3)` 测试：读取全部在市股票，按现有覆盖
   缺口调用历史源，每只成功后立即写 bars/coverage/progress，失败只写 failure 并继续。
2. 运行测试，确认模块缺失。
3. 实现 `SyncSummary(job_id,total,succeeded,failed,status)` 和逐股同步；开始日使用
   `end - relativedelta(years=years)` 的等价安全日期计算，上市日晚于开始日时取上市日。
4. 写并实现 `resume(job_id)` 与 `retry_failed(job_id)`：已成功股票不再请求，失败
   重试成功后清除活动失败并更新计数。
5. 覆盖空股票池、全失败、部分缓存和中断后恢复；运行目标测试、全套测试与 Ruff。
6. 提交 `feat: add resumable full-market history sync`。

### Task 4: 条件目录与安全 AST

**Files:**
- Create: `src/astock/screening/models.py`
- Create: `src/astock/screening/catalog.py`
- Create: `src/astock/screening/validation.py`
- Create: `tests/screening/test_models.py`
- Create: `tests/screening/test_validation.py`

**Steps:**

1. 写失败测试并定义 JSON 合同：

   ```json
   {"kind":"group","logic":"and","children":[
     {"kind":"condition","metric":"return_20","timeframe":"day","operator":"gte",
      "right":{"kind":"constant","value":30,"unit":"percent"}},
     {"kind":"group","logic":"not","children":[
       {"kind":"condition","metric":"is_st","timeframe":"day","operator":"eq",
        "right":{"kind":"constant","value":true,"unit":"boolean"}}
     ]}
   ]}
   ```

2. 实现 `ConditionNode`/`GroupNode` 判别联合、`ConstantOperand`、`MetricOperand`
   （含 multiplier），及 `and/or/not` 结构约束。
3. 建立 `MetricCatalog`，首批登记价格、1/3/5/10/20/60/120/250 日收益、成交量、
   均量/量比、MA、MACD、KDJ、RSI、布林、ATR、OBV、波动率、上市交易日数、
   新股/次新股、ST/停牌、板块、形态、支撑压力距离。
4. 实现最大深度 32、节点 512、目录存在性、周期、运算符和单位兼容校验；错误必须
   带节点路径，例如 `root.children[1]`。
5. 运行目标测试、全套测试与 Ruff，提交 `feat: add safe screening condition AST`。

### Task 5: 日/周/月技术特征计算和持久化

**Files:**
- Create: `src/astock/features/technical.py`
- Create: `src/astock/features/store.py`
- Create: `src/astock/features/builder.py`
- Create: `tests/features/test_technical.py`
- Create: `tests/features/test_builder.py`

**Steps:**

1. 用固定 OHLCV 序列写失败测试，逐个覆盖收益率、MA/均量、MACD、KDJ、RSI14、
   Bollinger、ATR14、OBV、振幅、20 日波动率、20/60/250 日高低点、最大回撤和
   连涨/连跌。测试使用手算小样本或独立公式，不复制实现。
2. 实现纯函数 `compute_technical_features(bars) -> DataFrame`，所有滚动指标只用
   当前及过去数据；窗口不足返回 null。
3. 写失败测试：`FeatureBuilder.build_symbol(symbol, as_of)` 从日线读取并分别聚合
   DAY/WEEK/MONTH，计算上市交易日数，写入 `market_features`，重复执行幂等。
4. 实现 `MarketFeatureStore.upsert/read_latest/read_history` 与 builder；默认
   `feature_version="v1"`，新股 `<=30`，次新股 `31..250`。
5. 运行目标测试、全套测试与 Ruff，提交 `feat: build daily weekly monthly features`。

### Task 6: 确定性 K 线形态

**Files:**
- Create: `src/astock/features/patterns.py`
- Create: `tests/features/test_patterns.py`

**Steps:**

1. 为十字星、长上/下影、锤头、看涨/看跌吞没、刺透、乌云盖顶、早晨/黄昏之星、
   三连阳/阴、突破整理区间分别构造正例和反例失败测试。
2. 实现 `detect_patterns(bars, rule_version="v1")`，每个事件带 type、date、strength、
   body/range/shadow ratios 和参数快照；不得读取事件日之后的 K 线。
3. 实现事件幂等写入 `pattern_events`，并由 builder 在每个周期更新。
4. 运行目标测试、全套测试与 Ruff，提交 `feat: detect versioned candlestick patterns`。

### Task 7: 自动水平与趋势支撑压力区间

**Files:**
- Create: `src/astock/features/zones.py`
- Create: `tests/features/test_zones.py`

**Steps:**

1. 写合成波段失败测试：局部低点聚类得到绿色支撑区，局部高点聚类得到红色压力区；
   至少两个相容锚点才能形成趋势区；所有区域有 lower/center/upper、touches、strength。
2. 写防未来函数测试：截断未来 K 线后，截止日之前生成的结果不变。
3. 实现 ATR/百分比容差的 pivots、水平聚类和最小二乘趋势线；分类以截止日最新价和
   锚点方向为准，保存 `horizontal|trend` 与规则版本。
4. 实现 `nearest_zones(symbol,timeframe,as_of,limit_each=3)`：分别返回最近 3 个支撑
   与 3 个压力，自动区域标记 `source="auto"`，为后续图区分手动画线。
5. 运行目标测试、全套测试与 Ruff，提交 `feat: calculate support resistance zones`。

### Task 8: 可解释的三值筛选执行器

**Files:**
- Create: `src/astock/screening/evaluator.py`
- Create: `src/astock/screening/service.py`
- Create: `tests/screening/test_evaluator.py`
- Create: `tests/screening/test_service.py`

**Steps:**

1. 写 evaluator 失败测试，覆盖常量比较、字段对字段乘数、between/not-between、
   crosses_above/below、最近 M 期至少 N 次、连续 N 期及 null 三值逻辑。
2. 实现 `TRUE/FALSE/UNKNOWN`；AND 有 false 即 false，OR 有 true 即 true，NOT 保留
   unknown。每个节点返回 path、actual、expected、unit、result 和 children。
3. 写 service 失败测试：收盘模式读取同一 as-of 的全市场特征，执行嵌套条件，按指定
   指标升降序排名、分页，保存 definition/run/matches 和完整解释。
4. 实现 `ScreeningService.validate/run/results`；全市场候选只含在市 A 股，但不默认
   排除 ST、停牌、新股、次新股、北交所；缺值默认不命中并在解释中标 unknown。
5. 运行目标测试、全套测试与 Ruff，提交 `feat: run explainable nested stock screens`。

### Task 9: 盘中实时快照与实时筛选

**Files:**
- Modify: `src/astock/data/providers/tencent.py`
- Create: `src/astock/data/snapshots.py`
- Modify: `src/astock/screening/service.py`
- Modify: `tests/data/providers/test_tencent.py`
- Create: `tests/screening/test_live_screening.py`

**Steps:**

1. 写腾讯解析失败测试，覆盖批量代码、价格、开高低昨收、成交量、成交额、时间、
   换手率、量比、总市值/流通市值；缺字段返回 null，不返回 0。
2. 实现最多 60 代码/批的 `snapshot_many` 和批次失败收集。
3. 写 live screening 失败测试：把当日快照临时叠加到最后完整日线，仅重算盘中允许
   指标；历史 Parquet 和收盘特征不变化；缺失快照产生 unknown。
4. 实现快照覆盖率、失败批次数和快照 JSON 随 `screen_runs/matches` 保存。
5. 运行目标测试、全套测试与 Ruff，提交 `feat: add live full-market screening overlay`。

### Task 10: CLI 操作入口

**Files:**
- Modify: `src/astock/cli.py`
- Modify: `tests/test_cli.py`

**Steps:**

1. 写失败测试：
   - `astock data sync-market --years 3 --end YYYY-MM-DD`
   - `astock data sync-status [JOB_ID]`
   - `astock data retry-failed JOB_ID`
   - `astock screen catalog`
   - `astock screen validate FILE`
   - `astock screen run FILE --mode close|live --as-of YYYY-MM-DD`
   - `astock screen results RUN_ID --limit 50 --offset 0`
2. 实现薄 CLI，只调用 service，不复制业务规则；JSON 输出含 job/run id、状态、数据日期、
   成功/失败数、实时覆盖率和结果解释。
3. 运行 CLI 测试、全套测试与 Ruff，提交 `feat: expose sync and screen CLI commands`。

### Task 11: 内部 HTTP API 与图表数据合同

**Files:**
- Modify: `pyproject.toml`
- Create: `src/astock/api/app.py`
- Create: `src/astock/api/dependencies.py`
- Create: `tests/api/test_screening_api.py`

**Steps:**

1. 先添加 FastAPI/TestClient 依赖配置，再写失败 API 测试：
   `GET /api/catalog`、`POST /api/screens/validate`、`POST /api/screens/run`、
   `GET /api/screens/runs/{id}`、`GET /api/sync/jobs/{id}`、
   `GET /api/symbols/{symbol}/bars`、`GET /api/symbols/{symbol}/zones`。
2. API 校验响应使用稳定错误结构 `{code,message,path}`；run 接受 close/live、as_of、
   rank、limit、offset；bars 支持 day/week/month 及日期范围。
3. zones 返回 `kind=support|resistance`、`geometry=horizontal|trend`、上下界、中心、
   anchors、strength、source=auto，足以让后续 K 线图按支撑绿/压力红绘制。
4. 实现依赖注入和薄路由，运行 API 测试、全套测试与 Ruff，提交
   `feat: expose screening internal API`。

### Task 12: 端到端验收与真实小样本烟测

**Files:**
- Create: `tests/integration/test_screening_pipeline.py`
- Modify: `README.md`

**Steps:**

1. 写本地端到端测试：固定 provider 数据 → 同步 → 特征 → 条件“过去 20 个交易日
   涨幅 >=30% 且成交量 > 20 日均量 1.5 倍” → 命中解释 → bars/zones 查询。
2. 运行并通过：

   ```bash
   pytest -q
   ruff check src tests
   ```

3. 更新 README，给出建库、恢复、失败重试、筛选 JSON、CLI/API 启动命令，并明确
   第一次全市场同步耗时取决于数据源，不承诺免费源的服务等级。
4. 用 3–5 只真实股票和短日期范围执行联网烟测；若上游当时不可用，保留失败日志并
   报告为外部限制，不用模拟结果冒充通过。
5. 检查 `git diff --check`、工作树状态和提交历史，执行 verification skill 后再交付。

## 最终成功标准

- 新环境能建立全部在市 A 股股票池并启动最近 3 年真实前复权日线同步。
- 中断或单股失败后可恢复，且不会重复请求已完整覆盖区间。
- 日/周/月特征无未来函数；新股/次新股按交易日口径。
- 任意合法 AND/OR/NOT 条件树可校验、执行、排名、分页并得到逐节点解释。
- “过去一个月涨幅超过 30%”可用 `return_20 >= 30 percent` 直接筛选并查看对应真实 K 线。
- 收盘结果可复现；盘中结果记录实时覆盖与快照，缺失数据不当作零。
- API 已提供后续条件编辑器和专业 K 线图所需稳定合同。
- 全套 pytest、Ruff 和端到端测试通过。
