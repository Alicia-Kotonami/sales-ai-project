"""企微回调接口：验签 / 解密委托 ``wecom_client``，本层只做 HTTP 适配。"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

from app.services import wecom_client

router = APIRouter(prefix="/wecom", tags=["wecom"])


@router.get("/callback")
async def wecom_callback_verify(
    msg_signature: str | None = Query(default=None),
    timestamp: str | None = Query(default=None),
    nonce: str | None = Query(default=None),
    echostr: str | None = Query(default=None),
):
    """
    D1 GET：企微 URL 验证。成功必须回明文（非 JSON）。
    """
    plain = wecom_client.verify_url(
        msg_signature=msg_signature,
        timestamp=timestamp,
        nonce=nonce,
        echostr=echostr,
    )
    return PlainTextResponse(plain)


@router.post("/callback")
async def wecom_callback_event(
    request: Request,
    msg_signature: str | None = Query(default=None),
    timestamp: str | None = Query(default=None),
    nonce: str | None = Query(default=None),
):
    """
    D1 POST：验签 + 解密，打桩返回 ok。禁止代发消息。
    """
    body = await request.body()
    text = await wecom_client.handle_callback(
        msg_signature=msg_signature,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return PlainTextResponse(text)
