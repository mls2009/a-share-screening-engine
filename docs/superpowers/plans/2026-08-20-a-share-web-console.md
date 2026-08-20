# A 股本地 Web 控制台与端到端交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用本地 FastAPI 服务端渲染界面串联数据、策略、回测、监控、模拟账户和设置，完成两条端到端验收流程与本机启动文档。

**Architecture:** 页面路由只调用应用服务，不直接查询行情源或修改领域对象。Jinja 模板负责首屏，HTMX 负责局部刷新，少量原生 JavaScript 只用于表单行增删和图表。耗时回测由后台进程执行，页面轮询任务状态。应用默认仅监听 `127.0.0.1`。

**Tech Stack:** FastAPI、Uvicorn、Jinja2、HTMX、Chart.js、Pydantic 2、pytest、HTTPX TestClient、Playwright（仅端到端测试）、Ruff

---

## Route Contract

```text
GET  /                              总览
GET  /watchlist                     自选股与实时行情
GET  /strategies                    策略列表
GET  /strategies/new                配置式策略编辑器
POST /strategies                    保存策略
GET  /backtests                     回测任务列表
POST /backtests                     创建回测
GET  /backtests/{run_id}            进度或报告
GET  /monitors                      监控任务
POST /monitors                      创建/更新监控
POST /monitors/{task_id}/toggle     启停
GET  /simulation                    模拟账户
GET  /data                          数据缓存与质量
POST /data/sync                     创建数据同步任务
GET  /settings                      本地设置
POST /settings/feishu/test          飞书测试
GET  /health/live                   进程存活
GET  /health/ready                  数据库迁移和服务就绪
```

## File Map

```text
src/astock/web/app.py                  FastAPI 工厂与生命周期
src/astock/web/dependencies.py         应用服务依赖
src/astock/web/viewmodels.py           页面专用展示模型
src/astock/web/forms.py                表单解析与校验
src/astock/web/routes/dashboard.py     总览
src/astock/web/routes/watchlist.py     自选股
src/astock/web/routes/strategies.py    策略管理
src/astock/web/routes/backtests.py     回测提交/报告
src/astock/web/routes/monitors.py      监控任务
src/astock/web/routes/simulation.py    模拟账户
src/astock/web/routes/data.py          数据管理
src/astock/web/routes/settings.py      设置与飞书测试
src/astock/web/templates/              Jinja 页面和局部模板
src/astock/web/static/app.css          本地样式
src/astock/web/static/app.js           轻量表单交互
src/astock/web/static/vendor/          固定版本 HTMX/Chart.js
tests/web/                              路由、模板和生命周期测试
tests/e2e/                              浏览器端到端测试
README.md                               安装、配置、运行和故障排查
.env.example                            非秘密配置示例
```

### Task 1: Create the local-only web application shell

**Files:**
- Modify: `pyproject.toml`
- Create: `src/astock/web/__init__.py`
- Create: `src/astock/web/app.py`
- Create: `src/astock/web/dependencies.py`
- Create: `src/astock/web/templates/base.html`
- Create: `src/astock/web/static/app.css`
- Test: `tests/web/test_app.py`

- [ ] **Step 1: Write failing app and health tests**

```python
from fastapi.testclient import TestClient
from astock.web.app import create_app


def test_app_is_ready_after_lifespan(app_services) -> None:
    with TestClient(create_app(app_services)) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").status_code == 200
        response = client.get("/")
        assert response.status_code == 200
        assert "A 股策略平台" in response.text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_app.py -v`
Expected: FAIL because the web package is missing.

- [ ] **Step 3: Add dependencies and app factory**

Add runtime dependencies `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `httpx`, and `apscheduler`; add development dependency `playwright`.

```python
# src/astock/web/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def create_app(services=None) -> FastAPI:
    services = services or build_services()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services.database.migrate()
        app.state.services = services
        yield
        services.close()

    app = FastAPI(title="A 股策略平台", lifespan=lifespan)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        return JSONResponse({"status": "ok" if services.ready() else "not_ready"},
                            status_code=200 if services.ready() else 503)

    register_routes(app)
    return app
```

- [ ] **Step 4: Add the base template and navigation**

The base template has a skip link, page title, visible current section, navigation to all eight pages, global source/monitor status, flash/error region and block content. Bundle static assets locally so normal use does not depend on a CDN.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_app.py -v`
Expected: PASS.

