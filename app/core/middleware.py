import json
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# 响应头里使用的 trace_id 字段名
TRACE_ID_HEADER = "X-Trace-Id"
# 挂到 request.state 上的属性名
TRACE_ID_KEY = "trace_id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    """
    为每个请求生成 / 透传 trace_id，并把它：
    1. 放进 request.state.trace_id，方便业务代码通过 get_trace_id(request) 读取；
    2. 写进响应头 X-Trace-Id，方便网关、Nginx、APM 抓取；
    3. 注入到 JSON 响应的 body 里，方便前端直接在弹窗展示。

    注意：
    - SSE（text/event-stream）响应不会被修改，避免破坏流式协议；
    - 修改 body 后必须删掉旧的 Content-Length，否则 Starlette 会抛
      `RuntimeError: Response content longer than Content-Length`。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1) 决定 trace_id：客户端传了就沿用，否则本地生成一个 16 位 hex
        trace_id = request.headers.get(TRACE_ID_HEADER) or uuid.uuid4().hex[:16]

        # 2) 挂到 request.state，供下游异常处理器 / 业务接口读取
        request.state.trace_id = trace_id

        # 3) 先让请求继续往下走，拿到原始响应
        response = await call_next(request)

        # 4) 无论如何，把 trace_id 写进响应头
        response.headers[TRACE_ID_HEADER] = trace_id

        # 5) 只处理 JSON 响应；SSE、文件下载等一律跳过
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            # 5.1) 把原始 body 读干净（body_iterator 只能迭代一次）
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            # 5.2) 尝试解析 JSON，往字典里补 trace_id
            try:
                data = json.loads(body)
                if isinstance(data, dict) and "trace_id" not in data:
                    data["trace_id"] = trace_id
                # ensure_ascii=False：保留中文，避免变成 \uXXXX
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            except Exception:
                # 不是合法 JSON（比如空 body），保持原样
                pass

            # 5.3) 复制响应头，准备构造新的 Response
            headers = dict(response.headers)

            # 5.4) 关键：body 长度已变，旧的 Content-Length 必须删掉
            #      否则 Starlette 会检测到长度不匹配并抛 RuntimeError
            headers.pop("content-length", None)

            # 5.5) 重新声明 content-type，明确 charset=utf-8
            headers["content-type"] = "application/json; charset=utf-8"

            # 5.6) 用新 body 构造 Response
            #      media_type=None：不要让它覆盖我们刚设置的 content-type
            response = Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=None,
            )

        return response


def get_trace_id(request: Request) -> str | None:
    """
    给业务代码 / 异常处理器使用：
    从 request.state 里取 trace_id，取不到返回 None。
    """
    return getattr(request.state, TRACE_ID_KEY, None)