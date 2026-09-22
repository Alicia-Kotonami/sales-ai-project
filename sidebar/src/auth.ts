import { api } from "./api/http";
import type { LoginData } from "./api/types";

const TOKEN_KEY = "salesai.sidebar.token";
const USER_KEY = "salesai.sidebar.user";

export type SessionUser = {
  userId: number;
  roleCode: string;
  dataScope: number;
};

export function getSessionUser(): SessionUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionUser;
  } catch {
    return null;
  }
}

export function persistLogin(data: LoginData): void {
  sessionStorage.setItem(TOKEN_KEY, data.accessToken);
  sessionStorage.setItem(
    USER_KEY,
    JSON.stringify({
      userId: data.userId,
      roleCode: data.roleCode,
      dataScope: data.dataScope,
    } satisfies SessionUser),
  );
}

export function clearSession(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

export function hasSession(): boolean {
  return Boolean(sessionStorage.getItem(TOKEN_KEY));
}

export async function loginByUserid(wechatUserid: string): Promise<LoginData> {
  const data = await api<LoginData>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ wechat_userid: wechatUserid }),
  });
  persistLogin(data);
  return data;
}

export async function loginByWecomCode(code: string): Promise<LoginData> {
  const data = await api<LoginData>("/api/v1/auth/wecom-oauth", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  persistLogin(data);
  return data;
}
