<script setup lang="ts">
/**
 * OOSectionTitle —— 区块小标题。
 *
 * 用于卡片内再分区（如「基本信息」「历史记录」），
 * 视觉层级低于 OOPageHeader，高于正文。
 */
defineProps<{
  title: string;
  /** 补充说明 */
  description?: string;
}>();
</script>

<template>
  <div class="oo-section">
    <div class="oo-section-head">
      <span class="oo-section-bar" aria-hidden="true" />
      <h4 class="oo-section-title">{{ title }}</h4>
      <span v-if="description" class="oo-section-desc">{{ description }}</span>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.oo-section {
  display: flex;
  flex-direction: column;
  gap: var(--oo-space-3);
}

.oo-section-head {
  display: flex;
  align-items: baseline;
  gap: var(--oo-space-2);
}

.oo-section-bar {
  width: 3px;
  height: 14px;
  border-radius: var(--oo-radius-pill);
  background: var(--oo-gradient-brand);
  align-self: center;
}

.oo-section-title {
  font-size: var(--oo-text-sm);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}

.oo-section-desc {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}
</style>