```bash
git add pyproject.toml src/astock/web tests/web/test_app.py
git commit -m "feat: scaffold local web console"
```

### Task 2: Add view models and form-error conventions

**Files:**
- Create: `src/astock/web/viewmodels.py`
- Create: `src/astock/web/forms.py`
- Test: `tests/web/test_forms.py`

- [ ] **Step 1: Write localized validation tests**

```python
def test_backtest_form_returns_field_errors() -> None:
    result = BacktestForm.from_form({"symbols": "", "initial_cash": "-1", "start": "bad"})
    assert result.errors == {
        "symbols": "至少输入一只股票",
        "initial_cash": "初始资金必须大于 0",
        "start": "请输入 YYYY-MM-DD 日期",
    }
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_forms.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement explicit form parsers**

Create `FormResult[T](value, errors)` and parsers for strategy, backtest, monitor, watchlist and settings forms. Convert web strings to existing Pydantic request models; translate known validation failures to field-level Chinese messages; retain submitted values after an error. Do not place parsing rules in route functions.

- [ ] **Step 4: Define serializable view models**

Create typed rows for source health, task status, quote, signal, position, order, data coverage, quality issue and report summary. Convert timestamps to Asia/Shanghai display strings at this boundary; keep domain timestamps timezone-aware.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_forms.py -v`
Expected: PASS.

```bash
git add src/astock/web/forms.py src/astock/web/viewmodels.py tests/web/test_forms.py
git commit -m "feat: validate console forms and views"
```

### Task 3: Implement dashboard and watchlist pages

**Files:**
- Create: `src/astock/web/routes/__init__.py`
- Create: `src/astock/web/routes/dashboard.py`
- Create: `src/astock/web/routes/watchlist.py`
- Create: `src/astock/web/templates/dashboard.html`
- Create: `src/astock/web/templates/watchlist.html`
- Create: `src/astock/web/templates/partials/watchlist_table.html`
- Test: `tests/web/test_dashboard.py`
- Test: `tests/web/test_watchlist.py`

- [ ] **Step 1: Write route tests against fake services**

```python
def test_dashboard_shows_degraded_source_and_today_signal(client, services) -> None:
    services.dashboard.source_status = "degraded"
    services.dashboard.today_signals = [SIGNAL]
    text = client.get("/").text
    assert "行情异常" in text
    assert "600519.SH" in text


def test_watchlist_partial_contains_freshness(client) -> None:
    response = client.get("/watchlist/table", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "5 秒前" in response.text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_dashboard.py tests/web/test_watchlist.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the dashboard**

Display source freshness, enabled/paused monitor counts, monitoring process state, simulated equity/P&L, today’s signals and latest quality errors. Every degraded tile links to the relevant data or monitor page and shows the stored reason.

- [ ] **Step 4: Implement watchlist CRUD and polling**

Add/remove symbols through service methods after symbol validation. Render code/name/price/change/volume/amount/quote time/freshness. HTMX refreshes only the table every 5 seconds while the page is visible; stale rows are visually marked and never shown as live.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_dashboard.py tests/web/test_watchlist.py -v`
Expected: PASS.

```bash
git add src/astock/web/routes src/astock/web/templates tests/web/test_dashboard.py tests/web/test_watchlist.py
git commit -m "feat: show dashboard and realtime watchlist"
```

### Task 4: Build the configured and Python strategy pages

**Files:**
- Create: `src/astock/web/routes/strategies.py`
- Create: `src/astock/web/templates/strategies/list.html`
- Create: `src/astock/web/templates/strategies/edit.html`
- Create: `src/astock/web/templates/strategies/python.html`
- Modify: `src/astock/web/static/app.js`
- Test: `tests/web/test_strategies.py`

- [ ] **Step 1: Write create/reject/round-trip tests**

```python
def test_configured_strategy_round_trip(client, strategy_repository) -> None:
    response = client.post("/strategies", data=VALID_MA_CROSS_FORM, follow_redirects=False)
    assert response.status_code == 303
    saved = strategy_repository.get(response.headers["location"].rsplit("/", 1)[-1])
    assert saved.buy_rule.operator == "and"


def test_editor_rejects_more_than_one_nested_group(client) -> None:
    response = client.post("/strategies", data=TOO_DEEP_FORM)
    assert response.status_code == 422
    assert "只支持一层 AND/OR 条件组" in response.text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_strategies.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the configured editor**

Support independent buy/sell groups; MA, MACD, KDJ, RSI, Bollinger, price and volume fields; comparison/cross operators; one nested group; quantity or target weight. Server validation is authoritative. Native JS only adds/removes condition rows and changes relevant operands—it must submit a normal form that works without JavaScript.

- [ ] **Step 4: Implement Python strategy management**

Allow creating/editing source files only inside configured `data/strategies/`; validate the filename and resolved path; display the required `create_strategy()` contract; load-test before saving; show a traceback without environment secrets. Save a content hash and version for reproducible backtests.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_strategies.py -v`
Expected: PASS.

