<script setup lang="ts">
/**
 * OOToolbar —— 内容区工具条。
 *
 * 场景：表格上方的一排「筛选 + 搜索 + 操作」按钮。
 * 统一为「左：筛选/搜索；右：主操作」的布局，
 * 并在窄屏自动换行（移动端不横向滚动，WCAG UX-024）。
 */
withDefaults(
  defineProps<{
    /** 左侧说明文字 */
    hint?: string;
    /** 左侧内容（筛选器等） */
    dense?: boolean;
  }>(),
  { dense: false },
);
</script>

<template>
  <div class="oo-toolbar" :class="{ 'oo-toolbar-dense': dense }">
    <div class="oo-toolbar-left">
      <span v-if="hint" class="oo-toolbar-hint">{{ hint }}</span>
      <slot name="left" />
    </div>
    <div class="oo-toolbar-right">
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
.oo-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-3);
  flex-wrap: wrap;
  padding: 12px 20px;
  border-bottom: 1px solid var(--oo-border-subtle);
  background: var(--oo-bg-surface);
}

.oo-toolbar-dense {
  padding: 8px 14px;
}

.oo-toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
  min-width: 0;
}

.oo-toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-wrap: wrap;
}

.oo-toolbar-hint {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

@media (max-width: 768px) {
  .oo-toolbar {
    padding: 10px 14px;
  }
  .oo-toolbar-right,
  .oo-toolbar-left {
    width: 100%;
  }
}
</style>
