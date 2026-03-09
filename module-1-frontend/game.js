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

// localStorage 中存完整对话历史用的 key（刷新/继续后恢复所有消息）
const CHAT_LOG_KEY = 'fangame_chat_log';
const CARD_START_SFX_URL = 'https://butter1.s3.us-east-1.amazonaws.com/rpgmusic/This+is+a+....mp3';
const CARD_SFX_VOLUME = 0.35;

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
  amulet: '🔮',
  merit:  '✨',
  cash:   '💵',
};

/**
 * stat 字段对应的中文显示名称。
 * 未在此表中的 stat 直接显示原始 key 名。
 */
const STAT_NAMES = {
  hp:     '生命',
  hp_max: null,
  gold:   '金币',
  bread:  '面包',
  sword:  '利剑',
  rope:   '绳索',
  torch:  '火把',
  key:    '钥匙',
  amulet: '护符',
  merit:  '功德',
  cash:   '现金',
};

/* ============================================================
   全局状态（只在此文件内使用，不暴露到 window）
   ============================================================ */

/** 当前会话 token */
let sessionToken = null;

/** 缓存从服务器预加载的存档状态（用于开始界面直接继续） */
let pendingRestoredState = null;

/** 恢复对话历史时临时禁止写入 localStorage，避免重复保存 */
let _suppressChatLogSave = false;

/**
 * 当前游戏阶段：'navigation'（导航中）或 'card'（卡片对话中）
 * 根据后端返回的 state.in_card 字段同步更新
 */
let currentPhase = 'navigation';

/**
 * /api/nav 返回的方向列表，按顺序对应导航旁白中的 A/B/C 选项。
 * 格式：[{direction: "right", card_title: "...", card_type: "..."}, ...]
 * 用于按钮点击时直接告知后端方向，绕过文字解析。
 */
let currentNavDirections = [];

/**
 * 当前旁白中提取的选项文字，与 currentNavDirections 对应。
 * 格式：[{direction: "right", text: "慢慢靠近井口查看"}, ...]
 * 用于用户输入自由文字时，帮助后端理解语义（"我想离开" → 匹配 "迅速离开此地" → right）
 */
let currentNavOptionTexts = [];

/** 是否正在等待 AI 响应，期间禁止发送 */
let isLoading = false;
let pendingChapterInfo = null;
let cardStartAudio = null;
let cardStartAudioUnlocked = false;
const _audioCache = new Map();  // URL → Audio 对象缓存，避免同一 URL 重复创建
let _currentAudio = null;       // 当前正在播放的 Audio 对象

function stopCurrentAudio() {
  if (_currentAudio) {
    try { _currentAudio.pause(); _currentAudio.currentTime = 0; } catch (_) {}
    _currentAudio = null;
  }
}

/**
 * 播放卡片触发视频，播完或跳过后执行 callback
 * @param {string} url   视频 URL，为空则直接执行 callback
 * @param {Function} callback  视频结束后的回调
 */
function playCardVideo(url, callback) {
  if (!url || !url.trim() || !elCardVideoScreen || !elCardVideo) {
    if (callback) callback();
    return;
  }
  _cardVideoEnded = false;
  elCardVideo.src = url.trim();
  elCardVideo.load();
  elCardVideoScreen.classList.remove('hidden');
  elCardVideo.play().catch(() => _endCardVideo());
  // 保存 callback 供 _endCardVideo 调用
  elCardVideo._onEndCallback = callback;
}

function _endCardVideo() {
  if (_cardVideoEnded) return;
  _cardVideoEnded = true;
  if (elCardVideo) { try { elCardVideo.pause(); } catch (_) {} }
  if (elCardVideoScreen) elCardVideoScreen.classList.add('hidden');
  const cb = elCardVideo && elCardVideo._onEndCallback;
  if (elCardVideo) elCardVideo._onEndCallback = null;
  if (cb) cb();
}

/* ============================================================
   DOM 元素引用（页面加载后赋值）
   ============================================================ */

// 三个顶层界面
let elStartScreen, elIntroScreen, elGameScreen;

// 开始界面元素
let elBtnNewGame;

// 游戏界面主要元素
let elGameTitle, elBtnNewGameIngame;
let elMessageList, elLoadingIndicator;
let elSidebarChapter, elSidebarPosition, elSidebarStats;
let elSidebarCard, elSidebarCardTitle, elSidebarCardRound;
let elSidebarChapterBackground, elSidebarChapterCharacters, elSidebarChapterObjectives;
let elPhaseLabel, elPlayerInput, elBtnSend;

// 手机端状态条 + 章节面板
let elMobileStatsBar;
let elBtnChapterInfo, elMobileChapterPanel;
let elMcpChapter, elMcpPosition, elMcpBackground, elMcpCharacters, elMcpObjectives;

// 卡片触发视频
let elCardVideoScreen, elCardVideo, elBtnSkipCardVideo;
let _cardVideoEnded = false;

// 介绍界面
let elBtnStartAdventure, elBtnIntroBack;

