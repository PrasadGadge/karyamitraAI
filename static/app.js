/**
 * KaryaMitra AI - Enterprise MSME Order Automation & Verification Console
 * Phase 3A: Live Backend Integration & Production-Ready UI
 */
(function () {
  'use strict';

  // Application State
  const state = {
    selectedOrder: null,
    orders: [],
    catalogueRecords: [],
    sampleOrders: [],
    evalRecords: [],
    evalSummary: null,
    metricsData: null,
    activeTab: 'workspace',
    activeSubTab: 'eval',
    evalFilter: {
      split: 'all',
      category: '',
      search: '',
      page: 1,
      pageSize: 10
    },
    catalogueSearch: ''
  };

  // Helper Utilities
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (val) => String(val ?? '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));

  function formatCurrency(num) {
    if (num === null || num === undefined || isNaN(num)) return '—';
    return '₹' + Number(num).toFixed(2);
  }

  function formatTime(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
    } catch {
      return isoStr;
    }
  }

  // Robust API Fetcher
  async function api(path, options = {}) {
    const res = await fetch(path, options);
    let body;
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      body = await res.json();
    } else {
      body = await res.text();
    }
    if (!res.ok) {
      const msg = (body && typeof body === 'object' && body.detail) ? body.detail : (typeof body === 'string' && body ? body : `Request failed (${res.status})`);
      throw new Error(msg);
    }
    return body;
  }

  // Toast / Status Message Banner
  function showStatus(message, type = 'info', timeout = 4000) {
    const banner = $('request-status-banner');
    if (!banner) return;
    banner.style.display = 'block';
    banner.className = `alert-banner ${type}`;
    banner.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;">
        ${type === 'danger' ? '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>' :
          type === 'success' ? '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>' :
          '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'}
      </svg>
      <div>${escapeHtml(message)}</div>
    `;
    if (timeout > 0) {
      setTimeout(() => {
        if (banner.textContent.includes(message)) {
          banner.style.display = 'none';
        }
      }, timeout);
    }
  }

  // Tab Switcher
  function switchTab(tabId) {
    state.activeTab = tabId;
    document.querySelectorAll('.nav-tab').forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-tab') === tabId);
    });
    document.querySelectorAll('.tab-pane').forEach(pane => {
      pane.classList.toggle('active', pane.id === `view-${tabId}`);
    });

    if (tabId === 'metrics') refreshMetrics();
    if (tabId === 'evaluation') refreshEvaluation();
    if (tabId === 'audit') renderAuditView();
    if (tabId === 'review') renderReviewView();
  }

  // Sub-Tab Switcher for Dataset Explorer
  function switchDatasetSubTab(subTabId) {
    state.activeSubTab = subTabId;
    document.querySelectorAll('.sub-nav-tab').forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-subtab') === subTabId);
    });
    $('subview-eval').style.display = subTabId === 'eval' ? 'block' : 'none';
    $('subview-catalogue').style.display = subTabId === 'catalogue' ? 'block' : 'none';
    $('subview-samples').style.display = subTabId === 'samples' ? 'block' : 'none';
  }

  // -------------------------------------------------------------
  // SCREEN 1 & 3: RENDER ORDER RESULTS AND HUMAN REVIEW
  // -------------------------------------------------------------
  function renderOrderResult(order) {
    if (!order) return;
    state.selectedOrder = order;

    // Update session orders list
    const existingIndex = state.orders.findIndex(o => o.id === order.id);
    if (existingIndex >= 0) {
      state.orders[existingIndex] = order;
    } else {
      state.orders.unshift(order);
    }

    // Update review badge
    const badge = $('badge-review-state');
    if (badge) {
      badge.textContent = order.state;
      badge.className = `tab-badge status-badge ${order.state}`;
    }

    // Populate Right Column Result Area
    const container = $('order-result-area');
    if (!container) return;

    const linesHtml = order.lines.map((line, idx) => {
      const isOk = line.verified;
      const findings = line.findings || [];
      const hasFindings = findings.length > 0;
      const cardClass = isOk ? 'line-item-card' : (findings.some(f => f.includes('No catalogue product') || f.includes('Multiple catalogue')) ? 'line-item-card unresolved' : 'line-item-card error');

      return `
        <div class="${cardClass}">
          <div class="line-header">
            <div class="line-requested-text">
              #${idx + 1} "${escapeHtml(line.product_text || line.source_text)}"
            </div>
            <span class="status-badge ${isOk ? 'VERIFIED' : 'NEEDS_CLARIFICATION'}">
              ${isOk ? '✓ Verified' : '⚠️ Action Needed'}
            </span>
          </div>

          <div class="line-matched-info">
            <strong>Matched Catalogue SKU:</strong>
            ${line.sku ? `<span class="sku-pill">${escapeHtml(line.sku)}</span> · <strong>${escapeHtml(line.product_name)}</strong>` : '<span style="color:#b91c1c; font-weight:600;">Unresolved — No Single Catalogue Match</span>'}
          </div>

          ${line.match_evidence && line.match_evidence.length > 1 ? `
            <div style="font-size:0.78rem; background:#fffbeb; padding:0.35rem 0.5rem; border-radius:4px; margin:0.35rem 0; border:1px solid #fde68a;">
              <strong>Ambiguous Candidate Matches (${line.match_evidence.length}):</strong>
              ${line.match_evidence.map(m => `<span class="sku-pill" style="margin-right:0.3rem;">${escapeHtml(m.sku)}: ${escapeHtml(m.name)}</span>`).join(' ')}
            </div>
          ` : ''}

          <div class="line-math-row">
            <div class="line-math-col">Requested: <strong>${line.quantity ?? 'None'} ${escapeHtml(line.requested_unit || 'unspecified')}</strong></div>
            <div class="line-math-col">Converted: <strong>${line.converted_quantity !== null && line.converted_quantity !== undefined ? line.converted_quantity : '—'} ${escapeHtml(line.sellable_unit || '')}</strong></div>
            <div class="line-math-col">Unit Price: <strong>${formatCurrency(line.unit_price)}</strong></div>
            <div class="line-math-col">Line Total: <strong>${formatCurrency(line.line_total)}</strong></div>
          </div>

          ${hasFindings ? `
            <div class="line-findings ${isOk ? 'success' : 'warning'}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
              <span>${findings.map(escapeHtml).join(' | ')}</span>
            </div>
          ` : `
            <div class="line-findings success">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>Deterministic catalogue verification passed.</span>
            </div>
          `}
        </div>
      `;
    }).join('');

    const unparsedHtml = order.unrecognised_text && order.unrecognised_text.length ? `
      <div class="alert-banner warning" style="margin-top:0.75rem;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
        <div>
          <strong>Unparsed Input Segments:</strong> ${order.unrecognised_text.map(t => `<code>${escapeHtml(t)}</code>`).join(', ')}
        </div>
      </div>
    ` : '';

    const errorHtml = order.error ? `
      <div class="alert-banner danger">
        <strong>Pipeline Error:</strong> ${escapeHtml(order.error)}
      </div>
    ` : '';

    // Safeguards explanation
    let safeguardExplanation = '';
    if (order.state === 'VERIFIED') {
      safeguardExplanation = 'All line items, pack sizes, conversions, and catalogue prices verified. Ready for operator approval.';
    } else if (order.state === 'NEEDS_CLARIFICATION') {
      safeguardExplanation = 'Approval is locked: order contains unresolved findings or ambiguous matches. Correct the message or reject.';
    } else if (order.state === 'APPROVED') {
      safeguardExplanation = 'Order signed off and verified. Ready for ERP / CSV / JSON export.';
    } else if (order.state === 'REJECTED') {
      safeguardExplanation = 'Order rejected by operator. No further actions permitted in this prototype.';
    } else {
      safeguardExplanation = 'Draft order under evaluation.';
    }

    container.innerHTML = `
      <div class="order-overview-header">
        <div class="order-meta-group">
          <span class="order-id-label">ID: ${escapeHtml(order.id.slice(0, 8))}…</span>
          <span class="status-badge ${order.state}">${order.state}</span>
          <span class="meta-pill">Parser: ${escapeHtml(order.parser.method)} v${escapeHtml(order.parser.version)}</span>
        </div>
        <div class="order-duration">
          Duration: <strong>${order.processing_duration_ms} ms</strong> · Corrections: <strong>${order.correction_count}</strong>
        </div>
      </div>

      ${errorHtml}

      <div style="margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: baseline;">
        <h3 style="font-size: 0.95rem; margin: 0; color: var(--color-text-secondary);">
          Extracted Line Items (${order.lines.length})
        </h3>
        <span style="font-size: 0.8rem; color: var(--color-text-muted);">Source: ${escapeHtml(order.source_record_id || 'Direct message')}</span>
      </div>

      <div class="lines-container">
        ${order.lines.length ? linesHtml : '<div class="empty-state"><p>No items could be extracted.</p></div>'}
      </div>

      ${unparsedHtml}

      <!-- Human Decision & Safeguards Gate -->
      <div class="safeguards-box">
        <div class="safeguards-status-text">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
          <strong>Safeguard Gate:</strong> ${escapeHtml(safeguardExplanation)}
        </div>
        <div class="actions-row">
          <button class="btn btn-success" id="btn-order-approve" ${order.state !== 'VERIFIED' ? 'disabled' : ''}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
            Approve Verified Order
          </button>
          <button class="btn btn-danger" id="btn-order-reject" ${['APPROVED', 'REJECTED'].includes(order.state) ? 'disabled' : ''}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            Reject Order
          </button>
          ${order.state === 'APPROVED' ? `
            <a class="btn btn-secondary" href="/api/orders/${order.id}/export?format=json" target="_blank" download="${order.id}.json">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              Export JSON
            </a>
            <a class="btn btn-secondary" href="/api/orders/${order.id}/export?format=csv" target="_blank" download="${order.id}.csv">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
              Export CSV
            </a>
          ` : ''}
        </div>
      </div>

      <!-- In-Line Correction Box -->
      <div style="margin-top: 1.25rem; border-top: 1px solid var(--color-border); padding-top: 1rem;">
        <label class="form-label" for="edit-message-input">
          <span>Human Correction &amp; Clarification</span>
          <span class="form-label-hint">Correction count: ${order.correction_count}</span>
        </label>
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
          <input type="text" class="form-input" id="edit-message-input" value="${escapeHtml(order.original_message)}" style="flex:1; min-width: 250px;">
          <button class="btn btn-secondary" id="btn-reprocess-correction">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2.5 2v6h6M21.5 22v-6h-6"/><path d="M22 11.5A10 10 0 0 0 3.2 7.2M2 12.5a10 10 0 0 0 18.8 4.2"/></svg>
            Save Correction &amp; Reprocess
          </button>
        </div>
      </div>

      <!-- Execution Trace Summary -->
      <div style="margin-top: 1.25rem;">
        <h4 style="font-size: 0.88rem; margin: 0 0 0.5rem; color: var(--color-text-secondary);">Execution Trace (${order.trace.length} events)</h4>
        <div class="trace-timeline">
          ${order.trace.map(tr => `
            <div class="trace-event-item">
              <div class="trace-dot"></div>
              <div class="trace-header">
                <span class="trace-title">${escapeHtml(tr.event)}</span>
                <span class="trace-time">${formatTime(tr.at)}</span>
              </div>
              ${tr.detail ? `<div class="trace-detail">${escapeHtml(tr.detail)}</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;

    // Bind dynamic action listeners
    const btnApprove = $('btn-order-approve');
    if (btnApprove) {
      btnApprove.addEventListener('click', async () => {
        try {
          btnApprove.disabled = true;
          const updated = await api(`/api/orders/${order.id}/approve`, { method: 'POST' });
          showStatus('Order explicitly approved by operator.', 'success');
          renderOrderResult(updated);
          refreshMetrics();
        } catch (err) {
          showStatus(`Approval failed: ${err.message}`, 'danger');
          btnApprove.disabled = false;
        }
      });
    }

    const btnReject = $('btn-order-reject');
    if (btnReject) {
      btnReject.addEventListener('click', async () => {
        try {
          btnReject.disabled = true;
          const updated = await api(`/api/orders/${order.id}/reject`, { method: 'POST' });
          showStatus('Order explicitly rejected by operator.', 'warning');
          renderOrderResult(updated);
          refreshMetrics();
        } catch (err) {
          showStatus(`Rejection failed: ${err.message}`, 'danger');
          btnReject.disabled = false;
        }
      });
    }

    const btnReprocess = $('btn-reprocess-correction');
    if (btnReprocess) {
      btnReprocess.addEventListener('click', async () => {
        const text = ($('edit-message-input').value || '').trim();
        if (!text) {
          showStatus('Correction message cannot be empty.', 'warning');
          return;
        }
        try {
          btnReprocess.disabled = true;
          const corrected = await api(`/api/orders/${order.id}/correct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
          });
          $('customer-message').value = text;
          showStatus('Correction reprocessed successfully.', 'success');
          renderOrderResult(corrected);
          refreshMetrics();
        } catch (err) {
          showStatus(`Correction failed: ${err.message}`, 'danger');
          btnReprocess.disabled = false;
        }
      });
    }

    updateReviewOrderSelector();
  }

  // -------------------------------------------------------------
  // SCREEN 3: DEDICATED HUMAN REVIEW CONSOLE
  // -------------------------------------------------------------
  function updateReviewOrderSelector() {
    const sel = $('review-order-selector');
    if (!sel) return;
    if (!state.orders.length) {
      sel.innerHTML = '<option value="">No orders in current session</option>';
      return;
    }
    sel.innerHTML = state.orders.map(o => `
      <option value="${o.id}" ${state.selectedOrder && state.selectedOrder.id === o.id ? 'selected' : ''}>
        ${o.id.slice(0, 8)}… (${o.state}) — ${escapeHtml(o.original_message.slice(0, 25))}…
      </option>
    `).join('');
  }

  function renderReviewView() {
    const container = $('human-review-content');
    if (!container) return;

    if (!state.selectedOrder && state.orders.length) {
      state.selectedOrder = state.orders[0];
    }

    const order = state.selectedOrder;
    if (!order) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🛡️</div>
          <div class="empty-state-title">No Order Available for Review</div>
          <p class="empty-state-desc">Process an order in the <strong>Order Workspace</strong> to evaluate lines, review findings, and execute approval or rejection actions.</p>
          <button class="btn btn-primary btn-sm" onclick="document.getElementById('tab-btn-workspace').click()">Go to Order Workspace</button>
        </div>
      `;
      return;
    }

    const unresolvedCount = order.lines.filter(l => !l.verified).length;
    const canApprove = order.state === 'VERIFIED';
    const canReject = !['APPROVED', 'REJECTED'].includes(order.state);

    container.innerHTML = `
      <div class="order-overview-header">
        <div>
          <span class="order-id-label">Active Review: ${escapeHtml(order.id)}</span>
          <span class="status-badge ${order.state}" style="margin-left: 0.5rem;">${order.state}</span>
        </div>
        <div>
          Created: <strong>${formatTime(order.created_at)}</strong> · Duration: <strong>${order.processing_duration_ms} ms</strong>
        </div>
      </div>

      <div class="workspace-grid" style="margin-top: 1rem;">
        <!-- Left: Customer Input & Raw Intent -->
        <div>
          <h3 style="font-size: 0.95rem; margin-top: 0;">1. Original Customer Message</h3>
          <div style="background: var(--color-bg-subtle); padding: 1rem; border-radius: var(--radius-md); border: 1px solid var(--color-border); font-size: 0.92rem; font-style: italic;">
            "${escapeHtml(order.original_message)}"
          </div>

          <h3 style="font-size: 0.95rem; margin-top: 1.25rem;">2. Natural Language Parsing</h3>
          <div class="table-container">
            <table class="data-table">
              <thead><tr><th>Source Segment</th><th>Quantity</th><th>Unit</th></tr></thead>
              <tbody>
                ${order.extracted_lines.map(ex => `
                  <tr>
                    <td><code>${escapeHtml(ex.product_text)}</code></td>
                    <td><strong>${ex.quantity ?? 'None'}</strong></td>
                    <td>${escapeHtml(ex.unit || 'None')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>

          <h3 style="font-size: 0.95rem; margin-top: 1.25rem;">3. Human Clarification / Message Edit</h3>
          <div class="form-group">
            <textarea class="form-textarea" id="review-edit-text" rows="3">${escapeHtml(order.original_message)}</textarea>
            <button class="btn btn-secondary btn-sm" id="btn-review-reprocess" style="margin-top: 0.5rem;">
              Reprocess Clarification
            </button>
          </div>
        </div>

        <!-- Right: Verification Diagnostics & Quality Gate -->
        <div>
          <h3 style="font-size: 0.95rem; margin-top: 0;">4. Catalogue Verification Diagnostics</h3>
          <div class="lines-container">
            ${order.lines.map((l, idx) => `
              <div class="line-item-card ${l.verified ? '' : 'unresolved'}">
                <div class="line-header">
                  <strong>#${idx + 1} ${escapeHtml(l.product_name || l.product_text)}</strong>
                  <span class="status-badge ${l.verified ? 'VERIFIED' : 'NEEDS_CLARIFICATION'}">
                    ${l.verified ? '✓ Passed' : '⚠️ Action Needed'}
                  </span>
                </div>
                <div style="font-size: 0.82rem; color: var(--color-text-secondary); margin: 0.25rem 0;">
                  SKU: <span class="sku-pill">${escapeHtml(l.sku || 'UNRESOLVED')}</span> | Price: <strong>${formatCurrency(l.unit_price)}</strong> | Total: <strong>${formatCurrency(l.line_total)}</strong>
                </div>
                ${l.findings.length ? `
                  <div class="line-findings warning" style="margin-top: 0.35rem;">
                    ${l.findings.map(escapeHtml).join(' | ')}
                  </div>
                ` : `
                  <div class="line-findings success" style="margin-top: 0.35rem;">All catalogue rules validated.</div>
                `}
              </div>
            `).join('')}
          </div>

          <!-- Quality Gate Checklist -->
          <h3 style="font-size: 0.95rem; margin-top: 1.25rem;">5. Safeguard Gate Checklist</h3>
          <div style="background: var(--color-bg-subtle); padding: 0.85rem 1rem; border-radius: var(--radius-md); border: 1px solid var(--color-border); font-size: 0.84rem;">
            <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom: 0.35rem;">
              <span>${unresolvedCount === 0 ? '✅' : '❌'}</span>
              <span>Deterministic SKU Match: <strong>${unresolvedCount === 0 ? 'All items matched uniquely' : `${unresolvedCount} item(s) unresolved`}</strong></span>
            </div>
            <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom: 0.35rem;">
              <span>${order.lines.every(l => l.unit_price) ? '✅' : '❌'}</span>
              <span>Catalogue Pricing Derived: <strong>${order.lines.every(l => l.unit_price) ? 'Prices verified from products.csv' : 'Price missing for one or more items'}</strong></span>
            </div>
            <div style="display:flex; align-items:center; gap:0.5rem;">
              <span>${canApprove ? '✅' : '🔒'}</span>
              <span>Backend Approval Eligibility: <strong>${canApprove ? 'Eligible for Human Approval' : 'Blocked by Backend Safeguards'}</strong></span>
            </div>
          </div>

          <!-- Action Gate Buttons -->
          <div class="actions-row" style="margin-top: 1.25rem;">
            <button class="btn btn-success" id="btn-review-approve" ${!canApprove ? 'disabled' : ''}>
              ✓ Approve Verified Order
            </button>
            <button class="btn btn-danger" id="btn-review-reject" ${!canReject ? 'disabled' : ''}>
              ✕ Reject Order
            </button>
            ${order.state === 'APPROVED' ? `
              <a class="btn btn-secondary" href="/api/orders/${order.id}/export?format=json" target="_blank" download="${order.id}.json">Export JSON</a>
              <a class="btn btn-secondary" href="/api/orders/${order.id}/export?format=csv" target="_blank" download="${order.id}.csv">Export CSV</a>
            ` : ''}
          </div>
        </div>
      </div>
    `;

    // Event listeners for review actions
    $('btn-review-approve').addEventListener('click', async () => {
      try {
        const updated = await api(`/api/orders/${order.id}/approve`, { method: 'POST' });
        showStatus('Order approved successfully in Human Review gate.', 'success');
        renderOrderResult(updated);
        renderReviewView();
        refreshMetrics();
      } catch (err) {
        showStatus(`Approval rejected by backend: ${err.message}`, 'danger');
      }
    });

    $('btn-review-reject').addEventListener('click', async () => {
      try {
        const updated = await api(`/api/orders/${order.id}/reject`, { method: 'POST' });
        showStatus('Order rejected in Human Review gate.', 'warning');
        renderOrderResult(updated);
        renderReviewView();
        refreshMetrics();
      } catch (err) {
        showStatus(`Rejection failed: ${err.message}`, 'danger');
      }
    });

    $('btn-review-reprocess').addEventListener('click', async () => {
      const text = ($('review-edit-text').value || '').trim();
      if (!text) return;
      try {
        const corrected = await api(`/api/orders/${order.id}/correct`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        showStatus('Correction processed successfully.', 'success');
        renderOrderResult(corrected);
        renderReviewView();
        refreshMetrics();
      } catch (err) {
        showStatus(`Reprocessing error: ${err.message}`, 'danger');
      }
    });
  }

  // -------------------------------------------------------------
  // SCREEN 2: DATASET EXPLORER (HIGHEST PRIORITY)
  // -------------------------------------------------------------
  async function loadDatasetExplorer() {
    try {
      // 1. Fetch Evaluation Records
      const evalData = await api('/api/evaluation/records');
      state.evalRecords = evalData.records || [];
      $('badge-dataset-count').textContent = state.evalRecords.length;
      $('metric-eval-count').textContent = state.evalRecords.length;

      // Update split pills count
      const counts = evalData.split_counts || {};
      $('count-split-all').textContent = evalData.total || 60;
      $('count-split-dev').textContent = counts.development || 36;
      $('count-split-val').textContent = counts.validation || 12;
      $('count-split-locked').textContent = counts.locked_test || 12;

      // Populate Categories filter dropdown
      const categories = Array.from(new Set(state.evalRecords.map(r => r.category))).sort();
      const catSelect = $('eval-category-select');
      catSelect.innerHTML = '<option value="">All Categories</option>' + categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');

      renderEvalTable();

      // 2. Fetch Catalogue Records
      const catData = await api('/api/catalogue');
      state.catalogueRecords = catData.records || [];
      $('catalogue-count-pill').textContent = `${state.catalogueRecords.length} Loaded SKUs`;
      $('metric-catalogue-count').textContent = state.catalogueRecords.length;
      renderCatalogueTable();

      // 3. Fetch Intake Samples
      const sampleData = await api('/api/dataset');
      state.sampleOrders = sampleData.records || [];
      renderSamplesTable();
      populateIntakeSelect();
    } catch (err) {
      console.error('Failed to load dataset explorer:', err);
      showStatus(`Dataset load error: ${err.message}`, 'danger');
    }
  }

  function renderEvalTable() {
    const tbody = $('eval-table-body');
    if (!tbody) return;

    let records = state.evalRecords.slice();

    // Split filter
    if (state.evalFilter.split !== 'all') {
      records = records.filter(r => r.split === state.evalFilter.split);
    }

    // Category filter
    if (state.evalFilter.category) {
      records = records.filter(r => r.category === state.evalFilter.category);
    }

    // Search filter
    if (state.evalFilter.search) {
      const q = state.evalFilter.search.toLowerCase();
      records = records.filter(r =>
        (r.record_id && r.record_id.toLowerCase().includes(q)) ||
        (r.input_message && r.input_message.toLowerCase().includes(q)) ||
        (r.category && r.category.toLowerCase().includes(q)) ||
        (r.language_category && r.language_category.toLowerCase().includes(q))
      );
    }

    const totalFiltered = records.length;
    const totalPages = Math.max(1, Math.ceil(totalFiltered / state.evalFilter.pageSize));
    if (state.evalFilter.page > totalPages) state.evalFilter.page = totalPages;

    const startIdx = (state.evalFilter.page - 1) * state.evalFilter.pageSize;
    const pageRecords = records.slice(startIdx, startIdx + state.evalFilter.pageSize);

    // Update pagination indicator
    $('eval-pagination-info').textContent = totalFiltered ?
      `Showing ${startIdx + 1} to ${Math.min(startIdx + state.evalFilter.pageSize, totalFiltered)} of ${totalFiltered} records (Total Corpus: 60)` :
      'No records match the filter criteria';
    $('eval-page-number').textContent = `Page ${state.evalFilter.page} of ${totalPages}`;
    $('btn-eval-prev').disabled = state.evalFilter.page <= 1;
    $('btn-eval-next').disabled = state.evalFilter.page >= totalPages;

    if (!pageRecords.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching evaluation records found.</td></tr>';
      return;
    }

    tbody.innerHTML = pageRecords.map(r => {
      const splitBadgeClass = r.split === 'development' ? 'split-dev' : (r.split === 'validation' ? 'split-val' : 'split-locked');
      const isLocked = r.split === 'locked_test';

      return `
        <tr>
          <td><span class="sku-pill">${escapeHtml(r.record_id)}</span></td>
          <td><span class="status-badge ${splitBadgeClass}">${escapeHtml(r.split)}</span></td>
          <td><strong>${escapeHtml(r.category)}</strong></td>
          <td>${escapeHtml(r.language_category)}</td>
          <td>
            ${isLocked ?
              `<span style="color:var(--color-text-muted); font-style:italic;">🔒 ${escapeHtml(r.input_message)}</span>` :
              `<code>${escapeHtml(r.input_message)}</code>`}
          </td>
          <td><span class="meta-pill" style="font-size:0.7rem;">${escapeHtml(r.source_type)}</span></td>
          <td><span class="status-badge pending_review">${escapeHtml(r.annotation_status)}</span></td>
          <td>
            ${!isLocked ? `
              <button class="btn btn-secondary btn-sm btn-test-intake" data-message="${escapeHtml(r.input_message)}" data-id="${escapeHtml(r.record_id)}">
                Test in Intake
              </button>
            ` : '<span style="font-size:0.75rem; color:var(--color-text-muted);">Protected</span>'}
          </td>
        </tr>
      `;
    }).join('');

    // Bind "Test in Intake" buttons
    tbody.querySelectorAll('.btn-test-intake').forEach(btn => {
      btn.addEventListener('click', () => {
        const msg = btn.getAttribute('data-message');
        const id = btn.getAttribute('data-id');
        $('customer-message').value = msg;
        $('char-count').textContent = `${msg.length} / 2000 chars`;
        switchTab('workspace');
        showStatus(`Loaded record ${id} into Order Workspace. Click "Process Order via FastAPI" to test.`, 'info');
      });
    });
  }

  function renderCatalogueTable() {
    const tbody = $('catalogue-table-body');
    if (!tbody) return;

    let records = state.catalogueRecords.slice();
    if (state.catalogueSearch) {
      const q = state.catalogueSearch.toLowerCase();
      records = records.filter(r => Object.values(r).join(' ').toLowerCase().includes(q));
    }

    if (!records.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No matching catalogue products found.</td></tr>';
      return;
    }

    tbody.innerHTML = records.map(p => {
      const aliases = (p.aliases || '').split('|').filter(Boolean);
      return `
        <tr>
          <td><span class="sku-pill">${escapeHtml(p.sku)}</span></td>
          <td><strong>${escapeHtml(p.name)}</strong></td>
          <td>${aliases.map(a => `<span class="meta-pill" style="font-size:0.72rem; margin:0.1rem;">${escapeHtml(a)}</span>`).join(' ')}</td>
          <td>${escapeHtml(p.pack_size || '—')}</td>
          <td><strong>${escapeHtml(p.sellable_unit || '—')}</strong></td>
          <td>${escapeHtml(p.units_per_box || '—')}</td>
          <td><code>${escapeHtml(p.supported_conversions || '—')}</code></td>
          <td><strong>${formatCurrency(p.price)}</strong></td>
          <td><span class="meta-pill" style="font-size:0.7rem;">${escapeHtml(p.dataset_source)}</span></td>
        </tr>
      `;
    }).join('');
  }

  function renderSamplesTable() {
    const tbody = $('samples-table-body');
    if (!tbody) return;

    tbody.innerHTML = state.sampleOrders.map(s => `
      <tr>
        <td><span class="sku-pill">${escapeHtml(s.id)}</span></td>
        <td><strong>${escapeHtml(s.category)}</strong></td>
        <td>${escapeHtml(s.language)}</td>
        <td><code>${escapeHtml(s.message)}</code></td>
        <td><span class="status-badge DRAFT">${escapeHtml(s.annotation_status)}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm btn-load-sample" data-id="${escapeHtml(s.id)}">
            Load into Intake
          </button>
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('.btn-load-sample').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        loadSampleById(id);
        switchTab('workspace');
      });
    });
  }

  function populateIntakeSelect() {
    const sel = $('records-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">Select a pre-built sample order…</option>' +
      state.sampleOrders.map(s => `
        <option value="${s.id}">${s.id} — ${s.category} (${s.language})</option>
      `).join('');
  }

  function loadSampleById(id) {
    const record = state.sampleOrders.find(r => r.id === id);
    if (record) {
      $('customer-message').value = record.message;
      $('records-select').value = record.id;
      $('char-count').textContent = `${record.message.length} / 2000 chars`;
      showStatus(`Loaded ${record.id} (${record.category}) into message box.`, 'info');
    }
  }

  // -------------------------------------------------------------
  // SCREEN 4: OPERATIONAL METRICS
  // -------------------------------------------------------------
  async function refreshMetrics() {
    try {
      const data = await api('/api/metrics');
      state.metricsData = data;

      $('metric-orders-processed').textContent = data.orders_processed ?? 0;
      $('metric-verified-orders').textContent = data.verified_orders ?? 0;
      $('metric-clarification-orders').textContent = data.needs_clarification ?? 0;
      $('metric-approved-orders').textContent = data.approved_orders ?? 0;
      $('metric-rejected-orders').textContent = data.rejected_orders ?? 0;
      $('metric-corrections').textContent = data.corrections ?? 0;
      $('metric-errors').textContent = data.processing_errors ?? 0;
      $('metric-catalogue-count').textContent = data.catalogue_records_loaded ?? 6;
      $('metric-eval-count').textContent = state.evalRecords.length || 60;
      $('metric-benchmark-accuracy').textContent = data.benchmark_accuracy || 'Not available';
    } catch (err) {
      console.error('Failed to refresh metrics:', err);
    }
  }

  // -------------------------------------------------------------
  // SCREEN 5: EVALUATION READINESS & INTEGRITY
  // -------------------------------------------------------------
  async function refreshEvaluation() {
    try {
      const data = await api('/api/evaluation/summary');
      state.evalSummary = data;

      const integrity = data.dataset && data.dataset.frozen_integrity;
      if (integrity && integrity.actual) {
        $('hash-messages-val').textContent = integrity.actual['locked_test_messages.json'] || '—';
        $('hash-annotations-val').textContent = integrity.actual['locked_test_annotations.json'] || '—';
      }

      if (data.baseline) {
        $('eval-status-val').textContent = data.baseline.status || 'Not evaluated';
      }
    } catch (err) {
      console.error('Failed to refresh evaluation summary:', err);
    }
  }

  // -------------------------------------------------------------
  // SCREEN 6: ACTIVITY & AUDIT TRAIL
  // -------------------------------------------------------------
  async function renderAuditView() {
    try {
      // Fetch latest orders list from backend
      const ordersRes = await api('/api/orders');
      if (ordersRes && Array.isArray(ordersRes.records)) {
        state.orders = ordersRes.records;
      }
    } catch (e) {
      // Fall back to local session state
    }

    const tbody = $('audit-orders-body');
    if (!tbody) return;

    if (!state.orders.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No orders processed in this session yet. Run an order in the Workspace!</td></tr>';
      $('audit-trace-container').innerHTML = '<p class="card-subtitle">No trace available.</p>';
      return;
    }

    tbody.innerHTML = state.orders.map(o => `
      <tr style="${state.selectedOrder && state.selectedOrder.id === o.id ? 'background: #f1f8f4;' : ''}">
        <td><span class="sku-pill">${escapeHtml(o.id.slice(0, 8))}…</span></td>
        <td>${formatTime(o.created_at)}</td>
        <td><code>${escapeHtml(o.original_message.slice(0, 35))}${o.original_message.length > 35 ? '…' : ''}</code></td>
        <td><span class="status-badge ${o.state}">${o.state}</span></td>
        <td><strong>${o.lines.length}</strong></td>
        <td>${o.processing_duration_ms} ms</td>
        <td>${o.correction_count}</td>
        <td>
          <button class="btn btn-secondary btn-sm btn-inspect-trace" data-id="${o.id}">
            Inspect Trace
          </button>
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('.btn-inspect-trace').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const found = state.orders.find(o => o.id === id);
        if (found) {
          state.selectedOrder = found;
          renderOrderTrace(found);
          renderAuditView();
        }
      });
    });

    if (state.selectedOrder) {
      renderOrderTrace(state.selectedOrder);
    } else if (state.orders.length) {
      renderOrderTrace(state.orders[0]);
    }
  }

  function renderOrderTrace(order) {
    const container = $('audit-trace-container');
    const heading = $('audit-trace-heading');
    if (!container) return;

    if (heading) {
      heading.textContent = `Execution Event Trace — Order ${order.id.slice(0, 8)}… (${order.state})`;
    }

    container.innerHTML = `
      <div class="trace-timeline">
        ${order.trace.map(tr => `
          <div class="trace-event-item">
            <div class="trace-dot"></div>
            <div class="trace-header">
              <span class="trace-title">${escapeHtml(tr.event)}</span>
              <span class="trace-time">${formatTime(tr.at)}</span>
            </div>
            ${tr.detail ? `<div class="trace-detail">${escapeHtml(tr.detail)}</div>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }

  // -------------------------------------------------------------
  // INITIALIZATION AND EVENT BINDINGS
  // -------------------------------------------------------------
  function setupEventListeners() {
    // Navigation Tabs
    document.querySelectorAll('.nav-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        switchTab(tab.getAttribute('data-tab'));
      });
    });

    // Sub-Tabs for Dataset Explorer
    document.querySelectorAll('.sub-nav-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        switchDatasetSubTab(tab.getAttribute('data-subtab'));
      });
    });

    // Sample Select Dropdown
    $('records-select').addEventListener('change', (e) => {
      const id = e.target.value;
      if (id) loadSampleById(id);
    });

    // Quick Test Presets
    const presets = {
      clear: 'Send 2 box 500ml oil and 5 dozen soap.',
      marathi: 'Bhau, 2 box 500ml oil ani 5 dozen soap pathav.',
      ambiguous: 'Send 3 classic soap.',
      unknown: 'Send 4 mystery drink.',
      'missing-qty': 'Please send soap.',
      conversion: 'Send 3 box small shampoo.'
    };

    document.querySelectorAll('.preset-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const sc = chip.getAttribute('data-scenario');
        if (presets[sc]) {
          $('customer-message').value = presets[sc];
          $('char-count').textContent = `${presets[sc].length} / 2000 chars`;
          showStatus(`Loaded "${chip.textContent}" into message box.`, 'info');
        }
      });
    });

    // Message Character Counter
    $('customer-message').addEventListener('input', (e) => {
      $('char-count').textContent = `${e.target.value.length} / 2000 chars`;
    });

    // Clear Message Button
    $('btn-clear-message').addEventListener('click', () => {
      $('customer-message').value = '';
      $('char-count').textContent = '0 / 2000 chars';
      $('records-select').value = '';
    });

    // Quick Start Button
    const btnQuickStart = $('btn-quick-start');
    if (btnQuickStart) {
      btnQuickStart.addEventListener('click', () => {
        loadSampleById('SYN-DEV-001');
      });
    }

    // Process Order Button
    const btnProcess = $('btn-process');
    btnProcess.addEventListener('click', async () => {
      const message = ($('customer-message').value || '').trim();
      if (!message) {
        showStatus('Please enter or select a customer order message.', 'warning');
        return;
      }

      btnProcess.disabled = true;
      btnProcess.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>
        Processing via FastAPI…
      `;

      try {
        const sourceRecordId = $('records-select').value || null;
        const result = await api('/api/orders/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, source_record_id: sourceRecordId })
        });

        renderOrderResult(result);
        showStatus(`Order processed in ${result.processing_duration_ms} ms with status: ${result.state}`, result.state === 'VERIFIED' ? 'success' : 'warning');
        refreshMetrics();
      } catch (err) {
        showStatus(`Pipeline failure: ${err.message}`, 'danger', 6000);
      } finally {
        btnProcess.disabled = false;
        btnProcess.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
          Process Order via FastAPI
        `;
      }
    });

    // Review Order Selector change
    $('review-order-selector').addEventListener('change', (e) => {
      const id = e.target.value;
      const found = state.orders.find(o => o.id === id);
      if (found) {
        state.selectedOrder = found;
        renderReviewView();
      }
    });

    // Go to Workspace from Review button
    const btnGotoWorkspace = $('btn-goto-workspace-from-review');
    if (btnGotoWorkspace) {
      btnGotoWorkspace.addEventListener('click', () => switchTab('workspace'));
    }

    // Refresh Telemetry Button
    $('btn-refresh-metrics').addEventListener('click', () => {
      refreshMetrics();
      showStatus('Operational telemetry refreshed.', 'info');
    });

    // Dataset Explorer Search & Filters
    $('eval-search').addEventListener('input', (e) => {
      state.evalFilter.search = e.target.value;
      state.evalFilter.page = 1;
      renderEvalTable();
    });

    $('eval-category-select').addEventListener('change', (e) => {
      state.evalFilter.category = e.target.value;
      state.evalFilter.page = 1;
      renderEvalTable();
    });

    document.querySelectorAll('#split-filter-pills .filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('#split-filter-pills .filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.evalFilter.split = pill.getAttribute('data-split');
        state.evalFilter.page = 1;
        renderEvalTable();
      });
    });

    $('btn-eval-prev').addEventListener('click', () => {
      if (state.evalFilter.page > 1) {
        state.evalFilter.page--;
        renderEvalTable();
      }
    });

    $('btn-eval-next').addEventListener('click', () => {
      state.evalFilter.page++;
      renderEvalTable();
    });

    // Catalogue Search
    $('catalogue-search').addEventListener('input', (e) => {
      state.catalogueSearch = e.target.value;
      renderCatalogueTable();
    });
  }

  // App Startup
  async function init() {
    setupEventListeners();
    await loadDatasetExplorer();
    await refreshMetrics();
    await refreshEvaluation();
  }

  window.addEventListener('DOMContentLoaded', init);
})();
