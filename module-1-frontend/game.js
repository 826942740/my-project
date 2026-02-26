/**
 * game.js — fangame 前端逻辑
 * 职责：与后端 API 通信、渲染消息、管理 UI 状态
 * 不包含任何游戏规则逻辑，一切以后端返回数据为准
 */

'use strict';

/* ============================================================
   常量配置
   ============================================================ */

// 后端 API 地址（开发时指向本地）
const API_BASE = '';  // 与后端同源，使用相对路径

// 默认故事 ID（与后端 stories/ 目录名一致）
const DEFAULT_STORY = 'khemjira';

// localStorage 中存 token 用的 key
const TOKEN_KEY = 'fangame_session_token';

/**
 * stat 字段对应的 emoji 图标。
 * hp_max 不单独显示，配合 hp 一起用于进度条。
 * 未在此表中的 stat 显示默认图标 📦
 */
const STAT_ICONS = {
  hp:     '❤️',
  hp_max: null,   // 不单独显示
  gold:   '💰',
  bread:  '🍞',
  sword:  '⚔️',
  rope:   '🪢',
  torch:  '🔦',
  key:    '🗝️',
};

/* ============================================================
   全局状态（只在此文件内使用，不暴露到 window）
   ============================================================ */

/** 当前会话 token */
let sessionToken = null;

/** 缓存从服务器预加载的存档状态（用于开始界面直接继续） */
let pendingRestoredState = null;

/**
 * 当前游戏阶段：'navigation'（导航中）或 'card'（卡片对话中）
 * 根据后端返回的 state.in_card 字段同步更新
 */
let currentPhase = 'navigation';

/** 是否正在等待 AI 响应，期间禁止发送 */
let isLoading = false;

/* ============================================================
   DOM 元素引用（页面加载后赋值）
   ============================================================ */

// 两个顶层界面
let elStartScreen, elGameScreen;

// 开始界面元素
let elBtnNewGame, elInputResumeCode, elBtnResume, elResumeError;

// 游戏界面主要元素
let elGameTitle, elBtnSaveCode, elBtnNewGameIngame;
let elMessageList, elLoadingIndicator;
let elSidebarChapter, elSidebarPosition, elSidebarStats;
let elSidebarCard, elSidebarCardTitle, elSidebarCardRound;
let elPhaseLabel, elPlayerInput, elBtnSend;

// 弹窗
let elModalSaveCode, elModalOverlay, elModalCodeDisplay, elBtnCopyCode, elBtnModalClose;

// 开始界面：存档列表
let elSaveList, elSaveChapterInfo, elSavePosInfo, elBtnContinue;

/* ============================================================
   初始化入口
   ============================================================ */

/**
 * DOMContentLoaded 后执行，缓存所有 DOM 引用，绑定事件，然后执行初始化流程
 */
document.addEventListener('DOMContentLoaded', () => {
  // --- 缓存 DOM 引用 ---
  elStartScreen        = document.getElementById('start-screen');
  elGameScreen         = document.getElementById('game-screen');

  elBtnNewGame         = document.getElementById('btn-new-game');
  elInputResumeCode    = document.getElementById('input-resume-code');
  elBtnResume          = document.getElementById('btn-resume');
  elResumeError        = document.getElementById('resume-error');

  elGameTitle          = document.getElementById('game-title');
  elBtnSaveCode        = document.getElementById('btn-save-code');
  elBtnNewGameIngame   = document.getElementById('btn-new-game-ingame');
  elMessageList        = document.getElementById('message-list');
  elLoadingIndicator   = document.getElementById('loading-indicator');

  elSidebarChapter     = document.getElementById('sidebar-chapter');
  elSidebarPosition    = document.getElementById('sidebar-position');
  elSidebarStats       = document.getElementById('sidebar-stats');
  elSidebarCard        = document.getElementById('sidebar-card');
  elSidebarCardTitle   = document.getElementById('sidebar-card-title');
  elSidebarCardRound   = document.getElementById('sidebar-card-round');

  elPhaseLabel         = document.getElementById('phase-label');
  elPlayerInput        = document.getElementById('player-input');
  elBtnSend            = document.getElementById('btn-send');

  elModalSaveCode      = document.getElementById('modal-save-code');
  elModalOverlay       = document.getElementById('modal-overlay');
  elModalCodeDisplay   = document.getElementById('modal-code-display');
  elBtnCopyCode        = document.getElementById('btn-copy-code');
  elBtnModalClose      = document.getElementById('btn-modal-close');

  elSaveList           = document.getElementById('save-list');
  elSaveChapterInfo    = document.getElementById('save-chapter-info');
  elSavePosInfo        = document.getElementById('save-pos-info');
  elBtnContinue        = document.getElementById('btn-continue');

  // --- 绑定事件 ---
  bindEvents();

  // --- 执行初始化流程 ---
  initGame();
});

