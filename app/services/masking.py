def mask_name(raw: str | None) -> str:
    """姓名脱敏：姓 + *，如 '李*'。"""
    if not raw:
        return ""
    return raw[0] + "*"


def mask_phone(raw: str | None) -> str:
    """手机脱敏：138****5678；长度不足则原样返回带 * 的占位。"""
    if not raw:
        return ""
    if len(raw) < 11:
        return raw[0] + "****" if raw else ""
    return raw[:3] + "****" + raw[-4:]