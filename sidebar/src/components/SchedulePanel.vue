<script setup lang="ts">
import { ref, watch } from "vue";
import { api, ApiError } from "../api/http";
import type { ParseCandidate, ScheduleTaskItem, TodayTasks } from "../api/types";

const props = defineProps<{
  customerId: number;
  conversationId: number;
}>();

const TYPE_LABEL: Record<number, string> = {
  1: "试听回访",
  2: "续费提醒",
  3: "生日关怀",
  4: "自定义",
  5: "SOP节点",
};

const STATUS_LABEL: Record<number, string> = {
  1: "已确认",
  2: "已完成",
  3: "已取消",
  4: "已调整",
};

const loading = ref(false);
const error = ref("");
const notice = ref("");
const today = ref<TodayTasks | null>(null);
const parseText = ref("明天下午跟进试听");
const candidates = ref<ParseCandidate[]>([]);
const dueEdits = ref<Record<number, string>>({});

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(raw: string): string {
  const d = new Date(raw);
  return d.toISOString();
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    today.value = await api<TodayTasks>("/api/v1/schedules/today");
    const next: Record<number, string> = {};
    for (const item of today.value.list || []) {
      next[item.taskId] = toLocalInput(item.dueAt);
    }
    dueEdits.value = next;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "今日任务加载失败";
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.customerId,
  () => {
    void load();
  },
  { immediate: true },
);

async function parse(): Promise<void> {
  error.value = "";
  try {
    const data = await api<{ candidates: ParseCandidate[] }>("/api/v1/schedules/parse", {
      method: "POST",
      body: JSON.stringify({ text: parseText.value, conversationId: props.conversationId }),
    });
    candidates.value = data.candidates || [];
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "解析失败";
  }
}

async function createFrom(c: ParseCandidate): Promise<void> {
  error.value = "";
  try {
    await api("/api/v1/schedules/tasks", {
      method: "POST",
      body: JSON.stringify({
        customerId: props.customerId,
        type: 4,
        title: c.task || "跟进",
        dueAt: c.parsedAt,
        priority: 1,
        sourceText: parseText.value,
        sourceRefs: c.sourceRefs,
        confirmFromParse: true,
      }),
    });
    notice.value = "已创建待办（日历标题由服务端脱敏生成）";
    candidates.value = [];
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "创建失败";
  }
}

async function adjust(task: ScheduleTaskItem, patch: { dueAt?: string; status?: number }): Promise<void> {
  error.value = "";
  try {
    await api(`/api/v1/schedules/tasks/${task.taskId}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    });
    notice.value = "已调整";
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "调整失败";
  }
}

async function syncWechat(task: ScheduleTaskItem): Promise<void> {
  error.value = "";
  try {
    const data = await api<{ taskId: number; wechatCalendarId: string }>(
      `/api/v1/schedules/tasks/${task.taskId}/sync-wechat`,
      { method: "POST" },
    );
    notice.value = `已同步日历 ${data.wechatCalendarId}（仅 calendar_title）`;
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "同步失败";
  }
}
</script>

<template>
  <section class="card panel">
    <div class="panel-head">
      <div>
        <h2>今日日程</h2>
        <p class="muted">
          {{ today?.date || "-" }} · 逾期 {{ today?.overdueCnt ?? 0 }} · 只改时间/完成/取消
        </p>
      </div>
    </div>

    <div class="stack">
      <p v-if="loading" class="muted">加载中…</p>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="notice" class="ok">{{ notice }}</p>

      <div class="list">
        <div v-for="task in today?.list || []" :key="task.taskId" class="item">
          <div>
            <b>{{ task.title }}</b>
            <span class="muted"> · {{ TYPE_LABEL[task.type] || task.type }} · {{ STATUS_LABEL[task.status] }}</span>
          </div>
          <div class="muted">{{ task.customerNameMasked }} · 日历 {{ task.calendarTitle || "-" }}</div>
          <div class="field">
            <label>到期时间</label>
            <input v-model="dueEdits[task.taskId]" type="datetime-local" />
          </div>
          <div class="panel-actions">
            <button
              class="btn"
              type="button"
              @click="adjust(task, { dueAt: fromLocalInput(dueEdits[task.taskId]) })"
            >
              调整时间
            </button>
            <button class="btn" type="button" @click="adjust(task, { status: 2 })">完成</button>
            <button class="btn danger" type="button" @click="adjust(task, { status: 3 })">取消</button>
            <button class="btn" type="button" @click="syncWechat(task)">同步日历</button>
          </div>
        </div>
        <p v-if="today && !today.list.length" class="muted">今日暂无待办</p>
      </div>

      <div class="field">
        <label>从聊天解析待办</label>
        <textarea v-model="parseText" rows="2" />
      </div>
      <div class="panel-actions">
        <button class="btn" type="button" @click="parse">解析</button>
        <button class="btn" type="button" @click="load">刷新今日</button>
      </div>
      <div v-if="candidates.length" class="list">
        <div v-for="(c, i) in candidates" :key="i" class="item">
          <div>{{ c.task }} · {{ c.parsedAt }}</div>
          <div class="muted">{{ c.rawTime }} · {{ c.priority }} · {{ c.confidence }}</div>
          <div class="panel-actions">
            <button class="btn primary" type="button" @click="createFrom(c)">确认创建</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
