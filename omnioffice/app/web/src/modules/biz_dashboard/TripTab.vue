<script setup lang="ts">
/** 出差与路径：出差记录 CRUD + 途经点 + 地图路径可视化。 */
import { computed, onMounted, ref } from "vue";
import { bizApi, type BizCapabilities, type BizTrip, type BizTripStop } from "@/api/biz-dashboard";
import { OOCard, OOEmptyState, OOIcon, OOPageHeader, OOStatTile, OOToolbar } from "@/components/ui";
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
  reasonCode: "",
  reimburseStatus: "none",
  reimburseAmount: 0,
  reportTaskIds: [] as number[],
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
    reasonCode: "",
    reimburseStatus: "none",
    reimburseAmount: 0,
    reportTaskIds: [],
    mileageKm: 0,
    costAmount: 0,
    status: "planned",
    note: "",
  };
  stops.value = [];
  quotaHint.value = "";
  manualCoords.value = false;
  manual.value = { originLng: "", originLat: "", destLng: "", destLat: "" };
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
    reasonCode: row.reasonCode ?? "",
    reimburseStatus: row.reimburseStatus ?? "none",
    reimburseAmount: row.reimburseAmount ?? 0,
    reportTaskIds: [...(row.reportTaskIds ?? [])],
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
  // 手动坐标输入框回填已有坐标（编辑时能直接看到/微调）
  quotaHint.value = "";
  manualCoords.value = false;
  manual.value = {
    originLng: row.originLng != null ? String(row.originLng) : "",
    originLat: row.originLat != null ? String(row.originLat) : "",
    destLng: row.destLng != null ? String(row.destLng) : "",
    destLat: row.destLat != null ? String(row.destLat) : "",
  };
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
    // 配额耗尽（HTTP 429）时，地址解析不可用但**手动填坐标仍可行**，
    // 因此这里不清空已有坐标，只提示用户可改用手动填写。
    const msg = e instanceof Error ? e.message : String(e);
    error.value = msg;
    if (/配额|429/.test(msg)) {
      quotaHint.value = "腾讯地图配额已用尽，地址解析暂不可用。可展开「手动填写坐标」直接输入经纬度。";
    }
  }
}

/** 手动坐标输入区是否展开（默认收起，解析失败或用户主动展开时打开）。 */
const manualCoords = ref(false);
const quotaHint = ref("");

/** 手动填坐标的经纬度输入（绑定到 form 上的 null 值）。 */
const manual = ref({
  originLng: "",
  originLat: "",
  destLng: "",
  destLat: "",
});

