<script setup lang="ts">
// 应用账号登录/注册。
//
// 与 NAS 登录是两层：飞牛账号登录由 NAS 网关负责（网关已注入 X-Trim-* 头），
// 这里只是「同一个 NAS 账号下的多个应用账号」——不同账号的周报/模板/导出记录互相隔离。
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { authApi, type AppUser } from "@/api/auth";

const emit = defineEmits<{ (e: "authed", user: AppUser): void }>();

const props = defineProps<{ initialized: boolean; nasUser: string }>();

/** 该 NAS 账号下还没有任何应用账号时，必须引导创建首个（管理员）账号 */
const mode = ref<"init" | "login" | "register">(props.initialized ? "login" : "init");

const form = ref({ username: "", password: "", confirm: "", displayName: "" });
const remember = ref(false);
const submitting = ref(false);
const errorMsg = ref("");

const isRegister = computed(() => mode.value !== "login");
const canSubmit = computed(
  () => form.value.username.trim().length >= 3 && form.value.password.length >= 8 && !submitting.value,
);

async function submit() {
  errorMsg.value = "";
  // 前端先挡一道常见错误，避免白跑一趟网络；真正的强度校验在服务端（前端校验只算体验）
  if (form.value.username.trim().length < 3) {
    errorMsg.value = "账号至少 3 个字符";
    return;
  }
  if (form.value.password.length < 8) {
    errorMsg.value = "密码至少 8 位";
    return;
  }
  if (!/[A-Za-z]/.test(form.value.password) || !/\d/.test(form.value.password)) {
    errorMsg.value = "密码需同时包含字母和数字";
    return;
  }
  if (isRegister.value && form.value.password !== form.value.confirm) {
    errorMsg.value = "两次输入的密码不一致";
    return;
  }

  submitting.value = true;
  try {
    if (isRegister.value) {
      const r = await authApi.register({
        username: form.value.username.trim(),
        password: form.value.password,
        confirm: form.value.confirm,
        displayName: form.value.displayName.trim(),
        remember: remember.value,
      });
      ElMessage.success(
        r.isFirst ? "管理员账号已创建，数据中台已就绪" : `账号「${r.user.username}」注册成功，已登录`,
      );
      emit("authed", r.user);
    } else {
      const r = await authApi.login({
        username: form.value.username.trim(),
        password: form.value.password,
        remember: remember.value,
      });
      ElMessage.success(`欢迎回来，${r.user.displayName}`);
      emit("authed", r.user);
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    submitting.value = false;
  }
}

function switchTo(m: "login" | "register") {
  mode.value = m;
  errorMsg.value = "";
  form.value.password = "";
  form.value.confirm = "";
}
</script>

<template>
  <div class="auth-wrap">
    <!-- 背景光晕：两团品牌渐变的柔光，给纯净留白一点层次（克制，不抢内容） -->
    <div class="auth-glow auth-glow-a" aria-hidden="true" />
    <div class="auth-glow auth-glow-b" aria-hidden="true" />

    <div class="auth-card">
      <div class="auth-head">
        <div class="auth-logo" aria-hidden="true">
          <span class="auth-logo-text">O</span>
        </div>
        <div class="auth-head-text">
          <h1 class="auth-title">全能办公室</h1>
          <p class="auth-sub">统一的工作入口 · NAS 账号 {{ props.nasUser }}</p>
        </div>
      </div>

      <el-alert
        v-if="mode === 'init'"
        type="info"
        :closable="false"
        show-icon
        class="auth-tip"
        title="创建管理员账号"
        description="这是本 NAS 账号下的第一个应用账号，将自动成为管理员，并沿用你已有的周报、模板与导出记录。此后注册的账号与它的数据完全隔离。"
      />

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input
            v-model="form.username"
            placeholder="字母、数字、下划线，至少 3 位"
            autocomplete="username"
          />
        </el-form-item>

        <el-form-item v-if="isRegister" label="姓名 / 备注">
          <el-input v-model="form.displayName" placeholder="导出文件名会用这个名字（可留空）" />
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
            placeholder="至少 8 位，含字母和数字"
            @keyup.enter="submit"
          />
        </el-form-item>

        <el-form-item v-if="isRegister" label="确认密码">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            autocomplete="new-password"
            @keyup.enter="submit"
          />
        </el-form-item>

        <div class="auth-row">
          <el-checkbox v-model="remember">记住登录（30 天）</el-checkbox>
          <span v-if="mode !== 'init'" class="auth-switch">
            <el-button link type="primary" @click="switchTo(isRegister ? 'login' : 'register')">
              {{ isRegister ? "已有账号？去登录" : "注册新账号" }}
            </el-button>
          </span>
        </div>

        <el-alert v-if="errorMsg" type="error" :closable="false" class="auth-err" :title="errorMsg" />

        <el-button
          type="primary"
          size="large"
          class="auth-submit"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ mode === "init" ? "创建并进入" : isRegister ? "注册并登录" : "登录" }}
        </el-button>
      </el-form>

      <p class="auth-foot">
        账号与 NAS 账号一一绑定：换一个飞牛账号登录，看到的将是另一套独立数据。
      </p>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: var(--oo-bg-app);
  padding: var(--oo-space-6);
  box-sizing: border-box;
}

