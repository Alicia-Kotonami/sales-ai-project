<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, ApiError, getToken } from "../api/http";
import { postSseWithReconnect, type SseEvent } from "../api/sse";
import type {
  AgentStartEvent,
  AgentStepEvent,
  Citation,
  SuggestDone,
  UncertaintyNote,
} from "../api/types";
import AgentStepList from "./AgentStepList.vue";
import AiWatermark from "./AiWatermark.vue";

const props = defineProps<{
  customerId: number;
  conversationId: number;
  /** 来自模拟家长对话窗的最新文本；有则优先生效 */
  parentMessage?: string;
}>();

const emit = defineEmits<{
  adopted: [text: string];
}>();

const messageText = ref(props.parentMessage || "数学怎么收费");
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
const mode = ref<string>("legacy");
const runId = ref<number | null>(null);
const steps = ref<AgentStepEvent[]>([]);
const stepsCollapsed = ref(true);
const citations = ref<Citation[]>([]);
const uncertaintyNotes = ref<UncertaintyNote[]>([]);
const ragHint = ref("");
const feedbackBusy = ref(false);
let abortCtl: AbortController | null = null;

watch(
  () => props.parentMessage,
  (v) => {
    if (v != null && v.trim()) messageText.value = v.trim();
  },
);

const candidates = computed(() =>
  Object.keys(texts.value)
    .map(Number)
    .sort((a, b) => a - b),
);

const showInterrupt = computed(
  () => streaming.value && mode.value === "agent" && runId.value != null,
);

const showAgentFeedback = computed(
  () => !streaming.value && mode.value === "agent" && runId.value != null && eventId.value != null,
);

function upsertStep(raw: AgentStepEvent): void {
  const idx = steps.value.findIndex((s) => s.stepIndex === raw.stepIndex);
  if (idx >= 0) {
    const next = [...steps.value];
    next[idx] = { ...next[idx], ...raw };
    steps.value = next;
  } else {
    steps.value = [...steps.value, raw].sort((a, b) => a.stepIndex - b.stepIndex);
  }
}

