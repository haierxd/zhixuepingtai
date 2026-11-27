/* ============================================================
   智学 — 前端应用 v2(原生 JS,无构建)
   ============================================================ */

const state = {
  view: "dashboard",
  profile: null,
  topics: null,
  chat: [],
  chatLoaded: false,
  chatTopic: null,
  quiz: null,
  quizTopic: null,
  readerTopic: null,   // 当前正在阅读的课程(电子书阅读页)
  streaming: false,
  abort: null,
  health: null,
  highlightTopic: null,
  identity: null,   // {role:'student'|'teacher', sid?, name?, pass?}
  viewSid: null,    // 教师只读查看某学生时,api 附加 ?student_id=
  readonly: false,  // 教师只读模式:隐藏学生侧写操作
};

const NAV_STUDENT = [
  { id: "learning", icon: "library", label: "我的学习" },
  { id: "dashboard", icon: "layout-dashboard", label: "学习概览" },
  { id: "chat", icon: "messages-square", label: "学习对话" },
  { id: "topics", icon: "book-open", label: "知识图谱" },
  { id: "quiz", icon: "clipboard-check", label: "智能测评" },
  { id: "records", icon: "bookmark", label: "收藏与学习记录" },
  { id: "mistakes", icon: "notebook-pen", label: "错题本" },
  { id: "report", icon: "file-text", label: "学习报告" },
];
const NAV_TEACHER = [
  { id: "t-overview", icon: "layout-dashboard", label: "班级总览" },
  { id: "t-students", icon: "users", label: "学生管理" },
  { id: "t-documents", icon: "files", label: "课件管理" },
];
const CRUMBS = {
  learning: ["学生端", "我的学习"], records: ["学生端", "收藏与学习记录"], mistakes: ["错题本"], report: ["学习报告"],
  dashboard: ["学习概览"], chat: ["学习对话"], topics: ["知识图谱"], quiz: ["智能测评"], about: ["关于本系统"],
  reader: ["知识图谱", "教材阅读"],
  "t-overview": ["教师端", "班级总览"], "t-students": ["教师端", "学生管理"], "t-student": ["教师端", "学生明细"],
  "t-documents": ["教师端", "课件管理"],
};
const VIEWS = {
  learning: () => {}, records: () => {}, mistakes: renderMistakesPage,
  report: () => {
    view().innerHTML = pageHead("STUDENT · REPORT", "学习报告", "基于你的学习轨迹与测评结果生成阶段报告。") +
      `<section class="panel"><div class="panel-body"><button class="da-btn primary" id="report-generate"><i data-lucide="file-text"></i> 生成学习报告</button></div></section>`;
    icons(); $("#report-generate").onclick = openReport;
  },
  dashboard: renderDashboard, chat: renderChat, topics: renderTopics, quiz: renderQuiz, about: renderAbout,
  reader: renderReader,
  "t-overview": renderTeacherOverview, "t-students": renderTeacherStudents, "t-student": renderTeacherStudent,
  "t-documents": renderTeacherDocuments,
};
const isTeacher = () => state.identity && state.identity.role === "teacher";

const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const HOVER = !(window.matchMedia && window.matchMedia("(hover: none)").matches);

/* ---------------- 工具 ---------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const view = () => $("#view");
function icons(root) { if (window.lucide) { lucide.createIcons(); (root || document).querySelectorAll("svg.lucide").forEach(s => s.setAttribute("aria-hidden", "true")); } }
function announce(msg) { const s = $("#sr-status"); if (s) s.textContent = msg; }

function renderMath(node) {
  if (window.renderMathInElement) {
    try {
      renderMathInElement(node, {
        delimiters: [
          { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
      });
    } catch (e) {}
  }
}

function md(text) {
  let html = window.marked ? marked.parse(text || "", { breaks: true, gfm: true }) : escapeHtml(text || "").replace(/\n/g, "<br>");
  if (window.DOMPurify) html = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
  return html;
}
function escapeHtml(s) { return (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 160); }, 2400);
}

function authHeaders() {
  const h = {}, id = state.identity;
  if (id && id.role === "student" && id.sid) h["X-Student-Id"] = id.sid;
  if (id && id.role === "student" && id.token) h.Authorization = "Bearer " + id.token;
  if (id && id.role === "teacher") h["X-Teacher-Pass"] = id.pass || "";
  return h;
}
function withViewSid(path) {
  if (isTeacher() && state.viewSid) path += (path.indexOf("?") >= 0 ? "&" : "?") + "student_id=" + encodeURIComponent(state.viewSid);
  return path;
}
async function api(path, opts = {}) {
  opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
  const r = await fetch(withViewSid(path), opts);
  if (!r.ok) {
    let detail = "请求失败";
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}
function friendlyError(e) {
  const m = (e && e.message) || "";
  if (/Failed to fetch|NetworkError|load failed/i.test(m)) return "网络连接异常,请稍后重试";
  return m || "出现未知错误";
}

function countUp(el, target, dur = 360) {
  const dec = !Number.isInteger(target);
  const fmt = (v) => dec ? v.toFixed(1) : String(Math.round(v));
  if (reduceMotion || isNaN(target)) { el.textContent = fmt(target); return; }
  const start = performance.now(), ease = (t) => 1 - Math.pow(1 - t, 3);
  (function step(now) {
    const p = Math.min(1, (now - start) / dur), v = target * ease(p);
    el.textContent = fmt(v);
    if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
  })(performance.now());
}

/* ---------------- 框架 / 路由 ---------------- */
function navItemHtml(it, active) {
  return `<button class="nav-item ${active ? "is-active" : ""}" data-nav="${it.id}" ${active ? 'aria-current="page"' : ""}>
    <i data-lucide="${it.icon}"></i><span>${it.label}</span></button>`;
}
function renderShell() {
  const teacher = isTeacher();
  const nav = teacher ? NAV_TEACHER : NAV_STUDENT;
  const bottom = teacher
    ? [{ id: "logout", icon: "log-out", label: "退出登录" }]
    : [{ id: "about", icon: "info", label: "关于本系统" }, { id: "logout", icon: "log-out", label: "切换身份" }];
  $("#nav").innerHTML = nav.map(it => navItemHtml(it, state.view === it.id)).join("");
  $("#nav-bottom").innerHTML = bottom.map(it => navItemHtml(it, false)).join("");
  document.querySelectorAll("[data-nav]").forEach(a => a.onclick = () => {
    closeNav();
    if (a.dataset.nav === "logout") return logout();
    navigate(a.dataset.nav);
  });
  const crumbs = CRUMBS[state.view] || [state.view];
  $("#crumbs").innerHTML = crumbs.map((c, i) =>
    `<span class="${i === crumbs.length - 1 ? "crumb-cur" : "crumb"}">${escapeHtml(c)}</span>` +
    (i < crumbs.length - 1 ? `<span class="crumb-sep">/</span>` : "")).join("");
  icons();
}

function renderView(v) {
  v = allowedView(v);
  if (!entryRole && ['learning', 'records'].includes(v)) { location.href = '/student/#' + v; return; }
  state.view = v;
  if (state.documentPreviewUrl) { URL.revokeObjectURL(state.documentPreviewUrl); state.documentPreviewUrl = null; }
  if (v !== "t-student") { state.viewSid = null; state.readonly = false; }
  renderShell();
  window.dispatchEvent(new CustomEvent('zx-view', { detail: { view: v, identity: state.identity, target: state.learningTarget } }));
  const m = view();
  m.onscroll = null;   // 清除上一视图(如阅读页)挂在 #view 上的滚动监听,避免泄漏
  m.className = "main" + (v === "chat" ? " flush" : "");
  document.title = `${(CRUMBS[v] || [v]).slice(-1)[0]} · 智学`;
  const ft = $("#app-footer"); if (ft) ft.classList.toggle("hide", v === "chat");
  (VIEWS[v] || renderDashboard)();
  // 进场动画
  m.classList.remove("enter"); void m.offsetWidth; m.classList.add("enter");
  // 焦点移到主区(便于键盘/读屏)
  if (v !== "chat") { const h = m.querySelector(".page-title"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); } }
}

function navigate(v, opts = {}) {
  state.learningTarget = opts.material ? { id: opts.material, anchor: opts.anchor } : null;
  if (v === "quiz" && opts.topic) state.quizTopic = opts.topic;
  if (v === "chat" && opts.topic) state.chatTopic = opts.topic;
  if (v === "reader" && opts.topic) state.readerTopic = opts.topic;
  if (!opts.fromPop) {
    try { history.pushState({ view: v }, "", "#" + v); } catch (e) {}
  }
  renderView(v);
}

function pageHead(eyebrow, title, lede, meta) {
  return `<div class="page-head">
    <div class="ph-left">
      <div class="page-bar"></div>
      <div class="eyebrow">${eyebrow}</div>
      <h1 class="page-title" tabindex="-1">${title}</h1>
      <p class="page-lede">${lede}</p>
    </div>
    ${meta ? `<div class="page-head-meta">${meta}</div>` : ""}
  </div><div class="tech-rule"></div>`;
}
function errorState(container, msg, onRetry, raw) {
  container.innerHTML = `<div class="empty">
    <div class="empty-mark"><i data-lucide="alert-triangle"></i></div>
    <h3>载入失败</h3><p>${escapeHtml(msg)}</p>
    <button class="da-btn secondary" id="retry-btn"><i data-lucide="rotate-ccw"></i> 重试</button>
    ${raw ? `<span class="coord">${escapeHtml(raw)}</span>` : ""}
  </div>`;
  const b = $("#retry-btn", container); if (b) b.onclick = onRetry;
  icons(container);
}
function renderMistakesPage() {
  view().innerHTML = pageHead("STUDENT · REVIEW", "错题本", "根据测评记录复习错题。") +
    `<section id="quiz-area"><div class="loading-row"><span class="spin"></span> 载入错题…</div></section>`;
  renderMistakes();
}

/* ---------------- 学习概览(产品首页) ---------------- */
function skeletonDashboard() {
  return `<div class="dash-hero"><div class="sk sk-line" style="width:90px;height:10px"></div><div class="sk" style="height:32px;width:280px;margin:12px 0 8px"></div><div class="sk sk-line" style="width:55%"></div></div>
    <div class="resume-card" style="box-shadow:none"><div class="rc-l" style="flex:1"><div class="sk sk-line" style="width:150px"></div><div class="sk" style="height:24px;width:46%;margin:12px 0"></div><div class="sk sk-line" style="width:68%"></div></div></div>
    <div class="metrics">${Array(4).fill(0).map(() => `<div class="metric"><div class="sk sk-line" style="width:50%"></div><div class="sk" style="height:28px;width:60%;margin:14px 0 8px"></div><div class="sk sk-line" style="width:40%"></div></div>`).join("")}</div>`;
}

function learnStreak(events) {
  const days = new Set((events || []).map(e => new Date(e.created_at * 1000).toDateString()));
  let s = 0, d = new Date();
  while (days.has(d.toDateString())) { s++; d.setDate(d.getDate() - 1); }
  if (s === 0) { const y = new Date(); y.setDate(y.getDate() - 1); while (days.has(y.toDateString())) { s++; y.setDate(y.getDate() - 1); } }
  return s;
}

