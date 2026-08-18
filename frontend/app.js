const API = {
  health: "/health",
  models: "/v1/models",
  chat: "/v1/chat/completions",
  routers: "/routers",
  system: "/api/system",
  routerConfig: "/api/router/config",
  metrics: "/api/metrics",
  logs: "/api/logs",
  configurableModels: "/api/models",
  experiments: "/api/experiments",
  runExperiment: "/api/experiments/run",
  experimentReport: "/api/experiments/report",
  experimentChartData: "/api/experiments/chart-data",
  feedback: "/api/feedback",
  experienceMetrics: "/api/experience/metrics",
  abCompare: "/api/chat/compare",
};

const storageKey = "llmrouter-console-state-v1";
const state = {
  system: null,
  models: [],
  sessions: [],
  activeSessionId: null,
  requestCount: 0,
  routeLog: [],
  routerConfig: null,
  metrics: null,
  logs: [],
  experiments: null,
  lastRouting: null,
  editingModelId: null,
  sending: false,
  settings: {
    temperature: 0.7,
    maxTokens: 1024,
    systemPrompt: "",
    solveMode: "single",
    dispatchMode: "conservative",
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const solveModeDispatchOptions = {
  single: [],
  static_multi: [
    { value: "conservative", label: "串行" },
  ],
  dynamic_subtasks: [
    { value: "conservative", label: "串行" },
    { value: "balanced", label: "DAG图" },
    { value: "fast", label: "并行" },
  ],
};

const mainExperimentAlgorithmIds = new Set(["graphrouter", "knnrouter", "dcrouter", "automixrouter"]);

const serviceStrategyAlgorithmOptions = {
  llmrouter: "all",
};

const elements = {
  sidebar: $("#sidebar"),
  menuButton: $("#menuButton"),
  newChatButton: $("#newChatButton"),
  clearSessionsButton: $("#clearSessionsButton"),
  sessionList: $("#sessionList"),
  viewTitle: $("#viewTitle"),
  viewSubtitle: $("#viewSubtitle"),
  modelSelect: $("#modelSelect"),
  solveModeSelect: $("#solveModeSelect"),
  dispatchModeSelect: $("#dispatchModeSelect"),
  refreshButton: $("#refreshButton"),
  settingsButton: $("#settingsButton"),
  messageList: $("#messageList"),
  welcomeState: $("#welcomeState"),
  messageInput: $("#messageInput"),
  sendButton: $("#sendButton"),
  compareButton: $("#compareButton"),
  composerHint: $("#composerHint"),
  selectedModelName: $("#selectedModelName"),
  routeState: $("#routeState"),
  strategyValue: $("#strategyValue"),
  solveModeValue: $("#solveModeValue"),
  dispatchModeValue: $("#dispatchModeValue"),
  algorithmValue: $("#algorithmValue"),
  latencyValue: $("#latencyValue"),
  requestCountValue: $("#requestCountValue"),
  routeLog: $("#routeLog"),
  routeReason: $("#routeReason"),
  routeStepList: $("#routeStepList"),
  candidateList: $("#candidateList"),
  sidebarStatusDot: $("#sidebarStatusDot"),
  sidebarStatusText: $("#sidebarStatusText"),
  routerHealthBadge: $("#routerHealthBadge"),
  routingStrategyName: $("#routingStrategyName"),
  routingAlgorithmName: $("#routingAlgorithmName"),
  routingConfigPath: $("#routingConfigPath"),
  prefixFeatureValue: $("#prefixFeatureValue"),
  routerLoadedValue: $("#routerLoadedValue"),
  serviceStrategySelect: $("#serviceStrategySelect"),
  algorithmRouterSelect: $("#algorithmRouterSelect"),
  algorithmSelectField: $("#algorithmSelectField"),
  applyRouterButton: $("#applyRouterButton"),
  serviceStrategyCount: $("#serviceStrategyCount"),
  algorithmRouterCount: $("#algorithmRouterCount"),
  serviceCatalogList: $("#serviceCatalogList"),
  algorithmCatalogList: $("#algorithmCatalogList"),
  modelCountBadge: $("#modelCountBadge"),
  modelGrid: $("#modelGrid"),
  addModelButton: $("#addModelButton"),
  modelModalBackdrop: $("#modelModalBackdrop"),
  modelModal: $("#modelModal"),
  modelModalTitle: $("#modelModalTitle"),
  closeModelModalButton: $("#closeModelModalButton"),
  cancelModelButton: $("#cancelModelButton"),
  modelForm: $("#modelForm"),
  saveModelButton: $("#saveModelButton"),
  modelIdInput: $("#modelIdInput"),
  modelProviderInput: $("#modelProviderInput"),
  modelApiNameInput: $("#modelApiNameInput"),
  modelBaseUrlInput: $("#modelBaseUrlInput"),
  modelChatPathInput: $("#modelChatPathInput"),
  modelAuthModeInput: $("#modelAuthModeInput"),
  modelApiKeyInput: $("#modelApiKeyInput"),
  apiKeyHint: $("#apiKeyHint"),
  modelContextLimitInput: $("#modelContextLimitInput"),
  modelMaxTokensInput: $("#modelMaxTokensInput"),
  modelInputPriceInput: $("#modelInputPriceInput"),
  modelOutputPriceInput: $("#modelOutputPriceInput"),
  modelAutoRoutableInput: $("#modelAutoRoutableInput"),
  modelDescriptionInput: $("#modelDescriptionInput"),
  refreshMetricsButton: $("#refreshMetricsButton"),
  runExperimentButton: $("#runExperimentButton"),
  runRealExperimentButton: $("#runRealExperimentButton"),
  runPilotExperimentButton: $("#runPilotExperimentButton"),
  exportExperimentButton: $("#exportExperimentButton"),
  metricRequests: $("#metricRequests"),
  metricSuccessRate: $("#metricSuccessRate"),
  metricLatency: $("#metricLatency"),
  metricFallbacks: $("#metricFallbacks"),
  modelUsageBars: $("#modelUsageBars"),
  modelHealthList: $("#modelHealthList"),
  experimentBasisText: $("#experimentBasisText"),
  experimentWeights: $("#experimentWeights"),
  experimentTaskCount: $("#experimentTaskCount"),
  experimentTaskList: $("#experimentTaskList"),
  experimentBestStrategy: $("#experimentBestStrategy"),
  experimentStrategyList: $("#experimentStrategyList"),
  experimentTableBody: $("#experimentTableBody"),
  experimentProcessList: $("#experimentProcessList"),
  experimentCaseList: $("#experimentCaseList"),
  refreshLogsButton: $("#refreshLogsButton"),
  logTableBody: $("#logTableBody"),
  systemHealthBadge: $("#systemHealthBadge"),
  systemStatusValue: $("#systemStatusValue"),
  systemStrategyValue: $("#systemStrategyValue"),
  systemModelCountValue: $("#systemModelCountValue"),
  endpointList: $("#endpointList"),
  settingsDrawer: $("#settingsDrawer"),
  drawerBackdrop: $("#drawerBackdrop"),
  closeSettingsButton: $("#closeSettingsButton"),
  temperatureInput: $("#temperatureInput"),
  temperatureOutput: $("#temperatureOutput"),
  routerLoadedValue: $("#routerLoadedValue"),
  serviceStrategySelect: $("#serviceStrategySelect"),
  algorithmRouterSelect: $("#algorithmRouterSelect"),
  algorithmSelectField: $("#algorithmSelectField"),
  applyRouterButton: $("#applyRouterButton"),
  serviceStrategyCount: $("#serviceStrategyCount"),
  algorithmRouterCount: $("#algorithmRouterCount"),
  serviceCatalogList: $("#serviceCatalogList"),
  algorithmCatalogList: $("#algorithmCatalogList"),
  modelCountBadge: $("#modelCountBadge"),
  modelGrid: $("#modelGrid"),
  addModelButton: $("#addModelButton"),
  modelModalBackdrop: $("#modelModalBackdrop"),
  modelModal: $("#modelModal"),
  modelModalTitle: $("#modelModalTitle"),
  closeModelModalButton: $("#closeModelModalButton"),
  cancelModelButton: $("#cancelModelButton"),
  modelForm: $("#modelForm"),
  saveModelButton: $("#saveModelButton"),
  modelIdInput: $("#modelIdInput"),
  modelProviderInput: $("#modelProviderInput"),
  modelApiNameInput: $("#modelApiNameInput"),
  modelBaseUrlInput: $("#modelBaseUrlInput"),
  modelChatPathInput: $("#modelChatPathInput"),
  modelAuthModeInput: $("#modelAuthModeInput"),
  modelApiKeyInput: $("#modelApiKeyInput"),
  apiKeyHint: $("#apiKeyHint"),
  modelContextLimitInput: $("#modelContextLimitInput"),
  modelMaxTokensInput: $("#modelMaxTokensInput"),
  modelInputPriceInput: $("#modelInputPriceInput"),
  modelOutputPriceInput: $("#modelOutputPriceInput"),
  modelAutoRoutableInput: $("#modelAutoRoutableInput"),
  modelDescriptionInput: $("#modelDescriptionInput"),
  refreshMetricsButton: $("#refreshMetricsButton"),
  runExperimentButton: $("#runExperimentButton"),
  runRealExperimentButton: $("#runRealExperimentButton"),
  runPilotExperimentButton: $("#runPilotExperimentButton"),
  exportExperimentButton: $("#exportExperimentButton"),
  metricRequests: $("#metricRequests"),
  metricSuccessRate: $("#metricSuccessRate"),
  metricLatency: $("#metricLatency"),
  metricFallbacks: $("#metricFallbacks"),
  modelUsageBars: $("#modelUsageBars"),
  modelHealthList: $("#modelHealthList"),
  experimentBasisText: $("#experimentBasisText"),
  experimentWeights: $("#experimentWeights"),
  experimentTaskCount: $("#experimentTaskCount"),
  experimentTaskList: $("#experimentTaskList"),
  experimentBestStrategy: $("#experimentBestStrategy"),
  experimentStrategyList: $("#experimentStrategyList"),
  experimentTableBody: $("#experimentTableBody"),
  experimentProcessList: $("#experimentProcessList"),
  experimentCaseList: $("#experimentCaseList"),
  refreshLogsButton: $("#refreshLogsButton"),
  logTableBody: $("#logTableBody"),
  systemHealthBadge: $("#systemHealthBadge"),
  systemStatusValue: $("#systemStatusValue"),
  systemStrategyValue: $("#systemStrategyValue"),
  systemModelCountValue: $("#systemModelCountValue"),
  endpointList: $("#endpointList"),
  settingsDrawer: $("#settingsDrawer"),
  drawerBackdrop: $("#drawerBackdrop"),
  closeSettingsButton: $("#closeSettingsButton"),
  temperatureInput: $("#temperatureInput"),
  temperatureOutput: $("#temperatureOutput"),
  maxTokensInput: $("#maxTokensInput"),
  systemPromptInput: $("#systemPromptInput"),
  clearChatButton: $("#clearChatButton"),
  toast: $("#toast"),
  paretoChart: $("#paretoChart"),
  radarChart: $("#radarChart"),
  taskBarChart: $("#taskBarChart"),
  utilityBarChart: $("#utilityBarChart"),
  chartSummaryGrid: $("#chartSummaryGrid"),
  refreshChartButton: $("#refreshChartButton"),
  refreshSchedulerButton: $("#refreshSchedulerButton"),
  runSchedulerButton: $("#runSchedulerButton"),
  schedulerResultHint: $("#schedulerResultHint"),
  schedulerResultGrid: $("#schedulerResultGrid"),
  schedulerAssignmentList: $("#schedulerAssignmentList"),
};

const chartInstances = {
  pareto: null,
  radar: null,
  taskBar: null,
  utilityBar: null,
};

function uid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function activeSession() {
  return state.sessions.find((item) => item.id === state.activeSessionId);
}

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    state.sessions = Array.isArray(saved.sessions) ? saved.sessions : [];
    state.activeSessionId = saved.activeSessionId || state.sessions[0]?.id || null;
    state.requestCount = Number(saved.requestCount || 0);
    state.routeLog = Array.isArray(saved.routeLog) ? saved.routeLog.slice(0, 8) : [];
    state.settings = { ...state.settings, ...(saved.settings || {}) };
  } catch {
    state.sessions = [];
  }
}

function saveState() {
  localStorage.setItem(
    storageKey,
    JSON.stringify({
      sessions: state.sessions.slice(0, 20),
      activeSessionId: state.activeSessionId,
      requestCount: state.requestCount,
      routeLog: state.routeLog.slice(0, 8),
      settings: state.settings,
    }),
  );
}

function createSession() {
  const session = {
    id: uid(),
    title: "新对话",
    createdAt: Date.now(),
    messages: [],
    selectedModel: "auto",
  };
  state.sessions.unshift(session);
  state.activeSessionId = session.id;
  saveState();
  renderSessions();
  renderMessages();
  elements.messageInput.focus();
}

function ensureSession() {
  if (!activeSession()) createSession();
  return activeSession();
}

