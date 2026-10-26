<script setup lang="ts">
/** 出差与路径：出差记录 CRUD + 途经点 + 地图路径可视化。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizTrip, type BizTripStop } from "@/api/biz-dashboard";
import TripMap from "./TripMap.vue";

const items = ref<BizTrip[]>([]);
const customers = ref<{ id: number; name: string }[]>([]);
const caps = ref<BizCapabilities | null>(null);
const loading = ref(false);
const error = ref("");
const mapConfigured = ref(false);

const dialog = ref(false);
const editing = ref<BizTrip | null>(null);
const form = ref({
  title: "",
  customerId: undefined as number | undefined,
  originName: "",
  originLng: null as number | null,
  originLat: null as number | null,
  destName: "",
  destLng: null as number | null,
  destLat: null as number | null,
  startDate: "",
  endDate: "",
  transport: "",
  mileageKm: 0,
  costAmount: 0,
  status: "planned",
  note: "",
});
const stops = ref<Array<{ name: string; lng: number | null; lat: number | null; arriveDate: string }>>([]);
const saving = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, cs, c, ks] = await Promise.all([
      bizApi.listTrips(),
      bizApi.listCustomers(),
      bizApi.capabilities(),
      bizApi.mapKeyStatus(),
    ]);
    items.value = list.items;
    customers.value = cs.items.map((x) => ({ id: x.id, name: x.name }));
    caps.value = c;
    mapConfigured.value = ks.configured;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function openCreate() {
  editing.value = null;
  form.value = {
    title: "",
    customerId: undefined,
    originName: "",
    originLng: null,
    originLat: null,
    destName: "",
    destLng: null,
    destLat: null,
    startDate: "",
    endDate: "",
    transport: "",
    mileageKm: 0,
    costAmount: 0,
    status: "planned",
    note: "",
  };
  stops.value = [];
  dialog.value = true;
}

function openEdit(row: BizTrip) {
  editing.value = row;
  form.value = {
    title: row.title,
    customerId: row.customerId ?? undefined,
    originName: row.originName,
    originLng: row.originLng,
    originLat: row.originLat,
    destName: row.destName,
    destLng: row.destLng,
    destLat: row.destLat,
    startDate: row.startDate,
    endDate: row.endDate,
    transport: row.transport,
    mileageKm: row.mileageKm,
    costAmount: row.costAmount,
    status: row.status,
    note: row.note,
  };
  stops.value = (row.stops ?? []).map((s: BizTripStop) => ({
    name: s.name,
    lng: s.lng,
    lat: s.lat,
    arriveDate: s.arriveDate,
  }));
  dialog.value = true;
}

async function save() {
  saving.value = true;
  error.value = "";
  try {
    const body = { ...form.value, stops: stops.value.map((s, i) => ({ ...s, seq: i + 1 })) };
    if (editing.value) {
      await bizApi.updateTrip(editing.value.id, body);
    } else {
      await bizApi.createTrip(body);
    }
    dialog.value = false;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function remove(row: BizTrip) {
  error.value = "";
  try {
    await bizApi.deleteTrip(row.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

/** 用地理编码把地名回填成经纬度。 */
async function geocodeInto(which: "origin" | "dest", addr: string) {
  if (!addr.trim()) return;
  try {
    const r = await bizApi.geocode(addr);
    const loc = r.result?.location;
    if (loc) {
      if (which === "origin") {
        form.value.originLng = loc.lng;
        form.value.originLat = loc.lat;
      } else {
        form.value.destLng = loc.lng;
        form.value.destLat = loc.lat;
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

/** 地图展示：当前所有出差的所有点 + 每条出差连成一条路径线。 */
const mapMarkers = computed(() =>
  items.value.flatMap((t) => {
    const pts: { lng: number; lat: number; title: string }[] = [];
    if (t.originLng != null && t.originLat != null) {
      pts.push({ lng: t.originLng, lat: t.originLat, title: `${t.title || "出差"} · 出发地` });
    }
    if (t.destLng != null && t.destLat != null) {
      pts.push({ lng: t.destLng, lat: t.destLat, title: `${t.title || "出差"} · 目的地` });
    }
    (t.stops ?? []).forEach((s) => {
      if (s.lng != null && s.lat != null) {
        pts.push({ lng: s.lng, lat: s.lat, title: s.name });
      }
    });
    return pts;
  }),
);

/** 每条出差画一条路径线：出发地 → 途经点（按 seq）→ 目的地。 */
const mapPathLines = computed(() =>
  items.value
    .map((t) => {
      const line: { lng: number; lat: number; title: string }[] = [];
      if (t.originLng != null && t.originLat != null) {
        line.push({ lng: t.originLng, lat: t.originLat, title: `${t.title || "出差"} · 出发地` });
      }
      (t.stops ?? []).forEach((s) => {
        if (s.lng != null && s.lat != null) {
          line.push({ lng: s.lng, lat: s.lat, title: s.name });
        }
      });
      if (t.destLng != null && t.destLat != null) {
        line.push({ lng: t.destLng, lat: t.destLat, title: `${t.title || "出差"} · 目的地` });
      }
      return line;
    })
    .filter((line) => line.length >= 2),
);

const statusLabel = (code: string) =>
  caps.value?.tripStatus.find((s) => s.value === code)?.label ?? code;
const transportLabel = (code: string) =>
  caps.value?.transportModes.find((s) => s.value === code)?.label ?? code;
</script>

<template>
  <div>
    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <el-card shadow="never" class="mb">
      <template #header>
        <div class="hdr">
          <span>出差路径地图</span>
          <el-button type="primary" size="small" @click="openCreate">新增出差</el-button>
        </div>
      </template>
      <el-alert
        v-if="!mapConfigured"
        type="info"
        :closable="false"
        show-icon
        title="未配置腾讯地图 Key，地图暂不可用。请到「设置 → 数据大屏」填写 Key（服务端代为调用，前端不会泄露）。"
        class="mb"
      />
      <TripMap v-else :markers="mapMarkers" :path-lines="mapPathLines" height="380px" />
    </el-card>

    <el-table :data="items" size="small" v-loading="loading" empty-text="暂无出差记录">
      <el-table-column prop="title" label="主题" min-width="140" />
      <el-table-column label="客户" width="140">
        <template #default="{ row }">
          {{ customers.find((c) => c.id === row.customerId)?.name ?? "—" }}
        </template>
      </el-table-column>
      <el-table-column label="路线" min-width="180">
        <template #default="{ row }">
          {{ row.originName || "—" }} → {{ row.destName || "—" }}
          <span v-if="(row.stops ?? []).length" class="bz-dim">
            （{{ (row.stops ?? []).length }} 站）
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="startDate" label="开始" width="110" />
      <el-table-column prop="endDate" label="结束" width="110" />
      <el-table-column label="交通" width="80">
        <template #default="{ row }">{{ transportLabel(row.transport) }}</template>
      </el-table-column>
      <el-table-column prop="mileageKm" label="里程(km)" width="100" align="right" />
      <el-table-column prop="costAmount" label="花费" width="110" align="right" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="删除该出差记录？" @confirm="remove(row)">
            <template #reference>
              <el-button link type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="editing ? '编辑出差' : '新增出差'" width="720px">
      <el-form label-width="90px">
        <el-form-item label="主题">
          <el-input v-model="form.title" placeholder="如：XX客户年度巡检" />
        </el-form-item>
        <el-form-item label="客户">
          <el-select v-model="form.customerId" clearable placeholder="选择客户（可选）" class="w-full">
            <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="出发地">
          <div class="row">
            <el-input v-model="form.originName" placeholder="城市 / 地点名称" />
            <el-button @click="geocodeInto('origin', form.originName)">解析坐标</el-button>
          </div>
        </el-form-item>
        <el-form-item label="目的地">
          <div class="row">
            <el-input v-model="form.destName" placeholder="城市 / 地点名称" />
            <el-button @click="geocodeInto('dest', form.destName)">解析坐标</el-button>
          </div>
        </el-form-item>
        <el-form-item label="起止日期">
          <div class="row">
            <el-date-picker
              v-model="form.startDate"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="开始"
            />
            <el-date-picker
              v-model="form.endDate"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="结束"
            />
          </div>
        </el-form-item>
        <el-form-item label="交通方式">
          <el-select v-model="form.transport" clearable class="w-full">
            <el-option
              v-for="t in caps?.transportModes ?? []"
              :key="t.value"
              :label="t.label"
              :value="t.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="里程/花费">
          <div class="row">
            <el-input-number v-model="form.mileageKm" :min="0" :step="10" />
            <el-input-number v-model="form.costAmount" :min="0" :step="100" />
          </div>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" class="w-full">
            <el-option
              v-for="s in caps?.tripStatus ?? []"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="途经点">
          <div class="stops">
            <div v-for="(s, i) in stops" :key="i" class="stop-row">
              <el-input v-model="s.name" placeholder="站点名称" />
              <el-input-number v-model="s.lng" :controls="false" placeholder="经度" class="num" />
              <el-input-number v-model="s.lat" :controls="false" placeholder="纬度" class="num" />
              <el-button link type="danger" @click="stops.splice(i, 1)">移除</el-button>
            </div>
            <el-button size="small" @click="stops.push({ name: '', lng: null, lat: null, arriveDate: '' })">
              添加途经点
            </el-button>
            <p class="bz-dim">
              途经点按顺序连成路径线。经纬度可手工填写，或用上面的「解析坐标」按钮获取。
            </p>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.stops {
  width: 100%;
}
.stop-row {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}
.num {
  width: 110px;
}
.w-full {
  width: 100%;
}
.bz-dim {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.mb {
  margin-bottom: 12px;
}
</style>