```bash
git add src/astock/web/routes/strategies.py src/astock/web/templates/strategies src/astock/web/static/app.js tests/web/test_strategies.py
git commit -m "feat: manage configured and Python strategies"
```

### Task 5: Add backtest submission, progress and report pages

**Files:**
- Create: `src/astock/web/routes/backtests.py`
- Create: `src/astock/web/templates/backtests/list.html`
- Create: `src/astock/web/templates/backtests/new.html`
- Create: `src/astock/web/templates/backtests/status.html`
- Create: `src/astock/web/templates/backtests/report.html`
- Create: `src/astock/web/templates/partials/backtest_status.html`
- Test: `tests/web/test_backtests.py`

- [ ] **Step 1: Write submission and report tests**

```python
def test_backtest_submission_redirects_to_job(client, backtest_service) -> None:
    response = client.post("/backtests", data=VALID_BACKTEST_FORM, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/backtests/run-1"
    assert backtest_service.submitted.mode.value == "realistic"


def test_failed_data_preparation_shows_missing_range(client, backtest_service) -> None:
    backtest_service.fail_with_missing("600519.SH", "2020-01-01", "2020-02-01")
    text = client.get("/backtests/run-1").text
    assert "600519.SH" in text and "2020-01-01" in text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_backtests.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement request and progress pages**

Form fields include strategy, symbols/universe, timeframe (5/15/30/60m, day/week/month), date range, cash, simple/realistic mode, adjustment, benchmark, allocation/caps, fees/tax/slippage. Before submit, show required cached/missing ranges. Status page polls a small partial and displays queued/preparing/running/completed/failed with stage, percentage and a concrete error.

- [ ] **Step 4: Implement the report**

Display saved request and hashes; summary metrics; Chart.js equity/benchmark/drawdown charts; position timeline; order/fill/fee tables; unmatched orders and reasons. Add CSV downloads generated from saved Parquet details, never rerun the backtest for display.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_backtests.py -v`
Expected: PASS.

```bash
git add src/astock/web/routes/backtests.py src/astock/web/templates/backtests src/astock/web/templates/partials/backtest_status.html tests/web/test_backtests.py
git commit -m "feat: submit and inspect backtests in console"
```

### Task 6: Add monitoring and simulated-account pages

**Files:**
- Create: `src/astock/web/routes/monitors.py`
- Create: `src/astock/web/routes/simulation.py`
- Create: `src/astock/web/templates/monitors/list.html`
- Create: `src/astock/web/templates/monitors/edit.html`
- Create: `src/astock/web/templates/simulation.html`
- Create: `src/astock/web/templates/partials/monitor_status.html`
- Create: `src/astock/web/templates/partials/simulation_tables.html`
- Test: `tests/web/test_monitors.py`
- Test: `tests/web/test_simulation.py`

- [ ] **Step 1: Write monitoring lifecycle and account tests**

```python
def test_monitor_can_be_enabled_and_paused_reason_is_visible(client, monitoring_service) -> None:
    response = client.post("/monitors/t1/toggle", data={"enabled": "true"}, follow_redirects=False)
    assert response.status_code == 303
    monitoring_service.pause("t1", "stale_quote")
    assert "行情已陈旧" in client.get("/monitors").text


def test_simulation_page_shows_rejected_order_reason(client) -> None:
    text = client.get("/simulation").text
    assert "T+1 当日不可卖" in text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_monitors.py tests/web/test_simulation.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement monitor editor and controls**

Support price and shared-strategy monitors, watchlist or market scope, timeframe, 5-second/5-minute effective cadence, cooldown, notify-only or simulated action, account and sizing. Enforce market scope at five minutes. Start/stop affects persisted task state; the page shows last run, next run, latest signal and paused/error reason.

- [ ] **Step 4: Implement simulated-account display**

Show cash/frozen cash, equity, realized/unrealized P&L, sellable/T+1-frozen quantities, positions, daily net value, signals, orders, fills, fees and rejection reasons. Poll only live summary fragments; historical tables use pagination.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_monitors.py tests/web/test_simulation.py -v`
Expected: PASS.