function renderSessions() {
  elements.sessionList.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-log";
    empty.textContent = "暂无历史对话";
    elements.sessionList.append(empty);
    return;
  }

  for (const session of state.sessions) {
    const item = document.createElement("div");
    item.className = `session-item${session.id === state.activeSessionId ? " active" : ""}`;

    const open = document.createElement("button");
    open.type = "button";
    open.textContent = session.title;
    open.title = session.title;
    open.addEventListener("click", () => {
      state.activeSessionId = session.id;
      elements.modelSelect.value = session.selectedModel || "auto";
      saveState();
      renderSessions();
      renderMessages();
      setView("chat");
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "session-delete";
    remove.textContent = "×";
    remove.title = "删除对话";
    remove.addEventListener("click", () => deleteSession(session.id));

    item.append(open, remove);
    elements.sessionList.append(item);
  }
}

function deleteSession(id) {
  state.sessions = state.sessions.filter((item) => item.id !== id);
  if (state.activeSessionId === id) {
    state.activeSessionId = state.sessions[0]?.id || null;
  }
  saveState();
  renderSessions();
  renderMessages();
}

function clearSessions() {
  state.sessions = [];
  state.activeSessionId = null;
  saveState();
  renderSessions();
  renderMessages();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderTextBlock(text) {
  let safe = escapeHtml(text);
  safe = safe.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  const lines = safe.split("\n");
  const output = [];
  let listType = null;
  for (const line of lines) {
    const bullet = line.match(/^\s*[-*]\s+(.+)/);
    const ordered = line.match(/^\s*\d+\.\s+(.+)/);
    if (bullet || ordered) {
      const nextType = bullet ? "ul" : "ol";
      if (listType !== nextType) {
        if (listType) output.push(`</${listType}>`);
        output.push(`<${nextType}>`);
        listType = nextType;
      }
      output.push(`<li>${bullet?.[1] || ordered?.[1]}</li>`);
      continue;
    }
    if (listType) {
      output.push(`</${listType}>`);
      listType = null;
    }
    if (line.trim()) output.push(`<p>${line}</p>`);
  }
  if (listType) output.push(`</${listType}>`);
  return output.join("");
}

function formatMessage(text) {
  const chunks = String(text).split(/```/);
  return chunks
    .map((chunk, index) => {
      if (index % 2 === 0) return renderTextBlock(chunk);
      const firstBreak = chunk.indexOf("\n");
      const language = firstBreak >= 0 ? chunk.slice(0, firstBreak).trim() : "";
      const code = firstBreak >= 0 ? chunk.slice(firstBreak + 1) : chunk;
      return `<pre data-language="${escapeHtml(language || "code")}"><code>${escapeHtml(code.trim())}</code></pre>`;
    })
    .join("");
}

function createMessageNode(message) {
  const article = document.createElement("article");
  article.className = `message ${message.role}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = message.role === "user" ? "我" : "AI";

  const content = document.createElement("div");
  const head = document.createElement("div");
  head.className = "message-head";

  const name = document.createElement("strong");
  name.textContent = message.role === "user" ? "你" : message.model || "LLMRouter";

  const time = document.createElement("span");
  time.textContent = new Date(message.createdAt || Date.now()).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const copy = document.createElement("button");
  copy.className = "message-copy";
  copy.type = "button";
  copy.title = "复制消息";
  copy.textContent = "⎘";
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(message.content);
    showToast("消息已复制");
  });

  head.append(name, time, copy);
  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = formatMessage(message.content);
  content.append(head, body);
  if (message.role === "assistant" && message.routing) {
    content.append(createRoutingCard(message.routing, message.model));
  }
  if (message.role === "assistant" && message.model && message.model !== "系统") {
    content.append(createFeedbackActions(message));
  }
  article.append(avatar, content);
  return article;
}

function createFeedbackActions(message) {
  const wrap = document.createElement("div");
  wrap.className = "message-feedback";
  const label = document.createElement("span");
  label.textContent = message.feedback
    ? `已反馈：${message.feedback === "up" ? "满意" : "不满意"}`
    : "评价回答与路由";
  const reason = document.createElement("select");
  reason.title = "反馈原因";
  const reasons = [
    ["answer_correct", "回答正确且模型合适"],
    ["too_slow", "回答正确但太慢"],
    ["too_expensive", "回答正确但太贵"],
    ["answer_wrong", "回答错误"],
    ["incomplete", "拒答或内容不完整"],
    ["wrong_model", "路由模型不合适"],
  ];
  for (const [value, text] of reasons) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    reason.append(option);
  }
  const up = document.createElement("button");
  up.type = "button"; up.title = "满意"; up.textContent = "👍";
  const down = document.createElement("button");
  down.type = "button"; down.title = "不满意"; down.textContent = "👎";
  up.disabled = Boolean(message.feedback); down.disabled = Boolean(message.feedback);
  reason.disabled = Boolean(message.feedback);
  up.addEventListener("click", () => submitMessageFeedback(message, "up", reason.value));
  down.addEventListener("click", () => submitMessageFeedback(
    message, "down", reason.value === "answer_correct" ? "answer_wrong" : reason.value,
  ));
  wrap.append(label, reason, up, down);
  return wrap;
}

async function submitMessageFeedback(message, rating, reason = "") {
  try {
    let correctedAnswer = "";
    let preferredModel = "";
    let feedbackText = "";
    if (rating === "down" && ["answer_wrong", "incomplete"].includes(reason)) {
      correctedAnswer = window.prompt("可选：请提供正确答案或期望补充的内容", "") || "";
    }
    if (["wrong_model", "too_slow", "too_expensive"].includes(reason)) {
      preferredModel = window.prompt("可选：你认为更合适的模型名称", "") || "";
    }
    if (rating === "down") {
      feedbackText = window.prompt("可选：补充说明问题原因", "") || "";
    }
    const response = await fetch(API.feedback, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: message.routing?.request_id || null,
        query: message.query || "",
        model: message.routing?.selected_model || message.model,
        rating, reason,
        corrected_answer: correctedAnswer || null,
        preferred_model: preferredModel || null,
        feedback_text: feedbackText || null,
        latency_ms: message.routing?.latency_ms || 0,
        fallback_count: Array.isArray(message.routing?.fallbacks) ? message.routing.fallbacks.length : 0,
        strategy: message.routing?.strategy || "",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "反馈提交失败");
    message.feedback = rating;
    message.feedbackReason = reason;
    message.verificationStatus = payload.experience?.verification_status || null;
    saveState(); renderMessages(); await refreshLogs();
    showToast(payload.message || "反馈已记录");
  } catch (error) {
    showToast(error.message);
  }
}

function createRoutingCard(routing = {}, messageModel = "") {
  const selectedModel = routing.selected_model || messageModel || "-";
  const initialModel = routing.initial_model && routing.initial_model !== selectedModel
    ? routing.initial_model
    : "";
  const allScores = Object.entries(routing.candidate_scores || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  const scoreLimit = 4;
  const scores = allScores.slice(0, scoreLimit);
  const multiSteps = Array.isArray(routing.multi_step) ? routing.multi_step : [];
  const fallbackText = routing.fallbacks?.length
    ? `原计划调用 ${initialModel || routing.fallbacks[0]?.model || "其他模型"}，失败后自动降级到 ${selectedModel}。`
    : "";
  const constraintText = routing.constraints
    ? `约束：质量≥${percent(routing.constraints.min_quality)} · 成本≤${percent(routing.constraints.max_cost)} · 延迟≤${percent(routing.constraints.max_latency)} · 可靠≥${percent(routing.constraints.min_reliability)}`
    : "";
  const paretoText = Array.isArray(routing.pareto_front) && routing.pareto_front.length
    ? `Pareto 前沿：${routing.pareto_front.join("、")}`
    : "";
  const nonlinearText = routing.nonlinear_score != null
    ? `非线性效用：${(Number(routing.nonlinear_score || 0) * 100).toFixed(1)}%${routing.linear_score != null ? ` · 线性基线：${(Number(routing.linear_score || 0) * 100).toFixed(1)}%` : ""}`
    : "";
  const riskText = routing.risk_level || routing.domain
    ? `风险等级：${routing.risk_level || "-"} · 领域：${routing.domain || "-"}`
    : "";
  const uncertaintyText = routing.confidence != null || routing.uncertainty != null
    ? `路由置信度：${(Number(routing.confidence || 0) * 100).toFixed(1)}% · 不确定性：${(Number(routing.uncertainty || 0) * 100).toFixed(1)}%${routing.score_margin != null ? ` · 分差：${Number(routing.score_margin || 0).toFixed(3)}` : ""}`
    : "";
  const escalationText = Array.isArray(routing.escalation_chain) && routing.escalation_chain.length
    ? `级联升级链：${routing.escalation_chain.join(" → ")}`
    : "";
  const overheadText = routing.router_overhead_ms != null
    ? `路由器自身开销：${Number(routing.router_overhead_ms || 0).toFixed(2)} ms${routing.router_overhead_ratio != null ? ` · 占总耗时 ${(Number(routing.router_overhead_ratio || 0) * 100).toFixed(2)}%` : ""}`
    : "";

  const card = document.createElement("section");
  card.className = "message-routing-card";
  card.innerHTML = `
    <div class="message-routing-head">
      <strong>路由决策依据</strong>
      <span>${escapeHtml(selectedModel)}</span>
    </div>
    <div class="message-routing-grid">
      <div>
        <small>服务策略</small>
        <b>${escapeHtml(routing.strategy || "manual")}</b>
      </div>
      <div>
        <small>算法路由器</small>
        <b>${escapeHtml(routing.algorithm || "服务层直接选择")}</b>
      </div>
      <div>
        <small>调度策略</small>
        <b>${escapeHtml(routing.dispatch_mode_label || dispatchModeLabel(routing.dispatch_mode) || "-")}</b>
      </div>
      <div>
        <small>最终模型</small>
        <b>${escapeHtml(selectedModel)}</b>
      </div>
    </div>
    <p>${escapeHtml(routing.reason || "本轮未返回详细路由理由。")}</p>
    ${fallbackText ? `<p class="routing-fallback">${escapeHtml(fallbackText)}</p>` : ""}
    ${constraintText ? `<p>${escapeHtml(constraintText)}</p>` : ""}
    ${paretoText ? `<p>${escapeHtml(paretoText)}</p>` : ""}
    ${nonlinearText ? `<p>${escapeHtml(nonlinearText)}</p>` : ""}
    ${uncertaintyText ? `<p>${escapeHtml(uncertaintyText)}</p>` : ""}
    ${escalationText ? `<p>${escapeHtml(escalationText)}</p>` : ""}
    ${overheadText ? `<p>${escapeHtml(overheadText)}</p>` : ""}
    ${riskText ? `<p>${escapeHtml(riskText)}</p>` : ""}
    ${scores.length ? `
      <div class="message-score-list">
        <div class="message-score-head">
          <strong>候选效用排序 · Top ${Math.min(scoreLimit, allScores.length)} / ${allScores.length}</strong>
          ${allScores.length > scoreLimit ? '<button class="score-expand-button" type="button" aria-expanded="false">展开全部</button>' : ""}
        </div>
        ${allScores.map(([model, rawScore], index) => {
          const score = Math.max(0, Math.min(1, Number(rawScore) || 0));
          return `
            <div class="message-score-row${model === selectedModel ? " selected" : ""}${index >= scoreLimit ? " score-row-extra" : ""}">
              <span>${escapeHtml(model)}${model === selectedModel ? " · 已选" : ""}</span>
              <i><em style="width:${(score * 100).toFixed(1)}%"></em></i>
              <b>${(score * 100).toFixed(1)}%</b>
            </div>
          `;
        }).join("")}
      </div>
    ` : ""}
    ${multiSteps.length ? `
      <div class="message-step-list">
        <strong>${escapeHtml(routing.solve_mode_label || "多步求解过程")}</strong>
        ${multiSteps.map((step) => `
          <div class="message-step-row ${step.status === "failed" ? "failed" : ""}">
            <span>${Number(step.index || 0)}. ${escapeHtml(step.name || "步骤")}</span>
            <b>${escapeHtml(step.selected_model || "-")}</b>
            <small>${escapeHtml(step.local_replan ? "局部重规划/降级" : step.status || "success")}</small>
            <em>第 ${Number(step.parallel_group || 1)} 批${step.depends_on?.length ? ` · 依赖 ${step.depends_on.join(", ")}` : " · 无前置依赖"}</em>
            <p>${escapeHtml(step.excerpt || step.goal || "")}</p>
          </div>
        `).join("")}
      </div>
    ` : ""}
  `;
  const expandButton = card.querySelector(".score-expand-button");
  expandButton?.addEventListener("click", () => {
    const expanded = card.classList.toggle("scores-expanded");
    expandButton.textContent = expanded ? "收起" : "展开全部";
    expandButton.setAttribute("aria-expanded", String(expanded));
  });
  return card;
}

function solveModeLabel(mode) {
  return {
    single: "普通自动路由",
    static_multi: "静态多轮路由",
    dynamic_subtasks: "动态子任务调度",
  }[mode || "single"] || "普通自动路由";
}

function dispatchModeLabel(mode) {
  if (!mode) return "";
  return {
    conservative: "串行",
    balanced: "DAG图",
    fast: "并行",
  }[mode || "conservative"] || "串行";
}

function rebuildDispatchOptions(preferredValue = "") {
  if (!elements.dispatchModeSelect) return;
  const solveMode = elements.solveModeSelect?.value || state.settings.solveMode || "single";
  const options = solveModeDispatchOptions[solveMode] || [];
  const previous = preferredValue || elements.dispatchModeSelect.value || state.settings.dispatchMode || "";
  elements.dispatchModeSelect.replaceChildren();
  if (!options.length) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "无对应调度策略";
    elements.dispatchModeSelect.append(empty);
    elements.dispatchModeSelect.value = "";
    elements.dispatchModeSelect.disabled = true;
    elements.dispatchModeSelect.closest(".model-control")?.classList.add("disabled");
    state.settings.dispatchMode = "";
    return;
  }
  for (const item of options) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    elements.dispatchModeSelect.append(option);
  }
  const validPrevious = options.some((item) => item.value === previous);
  elements.dispatchModeSelect.value = validPrevious ? previous : options[0].value;
  elements.dispatchModeSelect.disabled = false;
  elements.dispatchModeSelect.closest(".model-control")?.classList.remove("disabled");
  state.settings.dispatchMode = elements.dispatchModeSelect.value;
}

