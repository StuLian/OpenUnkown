"""MCP Tool 的 JSON Schema 到 LangChain StructuredTool 的转换逻辑。"""
from __future__ import annotations

from typing import Any

from pydantic import Field, create_model


def json_type_to_py_type(prop_spec: dict) -> type:
    """将 JSON Schema 数据类型映射为 Python 类型。"""
    t = prop_spec.get("type")
    if t == "string":
        return str
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    if t == "array":
        return list
    if t == "object":
        return dict
    return Any


def create_args_schema(model_name: str, input_schema: dict) -> type:
    """根据 MCP Tool 的 inputSchema 动态构建 Pydantic 模型用于参数校验和文档生成。"""
    if not input_schema or not isinstance(input_schema, dict):
        return create_model(model_name)

    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    fields: dict[str, Any] = {}

    for prop_name, prop_spec in properties.items():
        if not isinstance(prop_spec, dict):
            continue
        py_type = json_type_to_py_type(prop_spec)
        is_req = prop_name in required
        desc = prop_spec.get("description", "")

        if is_req:
            fields[prop_name] = (py_type, Field(default=..., description=desc))
        else:
            fields[prop_name] = (py_type | None, Field(default=None, description=desc))

    return create_model(model_name, **fields)
