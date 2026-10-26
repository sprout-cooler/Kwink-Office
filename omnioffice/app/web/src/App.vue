<script setup lang="ts">
import { onMounted } from "vue";
import { useAppStore } from "@/stores/app";
import AppShell from "@/shell/AppShell.vue";
import LoginView from "@/shell/LoginView.vue";

const store = useAppStore();
onMounted(() => {
  store.bootstrap();
});
</script>

<template>
  <!-- 未登录：挂登录页而不是报错横幅（AppShell 会在 authed 之前一直不渲染） -->
  <LoginView
    v-if="store.loaded && store.authRequired && !store.user"
    :initialized="store.authInitialized"
    :nas-user="store.nasUser"
    @authed="store.onAuthed($event)"
  />
  <AppShell v-else-if="store.loaded && !store.error" />
  <div v-else class="bootstrap-state">
    <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
    <!-- 加载态：品牌标识 + 呼吸点，避免首屏只有一行灰字 -->
    <div v-else class="oo-boot">
      <div class="oo-boot-mark" aria-hidden="true">
        <span class="oo-boot-mark-text">O</span>
      </div>
      <p class="oo-boot-text">正在加载全能办公室…</p>
      <div class="oo-boot-dots" aria-hidden="true">
        <span /><span /><span />
      </div>
    </div>
  </div>
</template>

<style scoped>
.oo-boot {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--oo-space-4);
  animation: oo-fade-in var(--oo-dur-slower) var(--oo-ease-out) both;
}

.oo-boot-mark {
  width: 56px;
  height: 56px;
  border-radius: var(--oo-radius-lg);
  background: var(--oo-gradient-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--oo-shadow-brand);
  animation: oo-boot-pulse 1.8s var(--oo-ease-in-out) infinite;
}

.oo-boot-mark-text {
  color: #fff;
  font-size: 26px;
  font-weight: var(--oo-weight-bold);
  line-height: 1;
}

.oo-boot-text {
  font-size: var(--oo-text-sm);
  color: var(--oo-text-tertiary);
}

.oo-boot-dots {
  display: flex;
  gap: 6px;
}

.oo-boot-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--oo-brand);
  opacity: 0.3;
  animation: oo-boot-bounce 1.2s var(--oo-ease-in-out) infinite;
}

.oo-boot-dots span:nth-child(2) {
  animation-delay: 0.15s;
}
.oo-boot-dots span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes oo-boot-pulse {
  0%,
  100% {
    transform: scale(1);
    box-shadow: var(--oo-shadow-brand);
  }
  50% {
    transform: scale(1.06);
    box-shadow: 0 10px 28px rgba(76, 111, 255, 0.32);
  }
}

@keyframes oo-boot-bounce {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.3;
  }
  50% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