function createLoadingNode() {
  const article = document.createElement("article");
  article.className = "message assistant";
  article.id = "loadingMessage";
  article.innerHTML = `
    <div class="message-avatar">AI</div>
    <div>
      <div class="message-head"><strong>正在路由并生成回答</strong></div>
      <div class="loading-dots"><i></i><i></i><i></i></div>
    </div>
  `;
  return article;
}

function renderMessages() {
  elements.messageList.replaceChildren();
  const session = activeSession();
  if (!session?.messages.length) {
    elements.messageList.append(elements.welcomeState);
    return;
  }

  for (const message of session.messages) {
    elements.messageList.append(createMessageNode(message));
  }
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function renderRouteLog() {
  elements.routeLog.replaceChildren();
  if (!state.routeLog.length) {
    const empty = document.createElement("div");
    empty.className = "empty-log";
    empty.textContent = "发送消息后显示路由结果";
    elements.routeLog.append(empty);
    return;
  }

  for (const item of state.routeLog) {
    const node = document.createElement("div");
    node.className = "route-log-item";
    const model = document.createElement("strong");
    model.textContent = item.model;
    const meta = document.createElement("span");
    meta.textContent = `${item.latency} · ${new Date(item.time).toLocaleTimeString("zh-CN")}`;
    node.append(model, meta);
    elements.routeLog.append(node);
  }
}

function renderRoutingDetails(routing = state.lastRouting) {
  elements.candidateList.replaceChildren();
  elements.routeStepList?.replaceChildren();
  if (!routing) {
    if (elements.solveModeValue) elements.solveModeValue.textContent = "-";
    if (elements.dispatchModeValue) elements.dispatchModeValue.textContent = "-";
    if (elements.routeStepList) {
      const emptyStep = document.createElement("div");
      emptyStep.className = "empty-log";
      emptyStep.textContent = "普通模式没有拆解步骤；选择静态多轮或动态子任务后会显示过程";
      elements.routeStepList.append(emptyStep);
    }
    elements.routeReason.textContent = "等待路由结果";
    const empty = document.createElement("div");
    empty.className = "empty-log";
    empty.textContent = "暂无候选评分";
    elements.candidateList.append(empty);
    return;
  }

  elements.routeReason.textContent = routing.reason || "本轮未提供路由说明。";
  if (elements.solveModeValue) {
    elements.solveModeValue.textContent = solveModeLabel(routing.solve_mode || "single");
  }
  if (elements.dispatchModeValue) {
    elements.dispatchModeValue.textContent = routing.dispatch_mode_label || dispatchModeLabel(routing.dispatch_mode);
  }
  const steps = Array.isArray(routing.multi_step) ? routing.multi_step : [];
  if (elements.routeStepList) {
    if (!steps.length) {
      const emptyStep = document.createElement("div");
      emptyStep.className = "empty-log";
      emptyStep.textContent = "本次使用普通自动路由：只选择一个最终模型，没有拆解子任务。";
      elements.routeStepList.append(emptyStep);
    } else {
      for (const step of steps) {
        const node = document.createElement("div");
        node.className = `route-step-item ${["failed", "timeout", "blocked"].includes(step.status) ? "failed" : ""}`;
        const depends = Array.isArray(step.depends_on) && step.depends_on.length
          ? `依赖步骤：${step.depends_on.join(", ")}`
          : "无前置依赖";
        node.innerHTML = `
          <div>
            <strong>${Number(step.index || 0)}. ${escapeHtml(step.name || "步骤")}</strong>
            <span>${escapeHtml(step.local_replan ? "局部重规划/降级" : step.status || "success")}</span>
          </div>
          <small>模型：${escapeHtml(step.selected_model || "-")}</small>
          <em>第 ${Number(step.parallel_group || 1)} 批执行 · ${escapeHtml(depends)} · ${escapeHtml(step.dispatch_mode_label || dispatchModeLabel(step.dispatch_mode))}</em>
          <p>${escapeHtml(step.excerpt || step.goal || "")}</p>
        `;
        elements.routeStepList.append(node);
      }
    }
  }
  const scores = Object.entries(routing.candidate_scores || {}).sort((a, b) => b[1] - a[1]);
  if (!scores.length) {
    const empty = document.createElement("div");
    empty.className = "empty-log";
    empty.textContent = "当前策略没有候选评分";
    elements.candidateList.append(empty);
    return;
  }

  for (const [model, rawScore] of scores) {
    const score = Math.max(0, Math.min(1, Number(rawScore) || 0));
    const row = document.createElement("div");
    row.className = `candidate-row${model === routing.selected_model ? " selected" : ""}`;
    row.innerHTML = `
      <div class="candidate-label">
        <strong>${escapeHtml(model)}</strong>
        <span>${model === routing.selected_model ? "最终选择" : ""}</span>
      </div>
      <div class="candidate-track"><div class="candidate-fill" style="width:${(score * 100).toFixed(1)}%"></div></div>
      <span class="candidate-score">${(score * 100).toFixed(1)}%</span>
    `;
    elements.candidateList.append(row);
  }
}

function updateInspector() {
  const router = state.system?.router || {};
  elements.strategyValue.textContent = router.strategy || "-";
  elements.algorithmValue.textContent = router.algorithm || "服务层直接选择";
  elements.requestCountValue.textContent = String(state.requestCount);
  renderRouteLog();
  renderRoutingDetails();
}

function setRouteState(type, label) {
  elements.routeState.className = `route-state ${type}`;
  elements.routeState.textContent = label;
}

function resizeInput() {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 160)}px`;
}

function cleanModelPrefix(content, model) {
  const expression = new RegExp(`^\\[${String(model).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\]\\s*`);
  return String(content || "").replace(expression, "");
}

async function sendMessage(prompt) {
  const text = (prompt ?? elements.messageInput.value).trim();
  if (!text || state.sending) return;

  const session = ensureSession();
  if (session.messages.length === 0) {
    session.title = text.length > 22 ? `${text.slice(0, 22)}…` : text;
  }
  session.selectedModel = elements.modelSelect.value;
  session.messages.push({
    id: uid(),
    role: "user",
    content: text,
    createdAt: Date.now(),
  });

  elements.messageInput.value = "";
  resizeInput();
  state.sending = true;
  elements.sendButton.disabled = true;
  setRouteState("routing", "路由中");
  elements.selectedModelName.textContent = "正在选择模型";
  elements.latencyValue.textContent = "-";
  saveState();
  renderSessions();
  renderMessages();
  elements.messageList.append(createLoadingNode());
  elements.messageList.scrollTop = elements.messageList.scrollHeight;

  const messages = [];
  if (state.settings.systemPrompt.trim()) {
    messages.push({ role: "system", content: state.settings.systemPrompt.trim() });
  }
  messages.push(
    ...session.messages.map(({ role, content }) => ({ role, content })),
  );

  const startedAt = performance.now();
  const solveMode = elements.solveModeSelect?.value || state.settings.solveMode || "single";
  const dispatchMode = elements.dispatchModeSelect?.value || state.settings.dispatchMode || null;
  try {
    const response = await fetch(API.chat, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: elements.modelSelect.value,
        messages,
        temperature: state.settings.temperature,
        max_tokens: state.settings.maxTokens,
        stream: false,
        solve_mode: solveMode,
        dispatch_mode: dispatchMode,
        planning_session_id: session.id,
        planning_scope: 'session',
        verify_response: true,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
    }

    const selectedModel = data.model || "unknown";
    const rawContent = data.choices?.[0]?.message?.content || "模型没有返回文本内容。";
    const content = cleanModelPrefix(rawContent, selectedModel);
    const elapsed = `${((performance.now() - startedAt) / 1000).toFixed(2)} 秒`;

    state.requestCount += 1;
    state.lastRouting = data.routing || {
      selected_model: selectedModel,
      reason: "接口没有返回详细路由诊断。",
      candidate_scores: {},
    };
    session.messages.push({
      id: uid(),
      role: "assistant",
      content,
      model: selectedModel,
      query: text,
      routing: state.lastRouting,
      createdAt: Date.now(),
    });
    const fallbackLabel = state.lastRouting.fallbacks?.length
      ? ` · 已从 ${state.lastRouting.initial_model} 自动降级`
      : "";
    state.routeLog.unshift({
      model: `${selectedModel}${fallbackLabel}`,
      latency: elapsed,
      time: Date.now(),
    });
    state.routeLog = state.routeLog.slice(0, 8);
    elements.selectedModelName.textContent = selectedModel;
    elements.latencyValue.textContent = elapsed;
    setRouteState("done", "已完成");
    saveState();
    updateInspector();
    renderMessages();
    await Promise.all([refreshMetrics(), refreshLogs(), refreshExperiments()]);
  } catch (error) {
    session.messages.push({
      id: uid(),
      role: "assistant",
      content: `请求失败：${error.message}`,
      model: "系统",
      query: text,
      createdAt: Date.now(),
    });
    elements.selectedModelName.textContent = "请求失败";
    setRouteState("idle", "异常");
    saveState();
    renderMessages();
    showToast("模型请求失败，请查看服务状态");
  } finally {
    document.querySelector("#loadingMessage")?.remove();
    state.sending = false;
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
  }
}

function formatABCompareResult(payload) {
  const lines = ["### A/B 模型对比", ""];
  lines.push(`自动路由选择：${payload.routing?.selected_model || "-"}`);
  if (payload.routing?.reason) {
    lines.push(`路由理由：${payload.routing.reason}`);
  }
  if (payload.routing?.router_overhead_ms != null) {
    lines.push(`路由器自身开销：${Number(payload.routing.router_overhead_ms || 0).toFixed(2)} ms`);
  }
  lines.push("");
  for (const item of payload.results || []) {
    lines.push(`#### ${item.model}${item.role === "auto_routed" ? "（自动路由）" : "（基线）"}`);
    if (!item.ok) {
      lines.push(`调用失败：${item.error || "未知错误"}`, "");
      continue;
    }
    lines.push(`质量代理分：${(Number(item.quality_proxy || 0) * 100).toFixed(1)}%`);
    lines.push(`耗时：${Math.round(Number(item.latency_ms || 0))} ms`);
    lines.push(`成本：$${Number(item.raw_cost_usd || 0).toFixed(8)}`);
    lines.push("");
    lines.push(item.excerpt || item.answer || "无文本摘要");
    lines.push("");
  }
  return lines.join("\n");
}

async function runABCompare(prompt) {
  const text = (prompt ?? elements.messageInput.value).trim();
  if (!text || state.sending) return;
  const session = ensureSession();
  if (session.messages.length === 0) {
    session.title = text.length > 22 ? `${text.slice(0, 22)}…` : text;
  }
  session.messages.push({
    id: uid(),
    role: "user",
    content: text,
    createdAt: Date.now(),
  });
  elements.messageInput.value = "";
  resizeInput();
  state.sending = true;
  elements.sendButton.disabled = true;
  if (elements.compareButton) elements.compareButton.disabled = true;
  if (elements.compareButton) elements.compareButton.disabled = true;
  setRouteState("routing", "A/B 对比中");
  saveState();
  renderSessions();
  renderMessages();
  elements.messageList.append(createLoadingNode());

  const messages = [];
  if (state.settings.systemPrompt.trim()) {
    messages.push({ role: "system", content: state.settings.systemPrompt.trim() });
  }
  messages.push(...session.messages.map(({ role, content }) => ({ role, content })));

  try {
    const response = await fetch(API.abCompare, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        temperature: state.settings.temperature,
        max_tokens: Math.min(Number(state.settings.maxTokens || 768), 1024),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "A/B 对比失败");
    state.lastRouting = payload.routing;
    session.messages.push({
      id: uid(),
      role: "assistant",
      content: formatABCompareResult(payload),
      model: "A/B 对比",
      query: text,
      routing: payload.routing,
      createdAt: Date.now(),
    });
    state.requestCount += 1;
    elements.selectedModelName.textContent = payload.routing?.selected_model || "A/B 对比";
    elements.latencyValue.textContent = payload.routing?.router_overhead_ms != null
      ? `路由 ${Number(payload.routing.router_overhead_ms || 0).toFixed(1)} ms`
      : "-";
    setRouteState("done", "已完成");
    saveState();
    updateInspector();
    renderMessages();
    await Promise.all([refreshMetrics(), refreshLogs()]);
  } catch (error) {
    session.messages.push({
      id: uid(),
      role: "assistant",
      content: `A/B 对比失败：${error.message}`,
      model: "系统",
      query: text,
      createdAt: Date.now(),
    });
    setRouteState("idle", "异常");
    saveState();
    renderMessages();
    showToast(error.message);
  } finally {
    document.querySelector("#loadingMessage")?.remove();
    state.sending = false;
    elements.sendButton.disabled = false;
    if (elements.compareButton) elements.compareButton.disabled = false;
    if (elements.compareButton) elements.compareButton.disabled = false;
    elements.messageInput.focus();
  }
}

