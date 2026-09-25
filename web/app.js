/**
 * 考研数学《880》智能拼好卷 & 错题标练系统 - 核心交互控制器
 * 全面支持数学一 (23章·1121题)、数学二 (12章·929题)、数学三 (21章·1028题) 题库切换与全流程操作
 */

// Global State Store
const state = {
  currentSubject: '数学一',
  currentView: 'assemble',
  currentMode: '10-6-6',
  currentPaper: null,
  currentBundle: null,
  currentWrongPaper: null,
  initData: null,
  markedChapterQuestions: [],
};

// DOM References
const elements = {
  globalSubjectSelector: document.getElementById('globalSubjectSelector'),
  currentSubjectBadge: document.getElementById('currentSubjectBadge'),
  headerWrongCount: document.getElementById('headerWrongCount'),
  themeToggleBtn: document.getElementById('themeToggleBtn'),
  navTabs: document.querySelectorAll('.nav-tab'),
  viewPanels: document.querySelectorAll('.view-panel'),
  
  // Workspace 1
  modeCards: document.querySelectorAll('.mode-card'),
  sliderBasic: document.getElementById('sliderBasic'),
  sliderComp: document.getElementById('sliderComp'),
  sliderAdv: document.getElementById('sliderAdv'),
  valBasic: document.getElementById('valBasic'),
  valComp: document.getElementById('valComp'),
  valAdv: document.getElementById('valAdv'),
  tagSelect: document.getElementById('tagSelect'),
  btnGeneratePaper: document.getElementById('btnGeneratePaper'),
  btnResetCycle: document.getElementById('btnResetCycle'),
  bundleSwitcher: document.getElementById('bundleSwitcher'),
  paperDisplayTitle: document.getElementById('paperDisplayTitle'),
  paperMetaBadges: document.getElementById('paperMetaBadges'),
  paperQuestionsList: document.getElementById('paperQuestionsList'),
  btnDownloadClean: document.getElementById('btnDownloadClean'),
  btnDownloadSolved: document.getElementById('btnDownloadSolved'),
  btnArchiveLocal: document.getElementById('btnArchiveLocal'),
  cbToggleAllAnswers: document.getElementById('cbToggleAllAnswers'),
  
  // Workspace 2
  markerChapterSelect: document.getElementById('markerChapterSelect'),
  markerDiffSelect: document.getElementById('markerDiffSelect'),
  markerTypeSelect: document.getElementById('markerTypeSelect'),
  markerSearchInput: document.getElementById('markerSearchInput'),
  batchNumInput: document.getElementById('batchNumInput'),
  btnBatchMark: document.getElementById('btnBatchMark'),
  btnBatchUnmark: document.getElementById('btnBatchUnmark'),
  markerQuestionsList: document.getElementById('markerQuestionsList'),
  
  // Workspace 3
  wpTotalCount: document.getElementById('wpTotalCount'),
  wpChaptersCount: document.getElementById('wpChaptersCount'),
  btnGenerateWrongPaper: document.getElementById('btnGenerateWrongPaper'),
  btnExportWrongJson: document.getElementById('btnExportWrongJson'),
  wrongPaperContainer: document.getElementById('wrongPaperContainer'),
  
  // Workspace 4
  radarCoveragePercent: document.getElementById('radarCoveragePercent'),
  radarProgressBar: document.getElementById('radarProgressBar'),
  radarChaptersMatrix: document.getElementById('radarChaptersMatrix'),
  discAdvList: document.getElementById('discAdvList'),
  discLinList: document.getElementById('discLinList'),
  discProbList: document.getElementById('discProbList'),
  
  // Modal & Toast
  aiModal: document.getElementById('aiModal'),
  btnCloseAiModal: document.getElementById('btnCloseAiModal'),
  aiQuestionStem: document.getElementById('aiQuestionStem'),
  aiSolutionContent: document.getElementById('aiSolutionContent'),
  toastContainer: document.getElementById('toastContainer'),
};

// =========================================================================
// 1. App Initialization
// =========================================================================
async function initApp() {
  setupEventListeners();
  await loadInitData();
  await generatePaper();
}

// 顶部题库概况：各书题数 + 答案覆盖率
function updateBankStats(data) {
  const pill = document.getElementById('bankStatText');
  if (!pill) return;
  const books = data.books || [];
  if (!books.length) {
    pill.textContent = `${data.totalQuestions} 题`;
    return;
  }
  const parts = books.map(b => `${b.name.replace(/[《》]/g, '')} ${b.count}`);
  const cov = typeof data.answerCoverage === 'number' ? data.answerCoverage : 0;
  pill.textContent = `共 ${data.totalQuestions} 题（${parts.join(' + ')}）· 答案 ${cov}%`;
}

// 科目下拉：把真实题数写进选项文本
function updateSubjectOptions(data) {
  const sel = document.getElementById('globalSubjectSelector');
  if (!sel || !data) return;
  const current = sel.value;
  sel.dataset.stats = JSON.stringify({
    [data.currentSubject]: data.totalQuestions
  });
  Array.from(sel.options).forEach(opt => {
    const n = sel.dataset.stats && JSON.parse(sel.dataset.stats)[opt.value];
    if (n) opt.textContent = `📐 ${opt.value} (${n}题)`;
  });
  sel.value = current;
}