// 视频界面
let elVideoScreen, elIntroVideo, elBtnSkipVideo;
let _videoEnded = false;  // 防止 ended / catch 双触发导致 startNewGame 被调用两次

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
  elIntroScreen        = document.getElementById('intro-screen');
  elGameScreen         = document.getElementById('game-screen');

  elBtnNewGame         = document.getElementById('btn-new-game');

  elGameTitle          = document.getElementById('game-title');
  elBtnNewGameIngame   = document.getElementById('btn-new-game-ingame');
  elMessageList        = document.getElementById('message-list');
  elLoadingIndicator   = document.getElementById('loading-indicator');

  elSidebarChapter     = document.getElementById('sidebar-chapter');
  elSidebarPosition    = document.getElementById('sidebar-position');
  elSidebarStats       = document.getElementById('sidebar-stats');
  elSidebarCard        = document.getElementById('sidebar-card');
  elSidebarCardTitle   = document.getElementById('sidebar-card-title');
  elSidebarCardRound   = document.getElementById('sidebar-card-round');
  elSidebarChapterBackground = document.getElementById('sidebar-chapter-background');
  elSidebarChapterCharacters = document.getElementById('sidebar-chapter-characters');
  elSidebarChapterObjectives = document.getElementById('sidebar-chapter-objectives');

  elPhaseLabel         = document.getElementById('phase-label');
  elPlayerInput        = document.getElementById('player-input');
  elBtnSend            = document.getElementById('btn-send');

  elSaveList           = document.getElementById('save-list');
  elSaveChapterInfo    = document.getElementById('save-chapter-info');
  elSavePosInfo        = document.getElementById('save-pos-info');
  elBtnContinue        = document.getElementById('btn-continue');

  elBtnStartAdventure  = document.getElementById('btn-start-adventure');
  elBtnIntroBack       = document.getElementById('btn-intro-back');

  elVideoScreen        = document.getElementById('video-screen');
  elIntroVideo         = document.getElementById('intro-video');
  elBtnSkipVideo       = document.getElementById('btn-skip-video');

  elMobileStatsBar       = document.getElementById('mobile-stats-bar');
  elCardVideoScreen      = document.getElementById('card-video-screen');
  elCardVideo            = document.getElementById('card-video');
  elBtnSkipCardVideo     = document.getElementById('btn-skip-card-video');
  elBtnChapterInfo       = document.getElementById('btn-chapter-info');
  elMobileChapterPanel = document.getElementById('mobile-chapter-panel');
  elMcpChapter         = document.getElementById('mcp-chapter');
  elMcpPosition        = document.getElementById('mcp-position');
  elMcpBackground      = document.getElementById('mcp-background');
  elMcpCharacters      = document.getElementById('mcp-characters');
  elMcpObjectives      = document.getElementById('mcp-objectives');

  // --- 绑定事件 ---
  bindEvents();

  // --- 执行初始化流程 ---
  initGame();
});

/**
 * 绑定所有按钮、输入框事件
 */
function bindEvents() {
  // 卡片视频：跳过按钮
  if (elBtnSkipCardVideo) {
    elBtnSkipCardVideo.addEventListener('click', () => _endCardVideo());
  }
  if (elCardVideo) {
    elCardVideo.addEventListener('ended', () => _endCardVideo());
  }

  // 手机端：章节信息面板开关
  if (elBtnChapterInfo) {
    elBtnChapterInfo.addEventListener('click', () => {
      const isHidden = elMobileChapterPanel.classList.contains('hidden');
      elMobileChapterPanel.classList.toggle('hidden', !isHidden);
      elBtnChapterInfo.classList.toggle('active', isHidden);
    });
  }

  // 开始界面：继续上次游戏
  elBtnContinue.addEventListener('click', () => enterContinueGame());

  // 页面加载完成后立即预加载音频，让文件有足够时间缓冲再播放
  initCardStartSfxIfNeeded();

  // 开始界面：新游戏 → 先显示介绍页
  elBtnNewGame.addEventListener('click', () => showIntroScreen());

  // 介绍界面：开始冒险 → 先播放视频（若无视频元素则直接开始）
  elBtnStartAdventure.addEventListener('click', () => showVideoScreen());

  // 视频：跳过按钮（null 检查，兼容旧缓存）
  if (elBtnSkipVideo) {
    elBtnSkipVideo.addEventListener('click', () => endVideoAndStart());
  }
  if (elIntroVideo) {
    elIntroVideo.addEventListener('ended', () => endVideoAndStart());
  }

  // 介绍界面：返回开始界面
  elBtnIntroBack.addEventListener('click', () => showStartScreen());

  // 游戏内：发送按钮
  elBtnSend.addEventListener('click', handleSendClick);

  // 游戏内：输入框回车发送
  elPlayerInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) handleSendClick();
  });

  // 游戏内：新游戏按钮
  elBtnNewGameIngame.addEventListener('click', () => {
    // 二次确认，避免误触
    if (confirm('确定要开始新游戏吗？当前进度将丢失。')) {
      // 清除 token 并跳到开始界面
      sessionToken = null;
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(CHAT_LOG_KEY);
      showStartScreen();
    }
  });

}

/* ============================================================
   初始化流程
   ============================================================ */

/**
 * 页面初始化：始终先显示开始界面，如果有存档则在界面上展示存档信息
 */
function initCardStartSfxIfNeeded() {
  if (cardStartAudio) return cardStartAudio;
  try {
    cardStartAudio = new Audio(CARD_START_SFX_URL);
    cardStartAudio.preload = 'auto';
    cardStartAudio.volume = CARD_SFX_VOLUME;
  } catch (_) {
    cardStartAudio = null;
  }
  return cardStartAudio;
}

