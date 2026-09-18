from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    wechat_userid: str = Field(min_length=1, max_length=64)



"""
真实项目会走企微 OAuth。
这一步先做“模拟登录”：输入 wechat_userid，系统查 sys_user，签发 JWT。
后面接企微 OAuth 再换这一层。
"""
class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "Bearer"
    expiresIn: int
    userId: int
    roleCode: str
    dataScope: int