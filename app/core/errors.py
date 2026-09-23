from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0

    # 4xxx 客户端
    PARAM_INVALID = 1001          # 参数校验失败
    UNAUTHENTICATED = 1002        # 未认证 / token 过期
    FORBIDDEN = 1003              # 无权限（功能或数据范围）
    NOT_FOUND = 1004              # 资源不存在
    TAG_NOT_IN_CATALOG = 1005     # 非固定关键标签 / 禁止自由输入

    # 2xxx 业务状态
    STATE_CONFLICT = 2001         # 状态机非法流转（如重复确认）

    # 5xxx 服务端
    AI_BUSY = 5001                # AI 服务暂忙
    AI_TIMEOUT = 5002             # AI 推理超时（>3s 熔断）
    ASR_FAILED = 5003             # ASR 转写失败

    # 52xx 二期知识库 / Agent
    KB_NOT_READY = 5201           # 知识库未就绪 / 发布冲突
    AGENT_DISABLED = 5202         # 综合推理已关停
    AGENT_RUN_INVALID = 5203      # Agent Run 不可操作
    KB_PARSE_FAILED = 5204        # 向量/解析任务失败

    # 9xxx
    WECOM_SIGN_INVALID = 9001     # 企微回调验签失败
    UNKNOWN = 9999                # 未知服务端错误


# 错误码 -> HTTP 状态码映射
HTTP_STATUS_MAP: dict[int, int] = {
    ErrorCode.OK: 200,
    ErrorCode.PARAM_INVALID: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.TAG_NOT_IN_CATALOG: 400,
    ErrorCode.STATE_CONFLICT: 409,
    ErrorCode.AI_BUSY: 503,
    ErrorCode.AI_TIMEOUT: 504,
    ErrorCode.ASR_FAILED: 503,
    ErrorCode.KB_NOT_READY: 409,
    ErrorCode.AGENT_DISABLED: 503,
    ErrorCode.AGENT_RUN_INVALID: 409,
    ErrorCode.KB_PARSE_FAILED: 500,
    ErrorCode.WECOM_SIGN_INVALID: 401,
    ErrorCode.UNKNOWN: 500,
}


class BizError(Exception):
    """业务异常：所有可预期的错误都通过它抛出。"""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        *,
        http_status: int | None = None,
    ) -> None:
        self.code = int(code)
        self.message = message or self.default_message(self.code)
        self.http_status = http_status or HTTP_STATUS_MAP.get(self.code, 500)
        super().__init__(self.message)

    @staticmethod
    def default_message(code: int) -> str:
        return {
            ErrorCode.PARAM_INVALID: "参数校验失败",
            ErrorCode.UNAUTHENTICATED: "未认证或登录已过期",
            ErrorCode.FORBIDDEN: "无权限访问",
            ErrorCode.NOT_FOUND: "资源不存在",
            ErrorCode.TAG_NOT_IN_CATALOG: "非固定关键标签",
            ErrorCode.STATE_CONFLICT: "状态机非法流转",
            ErrorCode.AI_BUSY: "AI 服务暂忙，请稍后重试",
            ErrorCode.AI_TIMEOUT: "AI 推理超时",
            ErrorCode.ASR_FAILED: "语音识别失败",
            ErrorCode.KB_NOT_READY: "知识库未就绪或发布冲突",
            ErrorCode.AGENT_DISABLED: "综合推理已关停",
            ErrorCode.AGENT_RUN_INVALID: "推理任务不可操作",
            ErrorCode.KB_PARSE_FAILED: "知识库解析失败",
            ErrorCode.WECOM_SIGN_INVALID: "企微回调验签失败",
            ErrorCode.UNKNOWN: "服务端未知错误",
        }.get(code, "未知错误")