function unlockCardStartAudio() {
  if (cardStartAudioUnlocked) return;
  const audio = initCardStartSfxIfNeeded();
  if (!audio) return;
  const p = audio.play();
  if (p && typeof p.then === 'function') {
    p.then(() => {
      audio.pause();
      audio.currentTime = 0;
      cardStartAudioUnlocked = true;
    }).catch((e) => { console.warn('[audio] unlock failed:', e); });
    return;
  }
  try {
    audio.pause();
    audio.currentTime = 0;
    cardStartAudioUnlocked = true;
  } catch (_) {}
}

/**
 * 播放卡片入场音效
 * @param {string} [url] 卡片指定的音频 URL；省略或为空时使用默认音效
 */
function playCardStartSfx(url) {
  const src = (url && url.trim()) ? url.trim() : CARD_START_SFX_URL;
  if (!src) return;

  // 从缓存中获取或新建 Audio 对象
  let audio = _audioCache.get(src);
  if (!audio) {
    try {
      audio = new Audio(src);
      audio.preload = 'auto';
      audio.volume = CARD_SFX_VOLUME;
      _audioCache.set(src, audio);
    } catch (_) { return; }
  }

  stopCurrentAudio();
  _currentAudio = audio;
  try {
    audio.currentTime = 0;
    const p = audio.play();
    if (p && typeof p.catch === 'function') p.catch((e) => { console.warn('[audio] play failed:', e); });
  } catch (_) {}
}

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
      pendingChapterInfo = data.chapter_info || null;
      showSaveCard(data.state, pendingChapterInfo);
    } else {
      // 存档已过期
      localStorage.removeItem(TOKEN_KEY);
      elSaveList.classList.add('hidden');
    }
  } catch (err) {
    // 服务器无法连接，仅隐藏存档卡片，保留 token（网络恢复后可继续）
    elSaveList.classList.add('hidden');
  }
}

/**
 * 在开始界面显示存档卡片（章节名 + 坐标）
 * @param {object} state - GameState 对象
 */
function showSaveCard(state, chapterInfo = null) {
  const chapterName = state.chapter_name || `第 ${(state.chapter_idx || 0) + 1} 章`;
  const pos = state.position
    ? `(${state.position[0]}, ${state.position[1]})`
    : '—';

  elSaveChapterInfo.textContent = chapterName;
  elSavePosInfo.textContent = `位置：${pos}`;
  elSaveList.classList.remove('hidden');
  if (chapterInfo) updateChapterInfo(chapterInfo);
}

/**
 * 继续上次游戏：先从 localStorage 恢复完整对话历史，再同步游戏状态
 */
function enterContinueGame() {
  if (!sessionToken || !pendingRestoredState) return;

  showGameScreen();

  // 先从 localStorage 恢复完整对话历史（所有旁白、NPC回应、玩家输入）
  const hasChatLog = restoreChatLog();

  // 恢复游戏状态；若已从 localStorage 还原对话，跳过 card_history 避免重复渲染
  applyRestoredState(pendingRestoredState, hasChatLog, pendingChapterInfo);

  // 清除缓存，避免重复使用
  pendingRestoredState = null;
  pendingChapterInfo = null;
}

/**
 * 恢复已保存的游戏状态
 * @param {object} state - 后端返回的 GameState 对象
 * @param {boolean} skipCardHistory - 已从 localStorage 恢复对话时传 true，跳过 card_history 重复渲染
 */
