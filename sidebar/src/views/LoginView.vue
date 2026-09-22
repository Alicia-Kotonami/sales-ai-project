<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { loginByUserid, loginByWecomCode } from "../auth";
import { consumeOauthCode } from "../context";

const emit = defineEmits<{ loggedIn: [] }>();

const userid = ref("wx_advisor_002");
const loading = ref(false);
const error = ref("");
const hint = computed(() =>
  loading.value ? "登录中…" : "开发环境可用 wechat_userid；企微入口走 OAuth code。",
);

async function submit(): Promise<void> {
  error.value = "";
  loading.value = true;
  try {
    await loginByUserid(userid.value.trim());
    emit("loggedIn");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "登录失败";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  const code = consumeOauthCode();
  if (!code) return;
  loading.value = true;
  try {
    await loginByWecomCode(code);
    emit("loggedIn");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "OAuth 失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page">
    <div class="card">
      <h2>销售赋能 · 侧边栏登录</h2>
      <p class="muted">{{ hint }}</p>
      <form class="list" @submit.prevent="submit">
        <div class="field">
          <label>wechat_userid / 调试 code</label>
          <input v-model="userid" autocomplete="username" />
        </div>
        <p v-if="error" class="err">{{ error }}</p>
        <button class="btn primary" type="submit" :disabled="loading">登录</button>
      </form>
    </div>
    <p class="footer-note">顾问演示请用 wx_advisor_002，客户 3 / 会话 2。</p>
  </div>
</template>
