<script setup lang="ts">
/**
 * OOPageHeader —— 页面级标题区。
 *
 * 各 Tab 原先直接把 el-card 顶在最上面，没有页面级的标题层级，
 * 切换 Tab 后用户不知道自己在哪个页面。本组件统一提供：
 * 标题 + 说明 + 右侧操作区，是「内容区」的标题层。
 */
withDefaults(
  defineProps<{
    /** 页面标题 */
    title: string;
    /** 页面说明 */
    description?: string;
    /** 标题左侧的图标/徽标 */
    badge?: string;
  }>(),
  {},
);
</script>

<template>
  <header class="oo-page-head">
    <div class="oo-page-head-main">
      <div class="oo-page-title-row">
        <span v-if="badge" class="oo-page-badge" aria-hidden="true">{{ badge }}</span>
        <h2 class="oo-page-title">{{ title }}</h2>
      </div>
      <p v-if="description" class="oo-page-desc">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="oo-page-actions">
      <slot />
    </div>
  </header>
</template>

<style scoped>
.oo-page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--oo-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--oo-space-5);
}

.oo-page-head-main {
  min-width: 0;
}

.oo-page-title-row {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
}

.oo-page-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-gradient-brand);
  color: #fff;
  font-size: 16px;
  box-shadow: var(--oo-shadow-brand);
}

.oo-page-title {
  font-size: var(--oo-text-2xl);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
  letter-spacing: -0.01em;
}

.oo-page-desc {
  margin-top: 6px;
  font-size: var(--oo-text-sm);
  color: var(--oo-text-tertiary);
  line-height: var(--oo-line-relaxed);
}

.oo-page-actions {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .oo-page-title {
    font-size: var(--oo-text-xl);
  }
  .oo-page-actions {
    width: 100%;
  }
}
</style>
