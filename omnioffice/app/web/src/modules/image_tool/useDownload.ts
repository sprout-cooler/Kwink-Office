/** 图片下载：统一用 <a download>。
 *
 * 为什么不用 window.open：应用挂在网关子路径下，window.open 会被浏览器
 * 当作页面导航，丢掉应用外壳；<a download> 才是真正的下载行为。
 */
import { assetFileUrl, type ImageAssetDto } from "@/api/image-tool";

export function downloadAsset(asset: ImageAssetDto): void {
  const el = document.createElement("a");
  el.href = assetFileUrl(asset.id, true);
  el.download = asset.filename;
  document.body.appendChild(el);
  el.click();
  el.remove();
}