function onSse(evt: SseEvent): void {
  if (evt.id) lastEventId.value = evt.id;
  const data = evt.data as Record<string, unknown>;
  if (evt.event === "asr_result") {
    asrText.value = String(data.text ?? "");
    return;
  }
  if (evt.event === "agent_start") {
    const start = data as unknown as AgentStartEvent;
    mode.value = "agent";
    runId.value = Number(start.runId);
    steps.value = [];
    stepsCollapsed.value = false;
    return;
  }
  if (evt.event === "agent_step") {
    mode.value = "agent";
    upsertStep(data as unknown as AgentStepEvent);
    stepsCollapsed.value = false;
    return;
  }
  if (evt.event === "rag_status") {
    mode.value = mode.value === "agent" ? mode.value : "rag";
    ragHint.value = String(data.status ?? "searching");
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
    mode.value = done.mode || mode.value || "legacy";
    if (done.runId != null) runId.value = done.runId;
    citations.value = done.citations || [];
    uncertaintyNotes.value = (done.uncertaintyNotes || []).map((n) =>
      typeof n === "string" ? { message: n } : (n as UncertaintyNote),
    );
    reconnectHint.value = "";
    ragHint.value = "";
    if (mode.value !== "agent") {
      stepsCollapsed.value = true;
    }
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
  mode.value = "legacy";
  runId.value = null;
  steps.value = [];
  stepsCollapsed.value = true;
  citations.value = [];
  uncertaintyNotes.value = [];
  ragHint.value = "";

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

async function interrupt(): Promise<void> {
  if (!runId.value) return;
  error.value = "";
  try {
    await api(`/api/v1/reply/agent/runs/${runId.value}/interrupt`, {
      method: "POST",
      body: JSON.stringify({ reason: "advisor_stop" }),
    });
    notice.value = "已请求打断，等待服务端收尾…";
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "打断失败";
  }
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
      emit("adopted", finalText);
      notice.value = "已采纳：已写入左侧模拟对话（企微未接入，未真实出站）。";
    } else {
      notice.value = "已拒绝该建议";
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "回写失败";
  } finally {
    busyId.value = null;
  }
}

async function reportIssue(): Promise<void> {
  if (!runId.value) return;
  feedbackBusy.value = true;
  error.value = "";
  try {
    await api(`/api/v1/reply/agent/runs/${runId.value}/feedback`, {
      method: "POST",
      body: JSON.stringify({
        isNegative: true,
        comment: "侧边栏反馈：建议有问题",
        issueTags: ["sidebar_report"],
      }),
    });
    notice.value = "已提交反馈，感谢指出问题";
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "反馈失败";
  } finally {
    feedbackBusy.value = false;
  }
}
</script>

<template>
  <section class="card panel">
    <div class="panel-head">
      <div>
        <h2>回复建议</h2>
        <p class="muted">SSE 流式 · 采纳写入模拟对话（企微占位，禁止代发）</p>
      </div>
      <span class="badge">{{ mode }}</span>
    </div>

    <div class="stack">
      <div class="field-grid field-grid-2">
        <div class="field">
          <label>消息类型</label>
          <select v-model="msgType">
            <option value="text">text</option>
            <option value="audio">audio</option>
          </select>
        </div>
        <div v-if="msgType === 'audio'" class="field">
          <label>audioUrl</label>
          <input v-model="audioUrl" />
        </div>
      </div>

      <div class="field">
        <label>{{ msgType === "audio" ? "语音转写占位 / 原文" : "家长最新消息（可与左侧同步）" }}</label>
        <textarea v-model="messageText" rows="3" />
      </div>

      <div class="panel-actions">
        <button class="btn primary" type="button" :disabled="streaming" @click="generate">生成建议</button>
        <button class="btn" type="button" :disabled="!streaming" @click="stop">停止</button>
        <button
          v-if="showInterrupt"
          class="btn danger"
          type="button"
          @click="interrupt"
        >
          打断分析
        </button>
      </div>

      <div v-if="reconnectHint || lastEventId || asrText || ragHint || scenarioTags.length" class="meta-block">
        <p v-if="reconnectHint" class="muted">{{ reconnectHint }}</p>
        <p v-if="lastEventId" class="muted">Last-Event-ID {{ lastEventId }}</p>
        <p v-if="asrText" class="muted">ASR：{{ asrText }}</p>
        <p v-if="ragHint" class="muted">资料检索中（{{ ragHint }}）…</p>
        <p v-if="scenarioTags.length" class="muted">
          场景 {{ scenarioTags.join(" / ") }} · eventId {{ eventId }}
          <template v-if="runId"> · runId {{ runId }}</template>
        </p>
      </div>

      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="notice" class="ok">{{ notice }}</p>

      <AgentStepList
        v-if="steps.length"
        :steps="steps"
        :collapsed="stepsCollapsed && !streaming"
      />

      <div class="list">
        <AiWatermark v-for="cid in candidates" :key="cid">
          <div class="item suggest-item">
            <div class="muted">{{ candidates.length === 1 ? "AI 建议" : `候选 ${cid}` }}</div>
            <textarea
              :value="textOf(cid)"
              rows="5"
              @input="edited[cid] = ($event.target as HTMLTextAreaElement).value"
            />
            <div v-if="citations.length" class="cite-row">
              <span v-for="(c, i) in citations" :key="i" class="cite-chip" :title="c.excerpt || ''">
                {{ c.label || c.refId || `来源${i + 1}` }}
              </span>
            </div>
            <div v-if="uncertaintyNotes.length" class="warn-box">
              <div v-for="(n, i) in uncertaintyNotes" :key="i">
                ⚠ {{ typeof n === "string" ? n : n.message || n.code || "存在不确定信息，请核实" }}
              </div>
            </div>
            <div class="panel-actions">
              <button
                class="btn"
                type="button"
                :disabled="!textOf(cid)"
                @click="copyText(textOf(cid))"
              >
                复制
              </button>
              <button
                class="btn primary"
                type="button"
                :disabled="!eventId || busyId === cid"
                @click="feedback(cid, 'adopt_and_send_manually')"
              >
                采纳并手动发送
              </button>
              <button class="btn danger" type="button" :disabled="!eventId" @click="feedback(cid, 'reject')">
                拒绝
              </button>
              <button
                v-if="showAgentFeedback"
                class="btn"
                type="button"
                :disabled="feedbackBusy"
                @click="reportIssue"
              >
                有问题
              </button>
            </div>
          </div>
        </AiWatermark>
      </div>
    </div>
  </section>
</template>
