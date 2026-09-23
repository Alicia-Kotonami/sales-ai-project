<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

export type ChatRole = "parent" | "advisor" | "system";

export type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  at: number;
};

const props = defineProps<{
  messages: ChatMessage[];
}>();

const emit = defineEmits<{
  "update:messages": [ChatMessage[]];
  "parent-message": [string];
}>();

const draft = ref("");
const listEl = ref<HTMLElement | null>(null);

const latestParent = computed(() => {
  for (let i = props.messages.length - 1; i >= 0; i--) {
    if (props.messages[i].role === "parent") return props.messages[i].text;
  }
  return "";
});

watch(
  () => props.messages.length,
  async () => {
    await nextTick();
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight;
  },
);

function push(role: ChatRole, text: string): void {
  const next: ChatMessage = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role,
    text: text.trim(),
    at: Date.now(),
  };
  emit("update:messages", [...props.messages, next]);
}

function sendAsParent(): void {
  const text = draft.value.trim();
  if (!text) return;
  draft.value = "";
  push("parent", text);
  emit("parent-message", text);
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendAsParent();
  }
}

function seedDemo(): void {
  emit("update:messages", [
    {
      id: "seed-1",
      role: "system",
      text: "企微未接入：以下为本地模拟会话，发送不会出站。",
      at: Date.now(),
    },
    {
      id: "seed-2",
      role: "parent",
      text: "老师你好，小学数学一对一怎么收费？",
      at: Date.now(),
    },
  ]);
  emit("parent-message", "老师你好，小学数学一对一怎么收费？");
}

defineExpose({
  appendAdvisor(text: string) {
    const t = text.trim();
    if (!t) return;
    push("advisor", t);
  },
  latestParent,
});
</script>

<template>
  <section class="card chat-card panel">
    <div class="panel-head chat-head">
      <div>
        <h2>模拟家长对话</h2>
        <p class="muted">扮演家长发消息 · 企微占位，不真实出站</p>
      </div>
      <button class="btn" type="button" @click="seedDemo">重置示例</button>
    </div>

    <div ref="listEl" class="chat-list">
      <div
        v-for="m in messages"
        :key="m.id"
        class="bubble-row"
        :class="m.role"
      >
        <div class="bubble">
          <div class="bubble-role">
            {{ m.role === "parent" ? "家长" : m.role === "advisor" ? "顾问（模拟发送）" : "系统" }}
          </div>
          <div class="bubble-text">{{ m.text }}</div>
        </div>
      </div>
      <p v-if="!messages.length" class="muted chat-empty">点「重置示例」或在下方输入家长消息</p>
    </div>

    <div class="chat-compose">
      <textarea
        v-model="draft"
        rows="2"
        placeholder="以家长身份输入…"
        @keydown="onKey"
      />
      <button class="btn primary" type="button" :disabled="!draft.trim()" @click="sendAsParent">
        发送（家长）
      </button>
    </div>
    <p v-if="latestParent" class="muted" style="margin-top: 6px">
      最新家长消息将用于右侧「生成建议」
    </p>
  </section>
</template>