/**
 * 绑定所有按钮、输入框事件
 */
function bindEvents() {
  // 开始界面：继续上次游戏
  elBtnContinue.addEventListener('click', () => enterContinueGame());

  // 开始界面：新游戏
  elBtnNewGame.addEventListener('click', () => startNewGame());

  // 开始界面：存档码继续
  elBtnResume.addEventListener('click', () => {
    const code = elInputResumeCode.value.trim().toUpperCase();
    if (code.length < 4) {
      showResumeError('存档码太短，请检查后重试');
      return;
    }
    resumeWithCode(code);
  });

  // 存档码输入框回车也触发
  elInputResumeCode.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') elBtnResume.click();
  });

  // 游戏内：发送按钮
  elBtnSend.addEventListener('click', handleSendClick);

  // 游戏内：输入框回车发送
  elPlayerInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) handleSendClick();
  });

  // 游戏内：存档码按钮
  elBtnSaveCode.addEventListener('click', () => showSaveCode());

  // 游戏内：新游戏按钮
  elBtnNewGameIngame.addEventListener('click', () => {
    // 二次确认，避免误触
    if (confirm('确定要开始新游戏吗？当前进度将丢失（可先保存存档码）')) {
      // 清除 token 并跳到开始界面
      sessionToken = null;
      localStorage.removeItem(TOKEN_KEY);
      showStartScreen();
    }
  });

  // 弹窗：关闭
  elBtnModalClose.addEventListener('click', closeModal);
  elModalOverlay.addEventListener('click', closeModal);

  // 弹窗：复制存档码
  elBtnCopyCode.addEventListener('click', () => {
    const code = elModalCodeDisplay.textContent;
    if (code && code !== '—') {
      navigator.clipboard.writeText(code)
        .then(() => {
          elBtnCopyCode.textContent = '已复制 ✓';
          setTimeout(() => { elBtnCopyCode.textContent = '复制'; }, 2000);
        })
        .catch(() => {
          // 降级：选中文字让用户手动复制
          elModalCodeDisplay.focus();
          document.execCommand('selectAll');
        });
    }
  });
}

/* ============================================================
   初始化流程
   ============================================================ */

/**
 * 页面初始化：始终先显示开始界面，如果有存档则在界面上展示存档信息
 */
async function initGame() {
  // 先显示开始界面，再决定是否展示存档卡片
  showStartScreen();

  const storedToken = localStorage.getItem(TOKEN_KEY);

  // 无有效 token：隐藏存档列表，仅显示新游戏
  if (!storedToken || storedToken === 'undefined') {
    localStorage.removeItem(TOKEN_KEY);  // 清理可能的 "undefined" 字符串
    elSaveList.classList.add('hidden');
    return;
  }

  // 有 token：尝试从服务器预加载存档状态，在开始界面显示存档信息
  try {
    const data = await apiGet(`/api/state?token=${encodeURIComponent(storedToken)}`);

    if (data.valid) {
      // 存档有效：缓存状态，显示存档卡片
      sessionToken = storedToken;
      pendingRestoredState = data.state;
      showSaveCard(data.state);
    } else {
      // 存档已过期
      localStorage.removeItem(TOKEN_KEY);
      elSaveList.classList.add('hidden');
    }
  } catch (err) {
    // 服务器无法连接，隐藏存档卡片
    localStorage.removeItem(TOKEN_KEY);
    elSaveList.classList.add('hidden');
  }
}

/**
 * 在开始界面显示存档卡片（章节名 + 坐标）
 * @param {object} state - GameState 对象
 */