function renderModels() {
  elements.modelGrid.replaceChildren();
  elements.modelCountBadge.textContent = `${state.models.length} 个模型`;
  for (const model of state.models) {
    const card = document.createElement("article");
    card.className = `model-card${model.health?.status === "cooldown" ? " unavailable" : ""}`;
    const providerLabel = model.health?.status === "cooldown"
      ? "暂不可用"
      : model.provider || "model";
    const routingLabel = model.auto_routable ? "可参与自动路由" : "仅支持手动调用";
    card.innerHTML = `
      <div>
        <h3>${escapeHtml(model.id)}</h3>
        <p>${escapeHtml(model.description || "未提供模型说明")}</p>
      </div>
      <span class="provider-badge">${escapeHtml(providerLabel)}</span>
      <div class="model-meta">
        <span>实际模型：${escapeHtml(model.model_id || model.id)}</span>
        <span>上下文：${formatNumber(model.context_limit || 0)}</span>
        <span>价格：${Number(model.input_price || 0).toFixed(6)} / ${Number(model.output_price || 0).toFixed(6)}</span>
      </div>
      <div class="model-capability">
        <span>API Key：${model.api_key_configured ? "已配置" : "未配置"}</span>
        <strong class="${model.auto_routable ? "" : "manual-only"}">${routingLabel}</strong>
      </div>
      <div class="model-actions">
        <button class="model-action test-model" type="button">测试连接</button>
        <button class="model-action edit-model" type="button">修改配置</button>
        <button class="model-action danger delete-model" type="button">删除模型</button>
      </div>
    `;
    card.querySelector(".test-model").addEventListener("click", () => testModel(model.id));
    card.querySelector(".edit-model").addEventListener("click", () => openModelModal(model));
    card.querySelector(".delete-model").addEventListener("click", () => deleteModel(model.id));
    elements.modelGrid.append(card);
  }
}

function resetModelForm() {
  elements.modelForm.reset();
  elements.modelChatPathInput.value = "/chat/completions";
  elements.modelAuthModeInput.value = "bearer";
  elements.modelContextLimitInput.value = "32768";
  elements.modelMaxTokensInput.value = "1024";
  elements.modelInputPriceInput.value = "0";
  elements.modelOutputPriceInput.value = "0";
  elements.modelAutoRoutableInput.checked = true;
  elements.modelIdInput.disabled = false;
  elements.apiKeyHint.textContent = "Key 只写入本地配置，接口不会回传明文。";
}

function openModelModal(model = null) {
  resetModelForm();
  state.editingModelId = model?.id || null;
  elements.modelModalTitle.textContent = model ? "修改模型配置" : "添加模型";
  elements.saveModelButton.textContent = model ? "保存修改" : "添加模型";

  if (model) {
    elements.modelIdInput.value = model.id;
    elements.modelIdInput.disabled = true;
    elements.modelProviderInput.value = model.provider || "";
    elements.modelApiNameInput.value = model.model_id || "";
    elements.modelBaseUrlInput.value = model.base_url || "";
    elements.modelChatPathInput.value = model.chat_path || "/chat/completions";
    elements.modelAuthModeInput.value = model.auth_mode || "bearer";
    elements.modelContextLimitInput.value = model.context_limit || 32768;
    elements.modelMaxTokensInput.value = model.max_tokens || 1024;
    elements.modelInputPriceInput.value = model.input_price || 0;
    elements.modelOutputPriceInput.value = model.output_price || 0;
    elements.modelAutoRoutableInput.checked = model.auto_routable !== false;
    elements.modelDescriptionInput.value = model.description || "";
    elements.apiKeyHint.textContent = model.api_key_configured
      ? "已有 API Key。留空会保留原 Key，填写新值会覆盖。"
      : "当前未配置 API Key。";
  }

  elements.modelModal.classList.add("open");
  elements.modelModalBackdrop.classList.add("open");
  elements.modelModal.setAttribute("aria-hidden", "false");
  setTimeout(() => (
    model ? elements.modelProviderInput : elements.modelIdInput
  ).focus(), 20);
}

function closeModelModal() {
  elements.modelModal.classList.remove("open");
  elements.modelModalBackdrop.classList.remove("open");
  elements.modelModal.setAttribute("aria-hidden", "true");
  state.editingModelId = null;
}

function modelFormPayload() {
  return {
    id: state.editingModelId || elements.modelIdInput.value.trim(),
    provider: elements.modelProviderInput.value.trim(),
    model_id: elements.modelApiNameInput.value.trim(),
    base_url: elements.modelBaseUrlInput.value.trim(),
    chat_path: elements.modelChatPathInput.value.trim(),
    auth_mode: elements.modelAuthModeInput.value,
    api_key: elements.modelApiKeyInput.value.trim() || null,
    context_limit: Number(elements.modelContextLimitInput.value),
    max_tokens: Number(elements.modelMaxTokensInput.value),
    input_price: Number(elements.modelInputPriceInput.value || 0),
    output_price: Number(elements.modelOutputPriceInput.value || 0),
    auto_routable: elements.modelAutoRoutableInput.checked,
    description: elements.modelDescriptionInput.value.trim(),
  };
}