async function renderDashboard() {
  view().innerHTML = skeletonDashboard(); icons();
  let p, path, asg;
  try { [p, path, asg] = await Promise.all([api("/api/profile"), api("/api/path").catch(() => ({ recommendation: [] })), api("/api/assignments").catch(() => ({ assignments: [], pending: 0 }))]); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderDashboard); return; }
  state.profile = p; setOrg(p.student);

  const s = p.summary, name = p.student.name;
  const hr = new Date().getHours();
  const greet = hr < 6 ? "凌晨好" : hr < 11 ? "早上好" : hr < 13 ? "中午好" : hr < 18 ? "下午好" : "晚上好";
  const coord = `${p.student.major || "AI"} · ${p.student.grade || ""} · ${state.health && state.health.index_ready ? "IDX·READY" : "IDX·…"}`;
  const fresh = s.topics_studied === 0 && (!p.events || !p.events.length);

  if (fresh) {
    view().innerHTML = `
      <header class="dash-hero"><div class="hero-row"><div class="ph-left">
        <div class="page-bar"></div><div class="eyebrow">DASHBOARD · 开始使用</div>
        <h1 class="page-title dash-greet">欢迎来到智学,${escapeHtml(name)}</h1>
        <p class="dash-sub">系统会随你的学习实时刻画掌握度,并据此调整辅导与命题。先从下面任一步开始。</p>
      </div><span class="coord dash-coord">${escapeHtml(coord)}</span></div></header>
      <div class="tech-rule"></div>
      <div class="onboard"><div class="eyebrow">开始使用</div><h3>三步开启你的个性化学习</h3>
        <div class="onboard-steps">
          <div class="onboard-step"><span class="sn">01</span><span class="st">在知识图谱挑一个知识点,看清学习路线</span><button class="da-btn secondary sm" data-go="topics"><i data-lucide="book-open"></i> 去知识图谱</button></div>
          <div class="onboard-step"><span class="sn">02</span><span class="st">直接向导师提问,获得个性化讲解与来源</span><button class="da-btn secondary sm" data-go="chat"><i data-lucide="messages-square"></i> 去对话</button></div>
          <div class="onboard-step"><span class="sn">03</span><span class="st">做一次自适应测评,生成你的学情画像</span><button class="da-btn primary sm" data-go="quiz"><i data-lucide="clipboard-check"></i> 去测评</button></div>
        </div>
      </div>`;
    view().querySelectorAll("[data-go]").forEach(b => b.onclick = () => navigate(b.dataset.go));
    icons(); return;
  }

  const rec = (path.recommendation && path.recommendation[0]) || (p.weak_topics && p.weak_topics[0]) || null;
  const streak = learnStreak(p.events);
  const today = (p.events || []).filter(e => new Date(e.created_at * 1000).toDateString() === new Date().toDateString()).length;

  const recCard = rec ? `<button class="resume-card bracket" data-topic="${rec.id}">
      <div class="rc-l"><div class="eyebrow">CONTINUE · 为你推荐的下一步</div>
        <div class="rc-title">${escapeHtml(rec.title)}</div>
        <div class="rc-reason">${escapeHtml(rec.reason || "继续巩固你的薄弱知识点")}</div></div>
      <span class="rc-go"><i data-lucide="arrow-right"></i> 继续学习</span></button>` : "";

  const metrics = `<div class="metrics">
    ${metric("平均掌握度", s.avg_mastery, "分", "覆盖已学知识点", "WEIGHTED")}
    ${metric("已学知识点", s.topics_studied, "/ " + s.topics_total, "知识图谱进度", "PROGRESS")}
    ${metric("累计提问", s.questions_asked, "", "与导师对话", "TOTAL")}
    ${metric("完成测评", s.quizzes_done, "次", "评价闭环", "TOTAL")}
  </div>`;

  const strip = `<div class="today-strip">
    <div class="ts-item"><i data-lucide="flame" class="${streak > 0 ? "lit" : ""}"></i><div class="ts-text"><div class="ts-n">${streak}<span class="u">天</span></div><div class="ts-k">连续学习</div></div></div>
    <div class="ts-item"><i data-lucide="activity"></i><div class="ts-text"><div class="ts-n">${today}</div><div class="ts-k">今日学习活动</div></div></div>
    <div class="ts-item"><i data-lucide="git-fork"></i><div class="ts-text"><div class="ts-n">${s.topics_studied}<span class="u">/ ${s.topics_total}</span></div><div class="ts-k">知识图谱进度</div></div></div>
  </div>`;

  const weak = (p.weak_topics && p.weak_topics.length) ?
    `<div class="panel accent"><div class="panel-head"><h3 class="panel-title">需重点巩固</h3><span class="coord">PRIORITY</span></div>
      <div class="panel-body" id="weak-body">${p.weak_topics.map(t => masteryRow(t, true)).join("")}</div></div>` :
    `<div class="panel"><div class="panel-head"><h3 class="panel-title">需重点巩固</h3></div><div class="panel-body"><p class="page-lede" style="font-size:13px;padding:6px 0">暂无明显薄弱知识点,继续保持。</p></div></div>`;

  const feed = `<div class="panel"><div class="panel-head"><h3 class="panel-title">最近学习活动</h3><span class="coord">LOG</span></div>
    <div class="panel-body" id="feed-body">${renderFeed(p.events)}</div></div>`;

  const snap = `<div class="panel"><div class="panel-head"><h3 class="panel-title">学情快照</h3><span class="coord">SNAPSHOT</span></div>
    <div class="snap"><div class="ring2" id="snap-ring"><div class="inner"><div class="v">${s.avg_mastery}</div><div class="l">平均掌握</div></div></div>
      <div class="snap-stat">已学 <b>${s.topics_studied}</b> / ${s.topics_total} 个知识点<br>累计提问 <b>${s.questions_asked}</b> · 测评 <b>${s.quizzes_done}</b> 次</div>
      <div class="snap-cta"><button class="da-btn secondary sm" data-go="topics"><i data-lucide="book-open"></i> 查看完整知识图谱</button>
        <button class="da-btn secondary sm" id="gen-report" style="margin-top:8px"><i data-lucide="file-text"></i> 生成学习报告</button></div></div></div>`;

  const pend = (asg.assignments || []).filter(a => a.status === "pending");
  const todo = pend.length ? `<div class="panel accent"><div class="panel-head"><h3 class="panel-title">待办作业</h3><span class="coord">${pend.length} 项</span></div>
    <div class="panel-body">${pend.map(a => `<div class="todo-row"><i data-lucide="clipboard-list"></i><div style="flex:1;min-width:0"><div class="ft">《${escapeHtml(a.topic_title)}》测评 · ${a.n} 题</div><div class="fm">教师布置 · ${timeago(a.created_at)}</div></div><button class="da-btn primary sm" data-do="${a.topic_id}"><i data-lucide="arrow-right"></i> 去完成</button></div>`).join("")}</div></div>` : "";

  view().innerHTML = `
    <header class="dash-hero"><div class="hero-row"><div class="ph-left">
      <div class="page-bar"></div><div class="eyebrow">DASHBOARD · 学习概览</div>
      <h1 class="page-title dash-greet">${greet},${escapeHtml(name)}</h1>
      <p class="dash-sub">${rec ? "继续推进你的学习路线,下面是为你定制的下一步。" : "保持节奏,巩固薄弱、拓展掌握。"}</p>
    </div><span class="coord dash-coord">${escapeHtml(coord)}</span></div></header>
    <div class="tech-rule"></div>
    ${stateBanner(p.state)}
    ${recCard}${todo}${strip}${metrics}
    <div class="section-head"><h2 class="section-h2">学情画像</h2><span class="coord">PROFILE</span></div>
    <div class="dash-grid"><div class="dash-main">${weak}${feed}</div><aside class="dash-side">${stateCard(p.state)}${snap}</aside></div>`;

  view().querySelectorAll("[data-go]").forEach(b => b.onclick = () => navigate(b.dataset.go));
  view().querySelectorAll("[data-do]").forEach(b => b.onclick = () => navigate("quiz", { topic: b.dataset.do }));
  const repBtn = $("#gen-report"); if (repBtn) repBtn.onclick = openReport;
  const rcCard = view().querySelector(".resume-card"); if (rcCard) rcCard.onclick = () => navigate("chat", { topic: rcCard.dataset.topic });
  view().querySelectorAll(".mrow.clickable").forEach(r => r.onclick = () => navigate("quiz", { topic: r.dataset.topic }));
  bindFeed();
  view().querySelectorAll("[data-count]").forEach(el => countUp(el, parseFloat(el.dataset.count)));
  requestAnimationFrame(() => {
    view().querySelectorAll(".mbar > span[data-w]").forEach(x => x.style.width = x.dataset.w + "%");
    const r = $("#snap-ring"); if (r) r.style.setProperty("--val", s.avg_mastery);
  });
  icons();
}
function setOrg(student) {
  $("#org .org-name").textContent = `${student.name} · ${student.major}`;
  $("#org .org-plan").textContent = student.grade;
  const dot = $("#org .org-dot"); if (dot && student.name) dot.textContent = student.name.slice(0, 1);
  const av = $("#avatar"); if (av && student.name) av.textContent = student.name.slice(0, 1);
}
function metric(label, value, unit, note, cap) {
  return `<div class="metric">
    ${cap ? `<span class="coord metric-cap">${cap}</span>` : ""}
    <div class="metric-label">${label}</div>
    <div class="metric-value"><span class="num" data-count="${value}">0</span>${unit ? `<span class="unit">${unit}</span>` : ""}</div>
    <div class="metric-note">${note || ""}</div>
  </div>`;
}
function masteryRow(t, clickable) {
  const v = t.mastery || 0;
  const weak = t.attempts > 0 && v < 60;
  const cls = v === 0 ? "zero" : (weak ? "weak" : "");
  const tag = clickable ? "button" : "div";
  return `<${tag} class="mrow ${clickable ? "clickable" : ""}" ${clickable ? `data-topic="${t.id}"` : ""}>
    <span class="mname">${t.title}</span>
    <span class="mbar ${cls}"><span data-w="${v}"></span></span>
    <span class="mval ${weak ? "weak" : ""}">${v ? v.toFixed(0) : "—"}</span>
    ${clickable ? `<span class="mrow-go"><i data-lucide="chevron-right"></i></span>` : ""}
  </${tag}>`;
}
function renderFeed(events) {
  if (!events || !events.length) return `<div class="empty" style="padding:30px 12px"><div class="empty-mark"><i data-lucide="clock"></i></div><h3 style="font-size:18px">还没有学习活动</h3><p>完成一次对话或测评后,这里会按时间记录你的学习轨迹。</p></div>`;
  const ico = { chat: "messages-square", quiz_start: "file-pen", quiz_done: "clipboard-check" };
  return events.map(e => {
    let t = "", m = "", badge = "";
    if (e.kind === "chat") { t = `就「${(e.detail.topics || []).join("、") || "学习问题"}」咨询了导师`; m = "对话辅导"; }
    else if (e.kind === "quiz_start") { t = `开始《${e.detail.topic}》测评`; m = "智能测评"; }
    else if (e.kind === "quiz_done") {
      const sc = e.detail.score; t = `在《${e.detail.topic}》测评中得了 ${sc} 分`; m = "评价反馈";
      badge = sc >= 75 ? `<span class="fbadge ok">已掌握</span>` : (sc < 60 ? `<span class="fbadge weak">待巩固</span>` : `<span class="fbadge">${sc}</span>`);
    } else { t = e.kind; }
    const qid = (e.kind === "quiz_done") ? (e.detail.quiz_id || "") : "";
    const fm = `${m} · ${timeago(e.created_at)}${qid ? " · 点击查看" : ""}`;
    return `<button class="feed-row" data-kind="${e.kind}"${qid ? ` data-review="${qid}"` : ""}><i data-lucide="${ico[e.kind] || "circle"}"></i><div style="flex:1;min-width:0"><div class="ft">${escapeHtml(t)}</div><div class="fm">${fm}</div></div>${badge}</button>`;
  }).join("");
}
function bindFeed() {
  document.querySelectorAll(".feed-row").forEach(b => {
    if (b.dataset.review) { b.onclick = () => openReview(b.dataset.review); return; }  // 评价反馈→打开回顾(含学习状态)
    if (isTeacher()) { b.style.cursor = "default"; return; }   // 教师只读:非回顾行不跳转
    const k = b.dataset.kind;
    b.onclick = () => navigate(k === "chat" ? "chat" : (k && k.indexOf("quiz") === 0 ? "quiz" : "dashboard"));
  });
}
function timeago(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "刚刚";
  if (d < 3600) return Math.floor(d / 60) + " 分钟前";
  if (d < 86400) return Math.floor(d / 3600) + " 小时前";
  return Math.floor(d / 86400) + " 天前";
}

/* ---------------- 学习状态评价(答题快慢 + 表情识别预留) ---------------- */
const STATE_META = {
  good: { label: "专注良好", cls: "good", icon: "smile" },
  normal: { label: "状态一般", cls: "normal", icon: "meh" },
  poor: { label: "状态欠佳", cls: "poor", icon: "frown" },
  unknown: { label: "数据不足", cls: "unknown", icon: "help-circle" },
};
function stateBadge(st) {
  const m = STATE_META[(st && st.state) || "unknown"] || STATE_META.unknown;
  return `<span class="state-badge ${m.cls}"><i data-lucide="${m.icon}"></i>${escapeHtml((st && st.label) || m.label)}</span>`;
}
// 学生端提醒条:状态欠佳时高亮提醒(“现在状态不好”),其它状态低调展示。优先展示大模型解释。
function stateBanner(st, title) {
  if (!st || st.state === "unknown") return "";
  const m = STATE_META[st.state] || STATE_META.normal;
  const spq = st.metrics && st.metrics.avg_sec_per_q ? ` · 平均每题 ${st.metrics.avg_sec_per_q}s` : "";
  return `<div class="state-banner ${m.cls}">
    <i data-lucide="${st.alert ? "alert-triangle" : m.icon}"></i>
    <div class="sb-text"><div class="sb-title">${title || "学习状态"}:${escapeHtml(st.label)}${spq}</div>
      <div class="sb-reason">${escapeHtml(st.summary || st.reason || "")}</div></div></div>`;
}
// 学习状态面板(含预留的表情识别模块占位)
function stateCard(st) {
  const mt = (st && st.metrics) || {};
  const detail = mt.samples ? `<div class="snap-stat">平均每题 <b>${mt.avg_sec_per_q ?? "—"}</b> 秒 · 节奏 <b>${mt.pace_ratio}×</b><br>近 <b>${mt.samples}</b> 次测评 · 正确率 <b>${mt.avg_score}</b></div>`
    : `<div class="snap-stat">完成带计时的测评后,这里会根据答题快慢给出学习状态。</div>`;
  return `<div class="panel"><div class="panel-head"><h3 class="panel-title">学习状态</h3><span class="coord">STATE</span></div>
    <div class="panel-body">
      <div class="state-row">${stateBadge(st)}</div>
      <p class="state-reason">${escapeHtml((st && (st.summary || st.reason)) || "")}</p>
      ${detail}
      <div class="emotion-slot" id="emotion-slot"><i data-lucide="scan-face"></i><div class="es-text"><div class="es-t">表情识别</div><div class="es-d">模块预留 · 未启用</div></div></div>
    </div></div>`;
}

/* 表情识别(前端预留):接入摄像头后在此采集帧并 POST /api/emotion/frame。当前为占位,不启用。 */
async function captureEmotionFrame() {
  // TODO: 接入摄像头采集一帧(dataURL)后:
  // return api("/api/emotion/frame", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ frame }) });
  return { available: false };
}

/* ---------------- 学习对话 ---------------- */
const SUGGESTS = ["用一个例子解释梯度下降", "反向传播和梯度下降有什么区别?", "什么时候会过拟合,怎么缓解?", "Transformer 的注意力机制怎么工作?"];

async function renderChat() {
  const topicName = state.chatTopic ? topicTitle(state.chatTopic) : null;
  view().innerHTML = `
    <div class="chat">
      <div class="chat-head">
        <div class="t"><i data-lucide="bot"></i> 个性化学习导师${topicName ? ` · <b>${escapeHtml(topicName)}</b>` : ""}</div>
        <button class="da-btn ghost sm" id="clear-ctx">${topicName ? '<i data-lucide="x"></i> 退出该知识点' : '<i data-lucide="sliders-horizontal"></i> 已按学情自适应'}</button>
      </div>
      <div class="chat-scroll"><div class="chat-inner" id="chat-inner" role="log" aria-live="polite" aria-relevant="additions text"></div></div>
      <button class="da-btn secondary sm to-bottom hidden" id="to-bottom"><i data-lucide="arrow-down"></i> 回到底部</button>
      <div class="composer-wrap"><div class="composer-inner">
        <div class="suggest" id="suggest">${(topicName ? topicSuggests(topicName) : SUGGESTS).map(s => `<button class="chip">${escapeHtml(s)}</button>`).join("")}</div>
        <div class="composer">
          <textarea id="composer" rows="1" placeholder="向导师提问,例如:为什么需要激活函数?" aria-label="输入问题"></textarea>
          <button class="da-btn primary" id="send"><i data-lucide="send-horizontal"></i> 发送</button>
        </div>
        <div class="composer-hint">Enter 发送 · Shift+Enter 换行 · 回答基于知识库检索并标注来源</div>
      </div></div>
    </div>`;
  icons();

  if (!state.chatLoaded) {
    try { const h = await api("/api/history"); state.chat = h.messages.map(m => ({ role: m.role, content: m.content, citations: m.citations })); } catch (e) {}
    state.chatLoaded = true;
  }
  renderMessages();

  const ta = $("#composer");
  ta.oninput = () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; };
  ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  $("#send").onclick = () => { if (state.streaming) stopGen(); else send(); };
  bindSuggests();
  $("#clear-ctx").onclick = () => { state.chatTopic = null; renderChat(); };
  const sc = $(".chat-scroll");
  sc.onscroll = () => { const atBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 80; $("#to-bottom").classList.toggle("hidden", atBottom); };
  $("#to-bottom").onclick = () => { scrollChat(true); };
}
function topicSuggests(name) { return [`请由浅入深讲解《${name}》`, `给我一道《${name}》的例题`, `《${name}》最容易出错的点是什么?`, `《${name}》和相关知识点有什么联系?`]; }
function bindSuggests() { document.querySelectorAll("#suggest .chip").forEach(c => c.onclick = () => { const ta = $("#composer"); ta.value = c.textContent; send(); }); }
function topicTitle(id) { const t = (state.topics || []).find(x => x.id === id); return t ? t.title : id; }

function renderMessages() {
  const inner = $("#chat-inner");
  if (!inner) return;
  if (!state.chat.length) {
    inner.innerHTML = `<div class="empty" style="max-width:560px;margin:0 auto">
      <div class="empty-mark"><i data-lucide="sparkles"></i></div>
      <h3>开始你的个性化学习</h3>
      <p>我会根据你的掌握度调整讲解深浅,基于课程知识库作答并标注来源。试试下面的问题,或直接提问。</p>
      <div class="cap-row">
        <span class="cap"><i data-lucide="sliders-horizontal"></i> 按学情自适应</span>
        <span class="cap"><i data-lucide="book-marked"></i> 引用可溯源</span>
        <span class="cap"><i data-lucide="clipboard-check"></i> 测评成闭环</span>
      </div></div>`;
    icons(inner); toggleSuggest(true); return;
  }
  inner.innerHTML = state.chat.map((m, i) => msgHtml(m, i)).join("");
  inner.querySelectorAll(".bubble.md").forEach(b => renderMath(b));
  bindMsgActions();
  icons(inner);
  toggleSuggest(false);
  scrollChat(true);
}
function toggleSuggest(show) { const s = $("#suggest"); if (s) s.classList.toggle("hidden", !show); }