async function loadInitData() {
  try {
    const res = await fetch(`/api/init?subject=${encodeURIComponent(state.currentSubject)}`);
    const data = await res.json();
    state.initData = data;
    
    // Update Header Badges
    if (elements.headerWrongCount) {
      elements.headerWrongCount.textContent = data.wrongTotal;
    }
    if (elements.currentSubjectBadge) {
      elements.currentSubjectBadge.textContent = `当前科目: ${data.currentSubject} (${data.totalChapters}章·${data.totalQuestions}题)`;
    }

    // 题库构成与答案覆盖率：直接来自后端真实统计，不再写死
    updateBankStats(data);
    
    // Populate Marker Chapters Dropdown
    if (elements.markerChapterSelect) {
      elements.markerChapterSelect.innerHTML = data.chapters.map(c => 
        `<option value="${c.name}">${c.name} (${c.count}题${c.wrongCount > 0 ? ' · 错' + c.wrongCount : ''})</option>`
      ).join('');
    }

    // Render Radar View
    renderRadarView(data);
    
    // Load initial chapter questions for marker view
    if (data.chapters && data.chapters.length > 0) {
      await loadMarkerQuestions();
    }
    
    // Update wrong pool metrics
    await updateWrongPoolStats();
    updateSubjectOptions(data);
  } catch (err) {
    console.error('Failed to init data:', err);
    showToast('❌ 加载题库数据失败，请刷新重试');
  }
}

// =========================================================================
// 1.5 考场模式：全屏 + 横向翻页 + 答题卡 + 倒计时 + 交卷判分
// =========================================================================
const exam = {
  open: false,
  paper: null,
  subject: '数学一',
  index: 0,
  answers: {},        // {qid: 用户答案}
  flags: new Set(),   // 标记的题号
  minutes: 180,
  endsAt: 0,
  timerId: null,
  submitted: false,
};

const examEl = {
  overlay: () => document.getElementById('examOverlay'),
  track: () => document.getElementById('examTrack'),
  title: () => document.getElementById('examTitle'),
  timer: () => document.getElementById('examTimer'),
  progress: () => document.getElementById('examProgress'),
  sheet: () => document.getElementById('examSheet'),
  sheetGrid: () => document.getElementById('examSheetGrid'),
  resultOverlay: () => document.getElementById('examResultOverlay'),
  resultBody: () => document.getElementById('examResultBody'),
};

function examQuestions() {
  if (!exam.paper) return [];
  return exam.paper.allQuestions || exam.paper.questions || [];
}

function openExam(paper, minutes = 180) {
  const qs = (paper && (paper.allQuestions || paper.questions)) || [];
  if (!qs.length) {
    showToast('⚠️ 先生成一张卷子再进考场');
    return;
  }
  exam.paper = paper;
  exam.subject = state.currentSubject || '数学一';
  exam.index = 0;
  exam.answers = {};
  exam.flags = new Set();
  exam.submitted = false;
  exam.minutes = minutes;
  exam.endsAt = Date.now() + minutes * 60 * 1000;

  examEl.title().textContent = `${paper.title || '智能拼好卷'} · 共 ${qs.length} 题`;
  examEl.track().innerHTML = qs.map((q, i) => renderExamPage(q, i)).join('');
  examEl.overlay().hidden = false;
  document.body.style.overflow = 'hidden';
  exam.open = true;

  renderExamSheet();
  // 宽屏（平板横屏 / 桌面）默认展开答题卡双栏；窄屏保持浮层，不挤占题面
  examEl.sheet().hidden = !window.matchMedia('(min-width: 1024px)').matches;
  bindExamInputs();
  goExamPage(0, true);
  startExamTimer();
}

function closeExam() {
  stopExamTimer();
  examEl.overlay().hidden = true;
  examEl.resultOverlay().hidden = true;
  document.body.style.overflow = '';
  exam.open = false;
  if (document.fullscreenElement) document.exitFullscreen?.();
}

function renderExamPage(q, i) {
  const type = q.type || q.question_type || '';
  const opts = q.options || [];
  let body = '';
  if (type.includes('选择') && opts.length) {
    body = `<div class="exam-options">${opts.map((o, k) => {
      const key = String.fromCharCode(65 + k);
      return `<div class="exam-opt" data-qid="${q.id}" data-key="${key}">
                <span class="opt-key">${key}.</span><span>${o.replace(/^\s*[A-D]\s*[.．、]\s*/, '')}</span>
              </div>`;
    }).join('')}</div>`;
  } else if (type.includes('填空')) {
    body = `<input class="exam-fill-input" data-qid="${q.id}" placeholder="填入你的答案（可用 LaTeX，如 $e^{2x}$）" />`;
  } else {
    body = `<textarea class="exam-solution-input" data-qid="${q.id}" placeholder="写出你的解答过程"></textarea>`;
  }
  return `<section class="exam-page" data-index="${i}">
    <div class="exam-q-head">
      <span class="exam-q-index">第 ${i + 1} 题</span>
      <span>${q.chapter || ''}</span>
      <span>${q.difficulty || ''}</span>
      <span>${type}</span>
      <span style="opacity:.6">${q.id}</span>
    </div>
    <div class="exam-q-stem">${q.stem || ''}</div>
    ${body}
  </section>`;
}

