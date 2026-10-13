<script setup lang="ts">
import { onMounted } from "vue";
import { useAppStore } from "@/stores/app";
import AppShell from "@/shell/AppShell.vue";

const store = useAppStore();
onMounted(() => {
  store.bootstrap();
});
</script>

<template>
  <AppShell v-if="store.loaded && !store.error" />
  <div v-else class="bootstrap-state">
    <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
    <span v-else class="loading-text">正在加载全能办公室…</span>
  </div>
</template>
