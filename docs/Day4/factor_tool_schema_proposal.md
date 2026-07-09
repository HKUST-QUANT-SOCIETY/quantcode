# Day 4 · factor 工具(match_main / gen_schema)输入字段提案

> Owner: 尹一帆(stub 侧) ⇄ Lead(陈镇鸿,Day 4 §6 真 LLM 接入)
> 同步状态: **草案,待与 Lead 拍板**
> 配套代码:
> - `quantcode/tools/factor/match_main_stub.py`(待新建)
> - `quantcode/tools/factor/gen_schema_stub.py`(待新建)

---

## 1. 背景

Day 4 §2 / §6 要求:
- §2(尹一帆):factor tool 注册进 registry,AgentRunner(group="factor") 跑通 `match_main → gen_schema(≥3 步自主推理)`
- §6(Lead):程序化验收闭环 + match_main / gen_schema 接真 LLM,Lead 接 LLM 时**不动 schema 只换 `_execute` 函数体**

关键约束:**字段契约必须稳定**。我先写 stub 跑通 AgentRunner 流程,Lead 接真 LLM 时不能破 schema(否则 AgentRunner 调用失败,所有因子工作流崩)。

---

## 2. 提案字段(待 Lead 拍板)

### 2.1 `MatchMainArgs`(match_main tool)

```python
class MatchMainArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048)        # 因子想法描述
    extra_context: dict[str, Any] | None = None            # 透传:已有因子列表/主线函数签名等
```

**字段说明**:
- `idea`:必填,因子想法文本(如 "PB-ROE 因子,季度再平衡")
- `extra_context`:可选透传字段,Lead 接真 LLM 时可塞入:
  - `existing_factors: list[dict]` — 已有因子列表(避免重复)
  - `mainline_signatures: list[str]` — 主线函数签名(AST 提取)
  - `history: list[dict]` — 最近几次失败记录
  - 任何 Lead 需要的上下文

**为什么加 `extra_context`**:这是"未来安全网"。Day 4 stub 阶段不读这个字段,Lead 接真 LLM 时如果需要新字段,**只需要在 stub / 真 LLM 实现里读 extra_context 的子字段,不用动 schema**。

### 2.2 `GenSchemaArgs`(gen_schema tool)

```python
class GenSchemaArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea: str = Field(min_length=1, max_length=2048)        # 因子想法描述(冗余但可读)
    match_result: dict[str, Any]                            # match_main 的完整输出
    extra_context: dict[str, Any] | None = None            # 透传
```

**字段说明**:
- `idea`:冗余字段,跟 match_main 的 idea 保持一致(LLM 决策时更直观,不需要从 match_result 倒推)
- `match_result`:`match_main_tool` 的完整返回 dict(包含 `compatible` / `suggested_fields` / `notes` 等),让 `gen_schema` 能基于 match 结果生成 schema
- `extra_context`:同上,Lead 可塞入额外上下文

### 2.3 `AutoevalArgs`(autoeval tool)

```python
class AutoevalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]                                    # gen_schema 生成的 FactorSpec 序列化
```

**字段说明**:只有一个 `spec` 字段(因为 autoeval 是固定流程:接 FactorSpec → 调 AutoEval API),**不需要 `extra_context`**。如果 Lead 接真 AutoEval API 时需要额外参数(API key 之外的),可以加 `extra_context: dict | None = None`,但建议**Day 4 stub 阶段不加,等真有需求再补**。

---

## 3. stub 阶段实现(我的工作)

### 3.1 `match_main_stub.py`

```python
from pydantic import BaseModel, ConfigDict, Field
from typing import Any
from tools.registry import ToolDef

class MatchMainArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea: str = Field(min_length=1, max_length=2048)
    extra_context: dict[str, Any] | None = None

def _match_main_execute(args: MatchMainArgs, ctx: dict) -> dict[str, Any]:
    """stub: 固定返回 + TODO 标记。
    后续接真 LLM 时,只需替换此函数体(读 args.idea + args.extra_context),
    schema 不变,registry 不变,AgentRunner 不变。
    """
    return {
        "compatible": True,
        "suggested_fields": ["pb", "roe", "quarterly_rebalance"],
        "notes": "Day 4 stub: 固定返回,Lead 接真 LLM 时替换此函数",
    }

match_main_tool = ToolDef(
    id="match_main",
    description="Given a factor idea, return matching fields & suggested spec.",
    schema=MatchMainArgs,
    execute=_match_main_execute,
)
```

