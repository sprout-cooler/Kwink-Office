<script setup lang="ts">
/**
 * OOCard —— 统一卡片容器。
 *
 * 为什么需要它：项目里 7 处用 el-card、其余页面用裸 div，
 * 圆角/阴影/边框/悬浮反馈各不相同。本组件把容器视觉收敛成一处，
 * 新增页面只需引入，不必再写一遍卡片样式。
 *
 * 用法：
 *   <OOCard title="客户列表" subtitle="共 12 条" :loading="loading">
 *     ...内容...
 *   </OOCard>
 */
withDefaults(
  defineProps<{
    /** 卡片标题 */
    title?: string;
    /** 标题下方的补充说明 */
    subtitle?: string;
    /** 是否有悬浮反馈（可点击的卡片用） */
    hoverable?: boolean;
    /** 骨架屏加载态 */
    loading?: boolean;
    /** 内容区是否去掉内边距（表格类内容用） */
    flush?: boolean;
    /** 是否显示渐变底纹 */
    tinted?: boolean;
  }>(),
  { hoverable: false, loading: false, flush: false, tinted: false },
);
</script>

<template>
  <section
    class="oo-card oo-card-pad"
    :class="{ 'oo-card-hover': hoverable, 'oo-card-tinted': tinted }"
  >
    <header v-if="title || subtitle || $slots.header || $slots.actions" class="oo-card-head">
      <div class="oo-card-head-main">
        <slot name="header">
          <h3 v-if="title" class="oo-card-title">{{ title }}</h3>
          <p v-if="subtitle" class="oo-card-subtitle">{{ subtitle }}</p>
        </slot>
      </div>
      <div v-if="$slots.actions" class="oo-card-actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="oo-card-body" :class="{ 'oo-card-body-flush': flush }">
      <!-- 骨架屏：保留内容区高度，避免加载完成时布局跳动（CLS） -->
      <div v-if="loading" class="oo-skeleton-stack">
        <div class="oo-skeleton" style="height: 18px; width: 40%" />
        <div class="oo-skeleton" style="height: 14px; width: 90%" />
        <div class="oo-skeleton" style="height: 14px; width: 75%" />
        <div class="oo-skeleton" style="height: 14px; width: 85%" />
      </div>
      <slot v-else />
    </div>

    <footer v-if="$slots.footer" class="oo-card-foot">
      <slot name="footer" />
    </footer>
  </section>
</template>

<style scoped>
.oo-card-pad {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.oo-card-tinted {
  background: linear-gradient(
      180deg,
      var(--oo-bg-surface) 0%,
      var(--oo-bg-surface) 62%,
      var(--oo-bg-surface-2) 100%
    ),
    var(--oo-bg-surface);
}

.oo-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--oo-space-4);
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--oo-border-subtle);
}

.oo-card-head-main {
  min-width: 0;
  flex: 1;
}

.oo-card-title {
  font-size: var(--oo-text-base);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
}

.oo-card-subtitle {
  margin-top: 4px;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.oo-card-actions {
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  flex-shrink: 0;
}

.oo-card-body {
  flex: 1;
  padding: 16px 20px 20px;
  min-width: 0;
}

.oo-card-body-flush {
  padding: 0;
}

.oo-card-foot {
  padding: 12px 20px;
  border-top: 1px solid var(--oo-border-subtle);
  background: var(--oo-bg-surface-2);
}

.oo-skeleton-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
