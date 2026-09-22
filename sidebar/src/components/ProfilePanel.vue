<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api, ApiError } from "../api/http";
import type { ProfileActionResult, ProfileData } from "../api/types";
import AiWatermark from "./AiWatermark.vue";

const props = defineProps<{
  customerId: number;
  draftId: number | null;
}>();

const loading = ref(false);
const error = ref("");
const notice = ref("");
const profile = ref<ProfileData | null>(null);
const editing = ref(false);
const rejectOpen = ref(false);
const rejectReason = ref("");
const comment = ref("");
const sectionText = ref("");

const isDraftActionable = computed(() => Boolean(props.draftId));

function pretty(sections: Record<string, unknown>): string {
  return JSON.stringify(sections, null, 2);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    profile.value = await api<ProfileData>(`/api/v1/profiles/${props.customerId}`);
    sectionText.value = pretty(profile.value.sections || {});
    editing.value = false;
    rejectOpen.value = false;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "画像加载失败";
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.customerId, props.draftId],
  () => {
    void load();
  },
  { immediate: true },
);

function section(key: string): Record<string, unknown> {
  const raw = profile.value?.sections?.[key];
  return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
}

async function confirm(): Promise<void> {
  if (!props.draftId) return;
  error.value = "";
  try {
    const data = await api<ProfileActionResult>(
      `/api/v1/profiles/${props.customerId}/drafts/${props.draftId}/confirm`,
      { method: "POST", body: JSON.stringify({ comment: comment.value || undefined }) },
    );
    notice.value = `已确认，version=${data.version}`;
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "确认失败";
  }
}

async function reject(): Promise<void> {
  if (!props.draftId) return;
  if (!rejectReason.value.trim()) {
    error.value = "驳回必须填写原因";
    return;
  }
  error.value = "";
  try {
    await api<ProfileActionResult>(
      `/api/v1/profiles/${props.customerId}/drafts/${props.draftId}/reject`,
      { method: "POST", body: JSON.stringify({ reason: rejectReason.value.trim() }) },
    );
    notice.value = "已驳回草稿";
    rejectOpen.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "驳回失败";
  }
}

async function saveEdit(): Promise<void> {
  if (!props.draftId) return;
  error.value = "";
  let sections: Record<string, unknown>;
  try {
    sections = JSON.parse(sectionText.value) as Record<string, unknown>;
  } catch {
    error.value = "sections JSON 无法解析";
    return;
  }
  try {
    const data = await api<ProfileActionResult>(
      `/api/v1/profiles/${props.customerId}/drafts/${props.draftId}/edit`,
      { method: "POST", body: JSON.stringify({ sections }) },
    );
    notice.value = `已编辑生效，version=${data.version}`;
    editing.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "编辑失败";
  }
}

const basic = computed(() => section("basic"));
const study = computed(() => section("study"));
const preference = computed(() => section("preference"));
const followup = computed(() => section("followup"));
</script>

<template>
  <section class="card">
    <h2>客户画像</h2>
    <p class="muted">
      生效画像 P1 · version {{ profile?.version ?? "-" }}
      <span v-if="isDraftActionable"> · 草稿 {{ draftId }}</span>
      <span v-else> · 确认/编辑/驳回需 URL draftId</span>
    </p>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="notice" class="ok">{{ notice }}</p>

    <AiWatermark v-if="profile">
      <div class="kv">
        <div><b>基本</b> {{ basic.student_name || "-" }} / {{ basic.grade || "-" }} / {{ basic.school || "-" }}</div>
        <div><b>学情</b> {{ JSON.stringify(study) }}</div>
        <div><b>偏好</b> {{ JSON.stringify(preference) }}</div>
        <div><b>跟进</b> {{ JSON.stringify(followup) }}</div>
      </div>
      <p v-if="profile.sources?.length" class="muted">
        来源 {{ profile.sources.map((s) => `${s.field}@${s.confidence ?? "-"}`).join("；") }}
      </p>
    </AiWatermark>

    <div class="field" style="margin-top: 8px">
      <label>确认备注（可选）</label>
      <input v-model="comment" maxlength="255" />
    </div>
    <div class="row" style="margin-top: 8px">
      <button class="btn" type="button" :disabled="loading" @click="load">刷新</button>
      <button class="btn primary" type="button" :disabled="!isDraftActionable" @click="confirm">确认</button>
      <button class="btn" type="button" :disabled="!isDraftActionable" @click="editing = !editing">编辑</button>
      <button class="btn danger" type="button" :disabled="!isDraftActionable" @click="rejectOpen = !rejectOpen">
        驳回
      </button>
    </div>

    <div v-if="editing" class="list" style="margin-top: 8px">
      <div class="field">
        <label>sections（仅 basic / study / preference / followup）</label>
        <textarea v-model="sectionText" rows="8" />
      </div>
      <button class="btn primary" type="button" @click="saveEdit">保存并生效</button>
    </div>

    <div v-if="rejectOpen" class="list" style="margin-top: 8px">
      <div class="field">
        <label>驳回原因</label>
        <input v-model="rejectReason" maxlength="255" />
      </div>
      <button class="btn danger" type="button" @click="reject">提交驳回</button>
    </div>
  </section>
</template>
