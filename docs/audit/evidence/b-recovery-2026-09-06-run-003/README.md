# B2 acceptance evidence — 2026-09-06

- Base commit: `f0ec06fa80c9ffad28753827ce9533b080ea5f30`
- Branch: `feat/task-recovery-and-approval-reliability`
- Scope: local durable SQLite checkpoint/receipt stores, real OS `SIGKILL`, MCP
  `run_agent`, loopback Gateway HTTP, live roster reload, Gate expiry, and
  Blackboard Solution invalidation.
- Explicit exclusion: cross-machine recovery is not an acceptance criterion of
  this PR. It requires shared checkpoint/receipt storage plus deployment-level
  failover configuration and will be tracked separately.

`observations.json` 是去标识化的机器可读结果。原始 JUnit XML 由台账中记录的
focused pytest 命令在本机生成；因为它会嵌入本机 hostname，所以保留在本地且不进 Git。