function bindExamInputs() {
  examEl.track().querySelectorAll('.exam-opt').forEach(el => {
    el.addEventListener('click', () => {
      const qid = el.dataset.qid;
      exam.answers[qid] = el.dataset.key;
      el.parentElement.querySelectorAll('.exam-opt')
        .forEach(o => o.classList.toggle('selected', o === el));
      updateExamSheetCell(qid);
      updateExamProgress();
    });
  });
  examEl.track().querySelectorAll('.exam-fill-input, .exam-solution-input').forEach(el => {
    el.addEventListener('input', () => {
      exam.answers[el.dataset.qid] = el.value.trim();
      updateExamSheetCell(el.dataset.qid);
      updateExamProgress();
    });
  });
}

function renderExamSheet() {
  const qs = examQuestions();
  examEl.sheetGrid().innerHTML = qs.map((q, i) =>
    `<div class="exam-sheet-cell" data-qid="${q.id}" data-index="${i}" title="第 ${i + 1} 题">${i + 1}</div>`
  ).join('');
  examEl.sheetGrid().querySelectorAll('.exam-sheet-cell').forEach(cell => {
    cell.addEventListener('click', () => goExamPage(parseInt(cell.dataset.index, 10)));
  });
}

function updateExamSheetCell(qid) {
  const cell = examEl.sheetGrid().querySelector(`[data-qid="${qid}"]`);
  if (!cell) return;
  const answered = (exam.answers[qid] || '').toString().length > 0;
  cell.classList.toggle('done', answered);
}

function updateExamProgress() {
  const qs = examQuestions();
  const done = qs.filter(q => (exam.answers[q.id] || '').toString().length > 0).length;
  examEl.progress().textContent = `已答 ${done} / ${qs.length}`;
}

function goExamPage(i, instant = false) {
  const qs = examQuestions();
  if (!qs.length) return;
  exam.index = Math.max(0, Math.min(i, qs.length - 1));
  const page = examEl.track().children[exam.index];
  if (!page) return;
  const track = examEl.track();
  if (instant) track.style.scrollBehavior = 'auto';
  track.scrollTo({ left: page.offsetLeft, behavior: instant ? 'auto' : 'smooth' });
  if (instant) requestAnimationFrame(() => { track.style.scrollBehavior = 'smooth'; });

  examEl.sheetGrid().querySelectorAll('.exam-sheet-cell')
    .forEach(c => c.classList.toggle('current', parseInt(c.dataset.index, 10) === exam.index));
}

function startExamTimer() {
  stopExamTimer();
  const tick = () => {
    const left = Math.max(0, exam.endsAt - Date.now());
    const m = Math.floor(left / 60000);
    const s = Math.floor((left % 60000) / 1000);
    const el = examEl.timer();
    el.textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    el.classList.toggle('warning', left <= 15 * 60000 && left > 5 * 60000);
    el.classList.toggle('danger', left <= 5 * 60000);
    if (left <= 0) {
      stopExamTimer();
      showToast('⏰ 时间到，自动交卷');
      submitExam();
    }
  };
  tick();
  exam.timerId = setInterval(tick, 1000);
}

function stopExamTimer() {
  if (exam.timerId) clearInterval(exam.timerId);
  exam.timerId = null;
}

async function submitExam() {
  if (exam.submitted) return;
  exam.submitted = true;
  stopExamTimer();
  try {
    const res = await fetch('/api/submit-answers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: exam.subject, answers: exam.answers }),
    });
    const data = await res.json();
    renderExamResult(data);
  } catch (err) {
    showToast('❌ 交卷失败，请检查服务是否正常');
    exam.submitted = false;
  }
}

