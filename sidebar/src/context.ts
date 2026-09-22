export type CustomerContext = {
  customerId: number;
  conversationId: number;
  draftId: number | null;
};

const DEFAULT_CUSTOMER_ID = 3;
const DEFAULT_CONVERSATION_ID = 2;

function readInt(params: URLSearchParams, key: string): number | null {
  const raw = params.get(key);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function readContextFromUrl(): CustomerContext {
  const params = new URLSearchParams(window.location.search);
  return {
    customerId: readInt(params, "customerId") ?? DEFAULT_CUSTOMER_ID,
    conversationId: readInt(params, "conversationId") ?? DEFAULT_CONVERSATION_ID,
    draftId: readInt(params, "draftId"),
  };
}

export function writeContextToUrl(ctx: CustomerContext): void {
  const params = new URLSearchParams(window.location.search);
  params.set("customerId", String(ctx.customerId));
  params.set("conversationId", String(ctx.conversationId));
  if (ctx.draftId) params.set("draftId", String(ctx.draftId));
  else params.delete("draftId");
  params.delete("code");
  const next = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, "", next);
}

export function consumeOauthCode(): string | null {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  if (!code) return null;
  params.delete("code");
  const qs = params.toString();
  const next = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  window.history.replaceState({}, "", next);
  return code;
}

/** HLD NFR-9：移动端打开侧边栏引导使用 PC 企微。 */
export function isMobileClient(): boolean {
  const ua = navigator.userAgent;
  return /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
}
