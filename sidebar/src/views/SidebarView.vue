<script setup lang="ts">
import { ref } from "vue";
import { clearSession, getSessionUser, type SessionUser } from "../auth";
import { readContextFromUrl, type CustomerContext } from "../context";
import CustomerHeader from "../components/CustomerHeader.vue";
import ProfilePanel from "../components/ProfilePanel.vue";
import ReplyPanel from "../components/ReplyPanel.vue";
import TagPanel from "../components/TagPanel.vue";
import SchedulePanel from "../components/SchedulePanel.vue";

const emit = defineEmits<{ logout: [] }>();

const user = ref<SessionUser | null>(getSessionUser());
const ctx = ref<CustomerContext>(readContextFromUrl());

function onUpdate(next: CustomerContext): void {
  ctx.value = next;
}

function logout(): void {
  clearSession();
  emit("logout");
}
</script>

<template>
  <div class="page">
    <CustomerHeader :user="user" :context="ctx" @update="onUpdate" @logout="logout" />
    <ProfilePanel :customer-id="ctx.customerId" :draft-id="ctx.draftId" />
    <ReplyPanel :customer-id="ctx.customerId" :conversation-id="ctx.conversationId" />
    <TagPanel :customer-id="ctx.customerId" :conversation-id="ctx.conversationId" />
    <SchedulePanel :customer-id="ctx.customerId" :conversation-id="ctx.conversationId" />
    <p class="footer-note">AI 内容永久标注「AI 建议」。发送动作只发生在企微原生窗口，禁止代发。</p>
  </div>
</template>