function renderExamResult(data) {
  const map = {};
  (data.results || []).forEach(r => { map[r.id] = r; });
  const qs = examQuestions();
  const items = qs.map((q, i) => {
    const r = map[q.id] || {};
    const status = r.status || 'ungraded';
    const label = { correct: '✅ 正确', wrong: '❌ 错误', blank: '⚠️ 未作答', ungraded: '❔ 暂无标准答案' }[status];
    const detail = status === 'ungraded'
      ? '<div class="exam-result-answer">题库还没有这道题的答案/解析 —— 可以在「答案共享中心」生成模板补上，或点 AI 答疑。</div>'
      : `<div class="exam-result-answer">
           你的答案：<code>${escapeHtml(r.userAnswer || '（空）')}</code><br/>
           参考答案：<code>${escapeHtml(r.standardAnswer || '—')}</code>
           ${r.solution ? `<br/>解析：${escapeHtml(r.solution)}` : ''}
         </div>`;
    return `<div class="exam-result-item ${status}">
      <div><strong>第 ${i + 1} 题</strong> · ${label}</div>
      ${detail}
    </div>`;
  }).join('');

  examEl.resultBody().innerHTML = `
    <div class="exam-score-card">
      <div>
        <div class="exam-score-num">${data.score ?? 0}</div>
        <div style="opacity:.7;font-size:13px">得分（已判题）</div>
      </div>
      <div>
        共 ${data.total} 题 · 已判 ${data.graded} 题 · 答对 ${data.correct} 题<br/>
        <span style="opacity:.75">未判 ${data.ungraded} 题（题库暂无答案）</span>
      </div>
      <div>
        已自动加入错题本：<strong>${data.markedWrong ?? 0}</strong> 题<br/>
        <span style="opacity:.75">重练答对、已移出待练池：<strong>${data.masteredCount ?? 0}</strong> 题</span>
      </div>
    </div>
    ${items}
  `;
  examEl.resultOverlay().hidden = false;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function setupExamControls() {
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('click', fn); };
  on('examExitBtn', closeExam);
  on('examPrevBtn', () => goExamPage(exam.index - 1));
  on('examNextBtn', () => goExamPage(exam.index + 1));
  on('examSubmitBtn', () => {
    const done = examQuestions().filter(q => (exam.answers[q.id] || '').toString().length).length;
    const total = examQuestions().length;
    if (done < total && !confirm(`还有 ${total - done} 题未作答，确定交卷？`)) return;
    submitExam();
  });
  on('examSheetBtn', () => { examEl.sheet().hidden = !examEl.sheet().hidden; });
  on('examSheetClose', () => { examEl.sheet().hidden = true; });
  on('examResultClose', () => { examEl.resultOverlay().hidden = true; });
  on('examFullBtn', () => {
    if (!document.fullscreenElement) examEl.overlay().requestFullscreen?.().catch(() => {});
    else document.exitFullscreen?.();
  });
  on('examFlagBtn', () => {
    const q = examQuestions()[exam.index];
    if (!q) return;
    if (exam.flags.has(q.id)) exam.flags.delete(q.id); else exam.flags.add(q.id);
    const cell = examEl.sheetGrid().querySelector(`[data-qid="${q.id}"]`);
    if (cell) cell.classList.toggle('flag', exam.flags.has(q.id));
  });
  // 键盘流：← → 翻页；A-D / 1-4 选选项；Ctrl+Enter 交卷；F 全屏；M 标记本题
  document.addEventListener('keydown', (e) => {
    if (!exam.open) return;
    if (!examEl.resultOverlay().hidden) {
      if (e.key === 'Escape') examEl.resultOverlay().hidden = true;
      return;
    }
    const t = e.target;
    const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);

    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('examSubmitBtn')?.click();
      return;
    }
    if (typing) return;   // 正在填答案时不劫持字母/数字键

    if (e.key === 'ArrowLeft') { goExamPage(exam.index - 1); return; }
    if (e.key === 'ArrowRight') { goExamPage(exam.index + 1); return; }

    if (/^[a-dA-D1-4]$/.test(e.key)) {
      const key = /[1-4]/.test(e.key) ? String.fromCharCode(64 + Number(e.key)) : e.key.toUpperCase();
      const page = examEl.track().children[exam.index];
      const opt = page && page.querySelector(`.exam-opt[data-key="${key}"]`);
      if (opt) { opt.click(); e.preventDefault(); }
      return;
    }
    if (e.key === 'f' || e.key === 'F') document.getElementById('examFullBtn')?.click();
    else if (e.key === 'm' || e.key === 'M') document.getElementById('examFlagBtn')?.click();
  });
  // 横滑一页后同步当前题号（用于答题卡高亮与进度）
  const track = examEl.track();
  if (track) {
    let t = null;
    track.addEventListener('scroll', () => {
      clearTimeout(t);
      t = setTimeout(() => {
        const w = track.clientWidth || 1;
        const idx = Math.round(track.scrollLeft / w);
        // 只在确实翻到别的页时才回写，否则会和平滑滚动互相触发、来回抖
        if (idx !== exam.index) goExamPage(idx);
      }, 90);
    });
  }
}

