<script setup lang="ts">
/** 腾讯地图 GL JS 组件（Key 代理模式）。
 *
 * 合规要点（不可省略）：
 * 1. SDK 从官方 CDN 加载且**不带 key 参数**；
 * 2. `window._TMapSecurityConfig.serviceHost` 必须**在 SDK 加载前**设置，
 *    否则请求不会走代理；
 * 3. 前端全程不出现明文 Key —— Key 存服务端，由后端反代注入。
 *
 * 注意：不要再调 TMap.setConfig()，与 _TMapSecurityConfig 同时使用会导致底图空白。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { mapServiceHost } from "@/api/biz-dashboard";
import { chartColor, onChartThemeChange } from "@/composables/chart-theme";

/** 地图上的一个坐标点。 */
type MapPoint = { lng: number; lat: number; title?: string };

const props = withDefaults(
  defineProps<{
    /** 标记点列表 */
    markers?: MapPoint[];
    /** 路径线列表：每条线是一组按顺序排列的点（如「出发地 → 途经点 → 目的地」） */
    pathLines?: MapPoint[][];
    height?: string;
  }>(),
  { markers: () => [], pathLines: () => [], height: "360px" },
);

const emit = defineEmits<{ (e: "error", msg: string): void }>();

const container = ref<HTMLElement | null>(null);
const ready = ref(false);
const failed = ref("");
let mapInstance: any = null;
let markerLayer: any = null;
let pathLayer: any = null;
let sdkPromise: Promise<any> | null = null;

declare global {
  interface Window {
    TMap?: any;
    _TMapSecurityConfig?: { serviceHost: string };
  }
}

/** 加载腾讯地图 GL JS（官方 CDN，无 key 参数）。 */
function loadSdk(): Promise<any> {
  if (window.TMap) return Promise.resolve(window.TMap);
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve, reject) => {
    // 必须在 SDK 脚本注入之前设置，否则 SDK 不会走代理
    window._TMapSecurityConfig = { serviceHost: mapServiceHost };
    const s = document.createElement("script");
    s.src = "https://map.qq.com/api/gljs?v=1.exp&libraries=service";
    s.onload = () => (window.TMap ? resolve(window.TMap) : reject(new Error("SDK 加载异常")));
    s.onerror = () => reject(new Error("地图 SDK 加载失败，请检查 NAS 是否能访问外网"));
    document.head.appendChild(s);
  });
  return sdkPromise;
}

function drawLayers() {
  if (!mapInstance || !window.TMap) return;
  const TMap = window.TMap;

  if (markerLayer) {
    markerLayer.setGeometries([]);
  } else {
    markerLayer = new TMap.MultiMarker({ map: mapInstance, styles: {} });
  }
  if (props.markers.length) {
    markerLayer.setGeometries(
      props.markers.map((m, i) => ({
        id: String(i),
        position: new TMap.LatLng(m.lat, m.lng),
        properties: { title: m.title || "" },
      })),
    );
  } else {
    markerLayer.setGeometries([]);
  }

  if (pathLayer) {
    pathLayer.setGeometries([]);
  } else {
    pathLayer = new TMap.MultiPolyline({
      map: mapInstance,
      styles: {
        default: new TMap.PolylineStyle({
          // 路径线颜色跟随图表色板（随深浅色切换）
          color: chartColor(0),
          width: 4,
          borderWidth: 0,
          lineCap: "round",
        }),
      },
    });
  }
  // MultiPolyline 没有 setPaths 方法，只有 setGeometries(geometries)；
  // 每个 geometry 形如 { id, styleId, paths: LatLng[] }（paths 是一维点序列）。
  const lines = props.pathLines
    .filter((line) => line.length >= 2)
    .map((line, i) => ({
      id: `path-${i}`,
      styleId: "default",
      paths: line.map((p) => new TMap.LatLng(p.lat, p.lng)),
    }));
  pathLayer.setGeometries(lines);
}

/** 以所有点为中心定位视野。 */
function fitView() {
  if (!mapInstance || !window.TMap) return;
  const TMap = window.TMap;
  const pts = [...props.markers, ...props.pathLines.flat()].filter(
    (p) => Number.isFinite(p.lng) && Number.isFinite(p.lat),
  );
  if (!pts.length) return;
  const bounds = new TMap.LatLngBounds();
  pts.forEach((p) => bounds.extend(new TMap.LatLng(p.lat, p.lng)));
  mapInstance.fitBounds(bounds, { padding: 60 });
}

onMounted(async () => {
  try {
    const TMap = await loadSdk();
    if (!container.value) return;
    mapInstance = new TMap.Map(container.value, {
      center: new TMap.LatLng(39.984104, 116.307503),
      zoom: 10,
    });
    mapInstance.on("click", (e: any) => {
      emit("error", "");
    });
    ready.value = true;
    drawLayers();
    fitView();
  } catch (e) {
    failed.value = e instanceof Error ? e.message : String(e);
    emit("error", failed.value);
  }
});

watch(
  () => [props.markers, props.pathLines],
  () => {
    drawLayers();
    fitView();
  },
  { deep: true },
);

onBeforeUnmount(() => {
  try {
    mapInstance?.destroy?.();
  } catch {
    /* 忽略销毁异常 */
  }
  mapInstance = null;
});
</script>

<template>
  <div class="bz-map">
    <div v-if="failed" class="bz-map-err">
      <el-alert type="warning" :closable="false" :title="failed" show-icon />
    </div>
    <div
      v-else
      ref="container"
      class="bz-map-canvas"
      :style="{ height: props.height }"
    />
    <div v-if="!ready && !failed" class="bz-map-loading">
      <span class="oo-spin oo-spin-sm" aria-hidden="true" />
      <span>地图加载中…</span>
    </div>
  </div>
</template>

<style scoped>
.bz-map {
  position: relative;
  width: 100%;
}
.bz-map-canvas {
  width: 100%;
  border-radius: var(--oo-radius-lg);
  border: 1px solid var(--oo-border-subtle);
  box-shadow: var(--oo-shadow-sm);
  overflow: hidden;
}
.bz-map-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--oo-space-2);
  background: var(--oo-bg-surface-2);
  color: var(--oo-text-secondary);
  font-size: var(--oo-text-sm);
}
.bz-map-err {
  width: 100%;
}

/*
 * 腾讯地图 SDK 自带的比例尺与版权文字是深色硬编码（#000 / #333），
 * 落在深色主题的地图容器里几乎不可读（实测 1.21:1 / 1.38:1）。
 * 这里用 :deep() 覆写为跟随主题的次要文字色。
 */
.bz-map-canvas :deep(.tmap-scale-text) {
  color: var(--oo-text-secondary) !important;
  text-shadow: 0 0 3px var(--oo-bg-surface);
}

.bz-map-canvas :deep(.logo-text) {
  color: var(--oo-text-tertiary) !important;
  text-shadow: 0 0 3px var(--oo-bg-surface);
}
</style>
