<script setup lang="ts">
defineProps<{ label?: string }>();
</script>

<template>
  <div class="ai-host">
    <div class="ai-mark" aria-hidden="true">AI 建议</div>
    <span class="ai-chip">{{ label || "AI 建议" }}</span>
    <slot />
  </div>
</template>