```bash
git add src/astock/web/routes/monitors.py src/astock/web/routes/simulation.py src/astock/web/templates/monitors src/astock/web/templates/simulation.html src/astock/web/templates/partials tests/web/test_monitors.py tests/web/test_simulation.py
git commit -m "feat: control monitors and inspect simulation"
```

### Task 7: Add data-management and settings pages

**Files:**
- Create: `src/astock/web/routes/data.py`
- Create: `src/astock/web/routes/settings.py`
- Create: `src/astock/web/templates/data.html`
- Create: `src/astock/web/templates/settings.html`
- Test: `tests/web/test_data.py`
- Test: `tests/web/test_settings.py`

- [ ] **Step 1: Write data task and secret-handling tests**

```python
def test_data_page_shows_coverage_and_quality_reason(client) -> None:
    text = client.get("/data").text
    assert "600519.SH" in text
    assert "重复时间戳" in text


def test_settings_never_render_feishu_secret(client, monkeypatch) -> None:
    monkeypatch.setenv("ASTOCK_FEISHU_SECRET", "never-render-me")
    assert "never-render-me" not in client.get("/settings").text
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_data.py tests/web/test_settings.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement data visibility and sync jobs**

List coverage by symbol/base timeframe/adjustment, partition size, latest timestamp and source; list quality issues/corrections with timestamps and reasons. Sync form starts a background data task and reports progress. Derived periods are computed from daily/5-minute bases and are therefore shown as derivable coverage, not stored or rebuilt from this page. The UI never deletes base Parquet.

- [ ] **Step 4: Implement settings without secret persistence**

Show effective non-secret values: data path, quote freshness limit, keep-awake, fee presets, scan batch sizes and outbox retry limits. For Feishu, show only configured/not configured and a send-test action. Secret setup instructions point to `.env`; POST handlers must never echo secret values.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_data.py tests/web/test_settings.py -v`
Expected: PASS.

```bash
git add src/astock/web/routes/data.py src/astock/web/routes/settings.py src/astock/web/templates/data.html src/astock/web/templates/settings.html tests/web/test_data.py tests/web/test_settings.py
git commit -m "feat: manage data and local settings"
```

### Task 8: Add accessibility, safe local defaults and error pages

**Files:**
- Modify: `src/astock/web/app.py`
- Modify: `src/astock/web/templates/base.html`
- Modify: `src/astock/web/static/app.css`
- Create: `src/astock/web/templates/error.html`
- Test: `tests/web/test_safety.py`
- Test: `tests/web/test_accessibility.py`

- [ ] **Step 1: Write safety and semantic-markup tests**

```python
def test_unsafe_non_local_bind_requires_explicit_opt_in(settings) -> None:
    settings.web_host = "0.0.0.0"
    with pytest.raises(ValueError, match="ASTOCK_ALLOW_REMOTE"):
        settings.validate_web_bind()


def test_every_form_control_has_label(client) -> None:
    html = client.get("/backtests/new").text
    assert_no_unlabelled_controls(html)
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/web/test_safety.py tests/web/test_accessibility.py -v`
Expected: FAIL.

- [ ] **Step 3: Enforce local-only defaults and safe errors**

Default to `127.0.0.1:8000`; refuse a non-loopback host unless `ASTOCK_ALLOW_REMOTE=true` and print a warning that authentication/TLS are absent. Add request IDs; log stack traces server-side with secret filtering; render a concise Chinese error plus request ID. Reject state-changing requests without a same-origin `Origin`/`Host` match.

- [ ] **Step 4: Verify keyboard and status behavior**

All controls have labels, tables have captions/headings, color is not the only status cue, focus is visible, async fragments announce status through `aria-live`, and charts have a text/table equivalent. Add tests for navigation landmarks and error summary links.

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/web/test_safety.py tests/web/test_accessibility.py -v`
Expected: PASS.

```bash
git add src/astock/web tests/web/test_safety.py tests/web/test_accessibility.py
git commit -m "feat: harden and improve console accessibility"
```

### Task 9: Complete both end-to-end user journeys

**Files:**
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_backtest_journey.py`
- Create: `tests/e2e/test_monitoring_journey.py`
- Create: `tests/fixtures/e2e/recorded_market.json`

