<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { SessionUser } from "../auth";
import type { CustomerContext } from "../context";
import { writeContextToUrl } from "../context";
import { api } from "../api/http";
import type { ProfileData } from "../api/types";

const props = defineProps<{
  user: SessionUser | null;
  context: CustomerContext;
}>();

const emit = defineEmits<{
  update: [ctx: CustomerContext];
  logout: [];
}>();

const customerId = ref(String(props.context.customerId));
const conversationId = ref(String(props.context.conversationId));
const draftId = ref(props.context.draftId ? String(props.context.draftId) : "");
const summary = ref("加载客户上下文…");

const roleLabel = computed(() => props.user?.roleCode || "-");

watch(
  () => props.context,
  (ctx) => {
    customerId.value = String(ctx.customerId);
    conversationId.value = String(ctx.conversationId);
    draftId.value = ctx.draftId ? String(ctx.draftId) : "";
  },
  { deep: true },
);

watch(
  () => props.context.customerId,
  async (id) => {
    try {
      const data = await api<ProfileData>(`/api/v1/profiles/${id}`);
      const basic = (data.sections?.basic || {}) as Record<string, unknown>;
      summary.value = `${basic.student_name || "客户"} · ${basic.grade || "-"} · ${basic.school || "-"}`;
    } catch (e) {
      summary.value = e instanceof Error ? e.message : "客户不可访问";
    }
  },
  { immediate: true },
);

function apply(): void {
  const next: CustomerContext = {
    customerId: Number(customerId.value) || 3,
    conversationId: Number(conversationId.value) || 2,
    draftId: Number(draftId.value) > 0 ? Number(draftId.value) : null,
  };
  writeContextToUrl(next);
  emit("update", next);
}
</script>

<template>
  <header class="card">
    <div class="row" style="justify-content: space-between">
      <div>
        <div><b>{{ summary }}</b></div>
        <div class="muted">顾问 {{ user?.userId ?? "-" }} · {{ roleLabel }} · dataScope {{ user?.dataScope ?? "-" }}</div>
      </div>
      <button class="btn" type="button" @click="emit('logout')">退出</button>
    </div>
    <div class="banner" style="margin-top: 8px">
      顾问演示请用客户 3 / 会话 2。客户 1 归属管理员，顾问调用会 1003。
    </div>
    <div class="row" style="margin-top: 6px">
      <div class="field">
        <label>customerId</label>
        <input v-model="customerId" inputmode="numeric" />
      </div>
      <div class="field">
        <label>conversationId</label>
        <input v-model="conversationId" inputmode="numeric" />
      </div>
      <div class="field">
        <label>draftId</label>
        <input v-model="draftId" inputmode="numeric" placeholder="可选" />
      </div>
    </div>
    <div class="row" style="margin-top: 8px">
      <button class="btn primary" type="button" @click="apply">切换客户</button>
    </div>
  </header>
</template>