async function saveModel(event) {
  event.preventDefault();
  const payload = modelFormPayload();
  const editing = Boolean(state.editingModelId);
  elements.saveModelButton.disabled = true;
  elements.saveModelButton.textContent = "正在保存";
  try {
    const endpoint = editing
      ? `${API.configurableModels}/${encodeURIComponent(state.editingModelId)}`
      : API.configurableModels;
    const response = await fetch(endpoint, {
      method: editing ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "模型配置保存失败");
    closeModelModal();
    await refreshSystem();
    showToast(editing ? `已更新模型 ${data.id}` : `已添加模型 ${data.id}`);
  } catch (error) {
    showToast(error.message);
  } finally {
    elements.saveModelButton.disabled = false;
    elements.saveModelButton.textContent = editing ? "保存修改" : "添加模型";
  }
}

async function deleteModel(modelId) {
  const confirmed = window.confirm(
    `确定删除模型“${modelId}”吗？\n\n这会同时从本地 YAML 配置中删除该模型。`,
  );
  if (!confirmed) return;
  try {
    const response = await fetch(
      `${API.configurableModels}/${encodeURIComponent(modelId)}`,
      { method: "DELETE" },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "模型删除失败");
    const session = activeSession();
    if (session?.selectedModel === modelId) session.selectedModel = "auto";
    await refreshSystem();
    showToast(`已删除模型 ${modelId}`);
  } catch (error) {
    showToast(error.message);
  }
}

async function testModel(modelId) {
  showToast(`正在测试 ${modelId}`);
  try {
    const response = await fetch(`${API.configurableModels}/${encodeURIComponent(modelId)}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: "你好，请用一句话回复模型连接正常。" }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "模型测试失败");
    await Promise.all([refreshMetrics(), refreshLogs(), refreshSystem()]);
    showToast(`${modelId} 测试成功，耗时 ${Math.round(data.latency_ms || 0)} ms`);
  } catch (error) {
    await refreshSystem();
    showToast(`${modelId} 测试失败：${error.message}`);
  }
}

function populateRouterSelectors() {
  const config = state.routerConfig;
  if (!config) return;
  elements.serviceStrategySelect.replaceChildren();
  for (const strategy of config.service_strategies || []) {
    const option = document.createElement("option");
    option.value = strategy.id;
    option.textContent = `${strategy.name}${strategy.available === false ? "（未配置）" : ""}`;
    option.disabled = strategy.available === false;
    option.title = strategy.note || strategy.description || "";
    elements.serviceStrategySelect.append(option);
  }
  elements.serviceStrategySelect.value = config.current?.strategy || "llmrouter";
  rebuildAlgorithmOptions(config.current?.algorithm || "graphrouter");
  renderRouterCatalogs();
  updateAlgorithmField();
}

function renderRouterCatalogs() {
  const config = state.routerConfig;
  if (!config) return;
  const serviceStrategies = config.service_strategies || [];
  const algorithms = (config.algorithms || []).filter((algorithm) => mainExperimentAlgorithmIds.has(algorithm.id));
  const algorithmHeading = elements.algorithmCatalogList
    ?.closest(".catalog-section")
    ?.querySelector(".catalog-heading strong");
  if (algorithmHeading) algorithmHeading.textContent = "主实验算法层路由器";
  elements.serviceStrategyCount.textContent = `${serviceStrategies.length} 项`;
  elements.algorithmRouterCount.textContent = `${algorithms.length} 项`;
  elements.serviceCatalogList.replaceChildren();
  elements.algorithmCatalogList.replaceChildren();

  for (const strategy of serviceStrategies) {
    const item = document.createElement("span");
    const isCurrent = strategy.id === config.current?.strategy;
    item.className = `catalog-item${isCurrent ? " current" : ""}${strategy.available === false ? " unavailable" : ""}`;
    item.textContent = strategy.name;
    item.title = [strategy.description, strategy.note].filter(Boolean).join("\n");
    elements.serviceCatalogList.append(item);
  }

  for (const algorithm of algorithms) {
    const item = document.createElement("span");
    const isCurrent = algorithm.id === config.current?.algorithm;
    const isCompatibility = algorithm.execution_mode === "compatibility";
    item.className = `catalog-item${isCurrent ? " current" : ""}${algorithm.available ? "" : " unavailable"}${isCompatibility ? " compatibility" : ""}`;
    item.textContent = algorithm.name;
    item.title = [
      algorithm.description,
      algorithm.available ? "可从当前系统直接选择。" : "当前不可直接选择。",
      isCompatibility ? "执行方式：兼容模式。" : "执行方式：项目原生路由器。",
      algorithm.note,
    ].filter(Boolean).join("\n");
    elements.algorithmCatalogList.append(item);
  }
}

function updateAlgorithmField() {
  rebuildAlgorithmOptions(elements.algorithmRouterSelect.value || state.routerConfig?.current?.algorithm || "graphrouter");
}

function rebuildAlgorithmOptions(preferredValue = "") {
  const config = state.routerConfig;
  if (!config) return;
  const serviceId = elements.serviceStrategySelect.value;
  const strategyAlgorithms = serviceStrategyAlgorithmOptions[serviceId] || [];
  const algorithms = strategyAlgorithms === "all" ? (config.algorithms || []) : [];
  const previous = preferredValue || elements.algorithmRouterSelect.value;
  elements.algorithmRouterSelect.replaceChildren();
  if (!algorithms.length) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "无对应算法路由器";
    elements.algorithmRouterSelect.append(empty);
    elements.algorithmRouterSelect.value = "";
    elements.algorithmRouterSelect.disabled = true;
    elements.algorithmSelectField.classList.add("disabled");
    return;
  }
  for (const algorithm of algorithms) {
    const option = document.createElement("option");
    option.value = algorithm.id;
    const modeLabel = algorithm.execution_mode === "compatibility" ? "（兼容模式）" : "";
    option.textContent = `${algorithm.name}${modeLabel}${algorithm.available ? "" : "（当前不可用）"}`;
    option.disabled = !algorithm.available;
    option.title = algorithm.note || algorithm.description || "";
    elements.algorithmRouterSelect.append(option);
  }
  const validPrevious = [...elements.algorithmRouterSelect.options].some((option) => option.value === previous && !option.disabled);
  const firstAvailable = [...elements.algorithmRouterSelect.options].find((option) => !option.disabled);
  elements.algorithmRouterSelect.value = validPrevious ? previous : firstAvailable?.value || "";
  elements.algorithmRouterSelect.disabled = !elements.algorithmRouterSelect.value;
  elements.algorithmSelectField.classList.toggle("disabled", !elements.algorithmRouterSelect.value);
}

async function applyRouterConfig() {
  elements.applyRouterButton.disabled = true;
  elements.applyRouterButton.textContent = "正在加载";
  try {
    const response = await fetch(API.routerConfig, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: elements.serviceStrategySelect.value,
        algorithm: elements.algorithmRouterSelect.value || null,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "路由配置更新失败");
    showToast(`已切换为 ${data.strategy}${data.algorithm ? ` / ${data.algorithm}` : ""}`);
    await refreshSystem();
  } catch (error) {
    showToast(error.message);
  } finally {
    elements.applyRouterButton.disabled = false;
    elements.applyRouterButton.textContent = "应用配置";
  }
}

function percent(value) {
  return `${(Number(value || 0) * 100).toFixed(0)}%`;
}

function renderWeightGrid(weights = {}) {
  elements.experimentWeights.replaceChildren();
  const labels = {
    quality: "质量",
    cost: "成本",
    latency: "延迟",
    reliability: "可靠性",
  };
  for (const [key, label] of Object.entries(labels)) {
    const item = document.createElement("div");
    item.className = "weight-item";
    item.innerHTML = `
      <span>${label}</span>
      <strong>${percent(weights[key])}</strong>
    `;
    elements.experimentWeights.append(item);
  }
}

function renderExperimentScoring(scoring = {}, routerbench = null) {
  const panel = document.getElementById("experimentScoring");
  if (!panel) return;
  const sensitivity = Array.isArray(routerbench?.sensitivity) ? routerbench.sensitivity : [];
  panel.innerHTML = `
    <div class="panel-title"><h3>评分公式与证据口径</h3><span>λ=${Number(scoring.risk_lambda ?? routerbench?.risk_lambda ?? 1).toFixed(1)}</span></div>
    <p><strong>${escapeHtml(scoring.formula || "U=0.45Q+0.20(1-C)+0.15(1-L)+0.20R")}</strong></p>
    <p>${escapeHtml(scoring.overall_formula || "Overall=Σ(1+λ·risk_t)·U_t / Σ(1+λ·risk_t)")}</p>
    <small>${escapeHtml(scoring.weights_note || "权重是评价偏好，不是实验测得比例。")}</small>
    <small>${escapeHtml(scoring.cost_normalization || "")} · ${escapeHtml(scoring.latency_normalization || "")} · ${escapeHtml(scoring.reliability_definition || "")}</small>
    ${sensitivity.length ? `<small>权重敏感性：${sensitivity.map((item) => `${item.profile}→${item.winner}`).join("；")}</small>` : ""}
  `;
}

function renderExperimentTasks(tasks = [], sampledTasks = []) {
  elements.experimentTaskCount.textContent = sampledTasks.length
    ? `${tasks.length} 个任务 · 本次真实抽样 ${sampledTasks.length} 个`
    : `${tasks.length} 个任务`;
  elements.experimentTaskList.replaceChildren();
  if (!tasks.length) {
    elements.experimentTaskList.innerHTML = '<div class="empty-log">暂无实验任务</div>';
    return;
  }
  for (const task of tasks) {
    const sampled = sampledTasks.some((item) => item.id === task.id);
    const card = document.createElement("article");
    card.className = `task-card${sampled ? " sampled" : ""}`;
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(task.type)}</strong>
        <span>${sampled ? "本次抽样" : task.requires_verification ? "需要验证" : "无需额外验证"}</span>
      </div>
      <p>${escapeHtml(task.query)}</p>
      <small>${escapeHtml(task.agent_stage || "-")} · 风险 ${percent(task.risk)}</small>
    `;
    elements.experimentTaskList.append(card);
  }
}

function renderExperimentStrategies(strategies = [], appendixStrategies = []) {
  elements.experimentStrategyList.replaceChildren();
  if (!strategies.length) {
    elements.experimentStrategyList.innerHTML = '<div class="empty-log">暂无可对比策略</div>';
    return;
  }
  for (const strategy of strategies) {
    const summaryText = strategy.summary
      ? `综合效用 ${Number(strategy.summary.utility || 0).toFixed(3)}`
      : "待运行";
    const item = document.createElement("article");
    item.className = "strategy-card";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(strategy.name)}</strong>
        <span>${summaryText}</span>
      </div>
      <small>${escapeHtml(strategy.benchmark_role || strategy.category || "策略")}</small>
      <p>${escapeHtml(strategy.description || "")}</p>
    `;
    elements.experimentStrategyList.append(item);
  }
  if (appendixStrategies.length) {
    const appendix = document.createElement("article");
    appendix.className = "strategy-card appendix";
    appendix.innerHTML = `
      <div>
        <strong>附录/系统展示策略</strong>
        <span>${appendixStrategies.length} 个</span>
      </div>
      <small>不进入论文主表</small>
      <p>${escapeHtml("这些策略没有删除，仍可在路由中心和附录中说明；主实验只保留代表性范式，避免同类算法重复堆砌。")}</p>
    `;
    elements.experimentStrategyList.append(appendix);
  }
}

function renderExperimentTable(strategies = [], hasRun = false) {
  elements.experimentTableBody.replaceChildren();
  if (!hasRun || !strategies.length) {
    elements.experimentTableBody.innerHTML = '<tr><td colspan="9">暂无实验结果，请先运行路由实验</td></tr>';
    return;
  }
  for (const strategy of strategies) {
    const row = document.createElement("tr");
    const summary = strategy.summary || null;
    if (!summary) {
      row.innerHTML = `
      <td>${escapeHtml(strategy.name)}</td>
      <td>${escapeHtml(strategy.category || "-")}</td>
      <td colspan="7">待运行</td>
    `;
      elements.experimentTableBody.append(row);
      continue;
    }
    row.innerHTML = `
      <td>${escapeHtml(strategy.name)}</td>
      <td>${escapeHtml(strategy.category || "-")}</td>
      <td>${percent(summary.quality)}</td>
      <td>${percent(summary.cost)}</td>
      <td>${percent(summary.latency)}</td>
      <td>${percent(summary.reliability)}</td>
      <td><strong>${Number(summary.utility || 0).toFixed(3)}</strong></td>
      <td><strong>${Number(strategy.routerbench_summary?.risk_weighted_utility ?? summary.risk_weighted_utility ?? summary.utility ?? 0).toFixed(3)}</strong></td>
      <td>${escapeHtml(String(strategy.routerbench_summary?.utility_ci95 || summary.utility_ci95 || "-"))}</td>
    `;
    elements.experimentTableBody.append(row);
  }
}

function renderExperimentCases(cases = []) {
  elements.experimentCaseList.replaceChildren();
  if (!cases.length) {
    elements.experimentCaseList.innerHTML = '<div class="empty-log">点击“运行路由实验”后，会显示典型任务分别被当前路由和改进多目标路由分配给哪个模型，以及对应理由。</div>';
    return;
  }
  for (const item of cases) {
    const candidateText = Object.entries(item.candidate_scores || {})
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 4)
      .map(([model, score]) => `${model} ${(Number(score || 0) * 100).toFixed(1)}%`)
      .join(" > ");
    const usageText = item.usage
      ? `Token ${Number(item.usage.total_tokens || 0)} · ${Math.round(Number(item.latency_ms || 0))} ms`
      : "";
    const repeatText = item.repeat_count
      ? `重复 ${Number(item.repeat_count || 0)} 次 · 成功 ${Number(item.success_count || 0)} 次`
      : "";
    const costText = item.raw_cost_usd != null
      ? `估算成本 $${Number(item.raw_cost_usd || 0).toFixed(8)}`
      : "";
    const qualityText = item.quality_source
      ? `质量来源：${item.quality_source}${item.judge_model ? ` · 主裁判 ${item.judge_model}` : ""}${item.reviewer_model ? ` · 复核裁判 ${item.reviewer_model}` : ""}${item.objective_score != null ? ` · 客观分 ${(Number(item.objective_score) * 100).toFixed(1)}%` : ""}${item.manual_review_required ? " · 需人工复核" : ""}`
      : "";
    const judgeDimensionText = item.judge_dimensions
      ? Object.entries(item.judge_dimensions).map(([key, value]) => `${key} ${(Number(value || 0) * 100).toFixed(0)}%`).join(" · ")
      : "";
    const constraints = item.constraints || null;
    const constraintText = constraints
      ? `约束：质量≥${percent(constraints.min_quality)} · 成本≤${percent(constraints.max_cost)} · 延迟≤${percent(constraints.max_latency)} · 可靠≥${percent(constraints.min_reliability)}${constraints.relaxed ? " · 已放宽" : ""}`
      : "";
    const paretoText = Array.isArray(item.pareto_front) && item.pareto_front.length
      ? `Pareto 前沿：${item.pareto_front.join("、")}`
      : "";
    const feasibleText = Array.isArray(item.feasible_models) && item.feasible_models.length
      ? `满足约束：${item.feasible_models.join("、")}`
      : "";
    const rejectedText = Array.isArray(item.rejected_models) && item.rejected_models.length
      ? `过滤模型：${item.rejected_models.slice(0, 3).map((model) => `${model.model}(${(model.violations || []).join("/")})`).join("；")}`
      : "";
    const nonlinearText = item.nonlinear_score != null
      ? `非线性效用：${(Number(item.nonlinear_score || 0) * 100).toFixed(1)}%${item.linear_score != null ? ` · 线性基线：${(Number(item.linear_score || 0) * 100).toFixed(1)}%` : ""}`
      : "";
    const riskText = item.risk_level || item.domain
      ? `风险等级：${item.risk_level || "-"} · 领域：${item.domain || "-"}`
      : "";
    const paramsText = item.nonlinear_params
      ? `非线性参数：α=${Number(item.nonlinear_params.alpha || 0).toFixed(2)} β=${Number(item.nonlinear_params.beta || 0).toFixed(2)} γ=${Number(item.nonlinear_params.gamma || 0).toFixed(2)} δ=${Number(item.nonlinear_params.delta || 0).toFixed(2)}`
      : "";
    const uncertaintyText = item.confidence != null || item.uncertainty != null
      ? `路由置信度：${(Number(item.confidence || 0) * 100).toFixed(1)}% · 不确定性：${(Number(item.uncertainty || 0) * 100).toFixed(1)}%${item.score_margin != null ? ` · 分差：${Number(item.score_margin || 0).toFixed(3)}` : ""}`
      : "";
    const escalationText = Array.isArray(item.escalation_chain) && item.escalation_chain.length
      ? `级联升级链：${item.escalation_chain.join(" → ")}`
      : "";
    const card = document.createElement("article");
    card.className = "case-card";
    card.innerHTML = `
      <div class="case-head">
        <strong>${escapeHtml(item.strategy)}</strong>
        <span>${escapeHtml(item.selected_model)}</span>
      </div>
      <p>${escapeHtml(item.query)}</p>
      <div class="case-metrics">
        <span>质量 ${percent(item.metrics?.quality)}</span>
        <span>成本 ${percent(item.metrics?.cost)}</span>
        <span>延迟 ${percent(item.metrics?.latency)}</span>
        <span>可靠 ${percent(item.metrics?.reliability)}</span>
      </div>
      ${candidateText ? `<small>候选评分：${escapeHtml(candidateText)}</small>` : ""}
      ${constraintText ? `<small>${escapeHtml(constraintText)}</small>` : ""}
      ${paretoText ? `<small>${escapeHtml(paretoText)}</small>` : ""}
      ${feasibleText ? `<small>${escapeHtml(feasibleText)}</small>` : ""}
      ${rejectedText ? `<small>${escapeHtml(rejectedText)}</small>` : ""}
      ${nonlinearText ? `<small>${escapeHtml(nonlinearText)}</small>` : ""}
      ${uncertaintyText ? `<small>${escapeHtml(uncertaintyText)}</small>` : ""}
      ${escalationText ? `<small>${escapeHtml(escalationText)}</small>` : ""}
      ${riskText ? `<small>${escapeHtml(riskText)}</small>` : ""}
      ${paramsText ? `<small>${escapeHtml(paramsText)}</small>` : ""}
      ${usageText ? `<small>真实调用：${escapeHtml(usageText)}</small>` : ""}
      ${repeatText ? `<small>${escapeHtml(repeatText)}</small>` : ""}
      ${costText ? `<small>${escapeHtml(costText)}</small>` : ""}
      ${qualityText ? `<small>${escapeHtml(qualityText)}</small>` : ""}
      ${judgeDimensionText ? `<small>裁判维度：${escapeHtml(judgeDimensionText)}</small>` : ""}
      ${item.judge_reason ? `<small>评分理由：${escapeHtml(item.judge_reason)}</small>` : ""}
      <small>${escapeHtml(item.reason || "")}</small>
    `;
    elements.experimentCaseList.append(card);
  }
}

function renderExperimentProcess(steps = []) {
  elements.experimentProcessList.replaceChildren();
  if (!steps.length) {
    elements.experimentProcessList.innerHTML = '<div class="empty-log">运行实验后，会显示任务加载、模型调用、策略对比、调度搜索和最终结论。</div>';
    return;
  }
  steps.forEach((step, index) => {
    const card = document.createElement("article");
    card.className = "process-card";
    card.innerHTML = `
      <div class="process-index">${String(index + 1).padStart(2, "0")}</div>
      <div>
        <strong>${escapeHtml(step.title || "-")}</strong>
        <p>${escapeHtml(step.detail || "")}</p>
      </div>
      <span>${escapeHtml(step.value || "")}</span>
    `;
    elements.experimentProcessList.append(card);
  });
}

function routerBenchSteps(routerbench) {
  if (!routerbench) return [];
  const pareto = Array.isArray(routerbench.pareto_front)
    ? routerbench.pareto_front.map((item) => item.name || item.id).slice(0, 5).join("、")
    : "";
  const significant = Array.isArray(routerbench.significance)
    ? routerbench.significance.filter((item) => item.significant).length
    : 0;
  const activeLearningCount = Array.isArray(routerbench.active_learning)
    ? routerbench.active_learning.length
    : 0;
  return [
    {
      title: "RouterBench 统一评估",
      detail: `已汇总质量、成本、P50/P95/P99 延迟、性价比 Pareto、鲁棒性和统计显著性。Pareto 前沿：${pareto || "-"}`,
      value: `${routerbench.strategy_count || 0} 个策略`,
    },
    {
      title: "统计显著性检验",
      detail: "对最优策略和其他策略做逐任务配对比较，包含 bootstrap 置信区间、paired t-test 和 Wilcoxon signed-rank。",
      value: `${significant} 个显著对比`,
    },
    {
      title: "主动学习样本池",
      detail: "自动筛选候选分数接近、低置信度或低效用任务，优先用于人工标注和真实多模型评估，减少暴力穷举成本。",
      value: `${activeLearningCount} 条样本`,
    },
  ];
}

function renderExperiments() {
  const payload = state.experiments || {};
  const hasRun = Boolean(payload.last_run || payload.best_strategy);
  const result = payload.last_run || payload;
  const basis = result.project_basis || payload.project_basis || {};
  const tasks = result.task_set || payload.task_set || [];
  const sampledTasks = result.sampled_task_set || payload.sampled_task_set || [];
  const strategies = result.strategies || [];
  const appendixStrategies = result.appendix_strategies || payload.appendix_strategies || [];
  const cases = result.case_results || [];
  const processSteps = result.process_steps || [];
  const routerbench = result.routerbench || payload.routerbench || null;
  const weights = result.weights || payload.weights || {};
  const scoring = result.scoring || payload.scoring || {};
  const sourceText = result.score_source || payload.score_source || "";
  const scopeText = result.strategy_scope_note || payload.strategy_scope_note || "";
  const financeDataset = result.finance_dataset || payload.finance_dataset || {};
  const financeText = financeDataset.loaded
    ? `金融数据：已加载 ${financeDataset.loaded} 条，来源 ${Object.entries(financeDataset.datasets || {}).map(([name, count]) => `${name}×${count}`).join("、")}。`
    : "";

  elements.experimentBasisText.textContent = [
    basis.note || basis.source || "这里用一组代表性任务，对比全部服务层策略、算法层路由器和调度优化方法在回答质量、调用成本、响应速度和稳定性上的取舍。",
    scopeText,
    financeText,
    sourceText,
  ].filter(Boolean).join(" ");
  elements.experimentBestStrategy.textContent = result.best_strategy
    ? `最优：${result.best_strategy}`
    : "等待运行";
  renderWeightGrid(weights);
  const benchmarkById = new Map((routerbench?.strategies || []).map((item) => [item.id, item.summary]));
  strategies.forEach((item) => { item.routerbench_summary = benchmarkById.get(item.id); });
  renderExperimentScoring(scoring, routerbench);
  renderExperimentTasks(tasks, sampledTasks);
  renderExperimentStrategies(strategies, appendixStrategies);
  renderExperimentTable(strategies, hasRun);
  renderExperimentProcess([...routerBenchSteps(routerbench), ...processSteps]);
  renderExperimentCases(cases);
  renderSchedulerView();
}

function schedulerStrategies() {
  const payload = state.experiments || {};
  const result = payload.last_run || payload;
  return (result.strategies || []).filter((item) => item.id === "pso_scheduler" || item.id === "ga_scheduler");
}

function schedulerCaseRows() {
  const payload = state.experiments || {};
  const result = payload.last_run || payload;
  return (result.case_results || []).filter((item) => {
    const name = String(item.strategy || "");
    return name.includes("PSO") || name.includes("GA");
  });
}

function renderSchedulerView() {
  if (!elements.schedulerResultGrid || !elements.schedulerAssignmentList) return;

  const strategies = schedulerStrategies();
  const cases = schedulerCaseRows();
  const hasRun = Boolean((state.experiments || {}).last_run || (state.experiments || {}).best_strategy);
  elements.schedulerResultGrid.replaceChildren();
  elements.schedulerAssignmentList.replaceChildren();
  elements.schedulerResultHint.textContent = hasRun
    ? `已读取 ${strategies.length} 个调度策略、${cases.length} 条任务分配`
    : "请先运行或刷新实验";

  if (!strategies.length) {
    elements.schedulerResultGrid.innerHTML = '<div class="empty-log">暂无 PSO / GA 调度结果，点击“运行调度实验”生成。</div>';
  } else {
    for (const strategy of strategies) {
      const summary = strategy.summary || {};
      const card = document.createElement("article");
      card.className = "scheduler-result-card";
      card.innerHTML = `
        <div>
          <strong>${escapeHtml(strategy.name)}</strong>
          <span>${escapeHtml(strategy.benchmark_role || strategy.category || "调度优化")}</span>
        </div>
        <p>${escapeHtml(strategy.description || "")}</p>
        <div class="scheduler-score-row">
          <span>质量 <b>${percent(summary.quality)}</b></span>
          <span>成本 <b>${percent(summary.cost)}</b></span>
          <span>延迟 <b>${percent(summary.latency)}</b></span>
          <span>可靠 <b>${percent(summary.reliability)}</b></span>
        </div>
        <div class="scheduler-utility">
          <span>综合效用</span>
          <strong>${Number(summary.utility || 0).toFixed(3)}</strong>
        </div>
      `;
      elements.schedulerResultGrid.append(card);
    }
  }

  if (!cases.length) {
    elements.schedulerAssignmentList.innerHTML = '<div class="empty-log">暂无任务分配明细。运行实验后，这里会显示每个任务由 PSO/GA 分配给哪个模型。</div>';
    return;
  }

  for (const item of cases) {
    const trace = Array.isArray(item.scheduler_trace) ? item.scheduler_trace : [];
    const traceText = trace.length
      ? trace.slice(-3).map((step) => {
        const round = step.iteration ?? step.generation ?? "-";
        return `第${round}轮 ${Number(step.best_fitness || 0).toFixed(3)}`;
      }).join(" · ")
      : "";
    const candidateText = Object.entries(item.candidate_scores || {})
      .sort((a, b) => Number(b[1]) - Number(a[1]))
      .slice(0, 3)
      .map(([model, score]) => `${model} ${Number(score || 0).toFixed(3)}`)
      .join(" > ");
    const row = document.createElement("article");
    row.className = "scheduler-assignment-card";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(item.strategy || "-")}</strong>
        <span>${escapeHtml(item.selected_model || "-")}</span>
      </div>
      <p>${escapeHtml(item.query || "")}</p>
      <div class="scheduler-score-row compact">
        <span>质量 <b>${percent(item.metrics?.quality)}</b></span>
        <span>成本 <b>${percent(item.metrics?.cost)}</b></span>
        <span>延迟 <b>${percent(item.metrics?.latency)}</b></span>
        <span>可靠 <b>${percent(item.metrics?.reliability)}</b></span>
      </div>
      ${item.scheduler_fitness != null ? `<small>批量适应度：${Number(item.scheduler_fitness || 0).toFixed(3)}</small>` : ""}
      ${traceText ? `<small>搜索轨迹：${escapeHtml(traceText)}</small>` : ""}
      ${candidateText ? `<small>候选效用：${escapeHtml(candidateText)}</small>` : ""}
      ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
    `;
    elements.schedulerAssignmentList.append(row);
  }
}

const SVG_NS = "http://www.w3.org/2000/svg";

const chartPalette = [
  "#A7D7C5",
  "#B8D8F8",
  "#F6C6C7",
  "#D8C7F2",
  "#FFE1A8",
  "#F7B7A3",
  "#CFE8F3",
  "#EADCF8",
  "#CDEAC0",
  "#FADDE1",
];

function stringHash(value) {
  return [...String(value || "")].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 7);
}