// =========================================================================
// 2. Navigation & Themes
// =========================================================================
function setupEventListeners() {
  // 考场模式控件 + 进入按钮
  setupExamControls();
  const enterExam = document.getElementById('enterExamBtn');
  if (enterExam) {
    enterExam.addEventListener('click', () => {
      if (!state.currentPaper) { showToast('⚠️ 先生成一张卷子'); return; }
      openExam(state.currentPaper, 180);
    });
  }

  // Subject Switcher
  if (elements.globalSubjectSelector) {
    elements.globalSubjectSelector.addEventListener('change', async (e) => {
      state.currentSubject = e.target.value;
      showToast(`⚡ 已切换至考研 ${state.currentSubject} 题库`);
      await loadInitData();
      await generatePaper();
    });
  }

  // Tabs Navigation
  elements.navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const view = tab.dataset.view;
      switchView(view);
    });
  });

  // Theme Toggle（含持久化：刷新后保持上次选择）
  if (elements.themeToggleBtn) {
    try {
      if (localStorage.getItem('pinpaper-theme') === 'light') {
        document.body.classList.add('theme-light');
        elements.themeToggleBtn.textContent = '☀️';
      }
    } catch (e) {}
    elements.themeToggleBtn.addEventListener('click', () => {
      document.body.classList.toggle('theme-light');
      const isLight = document.body.classList.contains('theme-light');
      elements.themeToggleBtn.textContent = isLight ? '☀️' : '🌙';
      try {
        localStorage.setItem('pinpaper-theme', isLight ? 'light' : 'dark');
      } catch (e) {}
    });
  }

  // Workspace 1 Mode Cards
  elements.modeCards.forEach(card => {
    card.addEventListener('click', () => {
      elements.modeCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      state.currentMode = card.dataset.mode;
    });
  });

  // Sliders
  if (elements.sliderBasic) {
    elements.sliderBasic.addEventListener('input', (e) => elements.valBasic.textContent = e.target.value);
    elements.sliderComp.addEventListener('input', (e) => elements.valComp.textContent = e.target.value);
    elements.sliderAdv.addEventListener('input', (e) => elements.valAdv.textContent = e.target.value);
  }

  // Generate Paper Button
  if (elements.btnGeneratePaper) {
    elements.btnGeneratePaper.addEventListener('click', () => generatePaper());
  }
  
  // Reset Cycle Button
  if (elements.btnResetCycle) {
    elements.btnResetCycle.addEventListener('click', async () => {
      await fetch('/api/coverage/reset', { method: 'POST' });
      showToast('🔄 已重置覆盖轮次！');
      await loadInitData();
    });
  }

  // Toggle All Answers Checkbox
  if (elements.cbToggleAllAnswers) {
    elements.cbToggleAllAnswers.addEventListener('change', (e) => {
      const drawers = document.querySelectorAll('.q-solution-drawer');
      drawers.forEach(d => d.style.display = e.target.checked ? 'block' : 'none');
    });
  }

  // PDF Export & Archive Buttons
  if (elements.btnDownloadClean) elements.btnDownloadClean.addEventListener('click', () => downloadPaperFile(false));
  if (elements.btnDownloadSolved) elements.btnDownloadSolved.addEventListener('click', () => downloadPaperFile(true));
  if (elements.btnArchiveLocal) elements.btnArchiveLocal.addEventListener('click', () => archivePaperLocal());

  // Workspace 2 Marker Filters & Actions
  if (elements.markerChapterSelect) elements.markerChapterSelect.addEventListener('change', () => loadMarkerQuestions());
  if (elements.markerDiffSelect) elements.markerDiffSelect.addEventListener('change', () => loadMarkerQuestions());
  if (elements.markerTypeSelect) elements.markerTypeSelect.addEventListener('change', () => loadMarkerQuestions());
  if (elements.markerSearchInput) elements.markerSearchInput.addEventListener('input', debounce(() => loadMarkerQuestions(), 300));
  
  if (elements.btnBatchMark) elements.btnBatchMark.addEventListener('click', () => handleBatchMark(true));
  if (elements.btnBatchUnmark) elements.btnBatchUnmark.addEventListener('click', () => handleBatchMark(false));

  // Workspace 3 Wrong Practice
  if (elements.btnGenerateWrongPaper) elements.btnGenerateWrongPaper.addEventListener('click', () => generateWrongPaper());
  if (elements.btnExportWrongJson) elements.btnExportWrongJson.addEventListener('click', () => exportWrongJson());

  // AI Modal Close
  if (elements.btnCloseAiModal) {
    elements.btnCloseAiModal.addEventListener('click', () => {
      elements.aiModal.style.display = 'none';
    });
  }
}

function switchView(viewName) {
  state.currentView = viewName;
  elements.navTabs.forEach(t => t.classList.toggle('active', t.dataset.view === viewName));
  elements.viewPanels.forEach(p => p.classList.toggle('active', p.id === `view-${viewName}`));
  
  if (viewName === 'marker') {
    loadMarkerQuestions();
  } else if (viewName === 'wrong-practice') {
    updateWrongPoolStats();
  } else if (viewName === 'radar') {
    loadInitData();
  }
}

// =========================================================================
// 3. Paper Generation (Workspace 1)
// =========================================================================
async function generatePaper() {
  if (!elements.btnGeneratePaper) return;
  elements.btnGeneratePaper.disabled = true;
  elements.btnGeneratePaper.innerHTML = '⚡ 正在极速生成试卷...';
  
  try {
    const payload = {
      mode: state.currentMode,
      subject: state.currentSubject,
      tag: elements.tagSelect ? elements.tagSelect.value : '全部',
      diffWeights: {
        '基础': parseFloat(elements.sliderBasic ? elements.sliderBasic.value : 1.0),
        '综合': parseFloat(elements.sliderComp ? elements.sliderComp.value : 1.2),
        '拓展': parseFloat(elements.sliderAdv ? elements.sliderAdv.value : 0.8),
      },
      chapters: state.initData ? state.initData.chapters.map(c => c.name) : undefined,
    };

    const res = await fetch('/api/generate-paper', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.isBundle) {
      state.currentBundle = data;
      state.currentPaper = data.papers[0];
      renderBundleSwitcher(data);
    } else {
      state.currentBundle = null;
      state.currentPaper = data.paper;
      if (elements.bundleSwitcher) elements.bundleSwitcher.style.display = 'none';
    }

    renderPaper(state.currentPaper);
    await loadInitData();
    showToast(`✨ ${state.currentSubject} 试卷已智能生成！`);
  } catch (err) {
    console.error(err);
    showToast('❌ 组卷失败，请重试');
  } finally {
    if (elements.btnGeneratePaper) {
      elements.btnGeneratePaper.disabled = false;
      elements.btnGeneratePaper.innerHTML = '🚀 立即智能生成试卷';
    }
  }
}

function renderBundleSwitcher(bundleData) {
  if (!elements.bundleSwitcher) return;
  elements.bundleSwitcher.style.display = 'flex';
  elements.bundleSwitcher.innerHTML = bundleData.papers.map((p, idx) => `
    <button class="bundle-tab-btn ${idx === 0 ? 'active' : ''}" data-idx="${idx}">
      📄 ${p.title}
    </button>
  `).join('');

  elements.bundleSwitcher.querySelectorAll('.bundle-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      elements.bundleSwitcher.querySelectorAll('.bundle-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const idx = parseInt(btn.dataset.idx);
      state.currentPaper = bundleData.papers[idx];
      renderPaper(state.currentPaper);
    });
  });
}

