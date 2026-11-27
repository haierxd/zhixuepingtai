<script setup lang="ts">
import { onMounted, ref } from 'vue';
import LearningWorkspace from './LearningWorkspace.vue';

const role = location.pathname.startsWith('/teacher') ? 'teacher' : location.pathname.startsWith('/student') ? 'student' : '';
const active = ref('');
const student = ref<{ sid: string; name: string; token: string } | null>(null);
const target = ref<{ id: string; anchor?: string; page?: number } | null>(null);
onMounted(async () => {
  if (!role) return;
  window.addEventListener('zx-view', ((event: CustomEvent) => {
    active.value = event.detail.view;
    student.value = event.detail.identity?.role === 'student' ? event.detail.identity : null;
    target.value = event.detail.target || null;
  }) as EventListener);
  // @ts-expect-error Existing native views are reused as a single business module.
  await import('../../web/app.js');
});
</script>

<template>
  <main v-if="!role" class="portal">
    <a class="portal-brand" href="/"><span class="brand-mark">智</span>智学</a>
    <div class="eyebrow">围绕资料 · 自主学习</div>
    <h1>从一份资料开始，<br />把知识学明白。</h1>
    <p>阅读、提问、自测与复习，连接每一次学习。</p>
    <div class="portal-roles">
      <a href="/student/" class="portal-role"><span class="portal-number">01 / STUDENT</span><h2>学生学习空间 <span>↗</span></h2><p>我的资料 · AI 辅导 · 自测复练<br />知识图谱 · 错题与学习记录</p><strong>进入学生端 →</strong></a>
      <a href="/teacher/" class="portal-role teacher"><span class="portal-number">02 / TEACHER</span><h2>教师教学空间 <span>↗</span></h2><p>班级学情 · 学生管理 · 课程资料<br />作业管理 · 教学建议与数据导出</p><strong>进入教师端 →</strong></a>
    </div>
    <footer>智学 · 个性化学习指导与评价</footer>
  </main>
  <template v-else>
    <div class="app">
      <aside class="sidebar" aria-label="主导航">
        <div class="brand"><div class="brand-mark">智</div><div><div class="brand-zh">智学</div><div class="brand-en">{{ role === 'teacher' ? 'TEACHER WORKSPACE' : 'STUDENT WORKSPACE' }}</div></div></div>
        <nav class="nav" id="nav" aria-label="功能导航"></nav>
        <div class="nav-spacer"></div><nav class="nav" id="nav-bottom"></nav>
        <button class="org" id="org" aria-label="账户与设置"><div class="org-dot">{{ role === 'teacher' ? '师' : '学' }}</div><div class="org-info"><div class="org-name">{{ role === 'teacher' ? '教师端' : '学生端' }}</div><div class="org-plan">独立工作空间</div></div><i data-lucide="chevron-right"></i></button>
        <div class="side-foot da-coord">智学 · {{ role === 'teacher' ? '教师端' : '学生端' }}</div>
      </aside>
      <div class="col">
        <div class="topbar"><div class="topbar-left"><button class="da-btn ghost sm hamburger" id="hamburger" aria-label="打开菜单" aria-controls="nav" aria-expanded="false"><i data-lucide="menu"></i></button><div class="crumbs" id="crumbs"></div></div><div class="topbar-right"><span class="coord">{{ role === 'teacher' ? '教师端' : '学生端' }}</span><div class="telemetry"><span class="coord" id="idx-state">连接中</span><span class="da-live" id="live" role="status"></span></div><button class="avatar" id="avatar" aria-label="账户与设置">{{ role === 'teacher' ? '师' : '学' }}</button></div></div>
        <main id="view" class="main" v-show="!['learning', 'records'].includes(active)" aria-live="polite"></main>
        <LearningWorkspace v-if="student && ['learning', 'records'].includes(active)" :identity="student" :mode="active" :target="target" />
        <footer class="app-footer" id="app-footer"><span class="da-coord">智学 · 学习与教学工作空间</span><span class="foot-sep">/</span><span class="da-coord" id="foot-engine"></span></footer>
      </div>
    </div>
    <div id="gate" class="gate"></div><div id="nav-scrim" aria-hidden="true"></div><div id="sr-status" class="sr-only" role="status" aria-live="polite"></div>
  </template>
</template>
