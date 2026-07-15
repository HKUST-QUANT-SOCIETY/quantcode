"""autoeval tool — Day 5 Lead 真API实现。

调用auto_factor_evaluation API提交FactorSpec并获取评估结果。
保持与stub相同的schema，只替换_execute函数体。

TODO: 需要真实的AutoEval API endpoint
- 当前使用降级模式（返回mock数据）
- 实际部署需要从团队获取API地址和认证信息
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tools.registry import ToolDef

# 降级时使用的mock数据
from flows.factor_autoeval import MOCK_AUTOEVAL_PAYLOAD_V1


class AutoevalArgs(BaseModel):
    """autoeval tool 的入参 schema。"""

    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(description="gen_schema 生成的 FactorSpec 序列化")


def _autoeval_execute(args: AutoevalArgs, ctx: dict) -> dict[str, Any]:
    """真API实现：提交FactorSpec到AutoEval服务并返回评估结果。"""
    import os
    import json

    # TODO: 从配置或环境变量读取AutoEval API endpoint
    autoeval_api_url = os.environ.get('AUTOEVAL_API_URL')
    autoeval_api_key = os.environ.get('AUTOEVAL_API_KEY')

    if autoeval_api_url and autoeval_api_key:
        try:
            import requests

            # 调用真实AutoEval API
            response = requests.post(
                f"{autoeval_api_url}/evaluate",
                headers={
                    "Authorization": f"Bearer {autoeval_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "factor_spec": args.spec,
                    "version": "v1",
                },
                timeout=120,  # AutoEval可能需要较长时间
            )

            response.raise_for_status()
            result = response.json()

            # 验证返回字段
            required_fields = ['ic_mean', 'ic_std', 'ir', 't_stat', 'turnover_monthly']
            for field in required_fields:
                if field not in result:
                    raise ValueError(f"AutoEval API返回缺少必需字段: {field}")

            return result

        except Exception as e:
            # API调用失败，记录错误并降级
            print(f"⚠️ AutoEval API调用失败: {e}")
            print(f"降级使用mock数据")

    # 降级模式：返回mock数据
    result = dict(MOCK_AUTOEVAL_PAYLOAD_V1)

    # 根据spec动态调整部分字段
    factor_name = args.spec.get('name', 'unnamed')
    result['eval_run_id'] = f"{factor_name}-mock-eval"

    # 如果spec中有forward_return_horizon，更新horizons
    if 'forward_return_horizon' in args.spec:
        horizon = args.spec['forward_return_horizon']
        result['horizons'] = [1, horizon, 20]

    # 标记为降级数据
    result['_is_mock'] = True
    result['_reason'] = 'AutoEval API not configured or unavailable'

    return result


autoeval_tool = ToolDef(
    id="autoeval",
    description=(
        "Submit a FactorSpec to AutoEval and return metrics (ic / ir / t_stat / turnover / etc). "
        "Use this after gen_schema has produced a valid FactorSpec."
    ),
    schema=AutoevalArgs,
    execute=_autoeval_execute,
)


__all__ = ["AutoevalArgs", "autoeval_tool"]