function renderPaper(paper) {
  if (!paper || !elements.paperQuestionsList) return;
  elements.paperDisplayTitle.textContent = paper.title;
  elements.paperMetaBadges.textContent = `卷号: ${paper.id} · 题量: ${paper.totalCount} 题 (选择: ${paper.choiceQuestions.length}, 填空: ${paper.fillQuestions.length}, 解答: ${paper.solutionQuestions.length})`;

  let html = '';
  let qNum = 1;

  const sections = [
    { title: '一、选择题', list: paper.choiceQuestions },
    { title: '二、填空题', list: paper.fillQuestions },
    { title: '三、解答题', list: paper.solutionQuestions },
  ];

  sections.forEach(sec => {
    if (sec.list.length === 0) return;
    html += `<h3 style="margin:20px 0 10px 0; font-family:var(--font-serif); color:var(--text-primary);">${sec.title}（共 ${sec.list.length} 小题）</h3>`;
    sec.list.forEach(q => {
      html += renderQuestionCard(q, qNum++);
    });
  });

  elements.paperQuestionsList.innerHTML = html;
  attachQuestionCardEvents(elements.paperQuestionsList);
  renderLatexFormulas(elements.paperQuestionsList);
}

function renderQuestionCard(q, indexNum, isWrongView = false) {
  const diffClass = q.difficulty === '基础' ? 'badge-basic' : (q.difficulty === '拓展' ? 'badge-adv' : 'badge-comp');
  const tagsHtml = (q.tags || []).slice(0, 2).map(t => `<span class="q-badge badge-tag">#${escapeHtml(t)}</span>`).join('');
  const optionsHtml = (q.options && q.options.length > 0)
    ? `<div class="q-options-grid">${q.options.map(opt => `<div class="q-option-item">${renderMarkdown(opt)}</div>`).join('')}</div>`
    : '';

  return `
    <div class="q-card ${q.isWrong ? 'is-wrong' : ''}" data-qid="${q.id}">
      <div class="q-header">
        <div class="q-meta-left">
          ${indexNum ? `<span class="q-index-num">${indexNum}.</span>` : ''}
          <span class="q-badge ${diffClass}">[${q.difficulty}]</span>
          <span class="q-badge badge-ch">${q.chapter}</span>
          <span class="q-badge badge-ch">${q.type}</span>
          ${tagsHtml}
          <span class="q-id-code">(ID: ${q.id})</span>
        </div>
        <div>
          ${q.isWrong ? '<span class="q-badge badge-wrong-flag">❌ 已收录在错题本</span>' : ''}
        </div>
      </div>

      <div class="q-stem-content">${renderMarkdown(q.stem)}</div>
      ${optionsHtml}

      <div class="q-actions-bar">
        <div class="q-actions-left">
          <button class="btn-action-sm btn-toggle-wrong ${q.isWrong ? 'active' : ''}" data-qid="${q.id}">
            ${q.isWrong ? '⭐ 取消标错' : '❌ 标记错题'}
          </button>
          <button class="btn-action-sm btn-ai-solve" data-qid="${q.id}">
            🤖 AI 导师拆解
          </button>
        </div>
        <button class="btn-action-sm btn-toggle-ans" data-target="ans-${q.id}">
          🔍 查看答案与避坑
        </button>
      </div>

      <div class="q-solution-drawer" id="ans-${q.id}" style="display:none;">
        <div class="solution-header">
          <strong>【核心考点】</strong> ${(q.coreKnowledge || []).join('、') || '技巧计算'}
        </div>
        ${q.pitfallAnalysis ? `
          <div class="pitfall-box">
            <span class="pitfall-title">⚠️ 名师避坑画像：</span>
            <span>${q.pitfallAnalysis}</span>
          </div>
        ` : ''}
        <div class="answer-row">
          <strong>【参考答案】</strong> <span class="ans-text">${q.answer || '详见解析'}</span>
        </div>
        <div class="solution-body">
          <strong>【详细解析】</strong>
          <div>${renderMarkdown(q.solution || '根据题意计算可得。')}</div>
        </div>
      </div>
    </div>
  `;
}