function applyRestoredState(state, skipCardHistory = false, chapterInfo = null) {
  updateSidebar(state);
  if (chapterInfo) updateChapterInfo(chapterInfo);

  // 若 localStorage 没有对话历史（如首次或清除后），则用 card_history 兜底
  if (!skipCardHistory && state.card_history && state.card_history.length > 0) {
    state.card_history.forEach(msg => {
      if (msg.role === 'player') {
        renderMessage('player', msg.content);
      } else if (msg.role === 'npc') {
        renderMessage('npc', msg.content);
      }
    });
  }

  // 根据状态判断当前阶段
  if (state.daily_life_phase) {
    // 恢复到日常生活阶段（显示提示让玩家继续）
    enterDailyLifePhase();
    renderMessage('system', '（日常生活中，请选择或输入你想做的事）');
  } else if (state.in_card) {
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
  unlockCardStartAudio();
  elBtnNewGame.disabled = true;
  elBtnNewGame.textContent = '正在创建…';

  try {
    const data = await apiPost('/api/session/new', { story_id: DEFAULT_STORY });

    // 保存 token，清空旧对话历史（防止新游戏显示上局内容）
    sessionToken = data.session_token;
    localStorage.setItem(TOKEN_KEY, sessionToken);
    localStorage.removeItem(CHAT_LOG_KEY);

    // 立刻显示游戏界面和侧边栏
    showGameScreen();
    if (data.state) updateSidebar(data.state);
    if (data.chapter_info) updateChapterInfo(data.chapter_info);

    // 判断是否有开场卡片（prologue 作为第一张卡片）
    if (data.prologue && data.state && data.state.in_card) {
      const prologueVideoUrl = data.prologue_card && data.prologue_card.video_url;
      playCardVideo(prologueVideoUrl, () => {
        playCardStartSfx(data.prologue_card && data.prologue_card.audio_url);
        // 开场卡片模式：显示 prologue 文本 → 进入卡片阶段 → 等玩家交互
        renderMessage('narrative', data.prologue);
        const cardTitle = (data.prologue_card && data.prologue_card.title) || data.state.in_card;
        enterCardPhase(cardTitle, null);
        // 显示初始行动选项按钮
        const actions = (data.prologue_card && data.prologue_card.initial_actions) || [];
        if (actions.length >= 2) {
          _appendNavOptionButtons(actions.map((text, i) => ({
            label: ['A', 'B', 'C', 'D'][i] || String(i + 1),
            text,
          })));
        }
      });
      // 不调用 fetchNavNarrative()，等卡片结束后再进导航阶段
    } else {
      // 无开场卡片：正常导航流程
      enterNavPhase();
      if (data.prologue) {
        renderMessage('narrative', data.prologue);
      }
      fetchNavNarrative();
    }

  } catch (err) {
    renderMessage('warning', `创建游戏失败：${err.message}`);
  } finally {
    elBtnNewGame.disabled = false;
    elBtnNewGame.textContent = '开始新游戏';
  }
}

/* ============================================================
   玩家输入处理
   ============================================================ */

/**
 * 点击发送按钮或回车后的处理函数
 */
function handleSendClick() {
  unlockCardStartAudio();
  stopCurrentAudio();
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
 * @param {string|null} hintDirection - 导航阶段可选传入方向（来自按钮绑定），跳过文字解析
 */
async function sendInput(text, hintDirection = null) {
  if (!sessionToken) {
    renderMessage('warning', '会话已失效，请刷新页面');
    return;
  }

  // 用户已做出输入（按钮/手动），先清理历史选项，避免旧选项残留
  clearAllOptionGroups();

  // 先渲染玩家输入气泡
  renderMessage('player', text);

  // 禁用输入框，显示加载动画
  setInputEnabled(false);
  showLoading();

  try {
    if (currentPhase === 'navigation') {
      await handleNavigate(text, hintDirection);
    } else if (currentPhase === 'daily_life') {
      await handleDailyLifeAction(text);
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
 * @param {string|null} hintDirection - 直接指定方向（来自 A/B/C 按钮绑定），跳过后端文字解析
 */
async function handleNavigate(playerInput, hintDirection = null) {
  const body = { session_token: sessionToken, player_input: playerInput };
  if (hintDirection) {
    // 按钮点击：直接发方向，跳过文字解析
    body.hint_direction = hintDirection;
  } else if (currentNavOptionTexts.length > 0) {
    // 自由输入：发选项文字，让后端语义匹配（"我想离开" → "迅速离开此地" → 方向）
    body.nav_option_hints = currentNavOptionTexts;
  }
  const data = await apiPost('/api/navigate', body);
  if (data.chapter_info) updateChapterInfo(data.chapter_info);

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
    playCardStartSfx();
    enterCardPhase(null, null);
    return;
  }

  // 进入了某张卡片：切换 UI 阶段，异步拉取 AI 入场叙事
  if (data.entered_card) {
    playCardVideo(data.entered_card.video_url, () => {
      playCardStartSfx(data.entered_card.audio_url);
    });
    const cardLabel = data.entered_card.title || data.entered_card.card_id || '未知卡片';
    enterCardPhase(cardLabel, null);

    // 异步拉取 AI 入场叙事，加载完成后再显示初始行动选项
    const initialActions = data.entered_card.initial_actions || [];
    fetchCardEntryNarrative(initialActions);
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
  // 流式打字机渲染 NPC 回应
  const stream = renderMessageStream('npc');

  await new Promise((resolve) => {
    apiSSE(
      '/api/card_action', 'POST',
      { session_token: sessionToken, player_input: playerInput },
      (char) => stream.appendText(char),
      (data) => {
        if (!stream.getText() && data.npc_response) stream.appendText(data.npc_response);
        stream.finish();
        if (data.chapter_info) updateChapterInfo(data.chapter_info);
        if (data.stats) updateSidebarStats(data.stats);

        if (!data.card_done && data.judge) incrementCardRound();
        if (!data.card_done && data.options && data.options.length >= 1) {
          _appendNavOptionButtons(data.options.map((text, i) => ({
            label: ['A', 'B', 'C', 'D'][i] || String(i + 1), text,
          })));
        }

        if (data.effects_log && data.effects_log.length > 0) {
          const logText = data.effects_log.map(entry =>
            entry.replace(/^([a-z_]+)/, name => STAT_NAMES[name] || name)
          ).join('  ');
          renderMessage('system', `结算：${logText}`);
        }
        if (data.judge === 'win') renderMessage('system', '胜利！');
        else if (data.judge === 'lose') renderMessage('warning', '失败！');

        if (data.card_done) {
          exitCardPhase();
          if (data.daily_life) {
            enterDailyLifePhase();
            renderMessageTypewriter('narrative', data.daily_life.narrative, () => {
              const acts = data.daily_life.options || [];
              if (acts.length >= 1) {
                _appendNavOptionButtons(acts.map((t, i) => ({
                  label: ['A', 'B', 'C', 'D'][i] || String(i + 1), text: t,
                })));
              }
            });
          } else if (data.game_over) {
            renderMessage('warning', '游戏结束。');
          } else if (data.game_cleared) {
            renderMessage('main_story', '恭喜你完成了所有章节！感谢你的游玩。');
          } else {
            fetchNavNarrative();
          }
        }
        resolve();
      },
      (err) => {
        stream.finish();
        renderMessage('warning', `卡片行动请求失败（${err.message}），请重试`);
        resolve();
      },
      90000,
    );
  });
}

/**
 * 日常生活阶段：调用 POST /api/daily_life
 * @param {string} playerInput - 玩家选择的行动或自由输入
 */
async function handleDailyLifeAction(playerInput) {
  const stream = renderMessageStream('narrative');

  await new Promise((resolve) => {
    apiSSE(
      '/api/daily_life', 'POST',
      { session_token: sessionToken, player_input: playerInput },
      (char) => stream.appendText(char),
      (data) => {
        if (!stream.getText() && data.narrative) stream.appendText(data.narrative);
        stream.finish();
        if (data.chapter_info) updateChapterInfo(data.chapter_info);
        if (data.stats) updateSidebarStats(data.stats);

        if (data.done) {
          enterNavPhase();
          fetchNavNarrative();
        } else {
          const actions = data.options || [];
          if (actions.length >= 1) {
            _appendNavOptionButtons(actions.map((text, i) => ({
              label: ['A', 'B', 'C', 'D'][i] || String(i + 1), text,
            })));
          }
        }
        resolve();
      },
      (err) => {
        stream.finish();
        renderMessage('warning', `日常叙事请求失败（${err.message}），请重试`);
        resolve();
      },
      90000,
    );
  });
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
 * 切换到日常生活阶段：事件卡结束后的互动式日常过渡
 */
function enterDailyLifePhase() {
  currentPhase = 'daily_life';
  elPhaseLabel.textContent = '日常';
  elPlayerInput.placeholder = '选择或输入你想做的事…';
  elSidebarCard.classList.add('hidden');
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

  // 流式打字机渲染 narrative
  const stream = renderMessageStream('narrative');

  await apiSSE(
    `/api/nav?token=${encodeURIComponent(sessionToken)}`,
    'GET', null,
    (char) => stream.appendText(char),
    (data) => {
      // 兜底：状态机未提取到 token 时，用 done 数据中的完整文本补渲染
      if (!stream.getText() && data.narrative) stream.appendText(data.narrative);
      stream.finish();
      currentNavDirections = data.directions || [];
      if (data.chapter_info) updateChapterInfo(data.chapter_info);
      const options = data.options || [];
      if (options.length > 0) {
        const parsed = options.map((text, i) => ({
          label: ['A', 'B', 'C', 'D'][i] || String(i + 1),
          text: String(text || '').trim(),
          direction: currentNavDirections[i]?.direction || null,
        })).filter((o) => o.text);
        currentNavOptionTexts = parsed
          .filter(o => o.direction)
          .map(o => ({ direction: o.direction, text: o.text }));
        if (parsed.length > 0) _appendNavOptionButtons(parsed);
      }
    },
    (err) => {
      stream.finish();
      renderMessage('warning', `导航旁白加载失败（${err.message}），可输入方向继续`);
    },
    90000,
  );
}

/**
 * 异步拉取卡片入场叙事（AI 生成，进入卡片后调用）
 * 与导航旁白同理：先显示加载提示，AI 生成完成后替换为实际叙事，
 * 最后显示初始行动选项按钮，保证叙事在选项之前出现。
 * @param {string[]} initialActions - 卡片配置里的初始行动选项文字数组
 */
async function fetchCardEntryNarrative(initialActions) {
  if (!sessionToken) return;

  const stream = renderMessageStream('narrative');

  function showActions() {
    if (initialActions.length >= 2) {
      _appendNavOptionButtons(initialActions.map((text, i) => ({
        label: ['A', 'B', 'C', 'D'][i] || String(i + 1),
        text,
      })));
    }
  }

  await apiSSE(
    `/api/card_entry?token=${encodeURIComponent(sessionToken)}`,
    'GET', null,
    (char) => stream.appendText(char),
    (data) => {
      if (!stream.getText() && data.narrative) stream.appendText(data.narrative);
      stream.finish();
      showActions();
    },
    (err) => {
      stream.finish();
      renderMessage('warning', `入场叙事加载失败（${err.message}），可直接输入行动`);
      showActions();
    },
    90000,
  );
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

  // 将消息存入 localStorage，供刷新/继续游戏时恢复（恢复中不重复写入）
  if (!_suppressChatLogSave) {
    saveToChatLog({ type, content, speakerName });
  }
}

/**
 * 渲染导航旁白：正文作为叙事，末尾的选项渲染为可点击按钮
 *
 * 支持两种 AI 输出格式：
 *   格式1（标准）：A. 行动  B. 行动  C. 行动
 *   格式2（偶发）：**行动1** / **行动2** / **行动3**（加粗+斜杠）
 *
 * @param {string} content - AI 生成的导航文字
 */
function renderNavNarrative(content) {
  if (!content) return;
  try {
    const obj = JSON.parse(content);
    if (obj && typeof obj === 'object' && typeof obj.narrative === 'string' && Array.isArray(obj.options)) {
      renderMessage('narrative', obj.narrative);
      const parsedJson = obj.options.map((text, i) => ({
        label: ['A', 'B', 'C', 'D'][i] || String(i + 1),
        text: String(text || '').trim(),
        direction: currentNavDirections[i]?.direction || null,
      })).filter((o) => o.text);
      currentNavOptionTexts = parsedJson
        .filter(o => o.direction)
        .map(o => ({ direction: o.direction, text: o.text }));
      if (parsedJson.length > 0) _appendNavOptionButtons(parsedJson);
      return;
    }
  } catch (_) {}
  if (content.includes('"options"')) {
    const optionsMatch = content.match(/"options"\s*:\s*\[(.*?)\]/s);
    const options = [];
    if (optionsMatch) {
      const quoted = optionsMatch[1].match(/"((?:\\.|[^"\\])*)"/g) || [];
      quoted.forEach((q) => {
        const optionText = q.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\').replace(/\\n/g, '\n').trim();
        if (optionText) options.push(optionText);
      });
    }
    if (options.length > 0) {
      const narrativeMatch = content.match(/"narrative"\s*:\s*"((?:\\.|[^"\\])*)"/s);
      if (narrativeMatch) {
        const narrativeText = narrativeMatch[1].replace(/\\"/g, '"').replace(/\\\\/g, '\\').replace(/\\n/g, '\n').trim();
        if (narrativeText) renderMessage('narrative', narrativeText);
      }
      const parsedFallback = options.map((text, i) => ({
        label: ['A', 'B', 'C', 'D'][i] || String(i + 1),
        text,
        direction: currentNavDirections[i]?.direction || null,
      }));
      currentNavOptionTexts = parsedFallback
        .filter(o => o.direction)
        .map(o => ({ direction: o.direction, text: o.text }));
      _appendNavOptionButtons(parsedFallback);
      return;
    }
  }

  // ─── 格式1：A. / B. / C. 标准选项格式 ───
  const optionRegex = /[A-Ca-c][\.：:）)]\s*(.+)/g;
  const optionMatches = [...content.matchAll(optionRegex)];

  if (optionMatches.length >= 2) {
    const firstOptionIndex = content.search(/[A-Ca-c][\.：:）)]/);
    const mainText = content.slice(0, firstOptionIndex).trim();
    if (mainText) renderMessage('narrative', mainText);
    const parsed = optionMatches.map((m, i) => ({
      label:     m[0][0].toUpperCase(),
      text:      m[1].trim(),
      direction: currentNavDirections[i]?.direction || null,
    }));
    // 保存选项文字，供用户自由输入时语义匹配方向
    currentNavOptionTexts = parsed
      .filter(o => o.direction)
      .map(o => ({ direction: o.direction, text: o.text }));
    _appendNavOptionButtons(parsed);
    return;
  }

  // ─── 格式2：**选项** / **选项** 加粗斜杠格式（AI 偶发）───
  const boldRegex = /\*\*(.+?)\*\*/g;
  const boldMatches = [...content.matchAll(boldRegex)];

  if (boldMatches.length >= 2) {
    const firstBoldIndex = content.indexOf('**');
    const mainText = content.slice(0, firstBoldIndex).trim();
    if (mainText) renderMessage('narrative', mainText);
    const labels = ['A', 'B', 'C', 'D'];
    const parsed2 = boldMatches.map((m, i) => ({
      label:     labels[i] || String(i + 1),
      text:      m[1].trim(),
      direction: currentNavDirections[i]?.direction || null,
    }));
    currentNavOptionTexts = parsed2
      .filter(o => o.direction)
      .map(o => ({ direction: o.direction, text: o.text }));
    _appendNavOptionButtons(parsed2);
    return;
  }

  // ─── 无可识别选项格式 → 普通叙事渲染 ───
  renderMessage('narrative', content);
}

/**
 * 将选项数组渲染为一排可点击按钮，追加到消息列表
 * @param {{ label: string, text: string }[]} options
 */
/**
 * @param {{ label: string, text: string, direction?: string|null }[]} options
 *   direction 字段仅导航旁白选项携带，点击时直接发给后端跳过文字解析；
 *   卡片选项没有 direction，走普通输入流程。
 */
function _appendNavOptionButtons(options) {
  const el = document.createElement('div');
  el.classList.add('nav-options');

  options.forEach(({ label, text, direction }) => {
    const btn = document.createElement('button');
    btn.classList.add('btn', 'nav-option-btn');
    // label 字段保留兼容旧调用，但按钮仅显示模型原始选项文本
    btn.textContent = text;
    btn.addEventListener('click', () => {
      unlockCardStartAudio();
      stopCurrentAudio();
      if (isLoading) return;
      btn.disabled = true;
      // 点击后立即移除这组选项，防止重复点击和视觉残留
      el.remove();
      elPlayerInput.value = '';
      // 导航旁白按钮：直接携带方向，绕过文字解析，100% 准确
      // 卡片按钮：没有 direction，走普通文字输入流程
      sendInput(text, direction || null);
    });
    el.appendChild(btn);
  });

  elMessageList.appendChild(el);
  scrollToBottom();
}

/**
 * 清理消息流中所有历史选项按钮组
 * 用于玩家完成选择后立即收起旧选项，避免重复展示
 */
function clearAllOptionGroups() {
  elMessageList.querySelectorAll('.nav-options').forEach((node) => node.remove());
}

/**
 * 滚动消息列表到最底部（新消息出现后调用）
 */
function scrollToBottom() {
  elMessageList.scrollTop = elMessageList.scrollHeight;
}

/**
 * 将一条消息追加到 localStorage 对话历史
 * @param {{ type: string, content: string, speakerName: string|null }} msg
 */
function saveToChatLog(msg) {
  try {
    const raw = localStorage.getItem(CHAT_LOG_KEY);
    const log = raw ? JSON.parse(raw) : [];
    log.push(msg);
    // 最多保留 500 条，防止 localStorage 容量超限
    const trimmed = log.length > 500 ? log.slice(-500) : log;
    localStorage.setItem(CHAT_LOG_KEY, JSON.stringify(trimmed));
  } catch (e) {
    // 静默忽略（隐私模式或容量超限时不影响游戏）
  }
}

/**
 * 从 localStorage 恢复完整对话历史，渲染到消息列表
 * @returns {boolean} 是否成功恢复了历史记录
 */
function restoreChatLog() {
  try {
    const raw = localStorage.getItem(CHAT_LOG_KEY);
    if (!raw) return false;
    const log = JSON.parse(raw);
    if (!log || log.length === 0) return false;

    // 暂时禁止写入，避免还原时重复保存
    _suppressChatLogSave = true;
    log.forEach(({ type, content, speakerName }) => {
      renderMessage(type, content, speakerName || null);
    });
    _suppressChatLogSave = false;
    return true;
  } catch (e) {
    _suppressChatLogSave = false;
    return false;
  }
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
  if (elMcpChapter) elMcpChapter.textContent = chapterName;

  // 更新坐标
  if (state.position) {
    updateSidebarPosition(state.position);
    if (elMcpPosition) elMcpPosition.textContent = `(${state.position[0]}, ${state.position[1]})`;
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
function updateChapterInfo(chapterInfo) {
  if (!chapterInfo) return;

  // 更新章节名称（章节推进时同步刷新）
  if (chapterInfo.name) {
    const label = `📍 ${chapterInfo.name}`;
    if (elSidebarChapter) elSidebarChapter.textContent = label;
    if (elMcpChapter) elMcpChapter.textContent = chapterInfo.name;
  }

  const background = chapterInfo.background || chapterInfo.chapter_background || '';
  const characters = chapterInfo.key_characters || chapterInfo.characters || [];
  const objectives = chapterInfo.objectives || chapterInfo.goals || [];

  if (elSidebarChapterBackground) {
    elSidebarChapterBackground.textContent = background || '-';
  }
  if (elSidebarChapterCharacters) {
    const chars = Array.isArray(characters) ? characters : [characters];
    const cleaned = chars.map((v) => String(v || '').trim()).filter(Boolean);
    elSidebarChapterCharacters.textContent = cleaned.length > 0 ? cleaned.join('\n') : '-';
  }
  if (elSidebarChapterObjectives) {
    elSidebarChapterObjectives.innerHTML = '';
    const goals = Array.isArray(objectives) ? objectives : [objectives];
    const cleanedGoals = goals.map((v) => String(v || '').trim()).filter(Boolean);
    if (cleanedGoals.length === 0) {
      const li = document.createElement('li');
      li.textContent = '-';
      elSidebarChapterObjectives.appendChild(li);
    } else {
      cleanedGoals.forEach((goal) => {
        const li = document.createElement('li');
        li.textContent = goal;
        elSidebarChapterObjectives.appendChild(li);
      });
    }
  }

  // 同步更新手机端章节面板
  if (elMcpBackground) elMcpBackground.textContent = background || '-';
  if (elMcpCharacters) {
    const chars = Array.isArray(characters) ? characters : [characters];
    elMcpCharacters.textContent = chars.map((v) => String(v || '').trim()).filter(Boolean).join('\n') || '-';
  }
  if (elMcpObjectives) {
    elMcpObjectives.innerHTML = '';
    const goals = Array.isArray(objectives) ? objectives : [objectives];
    goals.map((v) => String(v || '').trim()).filter(Boolean).forEach((goal) => {
      const li = document.createElement('li');
      li.textContent = goal;
      elMcpObjectives.appendChild(li);
    });
    if (!elMcpObjectives.children.length) {
      const li = document.createElement('li'); li.textContent = '-';
      elMcpObjectives.appendChild(li);
    }
  }
}

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
          <span>生命</span>
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

    // 获取图标（未知字段用 📦）和中文名（未知字段直接显示 key）
    const icon = STAT_ICONS[key] !== undefined ? STAT_ICONS[key] : '📦';
    const name = STAT_NAMES[key] !== undefined ? STAT_NAMES[key] : key;

    const row = document.createElement('div');
    row.classList.add('stat-row');
    row.innerHTML = `
      <span class="stat-icon">${icon}</span>
      <span class="stat-name">${name}</span>
      <span class="stat-value">${val}</span>
    `;
    elSidebarStats.appendChild(row);
  }

  // 同步更新手机端紧凑状态条
  updateMobileStatsBar(stats);
}

/**
 * 更新手机端状态条（仅手机端可见，侧边栏的紧凑替代）
 * @param {object} stats - { hp: 80, hp_max: 100, amulet: 60, ... }
 */
function updateMobileStatsBar(stats) {
  if (!elMobileStatsBar) return;
  elMobileStatsBar.innerHTML = '';

  for (const [key, val] of Object.entries(stats)) {
    if (key === 'hp_max') continue;           // hp_max 并入 hp 显示
    if (val === null || val === undefined) continue;
    if (val === 0) continue;                  // 值为 0 不显示

    const icon = STAT_ICONS[key] !== undefined ? STAT_ICONS[key] : '📦';
    const chip = document.createElement('span');
    chip.classList.add('mobile-stat-chip');

    if (key === 'hp') {
      // HP 显示 "❤️ 80/100"
      const hpMax = stats.hp_max || 100;
      chip.textContent = `${icon} ${val}/${hpMax}`;
    } else {
      chip.textContent = `${icon} ${val}`;
    }

    elMobileStatsBar.appendChild(chip);
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
   界面切换
   ============================================================ */

/** 显示开始界面，隐藏游戏界面 */
function showStartScreen() {
  elStartScreen.classList.remove('hidden');
  elIntroScreen.classList.add('hidden');
  elGameScreen.classList.add('hidden');
  if (elVideoScreen) elVideoScreen.classList.add('hidden');
}

/** 显示游戏介绍界面 */
function showIntroScreen() {
  elStartScreen.classList.add('hidden');
  elIntroScreen.classList.remove('hidden');
  elGameScreen.classList.add('hidden');
  if (elVideoScreen) elVideoScreen.classList.add('hidden');
  // 滚动回顶部（防止上次滚到底部）
  elIntroScreen.scrollTop = 0;
}

/** 显示开场视频界面并播放 */
function showVideoScreen() {
  // 若视频元素不存在（旧缓存），直接开始游戏
  if (!elVideoScreen || !elIntroVideo) {
    startNewGame();
    return;
  }
  _videoEnded = false;  // 重置互斥锁
  elStartScreen.classList.add('hidden');
  elIntroScreen.classList.add('hidden');
  elGameScreen.classList.add('hidden');
  elVideoScreen.classList.remove('hidden');
  elIntroVideo.currentTime = 0;
  elIntroVideo.play().catch(() => {
    // 自动播放被阻止 / 视频文件不存在时，直接跳过
    endVideoAndStart();
  });
}

/** 视频结束或跳过：隐藏视频界面，进入游戏（互斥，只执行一次） */
function endVideoAndStart() {
  if (_videoEnded) return;
  _videoEnded = true;
  if (elIntroVideo) elIntroVideo.pause();
  if (elVideoScreen) elVideoScreen.classList.add('hidden');
  startNewGame();
}

/** 显示游戏界面，隐藏开始界面 */
function showGameScreen() {
  elStartScreen.classList.add('hidden');
  elIntroScreen.classList.add('hidden');
  elGameScreen.classList.remove('hidden');
  // 聚焦输入框，方便直接打字
  elPlayerInput.focus();
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
 * SSE 流式请求工具
 * 读取 text/event-stream 响应，将 token/done/error 事件分发给回调。
 */
async function apiSSE(path, method, body, onToken, onDone, onError, timeoutMs = 90000) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const fetchOpts = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    };
    if (body) fetchOpts.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + path, fetchOpts);
    if (!resp.ok) {
      const t = await resp.text().catch(() => '');
      throw new Error(`HTTP ${resp.status}: ${t}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'token') onToken(evt.text);
          else if (evt.type === 'done') onDone(evt);
          else if (evt.type === 'error') onError?.(new Error(evt.message || 'SSE error'));
        } catch (_) { /* 忽略解析失败 */ }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      onError?.(new Error(`请求超时（>${Math.round(timeoutMs / 1000)}s）`));
    } else {
      onError?.(err);
    }
  } finally {
    clearTimeout(timerId);
  }
}

/**
 * 创建打字机消息元素，返回 { appendText(char), finish(fullContent?) }。
 * 样式类和 badge 与 renderMessage 一致。
 */
function renderMessageStream(type, speakerName) {
  // 懒创建：首个 token 到达时才生成 DOM，避免空气泡
  let el = null;
  let textNode = null;

  function _ensureEl() {
    if (el) return;
    el = document.createElement('div');
    el.classList.add('msg', `msg-${type}`);
    if (type === 'npc' && speakerName) {
      const s = document.createElement('span');
      s.classList.add('speaker-name');
      s.textContent = speakerName;
      el.appendChild(s);
    } else if (type === 'system') {
      const s = document.createElement('span');
      s.classList.add('tag');
      s.textContent = '系统';
      el.appendChild(s);
    } else if (type === 'warning') {
      const s = document.createElement('span');
      s.classList.add('tag');
      s.textContent = '警告';
      el.appendChild(s);
    }
    textNode = document.createTextNode('');
    el.appendChild(textNode);
    elMessageList.appendChild(el);
    scrollToBottom();
  }

  return {
    appendText(c) { _ensureEl(); textNode.textContent += c; scrollToBottom(); },
    getText() { return textNode ? textNode.textContent : ''; },
    finish(full) {
      const content = full ?? (textNode ? textNode.textContent : '');
      if (!_suppressChatLogSave && content) {
        saveToChatLog({ type, content, speakerName });
      }
    },
  };
}

/**
 * 本地打字机：将已有完整文本逐字显示（非 SSE，用于 done 事件中携带的文本）。
 */
function renderMessageTypewriter(type, text, onDone, interval) {
  if (!text) { onDone?.(); return; }
  const ms = interval ?? 18;
  const stream = renderMessageStream(type);
  let i = 0;
  (function tick() {
    if (i < text.length) { stream.appendText(text[i++]); setTimeout(tick, ms); }
    else { stream.finish(text); onDone?.(); }
  })();
}

/**
 * 带超时的 fetch 封装（默认 30 秒）
 * @param {string} url
 * @param {RequestInit} options
 * @param {number} timeoutMs - 超时毫秒数，默认 30000
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options, timeoutMs = 90000) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const resp = await fetch(url, { ...options, signal: controller.signal });
    return resp;
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(`请求超时（>${Math.round(timeoutMs / 1000)}s），请检查网络或后端状态`);
    }
    throw err;
  } finally {
    clearTimeout(timerId);
  }
}