/** 把手动输入的经纬度写回 form（空值不覆盖）。 */
function applyManualCoords() {
  const num = (s: string): number | null => {
    const v = Number(s);
    return s.trim() === "" || Number.isNaN(v) ? null : v;
  };
  if (manual.value.originLng.trim() || manual.value.originLat.trim()) {
    form.value.originLng = num(manual.value.originLng);
    form.value.originLat = num(manual.value.originLat);
  }
  if (manual.value.destLng.trim() || manual.value.destLat.trim()) {
    form.value.destLng = num(manual.value.destLng);
    form.value.destLat = num(manual.value.destLat);
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
const reasonLabel = (code: string) =>
  caps.value?.tripReasons.find((s) => s.value === code)?.label ?? code;
const reimburseLabel = (code: string) =>
  caps.value?.reimburseStatus.find((s) => s.value === code)?.label ?? code;

/** KPI 汇总：出差条数、总里程、总花费、待报销金额。 */
const tripCount = computed(() => items.value.length);
const totalMileage = computed(() => items.value.reduce((s, t) => s + (t.mileageKm ?? 0), 0));
const totalCost = computed(() => items.value.reduce((s, t) => s + (t.costAmount ?? 0), 0));
const pendingReimburse = computed(() =>
  items.value
    .filter((t) => t.reimburseStatus && t.reimburseStatus !== "none")
    .reduce((s, t) => s + Number(t.reimburseAmount ?? 0), 0),
);
</script>

<template>
  <div>
    <OOPageHeader title="出差与路径" description="记录出差行程、途经点与报销状态，并在地图上还原路径">
      <el-button type="primary" @click="openCreate">
        <OOIcon name="plus" :size="16" style="margin-right: 6px; vertical-align: -2px" />
        新增出差
      </el-button>
    </OOPageHeader>

    <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon class="mb" />

    <div class="bz-kpis">
      <OOStatTile
        label="出差记录"
        icon="T"
        tone="brand"
        :value="tripCount"
        hint="全部行程条目"
      />
      <OOStatTile
        label="总里程"
        icon="M"
        tone="teal"
        :value="`${totalMileage.toFixed(0)} km`"
        hint="累计公里数"
      />
      <OOStatTile
        label="总花费"
        icon="¥"
        tone="amber"
        :value="`¥${totalCost.toFixed(2)}`"
        hint="累计出行成本"
      />
      <OOStatTile
        label="报销金额"
        icon="R"
        tone="purple"
        :value="`¥${pendingReimburse.toFixed(2)}`"
        hint="非「无需报销」的合计"
      />
    </div>

    <OOCard title="出差路径地图" subtitle="每条出差按出发地 → 途经点 → 目的地连成一条路径" class="mb">
      <template #actions>
        <el-button size="small" type="primary" plain @click="openCreate">新增出差</el-button>
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
    </OOCard>

    <OOCard title="出差记录" :subtitle="`共 ${items.length} 条`" flush>
      <OOToolbar dense hint="点击行尾「编辑」可调整行程与报销信息">
        <template #right>
          <span class="oo-text-tertiary oo-text-xs">地图数据由服务端代理腾讯地图接口</span>
        </template>
      </OOToolbar>
      <el-table :data="items" size="small" v-loading="loading">
        <template #empty>
          <OOEmptyState variant="inbox" title="暂无出差记录" description="点击右上角「新增出差」记录第一行程" />
        </template>
        <el-table-column prop="title" label="主题" min-width="140">
          <template #default="{ row }">{{ row.title || "（未命名）" }}</template>
        </el-table-column>
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
        <el-table-column label="开始" width="110">
          <template #default="{ row }"><span class="oo-num">{{ row.startDate || "—" }}</span></template>
        </el-table-column>
        <el-table-column label="结束" width="110">
          <template #default="{ row }"><span class="oo-num">{{ row.endDate || "—" }}</span></template>
        </el-table-column>
        <el-table-column label="交通" width="80">
          <template #default="{ row }">{{ transportLabel(row.transport) }}</template>
        </el-table-column>
        <el-table-column label="里程(km)" width="100" align="right">
          <template #default="{ row }"><span class="oo-num">{{ Number(row.mileageKm ?? 0).toFixed(0) }}</span></template>
        </el-table-column>
        <el-table-column label="花费" width="110" align="right">
          <template #default="{ row }"><span class="oo-num">¥{{ Number(row.costAmount ?? 0).toFixed(2) }}</span></template>
        </el-table-column>
        <el-table-column label="事由" width="100">
          <template #default="{ row }">
            <span v-if="row.reasonCode">{{ reasonLabel(row.reasonCode) }}</span>
            <span v-else class="bz-dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="报销" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ reimburseLabel(row.reimburseStatus) }}</el-tag>
            <div v-if="row.reimburseAmount" class="bz-dim oo-num">
              ¥{{ Number(row.reimburseAmount).toFixed(2) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="light">{{ statusLabel(row.status) }}</el-tag>
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
    </OOCard>

    <el-dialog v-model="dialog" width="720px" align-center>
      <template #header>
        <div class="oo-dialog-head">
          <span class="oo-dialog-icon"><OOIcon name="route" :size="18" /></span>
          <div>
            <h3 class="oo-dialog-title">{{ editing ? "编辑出差" : "新增出差" }}</h3>
            <p class="oo-dialog-desc">填写行程与报销信息；坐标可自动解析，也可手动填写</p>
          </div>
        </div>
      </template>
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
        <el-form-item label="坐标">
          <el-button link type="primary" @click="manualCoords = !manualCoords">
            {{ manualCoords ? "收起手动坐标" : "手动填写坐标" }}
          </el-button>
          <span v-if="quotaHint" class="hint">{{ quotaHint }}</span>
        </el-form-item>
        <el-form-item v-if="manualCoords" label="经纬度">
          <div class="row">
            <el-input v-model="manual.originLng" placeholder="出发地经度" class="coord" />
            <el-input v-model="manual.originLat" placeholder="出发地纬度" class="coord" />
          </div>
          <div class="row mt-2">
            <el-input v-model="manual.destLng" placeholder="目的地经度" class="coord" />
            <el-input v-model="manual.destLat" placeholder="目的地纬度" class="coord" />
            <el-button @click="applyManualCoords">应用坐标</el-button>
          </div>
          <div class="hint">格式：小数度（如 116.307503, 39.984104），北京为东经北纬。留空表示该端无坐标。</div>
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
        <el-form-item label="出差事由">
          <el-select v-model="form.reasonCode" clearable placeholder="未指定" class="w-full">
            <el-option
              v-for="r in caps?.tripReasons ?? []"
              :key="r.value"
              :label="r.label"
              :value="r.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="报销">
          <div class="row">
            <el-select v-model="form.reimburseStatus" class="w-full">
              <el-option
                v-for="s in caps?.reimburseStatus ?? []"
                :key="s.value"
                :label="s.label"
                :value="s.value"
              />
            </el-select>
            <el-input-number
              v-model="form.reimburseAmount"
              :min="0"
              :step="100"
              :disabled="form.reimburseStatus === 'none'"
            />
          </div>
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
.bz-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr));
  gap: var(--oo-space-3);
  margin-bottom: var(--oo-space-5);
}

.row {
  display: flex;
  gap: var(--oo-space-2);
  width: 100%;
  flex-wrap: wrap;
}
.mt-2 {
  margin-top: var(--oo-space-2);
}
.hint {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
  line-height: 1.6;
}
.stops {
  width: 100%;
}
.stop-row {
  display: flex;
  gap: var(--oo-space-1);
  align-items: center;
  margin-bottom: var(--oo-space-2);
  flex-wrap: wrap;
}
.coord {
  width: 150px;
}
.num {
  width: 110px;
}
.w-full {
  width: 100%;
}
.bz-dim {
  color: var(--oo-text-tertiary);
  font-size: var(--oo-text-xs);
}
.mb {
  margin-bottom: var(--oo-space-5);
}

.oo-dialog-head {
  display: flex;
  align-items: center;
  gap: var(--oo-space-3);
}
.oo-dialog-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--oo-radius-sm);
  background: var(--oo-brand-soft);
  color: var(--oo-brand);
}
.oo-dialog-title {
  margin: 0;
  font-size: var(--oo-text-lg);
  font-weight: var(--oo-weight-semibold);
  color: var(--oo-text-primary);
}
.oo-dialog-desc {
  margin: 2px 0 0;
  font-size: var(--oo-text-xs);
  color: var(--oo-text-tertiary);
}

@media (max-width: 560px) {
  .bz-kpis {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--oo-space-2);
  }
  .coord {
    width: 100%;
  }
  .num {
    width: 92px;
  }
}
</style>
