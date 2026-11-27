<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import katex from 'katex';
import PdfReader from './PdfReader.vue';
import './learning.css';

type Citation = { material_id: string; title: string; anchor: string; section?: string; page?: number; excerpt?: string };
type Block = { anchor: string; section: string; text: string; page: number | null };
type Trail = { id: string; kind: string; material_id: string; updated_at: number; payload: any };
type Material = { id: string; title: string; kind: string; source: string; status: string; can_ask: boolean; error?: string; blocks: Block[]; records: Trail[]; pages?: any[] };
const props = defineProps<{ identity: { sid: string; name: string; token: string }; mode: string; target: { id: string; anchor?: string; page?: number } | null }>();
const catalog = ref<Material[]>([]), trail = ref<Trail[]>([]), current = ref<Material | null>(null);
const busy = ref(false), notice = ref(''), search = ref(''), filter = ref('all');
const showUpload = ref(false), uploadTitle = ref(''), uploadText = ref(''), uploadFile = ref<File | null>(null);
const selection = ref(''), anchor = ref(''), page = ref(1), question = ref('');
const chats = ref<{ question: string; answer: string; citation: Citation }[]>([]);
const activeQuiz = ref<{ quiz_id: string; question: { stem: string; options: string[]; concept: string }; citation: Citation } | null>(null);
const choice = ref(''), result = ref<any>(null), reader = ref<HTMLElement>();
const recordFilter = ref('all'), highlighted = ref(''), loading = ref(true);
let positionTimer: ReturnType<typeof setTimeout> | undefined;
let openGeneration = 0, disposed = false;
const filtered = computed(() => catalog.value.filter(m => (filter.value === 'all' || m.source === filter.value) && m.title.toLowerCase().includes(search.value.toLowerCase())));
const positions = computed(() => trail.value.filter(t => t.kind === 'position'));
const filteredTrail = computed(() => trail.value.filter(t => t.kind !== 'chat' && (recordFilter.value === 'all' || t.kind === recordFilter.value)));
const currentBlock = computed(() => current.value?.blocks.find(b => b.anchor === anchor.value) || null);
const currentHasText = computed(() => Boolean(currentBlock.value));
async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers); headers.set('Authorization', 'Bearer ' + props.identity.token);
  const response = await fetch('/api/learning' + path, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : '操作失败，请检查输入后重试');
  }
  return response.json();
}
function post(path: string, body: unknown, method = 'POST') { return api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }
async function run(action: () => Promise<unknown>) {
  if (busy.value) return;
  busy.value = true; notice.value = '';
  try { await action(); } catch (error) { notice.value = error instanceof Error ? error.message : '操作失败'; }
  finally { busy.value = false; }
}
async function refresh() {
  const [m, r] = await Promise.all([api('/materials'), api('/records')]); catalog.value = m.materials; trail.value = r.records;
}
function markdown(text: string) {
  const equations: string[] = [], code: string[] = [];
  let input = text.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, s => 'CODETOKEN' + (code.push(s) - 1) + 'END');
  input = input.replace(/\$\$([\s\S]+?)\$\$|(?<!\$)\$([^$\n]+)\$/g, (_, display: string, inline: string) => {
    const html = katex.renderToString(display ?? inline, { displayMode: Boolean(display), throwOnError: false }); return 'MATHTOKEN' + (equations.push(html) - 1) + 'END';
  });
  code.forEach((value, i) => { input = input.replace('CODETOKEN' + i + 'END', value); });
  let html = String(marked.parse(input)); equations.forEach((value, i) => { html = html.replace('MATHTOKEN' + i + 'END', value); });
  return DOMPurify.sanitize(html);
}
function sourceName(source: string) { return ({ personal: '个人资料', course: '教师课件', textbook: '课程教材' } as Record<string, string>)[source] || source; }
function statusName(m: Material) { return m.status === 'parse_failed' ? '解析失败' : m.can_ask ? '可阅读 · 可提问' : '可阅读 · 无文字'; }
function displayDate(timestamp: number) { return new Date(timestamp * 1000).toLocaleString('zh-CN'); }
function sourceBody() { return { material_id: current.value!.id, anchor: anchor.value, selection: selection.value }; }
async function persistPosition(keepalive = false) {
  if (!current.value) return;
  const maximum = (reader.value?.scrollHeight || 0) - (reader.value?.clientHeight || 0);
  const body = { material_id: current.value.id, anchor: anchor.value, page: page.value, scroll: maximum > 0 ? (reader.value?.scrollTop || 0) / maximum : 0 };
  await fetch('/api/learning/position', { method: 'PUT', headers: { Authorization: 'Bearer ' + props.identity.token, 'Content-Type': 'application/json' }, body: JSON.stringify(body), keepalive });
}
function schedulePosition() { if (positionTimer) clearTimeout(positionTimer); positionTimer = setTimeout(() => { void persistPosition().catch(() => {}); }, 450); }
function onScroll() {
  if (current.value?.kind === 'markdown' && reader.value) {
    const top = reader.value.getBoundingClientRect().top + 70;
    const block = Array.from(reader.value.querySelectorAll<HTMLElement>('[data-anchor]')).find(el => el.getBoundingClientRect().bottom > top);
    if (block?.dataset.anchor && block.dataset.anchor !== anchor.value) { anchor.value = block.dataset.anchor; selection.value = ''; }
  }
  schedulePosition();
}
async function open(id: string, cite?: Partial<Citation>) {
  await persistPosition().catch(() => {}); if (positionTimer) clearTimeout(positionTimer);
  const generation = ++openGeneration; loading.value = true; notice.value = '';
  try {
    const data: Material = await api('/materials/' + encodeURIComponent(id));
    if (disposed || generation !== openGeneration) return;
    current.value = data; selection.value = ''; activeQuiz.value = null; result.value = null; choice.value = ''; question.value = '';
    chats.value = data.records.filter(t => t.kind === 'chat').reverse().map(t => t.payload);
    const position = data.records.find(t => t.kind === 'position')?.payload;
    anchor.value = cite?.anchor || position?.anchor || data.blocks[0]?.anchor || (data.kind === 'pdf' ? 'page-1' : '');
    page.value = cite?.page || (data.kind === 'pdf' ? Number(anchor.value.replace('page-', '')) || position?.page || 1 : 1);
    await nextTick();
    if (reader.value && data.kind === 'markdown') { if (cite?.anchor) jumpTo(cite); else reader.value.scrollTop = (position?.scroll || 0) * (reader.value.scrollHeight - reader.value.clientHeight); }
    schedulePosition();
  } catch (error) { notice.value = error instanceof Error ? error.message : '资料载入失败'; }
  finally { if (generation === openGeneration) loading.value = false; }
}
function selectMarkdown() {
  const value = window.getSelection();
  if (!value?.rangeCount || !reader.value?.contains(value.anchorNode) || !reader.value?.contains(value.focusNode)) return;
  const node = value.anchorNode?.nodeType === Node.ELEMENT_NODE ? value.anchorNode as Element : value.anchorNode?.parentElement;
  const end = value.focusNode?.nodeType === Node.ELEMENT_NODE ? value.focusNode as Element : value.focusNode?.parentElement;
  const block = node?.closest<HTMLElement>('[data-anchor]');
  if (!block || end?.closest('[data-anchor]') !== block) { if (value.toString().trim()) notice.value = '请在同一个小节内划选内容。'; return; }
  const text = value.toString().trim(); if (text) { selection.value = text; anchor.value = block.dataset.anchor!; notice.value = ''; }
}
function selectPdf(value: { text: string; anchor: string; page: number }) { selection.value = value.text; anchor.value = value.anchor; page.value = value.page; notice.value = ''; }
function pdfPage(value: number) { if (page.value !== value || anchor.value !== 'page-' + value) selection.value = ''; page.value = value; anchor.value = 'page-' + value; schedulePosition(); }
function jumpTo(cite: Partial<Citation>) {
  if (!current.value) return;
  const targetAnchor = cite.anchor || '';
  if (cite.material_id && cite.material_id !== current.value.id) { void open(cite.material_id, cite); return; }
  if (current.value.kind === 'pdf') { page.value = cite.page || Number(targetAnchor.replace('page-', '')) || 1; anchor.value = 'page-' + page.value; }
  else { const block = reader.value?.querySelector<HTMLElement>('[data-anchor="' + CSS.escape(targetAnchor) + '"]'); block?.scrollIntoView({ behavior: 'smooth', block: 'start' }); anchor.value = targetAnchor; }
  highlighted.value = targetAnchor; selection.value = cite.excerpt || ''; schedulePosition();
}
async function upload() {
  await run(async () => {
    const body = new FormData(); body.set('title', uploadTitle.value);
    if (uploadFile.value) body.set('file', uploadFile.value); else body.set('markdown', uploadText.value);
    const created = await api('/materials', { method: 'POST', body });
    showUpload.value = false; uploadTitle.value = ''; uploadText.value = ''; uploadFile.value = null;
    await refresh(); await open(created.id);
  });
}
function chooseFile(event: Event) { uploadFile.value = (event.target as HTMLInputElement).files?.[0] || null; if (uploadFile.value && !uploadTitle.value) uploadTitle.value = uploadFile.value.name.replace(/\.[^.]+$/, ''); }
async function ask(hint = false) {
  if (!question.value.trim()) { notice.value = '请输入你的问题。'; return; }
  await run(async () => { const response = await post('/ask', { ...sourceBody(), question: question.value.trim(), hint }); chats.value.push(response); question.value = ''; });
}
async function bookmark() { await run(async () => { await post('/bookmarks', sourceBody()); await refresh(); notice.value = '已收藏选中片段，可以从学习记录返回原文。'; }); }
async function generateQuiz(retry = false) {
  await run(async () => {
    const body = retry ? { material_id: current.value!.id, retry_id: result.value.quiz_id } : sourceBody();
    activeQuiz.value = await post('/quiz', body);
    result.value = null;
    choice.value = '';
  });
}
async function grade() { await run(async () => { result.value = await post('/grade', { quiz_id: activeQuiz.value!.quiz_id, answer: choice.value }); await refresh(); }); }
async function back() { await persistPosition().catch(() => {}); current.value = null; await refresh(); }
async function deleteBookmark(id: string) { await run(async () => { await api('/records/' + id, { method: 'DELETE' }); await refresh(); }); }
watch(() => props.mode, () => { if (props.mode === 'records') void back(); });
watch(() => props.target, value => { if (value) void open(value.id, value); });
function flush() { if (!document.body.classList.contains('gated')) void persistPosition(true).catch(() => {}); }
onMounted(async () => { (window as any).zxBeforeLogout = async () => { await persistPosition().catch(() => {}); }; window.addEventListener('pagehide', flush); try { await refresh(); if (props.target) await open(props.target.id, props.target); } catch (error) { notice.value = error instanceof Error ? error.message : '载入失败'; } finally { loading.value = false; } });
onBeforeUnmount(() => { delete (window as any).zxBeforeLogout; disposed = true; openGeneration++; if (positionTimer) clearTimeout(positionTimer); flush(); window.removeEventListener('pagehide', flush); });
</script>

