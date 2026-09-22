<script setup lang="ts">
import { computed, ref } from "vue";
import { api, ApiError, getToken } from "../api/http";
import { postSseWithReconnect, type SseEvent } from "../api/sse";
import type { SuggestDone } from "../api/types";
import AiWatermark from "./AiWatermark.vue";

const props = defineProps<{
  customerId: number;
  conversationId: number;
}>();

const messageText = ref("数学怎么收费");
const msgType = ref<"text" | "audio">("text");
const audioUrl = ref("oss://msg/demo.amr");
const streaming = ref(false);
const reconnectHint = ref("");
const lastEventId = ref("");
const error = ref("");
const notice = ref("");
const asrText = ref("");
const scenarioTags = ref<string[]>([]);
const eventId = ref<number | null>(null);
const texts = ref<Record<number, string>>({});
const edited = ref<Record<number, string>>({});
const busyId = ref<number | null>(null);
let abortCtl: AbortController | null = null;

const candidates = computed(() =>
  Object.keys(texts.value)
    .map(Number)
    .sort((a, b) => a - b),
);

function onSse(evt: SseEvent): void {
  if (evt.id) lastEventId.value = evt.id;
  const data = evt.data as Record<string, unknown>;
  if (evt.event === "asr_result") {
    asrText.value = String(data.text ?? "");
    return;
  }
  if (evt.event === "suggest_chunk") {
    const cid = Number(data.candidateId);
    const delta = String(data.delta ?? "");
    texts.value = { ...texts.value, [cid]: (texts.value[cid] || "") + delta };
    return;
  }
  if (evt.event === "suggest_done") {
    const done = data as unknown as SuggestDone;
    eventId.value = done.eventId;
    scenarioTags.value = done.scenarioTags || [];
    reconnectHint.value = "";
    return;
  }
  if (evt.event === "suggest_error") {
    const code = data.code;
    error.value = `AI 错误 ${code ?? ""}：${String(data.message ?? "暂忙")}`;
  }
}

async function generate(): Promise<void> {
  abortCtl?.abort();
  abortCtl = new AbortController();
  streaming.value = true;
  error.value = "";
  notice.value = "";
  asrText.value = "";
  scenarioTags.value = [];
  eventId.value = null;
  texts.value = {};
  edited.value = {};
  reconnectHint.value = "";
  lastEventId.value = "";

  const currentMessage =
    msgType.value === "audio"
      ? { type: "audio", audioUrl: audioUrl.value, text: messageText.value || "" }
      : { type: "text", text: messageText.value };

  try {
    await postSseWithReconnect({
      url: "/api/v1/reply/suggestions/stream",
      body: {
        conversationId: props.conversationId,
        customerId: props.customerId,
        currentMessage,
      },
      token: getToken(),
      lastEventId: lastEventId.value || undefined,
      signal: abortCtl.signal,
      onEvent: onSse,
      onRetryWait: (ms) => {
        reconnectHint.value = `SSE 断开，${ms / 1000}s 后重连（Last-Event-ID: ${lastEventId.value || "无"}）`;
      },
      isTerminal: (event) => event === "suggest_done" || event === "suggest_error",
    });
  } catch (e) {
    if (!(e instanceof DOMException && e.name === "AbortError")) {
      error.value = e instanceof Error ? e.message : "拉流失败";
    }
  } finally {
    streaming.value = false;
  }
}

function stop(): void {
  abortCtl?.abort();
  streaming.value = false;
}

function textOf(cid: number): string {
  return edited.value[cid] ?? texts.value[cid] ?? "";
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    notice.value = "复制失败，请手动划选";
  }
}

async function feedback(cid: number, action: "adopt_and_send_manually" | "reject"): Promise<void> {
  if (!eventId.value) {
    error.value = "尚未生成完成，无法回写";
    return;
  }
  const finalText = textOf(cid);
  if (action === "adopt_and_send_manually" && !finalText.trim()) {
    error.value = "采纳时文案不能为空";
    return;
  }
  busyId.value = cid;
  error.value = "";
  try {
    await api(`/api/v1/reply/suggestions/${eventId.value}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        candidateId: cid,
        action,
        finalText: action === "adopt_and_send_manually" ? finalText : undefined,
      }),
    });
    if (action === "adopt_and_send_manually") {
      await copyText(finalText);
      notice.value = "已采纳并复制。请到企微原生聊天窗口手动发送，本侧边栏禁止代发。";
    } else {
      notice.value = "已拒绝该建议";
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "回写失败";
  } finally {
    busyId.value = null;
  }
}
</script>

<template>
  <section class="card">
    <h2>回复建议</h2>
    <p class="muted">SSE 流式 · 采纳后仅复制，发送只发生在企微窗口</p>
    <div class="row">
      <div class="field">
        <label>消息类型</label>
        <select v-model="msgType">
          <option value="text">text</option>
          <option value="audio">audio</option>
        </select>
      </div>
    </div>
    <div class="field" style="margin-top: 6px">
      <label>{{ msgType === "audio" ? "语音转写占位 / 原文" : "家长最新消息" }}</label>
      <textarea v-model="messageText" rows="2" />
    </div>
    <div v-if="msgType === 'audio'" class="field" style="margin-top: 6px">
      <label>audioUrl</label>
      <input v-model="audioUrl" />
    </div>
    <div class="row" style="margin-top: 8px">
      <button class="btn primary" type="button" :disabled="streaming" @click="generate">生成建议</button>
      <button class="btn" type="button" :disabled="!streaming" @click="stop">停止</button>
    </div>
    <p v-if="reconnectHint" class="muted">{{ reconnectHint }}</p>
    <p v-if="lastEventId" class="muted">Last-Event-ID {{ lastEventId }}</p>
    <p v-if="asrText" class="muted">ASR：{{ asrText }}</p>
    <p v-if="scenarioTags.length" class="muted">场景 {{ scenarioTags.join(" / ") }} · eventId {{ eventId }}</p>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="notice" class="ok">{{ notice }}</p>

    <div class="list" style="margin-top: 8px">
      <AiWatermark v-for="cid in candidates" :key="cid">
        <div class="item" style="border: none; padding-top: 22px">
          <div class="muted">候选 {{ cid }}</div>
          <textarea
            :value="textOf(cid)"
            rows="4"
            @input="edited[cid] = ($event.target as HTMLTextAreaElement).value"
          />
          <div class="row" style="margin-top: 6px">
            <button
              class="btn primary"
              type="button"
              :disabled="!eventId || busyId === cid"
              @click="feedback(cid, 'adopt_and_send_manually')"
            >
              采纳并复制
            </button>
            <button class="btn danger" type="button" :disabled="!eventId" @click="feedback(cid, 'reject')">
              拒绝
            </button>
          </div>
        </div>
      </AiWatermark>
    </div>
  </section>
</template>