- [ ] **Step 1: Build a deterministic local E2E fixture**

Start the real FastAPI app with a temporary DuckDB/Parquet directory, recorded history/quotes and a fake Feishu HTTP endpoint. Run background workers in deterministic test mode with an injectable clock. Never use public network services in CI.

- [ ] **Step 2: Implement the backtest journey**

```python
def test_create_strategy_download_run_and_view_report(page, app):
    page.goto(app.url + "/strategies/new")
    create_ma_cross_strategy(page)
    submit_realistic_backtest(page, symbol="600519.SH", timeframe="15m")
    page.get_by_text("回测完成").wait_for()
    expect(page.get_by_text("最大回撤")).to_be_visible()
    expect(page.get_by_text("下一根 K 线开盘")).to_be_visible()
```

- [ ] **Step 3: Implement the monitoring journey**

```python
def test_monitor_trigger_feishu_fill_and_position(page, app, market_clock, fake_feishu):
    create_price_monitor(page, threshold=100, simulate=True)
    market_clock.feed_prices([99, 101, 102])
    expect(page.get_by_text("已触发")).to_be_visible()
    assert fake_feishu.message_count == 1
    page.goto(app.url + "/simulation")
    expect(page.get_by_text("600519.SH")).to_be_visible()
```

- [ ] **Step 4: Verify restart idempotency in the browser journey**

Restart the app between trigger and the repeated quote. Assert one signal, one simulated fill, one sent notification and the same position remain visible.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m playwright install chromium
python -m pytest tests/e2e -v
```

Expected: both journeys PASS without external network access.

```bash
git add tests/e2e tests/fixtures/e2e
git commit -m "test: cover backtest and monitoring journeys"
```

### Task 10: Add operator documentation and final verification

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Modify: `src/astock/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write CLI help tests**

```python
def test_serve_help_documents_local_bind(cli_runner) -> None:
    result = cli_runner.invoke(["serve", "--help"])
    assert result.exit_code == 0
    assert "127.0.0.1" in result.output
```

- [ ] **Step 2: Implement the serve command**

`astock serve --host 127.0.0.1 --port 8000` validates the host, ensures directories, migrates DuckDB and launches Uvicorn. Monitoring starts only when explicitly enabled from the UI/CLI; merely opening the web app does not start market scans.

- [ ] **Step 3: Write the runbook**

README sections: Python 3.12 installation, virtual environment, dependency install, BaoStock/mootdx online smoke tests, Feishu bot webhook/signature setup, `.env` keys, `astock serve`, web journeys, monitoring lifecycle, macOS sleep behavior, data backup, log locations, data-source outage recovery and the explicit no-real-trading scope.

`.env.example` contains placeholders and documented non-secret defaults only:

```dotenv
ASTOCK_DATA_DIR=data
ASTOCK_WEB_HOST=127.0.0.1
ASTOCK_WEB_PORT=8000
ASTOCK_KEEP_AWAKE=true
ASTOCK_FEISHU_WEBHOOK=
ASTOCK_FEISHU_SECRET=
```

- [ ] **Step 4: Run complete offline verification**

Run:

```bash
python -m pytest --cov=astock --cov-report=term-missing
ruff check .
python -m pytest tests/e2e -v
astock --help
astock serve --help
```

Expected: all offline tests PASS, lint is clean, both journeys pass and all commands are documented.

- [ ] **Step 5: Run opt-in live acceptance on the target Mac**

During an A-share trading session:

```bash
astock data smoke --provider baostock
astock data smoke --provider mootdx
astock notify test
astock serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, run one short historical backtest, enable one watchlist price alert, confirm one Feishu card, then disable monitoring and confirm the owned `caffeinate` child exits.

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example src/astock/cli.py tests/test_cli.py
git commit -m "docs: add local operation runbook"
```

## Milestone Verification

Run:

```bash
python -m pytest --cov=astock --cov-report=term-missing
ruff check .
python -m pytest tests/e2e -v
```

Expected:

- all eight required pages are reachable and show service-backed state;
- a user can create a strategy, prepare data, run a backtest and inspect the saved report;
- a user can create a monitor, trigger a recorded quote, see one Feishu delivery and one simulated fill;
- restart preserves tasks, signals, account and reports without duplication;
- data-quality or freshness failures show a concrete Chinese reason;
- local installation and operation are reproducible from README alone.
