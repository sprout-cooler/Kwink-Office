<script setup lang="ts">
/**
 * OOEmptyState —— 统一空状态。
 *
 * 项目里 9 处用 el-empty，但插图样式、说明层级各不相同。
 * 本组件提供「图形 + 主文案 + 补充说明 + 操作按钮」四段式结构，
 * 并内置加载中骨架态（loading=true 时切换为骨架屏）。
 *
 * 注意：图形用纯 CSS 绘制（不引图片资源）——
 * NAS 可能离线，且矢量图标在深浅色下都要能适配。
 */
withDefaults(
  defineProps<{
    /** 主文案 */
    title?: string;
    /** 补充说明 */
    description?: string;
    /** 图形类型 */
    variant?: "inbox" | "search" | "chart" | "folder" | "error" | "users";
    /** 加载中（显示骨架屏而非空状态） */
    loading?: boolean;
    /** 骨架屏行数 */
    rows?: number;
  }>(),
  { variant: "inbox", loading: false, rows: 3 },
);
</script>

<template>
  <div v-if="loading" class="oo-empty oo-empty-loading">
    <div class="oo-skeleton" style="height: 56px; width: 56px; border-radius: 50%" />
    <div
      v-for="i in rows"
      :key="i"
      class="oo-skeleton"
      :style="{ height: '13px', width: `${70 - i * 8}%` }"
    />
  </div>

  <div v-else class="oo-empty">
    <div class="oo-empty-art" :class="`oo-empty-art-${variant}`" aria-hidden="true">
      <svg viewBox="0 0 64 64" width="56" height="56" fill="none">
        <template v-if="variant === 'search'">
          <circle cx="28" cy="28" r="16" stroke="currentColor" stroke-width="3" />
          <path d="M40 40L54 54" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" />
        </template>
        <template v-else-if="variant === 'chart'">
          <rect x="10" y="34" width="9" height="20" rx="3" fill="currentColor" opacity="0.35" />
          <rect x="27" y="22" width="9" height="32" rx="3" fill="currentColor" opacity="0.6" />
          <rect x="44" y="12" width="9" height="42" rx="3" fill="currentColor" />
        </template>
        <template v-else-if="variant === 'folder'">
          <path
            d="M8 20a6 6 0 016-6h11l6 7h19a6 6 0 016 6v19a6 6 0 01-6 6H14a6 6 0 01-6-6V20z"
            stroke="currentColor"
            stroke-width="3"
            stroke-linejoin="round"
          />
        </template>
        <template v-else-if="variant === 'error'">
          <circle cx="32" cy="32" r="22" stroke="currentColor" stroke-width="3" />
          <path d="M32 20v16" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" />
          <circle cx="32" cy="42" r="2.4" fill="currentColor" />
        </template>
        <template v-else-if="variant === 'users'">
          <circle cx="24" cy="20" r="7" stroke="currentColor" stroke-width="3" />
          <path
            d="M10 50c0-8 6.5-13 14-13s14 5 14 13"
            stroke="currentColor"
            stroke-width="3"
            stroke-linecap="round"
          />
          <circle cx="45" cy="24" r="5" stroke="currentColor" stroke-width="2.6" opacity="0.55" />
          <path
            d="M44 39c5 1.2 8.5 4.6 8.5 10"
            stroke="currentColor"
            stroke-width="2.6"
            stroke-linecap="round"
            opacity="0.55"
          />
        </template>
        <template v-else>
          <rect x="9" y="18" width="46" height="34" rx="7" stroke="currentColor" stroke-width="3" />
          <path d="M9 27h46" stroke="currentColor" stroke-width="2.5" opacity="0.5" />
          <path d="M24 38h16" stroke="currentColor" stroke-width="3" stroke-linecap="round" opacity="0.6" />
        </template>
      </svg>
    </div>

    <p v-if="title" class="oo-empty-title">{{ title }}</p>
    <p v-if="description" class="oo-empty-desc">{{ description }}</p>

    <div v-if="$slots.default" class="oo-empty-action">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.oo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--oo-space-2);
  padding: var(--oo-space-8) var(--oo-space-5);
  text-align: center;
  animation: oo-fade-up var(--oo-dur-slow) var(--oo-ease-out) both;
}

.oo-empty-loading {
  gap: 10px;
}

.oo-empty-art {
  color: var(--oo-brand);
  opacity: 0.5;
  margin-bottom: var(--oo-space-1);
}

.oo-empty-art-error {
  color: var(--oo-danger);
}
.oo-empty-art-search {
  color: var(--oo-text-tertiary);
}
.oo-empty-art-chart {
  color: var(--oo-teal-500);
}
.oo-empty-art-users {
  color: var(--oo-purple-500);
}
.oo-empty-art-folder {
  color: var(--oo-purple-500);
}

.oo-empty-title {
  font-size: var(--oo-text-md);
  font-weight: var(--oo-weight-medium);
  color: var(--oo-text-secondary);
}

.oo-empty-desc {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-tertiary);
  max-width: 42ch;
  line-height: var(--oo-line-relaxed);
}

.oo-empty-action {
  margin-top: var(--oo-space-3);
}
</style>