function getChartColor(category, index = 0, name = "") {
  const named = {
    固定高性能模型: "#BFC7D5",
    固定轻量模型: "#DDE3EA",
    随机路由: "#F7B7A3",
    KNNRouter: "#B8D8F8",
    RouterDC: "#A7D7C5",
    GraphRouter: "#D8C7F2",
    AutoMix: "#FFE1A8",
    "Latency-SLA Pareto 路由": "#FADDE1",
    "级联 Bandit Pareto 路由": "#BDE6D0",
    金融风险自适应路由: "#CFE8F3",
  };
  if (named[name]) return named[name];
  if (category === "基线") return ["#BFC7D5", "#DDE3EA"][index % 2];
  const seed = name ? stringHash(name) : index;
  return chartPalette[seed % chartPalette.length];
}

function svgNode(name, attrs = {}, text = "") {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, String(value));
  }
  if (text !== "") node.textContent = text;
  return node;
}

function pctValue(value, digits = 1) {
  return `${(Number(value || 0) * 100).toFixed(digits)}%`;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value || 0)));
}

function clearChart(container) {
  if (!container) return;
  container.replaceChildren();
}

function chartMessage(container, message) {
  clearChart(container);
  const empty = document.createElement("div");
  empty.className = "chart-empty";
  empty.textContent = message;
  container.append(empty);
}

function prepareChartsView() {
  const chartsView = $("#chartsView");
  const chartsNav = $('[data-view="charts"]');
  if (chartsNav) {
    chartsNav.innerHTML = '<span class="nav-icon" aria-hidden="true">图</span>可视化分析';
  }
  chartsView?.querySelector("h2") && (chartsView.querySelector("h2").textContent = "实验结果可视化分析");
  elements.refreshChartButton && (elements.refreshChartButton.textContent = "刷新图表");
  elements.paretoChart?.setAttribute("data-title", "成本-质量 Pareto 图");
  elements.radarChart?.setAttribute("data-title", "多维性能雷达图");
  elements.taskBarChart?.setAttribute("data-title", "任务类型质量对比");
  elements.utilityBarChart?.setAttribute("data-title", "综合效用排序");
  if (!elements.chartSummaryGrid && chartsView) {
    const heading = chartsView.querySelector(".content-heading");
    const summary = document.createElement("div");
    summary.className = "chart-summary-grid";
    summary.id = "chartSummaryGrid";
    heading?.insertAdjacentElement("afterend", summary);
    elements.chartSummaryGrid = summary;
  }
}

async function refreshCharts() {
  prepareChartsView();
  try {
    const response = await fetch(API.experimentChartData, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "无法读取可视化数据");
    renderExperimentCharts(payload);
  } catch (error) {
    renderChartSummary(null, error.message);
    chartMessage(elements.paretoChart, "暂无可视化数据，请先在“实验验证”页面运行一次实验。");
    chartMessage(elements.radarChart, "暂无数据");
    chartMessage(elements.taskBarChart, "暂无数据");
    chartMessage(elements.utilityBarChart, "暂无数据");
    showToast(error.message);
  }
}

function renderExperimentCharts(data) {
  renderChartSummary(data);
  renderParetoChart(data);
  renderRadarChart(data);
  renderTaskBarChart(data);
  renderUtilityChart(data);
}

function renderChartSummary(data, errorMessage = "") {
  prepareChartsView();
  if (!elements.chartSummaryGrid) return;
  elements.chartSummaryGrid.replaceChildren();
  if (!data || errorMessage) {
    const card = document.createElement("article");
    card.className = "chart-summary-card";
    card.innerHTML = `
      <span>图表状态</span>
      <strong>等待实验</strong>
      <small>${escapeHtml(errorMessage || "运行实验后自动生成可视化结果")}</small>
    `;
    elements.chartSummaryGrid.append(card);
    return;
  }
  const ranking = Array.isArray(data.utility_ranking) ? data.utility_ranking.slice().sort((a, b) => Number(b.utility) - Number(a.utility)) : [];
  const points = Array.isArray(data.pareto_points) ? data.pareto_points : [];
  const best = ranking[0] || {};
  const paretoCount = points.filter((item) => item.pareto).length;
  const strong = points.find((item) => item.name === "固定高性能模型") || points.find((item) => /高性能|Largest|Strong/i.test(item.name || ""));
  const light = points.find((item) => item.name === "固定轻量模型") || points.find((item) => /轻量|Smallest|Light/i.test(item.name || ""));
  const bestPoint = points.find((item) => item.name === best.name) || {};
  const costSaving = strong ? Math.max(0, Number(strong.cost || 0) - Number(bestPoint.cost || 0)) : 0;
  const qualityGain = light ? Number(bestPoint.quality || 0) - Number(light.quality || 0) : 0;
  const cards = [
    ["最优策略", best.name || "-", `综合效用 ${Number(best.utility || 0).toFixed(3)}`],
    ["Pareto 前沿", `${paretoCount} 个`, "前沿策略代表没有被其他策略全面超越"],
    ["相对强模型省成本", pctValue(costSaving), strong ? "以固定高性能模型为参照" : "缺少固定高性能模型参照"],
    ["相对轻量模型提质量", `${qualityGain >= 0 ? "+" : ""}${pctValue(qualityGain)}`, light ? "以固定轻量模型为参照" : "缺少固定轻量模型参照"],
  ];
  for (const [label, value, note] of cards) {
    const card = document.createElement("article");
    card.className = "chart-summary-card";
    card.innerHTML = `
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(note)}</small>
    `;
    elements.chartSummaryGrid.append(card);
  }
}

