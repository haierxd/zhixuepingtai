<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'pdfjs-dist/web/pdf_viewer.css';

GlobalWorkerOptions.workerSrc = workerUrl;
const props = defineProps<{ url: string; page: number; token: string }>();
const emit = defineEmits<{ select: [value: { text: string; anchor: string; page: number }]; page: [value: number]; notice: [value: string] }>();
const canvas = ref<HTMLCanvasElement>();
const layer = ref<HTMLDivElement>();
const surface = ref<HTMLDivElement>();
const count = ref(0), current = ref(props.page || 1), boxMode = ref(false), loading = ref(true), failure = ref('');
const box = ref<{ x: number; y: number; w: number; h: number } | null>(null);
let pdf: PDFDocumentProxy | null = null;
let renderTask: RenderTask | null = null;
let textLayer: TextLayer | null = null;
let start: { x: number; y: number } | null = null;
let generation = 0, disposed = false;
async function draw() {
  const version = ++generation;
  if (!pdf) return;
  loading.value = true; failure.value = '';
  renderTask?.cancel(); textLayer?.cancel();
  try {
    const page = await pdf.getPage(current.value);
    await nextTick();
    if (version !== generation || disposed || !canvas.value || !layer.value || !surface.value) return;
    const native = page.getViewport({ scale: 1 });
    const width = Math.min(900, Math.max(260, surface.value.parentElement?.clientWidth || 650));
    const viewport = page.getViewport({ scale: width / native.width });
    const ratio = window.devicePixelRatio || 1;
    canvas.value.width = Math.round(viewport.width * ratio); canvas.value.height = Math.round(viewport.height * ratio);
    canvas.value.style.width = viewport.width + 'px'; canvas.value.style.height = viewport.height + 'px';
    surface.value.style.width = viewport.width + 'px'; surface.value.style.height = viewport.height + 'px';
    surface.value.style.setProperty('--scale-factor', String(viewport.scale));
    layer.value.replaceChildren();
    renderTask = page.render({ canvasContext: canvas.value.getContext('2d')!, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
    await renderTask.promise;
    if (version !== generation || disposed) return;
    textLayer = new TextLayer({ textContentSource: await page.getTextContent(), container: layer.value, viewport });
    await textLayer.render(); emit('page', current.value);
  } catch (error) {
    if (version === generation && !disposed && !(error instanceof Error && error.name === 'RenderingCancelledException')) failure.value = 'PDF 页面载入失败，请检查文件。';
  } finally { if (version === generation) loading.value = false; }
}
function selectText() {
  if (boxMode.value) return;
  const selection = window.getSelection();
  if (!selection?.rangeCount || !layer.value?.contains(selection.anchorNode) || !layer.value?.contains(selection.focusNode)) return;
  const text = selection.toString().trim();
  if (text) emit('select', { text, anchor: 'page-' + current.value, page: current.value });
}
function down(event: PointerEvent) {
  if (!boxMode.value || !surface.value) return;
  const bounds = surface.value.getBoundingClientRect();
  start = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  box.value = { ...start, w: 0, h: 0 }; surface.value.setPointerCapture(event.pointerId); event.preventDefault();
}
function move(event: PointerEvent) {
  if (!start || !surface.value) return;
  const bounds = surface.value.getBoundingClientRect();
  const x = event.clientX - bounds.left, y = event.clientY - bounds.top;
  box.value = { x: Math.min(start.x, x), y: Math.min(start.y, y), w: Math.abs(x - start.x), h: Math.abs(y - start.y) };
}
function up() {
  if (!start || !surface.value || !box.value || !layer.value) return;
  const bounds = surface.value.getBoundingClientRect(), b = box.value;
  const text = Array.from(layer.value.querySelectorAll('span')).filter(span => {
    const r = span.getBoundingClientRect();
    return r.width > 0 && r.right > bounds.left + b.x && r.left < bounds.left + b.x + b.w && r.bottom > bounds.top + b.y && r.top < bounds.top + b.y + b.h;
  }).map(span => span.textContent || '').join(' ').trim();
  if (text) emit('select', { text, anchor: 'page-' + current.value, page: current.value });
  else emit('notice', '选中的区域没有可提取文字，请换一段内容。');
  start = null;
}
watch(() => props.page, value => { if (value && value !== current.value) { current.value = value; void draw(); } });
function changePage(value: number) {
  if (!Number.isInteger(value) || value < 1 || value > count.value || loading.value) return;
  current.value = value; box.value = null; void draw();
}
onMounted(async () => {
  try {
    pdf = await getDocument({ url: props.url, httpHeaders: { Authorization: 'Bearer ' + props.token },
      cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/' }).promise;
    if (disposed) { await pdf.destroy(); return; }
    count.value = pdf.numPages; current.value = Math.min(count.value, Math.max(1, current.value)); await draw();
  } catch { failure.value = 'PDF 无法打开，请检查文件是否损坏或加密。'; loading.value = false; }
});
onBeforeUnmount(() => { disposed = true; generation++; renderTask?.cancel(); textLayer?.cancel(); void pdf?.destroy(); });
</script>
<template>
  <div class="pdf-controls">
    <button class="da-btn secondary sm" :disabled="current === 1 || loading" @click="changePage(current - 1)">上一页</button>
    <label>第 <input aria-label="PDF 页码" type="number" :value="current" min="1" :max="count" @change="changePage(Number(($event.target as HTMLInputElement).value))" /> / {{ count }} 页</label>
    <button class="da-btn secondary sm" :disabled="current === count || loading" @click="changePage(current + 1)">下一页</button>
    <button class="da-btn secondary sm" :aria-pressed="boxMode" @click="boxMode = !boxMode; box = null">{{ boxMode ? '✓ 框选文字' : '框选文字' }}</button>
  </div>
  <p v-if="failure" role="alert" class="learn-notice">{{ failure }}</p>
  <div class="pdf-scroll"><div ref="surface" class="pdf-surface" :class="{ boxing: boxMode }" @pointerdown="down" @pointermove="move" @pointerup="up" @mouseup="selectText" @keyup="selectText">
    <canvas ref="canvas"></canvas><div ref="layer" class="textLayer"></div>
    <div v-if="box" class="pdf-selection-box" :style="{ left: box.x + 'px', top: box.y + 'px', width: box.w + 'px', height: box.h + 'px' }"></div>
  </div></div>
  <p v-if="loading" class="learn-muted" role="status">正在载入 PDF…</p>
</template>