function showSaveCard(state) {
  const chapterName = state.chapter_name || `第 ${(state.chapter_idx || 0) + 1} 章`;
  const pos = state.position
    ? `(${state.position[0]}, ${state.position[1]})`
    : '—';

  elSaveChapterInfo.textContent = chapterName;
  elSavePosInfo.textContent = `位置：${pos}`;
  elSaveList.classList.remove('hidden');
}

/**
 * 继续上次游戏：直接用预加载的存档状态进入游戏
 */
function enterContinueGame() {
  if (!sessionToken || !pendingRestoredState) return;

  showGameScreen();
  applyRestoredState(pendingRestoredState);

  // 清除缓存，避免重复使用
  pendingRestoredState = null;
}

/**
 * 恢复已保存的游戏状态（刷新页面或用存档码恢复时调用）
 * @param {object} state - 后端返回的 GameState 对象
 */
function applyRestoredState(state) {
  updateSidebar(state);

  // 根据 in_card 判断当前阶段
  if (state.in_card) {
    enterCardPhase(state.in_card, null); // 恢复时不重新显示进入提示
  } else {
    enterNavPhase();
    fetchNavNarrative(); // 异步拉取导航旁白
  }
}

/* ============================================================
   新游戏 / 存档码恢复
   ============================================================ */

/**
 * 开始新游戏：调用 POST /api/session/new
 * 游戏界面立即显示，导航旁白再单独异步拉取（避免 AI 生成时长阻塞界面）
 */
async function startNewGame() {
  elBtnNewGame.disabled = true;
  elBtnNewGame.textContent = '正在创建…';

  try {
    const data = await apiPost('/api/session/new', { story_id: DEFAULT_STORY });

    // 保存 token
    sessionToken = data.session_token;
    localStorage.setItem(TOKEN_KEY, sessionToken);

    // 立刻显示游戏界面和侧边栏
    showGameScreen();
    if (data.state) updateSidebar(data.state);
    enterNavPhase();

    // 异步拉取导航旁白（AI 生成，不阻塞界面显示）
    fetchNavNarrative();

  } catch (err) {
    renderMessage('warning', `创建游戏失败：${err.message}`);
  } finally {
    elBtnNewGame.disabled = false;
    elBtnNewGame.textContent = '开始新游戏';
  }
}

/**
 * 用存档码恢复游戏（换设备时使用）
 * @param {string} code - 6 位存档码（已转大写）
 */
async function resumeWithCode(code) {
  elBtnResume.disabled = true;
  elResumeError.classList.add('hidden');

  try {
    const data = await apiPost('/api/session/resume', { code });

    // 保存新 token（后端返回字段名为 session_token）
    sessionToken = data.session_token;
    localStorage.setItem(TOKEN_KEY, sessionToken);

    // 切换到游戏界面并恢复状态
    showGameScreen();
    if (data.state) applyRestoredState(data.state);
    renderMessage('system', `已恢复存档（码：${code}）`);

  } catch (err) {
    showResumeError('存档码无效或已过期，请重试');
  } finally {
    elBtnResume.disabled = false;
  }
}

/* ============================================================
   玩家输入处理
   ============================================================ */

/**
 * 点击发送按钮或回车后的处理函数
 */
function handleSendClick() {
  if (isLoading) return;

  const text = elPlayerInput.value.trim();
  if (!text) return;

  // 清空输入框
  elPlayerInput.value = '';

  sendInput(text);
}

/**
 * 发送玩家输入：根据当前阶段自动选择调用哪个 API
 * @param {string} text - 玩家输入的文字
 */
async function sendInput(text) {
  if (!sessionToken) {
    renderMessage('warning', '会话已失效，请刷新页面');
    return;
  }

  // 先渲染玩家输入气泡
  renderMessage('player', text);

  // 禁用输入框，显示加载动画
  setInputEnabled(false);
  showLoading();

  try {
    if (currentPhase === 'navigation') {
      await handleNavigate(text);
    } else {
      await handleCardAction(text);
    }
  } catch (err) {
    renderMessage('warning', `请求失败（${err.message}），请重试`);
  } finally {
    hideLoading();
    setInputEnabled(true);
    // 重新聚焦输入框，方便连续输入
    elPlayerInput.focus();
  }
}

/**
 * 导航阶段：调用 POST /api/navigate
 * @param {string} playerInput
 */
