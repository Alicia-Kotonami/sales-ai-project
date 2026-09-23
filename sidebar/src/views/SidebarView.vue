<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { clearSession, getSessionUser, type SessionUser } from "../auth";
import { readContextFromUrl, type CustomerContext } from "../context";
import CustomerHeader from "../components/CustomerHeader.vue";
import ParentChatPanel, {
  type ChatMessage,
} from "../components/ParentChatPanel.vue";
import ProfilePanel from "../components/ProfilePanel.vue";
import ReplyPanel from "../components/ReplyPanel.vue";
import TagPanel from "../components/TagPanel.vue";
import SchedulePanel from "../components/SchedulePanel.vue";

type MenuKey = "customer" | "profile" | "reply" | "tags" | "schedule";

const MENU: { key: MenuKey; label: string }[] = [
  { key: "customer", label: "客户" },
  { key: "profile", label: "画像" },
  { key: "reply", label: "建议" },
  { key: "tags", label: "标签" },
  { key: "schedule", label: "日程" },
];

const emit = defineEmits<{ logout: [] }>();

const user = ref<SessionUser | null>(getSessionUser());
const ctx = ref<CustomerContext>(readContextFromUrl());
const chatMessages = ref<ChatMessage[]>([]);
const chatRef = ref<InstanceType<typeof ParentChatPanel> | null>(null);
const activeMenu = ref<MenuKey>("reply");

const latestParentMessage = computed(() => {
  for (let i = chatMessages.value.length - 1; i >= 0; i--) {
    if (chatMessages.value[i].role === "parent") return chatMessages.value[i].text;
  }
  return "";
});

function onUpdate(next: CustomerContext): void {
  ctx.value = next;
}

function logout(): void {
  clearSession();
  emit("logout");
}

function onParentMessage(_text: string): void {
  // parentMessage 经 computed 同步进 ReplyPanel
}

function onAdopted(text: string): void {
  chatRef.value?.appendAdvisor(text);
}

onMounted(() => {
  chatMessages.value = [
    {
      id: "boot-sys",
      role: "system",
      text: "企微未接入：左侧为模拟家长窗，右侧为顾问侧栏。",
      at: Date.now(),
    },
    {
      id: "boot-parent",
      role: "parent",
      text: "老师你好，小学数学一对一怎么收费？",
      at: Date.now(),
    },
  ];
});
</script>

<template>
  <div class="demo-shell">
    <div class="banner wecom-stub">
      企业微信：占位中（无真实账号）。发送仅写入本地模拟对话，不会出站。
    </div>
    <div class="demo-layout">
      <aside class="demo-chat">
        <ParentChatPanel
          ref="chatRef"
          v-model:messages="chatMessages"
          @parent-message="onParentMessage"
        />
      </aside>

      <main class="demo-advisor">
        <div class="advisor-top">
          <div class="advisor-brand">
            <span class="advisor-brand-mark">销</span>
            <div class="advisor-brand-text">
              <strong>销售赋能</strong>
              <span class="muted">顾问侧栏</span>
            </div>
          </div>
          <nav class="nav-menu" aria-label="侧栏功能">
            <button
              v-for="item in MENU"
              :key="item.key"
              type="button"
              class="nav-item"
              :class="{ active: activeMenu === item.key }"
              @click="activeMenu = item.key"
            >
              {{ item.label }}
            </button>
          </nav>
        </div>

        <div class="advisor-body">
          <CustomerHeader
            v-show="activeMenu === 'customer'"
            :user="user"
            :context="ctx"
            @update="onUpdate"
            @logout="logout"
          />
          <ProfilePanel
            v-show="activeMenu === 'profile'"
            :customer-id="ctx.customerId"
            :draft-id="ctx.draftId"
          />
          <ReplyPanel
            v-show="activeMenu === 'reply'"
            :customer-id="ctx.customerId"
            :conversation-id="ctx.conversationId"
            :parent-message="latestParentMessage"
            @adopted="onAdopted"
          />
          <TagPanel
            v-show="activeMenu === 'tags'"
            :customer-id="ctx.customerId"
            :conversation-id="ctx.conversationId"
          />
          <SchedulePanel
            v-show="activeMenu === 'schedule'"
            :customer-id="ctx.customerId"
            :conversation-id="ctx.conversationId"
          />
          <p class="footer-note">
            AI 内容永久标注「AI 建议」。真实企微接入前，请用左侧模拟窗验收闭环。
          </p>
        </div>
      </main>
    </div>
  </div>
</template>