function attachQuestionCardEvents(container) {
  // Toggle Wrong Button
  container.querySelectorAll('.btn-toggle-wrong').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const qid = btn.dataset.qid;
      const res = await fetch('/api/wrong/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: qid }),
      });
      const data = await res.json();
      
      elements.headerWrongCount.textContent = data.wrongTotal;
      btn.classList.toggle('active', data.isMarked);
      btn.textContent = data.isMarked ? '⭐ 取消标错' : '❌ 标记错题';
      
      const card = btn.closest('.q-card');
      if (card) {
        card.classList.toggle('is-wrong', data.isMarked);
        let flag = card.querySelector('.badge-wrong-flag');
        if (data.isMarked) {
          if (!flag) {
            const span = document.createElement('span');
            span.className = 'q-badge badge-wrong-flag';
            span.textContent = '❌ 已收录在错题本';
            card.querySelector('.q-header > div:last-child').appendChild(span);
          }
        } else {
          if (flag) flag.remove();
        }
      }
      showToast(data.isMarked ? `✓ 已将 ${qid} 加入 880 错题本！` : `✓ 已从错题本移除 ${qid}`);
      await updateWrongPoolStats();
    });
  });

  // Toggle Single Answer
  container.querySelectorAll('.btn-toggle-ans').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const drawer = document.getElementById(targetId);
      if (drawer) {
        const isHidden = drawer.style.display === 'none';
        drawer.style.display = isHidden ? 'block' : 'none';
        renderLatexFormulas(drawer);
      }
    });
  });

  // AI Tutor Call
  container.querySelectorAll('.btn-ai-solve').forEach(btn => {
    btn.addEventListener('click', async () => {
      const qid = btn.dataset.qid;
      const card = btn.closest('.q-card');
      const stem = card.querySelector('.q-stem-content').innerHTML;

      elements.aiModal.style.display = 'flex';
      elements.aiQuestionStem.innerHTML = stem;
      elements.aiSolutionContent.innerHTML = '⚡ 名师大模型正在分步推导逻辑链与避坑归纳，请稍候...';
      renderLatexFormulas(elements.aiQuestionStem);

      try {
        const res = await fetch('/api/ai-solve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: qid, subject: state.currentSubject }),
        });
        const data = await res.json();
        elements.aiSolutionContent.innerHTML = renderMarkdown(data.solution);
        renderLatexFormulas(elements.aiSolutionContent);
      } catch (err) {
        elements.aiSolutionContent.innerHTML = '<span style="color:#f87171;">AI 推导超时或未配置 Key，请检查配置。</span>';
      }
    });
  });
}

// =========================================================================
// 4. Workspace 2: 880 Marker Middle Office
// =========================================================================
async function loadMarkerQuestions() {
  if (!elements.markerChapterSelect) return;
  const chapter = elements.markerChapterSelect.value;
  const diff = elements.markerDiffSelect ? elements.markerDiffSelect.value : '全部';
  const qtype = elements.markerTypeSelect ? elements.markerTypeSelect.value : '全部';
  const kw = elements.markerSearchInput ? elements.markerSearchInput.value : '';

  const url = `/api/questions?subject=${encodeURIComponent(state.currentSubject)}&chapter=${encodeURIComponent(chapter)}&difficulty=${encodeURIComponent(diff)}&type=${encodeURIComponent(qtype)}&keyword=${encodeURIComponent(kw)}`;
  const res = await fetch(url);
  const data = await res.json();

  let html = '';
  data.questions.forEach((q, idx) => {
    html += renderQuestionCard(q, idx + 1);
  });

  if (data.questions.length === 0) {
    html = '<div style="text-align:center; padding:40px; color:var(--text-muted);">暂无匹配题目</div>';
  }

  elements.markerQuestionsList.innerHTML = html;
  attachQuestionCardEvents(elements.markerQuestionsList);
  renderLatexFormulas(elements.markerQuestionsList);
}

async function handleBatchMark(isMark) {
  const chapter = elements.markerChapterSelect.value;
  const numbers = elements.batchNumInput.value.trim();
  if (!numbers) {
    showToast('⚠️ 请在输入框中输入题号，例如：1, 3, 5');
    return;
  }

  const endpoint = isMark ? '/api/wrong/batch-mark' : '/api/wrong/batch-unmark';
  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chapter, numbers, subject: state.currentSubject }),
  });
  const data = await res.json();

  elements.headerWrongCount.textContent = data.wrongTotal;
  elements.batchNumInput.value = '';
  showToast(isMark ? `✓ 成功批量标记 ${data.markedCount} 题！` : `✓ 成功批量移除 ${data.unmarkedCount} 题！`);
  
  await loadMarkerQuestions();
  await updateWrongPoolStats();
}

// =========================================================================
// 5. Workspace 3: Wrong Practice Hub
// =========================================================================
async function updateWrongPoolStats() {
  if (!elements.wpTotalCount) return;
  const res = await fetch(`/api/wrong-pool?subject=${encodeURIComponent(state.currentSubject)}`);
  const data = await res.json();
  
  elements.wpTotalCount.textContent = data.count;
  const chs = new Set(data.questions.map(q => q.chapter));
  elements.wpChaptersCount.textContent = chs.size;
}

async function generateWrongPaper() {
  const res = await fetch(`/api/wrong-pool?subject=${encodeURIComponent(state.currentSubject)}`);
  const data = await res.json();

  if (data.count === 0) {
    showToast('⚠️ 错题本暂无题目，请先在【880 逐题标错中枢】标记错题！');
    return;
  }

  const modeRadio = document.querySelector('input[name="wrongPracticeMode"]:checked').value;
  let questions = [...data.questions];

  if (modeRadio === '10-6-6') {
    questions = questions.slice(0, 22);
  } else if (modeRadio === '5-3-3') {
    questions = questions.slice(0, 11);
  }

  let html = `
    <div class="paper-toolbar glass-panel" style="margin-top:20px;">
      <div>
        <h3 class="paper-title">🎯 考研数学《880》纯错题专项重练卷</h3>
        <span class="paper-meta-sub">共 ${questions.length} 题纯错题</span>
      </div>
    </div>
    <div class="questions-wall">
  `;

  questions.forEach((q, idx) => {
    html += renderQuestionCard(q, idx + 1, true);
  });
  html += '</div>';

  elements.wrongPaperContainer.innerHTML = html;
  attachQuestionCardEvents(elements.wrongPaperContainer);
  renderLatexFormulas(elements.wrongPaperContainer);
  showToast('🔥 纯错题专属试卷已生成！');
}