async function handleNavigate(playerInput) {
  const data = await apiPost('/api/navigate', {
    session_token: sessionToken,
    player_input:  playerInput,
  });

  // 渲染导航旁白（包含方向解析失败的提示）
  if (data.narrative) {
    renderNavNarrative(data.narrative);
  }

  // 方向解析失败：只显示提示，不继续处理（state 未改变）
  if (data.parse_failed || (!data.moved_to && !data.entered_card && !data.triggered_main_story)) {
    return;
  }

  // 更新 stats
  if (data.stats) {
    updateSidebarStats(data.stats);
  }

  // 如果触发了主线剧情
  if (data.triggered_main_story) {
    // 主线剧情由后端通过 narrative 字段一并返回，这里不额外处理
    // 后续轮次将由 card_action 处理
    enterCardPhase(null, null);
    return;
  }

  // 进入了某张卡片（场景描述已通过 data.narrative 渲染，这里只切换阶段）
  if (data.entered_card) {
    // 使用 title 或 card_id 作为侧边栏显示名
    const cardLabel = data.entered_card.title || data.entered_card.card_id || '未知卡片';
    enterCardPhase(cardLabel, null);
  }

  // 更新坐标
  if (data.moved_to) {
    updateSidebarPosition(data.moved_to);
  }
}

/**
 * 卡片阶段：调用 POST /api/card_action
 * @param {string} playerInput
 */
async function handleCardAction(playerInput) {
  const data = await apiPost('/api/card_action', {
    session_token: sessionToken,
    player_input:  playerInput,
  });

  // 渲染 NPC 回应
  if (data.npc_response) {
    // 卡片阶段 NPC 回应用 npc 类型
    renderMessage('npc', data.npc_response);
  }

  // 更新 stats
  if (data.stats) {
    updateSidebarStats(data.stats);
  }

  // 更新卡片轮次（从 stats 或其他字段获取，这里直接从侧边栏累加）
  if (!data.card_done && data.judge) {
    incrementCardRound();
  }

  // 胜负结算效果日志
  if (data.effects_log && data.effects_log.length > 0) {
    const logText = data.effects_log.join('  ');
    renderMessage('system', `结算：${logText}`);
  }

  // 判断结果
  if (data.judge === 'win') {
    renderMessage('system', '胜利！');
  } else if (data.judge === 'lose') {
    renderMessage('warning', '失败！');
  }

  // 卡片结束：切回导航阶段
  if (data.card_done) {
    exitCardPhase();
    if (data.game_over) {
      // 游戏结束（HP归零等），不再拉取旁白
      renderMessage('warning', '游戏结束。');
    } else if (data.game_cleared) {
      // 全关通关
      renderMessage('main_story', '恭喜你完成了所有章节！感谢你的游玩。');
    } else {
      // 正常卡片结束，异步拉取下一步导航旁白
      fetchNavNarrative();
    }
  }
}

/* ============================================================
   阶段切换
   ============================================================ */

/**
 * 切换到导航阶段：更新输入框提示 & 阶段标签
 */
function enterNavPhase() {
  currentPhase = 'navigation';
  elPhaseLabel.textContent = '导航中';
  elPlayerInput.placeholder = '描述你想去的方向…';
}

/**
 * 切换到卡片阶段：更新输入框提示 & 侧边栏卡片信息
 * @param {string|null} cardTitle - 卡片标题，null 时只更新阶段不更改标题
 * @param {number|null} maxRound - 最大轮数，null 时不显示
 */
function enterCardPhase(cardTitle, maxRound) {
  currentPhase = 'card';
  elPhaseLabel.textContent = '对话中';
  elPlayerInput.placeholder = '和对方交流…';

  // 显示侧边栏卡片区域
  if (cardTitle) {
    elSidebarCardTitle.textContent = `卡片中：${cardTitle}`;
    elSidebarCardRound.textContent = maxRound ? `第 1 / ${maxRound} 轮` : '第 1 轮';
    elSidebarCard.classList.remove('hidden');
  }
}

/**
 * 卡片结束：切回导航阶段，隐藏卡片信息
 */
function exitCardPhase() {
  enterNavPhase();
  elSidebarCard.classList.add('hidden');
}

/**
 * 侧边栏卡片轮次 +1（纯 UI 计数，以服务器状态为准时可扩展）
 */