<template>
  <main class="learning-main">
    <p v-if="notice" class="learn-notice" role="status">{{ notice }}</p>
    <template v-if="!current">
      <header class="learn-heading"><div><div class="eyebrow">{{ mode === 'records' ? 'YOUR LEARNING TRAIL' : 'YOUR LEARNING SPACE' }}</div><h1>{{ mode === 'records' ? '收藏与学习记录' : '我的学习' }}</h1><p>{{ mode === 'records' ? '每一个收藏、阅读位置与自测结果，都能带你回到原文。' : '打开一份资料，开始阅读、提问和自测。' }}</p></div><button v-if="mode !== 'records'" class="da-btn primary" @click="showUpload = true">＋ 上传个人资料</button></header>
      <p v-if="loading" role="status">正在载入…</p>
      <template v-else-if="mode !== 'records'">
        <section v-if="positions.length" class="continue-strip"><div class="eyebrow">CONTINUE READING</div><h2>继续阅读</h2><div class="continue-grid"><button v-for="item in positions.slice(0, 3)" :key="item.id" @click="open(item.material_id)"><strong>{{ item.payload.title }}</strong><span>{{ displayDate(item.updated_at) }} · 继续 →</span></button></div></section>
        <div class="library-toolbar"><div class="learn-tabs"><button v-for="item in [{ id: 'all', label: '全部资料' }, { id: 'personal', label: '个人资料' }, { id: 'course', label: '教师课件' }, { id: 'textbook', label: '课程教材' }]" :key="item.id" :class="{ active: filter === item.id }" @click="filter = item.id">{{ item.label }}</button></div><input v-model="search" type="search" placeholder="搜索资料标题" aria-label="搜索资料" /></div>
        <div v-if="!filtered.length" class="learn-empty">这里还没有资料。上传 PDF 或 Markdown，或查看已发布的课程课件。</div>
        <section class="material-grid"><button v-for="item in filtered" :key="item.id" class="material-card" @click="open(item.id)"><div class="material-card-top"><span class="material-format">{{ item.kind === 'pdf' ? 'PDF' : 'MD' }}</span><span>{{ sourceName(item.source) }}</span></div><h2>{{ item.title }}</h2><div class="material-card-bottom"><span :class="{ 'error-label': item.status === 'parse_failed' }">{{ statusName(item) }}</span><span>打开 ↗</span></div></button></section>
      </template>
      <template v-else>
        <div class="learn-tabs record-tabs"><button v-for="item in [{ id: 'all', label: '全部记录' }, { id: 'bookmark', label: '收藏片段' }, { id: 'position', label: '最近阅读' }, { id: 'quiz', label: '自测与复练' }]" :key="item.id" :class="{ active: recordFilter === item.id }" @click="recordFilter = item.id">{{ item.label }}</button></div>
        <p v-if="!filteredTrail.length" class="learn-empty">还没有学习记录。阅读资料后，你的进度、收藏和自测会保存在这里。</p>
        <article v-for="item in filteredTrail" :key="item.id" class="trail-card"><div class="trail-meta">{{ item.kind === 'bookmark' ? '收藏片段' : item.kind === 'quiz' ? '自测结果' : '阅读位置' }} · {{ displayDate(item.updated_at) }}</div><h2>{{ item.payload.title }}</h2><blockquote v-if="item.payload.excerpt">{{ item.payload.excerpt }}</blockquote><template v-if="item.kind === 'quiz'"><p>{{ item.payload.result.stem }}</p><strong>{{ item.payload.result.score }} 分 · {{ item.payload.result.correct ? '回答正确' : '需要复习' }}</strong><p>{{ item.payload.result.explanation }}</p></template><div class="trail-actions"><button class="da-btn secondary sm" @click="open(item.material_id, item.payload.citation || item.payload)">返回原文 →</button><button v-if="item.kind === 'bookmark'" class="da-btn ghost sm" @click="deleteBookmark(item.id)">取消收藏</button></div></article>
      </template>
    </template>
    <template v-else>
      <header class="reading-header"><button class="da-btn secondary sm" @click="back">← 返回{{ mode === 'records' ? '记录' : '资料列表' }}</button><div><h1>{{ current.title }}</h1><span>{{ sourceName(current.source) }} · {{ statusName(current) }}</span></div></header>
      <p v-if="current.error" class="learn-notice" role="alert">{{ current.error }}</p>
      <div class="learning-workbench"><section class="reading-pane"><div class="reading-toolbar"><span>{{ current.kind === 'pdf' ? 'PDF 原文' : currentBlock?.section || '资料原文' }}</span><select v-if="current.kind === 'markdown'" aria-label="跳转小节" :value="anchor" @change="jumpTo({ anchor: ($event.target as HTMLSelectElement).value })"><option v-for="b in current.blocks" :key="b.anchor" :value="b.anchor">{{ b.section }}</option></select></div><div ref="reader" class="reading-scroll" @scroll="onScroll" @mouseup="selectMarkdown" @keyup="selectMarkdown"><PdfReader v-if="current.kind === 'pdf'" :key="current.id" :url="'/api/learning/materials/' + encodeURIComponent(current.id) + '/file'" :token="identity.token" :page="page" @select="selectPdf" @page="pdfPage" @notice="notice = $event" /><template v-else><article v-for="block in current.blocks" :key="block.anchor" :data-anchor="block.anchor" :class="{ 'source-highlight': highlighted === block.anchor }" class="reading-block md" v-html="markdown(block.text)"></article></template></div></section>
        <aside class="learning-assistant"><div class="assistant-heading"><span class="brand-mark">智</span><div><h2>学习助手</h2><p>围绕当前资料，一起弄懂问题。</p></div></div>
          <div class="selection-card"><div class="selection-title">{{ selection ? '已选择的内容' : currentBlock ? '当前页 / 小节' : '当前页没有可提取文字' }}<button v-if="selection" @click="selection = ''" aria-label="清除选区">×</button></div><blockquote>{{ selection || currentBlock?.text.slice(0, 160) || '你仍然可以阅读原件；提问和自测时，请换一页有文字的内容。' }}</blockquote><button class="da-btn secondary sm" :disabled="!selection || busy" @click="bookmark">☆ 收藏片段</button></div>
          <div class="assistant-conversation"><div v-if="!chats.length" class="assistant-welcome">选中左侧的一段内容，向我提问。也可以从当前小节主动发起一次自测。</div><article v-for="(chat, index) in chats" :key="index" class="learning-chat"><p class="learning-question">{{ chat.question }}</p><div class="md" v-html="markdown(chat.answer)"></div><button class="source-link" @click="jumpTo(chat.citation)">↗ {{ chat.citation.section || '返回出处' }}</button></article></div>
          <form class="learning-composer" @submit.prevent="ask(false)"><label class="sr-only" for="learning-question">向学习助手提问</label><textarea id="learning-question" v-model="question" placeholder="这段话是什么意思？可以举个例子吗？" maxlength="2000" rows="3"></textarea><div><button type="button" class="da-btn secondary sm" :disabled="busy || !currentHasText" @click="ask(true)">给我提示</button><button type="submit" class="da-btn primary sm" :disabled="busy || !currentHasText">{{ busy ? '处理中…' : '发送问题 ↑' }}</button></div></form>
          <section class="material-quiz"><div class="quiz-section-head"><h2>主动自测</h2><button class="da-btn secondary sm" :disabled="busy || !currentHasText" @click="generateQuiz(false)">测一下我</button></div><p v-if="!activeQuiz" class="learn-muted">从选区、当前页或当前小节出一道题。</p><template v-else><h3>{{ activeQuiz.question.stem }}</h3><label v-for="(option, index) in activeQuiz.question.options" :key="index" class="material-option" :class="{ selected: choice === 'ABCD'[index] }"><input v-model="choice" type="radio" name="material-choice" :value="'ABCD'[index]" :disabled="!!result || busy" />{{ option }}</label><button v-if="!result" class="da-btn primary sm" :disabled="busy || !choice" @click="grade">提交作答</button><div v-if="result" class="material-result"><strong>{{ result.correct ? '回答正确' : '需要复习' }} · {{ result.score }} 分</strong><p>正确选项：{{ result.answer }}</p><p>{{ result.explanation }}</p><template v-if="result.diagnosis"><h3>错因与复习建议</h3><p>{{ result.diagnosis }}</p><p>{{ result.review_advice }}</p><button class="da-btn secondary sm" :disabled="busy" @click="generateQuiz(true)">再练一道同知识点的题</button></template><p v-else-if="!result.correct" class="learn-muted">暂时无法确定具体错因，请先结合解析回看原文。</p><button class="source-link" @click="jumpTo(result.citation)">↗ 返回原文依据</button></div></template></section>
        </aside>
      </div>
    </template>
    <div v-if="showUpload" class="learning-modal-backdrop" @click.self="showUpload = false"><form class="learning-upload" @submit.prevent="upload" role="dialog" aria-modal="true" aria-labelledby="upload-title"><div class="upload-head"><h2 id="upload-title">上传个人资料</h2><button type="button" :disabled="busy" @click="showUpload = false" aria-label="关闭">×</button></div><p class="learn-muted">仅你自己可以查看这些资料和对应的学习记录。</p><label>资料标题<input v-model="uploadTitle" required maxlength="255" placeholder="例如：过拟合与正则化笔记" /></label><label>PDF 或 Markdown 文件<input type="file" accept=".pdf,.md" @change="chooseFile" /></label><label v-if="!uploadFile">也可以直接粘贴 Markdown 正文<textarea v-model="uploadText" rows="7" placeholder="# 我的学习笔记"></textarea></label><p v-if="notice" class="learn-notice" role="alert">{{ notice }}</p><button class="da-btn primary" :disabled="busy || !uploadTitle.trim() || (!uploadFile && !uploadText.trim())">{{ busy ? '上传并解析中…' : '保存并开始阅读' }}</button></form></div>
  </main>
</template>