async function exportWrongJson() {
  const res = await fetch(`/api/wrong-pool?subject=${encodeURIComponent(state.currentSubject)}`);
  const data = await res.json();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `我的880${state.currentSubject}错题本备份.json`;
  a.click();
}

// =========================================================================
// 6. Workspace 4: Radar View
// =========================================================================
function renderRadarView(data) {
  if (!elements.radarCoveragePercent || !data || !data.chapters) return;
  const total = data.totalChapters || data.chapters.length;
  const coveredCount = (data.coveredChapters || []).length;
  const percent = total > 0 ? Math.min(100, Math.round((coveredCount / total) * 100)) : 0;

  elements.radarCoveragePercent.textContent = `${percent}%`;
  elements.radarProgressBar.style.width = `${percent}%`;

  // Dynamic Chapters Matrix
  elements.radarChaptersMatrix.innerHTML = data.chapters.map(c => `
    <span class="ch-pill ${c.isCovered ? 'done' : 'pending'}">
      ${c.isCovered ? '✓' : '○'} ${c.name} (${c.count}题)
    </span>
  `).join('');

  // 3 Disciplines by Category
  const adv = data.chapters.filter(c => c.category === '高等数学');
  const lin = data.chapters.filter(c => c.category === '线性代数');
  const prob = data.chapters.filter(c => c.category === '概率论与数理统计');

  elements.discAdvList.innerHTML = adv.length > 0
    ? adv.map(c => `<div class="disc-item"><span>${c.isCovered ? '✅' : '⏳'} ${c.name}</span><span style="font-size:11px; color:#64748b;">错${c.wrongCount}</span></div>`).join('')
    : '<div style="color:var(--text-muted); padding:6px 0; font-size:12px;">（本科目不考）</div>';

  elements.discLinList.innerHTML = lin.length > 0
    ? lin.map(c => `<div class="disc-item"><span>${c.isCovered ? '✅' : '⏳'} ${c.name}</span><span style="font-size:11px; color:#64748b;">错${c.wrongCount}</span></div>`).join('')
    : '<div style="color:var(--text-muted); padding:6px 0; font-size:12px;">（本科目不考）</div>';

  elements.discProbList.innerHTML = prob.length > 0
    ? prob.map(c => `<div class="disc-item"><span>${c.isCovered ? '✅' : '⏳'} ${c.name}</span><span style="font-size:11px; color:#64748b;">错${c.wrongCount}</span></div>`).join('')
    : '<div style="color:var(--text-muted); padding:6px 0; font-size:12px;">（数二不考概率论）</div>';
}

// =========================================================================
// 7. Helpers: Download & Archive
// =========================================================================
async function downloadPaperFile(isSolved) {
  if (!state.currentPaper) return;
  const qList = state.currentPaper.allQuestions;
  let printHtml = `
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"><title>${state.currentPaper.title}</title>
    <style>
      body { font-family: sans-serif; padding: 30px; }
      .q-block { margin-bottom: 25px; page-break-inside: avoid; }
      .draft-space { height: 90px; border: 1px dashed #ccc; margin: 10px 0; }
    </style></head><body>
    <h1>${state.currentPaper.title}</h1>
    <p>卷号: ${state.currentPaper.id}</p>
    <hr>
  `;
  qList.forEach((q, i) => {
    printHtml += `<div class="q-block"><strong>第 ${i+1} 题 [${q.type}·${q.difficulty}]</strong><p>${q.stem}</p>`;
    if (!isSolved) {
      printHtml += `<div class="draft-space"></div>`;
    } else {
      printHtml += `<p style="color:#b45309;"><b>考点</b>: ${(q.coreKnowledge||[]).join('、')} | <b>避坑</b>: ${q.pitfallAnalysis||''}</p><p><b>答案</b>: ${q.answer}</p><pre>${q.solution}</pre>`;
    }
    printHtml += `</div>`;
  });
  printHtml += `</body></html>`;

  const blob = new Blob([printHtml], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${state.currentPaper.id}_${isSolved ? '详细解析' : '全真模考'}.html`;
  a.click();
}

async function archivePaperLocal() {
  if (!state.currentPaper) return;
  const res = await fetch('/api/archive-paper', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper: state.currentPaper, subject: state.currentSubject }),
  });
  const data = await res.json();
  showToast(`💾 试卷已成功归档保存至项目 【试卷库/】 目录！`);
}

function renderLatexFormulas(container) {
  if (window.renderMathInElement) {
    window.renderMathInElement(container, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false },
        { left: '\\[', right: '\\]', display: true },
      ],
      throwOnError: false,
    });
  }
}

function renderMarkdown(text) {
  if (!text) return '';
  if (window.marked && window.marked.parse) {
    return window.marked.parse(text);
  }
  return text;
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function showToast(msg) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span>${msg}</span>`;
  elements.toastContainer.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => t.remove(), 300);
  }, 3000);
}

function debounce(fn, delay) {
  let timer = null;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

// Start
document.addEventListener('DOMContentLoaded', initApp);