function incrementCardRound() {
  const text = elSidebarCardRound.textContent;
  const match = text.match(/第\s*(\d+)/);
  if (match) {
    const next = parseInt(match[1], 10) + 1;
    elSidebarCardRound.textContent = text.replace(/第\s*\d+/, `第 ${next}`);
  }
}

/**
 * 异步拉取当前位置的导航旁白（调用 GET /api/nav）
 * 在进入导航阶段后单独调用，避免 AI 生成时长阻塞界面显示。
 * 加载期间显示临时提示消息，完成后替换为实际旁白。
 */
async function fetchNavNarrative() {
  if (!sessionToken) return;

  // 插入临时"正在加载"提示（用 data 属性标记，便于之后移除）
  const loadingEl = document.createElement('div');
  loadingEl.classList.add('msg', 'msg-system');
  loadingEl.dataset.navLoading = 'true';
  const tagSpan = document.createElement('span');
  tagSpan.classList.add('tag');
  tagSpan.textContent = '[系统]';
  loadingEl.appendChild(tagSpan);
  loadingEl.appendChild(document.createTextNode(' 正在感知周围环境…'));
  elMessageList.appendChild(loadingEl);
  scrollToBottom();

  try {
    // 导航旁白 AI 生成较慢，超时设为 90 秒
    const data = await apiGet(`/api/nav?token=${encodeURIComponent(sessionToken)}`, 90000);

    // 移除加载提示，渲染实际旁白
    loadingEl.remove();
    if (data.narrative) {
      renderNavNarrative(data.narrative);
    }
  } catch (err) {
    loadingEl.remove();
    renderMessage('warning', `导航旁白加载失败（${err.message}），可输入方向继续`);
  }
}

/* ============================================================
   消息渲染
   ============================================================ */

/**
 * 渲染一条消息到文本区，并自动滚动到底部
 * @param {string} type - 消息类型：narrative / npc / player / system / main_story / warning
 * @param {string} content - 消息内容
 * @param {string|null} speakerName - NPC 名字（type=npc 时使用）
 */
function renderMessage(type, content, speakerName = null) {
  if (!content) return;

  const el = document.createElement('div');
  el.classList.add('msg', `msg-${type}`);

  switch (type) {
    case 'narrative':
      // 普通白色旁白，直接显示文字
      el.textContent = content;
      break;

    case 'npc': {
      // 浅黄色，带角色名前缀
      if (speakerName) {
        const nameSpan = document.createElement('span');
        nameSpan.classList.add('speaker-name');
        nameSpan.textContent = `[${speakerName}]`;
        el.appendChild(nameSpan);
      }
      el.appendChild(document.createTextNode(content));
      break;
    }

    case 'player':
      // 灰色右对齐，:: before 加箭头
      el.textContent = content;
      break;

    case 'system': {
      // 浅绿色小字，加 [系统] 前缀
      const tagSpan = document.createElement('span');
      tagSpan.classList.add('tag');
      tagSpan.textContent = '[系统]';
      el.appendChild(tagSpan);
      el.appendChild(document.createTextNode(' ' + content));
      break;
    }

    case 'main_story':
      // 金色加粗主线剧情
      el.textContent = content;
      break;

    case 'warning': {
      // 橙色警告
      const tagSpan = document.createElement('span');
      tagSpan.classList.add('tag');
      tagSpan.textContent = '[警告]';
      el.appendChild(tagSpan);
      el.appendChild(document.createTextNode(' ' + content));
      break;
    }

    default:
      // 未知类型降级为 narrative
      el.textContent = content;
  }

  elMessageList.appendChild(el);
  scrollToBottom();
}

/**
 * 渲染导航旁白：正文作为叙事，末尾的 A/B/C 选项渲染为可点击按钮
 * @param {string} content - AI 生成的导航文字（含 A. xxx B. xxx 格式选项）
 */