### 3.2 `gen_schema_stub.py`

```python
class GenSchemaArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea: str = Field(min_length=1, max_length=2048)
    match_result: dict[str, Any]
    extra_context: dict[str, Any] | None = None

def _gen_schema_execute(args: GenSchemaArgs, ctx: dict) -> dict[str, Any]:
    """stub: 固定返回 FactorSpec dict。
    Lead 接真 LLM 时替换函数体。
    """
    return {
        "name": args.idea.replace(" ", "_").lower()[:32],
        "formula": "pb * roe",  # stub 硬编码
        "fields": args.match_result.get("suggested_fields", []),
        "rebalance": "quarterly",
    }

gen_schema_tool = ToolDef(
    id="gen_schema",
    description="Generate a FactorSpec from idea + match result.",
    schema=GenSchemaArgs,
    execute=_gen_schema_execute,
)
```

### 3.3 `autoeval_stub.py`

```python
from quantcode.flows.factor_autoeval import MOCK_AUTOEVAL_PAYLOAD_V1

class AutoevalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict[str, Any]

def _autoeval_execute(args: AutoevalArgs, ctx: dict) -> dict[str, Any]:
    """stub: 直接返回 MOCK_AUTOEVAL_PAYLOAD_V1 共享常量。
    Lead 接真 AutoEval API 时替换此函数体,只调 autoeval_client.submit(args.spec)。
    """
    return dict(MOCK_AUTOEVAL_PAYLOAD_V1)

autoeval_tool = ToolDef(
    id="autoeval",
    description="Submit a FactorSpec to AutoEval and return metrics.",
    schema=AutoevalArgs,
    execute=_autoeval_execute,
)
```

**关键**:`autoeval_stub` 不直接调 `flows/factor_autoeval.py:call_autoeval_api(state)` —— 那个函数接 state 不是 `(args, ctx)`,签名不匹配。stub 阶段通过共享常量 `MOCK_AUTOEVAL_PAYLOAD_V1` 解耦(Lead 接真 LLM 时只需替换 `flows/factor_autoeval.py:call_autoeval_api` 函数体,`autoeval_stub` 自动跟新)。

---

## 4. Lead 需要拍板的点

1. **`MatchMainArgs` 是否加 `extra_context`?**
   - 加:Lead 接真 LLM 时可塞入已有因子 / 主线签名 / 历史,Day 4 stub 不读
   - 不加:Lead 改 schema 即可(只动 Day 4 后 1 次)
   - **建议加**(未来安全网,代价 0)

2. **`GenSchemaArgs` 是否加 `extra_context`?**
   - 建议加,理由同上

3. **`AutoevalArgs` 是否加 `extra_context`?**
   - 建议**Day 4 不加**,等 Lead 接真 AutoEval API 时如有需求再补
   - 理由:autoeval 是固定流程,字段稳定,过度预留反而可能让 schema 跟实际需求脱节

4. **字段命名是否一致?**
   - `idea`(所有 tool 都有)— 建议保留
   - `match_result`(gen_schema 才有)— 建议保留
   - `spec`(autoeval 才有)— 建议保留
   - `extra_context`(可选透传)— 建议保留
   - Lead 接 LLM 时如有不同命名习惯,提出来讨论

---

## 5. 时间表

- **今开工前(30 分钟会议)**:Lead 看完本文档,反馈 §4 四个问题
- **我方立刻开 T0**:基于 Lead 拍板的字段写 stub,如有调整 5 分钟内跟进
- **Lead 接真 LLM 时间表**:Day 4 §6 是程序化验收闭环(自动 merge/reject),match_main/gen_schema 接 LLM 排 Day 4 下午 / Day 5

---

## 6. 同步产物

- 同意 / 不同意 / 部分修改请直接回复
- 拍板后我立即开 T0 写 stub + 注册 + AgentRunner 跑通
- 测试用例 `tests/test_factor_stub_tools.py:test_match_main_stub_returns_expected_shape` 会覆盖 stub 返回结构
- Lead 接真 LLM 后,`test_autoeval_payload_parity_with_factor_autoeval_flows` 仍能跑(stub 跟 flows 共享 `MOCK_AUTOEVAL_PAYLOAD_V1` 键集合一致)
