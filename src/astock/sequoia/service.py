"""Independent run snapshots and watchlist bridge for Sequoia strategies."""

import json
import logging
from datetime import date, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .strategies import BY_ID, evaluate, placement_dates, rps_scores, unknown

LOGGER = logging.getLogger(__name__)


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date = Field(default_factory=today)
    period: Literal["latest", "1y", "2y"] = "latest"
    scope: Literal["market", "watchlist"] = "market"
    group_id: str | None = None
    strategies: list[str] = Field(min_length=1, max_length=7)
    minimum_matches: int = Field(default=1, ge=1, le=7)
    parameters: dict[str, dict[str, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self):
        if self.as_of > today():
            raise ValueError("不能选择未来日期")
        if self.group_id and self.scope != "watchlist":
            raise ValueError("自选分组只能用于自选范围")
        if len(set(self.strategies)) != len(self.strategies) or any(
            s not in BY_ID for s in self.strategies
        ):
            raise ValueError("策略名称无效或重复")
        if self.minimum_matches > len(self.strategies):
            raise ValueError("同日最少命中数不能超过已选策略数")
        if "placement" in self.strategies and (self.as_of != today() or self.period != "latest"):
            raise ValueError("定增名单仅支持今天单日查询，不能用于历史范围筛选")
        for strategy, params in self.parameters.items():
            if strategy not in self.strategies:
                raise ValueError("参数只能属于已选择的策略")
            for key, value in params.items():
                spec = BY_ID[strategy]["parameters"].get(key)
                if (
                    not spec
                    or not spec["min"] <= value <= spec["max"]
                    or (spec["integer"] and value != int(value))
                ):
                    raise ValueError(f"{strategy}.{key} 参数超出范围或类型错误")
        return self


class AddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=10000)
    group_id: str | None = None
    by_strategy: bool = False

    @model_validator(mode="after")
    def one_destination(self):
        if self.group_id and self.by_strategy:
            raise ValueError("指定分组与按策略分组不能同时选择")
        return self


def source_snapshot(run_id, as_of, groups, minimum_matches=1, confluence_dates=None):
    nodes, evaluations, marks = [], [], []
    for i, group in enumerate(groups):
        children, results = [], []
        checks = [check for hit in group["occurrences"] for check in hit["checks"]] if group.get("occurrences") else group["checks"]
        for j, check in enumerate(checks):
            path = f"root.{i}.{j}"
            children.append(
                {
                    "kind": "condition",
                    "metric": check["label"],
                    "timeframe": "1d",
                    "operator": check["operator"],
                    "right": {"kind": "constant", "value": check["expected"]},
                }
            )
            results.append(
                {
                    "path": path,
                    "result": check["result"],
                    "actual": check["actual"],
                    "expected": check["expected"],
                    "children": [],
                }
            )
            if check.get("mark") and group["id"] != "turtle":
                marks.append({**check["mark"], "path": path})
        if group["id"] == "turtle":
            episodes = group.get("occurrences") or [{"checks": group["checks"]}]
            for hit in episodes:
                mark = hit["checks"][0].get("mark")
                if mark:
                    day = hit.get("date", mark["date"])
                    label = f"海龟突破 · 首次满足 {day}"
                    if hit.get("end_date"):
                        label += f" ～ {hit['end_date']} · 阶段内 {hit['days']} 根日线"
                    if hit.get('breakout_level') is not None:
                        label += f"；固定突破前高 {hit['breakout_level']:g}"
                        label += f"；{hit['ended_on']} 收盘跌破结束" if hit.get('ended_on') else "；截至观察日尚未确认跌破"
                    marks.append({**mark, "date": day, "startDate": day, "periods": 1, "label": label})
        nodes.append(
            {"kind": "group", "logic": "and", "label": group["name"], "children": children}
        )
        evaluations.append({"path": f"root.{i}", "result": "true", "children": results})
    return {
        "run_id": run_id,
        "as_of": as_of,
        "mode": "sequoia",
        "origin": "sequoia",
        "minimum_matches": minimum_matches,
        "confluence_dates": confluence_dates or [],
        "groups": groups,
        "tree": {
            "kind": "group",
            "logic": "at_least" if minimum_matches > 1 else "or",
            "minimumMatches": minimum_matches,
            "label": (f"Sequoia：同日最少满足 {minimum_matches} 个策略 · " if minimum_matches > 1 else "Sequoia：") + " / ".join(g["name"] for g in groups),
            "children": nodes,
        },
        "explanation": {"path": "root", "result": "true", "children": evaluations},
        "marks": marks,
    }


