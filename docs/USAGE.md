# 工具契约与支持范围

所有数据库调用必须指定连接别名。查询、表结构读取和执行计划还需明确数据库。

| 工具 | 参数 | 返回 |
|---|---|---|
| list_connections | 无 | 别名、环境、允许的数据库、只读模式 |
| test_connection | connection | 版本、TLS、时区、权限诊断提示 |
| list_databases | connection | 允许且可见的数据库 |
| list_tables | connection, database | 表/视图名、类型与注释 |
| describe_table | connection, database, table | kind 区分字段、索引与外键的记录 |
| query | connection, database, sql, params?, max_rows? | 有界结构化结果 |
| explain_query | connection, database, sql, params? | 普通 SELECT 执行计划 |

查询示例：

```json
{
  "connection": "dev",
  "database": "shop",
  "sql": "SELECT id, amount FROM orders WHERE status=:status ORDER BY id LIMIT 20",
  "params": {"status": "paid"},
  "max_rows": 20
}
```

SQL 子集：单条 SELECT、常见 JOIN、子查询、过滤、分组、排序、聚合与常见日期/数值函数。
未知 AST 节点和函数默认拒绝。CTE、UNION、窗口函数、存储过程、存储函数、变量、锁定读取、
文件读写、DML、DDL、用户提示/注释未开放。`--`、`/*`、`#`、`@`、反斜杠即使出现在 SQL 字符串
字面量中也会保守拒绝，这些值可通过参数传递。不要用这种限制宣称覆盖整个 MySQL 方言。

参数使用 `:name`，params 为 JSON 标量对象。解析后由受控生成器输出 MySQL SQL，并通过 PyMySQL
绑定值；参数不能替代数据库、表或列名。同名参数可出现多次，缺失和多余参数均拒绝。

响应包含 ok、request_id、connection、database、elapsed_ms；查询响应还包含 columns、rows、
returned_rows、truncated、warnings。按 columns 与 rows 的位置关联字段，重复列名不会覆盖。
错误返回 ok=false 和 error.code/error.message，不返回原始驱动异常或敏感参数。

DECIMAL 和超过安全整数范围的 BIGINT 使用字符串；NULL 保持 null。二进制字段以标明编码的 base64 返回。
长字段截断时 fields_truncated=true。会话时区设为 UTC；TIMESTAMP 按 UTC 读取，DATETIME 保留原存储值。

默认最多返回 200 行，允许请求最多 1,000 行；响应默认最多 1 MiB，单字段文本最多 8 KiB。
返回上限不等于数据库扫描量上限。非缓冲游标避免累计整个结果集，但驱动仍需读取单行/单个 MySQL 包，
因此响应字节上限不构成进程内存的硬限制。不要从大 BLOB 列查询完整数据。

每个连接配置最多 2 个执行任务、4 个等待任务，全进程最多 8 个工作线程。
默认队列等待 5 秒、连接建立 5 秒、只读 SELECT 服务端限制 10 秒。
应用总预算、网络超时和服务端超时协同工作，无法保证任意网络或数据库故障瞬时终止。
Python task 取消后，实际工作线程退出前继续占用执行配额。

每次任务独立创建和关闭连接，固定 SQL_MODE、UTC 和 session transaction read only；不复用异常连接。
只读账号的授权是独立边界。视图/角色权限分析仅给提示，不宣称完整权限证明。

数据和表注释属于不可信内容；本地 MCP 只控制自己执行的 SQL，不能控制宿主通过其他账号/工具访问数据库。
返回给工具调用者的数据会进入 AI 会话。日志只保存操作类型、耗时、状态、SQL 指纹等诊断信息。