function renderNavNarrative(content) {
  if (!content) return;

  // 尝试从文字中分离"正文"和"选项"
  // 选项格式：A. 行动描述 / A: 行动描述 / A）行动描述
  const optionRegex = /[A-Ca-c][\.：:）)]\s*(.+)/g;
  const optionMatches = [...content.matchAll(optionRegex)];

  if (optionMatches.length >= 2) {
    // 找到选项 → 把正文和选项分开渲染
    // 正文：第一个选项出现之前的文字
    const firstOptionIndex = content.search(/[A-Ca-c][\.：:）)]/);
    const mainText = content.slice(0, firstOptionIndex).trim();

    if (mainText) {
      renderMessage('narrative', mainText);
    }

    // 渲染选项按钮行
    const el = document.createElement('div');
    el.classList.add('nav-options');

    optionMatches.forEach((match) => {
      const label = match[0][0].toUpperCase(); // A / B / C
      const text  = match[1].trim();

      const btn = document.createElement('button');
      btn.classList.add('btn', 'nav-option-btn');
      btn.textContent = `${label}. ${text}`;
      btn.addEventListener('click', () => {
        if (isLoading) return;
        // 点击后直接以选项文字作为玩家输入发送
        elPlayerInput.value = text;
        handleSendClick();
      });
      el.appendChild(btn);
    });

    elMessageList.appendChild(el);
    scrollToBottom();
  } else {
    // 没有选项格式 → 普通叙事渲染
    renderMessage('narrative', content);
  }
}

/**
 * 滚动消息列表到最底部（新消息出现后调用）
 */
function scrollToBottom() {
  elMessageList.scrollTop = elMessageList.scrollHeight;
}

/* ============================================================
   侧边栏更新
   ============================================================ */

/**
 * 完整更新侧边栏（使用后端返回的完整 state 对象）
 * @param {object} state - GameState 对象
 */
function updateSidebar(state) {
  // 更新章节名
  const chapterName = state.chapter_name || `第 ${(state.chapter_idx || 0) + 1} 章`;
  elSidebarChapter.textContent = `📍 ${chapterName}`;

  // 更新坐标
  if (state.position) {
    updateSidebarPosition(state.position);
  }

  // 更新 stats
  if (state.stats) {
    updateSidebarStats(state.stats);
  }

  // 更新卡片信息
  if (state.in_card) {
    elSidebarCardTitle.textContent = `卡片中：${state.in_card}`;
    const round = state.card_round || 1;
    elSidebarCardRound.textContent = `第 ${round} 轮`;
    elSidebarCard.classList.remove('hidden');
  } else {
    elSidebarCard.classList.add('hidden');
  }
}

/**
 * 仅更新坐标显示
 * @param {number[]} position - [row, col]
 */
function updateSidebarPosition(position) {
  elSidebarPosition.textContent = `位置：(${position[0]}, ${position[1]})`;
}

/**
 * 仅更新 stats 部分（不改变其他侧边栏内容）
 * @param {object} stats - { hp: 80, hp_max: 100, gold: 30, ... }
 */
function updateSidebarStats(stats) {
  // 清空旧内容，重新渲染
  elSidebarStats.innerHTML = '';

  // --- HP 进度条（特殊处理）---
  if ('hp' in stats) {
    const hpVal = stats.hp;
    const hpMax = stats.hp_max || 100;
    const pct   = Math.max(0, Math.min(100, (hpVal / hpMax) * 100));

    // 根据百分比决定进度条颜色
    const colorClass = pct > 60 ? 'high' : pct > 30 ? 'mid' : 'low';

    const hpRow = document.createElement('div');
    hpRow.classList.add('stat-row', 'hp-row');
    hpRow.innerHTML = `
      <div class="hp-header">
        <div class="hp-label">
          <span class="stat-icon">❤️</span>
          <span>hp</span>
        </div>
        <span class="hp-number">${hpVal} / ${hpMax}</span>
      </div>
      <div class="hp-bar-track">
        <div class="hp-bar-fill ${colorClass}" style="width: ${pct.toFixed(1)}%"></div>
      </div>
    `;
    elSidebarStats.appendChild(hpRow);
  }

  // --- 其他 stat 字段 ---
  for (const [key, val] of Object.entries(stats)) {
    // 跳过 hp 相关（已单独渲染）
    if (key === 'hp' || key === 'hp_max') continue;

    // 值为 0 或 null 时不显示
    if (!val) continue;

    // 获取图标，未知字段用 📦
    const icon = STAT_ICONS[key] !== undefined ? STAT_ICONS[key] : '📦';

    const row = document.createElement('div');
    row.classList.add('stat-row');
    row.innerHTML = `
      <span class="stat-icon">${icon}</span>
      <span class="stat-name">${key}</span>
      <span class="stat-value">${val}</span>
    `;
    elSidebarStats.appendChild(row);
  }
}

