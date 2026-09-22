<script setup lang="ts">
import { ref } from "vue";
import { hasSession } from "./auth";
import { isMobileClient } from "./context";
import LoginView from "./views/LoginView.vue";
import MobileGuard from "./views/MobileGuard.vue";
import SidebarView from "./views/SidebarView.vue";

const mobile = isMobileClient();
const loggedIn = ref(hasSession());
</script>

<template>
  <MobileGuard v-if="mobile" />
  <LoginView v-else-if="!loggedIn" @logged-in="loggedIn = true" />
  <SidebarView v-else @logout="loggedIn = false" />
</template>
