<script setup lang="ts">
/**
 * OOSkeleton —— 加载骨架屏。
 *
 * 为什么不用 el-skeleton：EP 的骨架屏没有 shimmer 动画，
 * 且无法按卡片/表格形态定制。这里提供三种常见形态：
 * card（卡片）、table（表格行）、list（列表项）。
 *
 * 关键：骨架屏的高度与真实内容接近，避免加载完成时布局跳动（CLS < 0.1）。
 */
withDefaults(
  defineProps<{
    /** 形态 */
    variant?: "card" | "table" | "list";
    /** 行数 */
    rows?: number;
    /** 是否有标题条 */
    withTitle?: boolean;
  }>(),
  { variant: "card", rows: 4, withTitle: true },
);
</script>

<template>
  <div class="oo-skel" :class="`oo-skel-${variant}`" aria-busy="true" aria-live="polite">
    <template v-if="variant === 'card'">
      <div v-if="withTitle" class="oo-skeleton" style="height: 20px; width: 32%" />
      <div v-for="i in rows" :key="i" class="oo-skeleton" :style="{ height: '13px', width: `${92 - i * 7}%` }" />
    </template>

    <template v-else-if="variant === 'table'">
      <div class="oo-skeleton" style="height: 34px; width: 100%; border-radius: 8px" />
      <div v-for="i in rows" :key="i" class="oo-skel-row">
        <div class="oo-skeleton" style="height: 13px; width: 22%" />
        <div class="oo-skeleton" style="height: 13px; width: 32%" />
        <div class="oo-skeleton" style="height: 13px; width: 18%" />
        <div class="oo-skeleton" style="height: 13px; width: 14%" />
      </div>
    </template>

    <template v-else>
      <div v-for="i in rows" :key="i" class="oo-skel-list-item">
        <div class="oo-skeleton" style="height: 38px; width: 38px; border-radius: 50%" />
        <div class="oo-skel-list-text">
          <div class="oo-skeleton" style="height: 13px; width: 44%" />
          <div class="oo-skeleton" style="height: 11px; width: 72%" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.oo-skel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.oo-skel-row {
  display: grid;
  grid-template-columns: 22% 32% 18% 14%;
  gap: 16px;
  align-items: center;
  padding: 11px 0;
  border-bottom: 1px solid var(--oo-border-subtle);
}

.oo-skel-row:last-child {
  border-bottom: none;
}

.oo-skel-list-item {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  padding: 8px 0;
}

.oo-skel-list-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

@media (max-width: 768px) {
  .oo-skel-row {
    grid-template-columns: 30% 40% 30%;
  }
  .oo-skel-row > :last-child {
    display: none;
  }
}
</style>
