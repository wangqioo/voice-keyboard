"""Built-in HTML review console for intent-training samples."""

from __future__ import annotations


def render_review_page() -> str:
    return _REVIEW_PAGE_HTML


_REVIEW_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Voice Keyboard Intent Review</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-soft: #eef2f6;
      --text: #17202a;
      --muted: #5f6b7a;
      --line: #d8dee7;
      --primary: #0f766e;
      --primary-strong: #115e59;
      --danger: #b42318;
      --ok: #176b3a;
      --shadow: 0 1px 2px rgba(20, 30, 45, 0.08);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255, 255, 255, 0.96);
      border-bottom: 1px solid var(--line);
      box-shadow: var(--shadow);
    }
    .topbar {
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(300px, 620px);
      gap: 16px;
      align-items: center;
      max-width: 1440px;
      margin: 0 auto;
      padding: 12px 16px;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .auth {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 8px;
      align-items: end;
    }
    main {
      max-width: 1440px;
      margin: 0 auto;
      padding: 16px;
    }
    .filters {
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr)) auto;
      gap: 10px;
      align-items: end;
      margin-bottom: 12px;
      padding: 12px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(6, minmax(110px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .stat {
      min-height: 64px;
      padding: 10px 12px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .stat span {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }
    .stat strong {
      display: block;
      margin-top: 4px;
      font-size: 20px;
      line-height: 1.2;
    }
    label {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    input, select, textarea, button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
      letter-spacing: 0;
    }
    input, select, textarea {
      width: 100%;
      padding: 7px 9px;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 64px;
      resize: vertical;
    }
    button {
      padding: 7px 12px;
      background: var(--surface-soft);
      color: var(--text);
      cursor: pointer;
      font-weight: 650;
    }
    button.primary {
      background: var(--primary);
      border-color: var(--primary);
      color: #fff;
    }
    button.primary:hover { background: var(--primary-strong); }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .status {
      min-height: 20px;
      margin-bottom: 10px;
      color: var(--muted);
    }
    .status.error { color: var(--danger); }
    .status.ok { color: var(--ok); }
    .tableWrap {
      overflow-x: auto;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    table {
      width: 100%;
      min-width: 1180px;
      border-collapse: collapse;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 62px;
      z-index: 5;
      background: var(--surface-soft);
      color: #334155;
      font-size: 12px;
    }
    tr:last-child td { border-bottom: 0; }
    .textCell {
      width: 260px;
      min-width: 260px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .reviewGrid {
      display: grid;
      grid-template-columns: 145px 150px 160px 170px 1fr auto;
      gap: 8px;
      align-items: start;
      min-width: 820px;
    }
    .noteField { min-width: 180px; }
    .empty {
      padding: 26px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 900px) {
      .topbar,
      .auth,
      .filters,
      .stats {
        grid-template-columns: 1fr;
      }
      th { top: 0; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <h1>Voice Keyboard Intent Review</h1>
      <div class="auth">
        <label>Token
          <input id="tokenInput" type="password" autocomplete="off" placeholder="Bearer token">
        </label>
        <button id="saveTokenButton" type="button">保存</button>
        <button id="reloadButton" class="primary" type="button">刷新</button>
      </div>
    </div>
  </header>

  <main>
    <section class="filters" aria-label="样本筛选">
      <label>复核状态
        <select id="reviewFilter" name="review_label">
          <option value="">未复核</option>
          <option value="correct">correct</option>
          <option value="wrong_intent">wrong_intent</option>
          <option value="wrong_target">wrong_target</option>
          <option value="unsafe_should_confirm">unsafe_should_confirm</option>
          <option value="missing_shortcut">missing_shortcut</option>
          <option value="unclear">unclear</option>
          <option value="__all__">全部</option>
        </select>
      </label>
      <label>意图类型
        <input id="intentTypeFilter" name="intent_type" placeholder="shortcut / delete / chat">
      </label>
      <label>状态
        <input id="statusFilter" name="status" placeholder="ok / error">
      </label>
      <label>数量
        <select id="limitFilter">
          <option>50</option>
          <option selected>100</option>
          <option>200</option>
          <option>500</option>
        </select>
      </label>
      <label>偏移
        <input id="offsetFilter" type="number" min="0" step="1" value="0">
      </label>
      <button id="applyFiltersButton" class="primary" type="button">应用</button>
    </section>

    <section class="stats" aria-label="统计">
      <div class="stat"><span>总样本</span><strong id="statTotal">0</strong></div>
      <div class="stat"><span>已纠正</span><strong id="statCorrected">0</strong></div>
      <div class="stat"><span>shortcut</span><strong id="statShortcut">0</strong></div>
      <div class="stat"><span>chat</span><strong id="statChat">0</strong></div>
      <div class="stat"><span>delete</span><strong id="statDelete">0</strong></div>
      <div class="stat"><span>wrong_intent</span><strong id="statWrongIntent">0</strong></div>
    </section>

    <div id="statusMessage" class="status" role="status"></div>

    <section class="tableWrap" aria-label="样本列表">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>文本</th>
            <th>当前判断</th>
            <th>上下文</th>
            <th>复核和修正</th>
          </tr>
        </thead>
        <tbody id="sampleRows">
          <tr><td class="empty" colspan="5">等待加载样本</td></tr>
        </tbody>
      </table>
    </section>
  </main>

  <script>
    const tokenInput = document.getElementById('tokenInput');
    const statusMessage = document.getElementById('statusMessage');
    const sampleRows = document.getElementById('sampleRows');

    tokenInput.value = localStorage.getItem('intentReviewToken') || '';

    document.getElementById('saveTokenButton').addEventListener('click', () => {
      localStorage.setItem('intentReviewToken', tokenInput.value.trim());
      setStatus('Token 已保存', 'ok');
    });
    document.getElementById('reloadButton').addEventListener('click', loadAll);
    document.getElementById('applyFiltersButton').addEventListener('click', loadAll);

    function authHeaders(extra = {}) {
      const token = tokenInput.value.trim();
      const headers = { ...extra };
      if (token) headers.Authorization = `Bearer ${token}`;
      return headers;
    }

    function setStatus(message, kind = '') {
      statusMessage.textContent = message;
      statusMessage.className = `status ${kind}`;
    }

    function value(id) {
      return document.getElementById(id).value.trim();
    }

    async function requestJson(url, options = {}) {
      const response = await fetch(url, {
        ...options,
        headers: authHeaders(options.headers || {}),
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${text}`);
      }
      return response.json();
    }

    async function loadAll() {
      setStatus('加载中...');
      try {
        const [stats, samples] = await Promise.all([loadStats(), loadSamples()]);
        renderStats(stats);
        renderSamples(samples.items || []);
        setStatus(`已加载 ${(samples.items || []).length} 条样本`, 'ok');
      } catch (error) {
        setStatus(error.message || String(error), 'error');
      }
    }

    function sampleQuery() {
      const params = new URLSearchParams();
      params.set('limit', value('limitFilter') || '100');
      params.set('offset', value('offsetFilter') || '0');
      const review = value('reviewFilter');
      if (review !== '__all__') params.set('review_label', review);
      const intentType = value('intentTypeFilter');
      if (intentType) params.set('intent_type', intentType);
      const status = value('statusFilter');
      if (status) params.set('status', status);
      return params.toString();
    }

    function loadStats() {
      return requestJson('/v1/stats');
    }

    function loadSamples() {
      return requestJson(`/v1/intent-samples?${sampleQuery()}`);
    }

    function renderStats(stats) {
      document.getElementById('statTotal').textContent = stats.total || 0;
      document.getElementById('statCorrected').textContent = stats.corrected_total || 0;
      document.getElementById('statShortcut').textContent = (stats.by_intent || {}).shortcut || 0;
      document.getElementById('statChat').textContent = (stats.by_intent || {}).chat || 0;
      document.getElementById('statDelete').textContent = (stats.by_intent || {}).delete || 0;
      document.getElementById('statWrongIntent').textContent = (stats.by_review || {}).wrong_intent || 0;
    }

    function renderSamples(items) {
      if (!items.length) {
        sampleRows.innerHTML = '<tr><td class="empty" colspan="5">没有匹配样本</td></tr>';
        return;
      }
      sampleRows.innerHTML = '';
      for (const sample of items) {
        sampleRows.appendChild(renderSampleRow(sample));
      }
    }

    function renderSampleRow(sample) {
      const row = document.createElement('tr');
      const corrected = sample.corrected_intent || {};
      row.innerHTML = `
        <td class="meta">#${escapeHtml(sample.id)}<br>${formatTime(sample.created_at)}</td>
        <td class="textCell">${escapeHtml(sample.text || '')}</td>
        <td>
          <div><strong>${escapeHtml(sample.intent_type || '')}</strong></div>
          <div class="meta">${escapeHtml(sample.intent_name || sample.intent_key || '')}</div>
          <div class="meta">${escapeHtml(sample.intent_source || '')} ${escapeHtml(sample.intent_confidence || '')}</div>
          <div class="meta">${escapeHtml(sample.status || '')}</div>
        </td>
        <td>
          <div>${escapeHtml(sample.active_application || '')}</div>
          <div class="meta">selection: ${sample.has_selection ? 'yes' : 'no'} / recent: ${sample.has_recent_text ? 'yes' : 'no'}</div>
          <div class="meta">${escapeHtml(sample.detail || '')}</div>
        </td>
        <td>
          <div class="reviewGrid">
            <label>review_label
              <select data-field="label">
                ${reviewOptions(sample.review_label || '')}
              </select>
            </label>
            <label>corrected_intent
              <select data-field="correctedType">
                ${intentOptions(corrected.type || '')}
              </select>
            </label>
            <label>name/key
              <input data-field="correctedName" value="${escapeAttr(corrected.name || corrected.key || '')}" placeholder="保存 / cmd+s">
            </label>
            <label>reply
              <input data-field="correctedReply" value="${escapeAttr(corrected.reply || '')}" placeholder="chat 回复">
            </label>
            <label class="noteField">note
              <textarea data-field="note" placeholder="复核备注">${escapeHtml(sample.review_note || '')}</textarea>
            </label>
            <button class="primary" type="button" data-action="save">保存</button>
          </div>
        </td>
      `;
      row.querySelector('[data-action="save"]').addEventListener('click', () => saveReview(sample.id, row));
      return row;
    }

    function reviewOptions(current) {
      return ['', 'correct', 'wrong_intent', 'wrong_target', 'unsafe_should_confirm', 'missing_shortcut', 'unclear']
        .map(value => `<option value="${value}" ${value === current ? 'selected' : ''}>${value || '未复核'}</option>`)
        .join('');
    }

    function intentOptions(current) {
      return ['', 'shortcut', 'delete', 'memory_save', 'memory_query', 'chat', 'rewrite', 'replace', 'continue']
        .map(value => `<option value="${value}" ${value === current ? 'selected' : ''}>${value || '不修正'}</option>`)
        .join('');
    }

    async function saveReview(sampleId, row) {
      const button = row.querySelector('[data-action="save"]');
      button.disabled = true;
      try {
        const payload = {
          label: row.querySelector('[data-field="label"]').value,
          note: row.querySelector('[data-field="note"]').value,
        };
        const corrected = correctedIntentFromRow(row);
        if (corrected) payload.corrected_intent = corrected;
        await requestJson(`/v1/intent-samples/${sampleId}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setStatus(`#${sampleId} 已保存`, 'ok');
        await loadAll();
      } catch (error) {
        setStatus(error.message || String(error), 'error');
      } finally {
        button.disabled = false;
      }
    }

    function correctedIntentFromRow(row) {
      const type = row.querySelector('[data-field="correctedType"]').value;
      if (!type) return null;
      const name = row.querySelector('[data-field="correctedName"]').value.trim();
      const reply = row.querySelector('[data-field="correctedReply"]').value.trim();
      const corrected = { type };
      if (type === 'shortcut') {
        if (name) corrected.name = name;
      } else if (type === 'chat') {
        if (reply) corrected.reply = reply;
      } else if (name) {
        corrected.name = name;
      }
      return corrected;
    }

    function formatTime(value) {
      if (!value) return '';
      return new Date(Number(value) * 1000).toLocaleString();
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function escapeAttr(value) {
      return escapeHtml(value).replaceAll('`', '&#96;');
    }

    loadAll();
  </script>
</body>
</html>
"""
