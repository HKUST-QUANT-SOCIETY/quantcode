"""Admin 中枢工具（P-08）——Admin 角色专属的跨组只读查询面。

实现与注册在 ``tools.admin._register``（标准 registry 通道 + _meta 元工具，
与 runner/distill/cards.py 的 list_capabilities 同模式）：
- ``admin_list_runs``         跨组 run 聚合（组→人/线程→状态/错误）
- ``admin_errors``            错误沉淀汇总
- ``admin_blackboard_read``   Blackboard 跨组只读
- ``admin_repo_status``       GitHub org repo 状态（GitGraph 面板数据源，AG-K）
- ``admin_package_updates``   依赖文件更新检测（双类 pop 之 package pop 数据源）
- ``ssh_status``              SSH 连接配置状态（后端实现在 runner/server_ssh.py，AG-F）

权限边界：五个 ``admin_*`` 工具运行时经 ``runner.admin_scope.is_admin`` 门禁
（Admin 是角色不是第七组，见该模块 docstring）；非 Admin 返回领域拒绝
``{"ok": False, "error": "admin only"}``（不抛异常，保证原因对 LLM 可见）。
"""
