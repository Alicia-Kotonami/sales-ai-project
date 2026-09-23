<script setup lang="ts">
import type { AgentStepEvent } from "../api/types";

defineProps<{
  steps: AgentStepEvent[];
  collapsed?: boolean;
}>();

function mark(status: string | undefined): string {
  if (status === "ok") return "✓";
  if (status === "error") return "!";
  if (status === "running") return "●";
  return "○";
}
</script>

<template>
  <div v-if="steps.length" class="agent-steps" :class="{ collapsed }">
    <div class="agent-steps-title">推理过程</div>
    <ul class="agent-steps-list">
      <li
        v-for="s in steps"
        :key="s.stepIndex"
        class="agent-step"
        :data-status="s.status || 'pending'"
      >
        <span class="agent-step-mark">{{ mark(s.status) }}</span>
        <div class="agent-step-body">
          <div class="agent-step-title">{{ s.title || s.capability || `步骤 ${s.stepIndex}` }}</div>
          <div v-if="s.summary" class="agent-step-summary muted">{{ s.summary }}</div>
        </div>
      </li>
    </ul>
  </div>
</template>