/* 背景柔光：两团品牌色径向渐变，blur 后几乎不可察觉但让留白有呼吸 */
.auth-glow {
  position: fixed;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
  opacity: 0.9;
  z-index: 0;
}

.auth-glow-a {
  width: 520px;
  height: 520px;
  top: -160px;
  left: -120px;
  background: radial-gradient(circle, rgba(76, 111, 255, 0.45) 0%, transparent 68%);
}

.auth-glow-b {
  width: 460px;
  height: 460px;
  bottom: -140px;
  right: -90px;
  background: radial-gradient(circle, rgba(124, 92, 240, 0.42) 0%, transparent 68%);
}

html.dark .auth-glow {
  opacity: 0.45;
}

html.dark .auth-glow-a {
  background: radial-gradient(circle, rgba(95, 125, 255, 0.4) 0%, transparent 68%);
}

html.dark .auth-glow-b {
  background: radial-gradient(circle, rgba(143, 108, 245, 0.38) 0%, transparent 68%);
}

.auth-card {
  width: 440px;
  max-width: 100%;
  position: relative;
  z-index: 1;
  background: var(--oo-bg-surface);
  border: 1px solid var(--oo-border-subtle);
  border-radius: var(--oo-radius-2xl);
  padding: 34px 32px 26px;
  box-shadow: var(--oo-shadow-xl);
  animation: oo-scale-in var(--oo-dur-slower) var(--oo-ease-out) both;
}

/* 卡片顶部一道品牌渐变细线。
   用 inset 定位（不是 inset:0 0 auto 0），否则会被卡片的大圆角裁切成弧形残段。 */
.auth-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 88px;
  height: 3px;
  border-radius: 0 0 var(--oo-radius-pill) var(--oo-radius-pill);
  background: var(--oo-gradient-brand);
}

.auth-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-6);
}

.auth-logo {
  width: 48px;
  height: 48px;
  border-radius: var(--oo-radius-md);
  background: var(--oo-gradient-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--oo-shadow-brand);
  flex-shrink: 0;
}

.auth-logo-text {
  color: #fff;
  font-size: 22px;
  font-weight: var(--oo-weight-bold);
  line-height: 1;
}

.auth-head-text {
  min-width: 0;
}

.auth-title {
  margin: 0;
  font-size: var(--oo-text-2xl);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
  line-height: var(--oo-line-tight);
  letter-spacing: -0.01em;
}

.auth-sub {
  margin: 4px 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

.auth-tip {
  margin-bottom: var(--oo-space-4);
}

.auth-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-3);
  flex-wrap: wrap;
}

.auth-switch {
  font-size: var(--oo-text-sm);
}

.auth-err {
  margin-bottom: var(--oo-space-3);
}

.auth-submit {
  width: 100%;
  margin-top: var(--oo-space-1);
  height: 44px;
  font-size: var(--oo-text-md);
  border-radius: var(--oo-radius-lg);
}

.auth-foot {
  margin: var(--oo-space-5) 0 0;
  padding-top: var(--oo-space-4);
  border-top: 1px solid var(--oo-border-subtle);
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
  line-height: var(--oo-line-relaxed);
}

@media (max-width: 480px) {
  .auth-wrap {
    padding: var(--oo-space-4);
  }
  .auth-card {
    padding: 26px 20px 20px;
    border-radius: var(--oo-radius-xl);
  }
  .auth-title {
    font-size: var(--oo-text-xl);
  }
}
</style>