class SequoiaService:
    def __init__(self, database, placement_loader=None, bar_store=None):
        self.bar_store = bar_store
        self.con = database.connection
        self.lock = RLock()
        self.placement_loader = placement_loader or self.load_placements
        self.con.execute("""create table if not exists sequoia_runs (
            run_id varchar primary key, created_at timestamp default current_timestamp,
            status varchar not null, payload json not null)""")
        # A process restart cannot resume a half-computed snapshot safely.
        for run_id, raw in self.con.execute(
            "select run_id, payload from sequoia_runs where status='running'"
        ).fetchall():
            data = json.loads(raw)
            data.update(status="failed", error="服务重启中断了本次计算，请重新运行")
            self.save(data)

    @staticmethod
    def load_placements():
        # Read source directly with a bounded HTTP timeout instead of an unbounded SDK call.
        import requests

        records = []
        page = 1
        while True:
            response = requests.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={
                    "sortColumns": "ISSUE_DATE,SECURITY_CODE",
                    "sortTypes": "-1,-1",
                    "pageSize": 500,
                    "pageNumber": page,
                    "reportName": "RPT_SEO_DETAIL",
                    "columns": "ALL",
                    "source": "WEB",
                    "client": "WEB",
                    "filter": f"(ISSUE_DATE>='{today() - timedelta(days=90)}')",
                },
                timeout=20,
            )
            response.raise_for_status()
            body = response.json()
            result = body.get("result")
            if (
                not body.get("success")
                or not isinstance(result, dict)
                or not isinstance(result.get("data"), list)
            ):
                raise ValueError("东方财富定增数据响应无效")
            for row in result["data"]:
                records.append(
                    {
                        "股票代码": row.get("SECURITY_CODE"),
                        "发行日期": row.get("ISSUE_DATE"),
                        "发行方式": {"1": "定向增发", "2": "公开增发"}.get(
                            str(row.get("SEO_TYPE"))
                        ),
                    }
                )
            if page >= result.get("pages", 1):
                break
            page += 1
            if page > 100:
                raise ValueError("东方财富定增分页异常")
        return records

    def save(self, data):
        self.con.execute(
            "update sequoia_runs set status=?, payload=? where run_id=?",
            [data["status"], json.dumps(data, ensure_ascii=False, allow_nan=False), data["run_id"]],
        )

    def get(self, identifier):
        row = self.con.execute(
            "select payload from sequoia_runs where run_id=?", [identifier]
        ).fetchone()
        if not row:
            raise HTTPException(404, "选股记录不存在")
        return json.loads(row[0])

    def history(self):
        return [
            {k: v for k, v in json.loads(raw).items() if k != "matches"}
            for (raw,) in self.con.execute(
                "select payload from sequoia_runs order by created_at desc limit 30"
            ).fetchall()
        ]

    def start(self, config):
        with self.lock:
            if self.con.execute("select 1 from sequoia_runs where status='running'").fetchone():
                raise HTTPException(409, "已有 Sequoia 筛选在运行，请等待完成")
            if (
                config.group_id
                and not self.con.execute(
                    "select 1 from watchlist_groups where cast(group_id as varchar)=?",
                    [config.group_id],
                ).fetchone()
            ):
                raise HTTPException(422, "自选分组不存在")
            identifier = str(uuid4())
            data = {
                "run_id": identifier,
                "status": "running",
                "progress": 0,
                "message": "读取本地日线",
                "config": config.model_dump(mode="json"),
                "turtle_rule": "relative_volume_limit_close_fixed_level_v2",
                "matches": [],
                "groups": [],
                "universe_size": 0,
            }
            self.con.execute(
                "insert into sequoia_runs(run_id,status,payload) values (?, ?, ?)",
                [identifier, "running", json.dumps(data)],
            )
            return data

    def run(self, identifier):
        data = self.get(identifier)
        try:
            config = RunRequest.model_validate(data["config"])
            as_of = self.con.execute(
                """select max(feature_date) from market_features join symbols using(symbol)
                where timeframe='1d' and feature_version='v1' and feature_date<=?
                and instrument_type='stock'""",
                [config.as_of],
            ).fetchone()[0]
            if not as_of:
                raise ValueError("所选日期之前没有本地日线，请先更新行情")
            data["data_date"] = as_of.isoformat()
            if config.period != "latest":
                from .history import scan_history
                def progress(value, message):
                    data.update(progress=value, message=message)
                    self.save(data)
                data.update(scan_history(self.con, config, as_of, progress, self.bar_store))
                for match in data["matches"]:
                    match["source"] = source_snapshot(identifier, data["data_date"], match["groups"], config.minimum_matches, match.get("confluence_dates"))
                data.update(status="completed", progress=100, message="历史识别完成")
                self.save(data)
                return
            # One bounded SQL read; no full-market network downloads or changes to existing features.
            rows = self.con.execute(
                """select symbol, feature_date, open, high, low, close, volume, amount from (
                select f.*, row_number() over(partition by f.symbol order by feature_date desc) as rn
                from market_features f join symbols s using(symbol)
                where timeframe='1d' and feature_version='v1' and feature_date<=?
                and s.instrument_type='stock') where rn<=251 order by symbol,feature_date""",
                [as_of],
            ).fetchall()
            securities = self.con.execute(
                """select symbol,name,listed_on,delisted_on,is_listed from symbols
                where instrument_type='stock' and (listed_on is null or listed_on<=?)
                and (delisted_on is null or delisted_on>?)""",
                [as_of, as_of],
            ).fetchall()
            universe = {r[0]: r[1] for r in securities if r[4] or r[3] is not None}
            histories = {}
            keys = ["date", "open", "high", "low", "close", "volume", "amount"]
            for symbol, day, *values in rows:
                if symbol in universe:
                    histories.setdefault(symbol, []).append(
                        dict(zip(keys, [day.isoformat(), *values]))
                    )
            current = {s: h for s, h in histories.items() if h[-1]["date"] == data["data_date"]}
            if "turtle" in config.strategies:
                from .limits import attach_turtle_limits
                attach_turtle_limits(self.con, self.bar_store, current,
                                     int(config.parameters.get("turtle", {}).get("window", 20)), latest=True)
            scores = rps_scores(current) if "rps" in config.strategies else {}
            data["rps_universe_size"] = len(scores)
            if config.scope == "watchlist":
                scope = {r[0] for r in self.con.execute("select symbol from watchlist").fetchall()}
                if config.group_id:
                    scope &= {
                        r[0]
                        for r in self.con.execute(
                            "select symbol from watchlist_group_members where cast(group_id as varchar)=?",
                            [config.group_id],
                        ).fetchall()
                    }
                universe = {s: name for s, name in universe.items() if s in scope}
            data["universe_size"] = len(universe)
            data["listing_date_unknown"] = sum(r[2] is None for r in securities if r[0] in universe)
            placements, placement_error = {}, None
            if "placement" in config.strategies:
                data.update(message="查询东方财富定向增发名单", progress=5)
                self.save(data)
                try:
                    placements = placement_dates(
                        self.placement_loader(),
                        config.as_of,
                        int(config.parameters.get("placement", {}).get("days", 7)),
                    )
                except Exception as exc:
                    LOGGER.exception("Sequoia placement data failed")
                    placement_error = f"定增数据获取失败：{exc}"
            stats = {
                s: {
                    "id": s,
                    "name": BY_ID[s]["name"],
                    "matched": 0,
                    "rejected": 0,
                    "unknown": 0,
                    "examples": [],
                    "error": placement_error if s == "placement" else None,
                }
                for s in config.strategies
            }
            for index, (symbol, name) in enumerate(universe.items()):
                groups = []
                history = current.get(symbol)
                for s in config.strategies:
                    if s == "placement" and placement_error:
                        result = unknown(s, placement_error)
                    elif history is None:
                        result = unknown(s, "缺少当前市场日的日线，未将停更行情当作当日信号")
                    else:
                        result = evaluate(
                            s,
                            history,
                            config.parameters.get(s),
                            rps=scores.get(symbol),
                            issuance=placements.get(symbol.split(".")[0]),
                        )
                    key = {"true": "matched", "false": "rejected", "unknown": "unknown"}[
                        result["result"]
                    ]
                    stats[s][key] += 1
                    if key == "matched":
                        groups.append(result)
                    elif key == "unknown" and len(stats[s]["examples"]) < 5:
                        stats[s]["examples"].append({"symbol": symbol, "reason": result["reason"]})
                if len(groups) >= config.minimum_matches:
                    close = history[-1]["close"]
                    previous = history[-2]["close"] if len(history) > 1 else None
                    change = (close / previous - 1) * 100 if close and previous else None
                    data["matches"].append(
                        {
                            "symbol": symbol,
                            "name": name,
                            "close": close,
                            "change_percent": change,
                            "groups": groups,
                            "source": source_snapshot(identifier, data["data_date"], groups, config.minimum_matches),
                        }
                    )
                if index % 250 == 0:
                    data.update(
                        progress=10 + int(85 * (index + 1) / max(1, len(universe))),
                        message=f"已分析 {index + 1} / {len(universe)} 只",
                    )
                    self.save(data)
            data.update(
                status="partial" if placement_error else "completed",
                progress=100,
                message="计算完成",
                groups=[{**stat, "signal_count": sum(
                    any(group["id"] == strategy for group in match["groups"])
                    for match in data["matches"]
                )} for strategy, stat in stats.items()],
                match_count=len(data["matches"]),
            )
        except Exception as exc:
            LOGGER.exception("Sequoia run failed")
            data.update(status="failed", error=str(exc), message="计算失败")
        self.save(data)

    def add_watchlist(self, identifier, payload):
        with self.lock:
            data = self.get(identifier)
            if data["status"] not in ("completed", "partial"):
                raise HTTPException(409, "请等待本次筛选完成")
            matches = {m["symbol"]: m for m in data["matches"]}
            if any(s not in matches for s in payload.symbols):
                raise HTTPException(422, "只能添加本次命中的股票")
            if (
                payload.group_id
                and not self.con.execute(
                    "select 1 from watchlist_groups where cast(group_id as varchar)=?",
                    [payload.group_id],
                ).fetchone()
            ):
                raise HTTPException(422, "目标分组不存在")
            self.con.execute("begin transaction")
            try:
                for symbol in set(payload.symbols):
                    match = matches[symbol]
                    row = self.con.execute(
                        "select sources from watchlist where symbol=?", [symbol]
                    ).fetchone()
                    sources = json.loads(row[0]) if row else []
                    if not any(s["run_id"] == identifier for s in sources):
                        sources.append(match["source"])
                    self.con.execute(
                        """insert into watchlist(symbol,name,sources) values (?,?,?)
                        on conflict(symbol) do update set sources=excluded.sources""",
                        [symbol, match["name"], json.dumps(sources, ensure_ascii=False)],
                    )
                    destinations = [payload.group_id] if payload.group_id else []
                    if payload.by_strategy:
                        for group in match["groups"]:
                            name = "Sequoia · " + group["name"]
                            row = self.con.execute(
                                "select group_id from watchlist_groups where name=?", [name]
                            ).fetchone()
                            group_id = str(row[0]) if row else str(uuid4())
                            if not row:
                                self.con.execute(
                                    "insert into watchlist_groups values (?,?)", [group_id, name]
                                )
                            destinations.append(group_id)
                    for group_id in destinations:
                        self.con.execute(
                            "insert into watchlist_group_members values (?,?) on conflict do nothing",
                            [group_id, symbol],
                        )
                self.con.execute("commit")
            except Exception:
                self.con.execute("rollback")
                raise
            return {"added": len(set(payload.symbols))}