function msgHtml(m, idx) {
  const isUser = m.role === "user";
  const name = isUser ? "你" : "学习导师";
  let body;
  if (m.streaming && !m.content) body = `<div class="bubble"><div class="typing" aria-label="导师正在输入"><span></span><span></span><span></span></div></div>`;
  else body = `<div class="bubble md">${isUser ? escapeHtml(m.content) : md(m.content)}</div>`;
  let cites = "";
  if (!isUser && m.citations && m.citations.length) {
    cites = `<div class="cites"><span class="cite-head">参考来源</span>` +
      m.citations.map(c => `<button class="cite-chip go" data-topic="${c.topic_id}"><i data-lucide="book-marked"></i>${escapeHtml(c.title)}</button>`).join("") + `</div>`;
  }
  let follow = "";
  if (!isUser && !m.streaming && m.content && m.citations && m.citations.length) {
    const c0 = m.citations[0], qs = topicSuggests(c0.title).slice(0, 2);
    follow = `<div class="followups"><span class="cite-head">继续深入</span>` +
      qs.map(q => `<button class="fu-chip" data-fu="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join("") +
      `<button class="fu-chip quiz" data-fuquiz="${c0.topic_id}"><i data-lucide="clipboard-check"></i>就《${escapeHtml(c0.title)}》测一测</button></div>`;
  }
  let tools = "";
  if (!isUser && !m.streaming && m.content) {
    tools = `<div class="msg-tools">
      <button class="da-btn ghost" data-copy="${idx}"><i data-lucide="copy"></i> 复制</button>
      <button class="da-btn ghost" data-regen="${idx}"><i data-lucide="rotate-ccw"></i> 重答</button></div>`;
  }
  return `<div class="msg ${isUser ? "user" : "assistant"}" ${!isUser ? 'aria-busy="' + (m.streaming ? "true" : "false") + '"' : ""}>
    <div class="msg-avatar" aria-hidden="true">${isUser ? "你" : "智"}</div>
    <div class="msg-main"><div class="msg-name">${name}</div>${body}${cites}${follow}${tools}</div></div>`;
}
function bindMsgActions() {
  document.querySelectorAll(".cite-chip.go").forEach(c => c.onclick = () => {
    if (entryRole === 'student') {
      const citation = state.chat.flatMap(m => m.citations || []).find(item => item.topic_id === c.dataset.topic);
      const material = citation?.document_id ? 'course:' + citation.document_id + ':' + citation.version_id : 'topic:' + c.dataset.topic;
      navigate('learning', { material, anchor: citation?.page_number ? 'page-' + citation.page_number : undefined });
    } else { state.highlightTopic = c.dataset.topic; navigate("topics"); }
  });
  document.querySelectorAll("[data-fu]").forEach(b => b.onclick = () => { const ta = $("#composer"); if (ta) { ta.value = b.dataset.fu; send(); } });
  document.querySelectorAll("[data-fuquiz]").forEach(b => b.onclick = () => navigate("quiz", { topic: b.dataset.fuquiz }));
  document.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => {
    const m = state.chat[+b.dataset.copy]; if (m && navigator.clipboard) navigator.clipboard.writeText(m.content).then(() => toast("已复制到剪贴板"));
  });
  document.querySelectorAll("[data-regen]").forEach(b => b.onclick = () => {
    const i = +b.dataset.regen; const prev = state.chat[i - 1];
    if (prev && prev.role === "user" && !state.streaming) { state.chat = state.chat.slice(0, i - 1); renderMessages(); send(prev.content); }
  });
}

function scrollChat(force) {
  const sc = $(".chat-scroll"); if (!sc) return;
  const atBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 80;
  if (force || atBottom) { sc.scrollTop = sc.scrollHeight; $("#to-bottom").classList.add("hidden"); }
  else if (state.streaming) $("#to-bottom").classList.remove("hidden");
}

function setSendMode(mode) {
  const b = $("#send"); if (!b) return;
  if (mode === "stop") { b.classList.remove("primary"); b.classList.add("secondary"); b.innerHTML = '<i data-lucide="square"></i> 停止'; }
  else { b.classList.remove("secondary"); b.classList.add("primary"); b.innerHTML = '<i data-lucide="send-horizontal"></i> 发送'; }
  icons(b.parentElement);
}
function stopGen() { if (state.abort) state.abort.abort(); }

async function send(preset) {
  if (state.streaming) return;
  const ta = $("#composer");
  const text = (preset != null ? preset : (ta ? ta.value : "")).trim();
  if (!text) return;
  if (ta) { ta.value = ""; ta.style.height = "auto"; }
  state.chat.push({ role: "user", content: text });
  const asst = { role: "assistant", content: "", citations: [], streaming: true };
  state.chat.push(asst);
  renderMessages();
  announce("已发送,正在生成回答");
  state.streaming = true;
  setSendMode("stop");
  const ac = new AbortController(); state.abort = ac;

  try {
    const resp = await fetch("/api/chat", {
      method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify({ message: text, topic_id: state.chatTopic || null }), signal: ac.signal,
    });
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "", rafPending = false;
    const flush = () => {
      rafPending = false;
      const inner = $("#chat-inner"), last = inner && inner.lastElementChild;
      if (last) { const b = last.querySelector(".bubble"); if (b) { b.className = "bubble md"; b.innerHTML = md(asst.content) + '<span class="da-caret"></span>'; renderMath(b); } }
      scrollChat();
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const blk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = blk.split("\n").find(l => l.startsWith("data:"));
        if (!line) continue;
        let data; try { data = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
        if (data.type === "meta") asst.citations = data.citations || [];
        else if (data.type === "delta") { asst.content += data.text; if (!rafPending) { rafPending = true; requestAnimationFrame(flush); } }
        else if (data.type === "error") asst.content += "\n\n> 出错:" + data.message;
        else if (data.type === "done") asst.streaming = false;
      }
    }
  } catch (e) {
    if (e.name === "AbortError") { if (asst.content) asst.content += "\n\n*(已停止生成)*"; else asst.content = "*(已停止生成)*"; }
    else asst.content = (asst.content || "") + `\n\n> 连接出错:${friendlyError(e)}`;
  } finally {
    asst.streaming = false; state.streaming = false; state.abort = null;
    setSendMode("send");
    finalizeAssistant(asst);
    announce("回答已完成");
  }
}
function finalizeAssistant(asst) {
  const inner = $("#chat-inner"), last = inner && inner.lastElementChild;
  if (!last) { renderMessages(); return; }
  const main = last.querySelector(".msg-main");
  last.setAttribute("aria-busy", "false");
  const idx = state.chat.length - 1;
  // 重建该条助手消息的主体(去光标、加引用与操作)
  const tmp = document.createElement("div");
  tmp.innerHTML = msgHtml(asst, idx);
  main.innerHTML = tmp.querySelector(".msg-main").innerHTML;
  main.querySelectorAll(".bubble.md").forEach(b => renderMath(b));
  bindMsgActions(); icons(main); scrollChat();
}

/* ---------------- 知识图谱 ---------------- */
const STATUS_LABEL = { mastered: "已掌握", learning: "学习中", weak: "待巩固", available: "可学习", locked: "待解锁" };
function statusLabel(s) { return STATUS_LABEL[s] || "未学"; }

async function renderTopics() {
  if (!state.kgView) state.kgView = "graph";
  view().innerHTML = pageHead("KNOWLEDGE MAP · 人工智能", "知识图谱",
    "按前置依赖组织的知识点关系图。横向为学习顺序,连线表示依赖;点击节点查看详情、问导师或测一测。") +
    `<div class="loading-row"><span class="spin"></span> 正在载入知识图谱…</div>`;
  icons();
  try { state.graph = await api("/api/graph"); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderTopics); return; }
  state.topics = state.graph.nodes.map(n => ({ id: n.id, title: n.title, title_en: n.title_en, difficulty: n.difficulty, mastery: n.mastery, attempts: n.attempts }));
  renderKG();
  if (state.highlightTopic) { openTopicDrawer(state.highlightTopic); state.highlightTopic = null; }
}

function renderKG() {
  const g = state.graph;
  const legend = ["mastered", "learning", "weak", "available", "locked"]
    .map(s => `<span class="kg-leg"><span class="d ${s}"></span>${statusLabel(s)}</span>`).join("");
  const rec = (g.recommendation && g.recommendation.length) ? `<div class="kg-rec">
      <span class="lbl">建议下一步</span>
      ${g.recommendation.map((r, i) => `<button class="rec-chip" data-rec="${r.id}"><span class="seq">${i + 1}</span>${escapeHtml(r.title)}<span class="coord">${escapeHtml(r.reason)}</span></button>`).join("")}
    </div>` : "";
  const toolbar = `<div class="kg-toolbar">
      <div class="kg-legend">${legend}</div>
      <div class="kg-toggle">
        <button data-view="graph" class="${state.kgView === "graph" ? "on" : ""}"><i data-lucide="route"></i> 路线图</button>
        <button data-view="list" class="${state.kgView === "list" ? "on" : ""}"><i data-lucide="layout-grid"></i> 列表</button>
      </div>
    </div>`;
  const bodyHtml = state.kgView === "graph"
    ? `<div class="rm-hero" id="rm-hero"></div><div class="kg-hint"><i data-lucide="info"></i> 纵向为学习顺序(上→下),分阶段推进;悬停卡片高亮其前置与后继,点击查看详情。</div><div class="roadmap" id="roadmap"></div>`
    : `<div class="grid3" id="kg-list"></div>`;
  view().innerHTML = pageHead("KNOWLEDGE MAP · 人工智能", "知识图谱",
    "按学习阶段组织的知识点路线图。自上而下循序渐进,卡片颜色表示掌握度;点击查看详情、问导师或测一测。") +
    rec + toolbar + bodyHtml;
  view().querySelectorAll("[data-view]").forEach(b => b.onclick = () => { state.kgView = b.dataset.view; renderKG(); });
  view().querySelectorAll("[data-rec]").forEach(c => c.onclick = () => openTopicDrawer(c.dataset.rec));
  if (state.kgView === "graph") buildRoadmap(g); else buildListGrid(g);
  icons();
}

const RM_ICON = {
  "ai-ml-overview": "brain-circuit", "supervised-unsupervised": "split", "linear-regression": "trending-up",
  "logistic-classification": "sigma", "loss-gradient-descent": "move-down-right", "backpropagation": "iteration-ccw",
  "neural-networks": "network", "overfitting-regularization": "shield-half", "model-evaluation": "target",
  "bias-variance-cv": "scale", "cnn": "scan", "rnn-lstm": "repeat", "attention-transformer": "focus",
  "embeddings": "vector-square", "llm-pretrain-finetune-rag": "bot", "reinforcement-learning": "gamepad-2",
};
const RM_ST_ICON = { mastered: "check", learning: "loader", weak: "alert-triangle", available: "circle-dot", locked: "lock" };
const RM_DIFF = { "入门": 1, "核心": 2, "进阶": 3 };

function buildRoadmap(g) {
  const recSeq = {}; (g.recommendation || []).forEach((r, i) => recSeq[r.id] = i + 1);
  const byCat = {}; g.nodes.forEach(n => { (byCat[n.category] = byCat[n.category] || []).push(n); });
  const prereqMap = {}; g.nodes.forEach(n => prereqMap[n.id] = n.prereqs || []);
  const leadMap = {}; g.edges.forEach(e => { (leadMap[e.source] = leadMap[e.source] || []).push(e.target); });

  // 总览英雄区
  const total = g.nodes.length;
  const masteredAll = g.nodes.filter(n => n.status === "mastered").length;
  const avg = total ? Math.round(g.nodes.reduce((s, n) => s + (n.mastery || 0), 0) / total) : 0;
  let curStage = g.categories[g.categories.length - 1] || "—";
  for (const cat of g.categories) { const ns = byCat[cat] || []; if (!(ns.length && ns.every(n => n.status === "mastered"))) { curStage = cat; break; } }
  const curIdx = Math.max(0, g.categories.indexOf(curStage));
  let streak = 0; for (const cat of g.categories) { const ns = byCat[cat] || []; if (ns.length && ns.every(n => n.status === "mastered")) streak++; else break; }
  const hero = $("#rm-hero");
  if (hero) {
    hero.innerHTML = `<div class="ring" id="rm-ring"><div class="inner"><div class="v">${avg}</div><div class="l">平均掌握</div></div></div>
      <div class="stats">
        <div class="rm-cell"><div class="n">${masteredAll}<span class="u">/ ${total}</span></div><div class="k">已掌握知识点</div></div>
        <div class="rm-cell"><div class="n">${curIdx + 1}<span class="u">/ ${g.categories.length}</span></div><div class="k cur">当前阶段 · ${escapeHtml(curStage)}</div></div>
        <div class="rm-cell"><div class="n"><i data-lucide="flame" class="${streak > 0 ? "lit" : ""}"></i>${streak}</div><div class="k">连续通关阶段</div></div>
      </div>`;
    requestAnimationFrame(() => { const r = $("#rm-ring"); if (r) r.style.setProperty("--val", avg); });
  }

  const html = g.categories.map((cat, ci) => {
    const nodes = (byCat[cat] || []).slice().sort((a, b) => a.level - b.level || a.title.localeCompare(b.title));
    const mastered = nodes.filter(n => n.status === "mastered").length;
    const started = nodes.some(n => n.attempts > 0);
    const done = nodes.length && mastered === nodes.length;
    const pct = nodes.length ? Math.round(mastered / nodes.length * 100) : 0;
    const mState = done ? "done" : (started ? "active" : "todo");
    const cards = nodes.map(n => {
      const v = n.mastery || 0, seq = recSeq[n.id];
      const locked = n.status === "locked", available = n.status === "available";
      const lv = RM_DIFF[n.difficulty] || 1;
      const diff = locked ? "" : `<span class="rm-diff" title="难度 · ${n.difficulty}" aria-label="难度 ${n.difficulty}">${[1, 2, 3].map(i => `<i class="${i <= lv ? "on" : ""}"></i>`).join("")}</span>`;
      const cc = n.core_concepts || [], shown = cc.slice(0, 2), more = cc.length - shown.length;
      const chips = locked ? "" : `<div class="rm-chips">${shown.map(c => `<span class="rm-chip">${escapeHtml(c)}</span>`).join("")}${more > 0 ? `<span class="rm-chip more">+${more}</span>` : ""}</div>`;
      let foot;
      if (locked) foot = `<div class="rm-foot lock"><i data-lucide="lock"></i><span>需先掌握 ${(prereqMap[n.id] || []).length} 个前置</span></div>`;
      else if (available) foot = `<div class="rm-foot start"><i data-lucide="arrow-right"></i><span>可开始学习</span></div>`;
      else { const bc = (n.status === "mastered" ? "ink" : "") + (v === 0 ? " zero" : ""); foot = `<div class="rm-foot"><span class="rm-foot-l">MASTERY</span><span class="mbar ${bc}"><span data-w="${v}"></span></span><span class="v">${v ? v.toFixed(0) : "—"}</span></div>`; }
      const cardCls = "rm-card" + (seq === 1 ? " is-next" : "") + (seq > 1 ? " rec" : "");
      return `<button class="${cardCls}" data-status="${n.status}" data-id="${n.id}" aria-label="${escapeHtml(n.title)},${statusLabel(n.status)}">
        ${seq ? `<span class="rm-seq">${seq}</span>` : ""}
        <div class="rm-head"><span class="rm-ico"><i data-lucide="${RM_ICON[n.id] || "circle-dot"}"></i></span><span class="rm-badge"><i data-lucide="${RM_ST_ICON[n.status] || "circle"}"></i>${statusLabel(n.status)}</span>${diff}</div>
        <div class="rm-title"><div class="rm-name">${escapeHtml(n.title)}</div><div class="rm-en">${escapeHtml(n.title_en || "")}</div></div>
        ${chips}
        ${foot}
      </button>`;
    }).join("");
    const markerHtml = done ? `<i data-lucide="check"></i>` : `${ci + 1}`;
    return `<div class="stage">
      <div class="stage-rail"><div class="stage-marker ${mState}">${markerHtml}</div></div>
      <div class="stage-body">
        <div class="eyebrow stage-eyebrow">STAGE ${String(ci + 1).padStart(2, "0")}</div>
        <div class="stage-h"><span class="stage-name">${escapeHtml(cat)}${done ? `<i data-lucide="check" class="stage-seal"></i>` : ""}</span><span class="stage-meta">${nodes.length} 个知识点</span></div>
        <div class="stage-prog"><span class="mbar"><span data-w="${pct}"></span></span><span class="pct">已掌握 ${mastered}/${nodes.length} · ${pct}%</span></div>
        <div class="stage-cards">${cards}</div>
      </div>
    </div>`;
  }).join("");

  const rm = $("#roadmap"); rm.innerHTML = html;
  requestAnimationFrame(() => rm.querySelectorAll(".mbar > span[data-w]").forEach(s => s.style.width = s.dataset.w + "%"));
  rm.querySelectorAll(".rm-card").forEach(card => {
    const id = card.dataset.id;
    const rel = new Set([...(prereqMap[id] || []), ...(leadMap[id] || [])]);
    if (HOVER) {
      card.addEventListener("mouseenter", () => rel.forEach(x => { const el = rm.querySelector(`.rm-card[data-id="${x}"]`); if (el) el.classList.add("dep"); }));
      card.addEventListener("mouseleave", () => rm.querySelectorAll(".rm-card.dep").forEach(e => e.classList.remove("dep")));
    }
    card.addEventListener("click", () => openTopicDrawer(id));
  });
}

function buildListGrid(g) {
  const el = $("#kg-list");
  el.innerHTML = g.nodes.map(n => {
    const v = n.mastery || 0, cls = v === 0 ? "zero" : "";
    const facet = (n.status === "weak" || n.status === "available" || n.status === "locked") ? `<div class="topic-facet"></div>` : "";
    return `<button class="topic-card" data-id="${n.id}">
      ${facet}
      <div><span class="badge diff"><span class="dot"></span>${n.difficulty} · ${escapeHtml(n.category)}</span></div>
      <div><div class="topic-name">${escapeHtml(n.title)}</div><div class="topic-en">${escapeHtml(n.title_en || "")}</div></div>
      <div class="topic-tags">${(n.core_concepts || []).slice(0, 3).map(c => `<span class="badge tag">${escapeHtml(c)}</span>`).join("")}</div>
      <div class="topic-foot"><div class="mbar ${cls}" style="flex:1"><span data-w="${v}"></span></div><div class="mval">${v ? v.toFixed(0) : statusLabel(n.status)}</div></div>
    </button>`;
  }).join("");
  requestAnimationFrame(() => el.querySelectorAll(".mbar > span[data-w]").forEach(s => s.style.width = s.dataset.w + "%"));
  el.querySelectorAll(".topic-card").forEach(c => c.onclick = () => openTopicDrawer(c.dataset.id));
}

/* 节点详情抽屉 */
function drawerEsc(e) { if (e.key === "Escape") closeDrawer(); }
function closeDrawer() { const s = $("#drawer-scrim"); if (s) s.remove(); document.removeEventListener("keydown", drawerEsc); lockScroll(false); }
async function openTopicDrawer(id) {
  closeDrawer();
  let d;
  try { d = await api("/api/topic/" + id); } catch (e) { toast("详情载入失败:" + friendlyError(e)); return; }
  const v = d.mastery || 0, cls = v === 0 ? "zero" : "";
  const linkChips = (arr) => arr.map(x => `<span class="chip-link" data-open="${x.id}">${escapeHtml(x.title)}</span>`).join("");
  const sec = (title, inner) => inner ? `<div class="drawer-sec"><span class="h">${title}</span>${inner}</div>` : "";
  const concepts = d.core_concepts.length ? `<div class="chips">${d.core_concepts.map(c => `<span class="chip-static">${escapeHtml(c)}</span>`).join("")}</div>` : "";
  const outline = d.outline.length ? `<ol class="outline-list">${d.outline.map(o => `<li>${escapeHtml(o)}</li>`).join("")}</ol>` : "";
  const scrim = document.createElement("div");
  scrim.className = "drawer-scrim"; scrim.id = "drawer-scrim";
  scrim.innerHTML = `<aside class="drawer" role="dialog" aria-modal="true" aria-label="知识点详情">
    <div class="drawer-head">
      <div>
        <span class="badge diff"><span class="dot"></span>${d.difficulty} · ${escapeHtml(d.category)} · ${statusLabel(d.status)}</span>
        <h3 class="drawer-title" tabindex="-1">${escapeHtml(d.title)}</h3>
        <div class="drawer-en">${escapeHtml(d.title_en || "")}</div>
      </div>
      <button class="da-btn ghost icon" id="drawer-close" aria-label="关闭详情"><i data-lucide="x"></i></button>
    </div>
    ${d.summary ? `<div class="drawer-sec"><div class="drawer-sum">${escapeHtml(d.summary)}</div></div>` : ""}
    <div class="drawer-sec"><span class="h">掌握度</span><div class="drawer-mastery"><span class="mbar ${cls}" style="flex:1"><span data-w="${v}"></span></span><span class="mval">${v ? v.toFixed(0) : "—"}</span></div></div>
    ${sec("核心概念", concepts)}
    ${sec("内容大纲", outline)}
    ${sec("前置知识", d.prereqs.length ? `<div class="chips">${linkChips(d.prereqs)}</div>` : "")}
    ${sec("学完可解锁", d.leads_to.length ? `<div class="chips">${linkChips(d.leads_to)}</div>` : "")}
    ${sec("相关知识", d.related.length ? `<div class="chips">${linkChips(d.related)}</div>` : "")}
    ${state.readonly ? "" : `<div class="drawer-actions">
      <button class="da-btn primary block" id="dw-read"><i data-lucide="book-open-text"></i> 阅读完整教材</button>
      <button class="da-btn secondary" id="dw-ask"><i data-lucide="message-circle"></i> 问导师</button>
      <button class="da-btn secondary" id="dw-quiz"><i data-lucide="clipboard-check"></i> 测一测</button>
    </div>`}
  </aside>`;
  document.body.appendChild(scrim);
  lockScroll(true);
  icons(scrim);
  requestAnimationFrame(() => scrim.querySelectorAll(".mbar > span[data-w]").forEach(s => s.style.width = s.dataset.w + "%"));
  scrim.onclick = (e) => { if (e.target === scrim) closeDrawer(); };
  $("#drawer-close", scrim).onclick = closeDrawer;
  scrim.querySelectorAll("[data-open]").forEach(c => c.onclick = () => openTopicDrawer(c.dataset.open));
  const rd = $("#dw-read", scrim); if (rd) rd.onclick = () => { closeDrawer(); navigate("reader", { topic: id }); };
  const ask = $("#dw-ask", scrim); if (ask) ask.onclick = () => { closeDrawer(); state.chatTopic = id; navigate("chat"); };
  const qz = $("#dw-quiz", scrim); if (qz) qz.onclick = () => { closeDrawer(); navigate("quiz", { topic: id }); };
  document.addEventListener("keydown", drawerEsc);
  const cl = $("#drawer-close", scrim); if (cl) cl.focus();
}

/* ---------------- 课程教材(电子书阅读页) ---------------- */
// 数学安全的 Markdown 渲染:先把公式抽出占位,marked+净化后再还原原始公式,最后由调用方跑 KaTeX。
// 直接用 marked 会把 $\nabla_w L$、$\sum_{i=1}^{m}$ 里的 _ / * 误判成 <em>/<strong>,破坏公式。
function mdBook(src) {
  const math = [];
  const stash = (raw) => { const k = "MATHPLACEHOLDER" + math.length + "ENDMATH"; math.push(raw); return k; };
  let s = src || "";
  s = s.replace(/\\\$/g, () => "$");   // 部分知识库正文把美元定界符写成转义的 \$,统一还原为裸 $ 供 KaTeX 识别
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => stash("$$" + m + "$$"));   // display 先抽
  s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => stash("\\[" + m + "\\]"));
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => stash("\\(" + m + "\\)"));
  s = s.replace(/\$([^\n$]+?)\$/g, (_, m) => stash("$" + m + "$"));         // 行内(单行、不含 $)
  let html = window.marked ? marked.parse(s, { breaks: true, gfm: true }) : escapeHtml(s);
  if (window.DOMPurify) html = DOMPurify.sanitize(html, { ADD_ATTR: ["target"] });
  html = html.replace(/MATHPLACEHOLDER(\d+)ENDMATH/g, (_, i) => escapeHtml(math[+i]));  // 净化后还原
  return html;
}

async function renderReader() {
  const id = state.readerTopic;
  if (!id) { navigate("topics"); return; }   // 直接刷新 / 后退兜底
  view().innerHTML = `<div class="loading-row"><span class="spin"></span> 正在载入教材…</div>`;
  icons();
  let d;
  try { d = await api("/api/topic/" + id + "/content"); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderReader); return; }

  const v = d.mastery || 0, cls = v === 0 ? "zero" : "";
  const toc = (d.sections || []).map((s, i) => `<a class="toc-item" href="#sec-${i}" data-sec="${i}">${escapeHtml(s)}</a>`).join("");
  const navCard = (t, dir) => t
    ? `<button class="reader-nav ${dir}" data-rdgo="${t.id}"><span class="rn-dir">${dir === "prev" ? "← 上一课" : "下一课 →"}</span><span class="rn-t">${escapeHtml(t.title)}</span></button>`
    : `<span class="reader-nav empty"></span>`;
  const actions = state.readonly ? "" : `<div class="reader-actions">
      <button class="da-btn secondary sm" id="rd-ask"><i data-lucide="message-circle"></i> 问导师</button>
      <button class="da-btn secondary sm" id="rd-quiz"><i data-lucide="clipboard-check"></i> 测一测</button>
    </div>`;

  view().innerHTML = `
    <div class="reader-progress" id="reader-progress"><span></span></div>
    <div class="reader-top">
      <button class="da-btn ghost sm" id="reader-back"><i data-lucide="arrow-left"></i> 返回知识图谱</button>
      ${actions}
    </div>
    <div class="reader-layout">
      <aside class="reader-toc" aria-label="本章目录">
        <div class="rt-head"><i data-lucide="list"></i> 目录</div>
        <nav class="rt-nav">${toc || '<span class="coord">本课无小节</span>'}</nav>
        <div class="rt-meta"><span class="coord">MASTERY</span><span class="mbar ${cls}"><span data-w="${v}"></span></span><span class="mval">${v ? v.toFixed(0) : "—"}</span></div>
      </aside>
      <article class="reader-main">
        <header class="reader-head">
          <span class="badge diff"><span class="dot"></span>${d.difficulty} · ${escapeHtml(d.category)} · ${statusLabel(d.status)}</span>
          <h1 class="page-title reader-title" tabindex="-1">${escapeHtml(d.title)}</h1>
          <div class="reader-en">${escapeHtml(d.title_en || "")}</div>
          ${d.summary ? `<p class="reader-sum">${escapeHtml(d.summary)}</p>` : ""}
        </header>
        <div class="md reader-body" id="reader-body"></div>
        <nav class="reader-foot-nav">${navCard(d.prev, "prev")}${navCard(d.next, "next")}</nav>
      </article>
    </div>`;

  const bodyEl = $("#reader-body");
  bodyEl.innerHTML = mdBook(d.body || "");
  bodyEl.querySelectorAll("h2").forEach((h, i) => { h.id = "sec-" + i; });   // 目录锚点,按文档顺序编号
  renderMath(bodyEl);                                                        // 还原后再跑 KaTeX

  requestAnimationFrame(() => view().querySelectorAll(".mbar > span[data-w]").forEach(s => s.style.width = s.dataset.w + "%"));
  $("#reader-back").onclick = () => navigate("topics");
  const ask = $("#rd-ask"); if (ask) ask.onclick = () => { state.chatTopic = id; navigate("chat"); };
  const qz = $("#rd-quiz"); if (qz) qz.onclick = () => navigate("quiz", { topic: id });
  view().querySelectorAll("[data-rdgo]").forEach(b => b.onclick = () => { navigate("reader", { topic: b.dataset.rdgo }); });

  const sc = view();
  const relTop = (el) => el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop;
  view().querySelectorAll(".toc-item").forEach(a => a.onclick = (e) => {
    e.preventDefault();
    const t = document.getElementById("sec-" + a.dataset.sec);
    if (t) sc.scrollTo({ top: relTop(t) - 16, behavior: reduceMotion ? "auto" : "smooth" });
  });
  setupReaderScroll(bodyEl);
  icons();
}

// 阅读进度条 + 目录滚动高亮(scroll-spy)。滚动容器是 #view(.main{overflow-y:auto})。
function setupReaderScroll(bodyEl) {
  const sc = view();
  const bar = $("#reader-progress > span");
  const heads = Array.from(bodyEl.querySelectorAll("h2"));
  const items = Array.from(document.querySelectorAll(".toc-item"));
  const relTop = (el) => el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop;
  let ticking = false;
  const onScroll = () => {
    if (ticking) return; ticking = true;
    requestAnimationFrame(() => {
      const max = sc.scrollHeight - sc.clientHeight;
      if (bar) bar.style.width = (max > 0 ? Math.min(100, sc.scrollTop / max * 100) : 0) + "%";
      const line = sc.scrollTop + 120;
      let active = 0;
      heads.forEach((h, i) => { if (relTop(h) <= line) active = i; });
      items.forEach((it, i) => it.classList.toggle("on", i === active));
      ticking = false;
    });
  };
  sc.onscroll = onScroll;
  onScroll();
}

/* ---------------- 智能测评 ---------------- */
async function renderQuiz() {
  if (!state.topics) { try { state.topics = (await api("/api/topics")).topics; } catch (e) { state.topics = []; } }
  const head = pageHead("EVALUATION · 自适应命题", "智能测评", "依据你在该知识点的掌握度自适应出题,自动评分并给出个性化反馈,结果回写学情。");
  if (!state.topics.length) { const c = document.createElement("div"); view().innerHTML = head; view().appendChild(c); errorState(c, "知识点列表暂不可用", renderQuiz); return; }
  const opts = state.topics.map(t => `<option value="${t.id}" ${state.quizTopic === t.id ? "selected" : ""}>${t.title}${t.mastery ? `(掌握 ${t.mastery.toFixed(0)})` : ""}</option>`).join("");
  let quizzes = [];
  try { quizzes = (await api("/api/quizzes")).quizzes; } catch (e) {}
  view().innerHTML = head +
    `<div class="panel accent"><div class="panel-head"><h3 class="panel-title">配置测评</h3>
      <div style="display:flex;gap:6px"><button class="da-btn ghost sm" id="show-mistakes"><i data-lucide="book-x"></i> 错题本</button><span class="coord">ADAPTIVE</span></div></div>
      <div class="panel-body"><div class="quiz-setup" style="margin:0">
        <div class="field"><label for="q-topic">选择知识点</label><select id="q-topic">${opts}</select></div>
        <div class="field"><label for="q-n">题量</label><select id="q-n"><option>4</option><option selected>5</option><option>6</option></select></div>
        <button class="da-btn primary" id="q-gen"><i data-lucide="wand-2"></i> 生成试题</button>
      </div></div></div>
    <div id="quiz-area">${quizIntro(quizzes)}</div>`;
  icons();
  $("#q-gen").onclick = genQuiz;
  $("#show-mistakes").onclick = renderMistakes;
  view().querySelectorAll("[data-review]").forEach(b => b.onclick = () => openReview(b.dataset.review));
}
function quizIntro(quizzes) {
  const hist = (quizzes && quizzes.length) ? `<div class="panel" style="margin-top:18px"><div class="panel-head"><h3 class="panel-title">测评回顾</h3><span class="coord">HISTORY · 点击复盘</span></div>
    <div class="panel-body">${quizzes.slice(0, 8).map(q => { const sc = q.score, b = sc >= 75 ? `<span class="fbadge ok">已掌握</span>` : (sc < 60 ? `<span class="fbadge weak">待巩固</span>` : `<span class="fbadge">${sc.toFixed(0)}</span>`); return `<button class="feed-row" data-review="${q.id}"><i data-lucide="clipboard-check"></i><div style="flex:1;min-width:0"><div class="ft">《${escapeHtml(q.topic_title)}》得 ${sc.toFixed(0)} 分</div><div class="fm">${q.n} 题 · ${timeago(q.created_at)} · 点击查看逐题解析</div></div>${b}</button>`; }).join("")}</div></div>` : "";
  return `<div class="empty" style="padding:44px 20px"><div class="empty-mark"><i data-lucide="clipboard-check"></i></div>
    <h3>生成你的自适应测评</h3>
    <p>选择知识点并生成试题,系统会依据你在该知识点的掌握度调整难度,自动评分并给出个性化反馈。</p></div>${hist}`;
}
async function genQuiz() {
  const topic_id = $("#q-topic").value, n = parseInt($("#q-n").value, 10);
  const area = $("#quiz-area"), gen = $("#q-gen");
  area.innerHTML = `<div class="empty"><div class="empty-mark"><span class="spin"></span></div><h3>正在命题</h3><p>依据你的学情自适应生成 ${n} 道题…</p></div>`;
  gen.disabled = true; gen.classList.add("busy");
  try {
    state.quiz = await api("/api/quiz/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic_id, n }) });
    renderQuizQuestions();
  } catch (e) { errorState(area, friendlyError(e), genQuiz); }
  finally { gen.disabled = false; gen.classList.remove("busy"); }
}
function renderQuizQuestions() {
  const { quiz } = state.quiz;
  state.quizStart = Date.now();   // 记录开始作答时间,用于答题快慢 / 学习状态评价
  state.answerTimes = {};         // 逐题最后作答时刻,用于估算每题用时
  const qs = quiz.questions.map((q, i) => {
    const head = `<span class="qn">题 ${String(i + 1).padStart(2, "0")}</span><span class="qtype badge tag">${q.type === "choice" ? "单选" : "简答"}</span><div class="stem">${escapeHtml(q.stem)}</div>`;
    let body;
    if (q.type === "choice") {
      body = (q.options || []).map(o => { const letter = (o.trim()[0] || "").toUpperCase(); return `<label class="opt"><input type="radio" name="${q.id}" value="${letter}"> <span>${escapeHtml(o)}</span></label>`; }).join("");
    } else body = `<textarea data-q="${q.id}" placeholder="在此作答…" aria-label="作答 ${i + 1}"></textarea>`;
    return `<div class="quiz-q" id="qq-${q.id}">${head}${body}</div>`;
  }).join("");
  const total = quiz.questions.length;
  $("#quiz-area").innerHTML =
    `<div class="quiz-progress"><span id="q-count">0 / ${total} 已作答</span><span class="pbar"><span id="q-pbar"></span></span></div>` +
    qs + `<button class="da-btn primary" id="q-submit"><i data-lucide="check-check"></i> 提交评分</button>`;
  icons();
  renderMath($("#quiz-area"));   // 渲染题干/选项中的 LaTeX 公式
  // 作答进度
  const upd = () => {
    let done = 0;
    quiz.questions.forEach(q => { if (q.type === "choice") { if (document.querySelector(`input[name="${q.id}"]:checked`)) done++; } else { const t = document.querySelector(`textarea[data-q="${q.id}"]`); if (t && t.value.trim()) done++; } });
    $("#q-count").textContent = `${done} / ${total} 已作答`;
    $("#q-pbar").style.width = (done / total * 100) + "%";
  };
  // 逐题用时:每次作答(input/change)记录该题最后作答时刻
  const markTime = (e) => { const box = e.target.closest(".quiz-q"); if (box && box.id.indexOf("qq-") === 0) state.answerTimes[box.id.slice(3)] = Date.now(); };
  $("#quiz-area").addEventListener("input", upd);
  $("#quiz-area").addEventListener("change", upd);
  $("#quiz-area").addEventListener("input", markTime);
  $("#quiz-area").addEventListener("change", markTime);
  $("#q-submit").onclick = submitQuiz;
}
async function submitQuiz() {
  const answers = {}; let unanswered = [];
  state.quiz.quiz.questions.forEach(q => {
    let v = "";
    if (q.type === "choice") { const sel = document.querySelector(`input[name="${q.id}"]:checked`); v = sel ? sel.value : ""; }
    else { const ta = document.querySelector(`textarea[data-q="${q.id}"]`); v = ta ? ta.value.trim() : ""; }
    answers[q.id] = v; if (!v) unanswered.push(q.id);
  });
  document.querySelectorAll(".quiz-q.unanswered").forEach(e => e.classList.remove("unanswered"));
  if (unanswered.length) {
    unanswered.forEach(id => $("#qq-" + id).classList.add("unanswered"));
    toast(`还有 ${unanswered.length} 题未作答`);
    $("#qq-" + unanswered[0]).scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
    return;
  }
  const btn = $("#q-submit"); btn.disabled = true; btn.classList.add("busy"); btn.innerHTML = `<span class="spin"></span> 评分中…`;
  try {
    const now = Date.now();
    const elapsed_sec = state.quizStart ? (now - state.quizStart) / 1000 : null;
    // 逐题用时:按作答先后排序,取相邻间隔(首题从开始作答算起),保证非负且累加≈总用时
    const order = Object.entries(state.answerTimes || {}).map(([id, t]) => ({ id, t })).sort((a, b) => a.t - b.t);
    const question_times = {}; let prev = state.quizStart || (order[0] ? order[0].t : now);
    for (const e of order) { question_times[e.id] = Math.max(0, (e.t - prev) / 1000); prev = e.t; }
    const res = await api("/api/quiz/grade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ quiz_id: state.quiz.quiz_id, answers, elapsed_sec, question_times }) });
    renderQuizResult(res);
  } catch (e) { btn.disabled = false; btn.classList.remove("busy"); btn.innerHTML = "提交评分"; toast("评分失败:" + friendlyError(e)); }
}
function renderQuizResult(res) {
  const byId = {}; res.results.forEach(r => byId[r.id] = r);
  state.quiz.quiz.questions.forEach(q => {
    const r = byId[q.id], box = $("#qq-" + q.id); if (!box || !r) return;
    const ok = r.type === "choice" ? r.correct : r.score >= 60;
    if (r.type === "choice") {
      box.querySelectorAll(".opt").forEach(o => {
        const v = (o.querySelector("input").value || "").toUpperCase(); o.style.pointerEvents = "none"; o.querySelector("input").disabled = true;
        if (v === r.answer) { o.classList.add("correct"); o.insertAdjacentHTML("beforeend", `<span class="opt-tag"><i data-lucide="check"></i>正确答案</span>`); }
        else if (v === (r.your || "").toUpperCase()[0]) { o.classList.add("wrong"); o.insertAdjacentHTML("beforeend", `<span class="opt-tag"><i data-lucide="x"></i>你的作答</span>`); }
      });
    } else { const ta = box.querySelector("textarea"); if (ta) ta.disabled = true; }
    const extra = document.createElement("div"); extra.className = "qresult";
    extra.innerHTML =
      `<div class="verdict ${ok ? "ok" : "no"}"><i data-lucide="${ok ? "check-circle-2" : "alert-circle"}"></i> ${r.type === "choice" ? (ok ? "回答正确" : `正确答案:${r.answer}`) : `得分 ${r.score}`}</div>` +
      (r.reference ? `<div class="expl"><b>参考要点:</b>${escapeHtml(r.reference)}</div>` : "") +
      (r.feedback ? `<div class="expl"><b>点评:</b>${escapeHtml(r.feedback)}</div>` : "") +
      (r.explanation ? `<div class="expl"><b>解析:</b>${escapeHtml(r.explanation)}</div>` : "");
    box.appendChild(extra);
  });
  const banner = document.createElement("div"); banner.className = "result-banner";
  const st = res.state;
  const stateLine = st ? `<div class="result-state">${stateBadge(st)}<span class="rs-summary">${escapeHtml(st.summary || st.reason || "")}</span></div>` : "";
  banner.innerHTML = `
    <div class="score-ring"><div class="inner"><div class="v" data-count="${res.overall}">0</div><div class="l">总分</div></div></div>
    <div><div class="eyebrow">个性化评价 · 掌握度更新为 ${res.new_mastery}</div>
    <div class="result-fb" style="margin-top:10px">${escapeHtml(res.feedback || "")}</div>${stateLine}</div>`;
  $("#quiz-area").prepend(banner);
  const ring = banner.querySelector(".score-ring");
  requestAnimationFrame(() => { ring.style.setProperty("--val", res.overall); });
  countUp(banner.querySelector(".v"), res.overall);
  const sub = $("#q-submit"); if (sub) sub.outerHTML = `<button class="da-btn secondary" id="q-again"><i data-lucide="rotate-ccw"></i> 再测一次</button>`;
  const again = $("#q-again"); if (again) again.onclick = () => navigate("quiz", { topic: res.topic_id });
  icons();
  renderMath($("#quiz-area"));   // 渲染解析/点评/参考要点中的 LaTeX 公式
  banner.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
}

/* ---------------- 关于 ---------------- */
function renderAbout() {
  const h = state.health || {};
  const release = `<div class="panel"><div class="panel-head"><h3 class="panel-title">版本与运行</h3><span class="coord">RELEASE</span></div>
    <div class="panel-body"><div class="about-meta">
      <div><span class="k">版本</span><span class="v">v1.0.0</span></div>
      <div><span class="k">对话引擎</span><span class="v">${escapeHtml(h.model || "Gemini")}</span></div>
      <div><span class="k">知识库</span><span class="v">${(h.topics || 16)} 个知识点 · ${(h.chunks || 131)} 块</span></div>
      <div><span class="k">索引状态</span><span class="v">${h.index_ready ? "就绪" : "构建中"}</span></div>
    </div></div></div>`;
  view().innerHTML = pageHead("ABOUT · 产品信息", "关于智学",
    "面向人工智能方向本科生的个性化学习指导与评价系统。以掌握度建模驱动辅导与命题,形成学—评—调闭环。",
    `<span class="coord">v1.0.0</span>`) +
    release + `<div class="panel"><div class="panel-body md" id="about-md"></div></div>`;
  $("#about-md").innerHTML = md(`
### 系统能力
- **个性化指导**:导师依据你的实时掌握度调整讲解深浅,薄弱处多铺垫直觉,已掌握处深入拓展。
- **知识检索(RAG)**:回答基于人工智能课程知识库检索,并标注来源,减少臆测。
- **智能评价**:自适应命题、自动评分、个性化反馈,测评结果回写学情,形成闭环。

### 技术架构
- **大模型底座**:Google Gemini(对话与命题评分)+ gemini-embedding 向量检索。
- **检索增强**:课程级知识库按小节切块、向量化,余弦相似度召回 Top-K。
- **后端**:FastAPI,SSE 流式输出;**前端**:原生 SPA,采用统一的视觉设计系统(中国红 + 暖白 + 火焰橙,锋利克制)。
- **学情建模**:掌握度以指数滑动平均更新,测评(权重高)与对话曝光(权重低)共同驱动。

### 使用建议
1. 在「知识图谱」浏览知识点,点「问导师」开始个性化对话;
2. 用「智能测评」检验掌握,系统据你的水平自适应难度;
3. 回到「学习概览」查看掌握度与学习轨迹。
`);
  renderMath($("#about-md")); icons();
}

/* ---------------- 移动端侧栏 ---------------- */
function lockScroll(on) { document.documentElement.style.overflow = on ? "hidden" : ""; }
function openNav() {
  $(".app").classList.add("nav-open");
  const h = $("#hamburger"); if (h) h.setAttribute("aria-expanded", "true");
  lockScroll(true);
  requestAnimationFrame(() => { const f = document.querySelector(".app.nav-open .nav-item.is-active") || document.querySelector(".app.nav-open .nav-item"); if (f) f.focus(); });
}
function closeNav() {
  const app = $(".app"); if (!app.classList.contains("nav-open")) return;
  app.classList.remove("nav-open");
  const h = $("#hamburger"); if (h) { h.setAttribute("aria-expanded", "false"); h.focus(); }
  lockScroll(false);
}

/* 软键盘 / 地址栏:把可视视口高度写入 --vvh,供移动端 .col 使用 */
function trackViewport() {
  const vv = window.visualViewport; if (!vv) return;
  const set = () => {
    document.documentElement.style.setProperty("--vvh", vv.height + "px");
    if (state.view === "chat" && state.streaming) scrollChat(true);
  };
  set(); vv.addEventListener("resize", set); vv.addEventListener("scroll", set);
}

/* ================= 身份与登录 ================= */
const entryRole = location.pathname.startsWith('/teacher') ? 'teacher' : location.pathname.startsWith('/student') ? 'student' : null;
const identityKey = 'zx_identity_' + (entryRole || 'legacy');
function loadIdentity() { try { return JSON.parse(sessionStorage.getItem(identityKey) || 'null'); } catch (e) { return null; } }
function saveIdentity(id) { state.identity = id; sessionStorage.setItem(identityKey, JSON.stringify(id)); }
async function logout() {
  await window.zxBeforeLogout?.();
  if (!isTeacher()) await fetch('/api/logout', { method: 'POST', headers: authHeaders() }).catch(() => {});
  state.abort?.abort(); sessionStorage.removeItem(identityKey); state.identity = null; state.viewSid = null; state.readonly = false; state.chatLoaded = false; state.chat = []; state.topics = null;
  window.dispatchEvent(new CustomEvent('zx-view', { detail: { view: '', identity: null } })); showGate();
}

function allowedView(v) {
  const tviews = ["t-overview", "t-students", "t-student", "t-documents"];
  if (isTeacher()) return tviews.includes(v) ? v : "t-overview";
  return tviews.includes(v) ? "dashboard" : v;
}
function defaultView() { return isTeacher() ? "t-overview" : entryRole === "student" ? "learning" : "dashboard"; }

function setOrgTeacher() {
  $("#org .org-name").textContent = "教师 · 管理端";
  $("#org .org-plan").textContent = "全班学情监控";
  const dot = $("#org .org-dot"); if (dot) dot.textContent = "师";
  const av = $("#avatar"); if (av) av.textContent = "师";
}

function enterApp() {
  document.body.classList.remove("gated");
  if (isTeacher()) setOrgTeacher();
  const initial = (location.hash || "").slice(1);
  renderView(allowedView(VIEWS[initial] ? initial : defaultView()));
}

/* 身份门 */
function showGate() { document.body.classList.add("gated"); entryRole === 'student' ? gateStudent() : entryRole === 'teacher' ? gateTeacher() : gateRole(); }

function gateShell(inner) {
  $("#gate").innerHTML = `<div class="gate-card">
    <div class="gate-brand"><div class="brand-mark">智</div><div><div class="gate-zh">智学</div><div class="gate-en">PERSONALIZED LEARNING</div></div></div>
    <div class="gate-sub">基于大语言模型的个性化学习指导与评价</div>
    ${inner}
  </div>`;
  icons($("#gate"));
}
function gateRole() {
  if (entryRole) { location.href = '/'; return; }
  gateShell(`<div class="gate-roles">
      <button class="gate-role" id="g-student"><i data-lucide="graduation-cap"></i><span class="t">我是学生</span><span class="d">进入个性化学习</span></button>
      <button class="gate-role" id="g-teacher"><i data-lucide="users"></i><span class="t">我是教师</span><span class="d">进入班级管理端</span></button>
    </div>`);
  $("#g-student").onclick = gateStudent;
  $("#g-teacher").onclick = gateTeacher;
}
function gateStudent() {
  gateShell(`<div class="gate-back" id="g-back"><i data-lucide="arrow-left"></i> 返回</div>
    <div class="eyebrow" style="margin-bottom:12px">学生登录</div>
    <div class="gate-form">
      <div class="field"><label>账号</label><input id="s-user" placeholder="账号(通常是学号)" autocomplete="username"></div>
      <div class="field"><label>密码</label><input id="s-pass" type="password" placeholder="请输入密码" autocomplete="current-password"></div>
      <button class="da-btn primary" id="s-login"><i data-lucide="log-in"></i> 登录</button>
      <div class="coord" style="margin-top:4px">账号由教师开通 · 演示账号:demo / 888888</div>
    </div>`);
  $("#g-back").onclick = gateRole;
  const submit = async () => {
    const username = $("#s-user").value.trim(), password = $("#s-pass").value;
    if (!username || !password) return toast("请输入账号和密码");
    try {
      const s = await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
      enterAsStudent(s);
    } catch (e) { toast(friendlyError(e)); }
  };
  $("#s-login").onclick = submit;
  $("#s-pass").onkeydown = (e) => { if (e.key === "Enter") submit(); };
  $("#s-user").onkeydown = (e) => { if (e.key === "Enter") $("#s-pass").focus(); };
  $("#s-user").focus();
}
function enterAsStudent(s) {
  if (!s) return;
  saveIdentity({ role: "student", sid: s.id, name: s.name, token: s.token });
  state.chatLoaded = false; state.chat = []; state.topics = null;
  try { history.replaceState({}, "", entryRole === "student" ? "#learning" : "#dashboard"); } catch (e) {}
  enterApp();
}
function gateTeacher() {
  gateShell(`<div class="gate-back" id="g-back"><i data-lucide="arrow-left"></i> 返回</div>
    <div class="eyebrow" style="margin-bottom:12px">教师登录</div>
    <div class="gate-form">
      <div class="field"><label>管理口令</label><input id="t-pass" type="password" placeholder="请输入教师口令" autocomplete="off"></div>
      <button class="da-btn primary" id="t-login"><i data-lucide="log-in"></i> 进入管理端</button>
      <div class="coord" style="margin-top:4px">演示口令:888888</div>
    </div>`);
  $("#g-back").onclick = gateRole;
  const submit = async () => {
    const pass = $("#t-pass").value.trim(); if (!pass) return;
    try {
      await api("/api/teacher/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ passcode: pass }) });
      saveIdentity({ role: "teacher", pass });
      try { history.replaceState({}, "", "#t-overview"); } catch (e) {}
      enterApp();
    } catch (e) { toast("口令无效"); }
  };
  $("#t-login").onclick = submit;
  $("#t-pass").onkeydown = (e) => { if (e.key === "Enter") submit(); };
  $("#t-pass").focus();
}

/* ================= 通用弹窗 ================= */
function openModal(html) {
  closeModal();
  const s = document.createElement("div");
  s.className = "modal-scrim"; s.id = "modal-scrim";
  s.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  document.body.appendChild(s); lockScroll(true); icons(s);
  s.onclick = (e) => { if (e.target === s) closeModal(); };
  document.addEventListener("keydown", modalEsc);
  return s;
}
function modalEsc(e) { if (e.key === "Escape") closeModal(); }
function closeModal() { const s = $("#modal-scrim"); if (s) s.remove(); document.removeEventListener("keydown", modalEsc); lockScroll(false); }
function confirmDialog(title, msg, onYes, danger) {
  const s = openModal(`<div class="modal-head"><h3>${escapeHtml(title)}</h3></div>
    <p class="modal-msg">${escapeHtml(msg)}</p>
    <div class="modal-foot"><button class="da-btn ghost" id="m-cancel">取消</button><button class="da-btn ${danger ? "danger" : "primary"}" id="m-yes">确定</button></div>`);
  $("#m-cancel", s).onclick = closeModal;
  $("#m-yes", s).onclick = () => { closeModal(); onYes(); };
}

/* ================= 教师端 ================= */
function heatRow(t) {
  const v = t.avg || 0, weak = t.studied > 0 && v < 60, cls = v === 0 ? "zero" : (weak ? "weak" : "");
  return `<button class="mrow clickable" data-topic="${t.id}"><span class="mname">${escapeHtml(t.title)}</span>
    <span class="mbar ${cls}"><span data-w="${v}"></span></span>
    <span class="mval ${weak ? "weak" : ""}">${t.studied ? v.toFixed(0) : "—"}</span>
    <span class="coord" style="flex:0 0 52px;text-align:right">${t.studied}人</span></button>`;
}
function teacherActivity(acts) {
  if (!acts || !acts.length) return `<div class="empty" style="padding:24px"><div class="empty-mark"><i data-lucide="clock"></i></div><h3 style="font-size:17px">暂无活动</h3></div>`;
  const ico = { chat: "messages-square", quiz_start: "file-pen", quiz_done: "clipboard-check" };
  return acts.map(e => {
    let t = "";
    if (e.kind === "chat") t = `咨询了「${(e.detail.topics || []).join("、") || "学习问题"}」`;
    else if (e.kind === "quiz_start") t = `开始《${e.detail.topic}》测评`;
    else if (e.kind === "quiz_done") t = `《${e.detail.topic}》测评得 ${e.detail.score} 分`;
    else t = e.kind;
    // 评价反馈(quiz_done)且带 quiz_id 时:可点击查看与学生一致的评价反馈 + 学习状态
    const qid = (e.kind === "quiz_done") ? (e.detail.quiz_id || "") : "";
    if (qid) {
      return `<button class="feed-row clickable" data-review="${qid}" data-sid="${e.student_id || ""}"><i data-lucide="${ico[e.kind] || "circle"}"></i><div style="flex:1;min-width:0"><div class="ft"><b>${escapeHtml(e.student || "")}</b> ${escapeHtml(t)}</div><div class="fm">${timeago(e.created_at)} · 点击查看评价反馈与学习状态</div></div><i data-lucide="chevron-right" class="fr-go"></i></button>`;
    }
    return `<div class="feed-row" style="cursor:default"><i data-lucide="${ico[e.kind] || "circle"}"></i><div style="flex:1;min-width:0"><div class="ft"><b>${escapeHtml(e.student || "")}</b> ${escapeHtml(t)}</div><div class="fm">${timeago(e.created_at)}</div></div></div>`;
  }).join("");
}
// 教师端·学习状态感知:全班状态分布 + 逐生状态卡(含大模型解释,点击下钻)
function teacherStatePanel(d) {
  const sc = d.state_counts || {};
  const dist = `<div class="state-dist">
      <span class="sd good"><b>${sc.good || 0}</b> 专注良好</span>
      <span class="sd normal"><b>${sc.normal || 0}</b> 状态一般</span>
      <span class="sd poor"><b>${sc.poor || 0}</b> 状态欠佳</span>
      <span class="sd unknown"><b>${sc.unknown || 0}</b> 数据不足</span>
    </div>`;
  const list = (d.states || []).filter(x => x.state !== "unknown");
  const cards = list.length ? `<div class="state-grid">${list.map(x => {
    const mt = x.metrics || {};
    const meta = mt.samples ? `<div class="ss-meta">每题 ${mt.avg_sec_per_q}s · 节奏 ${mt.pace_ratio}× · 正确率 ${mt.avg_score}</div>` : "";
    return `<button class="state-stu clickable ${x.state}" data-sid="${x.id}">
      <div class="ss-head"><span class="ss-name">${escapeHtml(x.name)}</span>${stateBadge(x)}</div>
      ${meta}<div class="ss-sum">${escapeHtml(x.summary || "")}</div></button>`;
  }).join("")}</div>`
    : `<p class="page-lede" style="font-size:13px;padding:6px 0">尚无学生完成带计时的测评,完成后这里会按答题快慢呈现每位学生的学习状态。</p>`;
  return `<div class="panel"><div class="panel-head"><h3 class="panel-title">学习状态感知</h3><span class="coord">STATE · 答题快慢 + 表情(预留)</span></div>
    <div class="panel-body">${dist}${cards}</div></div>`;
}

async function renderTeacherOverview() {
  view().innerHTML = pageHead("TEACHER · 班级总览", "班级总览", "全班学情一览:掌握度热力、待关注学生与最近活动。") +
    `<div class="loading-row"><span class="spin"></span> 载入班级数据…</div>`;
  icons();
  let d;
  try { d = await api("/api/teacher/overview"); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderTeacherOverview); return; }
  const s = d.summary;
  const metrics = `<div class="metrics">
    ${metric("学生数", s.students, "人", "全班", "CLASS")}
    ${metric("班级均掌握", s.avg_mastery, "分", "已学知识点", "WEIGHTED")}
    ${metric("近 24h 活跃", s.active_24h, "人", "学习活动", "ACTIVE")}
    ${metric("累计测评", s.quizzes_done, "次", "全班", "TOTAL")}</div>`;
  const heat = `<div class="panel"><div class="panel-head"><h3 class="panel-title">知识点掌握热力</h3><span class="coord">CLASS AVG</span></div>
    <div class="panel-body">${d.topics.map(heatRow).join("")}</div></div>`;
  const strug = `<div class="panel accent"><div class="panel-head"><h3 class="panel-title">待关注学生</h3><span class="coord">${d.struggling.length}</span></div>
    <div class="panel-body">${d.struggling.length ? d.struggling.map(st =>
      `<button class="mrow clickable" data-sid="${st.id}"><span class="mname">${escapeHtml(st.name)}</span><span class="mbar ${st.avg_mastery < 60 ? "weak" : ""}"><span data-w="${st.avg_mastery}"></span></span><span class="mval weak">${st.avg_mastery.toFixed(0)}</span>${st.state ? stateBadge(st.state) : `<span class="coord" style="flex:0 0 56px;text-align:right">${st.weak_count}薄弱</span>`}</button>`).join("")
      : `<p class="page-lede" style="font-size:13px;padding:6px 0">暂无明显落后的学生。</p>`}</div></div>`;
  const insight = `<div class="panel"><div class="panel-head"><h3 class="panel-title">教学建议</h3><button class="da-btn ghost sm" id="gen-insight"><i data-lucide="sparkles"></i> 生成</button></div>
    <div class="panel-body" id="insight-body"><p class="page-lede" style="font-size:13px;padding:6px 0">点击「生成」,系统将基于全班最弱知识点给出教学侧重建议。</p></div></div>`;
  const feed = `<div class="panel"><div class="panel-head"><h3 class="panel-title">最近活动</h3><span class="coord">LOG</span></div>
    <div class="panel-body">${teacherActivity(d.activity)}</div></div>`;
  const poorN = (d.state_counts && d.state_counts.poor) || 0;
  const stateNotice = poorN ? `<div class="notice"><i data-lucide="activity"></i> ${poorN} 名学生当前学习状态欠佳(答题过快/过慢),建议重点关注。</div>` : "";
  const alert = (d.inactive && d.inactive.length) ? `<div class="notice"><i data-lucide="alert-triangle"></i> ${d.inactive.length} 名学生 3 天以上未活跃:${d.inactive.slice(0, 5).map(x => escapeHtml(x.name)).join("、")}${d.inactive.length > 5 ? " 等" : ""}</div>` : "";
  view().innerHTML = pageHead("TEACHER · 班级总览", "班级总览", "全班学情一览:掌握度热力、待关注学生与最近活动。点击知识点可下钻到逐生掌握。",
    `<span class="coord">${s.students} 名学生</span>`) +
    stateNotice + alert + metrics +
    `<div class="section-head"><h2 class="section-h2">学习状态感知</h2><span class="coord">LEARNING STATE</span></div>` +
    teacherStatePanel(d) +
    `<div class="section-head"><h2 class="section-h2">学情分析</h2><span class="coord">ANALYTICS</span></div>
     <div class="dash-grid"><div class="dash-main">${heat}${feed}</div><aside class="dash-side">${strug}${insight}</aside></div>`;
  requestAnimationFrame(() => view().querySelectorAll(".mbar > span[data-w]").forEach(x => x.style.width = x.dataset.w + "%"));
  view().querySelectorAll(".mrow.clickable[data-sid]").forEach(b => b.onclick = () => openStudent(b.dataset.sid));
  view().querySelectorAll(".state-stu[data-sid]").forEach(b => b.onclick = () => openStudent(b.dataset.sid));
  view().querySelectorAll(".feed-row[data-review]").forEach(b => b.onclick = () => openReview(b.dataset.review, b.dataset.sid));
  view().querySelectorAll(".mrow.clickable[data-topic]").forEach(b => b.onclick = () => openTopicBreakdown(b.dataset.topic));
  $("#gen-insight").onclick = async () => {
    const body = $("#insight-body"); body.innerHTML = `<div class="loading-row"><span class="spin"></span> 生成中…</div>`;
    try { const r = await api("/api/teacher/insight"); body.innerHTML = `<p style="font-family:var(--da-font-han);font-size:14px;line-height:1.7;color:var(--da-ink-1)">${escapeHtml(r.text)}</p>`; }
    catch (e) { body.innerHTML = `<p class="coord">生成失败:${escapeHtml(friendlyError(e))}</p>`; }
  };
  icons();
}

async function renderTeacherDocuments() {
  const topicsRequest = api("/api/topics");
  view().innerHTML = pageHead("TEACHER · COURSE MATERIALS", "课件管理", "创建和维护课程讲义；发布后可供学生阅读，并接入知识检索。",
    `<button class="da-btn primary sm" id="doc-new"><i data-lucide="plus"></i> 新建课件</button>`) +
    `<div class="loading-row"><span class="spin"></span> 载入课件…</div>`;
  icons();

  let topics;
  try {
    const data = await topicsRequest;
    topics = data.topics || [];
  } catch (e) {
    const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c);
    errorState(c, friendlyError(e), renderTeacherDocuments); return;
  }

  let docs = [], current = null, preview = null, editor = false, fileUrl = null;
  const root = view();
  const topicName = id => topics.find(t => t.id === id)?.title || id || "未关联知识点";
  const statusName = status => ({ draft: "草稿", indexing: "索引中", published: "已发布", read_only: "仅供阅读", failed: "发布失败", parse_failed: "解析失败" })[status] || status || "未知";
  const releaseFileUrl = () => { if (fileUrl) { URL.revokeObjectURL(fileUrl); fileUrl = null; } };
  const loadDocuments = async (selectId) => {
    const data = await api("/api/teacher/documents"); docs = data.documents || [];
    draw();
    const id = selectId || current?.id || docs[0]?.id;
    if (id) await selectDocument(id);
  };
  const draw = () => {
    if (state.view !== "t-documents") return;
    const list = docs.length ? docs.map(d => `<button class="doc-row ${current?.id === d.id ? "active" : ""}" data-doc="${escapeHtml(d.id)}">
      <span class="doc-kind ${d.kind === "pdf" ? "pdf" : "md"}">${d.kind === "pdf" ? "PDF" : "MD"}</span>
      <span class="doc-row-main"><strong>${escapeHtml(d.title)}</strong><small>${escapeHtml(topicName(d.topic_id))} · v${d.number || 1}</small></span>
      <span class="doc-status ${escapeHtml(d.status || "draft")}">${escapeHtml(statusName(d.status))}</span></button>`).join("") : `<div class="doc-empty">暂无课件</div>`;
    root.innerHTML = pageHead("TEACHER · COURSE MATERIALS", "课件管理", "创建和维护课程讲义；发布后可供学生阅读，并接入知识检索。",
      `<button class="da-btn primary sm" id="doc-new"><i data-lucide="plus"></i> 新建课件</button>`) +
      `<div class="doc-workspace"><section class="panel doc-list-panel"><div class="panel-head"><h2 class="panel-title">课件列表</h2><button class="da-btn ghost sm icon" id="doc-refresh" title="刷新列表" aria-label="刷新列表"><i data-lucide="refresh-cw"></i></button></div>
      <div class="doc-list">${list}</div></section><section class="panel doc-detail-panel" id="doc-detail"><div class="doc-empty">选择一个课件，或新建课件。</div></section></div>`;
    icons(root);
    $("#doc-new", root).onclick = () => { current = null; preview = null; editor = true; drawDetail(); };
    $("#doc-refresh", root).onclick = () => loadDocuments(current?.id).catch(e => toast(friendlyError(e)));
    root.querySelectorAll("[data-doc]").forEach(b => b.onclick = () => selectDocument(b.dataset.doc).catch(e => toast(friendlyError(e))));
    drawDetail();
  };
  const drawDetail = () => {
    const panel = $("#doc-detail", root); if (!panel) return;
    if (!current && !editor) { panel.innerHTML = `<div class="doc-empty">选择一个课件，或新建课件。</div>`; return; }
    if (editor) {
      const selectedTopic = current?.topic_id || topics[0]?.id || "";
      const initialMarkdown = preview?.markdown || "# 新课件\n\n";
      panel.innerHTML = `<div class="doc-editor-head"><div><div class="eyebrow">${current ? "NEW VERSION" : "NEW MATERIAL"}</div><h2>${current ? "编辑新版本" : "新建课件"}</h2></div><button class="da-btn ghost sm icon" id="doc-edit-close" title="关闭编辑" aria-label="关闭编辑"><i data-lucide="x"></i></button></div>
        <form id="doc-form" class="doc-form"><label class="field"><span>课件标题</span><input name="title" maxlength="255" required value="${escapeHtml(preview?.title || current?.title || "")}" placeholder="输入课件标题"></label>
        ${current ? `<div class="doc-topic-line">关联知识点：${escapeHtml(topicName(current.topic_id))}</div>` : `<label class="field"><span>关联知识点</span><select name="topic_id" required>${topics.map(t => `<option value="${escapeHtml(t.id)}" ${t.id === selectedTopic ? "selected" : ""}>${escapeHtml(t.title)}</option>`).join("")}</select></label>`}
        <label class="field"><span>上传文件 <small>PDF / Markdown，选择文件后将使用文件内容</small></span><input name="file" type="file" accept=".pdf,.md,application/pdf,text/markdown"></label>
        <label class="field"><span>Markdown 正文</span><textarea name="markdown" rows="14" placeholder="# 标题\n\n在此输入 Markdown 讲义">${escapeHtml(initialMarkdown)}</textarea></label>
        <p class="doc-form-note">上传 PDF 后可阅读；有可提取文字的页面会进入知识检索。</p>
        <div class="doc-form-actions"><button type="button" class="da-btn ghost" id="doc-cancel">取消</button><button type="button" class="da-btn secondary" id="doc-preview"><i data-lucide="eye"></i> 预览正文</button><button class="da-btn primary" id="doc-save"><i data-lucide="save"></i> 保存草稿</button></div></form>
        <div class="doc-inline-preview" id="doc-inline-preview" hidden></div>`;
      icons(panel);
      $("#doc-edit-close", panel).onclick = () => { editor = false; drawDetail(); };
      $("#doc-cancel", panel).onclick = () => { editor = false; drawDetail(); };
      $("#doc-preview", panel).onclick = () => {
        const form = $("#doc-form", panel), markdown = form.elements.markdown.value;
        const out = $("#doc-inline-preview", panel); out.hidden = false;
        out.innerHTML = `<div class="doc-preview-label">正文预览</div><article class="doc-prose">${md(markdown)}</article>`; renderMath(out);
      };
      $("#doc-form", panel).onsubmit = async e => {
        e.preventDefault();
        const form = e.currentTarget, save = $("#doc-save", panel), file = form.elements.file.files[0];
        const body = new FormData(); body.set("title", form.elements.title.value.trim());
        if (!file && !form.elements.markdown.value.trim()) return toast("请填写 Markdown 正文或上传课件文件");
        if (file) body.set("file", file); else body.set("markdown", form.elements.markdown.value);
        if (!current) body.set("topic_id", form.elements.topic_id.value);
        save.disabled = true;
        try {
          const path = current ? `/api/teacher/documents/${encodeURIComponent(current.id)}/versions` : "/api/teacher/documents";
          const saved = await api(path, { method: "POST", body });
          editor = false; preview = null; toast("草稿已保存"); await loadDocuments(saved.id);
        } catch (err) { toast(friendlyError(err)); }
        finally { save.disabled = false; }
      };
      return;
    }
    if (!current) return;
    const v = preview;
    const controls = `<div class="doc-preview-actions"><button class="da-btn secondary sm" id="doc-edit"><i data-lucide="pencil"></i> 编辑新版本</button>${v && ["draft", "failed"].includes(v.status) ? `<button class="da-btn primary sm" id="doc-publish"><i data-lucide="send"></i> ${v.status === "failed" ? "重试发布" : "发布"}</button>` : ""}${v?.status === "indexing" ? `<button class="da-btn secondary sm" id="doc-status-refresh"><i data-lucide="refresh-cw"></i> 刷新状态</button>` : ""}</div>`;
    const content = !v ? `<div class="loading-row"><span class="spin"></span> 载入版本…</div>` : v.kind === "pdf"
      ? (fileUrl ? `<iframe class="doc-pdf-preview" src="${fileUrl}" title="${escapeHtml(v.title)}"></iframe>` : `<div class="doc-empty">正在载入 PDF…</div>`)
      : `<article class="doc-prose">${md(v.markdown || "")}</article>`;
    const history = (current.versions || []).map(item => `<button class="doc-version ${v?.id === item.id ? "active" : ""}" data-version="${escapeHtml(item.id)}">v${item.number} · ${escapeHtml(statusName(item.status))}</button>`).join("");
    panel.innerHTML = `<div class="doc-editor-head"><div><div class="eyebrow">${escapeHtml(topicName(current.topic_id))} · ${current.kind === "pdf" ? "PDF" : "MARKDOWN"}</div><h2>${escapeHtml(v?.title || current.title)}</h2><div class="doc-meta">${v ? `版本 ${v.number} · ${escapeHtml(statusName(v.status))}` : "正在载入…"}${v?.page_count ? ` · ${v.text_pages}/${v.page_count} 页可检索` : ""}${v?.chunk_count ? ` · ${v.chunk_count} 个检索片段` : ""}</div></div>${controls}</div>
      ${v?.error ? `<div class="notice doc-error"><i data-lucide="alert-triangle"></i>${escapeHtml(v.error)}</div>` : ""}
      ${v?.status === "read_only" ? `<div class="notice"><i data-lucide="book-open"></i>该 PDF 没有可检索文字，学生仍可阅读。</div>` : ""}
      <div class="doc-preview">${content}</div>
      ${history ? `<div class="doc-history"><span>版本历史</span>${history}</div>` : ""}`;
    icons(panel);
    $("#doc-edit", panel)?.addEventListener("click", () => { editor = true; drawDetail(); });
    $("#doc-status-refresh", panel)?.addEventListener("click", () => selectDocument(current.id));
    $("#doc-publish", panel)?.addEventListener("click", publishCurrent);
    panel.querySelectorAll("[data-version]").forEach(b => b.onclick = () => selectDocument(current.id, b.dataset.version));
    renderMath(panel);
  };
  const selectDocument = async (id, versionId) => {
    releaseFileUrl(); editor = false; preview = null;
    try {
      current = await api(`/api/teacher/documents/${encodeURIComponent(id)}`);
      draw();
      const target = versionId || current.latest_version_id;
      if (!target) return;
      preview = await api(`/api/documents/${encodeURIComponent(id)}/versions/${encodeURIComponent(target)}`);
      if (preview.kind === "pdf" && preview.has_file) {
        const response = await fetch(`/api/documents/${encodeURIComponent(id)}/versions/${encodeURIComponent(target)}/file`, { headers: authHeaders() });
        if (!response.ok) throw new Error("PDF 预览载入失败");
        fileUrl = URL.createObjectURL(await response.blob());
      }
      draw();
      if (preview.status === "indexing") setTimeout(() => { if (state.view === "t-documents" && current?.id === id) selectDocument(id, target).catch(() => {}); }, 2200);
    } catch (e) { toast(friendlyError(e)); }
  };
  const publishCurrent = async () => {
    if (!current || !preview) return;
    const button = $("#doc-publish", root); if (button) button.disabled = true;
    try {
      await api(`/api/teacher/documents/${encodeURIComponent(current.id)}/versions/${encodeURIComponent(preview.id)}/publish`, { method: "POST" });
      toast("已开始发布，正在建立检索索引"); await selectDocument(current.id, preview.id);
    } catch (e) { toast(friendlyError(e)); if (button) button.disabled = false; }
  };
  $("#doc-new", root).onclick = () => { current = null; editor = true; drawDetail(); };
  try { await loadDocuments(); }
  catch (e) { const c = document.createElement("div"); root.innerHTML = ""; root.appendChild(c); errorState(c, friendlyError(e), renderTeacherDocuments); }
}

async function renderTeacherStudents() {
  view().innerHTML = pageHead("TEACHER · 学生管理", "学生管理", "管理全班学生:查看学情、编辑信息、重置或删除。",
    `<button class="da-btn primary sm" id="add-stu"><i data-lucide="user-plus"></i> 开通账号</button>`) +
    `<div class="loading-row"><span class="spin"></span> 载入名册…</div>`;
  icons();
  $("#add-stu") && ($("#add-stu").onclick = () => studentForm());
  let d;
  try { d = await api("/api/teacher/students"); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderTeacherStudents); return; }
  const rows = d.students.map(s => {
    const v = s.avg_mastery || 0, cls = v === 0 ? "zero" : (v < 60 ? "weak" : "");
    return `<div class="stu-row">
      <span class="stu-dot">${escapeHtml((s.name || "?").slice(0, 1))}</span>
      <div class="stu-id"><div class="stu-name">${escapeHtml(s.name)} ${s.state ? stateBadge(s.state) : ""}</div><div class="stu-no">账号 ${escapeHtml(s.username || "—")} · 学号 ${escapeHtml(s.student_no || "—")}</div></div>
      <div class="stu-bar"><span class="mbar ${cls}"><span data-w="${v}"></span></span><span class="mval ${v < 60 && v > 0 ? "weak" : ""}">${v ? v.toFixed(0) : "—"}</span></div>
      <div class="stu-stat"><span>已学 ${s.topics_studied}</span><span>测评 ${s.quizzes_done}</span><span>${s.last_active ? timeago(s.last_active) : "未活跃"}</span></div>
      <div class="stu-act">
        <button class="da-btn ghost sm" data-view="${s.id}" title="查看"><i data-lucide="eye"></i></button>
        <button class="da-btn ghost sm" data-edit="${s.id}" title="编辑"><i data-lucide="pencil"></i></button>
        <button class="da-btn ghost sm" data-reset="${s.id}" title="重置学情"><i data-lucide="rotate-ccw"></i></button>
        <button class="da-btn ghost sm" data-del="${s.id}" title="删除"><i data-lucide="trash-2"></i></button>
      </div></div>`;
  }).join("");
  const meta = `<div class="page-head-actions"><button class="da-btn ghost sm" id="assign-btn"><i data-lucide="clipboard-list"></i> 布置作业</button><button class="da-btn ghost sm" id="csv-btn"><i data-lucide="download"></i> 导出</button><button class="da-btn primary sm" id="add-stu"><i data-lucide="user-plus"></i> 开通账号</button></div>`;
  view().innerHTML = pageHead("TEACHER · 学生管理", "学生管理", "管理全班学生:查看学情、编辑信息、重置或删除。", meta) +
    `<div class="panel"><div class="panel-body" style="padding:6px 16px">${rows}</div></div>`;
  requestAnimationFrame(() => view().querySelectorAll(".mbar > span[data-w]").forEach(x => x.style.width = x.dataset.w + "%"));
  const byId = Object.fromEntries(d.students.map(s => [s.id, s]));
  $("#add-stu").onclick = () => studentForm();
  $("#assign-btn").onclick = () => assignModal();
  $("#csv-btn").onclick = () => downloadCsv();
  view().querySelectorAll("[data-view]").forEach(b => b.onclick = () => openStudent(b.dataset.view));
  view().querySelectorAll("[data-edit]").forEach(b => b.onclick = () => studentForm(byId[b.dataset.edit]));
  view().querySelectorAll("[data-reset]").forEach(b => b.onclick = () => {
    const s = byId[b.dataset.reset];
    confirmDialog("重置学情", `确定清空「${s.name}」的全部掌握度、对话、测评、收藏与阅读记录?学生档案和个人资料保留。`, async () => {
      try { await api("/api/teacher/student/" + s.id + "/reset", { method: "POST" }); toast("已重置"); renderTeacherStudents(); } catch (e) { toast(friendlyError(e)); }
    }, true);
  });
  view().querySelectorAll("[data-del]").forEach(b => b.onclick = () => {
    const s = byId[b.dataset.del];
    confirmDialog("删除学生", `确定永久删除「${s.name}」及其全部学习数据?此操作不可撤销。`, async () => {
      try { await api("/api/teacher/student/" + s.id, { method: "DELETE" }); toast("已删除"); renderTeacherStudents(); } catch (e) { toast(friendlyError(e)); }
    }, true);
  });
  icons();
}
function studentForm(s) {
  const edit = !!s;
  const m = openModal(`<div class="modal-head"><h3>${edit ? "编辑学生" : "开通学生账号"}</h3></div>
    <div class="modal-body">
      <div class="field"><label>姓名</label><input id="f-name" value="${edit ? escapeHtml(s.name || "") : ""}" placeholder="如 李明"></div>
      <div class="field"><label>学号</label><input id="f-no" value="${edit ? escapeHtml(s.student_no || "") : ""}" placeholder="如 2023210007"></div>
      <div class="field"><label>账号</label><input id="f-user" value="${edit ? escapeHtml(s.username || "") : ""}" placeholder="学生登录账号(留空则取学号)" autocomplete="off"></div>
      <div class="field"><label>密码${edit ? "(留空则不修改)" : ""}</label><input id="f-pass" type="text" value="" placeholder="${edit ? "重置为新密码" : "留空则默认 888888"}" autocomplete="new-password"></div>
      <div class="field"><label>年级</label><input id="f-grade" value="${edit ? escapeHtml(s.grade || "本科 2023 级") : "本科 2023 级"}"></div>
      <div class="field"><label>专业</label><input id="f-major" value="${edit ? escapeHtml(s.major || "人工智能") : "人工智能"}"></div>
    </div>
    <div class="modal-foot"><button class="da-btn ghost" id="m-cancel">取消</button><button class="da-btn primary" id="m-save">${edit ? "保存" : "开通账号"}</button></div>`);
  $("#m-cancel", m).onclick = closeModal;
  $("#m-save", m).onclick = async () => {
    const body = {
      name: $("#f-name", m).value.trim(), student_no: $("#f-no", m).value.trim(),
      username: $("#f-user", m).value.trim(), password: $("#f-pass", m).value.trim(),
      grade: $("#f-grade", m).value.trim(), major: $("#f-major", m).value.trim(),
    };
    if (!body.name) return toast("请输入姓名");
    try {
      if (edit) await api("/api/teacher/student/" + s.id, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      else await api("/api/teacher/students", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      closeModal(); toast(edit ? "已保存" : `已开通账号「${body.username || body.student_no || body.name}」`); renderTeacherStudents();
    } catch (e) { toast(friendlyError(e)); }
  };
}
function openStudent(sid) { state.viewSid = sid; state.readonly = true; navigate("t-student"); }

async function renderTeacherStudent() {
  if (!state.viewSid) { navigate("t-students"); return; }
  view().innerHTML = `<button class="da-btn ghost sm" id="back-roster" style="margin-bottom:14px"><i data-lucide="arrow-left"></i> 返回学生管理</button><div class="loading-row"><span class="spin"></span> 载入学情…</div>`;
  icons();
  $("#back-roster").onclick = () => navigate("t-students");
  let p, g;
  try { [p, g] = await Promise.all([api("/api/profile"), api("/api/graph")]); }
  catch (e) { const c = document.createElement("div"); view().innerHTML = ""; view().appendChild(c); errorState(c, friendlyError(e), renderTeacherStudent); return; }
  const s = p.summary, st = p.student;
  const metrics = `<div class="metrics">
    ${metric("平均掌握度", s.avg_mastery, "分", "已学知识点", "WEIGHTED")}
    ${metric("已学知识点", s.topics_studied, "/ " + s.topics_total, "进度", "PROGRESS")}
    ${metric("累计提问", s.questions_asked, "", "对话", "TOTAL")}
    ${metric("完成测评", s.quizzes_done, "次", "评价", "TOTAL")}</div>`;
  const weak = (p.weak_topics && p.weak_topics.length) ?
    `<div class="panel accent"><div class="panel-head"><h3 class="panel-title">需重点巩固</h3><span class="coord">PRIORITY</span></div><div class="panel-body">${p.weak_topics.map(t => masteryRow(t, false)).join("")}</div></div>` : "";
  const feed = `<div class="panel"><div class="panel-head"><h3 class="panel-title">最近学习活动</h3><span class="coord">LOG</span></div><div class="panel-body">${renderFeed(p.events)}</div></div>`;
  const diag = `<div class="panel"><div class="panel-head"><h3 class="panel-title">AI 学情诊断</h3><button class="da-btn ghost sm" id="gen-diag"><i data-lucide="stethoscope"></i> 生成</button></div>
    <div class="panel-body" id="diag-body"><p class="page-lede" style="font-size:13px;padding:6px 0">点击「生成」,基于该生学情给出一对一辅导诊断与建议。</p></div></div>`;
  view().innerHTML =
    `<button class="da-btn ghost sm" id="back-roster" style="margin-bottom:14px"><i data-lucide="arrow-left"></i> 返回学生管理</button>
     <div class="ro-banner"><i data-lucide="eye"></i> 正在以只读方式查看 <b>${escapeHtml(st.name)}</b> 的学情</div>
     ${pageHead("STUDENT · 学情明细", escapeHtml(st.name), `账号 ${escapeHtml(st.username || "—")} · ${escapeHtml(st.student_no || "")} · ${escapeHtml(st.major || "")}`, `<span class="coord">只读</span>`)}
     ${metrics}
     ${stateBanner(p.state)}
     <div class="section-head"><h2 class="section-h2">知识图谱</h2><span class="coord">ROADMAP</span></div>
     <div class="roadmap" id="roadmap"></div>
     <div class="section-head"><h2 class="section-h2">学情画像</h2><span class="coord">PROFILE</span></div>
     <div class="dash-grid"><div class="dash-main">${weak}${feed}</div><aside class="dash-side">${stateCard(p.state)}${diag}</aside></div>`;
  $("#back-roster").onclick = () => navigate("t-students");
  state.graph = g; buildRoadmap(g);
  $("#gen-diag").onclick = async () => {
    const body = $("#diag-body"); body.innerHTML = `<div class="loading-row"><span class="spin"></span> 诊断中…</div>`;
    try { const r = await api("/api/teacher/student/" + state.viewSid + "/diagnose"); body.innerHTML = `<p style="font-family:var(--da-font-han);font-size:14px;line-height:1.7;color:var(--da-ink-1)">${escapeHtml(r.text)}</p>`; }
    catch (e) { body.innerHTML = `<p class="coord">生成失败:${escapeHtml(friendlyError(e))}</p>`; }
  };
  requestAnimationFrame(() => view().querySelectorAll(".mbar > span[data-w]").forEach(x => x.style.width = x.dataset.w + "%"));
  bindFeed();   // 让"最近学习活动"里的评价反馈可点击查看(教师只读)
  icons();
}

/* ================= 学生:测评回顾 / 错题本 / 学习报告 ================= */
async function openReview(quizId, sid) {
  // sid 仅在教师从活动流查看某学生测评时传入,经 ?student_id= 让后端按该生解析与校验归属
  const path = "/api/quiz/" + quizId + "/review" + (sid ? "?student_id=" + encodeURIComponent(sid) : "");
  let r; try { r = await api(path); } catch (e) { return toast("载入失败:" + friendlyError(e)); }
  const qs = r.questions.map((q, i) => {
    const res = (r.results || []).find(x => x.id === q.id) || {};
    const ok = q.type === "choice" ? res.correct : (res.score >= 60);
    let detail = "";
    if (q.type === "choice") {
      detail = (q.options || []).map(o => { const v = (o.trim()[0] || "").toUpperCase(); let cls = ""; if (v === q.answer) cls = "correct"; else if (v === (res.your || "").toUpperCase()[0]) cls = "wrong"; return `<div class="opt ${cls}" style="pointer-events:none">${escapeHtml(o)}</div>`; }).join("");
    } else {
      detail = `<div class="expl"><b>你的作答:</b>${escapeHtml(res.your || "(未作答)")}</div>` + (q.reference ? `<div class="expl"><b>参考要点:</b>${escapeHtml(q.reference)}</div>` : "");
    }
    const qt = (r.question_times || {})[q.id];
    const timeChip = (qt != null && qt > 0) ? `<span class="q-time"><i data-lucide="timer"></i>${Math.round(qt)}s</span>` : "";
    return `<div class="quiz-q"><span class="qn">题 ${String(i + 1).padStart(2, "0")}</span><span class="qtype badge tag">${q.type === "choice" ? "单选" : "简答"}</span>${timeChip}<div class="stem">${escapeHtml(q.stem)}</div>${detail}<div class="qresult"><span class="verdict ${ok ? "ok" : "no"}"><i data-lucide="${ok ? "check" : "x"}"></i>${q.type === "choice" ? (ok ? "回答正确" : "回答错误") : ("得分 " + res.score)}</span></div>${res.feedback ? `<div class="expl"><b>点评:</b>${escapeHtml(res.feedback)}</div>` : ""}${q.explanation ? `<div class="expl"><b>解析:</b>${escapeHtml(q.explanation)}</div>` : ""}</div>`;
  }).join("");
  const stateBlock = r.state ? stateBanner(r.state, "本次学习状态") : "";
  const teacherView = !!sid || isTeacher();
  const titlePrefix = teacherView ? "评价反馈" : "测评回顾";
  const redoBtn = teacherView ? "" : `<button class="da-btn primary" id="m-redo"><i data-lucide="rotate-ccw"></i> 再测一次</button>`;
  const m = openModal(`<div class="modal-head"><h3>${titlePrefix} · ${escapeHtml(r.topic_title)} <span class="coord">${r.score}分</span></h3></div><div class="modal-scroll">${stateBlock}${qs}</div><div class="modal-foot"><button class="da-btn ghost" id="m-cancel">关闭</button>${redoBtn}</div>`);
  $("#m-cancel", m).onclick = closeModal;
  const redo = $("#m-redo", m); if (redo) redo.onclick = () => { closeModal(); navigate("quiz", { topic: r.topic_id }); };
  renderMath(m);   // 渲染测评回顾中的 LaTeX 公式
}
async function renderMistakes() {
  const area = $("#quiz-area"); area.innerHTML = `<div class="loading-row"><span class="spin"></span> 载入错题…</div>`;
  let d; try { d = await api("/api/mistakes"); } catch (e) { errorState(area, friendlyError(e), renderMistakes); return; }
  if (!d.groups.length) { area.innerHTML = `<div class="empty" style="padding:44px"><div class="empty-mark"><i data-lucide="party-popper"></i></div><h3>暂无错题</h3><p>你的测评里还没有做错的题,继续保持。</p></div>`; icons(area); return; }
  area.innerHTML = d.groups.map(g => `<div class="panel"><div class="panel-head"><h3 class="panel-title">${escapeHtml(g.topic_title)}</h3><div style="display:flex;gap:6px"><button class="da-btn ghost sm" data-ask="${g.topic_id}"><i data-lucide="message-circle"></i> 问导师</button><button class="da-btn ghost sm" data-quiz="${g.topic_id}"><i data-lucide="rotate-ccw"></i> 再测</button></div></div><div class="panel-body">${g.items.map(it => `<div class="mk-item"><div class="mk-stem">${escapeHtml(it.stem)}</div><div class="mk-ans"><span class="mk-your">你的作答:${escapeHtml(String(it.your || "—"))}</span>${it.answer ? `<span class="mk-right">正确:${escapeHtml(it.answer)}</span>` : ""}</div>${it.explanation ? `<div class="expl">${escapeHtml(it.explanation)}</div>` : (it.feedback ? `<div class="expl">${escapeHtml(it.feedback)}</div>` : "")}</div>`).join("")}</div></div>`).join("");
  area.querySelectorAll("[data-ask]").forEach(b => b.onclick = () => { state.chatTopic = b.dataset.ask; navigate("chat"); });
  area.querySelectorAll("[data-quiz]").forEach(b => b.onclick = () => navigate("quiz", { topic: b.dataset.quiz }));
  icons(area);
  renderMath(area);   // 渲染错题本中的 LaTeX 公式
}
function repSec(title, items, icon) { if (!items || !items.length) return ""; return `<div class="rep-sec"><div class="eyebrow">${title}</div><ul class="rep-list">${items.map(x => `<li><i data-lucide="${icon}"></i><span>${escapeHtml(x)}</span></li>`).join("")}</ul></div>`; }
async function openReport() {
  const m = openModal(`<div class="modal-head"><h3>阶段学习报告</h3></div><div class="modal-scroll" id="rep-body"><div class="loading-row"><span class="spin"></span> 正在生成你的学习报告…</div></div><div class="modal-foot"><button class="da-btn primary" id="m-cancel">关闭</button></div>`);
  $("#m-cancel", m).onclick = closeModal;
  try {
    const r = await api("/api/report");
    $("#rep-body", m).innerHTML = `<p class="rep-sum">${escapeHtml(r.summary || "")}</p>` +
      repSec("学习亮点", r.highlights, "check") + repSec("仍需加强", r.weak, "alert-triangle") + repSec("下一步建议", r.suggestions, "arrow-right");
    icons(m);
  } catch (e) { $("#rep-body", m).innerHTML = `<p class="coord">生成失败:${escapeHtml(friendlyError(e))}</p>`; }
}

/* ================= 教师:知识点下钻 / 布置作业 / 导出 ================= */
async function openTopicBreakdown(topicId) {
  let d; try { d = await api("/api/teacher/topic/" + topicId); } catch (e) { return toast(friendlyError(e)); }
  const rows = d.students.map(s => `<button class="mrow clickable" data-sid="${s.id}"><span class="mname">${escapeHtml(s.name)}</span><span class="mbar ${s.status === "weak" ? "weak" : (s.attempts === 0 ? "zero" : "")}"><span data-w="${s.score}"></span></span><span class="mval ${s.status === "weak" ? "weak" : ""}">${s.attempts ? s.score.toFixed(0) : "未学"}</span></button>`).join("");
  const scrim = document.createElement("div"); scrim.className = "drawer-scrim"; scrim.id = "drawer-scrim";
  scrim.innerHTML = `<aside class="drawer" role="dialog" aria-label="知识点下钻"><div class="drawer-head"><div><span class="badge diff"><span class="dot"></span>${d.difficulty}</span><h3 class="drawer-title">${escapeHtml(d.title)}</h3><div class="drawer-en">${escapeHtml(d.title_en || "")}</div></div><button class="da-btn ghost icon" id="drawer-close" aria-label="关闭"><i data-lucide="x"></i></button></div>
    <div class="drawer-sec"><div class="kpi-line"><span>班均 <b>${d.avg}</b></span><span>已学 <b>${d.studied}</b></span><span>已掌握 <b>${d.mastered}</b></span><span>薄弱 <b>${d.weak}</b></span></div></div>
    <div class="drawer-sec"><span class="h">逐生掌握(弱者在前)</span>${rows}</div></aside>`;
  document.body.appendChild(scrim); lockScroll(true); icons(scrim);
  requestAnimationFrame(() => scrim.querySelectorAll(".mbar > span[data-w]").forEach(s => s.style.width = s.dataset.w + "%"));
  scrim.onclick = (e) => { if (e.target === scrim) closeDrawer(); };
  $("#drawer-close", scrim).onclick = closeDrawer;
  scrim.querySelectorAll(".mrow.clickable").forEach(b => b.onclick = () => { closeDrawer(); openStudent(b.dataset.sid); });
  document.addEventListener("keydown", drawerEsc);
}
async function assignModal() {
  let topics, students;
  try {
    const [topicData, roster] = await Promise.all([
      state.tTopics ? Promise.resolve({ topics: state.tTopics }) : api("/api/topics"),
      api("/api/teacher/students"),
    ]);
    topics = topicData.topics;
    students = roster.students;
    state.tTopics = topics;
  } catch (e) { return toast(friendlyError(e)); }
  const opts = topics.map(t => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.title)}</option>`).join("");
  const choices = students.map(s => `<label class="assignment-student">
    <input type="checkbox" name="as-student" value="${escapeHtml(s.id)}">
    <span><span class="assignment-student-name">${escapeHtml(s.name)}</span><span class="assignment-student-no">学号 ${escapeHtml(s.student_no || "—")} · 账号 ${escapeHtml(s.username || "—")}</span></span>
  </label>`).join("");
  const m = openModal(`<div class="modal-head"><h3>布置测评任务</h3></div><div class="modal-body">
    <div class="field"><label>知识点</label><select id="as-topic">${opts}</select></div>
    <div class="field"><label>题量</label><select id="as-n"><option>4</option><option selected>5</option><option>6</option></select></div>
    <div class="field"><label for="as-scope">布置对象</label><select id="as-scope"><option value="all">全班学生</option><option value="selected">指定学生</option></select></div>
    <fieldset id="as-students" class="assignment-students" hidden>
      <legend>选择学生（可多选）</legend>
      <div class="assignment-student-list">${choices || '<p class="coord">暂无学生，请先开通学生账号。</p>'}</div>
      <p id="as-error" class="assignment-error" role="alert" hidden>请至少选择一名学生</p>
    </fieldset>
  </div><div class="modal-foot"><button class="da-btn ghost" id="m-cancel">取消</button><button class="da-btn primary" id="m-assign"><i data-lucide="send"></i> 布置</button></div>`);
  const selectedIds = () => Array.from(m.querySelectorAll('input[name="as-student"]:checked'), input => input.value);
  const scope = $("#as-scope", m), error = $("#as-error", m), submit = $("#m-assign", m);
  scope.onchange = () => {
    $("#as-students", m).hidden = scope.value !== "selected";
    error.hidden = true;
  };
  $("#as-students", m).onchange = () => { if (selectedIds().length) error.hidden = true; };
  $("#m-cancel", m).onclick = closeModal;
  submit.onclick = async () => {
    const body = { topic_id: $("#as-topic", m).value, n: parseInt($("#as-n", m).value, 10) };
    if (scope.value === "selected") {
      body.student_ids = selectedIds();
      if (!body.student_ids.length) {
        error.hidden = false;
        (m.querySelector('input[name="as-student"]') || scope).focus();
        return toast("请至少选择一名学生");
      }
    }
    submit.disabled = true;
    try { const r = await api("/api/teacher/assignments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); closeModal(); toast(`已向 ${r.assigned} 名学生布置《${r.topic}》`); }
    catch (e) { toast(friendlyError(e)); }
    finally { submit.disabled = false; }
  };
}
async function downloadCsv() {
  try { const r = await fetch("/api/teacher/export.csv", { headers: authHeaders() }); const blob = await r.blob(); const u = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = u; a.download = "班级名册.csv"; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(u); toast("已导出 CSV"); }
  catch (e) { toast("导出失败"); }
}

/* ---------------- 启动 ---------------- */
async function boot() {
  trackViewport();
  $("#hamburger").onclick = () => { $(".app").classList.contains("nav-open") ? closeNav() : openNav(); };
  $("#nav-scrim").onclick = closeNav;
  $("#org").onclick = () => { closeNav(); if (!isTeacher()) navigate("about"); };
  $("#avatar").onclick = () => { if (!isTeacher()) navigate("about"); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNav(); });
  window.onpopstate = () => { if (!state.identity) return; const v = (location.hash || "").slice(1); renderView(allowedView(VIEWS[v] ? v : defaultView())); };

  try {
    const h = await api("/api/health"); state.health = h;
    const fe = $("#foot-engine"); if (fe) fe.textContent = "引擎 " + (h.model || "Gemini");
    $("#idx-state").textContent = h.index_ready ? "IDX·READY" : "IDX·…";
  } catch (e) {
    const live = $("#live"); if (live) { live.style.background = "var(--da-ink-4)"; live.style.animation = "none"; live.setAttribute("aria-label", "服务离线"); }
    $("#idx-state").textContent = "OFFLINE";
  }
  state.identity = loadIdentity();
  if (state.identity?.role === 'student') {
    try { await api('/api/session'); } catch { state.identity = null; sessionStorage.removeItem(identityKey); }
  }
  if (entryRole && state.identity?.role !== entryRole) state.identity = null;
  if (state.identity) enterApp(); else showGate();
}
boot();
