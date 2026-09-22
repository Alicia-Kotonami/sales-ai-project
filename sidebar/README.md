# 企微智能侧边栏（阶段 E）

独立 H5：Vue 3 + Vite + TypeScript。对接后端已有 `/api/v1/*`，**禁止代发消息**，发送只发生在企微原生窗口。

## 本地运行

先起后端 `http://127.0.0.1:8000`（conda `RAG_study`，库 `salesai-ally`）。

```bash
cd sidebar
npm install
npm run dev
```

浏览器打开：

`http://127.0.0.1:5173/?customerId=3&conversationId=2`

开发登录：`wechat_userid=wx_advisor_002`（顾问刘大伟）。顾问只能看客户 3 / 会话 2。

企微 OAuth：URL 带 `code` 时自动调 `POST /api/v1/auth/wecom-oauth`。未配凭据且 `APP_DEBUG=true` 时，`code` 当作 `wechat_userid`。

画像确认/编辑/驳回需要草稿 ID：`&draftId=画像草稿主键`。后端一期无草稿列表接口，生效画像走 P1。

## 构建

```bash
npm run build
```
