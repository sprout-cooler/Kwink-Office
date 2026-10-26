<script setup lang="ts">
/**
 * OOStatTile —— KPI 指标块（总览页的 6 个数字卡片）。
 *
 * 与普通卡片的区别：
 *  1. 数值用 tabular-nums，避免刷新时数字宽度抖动；
 *  2. 可配图标 + 色调，色调用「图标底色 + 图标色」两档，
 *     不给文字上色 —— 文字永远保持 --oo-text-primary，
 *     保证任何色调下对比度都达标；
 *  3. 支持趋势标记（涨红跌绿，符合 A 股习惯）。
 */
withDefaults(
  defineProps<{
    /** 指标名 */
    label: string;
    /** 指标值（已格式化的字符串） */
    value: string | number;
    /** 图标（emoji 或短字符） */
    icon?: string;
    /** 色调 */
    tone?: "brand" | "teal" | "purple" | "pink" | "amber" | "green" | "red";
    /** 辅助说明 */
    hint?: string;
    /** 趋势方向（涨=up 跌=down） */
    trend?: "up" | "down" | "flat";
    /** 趋势数值 */
    delta?: string;
  }>(),
  { tone: "brand" },
);
</script>

<template>
  <div class="oo-stat" :class="`oo-stat-${tone}`">
    <div class="oo-stat-top">
      <span class="oo-stat-label">{{ label }}</span>
      <span v-if="icon" class="oo-stat-icon" aria-hidden="true">{{ icon }}</span>
    </div>
    <p class="oo-stat-value oo-num">{{ value }}</p>
    <div v-if="hint || delta" class="oo-stat-foot">
      <span v-if="delta" class="oo-stat-delta" :class="`is-${trend || 'flat'}`">
        <template v-if="trend === 'up'">▲</template>
        <template v-else-if="trend === 'down'">▼</template>
        <template v-else>—</template>
        {{ delta }}
      </span>
      <span v-if="hint" class="oo-stat-hint">{{ hint }}</span>
    </div>
  </div>
</template>

<style scoped>
.oo-stat {
  position: relative;
  padding: 16px 18px;
  border-radius: var(--oo-radius-lg);
  background: var(--oo-bg-surface);
  border: 1px solid var(--oo-border-subtle);
  box-shadow: var(--oo-shadow-xs);
  overflow: hidden;
  transition: box-shadow var(--oo-dur-base) var(--oo-ease-out),
    transform var(--oo-dur-base) var(--oo-ease-out);
}

.oo-stat::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--oo-brand);
  opacity: 0;
  transition: opacity var(--oo-dur-base) var(--oo-ease-out);
}

.oo-stat:hover {
  box-shadow: var(--oo-shadow-md);
  transform: translateY(-2px);
}

.oo-stat:hover::before {
  opacity: 1;
}

.oo-stat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-2);
}

.oo-stat-label {
  font-size: var(--oo-text-xs);
  color: var(--oo-text-secondary);
  font-weight: var(--oo-weight-medium);
  letter-spacing: 0.01em;
}

.oo-stat-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--oo-radius-sm);
  font-size: 15px;
  background: var(--oo-brand-soft);
  color: var(--oo-brand);
}

.oo-stat-teal .oo-stat-icon {
  background: var(--oo-info-soft);
  color: var(--oo-info-text);
}
.oo-stat-purple .oo-stat-icon {
  background: var(--oo-purple-100);
  color: var(--oo-purple-700);
}
.oo-stat-pink .oo-stat-icon {
  background: var(--oo-pink-100);
  color: var(--oo-pink-700);
}
.oo-stat-amber .oo-stat-icon {
  background: var(--oo-warning-soft);
  color: var(--oo-warning-text);
}
.oo-stat-green .oo-stat-icon {
  background: var(--oo-success-soft);
  color: var(--oo-success-text);
}
.oo-stat-red .oo-stat-icon {
  background: var(--oo-danger-soft);
  color: var(--oo-danger-text);
}

html.dark .oo-stat-purple .oo-stat-icon {
  background: rgba(124, 92, 240, 0.18);
  color: var(--oo-purple-300);
}
html.dark .oo-stat-pink .oo-stat-icon {
  background: rgba(232, 99, 143, 0.18);
  color: var(--oo-pink-300);
}

.oo-stat-value {
  margin-top: 8px;
  font-size: var(--oo-text-3xl);
  font-weight: var(--oo-weight-semibold);
  line-height: 1.15;
  color: var(--oo-text-primary);
  letter-spacing: -0.02em;
}

.oo-stat-foot {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: var(--oo-space-2);
  font-size: var(--oo-text-xs);
  min-height: 18px;
}

.oo-stat-delta {
  font-weight: var(--oo-weight-medium);
  font-variant-numeric: tabular-nums;
}

.oo-stat-delta.is-up {
  color: var(--oo-danger-text);
}
.oo-stat-delta.is-down {
  color: var(--oo-success-text);
}
.oo-stat-delta.is-flat {
  color: var(--oo-text-tertiary);
}

.oo-stat-hint {
  color: var(--oo-text-tertiary);
}

/* 窄屏：两列布局时压缩内边距与字号，避免卡片过高 */
@media (max-width: 560px) {
  .oo-stat {
    padding: 12px 13px;
  }
  .oo-stat-value {
    margin-top: 6px;
    font-size: var(--oo-text-2xl);
  }
  .oo-stat-icon {
    width: 26px;
    height: 26px;
    font-size: 13px;
  }
  .oo-stat-foot {
    margin-top: 6px;
  }
}
</style>
