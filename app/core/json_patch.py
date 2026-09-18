from typing import Any


def json_patch(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    """
    生成一个简易 JSON Patch 数组（仅 add / replace / remove 三种 op）。
    对齐 RFC 6902 常见子集，够我们审计用。
    """
    ops: list[dict[str, Any]] = []

    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() - new.keys():
            ops.append({"op": "remove", "path": f"{path}/{key}"})
        for key in new.keys() - old.keys():
            ops.append({"op": "add", "path": f"{path}/{key}", "value": new[key]})
        for key in old.keys() & new.keys():
            ops.extend(json_patch(old[key], new[key], f"{path}/{key}"))
        return ops

    if old != new:
        ops.append({"op": "replace", "path": path or "/", "value": new})
    return ops