function renderParetoChart(data) {
  const points = Array.isArray(data.pareto_points) ? data.pareto_points : [];
  if (!points.length) return chartMessage(elements.paretoChart, "暂无 Pareto 数据");
  clearChart(elements.paretoChart);
  const width = 920;
  const height = 500;
  const margin = { left: 70, right: 36, top: 28, bottom: 78 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const x = (value) => margin.left + clamp01(value) * plotW;
  const y = (value) => margin.top + (1 - clamp01(value)) * plotH;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "成本质量 Pareto 散点图" });
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = tick / 4;
    svg.append(svgNode("line", { x1: x(value), y1: margin.top, x2: x(value), y2: margin.top + plotH, class: "chart-grid" }));
    svg.append(svgNode("line", { x1: margin.left, y1: y(value), x2: margin.left + plotW, y2: y(value), class: "chart-grid" }));
    svg.append(svgNode("text", { x: x(value), y: height - 44, class: "chart-axis-label", "text-anchor": "middle" }, value.toFixed(2)));
    svg.append(svgNode("text", { x: 50, y: y(value) + 4, class: "chart-axis-label", "text-anchor": "end" }, value.toFixed(2)));
  }
  svg.append(svgNode("line", { x1: margin.left, y1: margin.top + plotH, x2: margin.left + plotW, y2: margin.top + plotH, class: "chart-axis" }));
  svg.append(svgNode("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + plotH, class: "chart-axis" }));
  svg.append(svgNode("text", { x: margin.left + plotW / 2, y: height - 14, class: "chart-axis-title", "text-anchor": "middle" }, "成本越低越好"));
  svg.append(svgNode("text", { x: 18, y: margin.top + plotH / 2, class: "chart-axis-title", transform: `rotate(-90 18 ${margin.top + plotH / 2})`, "text-anchor": "middle" }, "质量越高越好"));
  svg.append(svgNode("text", { x: margin.left + 12, y: margin.top + 18, class: "chart-hint" }, "理想区域：高质量 + 低成本"));

  const paretoPoints = points.filter((item) => item.pareto).sort((a, b) => Number(a.cost) - Number(b.cost));
  if (paretoPoints.length >= 2) {
    svg.append(svgNode("polyline", {
      points: paretoPoints.map((item) => `${x(item.cost)},${y(item.quality)}`).join(" "),
      class: "pareto-line",
      fill: "none",
    }));
  }
  points.forEach((item, index) => {
    const color = getChartColor(item.category, index, item.name);
    const group = svgNode("g", {});
    group.append(svgNode("title", {}, `${item.name}\n质量 ${Number(item.quality).toFixed(3)}\n成本 ${Number(item.cost).toFixed(3)}\n延迟 ${Number(item.latency).toFixed(3)}\n可靠性 ${Number(item.reliability).toFixed(3)}\n效用 ${Number(item.utility).toFixed(3)}`));
    group.append(svgNode("circle", {
      cx: x(item.cost),
      cy: y(item.quality),
      r: item.pareto ? 8 : 6,
      fill: color,
      class: item.pareto ? "chart-dot pareto-dot" : "chart-dot",
    }));
    if (item.pareto) {
      group.append(svgNode("text", { x: x(item.cost), y: y(item.quality) - 12, class: "pareto-star", "text-anchor": "middle" }, "★"));
      group.append(svgNode("text", { x: x(item.cost) + 10, y: y(item.quality) - 10, class: "chart-point-label" }, item.name));
    }
    svg.append(group);
  });
  renderLegend(svg, points, width, height - 24);
  elements.paretoChart.append(svg);
}

function renderRadarChart(data) {
  const profiles = Array.isArray(data.radar_profiles) ? data.radar_profiles.slice(0, 6) : [];
  if (!profiles.length) return chartMessage(elements.radarChart, "暂无雷达图数据");
  clearChart(elements.radarChart);
  const width = 620;
  const height = 500;
  const cx = width / 2;
  const cy = 215;
  const radius = 138;
  const axes = [
    ["质量", "quality"],
    ["成本效率", "costEff"],
    ["延迟效率", "latencyEff"],
    ["可靠性", "reliability"],
    ["鲁棒性", "robustness"],
  ];
  const pointAt = (axisIndex, value) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * axisIndex) / axes.length;
    return [cx + Math.cos(angle) * radius * clamp01(value), cy + Math.sin(angle) * radius * clamp01(value)];
  };
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "多维性能雷达图" });
  for (let ring = 1; ring <= 4; ring += 1) {
    svg.append(svgNode("polygon", {
      points: axes.map((_, index) => pointAt(index, ring / 4).join(",")).join(" "),
      class: "radar-ring",
    }));
  }
  axes.forEach(([label], index) => {
    const [x1, y1] = pointAt(index, 1);
    const [lx, ly] = pointAt(index, 1.16);
    svg.append(svgNode("line", { x1: cx, y1: cy, x2: x1, y2: y1, class: "radar-axis" }));
    svg.append(svgNode("text", { x: lx, y: ly, class: "chart-axis-title", "text-anchor": "middle" }, label));
  });
  svg.append(svgNode("polygon", {
    points: axes.map((_, index) => pointAt(index, 1).join(",")).join(" "),
    class: "radar-ideal",
  }));
  profiles.forEach((profile, index) => {
    const color = getChartColor(profile.category, index, profile.name);
    const points = axes.map(([, key], axisIndex) => pointAt(axisIndex, profile[key]).join(",")).join(" ");
    const polygon = svgNode("polygon", { points, fill: color, stroke: color, class: "radar-profile" });
    polygon.append(svgNode("title", {}, `${profile.name}\n质量 ${pctValue(profile.quality)}\n成本效率 ${pctValue(profile.costEff)}\n延迟效率 ${pctValue(profile.latencyEff)}\n可靠性 ${pctValue(profile.reliability)}\n鲁棒性 ${pctValue(profile.robustness)}`));
    svg.append(polygon);
  });
  renderLegend(svg, profiles, width, height - 46);
  elements.radarChart.append(svg);
}

function renderTaskBarChart(data) {
  const chartData = data.task_type_quality || {};
  const types = chartData.types || [];
  const series = (chartData.series || []).slice(0, 6);
  if (!types.length || !series.length) return chartMessage(elements.taskBarChart, "暂无任务类型数据");
  clearChart(elements.taskBarChart);
  const width = Math.max(980, types.length * 120);
  const height = 520;
  const margin = { left: 70, right: 30, top: 36, bottom: 98 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "任务类型质量分组柱状图" });
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = tick / 4;
    const y = margin.top + (1 - value) * plotH;
    svg.append(svgNode("line", { x1: margin.left, y1: y, x2: margin.left + plotW, y2: y, class: "chart-grid" }));
    svg.append(svgNode("text", { x: 50, y: y + 4, class: "chart-axis-label", "text-anchor": "end" }, value.toFixed(2)));
  }
  svg.append(svgNode("line", { x1: margin.left, y1: margin.top + plotH, x2: margin.left + plotW, y2: margin.top + plotH, class: "chart-axis" }));
  svg.append(svgNode("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + plotH, class: "chart-axis" }));
  const groupW = plotW / types.length;
  const barGap = 3;
  const barW = Math.max(6, (groupW - 22) / series.length - barGap);
  types.forEach((type, typeIndex) => {
    const baseX = margin.left + typeIndex * groupW + 11;
    series.forEach((item, seriesIndex) => {
      const value = clamp01(item.data[typeIndex]);
      const x = baseX + seriesIndex * (barW + barGap);
      const barH = value * plotH;
      const rect = svgNode("rect", {
        x,
        y: margin.top + plotH - barH,
        width: barW,
        height: barH,
        fill: getChartColor(item.category, seriesIndex, item.name),
        rx: 2,
      });
      rect.append(svgNode("title", {}, `${item.name}\n${type}：${pctValue(value)}`));
      svg.append(rect);
    });
    svg.append(svgNode("text", { x: baseX + groupW / 2 - 11, y: height - 50, class: "chart-axis-label", "text-anchor": "middle" }, type));
  });
  svg.append(svgNode("text", { x: 18, y: margin.top + plotH / 2, class: "chart-axis-title", transform: `rotate(-90 18 ${margin.top + plotH / 2})`, "text-anchor": "middle" }, "平均质量"));
  renderLegend(svg, series, width, height - 20);
  elements.taskBarChart.append(svg);
}

function renderUtilityChart(data) {
  const sorted = Array.isArray(data.utility_ranking)
    ? data.utility_ranking.slice().sort((a, b) => b.utility - a.utility)
    : [];
  if (!sorted.length) return chartMessage(elements.utilityBarChart, "暂无效用排序数据");
  clearChart(elements.utilityBarChart);
  const width = 700;
  const height = Math.max(360, sorted.length * 36 + 72);
  const margin = { left: 176, right: 56, top: 22, bottom: 34 };
  const plotW = width - margin.left - margin.right;
  const rowH = (height - margin.top - margin.bottom) / sorted.length;
  const maxUtility = Math.max(0.01, ...sorted.map((item) => Number(item.utility || 0)));
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "综合效用排名图" });
  sorted.forEach((item, index) => {
    const value = Number(item.utility || 0);
    const y = margin.top + index * rowH + rowH * 0.18;
    const barW = (value / maxUtility) * plotW;
    svg.append(svgNode("text", { x: margin.left - 12, y: y + rowH * 0.48, class: "utility-label", "text-anchor": "end" }, `${item.pareto ? "★ " : ""}${item.name}`));
    const rect = svgNode("rect", {
      x: margin.left,
      y,
      width: barW,
      height: rowH * 0.62,
      fill: getChartColor(item.category, index, item.name),
      rx: 4,
    });
    rect.append(svgNode("title", {}, `${item.name}\n综合效用：${value.toFixed(3)}`));
    svg.append(rect);
    svg.append(svgNode("text", { x: margin.left + barW + 8, y: y + rowH * 0.48, class: "chart-value-label" }, value.toFixed(3)));
  });
  elements.utilityBarChart.append(svg);
}

function renderLegend(svg, items, width, y) {
  const seen = new Map();
  items.forEach((item, index) => {
    const key = item.name || item.category || "其他";
    if (!seen.has(key)) seen.set(key, getChartColor(item.category, index, item.name));
  });
  let x = 32;
  let rowY = y;
  [...seen.entries()].slice(0, 10).forEach(([label, color]) => {
    const step = Math.min(178, Math.max(88, label.length * 12 + 32));
    if (x + step > width - 24) {
      x = 32;
      rowY += 18;
    }
    svg.append(svgNode("rect", { x, y: rowY - 9, width: 10, height: 10, fill: color, rx: 2 }));
    svg.append(svgNode("text", { x: x + 16, y: rowY, class: "chart-legend-text" }, label));
    x += step;
  });
}

