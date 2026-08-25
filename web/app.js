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
  } catch (err) {
    console.error('Failed to init data:', err);
    showToast('❌ 加载题库数据失败，请刷新重试');
  }
}

// =========================================================================
// 2. Navigation & Themes
// =========================================================================
function setupEventListeners() {
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

  // Theme Toggle
  if (elements.themeToggleBtn) {
    elements.themeToggleBtn.addEventListener('click', () => {
      document.body.classList.toggle('theme-light');
      const isLight = document.body.classList.contains('theme-light');
      elements.themeToggleBtn.textContent = isLight ? '☀️' : '🌙';
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