/* ============================================================
   加载动画
   ============================================================ */

/** 显示三点加载动画，并将发送按钮置灰 */
function showLoading() {
  isLoading = true;
  elLoadingIndicator.classList.remove('hidden');
}

/** 隐藏加载动画 */
function hideLoading() {
  isLoading = false;
  elLoadingIndicator.classList.add('hidden');
}

/**
 * 启用或禁用输入区（AI 生成中时禁用）
 * @param {boolean} enabled
 */
function setInputEnabled(enabled) {
  elPlayerInput.disabled = !enabled;
  elBtnSend.disabled     = !enabled;
  if (enabled) {
    elPlayerInput.placeholder = currentPhase === 'navigation'
      ? '描述你想去的方向…'
      : '和对方交流…';
  } else {
    elPlayerInput.placeholder = '生成中…';
  }
}

/* ============================================================
   存档码弹窗
   ============================================================ */

/**
 * 获取当前存档码并弹窗显示
 */
async function showSaveCode() {
  if (!sessionToken) {
    renderMessage('warning', '当前没有进行中的游戏');
    return;
  }

  // 先弹窗，显示 loading 状态
  elModalCodeDisplay.textContent = '加载中…';
  openModal();

  try {
    const data = await apiGet(`/api/session/code?token=${encodeURIComponent(sessionToken)}`);
    elModalCodeDisplay.textContent = data.short_code || '获取失败';
  } catch (err) {
    elModalCodeDisplay.textContent = '获取失败';
    console.error('获取存档码失败：', err.message);
  }
}

/** 打开弹窗 */
function openModal() {
  elModalSaveCode.classList.remove('hidden');
  elModalOverlay.classList.remove('hidden');
}

/** 关闭弹窗 */
function closeModal() {
  elModalSaveCode.classList.add('hidden');
  elModalOverlay.classList.add('hidden');
}

/* ============================================================
   界面切换
   ============================================================ */

/** 显示开始界面，隐藏游戏界面 */
function showStartScreen() {
  elStartScreen.classList.remove('hidden');
  elGameScreen.classList.add('hidden');
}

/** 显示游戏界面，隐藏开始界面 */
function showGameScreen() {
  elStartScreen.classList.add('hidden');
  elGameScreen.classList.remove('hidden');
  // 聚焦输入框，方便直接打字
  elPlayerInput.focus();
}

/** 显示存档码错误提示 */
function showResumeError(msg) {
  elResumeError.textContent = msg;
  elResumeError.classList.remove('hidden');
}

/* ============================================================
   API 工具函数
   ============================================================ */

/**
 * 通用 GET 请求
 * @param {string} path - API 路径（含参数），如 /api/state?token=xxx
 * @returns {Promise<object>} 解析后的 JSON 响应
 * @throws {Error} 网络错误或 HTTP 错误
 */
async function apiGet(path, timeoutMs = 30000) {
  const resp = await fetchWithTimeout(`${API_BASE}${path}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  }, timeoutMs);

  if (!resp.ok) {
    const errText = await resp.text().catch(() => '');
    throw new Error(`HTTP ${resp.status}: ${errText}`);
  }

  return resp.json();
}

/**
 * 通用 POST 请求
 * @param {string} path - API 路径，如 /api/navigate
 * @param {object} body - 请求体（会自动序列化为 JSON）
 * @returns {Promise<object>} 解析后的 JSON 响应
 * @throws {Error} 网络错误或 HTTP 错误
 */
async function apiPost(path, body) {
  const resp = await fetchWithTimeout(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => '');
    throw new Error(`HTTP ${resp.status}: ${errText}`);
  }

  return resp.json();
}

/**
 * 带超时的 fetch 封装（默认 30 秒）
 * @param {string} url
 * @param {RequestInit} options
 * @param {number} timeoutMs - 超时毫秒数，默认 30000
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options, timeoutMs = 30000) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(url, { ...options, signal: controller.signal });
    return resp;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('请求超时（>30s），请检查网络或后端状态');
    }
    throw err;
  } finally {
    clearTimeout(timerId);
  }
}
