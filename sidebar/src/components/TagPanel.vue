<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, ApiError, getToken } from "../api/http";
import { postSseWithReconnect, type SseEvent } from "../api/sse";
import type { CustomerTagItem, TagCatalogItem, TagRecommendItem } from "../api/types";
import AiWatermark from "./AiWatermark.vue";

const props = defineProps<{
  customerId: number;
  conversationId: number;
}>();

const CATEGORY_LABEL: Record<string, string> = {
  intent: "意向",
  subject: "学科",
  stage: "学段",
  service: "服务",
};

const loading = ref(false);
const error = ref("");
const notice = ref("");
const catalog = ref<TagCatalogItem[]>([]);
const selected = ref<CustomerTagItem[]>([]);
const recs = ref<TagRecommendItem[]>([]);
const streaming = ref(false);
const reconnectHint = ref("");
let abortCtl: AbortController | null = null;

const selectedIds = computed(() => new Set(selected.value.map((t) => t.tagId)));

const grouped = computed(() => {
  const map = new Map<string, TagCatalogItem[]>();
  for (const item of catalog.value) {
    const key = item.category || "other";
    const list = map.get(key) || [];
    list.push(item);
    map.set(key, list);
  }
  return [...map.entries()];
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [cat, cur] = await Promise.all([
      api<{ list: TagCatalogItem[] }>("/api/v1/tags/catalog"),
      api<{ list: CustomerTagItem[] }>(`/api/v1/customers/${props.customerId}/tags`),
    ]);
    catalog.value = cat.list || [];
    selected.value = cur.list || [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : "标签加载失败";
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

async function toggle(tag: TagCatalogItem, checked: boolean): Promise<void> {
  error.value = "";
  notice.value = "";
  try {
    await api(`/api/v1/customers/${props.customerId}/tags/toggle`, {
      method: "PUT",
      body: JSON.stringify({ tagId: tag.tagId, checked }),
    });
    await load();
    notice.value = checked ? `已勾选 ${tag.name}` : `已取消 ${tag.name}`;
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "勾选失败";
    await load();
  }
}

function onSse(evt: SseEvent): void {
  if (evt.event === "tag_recommend") {
    recs.value = [...recs.value, evt.data as TagRecommendItem];
  }
}

async function recommend(): Promise<void> {
  abortCtl?.abort();
  abortCtl = new AbortController();
  streaming.value = true;
  recs.value = [];
  reconnectHint.value = "";
  error.value = "";
  try {
    await postSseWithReconnect({
      url: "/api/v1/tags/recommendations/stream",
      body: { customerId: props.customerId, conversationId: props.conversationId },
      token: getToken(),
      signal: abortCtl.signal,
      onEvent: onSse,
      onRetryWait: (ms) => {
        reconnectHint.value = `SSE 断开，${ms / 1000}s 后重连`;
      },
      isTerminal: (event) => event === "tag_recommend_done" || event === "tag_recommend_error",
    });
  } catch (e) {
    if (!(e instanceof DOMException && e.name === "AbortError")) {
      error.value = e instanceof Error ? e.message : "推荐失败";
    }
  } finally {
    streaming.value = false;
  }
}
</script>

<template>
  <section class="card panel">
    <div class="panel-head">
      <div>
        <h2>固定关键标签</h2>
        <p class="muted">目录勾选，禁止自由填写。AI 推荐仅提示，生效走勾选。</p>
      </div>
    </div>

    <div class="stack">
      <p v-if="loading" class="muted">加载中…</p>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="notice" class="ok">{{ notice }}</p>
      <p v-if="reconnectHint" class="muted">{{ reconnectHint }}</p>

      <div v-for="[cat, items] in grouped" :key="cat" class="field">
        <label>{{ CATEGORY_LABEL[cat] || cat }}</label>
        <div class="tag-list">
          <label v-for="tag in items" :key="tag.tagId" class="tag-check">
            <input
              type="checkbox"
              :checked="selectedIds.has(tag.tagId)"
              @change="toggle(tag, ($event.target as HTMLInputElement).checked)"
            />
            <span class="tag-check-name">{{ tag.name }}</span>
            <span class="muted">{{ tag.code }}</span>
          </label>
        </div>
      </div>

      <div class="panel-actions">
        <button class="btn" type="button" @click="load">刷新已选</button>
        <button class="btn primary" type="button" :disabled="streaming" @click="recommend">拉 AI 推荐</button>
      </div>

      <div v-if="recs.length" class="list">
        <AiWatermark v-for="(rec, idx) in recs" :key="`${rec.tagId}-${idx}`">
          <div class="item suggest-item">
            <div>
              <span class="badge">{{ rec.action === "uncheck" ? "建议取消" : "建议勾选" }}</span>
              {{ rec.tagName }}
            </div>
            <p class="muted">{{ rec.reason }} · 置信度 {{ rec.confidence ?? "-" }}</p>
          </div>
        </AiWatermark>
      </div>
    </div>
  </section>
</template>
