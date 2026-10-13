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
    <div class="auth-card">
      <div class="auth-head">
        <div class="auth-logo">全</div>
        <div>
          <div class="auth-title">全能办公室</div>
          <div class="auth-sub">NAS 账号：{{ props.nasUser }}</div>
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

      <div class="auth-foot">
        账号与 NAS 账号一一绑定：换一个飞牛账号登录，看到的将是另一套独立数据。
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-lighter);
  padding: 24px;
}
.auth-card {
  width: 420px;
  max-width: 100%;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 26px 26px 20px;
  box-shadow: 0 6px 24px rgb(0 0 0 / 6%);
}
.auth-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.auth-logo {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: var(--el-color-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
.auth-title {
  font-size: 17px;
  font-weight: 600;
}
.auth-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.auth-tip {
  margin-bottom: 14px;
}
.auth-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.auth-switch {
  font-size: 13px;
}
.auth-err {
  margin-bottom: 10px;
}
.auth-submit {
  width: 100%;
}
.auth-foot {
  margin-top: 14px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  line-height: 1.6;
}
</style>
