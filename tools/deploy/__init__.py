"""tools.deploy — P-09 /deploy 黑盒部署适配（AG-H）。

对外最小面：
- ``DeployResult``      部署结果契约（黑盒字段面，extra="forbid"）
- ``DeployAdapter``     适配器协议（真 AlphaFlow 适配器实现它即可替换占位）
- ``StagingDeployAdapter``  staging 占位实现（真适配器 blocked 待世杰）

工具注册在 ``tools.deploy._register``（import 触发，mcp_server 接线移交 AG-D）。
"""
from tools.deploy.adapter import DeployAdapter, DeployResult
from tools.deploy.staging_adapter import StagingDeployAdapter

__all__ = ["DeployAdapter", "DeployResult", "StagingDeployAdapter"]
