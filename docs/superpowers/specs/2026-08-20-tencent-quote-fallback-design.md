# 腾讯实时行情备用源设计

## 目标

在不改变历史 K 线、回测数据和存储结构的前提下，为 A 股实时 `Quote`
增加腾讯行情备用源。`mootdx` 不可连接、请求报错或返回数据不完整时，
系统自动切换到腾讯，保证监控价格点位的基础可用性。

## 范围

- 新增纯 Python 的 `TencentQuoteProvider`，直接请求
  `https://qt.gtimg.cn/q=<symbols>`。
- 新增组合型 `FallbackQuoteProvider`，按 `mootdx -> tencent` 的固定顺序查询。
- CLI 的实时行情冒烟测试默认验证自动回退链路，同时保留单独验证
  `mootdx` 和 `tencent` 的能力。
- 不增加 Node.js 或 `stock-sdk` 运行时依赖。
- 不把腾讯用作回测历史数据源；历史 K 线继续由 BaoStock 和现有聚合层提供。
- 不在本次引入更多实时数据源、循环器、飞书发送或监控规则。

## 架构与边界

`TencentQuoteProvider` 和 `MootdxProvider` 都实现现有 `QuoteProvider` 协议。
`FallbackQuoteProvider` 接收按优先级排列的 provider 工厂，只负责延迟构造和
回退编排，不解析任何供应商数据，也不修改 `Quote` 领域模型。使用工厂而不是
预先构造的实例，可以捕获 `MootdxProvider` 在建立连接阶段的失败并继续回退。

```text
监控/CLI
   |
   v
FallbackQuoteProvider
   |-- 1. MootdxProvider ------> Quote(source="mootdx")
   `-- 2. TencentQuoteProvider -> Quote(source="tencent")
```

这个边界使后续的点位监控只依赖 `QuoteProvider`，无需知道本次实际命中了
哪个数据源。`Quote.source` 保留真实来源，便于日志和故障诊断。

## 腾讯数据归一化

- 证券代码：`600519.SH -> sh600519`、`000001.SZ -> sz000001`、
  `920xxx.BJ -> bj920xxx`。不支持的交易所后缀直接报参数错误。
- 字符编码：按腾讯响应的 GBK 解码，逐行解析 `~` 分隔字段。
- 完整性：只接受请求中的代码，且字段数至少覆盖索引 37。空行、
  无匹配占位行和截断行不生成伪造的零值行情。
- 价格：字段 3，单位为元。
- 时间：字段 30，格式 `yyyyMMddHHmmss`，解析为
  `Asia/Shanghai` 时区时间，不使用本机当前时间代替行情时间。
- 成交量：字段 36，腾讯口径为手，乘以 100 存入 `volume_shares`。
- 成交额：字段 37，腾讯口径为万元，乘以 10,000 存入
  `amount_cny`。
- 来源：固定为 `tencent`。

## 请求与错误处理

`TencentQuoteProvider` 使用 Python 标准库 `urllib.request`，不增加第三方依赖。
底层 transport 是可注入的可调用对象，生产实现设置有限超时，不在适配器内无限
重试。HTTP 失败、解码失败或核心字段非法时抛出带上下文的
`TencentQuoteError`。

`FallbackQuoteProvider` 的行为如下：

1. 调用第一个 provider。
2. 如果构造或请求报错，或者返回结果没有覆盖全部请求代码，调用下一个
   provider。
3. 任一 provider 返回完整数据后立即返回，不合并多源结果。
4. 所有 provider 失败时抛出统一 `QuoteProviderError`，错误中保留每个
   provider 的失败原因。
5. 空的证券代码列表直接返回空列表，不发网络请求。

不做“部分代码混合回填”：同一次查询全部使用同一数据源，避免时间戳和
口径不一致。任一请求代码缺失都触发整批回退；本次不引入跨源合并算法。

## CLI

`astock data smoke --provider` 支持：

- `auto`：默认选项，使用 `mootdx -> tencent` 自动回退链。
- `mootdx`：只验证 mootdx，用于故障诊断。
- `tencent`：只验证腾讯，用于故障诊断。

成功输出实际 `Quote.source`、价格和行情时间，避免把回退成功误报为 mootdx 成功。

## 测试与验收

单元测试必须先失败、再由最小实现使其通过，覆盖：

- 沪、深、北证券代码转换。
- 腾讯多行 GBK 响应的字段解析和请求顺序保持。
- 行情时间、手到股、万元到元的精确换算。
- 无匹配、截断行、非法数字和 HTTP 失败。
- 主源成功时不调用备用源。
- 主源构造/请求报错或返回结果不完整时调用腾讯。
- 所有数据源失败时保留完整的失败上下文。
- CLI 的 `auto` 默认值和真实来源输出。

完整验收条件：

1. 全部 pytest 通过，新增行为有回归测试。
2. Ruff 和 `git diff --check` 通过。
3. 独立腾讯在线冒烟测试返回 `600519.SH` 的正价格、正时间戳和非负成交量/成交额。
4. 在主源模拟失败时，在线 `auto` 冒烟测试返回 `source=tencent`。

## 风险与限制

腾讯该公开端点没有面向本项目的服务等级承诺，字段结构也不是正式稳定的
商业 API 合约。因此适配器必须严格验证行完整性，失效时明确报错，不能生成
伪数据。它适合当前的价格点位监控，不适合高频或交易执行级别的决策。
