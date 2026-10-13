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
    <span v-else class="loading-text">正在加载全能办公室…</span>
  </div>
</template>