async function refreshExperiments() {
  try {
    const response = await fetch(API.experiments, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取实验方案");
    state.experiments = await response.json();
    renderExperiments();
    if ($("#chartsView")?.classList.contains("active")) {
      await refreshCharts();
    }
    if ($("#schedulerView")?.classList.contains("active")) {
      renderSchedulerView();
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function runExperiment(mode = "simulated") {
  const button = mode === "real" ? elements.runRealExperimentButton : mode === "pilot" ? elements.runPilotExperimentButton : elements.runExperimentButton;
  button.disabled = true;
  button.textContent = mode === "real" ? "正式实验调用中" : mode === "pilot" ? "预实验调用中" : "正在运行";
  try {
    const response = await fetch(API.runExperiment, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        sample_limit: mode === "real" ? 100 : mode === "pilot" ? 10 : 100,
        repeats: mode === "real" ? 3 : mode === "pilot" ? 1 : 1,
        judge_enabled: mode !== "simulated",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "实验运行失败");
    state.experiments = payload;
    renderExperiments();
    if ($("#chartsView")?.classList.contains("active")) {
      await refreshCharts();
    }
    if ($("#schedulerView")?.classList.contains("active")) {
      renderSchedulerView();
    }
    await refreshLogs();
    showToast(mode === "real" ? "正式真实实验已完成" : mode === "pilot" ? "预实验已完成（不计入正式结果）" : "模拟路由实验已完成");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = mode === "real" ? "正式真实实验" : mode === "pilot" ? "运行10条预实验" : "运行模拟实验";
  }
}

function exportExperimentReport() {
  window.open(API.experimentReport, "_blank", "noopener");
}

function renderMetrics() {
  const metrics = state.metrics || {};
  elements.metricRequests.textContent = String(metrics.requests || 0);
  elements.metricSuccessRate.textContent = `${((metrics.success_rate || 0) * 100).toFixed(1)}%`;
  elements.metricLatency.textContent = `${Math.round(metrics.average_latency_ms || 0)} ms`;
  elements.metricFallbacks.textContent = String(metrics.fallbacks || 0);

  elements.modelUsageBars.replaceChildren();
  const usageEntries = Object.entries(metrics.model_usage || {});
  const maxUsage = Math.max(1, ...usageEntries.map(([, value]) => Number(value)));
  if (!usageEntries.length) {
    elements.modelUsageBars.innerHTML = '<div class="empty-log">暂无成功请求</div>';
  } else {
    for (const [model, value] of usageEntries.sort((a, b) => b[1] - a[1])) {
      const row = document.createElement("div");
      row.className = "usage-row";
      row.innerHTML = `
        <strong title="${escapeHtml(model)}">${escapeHtml(model)}</strong>
        <div class="usage-track"><div class="usage-fill" style="width:${(Number(value) / maxUsage) * 100}%"></div></div>
        <span>${Number(value)}</span>
      `;
      elements.modelUsageBars.append(row);
    }
  }

  elements.modelHealthList.replaceChildren();
  for (const [model, health] of Object.entries(metrics.model_health || {})) {
    const row = document.createElement("div");
    row.className = "health-row";
    const isCooling = health.status === "cooldown";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(model)}</strong>
        <small>${escapeHtml(health.last_error || "最近没有调用错误")}</small>
      </div>
      <span class="model-health-badge ${isCooling ? "cooldown" : ""}">${isCooling ? "冷却中" : "健康"}</span>
    `;
    elements.modelHealthList.append(row);
  }
}

async function refreshMetrics() {
  try {
    const [response, experienceResponse] = await Promise.all([
      fetch(API.metrics, { cache: "no-store" }),
      fetch(API.experienceMetrics, { cache: "no-store" }),
    ]);
    if (!response.ok) throw new Error("无法读取评估数据");
    state.metrics = await response.json();
    state.experienceMetrics = experienceResponse.ok ? await experienceResponse.json() : {};
    renderMetrics();
    const experience = state.experienceMetrics || {};
    $("#experienceEvents").textContent = String(experience.events || 0);
    $("#feedbackCoverage").textContent = `${(Number(experience.feedback_coverage || 0) * 100).toFixed(1)}%`;
    $("#routingAccuracy").textContent = `${(Number(experience.routing_accuracy || 0) * 100).toFixed(1)}%`;
    $("#negativeFeedbackRate").textContent = `${(Number(experience.negative_feedback_rate || 0) * 100).toFixed(1)}%`;
    $("#averageRegret").textContent = Number(experience.average_estimated_regret || 0).toFixed(3);
  } catch (error) {
    showToast(error.message);
  }
}

function renderLogs() {
  elements.logTableBody.replaceChildren();
  if (!state.logs.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="6">暂无运行日志</td>';
    elements.logTableBody.append(row);
    return;
  }
  for (const item of state.logs) {
    const row = document.createElement("tr");
    const statusLabel = item.status === "success" ? "成功" : item.status === "failed" ? "失败" : "配置";
    row.innerHTML = `
      <td>${new Date(item.time * 1000).toLocaleTimeString("zh-CN")}</td>
      <td><span class="log-status ${item.status === "failed" ? "failed" : ""}">${statusLabel}</span></td>
      <td>${escapeHtml([item.strategy, item.algorithm].filter(Boolean).join(" / ") || "-")}</td>
      <td>${escapeHtml(item.selected_model || "-")}</td>
      <td>${item.latency_ms ? `${Math.round(item.latency_ms)} ms` : "-"}</td>
      <td>${escapeHtml(item.reason || item.message || "-")}</td>
    `;
    elements.logTableBody.append(row);
  }
}

async function refreshLogs() {
  try {
    const response = await fetch(`${API.logs}?limit=80`, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取日志");
    const payload = await response.json();
    state.logs = payload.data || [];
    renderLogs();
  } catch (error) {
    showToast(error.message);
  }
}

function renderSystem() {
  const system = state.system;
  if (!system) return;
  const router = system.router || {};

  elements.routingStrategyName.textContent = router.strategy || "-";
  elements.routingAlgorithmName.textContent = router.algorithm || "服务层策略";
  elements.routingConfigPath.textContent = router.config || "未设置算法层配置";
  elements.prefixFeatureValue.textContent = system.features?.model_prefix ? "已启用" : "未启用";
  const executionMode = router.execution_mode === "compatibility" ? "兼容模式" : "原生模式";
  elements.routerLoadedValue.textContent = router.loaded ? `已加载（${executionMode}）` : "未加载或已回退";
  elements.routerHealthBadge.textContent = router.loaded ? "运行正常" : "需要检查";
  elements.routerHealthBadge.className = `health-badge ${router.loaded ? "online" : "offline"}`;

  elements.systemStatusValue.textContent = system.status === "online" ? "在线" : system.status;
  elements.systemStrategyValue.textContent = router.algorithm
    ? `${router.strategy} / ${router.algorithm}`
    : router.strategy || "-";
  elements.systemModelCountValue.textContent = String(state.models.length);

  elements.endpointList.replaceChildren();
  for (const [name, value] of Object.entries(system.endpoints || {})) {
    const [method, endpoint] = value.split(" ");
    const row = document.createElement("div");
    row.className = "endpoint-row";
    row.innerHTML = `
      <span class="method-badge ${method.toLowerCase()}">${escapeHtml(method)}</span>
      <code>${escapeHtml(endpoint)}</code>
      <span>${escapeHtml(endpointLabel(name))}</span>
    `;
    elements.endpointList.append(row);
  }
}

function endpointLabel(name) {
  return {
    chat: "聊天补全",
    models: "模型列表",
    health: "健康检查",
    routers: "路由策略",
  }[name] || name;
}

function formatNumber(number) {
  if (!number) return "-";
  return new Intl.NumberFormat("zh-CN").format(number);
}

function populateModelSelect() {
  const current = elements.modelSelect.value || activeSession()?.selectedModel || "auto";
  elements.modelSelect.replaceChildren();
  const auto = document.createElement("option");
  auto.value = "auto";
  auto.textContent = "策略路由（自动决策）";
  elements.modelSelect.append(auto);

  for (const model of state.models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = `路由覆盖 · ${model.id}`;
    elements.modelSelect.append(option);
  }
  elements.modelSelect.value = [...elements.modelSelect.options].some((option) => option.value === current)
    ? current
    : "auto";
}

async function refreshSystem(showSuccess = false) {
  elements.sidebarStatusText.textContent = "正在连接服务";
  try {
    const [healthResponse, systemResponse, routerConfigResponse] = await Promise.all([
      fetch(API.health, { cache: "no-store" }),
      fetch(API.system, { cache: "no-store" }),
      fetch(API.routerConfig, { cache: "no-store" }),
    ]);
    if (!healthResponse.ok || !systemResponse.ok || !routerConfigResponse.ok) throw new Error("服务未响应");
    const health = await healthResponse.json();
    state.system = await systemResponse.json();
    state.routerConfig = await routerConfigResponse.json();
    state.models = state.system.models || [];

    elements.sidebarStatusDot.className = "status-dot online";
    elements.sidebarStatusText.textContent = `${state.models.length} 个模型在线`;
    elements.systemHealthBadge.textContent = "服务在线";
    elements.systemHealthBadge.className = "health-badge online";
    elements.composerHint.textContent = `自动路由 · ${state.system.router?.algorithm || health.strategy}`;
    elements.viewSubtitle.textContent = state.system.router?.algorithm
      ? `由 ${state.system.router.algorithm} 自动选择合适的模型`
      : `当前服务策略：${health.strategy}`;
    populateModelSelect();
    renderModels();
    renderSystem();
    populateRouterSelectors();
    updateInspector();
    await Promise.all([refreshMetrics(), refreshLogs(), refreshExperiments()]);
    if (showSuccess) showToast("服务状态已刷新");
  } catch (error) {
    elements.sidebarStatusDot.className = "status-dot offline";
    elements.sidebarStatusText.textContent = "服务连接失败";
    elements.systemHealthBadge.textContent = "服务离线";
    elements.systemHealthBadge.className = "health-badge offline";
    showToast(`连接失败：${error.message}`);
  }
}

const viewMeta = {
  chat: ["智能对话", "通过路由器调用最合适的模型"],
  routing: ["路由中心", "查看服务层与算法层的当前运行配置"],
  models: ["模型管理", "查看已接入的模型和供应商"],
  evaluation: ["实验验证", "查看路由实验任务和运行结果"],
  scheduler: ["调度优化", "查看 PSO / GA 批量模型分配过程"],
  charts: ["可视化分析", "通过图表直观判断实验结果好坏"],
  logs: ["运行日志", "查看每次路由选择、模型调用和自动降级过程"],
  system: ["系统状态", "查看服务健康状态和 API 接口"],
};

function setView(view) {
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === view));
  const [title, subtitle] = viewMeta[view] || viewMeta.chat;
  elements.viewTitle.textContent = title;
  elements.viewSubtitle.textContent = view === "chat" && state.system?.router?.algorithm
    ? `由 ${state.system.router.algorithm} 自动选择合适的模型`
    : subtitle;
  if (view === "charts") {
    refreshCharts();
  }
  if (view === "scheduler") {
    if (state.experiments) renderSchedulerView();
    else refreshExperiments();
  }
  elements.sidebar.classList.remove("open");
}

function openSettings(open) {
  elements.settingsDrawer.classList.toggle("open", open);
  elements.drawerBackdrop.classList.toggle("open", open);
  elements.settingsDrawer.setAttribute("aria-hidden", String(!open));
}

let toastTimer;
function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2600);
}

function bindEvents() {
  elements.newChatButton.addEventListener("click", () => {
    createSession();
    setView("chat");
  });
  elements.clearSessionsButton.addEventListener("click", clearSessions);
  elements.menuButton.addEventListener("click", () => elements.sidebar.classList.toggle("open"));
  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  $$("[data-prompt]").forEach((button) => button.addEventListener("click", () => sendMessage(button.dataset.prompt)));
  elements.sendButton.addEventListener("click", () => sendMessage());
  elements.compareButton?.addEventListener("click", () => runABCompare());
  elements.messageInput.addEventListener("input", resizeInput);
  elements.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  elements.modelSelect.addEventListener("change", () => {
    const session = activeSession();
    if (session) session.selectedModel = elements.modelSelect.value;
    elements.composerHint.textContent = elements.modelSelect.value === "auto"
      ? `自动路由 · ${state.system?.router?.algorithm || "路由器"}`
      : `路由覆盖 · ${elements.modelSelect.value}`;
    if (elements.modelSelect.value !== "auto") {
      const scope = state.settings.solveMode === "single"
        ? "本轮将跳过自动模型决策。"
        : "所有子任务将限定使用该模型，自动模型决策不再生效。";
      showToast(`已启用路由覆盖：${scope}`);
    }
    saveState();
  });
  elements.solveModeSelect?.addEventListener("change", () => {
    state.settings.solveMode = elements.solveModeSelect.value;
    rebuildDispatchOptions(state.settings.dispatchMode);
    const dispatchText = dispatchModeLabel(state.settings.dispatchMode);
    elements.composerHint.textContent = dispatchText
      ? `${solveModeLabel(state.settings.solveMode)} · ${dispatchText}`
      : solveModeLabel(state.settings.solveMode);
    saveState();
  });
  elements.dispatchModeSelect?.addEventListener("change", () => {
    state.settings.dispatchMode = elements.dispatchModeSelect.value;
    const dispatchText = dispatchModeLabel(state.settings.dispatchMode);
    elements.composerHint.textContent = dispatchText
      ? `${solveModeLabel(state.settings.solveMode)} · ${dispatchText}`
      : solveModeLabel(state.settings.solveMode);
    saveState();
  });
  elements.refreshButton.addEventListener("click", () => refreshSystem(true));
  elements.refreshChartButton?.addEventListener("click", () => refreshCharts());
  elements.addModelButton.addEventListener("click", () => openModelModal());
  elements.closeModelModalButton.addEventListener("click", closeModelModal);
  elements.cancelModelButton.addEventListener("click", closeModelModal);
  elements.modelModalBackdrop.addEventListener("click", closeModelModal);
  elements.modelForm.addEventListener("submit", saveModel);
  elements.serviceStrategySelect.addEventListener("change", () => {
    updateAlgorithmField();
    renderRouterCatalogs();
  });
  elements.applyRouterButton.addEventListener("click", applyRouterConfig);
  elements.refreshMetricsButton.addEventListener("click", async () => {
    await Promise.all([refreshMetrics(), refreshExperiments()]);
  });
  elements.refreshSchedulerButton?.addEventListener("click", refreshExperiments);
  elements.runSchedulerButton?.addEventListener("click", () => runExperiment("simulated"));
  elements.runExperimentButton.addEventListener("click", () => runExperiment("simulated"));
  elements.runRealExperimentButton.addEventListener("click", () => runExperiment("real"));
  elements.runPilotExperimentButton.addEventListener("click", () => runExperiment("pilot"));
  elements.exportExperimentButton.addEventListener("click", exportExperimentReport);
  elements.refreshLogsButton.addEventListener("click", refreshLogs);
  elements.settingsButton.addEventListener("click", () => openSettings(true));
  elements.closeSettingsButton.addEventListener("click", () => openSettings(false));
  elements.drawerBackdrop.addEventListener("click", () => openSettings(false));
  elements.temperatureInput.addEventListener("input", () => {
    state.settings.temperature = Number(elements.temperatureInput.value);
    elements.temperatureOutput.value = state.settings.temperature.toFixed(1);
    saveState();
  });
  elements.maxTokensInput.addEventListener("change", () => {
    state.settings.maxTokens = Math.max(128, Math.min(4096, Number(elements.maxTokensInput.value) || 1024));
    elements.maxTokensInput.value = state.settings.maxTokens;
    saveState();
  });
  elements.systemPromptInput.addEventListener("change", () => {
    state.settings.systemPrompt = elements.systemPromptInput.value;
    saveState();
  });
  elements.clearChatButton.addEventListener("click", () => {
    const session = activeSession();
    if (session) session.messages = [];
    saveState();
    renderMessages();
    openSettings(false);
    showToast("当前对话已清空");
  });
}

function initSettings() {
  elements.temperatureInput.value = state.settings.temperature;
  elements.temperatureOutput.value = Number(state.settings.temperature).toFixed(1);
  elements.maxTokensInput.value = state.settings.maxTokens;
  elements.systemPromptInput.value = state.settings.systemPrompt;
  if (elements.solveModeSelect) {
    elements.solveModeSelect.value = state.settings.solveMode || "single";
  }
  if (elements.dispatchModeSelect) {
    rebuildDispatchOptions(state.settings.dispatchMode);
  }
}

async function init() {
  loadState();
  bindEvents();
  prepareChartsView();
  initSettings();
  renderSessions();
  renderMessages();
  updateInspector();
  await refreshSystem();
  const session = activeSession();
  if (session?.selectedModel) elements.modelSelect.value = session.selectedModel;
  const requestedView = new URLSearchParams(window.location.search).get("view");
  if (viewMeta[requestedView]) setView(requestedView);
  resizeInput();
}

init();
