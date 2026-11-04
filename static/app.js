// 页面只处理交互与展示；密钥、数据计算和模型调用均留在 Python 服务端。
const $ = (selector) => document.querySelector(selector);
let session = null,
  health = null,
  busy = false,
  toastTimer;
const toolNames = {
  get_total_sales: "计算总销售额",
  get_top_product: "查找销售冠军",
  get_sales_for_product: "查询指定商品",
  get_sales_by_date: "按日期统计",
  get_product_ranking: "商品排名",
  get_dataset_summary: "数据概况",
  create_sales_chart: "生成图表",
  get_data_schema: "读取字段契约",
  get_business_metrics: "读取指标口径",
  query_metric: "按指标定义计算",
  run_readonly_sql: "执行只读 SQL",
};
const formatNumber = (value) =>
  new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 4500);
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("无法连接本地服务，请确认 Python 程序仍在运行。");
  }
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {}
    const error = new Error(
      typeof detail === "string"
        ? detail
        : `请求未完成（${response.status}），请重试。`,
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function post(path, data) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
function setBusy(value) {
  busy = value;
  $("#send").disabled = value || !session;
  $("#question").disabled = value;
  $("#mode").disabled = value;
  $("#upload-button").disabled = value;
  $("#clear-chat").disabled = value;
  $("#restore-data").disabled = value;
  $("#session-history").disabled = value;
  $("#new-session").disabled = value;
  $("#send").firstChild.textContent = value ? "分析中 " : "发送 ";
}
function showTab(tab) {
  $("#analysis-view").hidden = tab !== "analysis";
  $("#data-view").hidden = tab !== "data";
  $("#metrics-view").hidden = tab !== "metrics";
  $("#view-name").textContent =
    tab === "analysis" ? "对话分析" : tab === "data" ? "数据预览" : "指标口径";
  document
    .querySelectorAll("[data-tab]")
    .forEach((node) =>
      node.classList.toggle("active", node.dataset.tab === tab),
    );
}
function setAnswerText(node, text) {
  // 支持安全的粗体展示，用户内容始终通过 textContent 写入。
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  for (const part of parts) {
    if (part.startsWith("**") && part.endsWith("**"))
      node.append(element("strong", "", part.slice(2, -2)));
    else node.append(document.createTextNode(part));
  }
}
function addMessage(role, text) {
  $("#welcome").hidden = true;
  const message = element("div", `message ${role}`);
  if (role !== "user") {
    const label = element("div", "message-label");
    label.append(
      element("span", "avatar", "✧"),
      document.createTextNode(role === "error" ? "提示" : "DataPilot"),
    );
    message.append(label);
  }
  const body = element("div", "message-body");
  setAnswerText(body, text);
  message.append(body);
  $("#chat-log").append(message);
  scrollChat();
  return message;
}
function scrollChat() {
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}
function renderResult(result) {
  const node = addMessage("assistant", result.answer);
  const meta = element("div", "message-meta");
  const tokens =
    (result.usage.prompt_tokens || 0) + (result.usage.completion_tokens || 0);
  meta.textContent = `${result.mode === "demo" ? "离线规则演示" : "DeepSeek"} · ${(result.duration_ms / 1000).toFixed(2)} s · ${result.traces.length} 次工具执行${result.mode === "live" ? ` · ${formatNumber(tokens)} tokens` : ""}`;
  node.append(meta);
  if (result.traces.length) {
    const details = element("details", "trace");
    details.append(
      element("summary", "", `查看分析过程 · ${result.traces.length} 个步骤`),
    );
    const list = element("ol");
    for (const trace of result.traces) {
      const item = element(
        "li",
        "",
        `${toolNames[trace.name] || trace.name} · ${trace.duration_ms} ms${trace.success ? "" : " · 查询提示"}`,
      );
      item.append(
        element(
          "pre",
          "",
          JSON.stringify(
            { 参数: trace.arguments, 结果: trace.result },
            null,
            2,
          ),
        ),
      );
      list.append(item);
    }
    details.append(list);
    node.append(details);
  }
  for (const trace of result.traces) {
    const data = trace.result;
    if (!data.sql || !Array.isArray(data.rows)) continue;
    const box = element("details", "sql-evidence");
    box.open = true;
    box.append(
      element(
        "summary",
        "",
        `查询依据 · ${data.row_count} 行${data.truncated ? "（已截断）" : ""}`,
      ),
      element("pre", "", data.sql),
    );
    const wrap = element("div", "table-wrap"),
      table = element("table"),
      head = element("thead"),
      header = element("tr"),
      body = element("tbody");
    for (const column of data.columns) header.append(element("th", "", column));
    head.append(header);
    for (const row of data.rows) {
      const tr = element("tr");
      for (const column of data.columns)
        tr.append(
          element("td", "", row[column] === null ? "NULL" : row[column]),
        );
      body.append(tr);
    }
    table.append(head, body);
    wrap.append(table);
    box.append(
      wrap,
      element(
        "p",
        "sql-note",
        `只读 SQLite · ${data.execution_ms} ms · 参数 ${JSON.stringify(data.parameters || [])}`,
      ),
    );
    node.append(box);
  }
  for (const artifact of result.artifacts) {
    if (artifact.kind !== "chart") continue;
    const box = element("div", "chart-result");
    const image = element("img");
    image.src = artifact.url;
    image.alt = "根据当前销售数据生成的图表";
    const link = element("a", "", "下载图表 PNG ↓");
    link.href = artifact.url;
    link.download = "sales-chart.png";
    box.append(image, link);
    node.append(box);
  }
  scrollChat();
}
function renderSession(data) {
  session = data;
  localStorage.setItem("datapilot-session", data.id);
  $("#mode").value = data.mode;
  const live = data.mode === "live";
  $("#mode-tag").textContent = live ? "DeepSeek" : "离线演示";
  $("#mode-notice").textContent = live
    ? "DeepSeek 根据工具返回的真实结果作答；点击“分析过程”查看计算依据。"
    : "离线演示使用规则路由与真实数据计算，不调用大模型。";
  $("#filename").textContent = data.filename;
  $("#file-info").textContent =
    `${formatNumber(data.summary.row_count)} 条记录 · ${data.summary.product_count} 种商品`;
  $("#total-sales").textContent = formatNumber(data.summary.total_sales_amount);
  $("#row-count").textContent = formatNumber(data.summary.row_count);
  $("#product-count").textContent = data.summary.product_count;
  $("#top-product").textContent = data.summary.top_product;
  $("#date-range").textContent =
    `${data.summary.date_min} — ${data.summary.date_max}`;
  $("#export-report").href = `/api/sessions/${data.id}/export.md`;
  $("#export-csv").href = `/api/sessions/${data.id}/export.csv`;
  const bars = $("#ranking-bars");
  bars.replaceChildren();
  const maximum = data.ranking[0]?.sales_amount || 1;
  for (const row of data.ranking) {
    const wrapper = element("div", "rank-row");
    const label = element("div", "rank-label");
    label.append(
      element("span", "", row.product),
      element("strong", "", formatNumber(row.sales_amount)),
    );
    const track = element("div", "rank-track"),
      fill = element("div", "rank-fill");
    fill.style.width = `${Math.max(0, (row.sales_amount / maximum) * 100)}%`;
    track.append(fill);
    wrapper.append(label, track);
    bars.append(wrapper);
  }
  const log = $("#chat-log"),
    welcome = $("#welcome");
  log.replaceChildren(welcome);
  welcome.hidden = !!data.turns.length;
  for (const turn of data.turns) {
    addMessage("user", turn.question);
    renderResult(turn);
  }
  const head = element("tr");
  for (const column of data.columns) head.append(element("th", "", column));
  $("#data-head").replaceChildren(head);
  $("#data-body").replaceChildren();
  for (const row of data.preview) {
    const tr = element("tr");
    for (const column of data.columns)
      tr.append(
        element(
          "td",
          "",
          typeof row[column] === "number"
            ? formatNumber(row[column])
            : row[column],
        ),
      );
    $("#data-body").append(tr);
  }
  setBusy(false);
  $("#persistence-state").textContent = health?.persistence
    ? "会话与数据已保存在本地"
    : "当前会话保存在内存";
  refreshHistory().catch(() => {});
}
async function startSession(mode) {
  if (
    session &&
    mode !== session.mode &&
    $("#chat-log").querySelector(".message") &&
    !confirm("切换模式将开始新对话，当前上传数据会保留。是否继续？")
  ) {
    $("#mode").value = session.mode;
    return;
  }
  setBusy(true);
  try {
    const path = session ? `/api/sessions/${session.id}/mode` : "/api/sessions";
    renderSession(await post(path, { mode }));
    await refreshHistory();
  } catch (error) {
    toast(error.message);
    setBusy(false);
    if (session) $("#mode").value = session.mode;
  }
}

async function refreshHistory() {
  if (!session) return;
  const data = await api("/api/sessions");
  const select = $("#session-history");
  select.replaceChildren();
  for (const item of data.sessions) {
    const option = element(
      "option",
      "",
      `${item.title || item.filename} · ${item.turn_count} 次问答`,
    );
    option.value = item.id;
    select.append(option);
  }
  select.value = session.id;
}
async function newSession() {
  if (busy) return;
  setBusy(true);
  try {
    renderSession(
      await post("/api/sessions", {
        mode: session?.mode || "demo",
        source_session_id: session?.id || null,
      }),
    );
    await refreshHistory();
    showTab("analysis");
    toast("已新建会话，当前数据保留，历史会话可以随时恢复。");
  } catch (error) {
    toast(error.message);
    setBusy(false);
  }
}
async function showMetrics() {
  try {
    const contract = await api("/api/metrics");
    const area = $("#metric-contract");
    area.replaceChildren(
      element(
        "p",
        "data-description",
        `定义版本 ${contract.version} · 数据表 ${contract.table}`,
      ),
    );
    for (const metric of contract.metrics) {
      const card = element("article", "contract-card");
      card.append(
        element("h3", "", `${metric.label} / ${metric.name}`),
        element("p", "", `${metric.description} 单位：${metric.unit}`),
        element("code", "", metric.expression),
      );
      area.append(card);
    }
    area.append(
      element("p", "data-description", contract.assumptions.join(" ")),
    );
    showTab("metrics");
  } catch (error) {
    toast(error.message);
  }
}
$("#new-session").addEventListener("click", newSession);
$("#session-history").addEventListener("change", async (event) => {
  if (busy) return;
  setBusy(true);
  try {
    renderSession(await api(`/api/sessions/${event.target.value}`));
    showTab("analysis");
  } catch (error) {
    toast(error.message);
    setBusy(false);
  }
});
$("#show-metrics").addEventListener("click", showMetrics);
$("#back-analysis").addEventListener("click", () => showTab("analysis"));
async function sendQuestion(text) {
  if (busy || !session) return;
  const question = text.trim();
  if (!question) return;
  showTab("analysis");
  addMessage("user", question);
  $("#question").value = "";
  setBusy(true);
  const pending = element("div", "pending", "正在选择工具并分析数据");
  $("#chat-log").append(pending);
  scrollChat();
  try {
    const result = await post(`/api/sessions/${session.id}/chat`, { question });
    pending.remove();
    renderResult(result);
  } catch (error) {
    pending.remove();
    addMessage("error", error.message);
  } finally {
    setBusy(false);
    refreshHistory().catch(() => {});
    $("#question").focus();
  }
}
async function uploadFile(file) {
  if (!file || busy || !session) return;
  if (!file.name.toLowerCase().endsWith(".csv"))
    return toast("请选择 CSV 文件。");
  if (file.size > 5 * 1024 * 1024) return toast("CSV 文件不能超过5 MB。");
  if (
    $("#chat-log").querySelector(".message") &&
    !confirm("更换数据会开始新的分析对话，是否继续？")
  )
    return;
  setBusy(true);
  try {
    const data = await api(`/api/sessions/${session.id}/dataset`, {
      method: "POST",
      headers: {
        "Content-Type": "text/csv",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    renderSession(data);
    toast("数据已通过校验，可以开始分析。");
  } catch (error) {
    toast(error.message);
  } finally {
    setBusy(false);
    $("#file-input").value = "";
  }
}
document
  .querySelectorAll("[data-tab]")
  .forEach((button) =>
    button.addEventListener("click", () => showTab(button.dataset.tab)),
  );
$("#show-data").addEventListener("click", () => showTab("data"));
document
  .querySelectorAll("[data-question]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      sendQuestion(button.dataset.question),
    ),
  );
$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendQuestion($("#question").value);
});
$("#question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendQuestion(event.target.value);
  }
});
$("#upload-button").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (event) =>
  uploadFile(event.target.files[0]),
);
$("#drop-zone").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("#drop-zone").classList.add("dragging");
});
$("#drop-zone").addEventListener("dragleave", () =>
  $("#drop-zone").classList.remove("dragging"),
);
$("#drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("#drop-zone").classList.remove("dragging");
  uploadFile(event.dataTransfer.files[0]);
});
$("#mode").addEventListener("change", (event) =>
  startSession(event.target.value),
);
$("#clear-chat").addEventListener("click", async () => {
  if (busy || !session) return;
  setBusy(true);
  try {
    renderSession(await post(`/api/sessions/${session.id}/reset`, {}));
    toast("已开始新对话，数据保持不变。");
  } catch (error) {
    toast(error.message);
    setBusy(false);
  }
});
$("#restore-data").addEventListener("click", async () => {
  if (busy || !session) return;
  setBusy(true);
  try {
    renderSession(
      await post(`/api/sessions/${session.id}/dataset/default`, {}),
    );
    toast("已恢复示例销售数据。");
  } catch (error) {
    toast(error.message);
    setBusy(false);
  }
});
(async () => {
  setBusy(true);
  try {
    health = await api("/api/health");
    $("#model-state").textContent = health.live_available
      ? `${health.model} · 已配置`
      : "DeepSeek 尚未配置密钥";
    $('#mode option[value="live"]').disabled = !health.live_available;
    const saved = localStorage.getItem("datapilot-session");
    if (saved) {
      try {
        renderSession(await api(`/api/sessions/${saved}`));
        return;
      } catch (error) {
        // 忙碌或存储异常时保留原会话ID，不静默创建新会话。
        if (error.status !== 404) throw error;
      }
    }
    await startSession("demo");
  } catch (error) {
    toast(error.message);
    setBusy(false);
  }
})();
