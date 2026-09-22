from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    wechat_userid: str = Field(min_length=1, max_length=64)


class WecomOAuthRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "Bearer"
    expiresIn: int
    userId: int
    roleCode: str
    dataScope: int