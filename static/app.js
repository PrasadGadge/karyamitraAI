/**
 * KaryaMitra AI - Enterprise MSME Order Automation & Verification Console
 * Phase 3C: UI Excellence and Dataset Transparency
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
    healthData: null,
    activeTab: 'workspace',
    activeSubTab: 'eval',
    evalFilter: {
      split: 'all',
      category: '',
      language: '',
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
    if (num === null || num === undefined || isNaN(num)) return '<span style="color:var(--color-text-muted);">—</span>';
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
    if (tabId === 'products') loadProductsTable();
    if (tabId === 'inventory') loadInventoryTable();
    if (tabId === 'movements') loadMovementsTable();
    if (tabId === 'transport') loadShipmentsTable();
  }

  // Sub-Tab Switcher for Dataset Explorer
  function switchDatasetSubTab(subTabId) {
    state.activeSubTab = subTabId;
    document.querySelectorAll('.sub-nav-tab').forEach(tab => {
      tab.classList.toggle('active', tab.getAttribute('data-subtab') === subTabId);
    });
    $('subview-eval').style.display = subTabId === 'eval' ? 'block' : 'none';
    $('subview-health').style.display = subTabId === 'health' ? 'block' : 'none';
    $('subview-catalogue').style.display = subTabId === 'catalogue' ? 'block' : 'none';
    $('subview-samples').style.display = subTabId === 'samples' ? 'block' : 'none';
  }

  // -------------------------------------------------------------
  // HEALTH & LLM CONFIGURATION
  // -------------------------------------------------------------
  async function checkHealthAndLLM() {
    try {
      const health = await api('/api/health');
      state.healthData = health;

      const llmHint = $('llm-status-hint');
      const llmText = $('llm-config-text');
      const evalLlmBadge = $('eval-llm-config-badge');

      if (health.llm_configured) {
        const modelName = health.llm_model || 'Configured Model';
        if (llmHint) llmHint.textContent = `Live model: ${modelName}`;
        if (llmText) llmText.textContent = `OpenRouter adapter configured with model: ${modelName}. Live requests will be sent when selected.`;
        if (evalLlmBadge) {
          evalLlmBadge.className = 'status-badge VERIFIED';
          evalLlmBadge.textContent = `Configured (${modelName})`;
        }
      } else {
        if (llmHint) llmHint.textContent = 'Unconfigured in environment';
        if (llmText) llmText.textContent = 'Rules-based parser active. LLM is unconfigured (OPENROUTER_API_KEY / OPENROUTER_MODEL not set); selecting LLM will trigger safe fallback to rules.';
        if (evalLlmBadge) {
          evalLlmBadge.className = 'status-badge DRAFT';
          evalLlmBadge.textContent = 'Unconfigured (Rules Primary)';
        }
      }
    } catch (e) {
      console.warn('Health check warning:', e);
    }
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

    // Fallback banner
    const fallbackHtml = order.fallback_reason ? `
      <div class="alert-banner warning" style="margin-bottom:0.85rem;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
        <div>
          <strong>LLM Fallback Activated:</strong> ${escapeHtml(order.fallback_reason)}
          <div style="font-size:0.78rem; margin-top:0.2rem; color:var(--color-text-secondary);">
            Deterministic rules-based extraction was used to complete the request safely without service interruption.
          </div>
        </div>
      </div>
    ` : '';

    // LLM proposal notes (delivery instructions, missing/ambiguous fields)
    const proposalHtml = (order.delivery_instructions || (order.missing_fields && order.missing_fields.length) || (order.ambiguous_fields && order.ambiguous_fields.length)) ? `
      <div class="alert-banner info" style="margin-bottom:0.85rem;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
        <div>
          <strong>Extraction Notes:</strong>
          ${order.delivery_instructions ? `<div><strong>Delivery instructions:</strong> ${escapeHtml(order.delivery_instructions)}</div>` : ''}
          ${order.missing_fields && order.missing_fields.length ? `<div><strong>Identified missing fields:</strong> ${order.missing_fields.map(escapeHtml).join(', ')}</div>` : ''}
          ${order.ambiguous_fields && order.ambiguous_fields.length ? `<div><strong>Identified ambiguous fields:</strong> ${order.ambiguous_fields.map(escapeHtml).join(', ')}</div>` : ''}
        </div>
      </div>
    ` : '';

    // Update 8-step workflow progression
    const stepBar = $('workflow-steps-bar');
    if (stepBar) {
      ['wf-step-1', 'wf-step-2', 'wf-step-3', 'wf-step-4', 'wf-step-5', 'wf-step-6', 'wf-step-7', 'wf-step-8'].forEach(id => {
        const el = $(id);
        if (el) el.classList.remove('active', 'completed');
      });
      // Steps 1 to 5 completed by successful backend processing
      ['wf-step-1', 'wf-step-2', 'wf-step-3', 'wf-step-4', 'wf-step-5'].forEach(id => {
        const el = $(id);
        if (el) el.classList.add('completed');
      });
      if (order.state === 'NEEDS_CLARIFICATION' || order.state === 'DRAFT') {
        const s6 = $('wf-step-6'); if (s6) s6.classList.add('active');
      } else if (order.state === 'VERIFIED') {
        const s6 = $('wf-step-6'); if (s6) s6.classList.add('completed');
        const s7 = $('wf-step-7'); if (s7) s7.classList.add('active');
      } else if (order.state === 'APPROVED') {
        const s6 = $('wf-step-6'); if (s6) s6.classList.add('completed');
        const s7 = $('wf-step-7'); if (s7) s7.classList.add('completed');
        const s8 = $('wf-step-8'); if (s8) s8.classList.add('active');
      } else if (order.state === 'REJECTED') {
        const s6 = $('wf-step-6'); if (s6) s6.classList.add('completed');
        const s7 = $('wf-step-7'); if (s7) s7.classList.add('completed');
      }
    }

    // Build Structured Order Lines Table
    const linesTableRows = order.lines.map((line, idx) => {
      const isOk = line.verified;
      const findings = line.findings || [];
      const rowClass = isOk ? 'line-row-verified' : 'line-row-unresolved';

      // Original quantity text
      const origQty = (line.quantity !== null && line.quantity !== undefined)
        ? `<strong>${line.quantity}</strong> ${escapeHtml(line.requested_unit || 'unit')}`
        : '<span style="color:#b91c1c; font-weight:600;">Missing Qty</span>';

      // Normalized quantity with explicit calculation
      let normQty = '<span style="color:var(--color-text-muted);">—</span>';
      if (line.converted_quantity !== null && line.converted_quantity !== undefined) {
        normQty = `<strong>${line.converted_quantity}</strong> ${escapeHtml(line.sellable_unit || '')}`;
        if (line.requested_unit && line.requested_unit.toLowerCase() !== (line.sellable_unit || '').toLowerCase()) {
          normQty += `<div style="font-size:0.72rem; color:var(--color-text-muted);">(${escapeHtml(line.quantity)} ${escapeHtml(line.requested_unit)} converted)</div>`;
        }
      }

      // SKU and product description
      let skuDesc = '';
      if (line.sku) {
        skuDesc = `<span class="sku-pill">${escapeHtml(line.sku)}</span><div style="font-weight:600; font-size:0.84rem; margin-top:2px; color:var(--color-text-primary);">${escapeHtml(line.product_name)}</div>`;
      } else if (line.match_evidence && line.match_evidence.length > 1) {
        skuDesc = `
          <span class="status-badge NEEDS_CLARIFICATION">Ambiguous (${line.match_evidence.length} matches)</span>
          <div style="font-size:0.75rem; margin-top:3px;">${line.match_evidence.map(m => `<span class="sku-pill" style="margin:1px 2px;">${escapeHtml(m.sku)}</span>`).join('')}</div>
        `;
      } else {
        skuDesc = '<span style="color:#b91c1c; font-weight:600; font-size:0.82rem;">No Catalogue Match</span>';
      }

      // Findings & Diagnostics
      let findingsHtml = '';
      if (findings.length) {
        findingsHtml = `<div style="color:var(--color-warning-text); font-size:0.76rem; line-height:1.3;">⚠️ ${findings.map(escapeHtml).join(' · ')}</div>`;
      } else {
        findingsHtml = '<div style="color:var(--color-success-text); font-size:0.76rem; font-weight:600;">✓ Catalogue rules validated</div>';
      }

      return `
        <tr class="${rowClass}">
          <td style="font-weight:700; color:var(--color-text-muted);">${idx + 1}</td>
          <td><code style="font-size:0.82rem;">${escapeHtml(line.product_text || line.source_text)}</code></td>
          <td>${skuDesc}</td>
          <td>${origQty}</td>
          <td>${normQty}</td>
          <td>${formatCurrency(line.unit_price)}</td>
          <td><strong style="color:var(--color-primary-dark); font-size:0.92rem;">${formatCurrency(line.line_total)}</strong></td>
          <td>
            <span class="status-badge ${isOk ? 'VERIFIED' : 'NEEDS_CLARIFICATION'}">
              ${isOk ? '✓ Verified' : '⚠️ Unresolved'}
            </span>
          </td>
          <td>${findingsHtml}</td>
        </tr>
      `;
    }).join('');

    const subtotal = order.lines.reduce((sum, l) => sum + (Number(l.line_total) || 0), 0);
    const verifiedLinesCount = order.lines.filter(l => l.verified).length;

    const unparsedHtml = order.unrecognised_text && order.unrecognised_text.length ? `
      <div class="alert-banner warning" role="alert" style="margin-top:0.75rem;">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
        <div>
          <strong>Unresolved request text — approval locked:</strong> ${order.unrecognised_text.map(t => `<code>${escapeHtml(t)}</code>`).join(', ')}
          <div style="font-size:0.78rem; margin-top:0.2rem;">These request segments were not converted into order lines. Correct the message before approval.</div>
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
      safeguardExplanation = 'All line items, pack sizes, conversions, and catalogue prices verified. Ready for human sign-off.';
    } else if (order.state === 'NEEDS_CLARIFICATION') {
      safeguardExplanation = 'Approval locked by backend safeguards: order has unresolved items or findings. Operator must correct or reject.';
    } else if (order.state === 'APPROVED') {
      safeguardExplanation = 'Order signed off by operator. Ready for ERP / CSV / JSON export.';
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
          <span class="meta-pill">Actual parser: <strong>${escapeHtml(order.parser.method)} v${escapeHtml(order.parser.version)}</strong></span>
          ${order.parser.requested_method && order.parser.requested_method !== order.parser.method ? `<span class="meta-pill" style="color:var(--color-warning-text);">Requested: ${escapeHtml(order.parser.requested_method)}</span>` : ''}
        </div>
        <div class="order-duration">
          Duration: <strong>${order.processing_duration_ms} ms</strong> · Corrections: <strong>${order.correction_count}</strong>
        </div>
      </div>

      ${errorHtml}
      ${fallbackHtml}
      ${proposalHtml}

      <div style="margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: baseline;">
        <h3 style="font-size: 0.95rem; margin: 0; color: var(--color-text-secondary);">
          Extracted Line Items (${order.lines.length})
        </h3>
        <span style="font-size: 0.8rem; color: var(--color-text-muted);">Source Record: ${escapeHtml(order.source_record_id || 'Direct message')}</span>
      </div>

      <!-- High-Readability Structured Order Result Table -->
      <div class="table-container order-table-container" style="margin-bottom:0.85rem; border:1px solid var(--color-border); border-radius:var(--radius-md); overflow-x:auto;">
        <table class="data-table order-result-table" style="margin:0;">
          <thead>
            <tr>
              <th style="width:32px;">#</th>
              <th style="min-width:130px;">Input Text</th>
              <th style="min-width:170px;">Matched SKU &amp; Product</th>
              <th>Original Qty</th>
              <th>Normalized Qty</th>
              <th>Unit Price</th>
              <th>Line Total</th>
              <th>Validation State</th>
              <th style="min-width:180px;">Safeguard Diagnostics</th>
            </tr>
          </thead>
          <tbody>
            ${order.lines.length ? linesTableRows : '<tr><td colspan="9" class="empty-state">No items could be extracted.</td></tr>'}
          </tbody>
          <tfoot>
            <tr style="background:var(--color-bg-subtle); font-weight:600; border-top:2px solid var(--color-border);">
              <td colspan="3" style="text-align:right;">Order Summary Totals:</td>
              <td colspan="2">Verified: <strong>${verifiedLinesCount} / ${order.lines.length}</strong> lines</td>
              <td>Total:</td>
              <td colspan="3"><strong style="font-size:1.05rem; color:var(--color-primary-dark);">${formatCurrency(subtotal)}</strong></td>
            </tr>
          </tfoot>
        </table>
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
      <div style="margin-top: 1.15rem; border-top: 1px solid var(--color-border); padding-top: 0.85rem;">
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
      <div style="margin-top: 1.15rem;">
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

    // Bind action listeners
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

          <h3 style="font-size: 0.95rem; margin-top: 1.15rem;">2. Natural Language Parsing</h3>
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

          <h3 style="font-size: 0.95rem; margin-top: 1.15rem;">3. Human Clarification / Message Edit</h3>
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
          <h3 style="font-size: 0.95rem; margin-top: 1.15rem;">5. Safeguard Gate Checklist</h3>
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
          <div class="actions-row" style="margin-top: 1.15rem;">
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
      renderCategoryCoverageTable();

      // 2. Fetch Catalogue Records
      const catData = await api('/api/catalogue');
      state.catalogueRecords = catData.records || [];
      $('catalogue-count-pill').textContent = `${state.catalogueRecords.length} Loaded SKUs`;
      $('metric-catalogue-count').textContent = state.catalogueRecords.length;
      $('bar-catalogue-count').textContent = state.catalogueRecords.length;
      renderCatalogueTable();

      // 3. Fetch Intake Samples
      const sampleData = await api('/api/dataset');
      state.sampleOrders = sampleData.records || [];
      const barSamples = $('bar-samples-count');
      if (barSamples) barSamples.textContent = state.sampleOrders.length;
      const barReadiness = $('bar-dataset-readiness');
      if (barReadiness) barReadiness.textContent = `${state.evalRecords.length} Synthetic · Not Evaluated`;
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

    // Language filter
    if (state.evalFilter.language) {
      records = records.filter(r => r.language_category === state.evalFilter.language);
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
              `<span style="color:var(--color-text-muted); font-style:italic;">🔒 [Protected in locked test evaluation]</span>` :
              `<code>${escapeHtml(r.input_message)}</code>`}
          </td>
          <td><span class="meta-pill" style="font-size:0.7rem;">${escapeHtml(r.source_type)}</span></td>
          <td><span class="status-badge pending_review">${escapeHtml(r.annotation_status)}</span></td>
          <td>
            <div style="display:flex; gap:0.35rem; align-items:center;">
              <button class="btn btn-secondary btn-sm btn-inspect-record" data-id="${escapeHtml(r.record_id)}">
                Inspect
              </button>
              ${!isLocked ? `
                <button class="btn btn-primary btn-sm btn-test-intake" data-message="${escapeHtml(r.input_message)}" data-id="${escapeHtml(r.record_id)}">
                  Test
                </button>
              ` : '<span style="font-size:0.72rem; color:var(--color-text-muted); font-style:italic;">Ineligible</span>'}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Bind "Test in Intake" buttons (Dev/Val only)
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

    // Bind "Inspect" buttons (Opens detail modal)
    tbody.querySelectorAll('.btn-inspect-record').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const record = state.evalRecords.find(r => r.record_id === id);
        if (record) openRecordModal(record);
      });
    });
  }

  function renderCategoryCoverageTable() {
    const tbody = $('category-coverage-body');
    if (!tbody || !state.evalRecords.length) return;

    const catMap = {};
    state.evalRecords.forEach(r => {
      if (!catMap[r.category]) {
        catMap[r.category] = { total: 0, dev: 0, val: 0, locked: 0 };
      }
      catMap[r.category].total++;
      if (r.split === 'development') catMap[r.category].dev++;
      else if (r.split === 'validation') catMap[r.category].val++;
      else if (r.split === 'locked_test') catMap[r.category].locked++;
    });

    const categoryDescriptions = {
      'clear order': 'Explicit item and valid pack quantity in English',
      'clear English order': 'Unambiguous English multi-item wholesale request',
      'supported informal order': 'Informal Hinglish/Marathi syntax with ani/pathav',
      'ambiguous product': 'Multiple candidate SKUs (e.g. Classic Soap 100g vs 125g)',
      'unknown product': 'Item absent from products.csv; halted for clarification',
      'missing quantity': 'Product named without valid numerical quantity',
      'missing quantity and unit': 'Product named without quantity or unit specification',
      'unconfigured box conversion': 'Item requested in boxes where units_per_box is undefined',
      'configured box conversion': 'Item requested in boxes with explicit 1:12 conversion',
      'dozen conversion': 'Standard dozen factor (1 dozen = 12 sellable units)',
      'plural unit': 'Plural grammatical variants (bottles, bars, boxes)',
      'unsupported unit': 'Unconfigured unit measurement (e.g. pieces, cartons)',
      'missing catalogue price': 'Catalogue item with null or invalid price',
      'personal identifier present': 'PII present (phone/email/name) requiring masking',
      'multiple products': 'Multi-line composite customer orders',
      'case variation': 'Upper/lower casing variations in product naming',
      'quantity variation': 'Spelled-out vs numerical quantity tokens',
      'registered alias': 'Product matched via secondary registered alias',
      'invalid quantity': 'Zero or negative quantity rejected by safeguards',
      'malformed order': 'Punctuation or whitespace anomalies',
      'unsupported wording': 'Unrecognised freeform conversational filler',
      'mixed conversion': 'Order mixing direct sellable units and pack conversions',
      'mixed configured and unsupported': 'Order with one supported and one unsupported unit',
      'mixed known and unknown': 'Order containing both known and unregistered products',
      'mixed price failure': 'Order where one line has valid price and another is unpriced',
      'mixed valid and ambiguous': 'Order containing a clear line and an ambiguous line',
      'pack size reference': 'Customer mentions pack volume instead of product name',
    };

    const sortedCats = Object.keys(catMap).sort();
    tbody.innerHTML = sortedCats.map(cat => {
      const data = catMap[cat];
      const desc = categoryDescriptions[cat] || 'Synthetic evaluation scenario';
      return `
        <tr>
          <td><strong>${escapeHtml(cat)}</strong></td>
          <td><span class="sku-pill">${data.total}</span></td>
          <td>${data.dev}</td>
          <td>${data.val}</td>
          <td>${data.locked ? `<span style="color:#b91c1c; font-weight:600;">${data.locked} (🔒)</span>` : '0'}</td>
          <td style="font-size:0.82rem; color:var(--color-text-secondary);">${escapeHtml(desc)}</td>
        </tr>
      `;
    }).join('');
  }

  function openRecordModal(record) {
    const modal = $('record-detail-modal');
    const body = $('modal-record-body');
    const title = $('modal-record-title');
    if (!modal || !body) return;

    const isLocked = record.split === 'locked_test';
    const splitBadgeClass = record.split === 'development' ? 'split-dev' : (record.split === 'validation' ? 'split-val' : 'split-locked');

    title.textContent = `Record Details: ${record.record_id}`;

    body.innerHTML = `
      <div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:1rem;">
        <span class="status-badge ${splitBadgeClass}">${escapeHtml(record.split)}</span>
        <span class="status-badge pending_review">${escapeHtml(record.annotation_status)}</span>
        <span class="meta-pill">Language: ${escapeHtml(record.language_category)}</span>
        <span class="meta-pill">Source: ${escapeHtml(record.source_type)}</span>
      </div>

      <div style="margin-bottom:1rem;">
        <label style="font-size:0.8rem; font-weight:600; color:var(--color-text-muted); text-transform:uppercase;">Category / Scenario</label>
        <div style="font-weight:700; font-size:1.05rem; color:var(--color-text-primary); margin-top:0.15rem;">
          ${escapeHtml(record.category)}
        </div>
      </div>

      <div style="margin-bottom:1.25rem;">
        <label style="font-size:0.8rem; font-weight:600; color:var(--color-text-muted); text-transform:uppercase;">Input Message Text</label>
        <div style="background:var(--color-bg-subtle); border:1px solid var(--color-border); border-radius:var(--radius-md); padding:0.85rem 1rem; margin-top:0.25rem; font-size:0.92rem;">
          ${isLocked ?
            '<span style="color:var(--color-text-muted); font-style:italic;">🔒 [Locked test message — protected in locked-test evaluation to preserve benchmark integrity]</span>' :
            `<code>${escapeHtml(record.input_message)}</code>`}
        </div>
      </div>

      <div style="background:#ffffff; border:1px solid var(--color-border); border-radius:var(--radius-md); padding:0.85rem 1rem; margin-bottom:1.25rem; font-size:0.82rem;">
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:0.6rem;">
          <div>Reviewer Assignment: <strong>${escapeHtml(record.reviewer_status || 'not_assigned')}</strong></div>
          <div>Ground Truth Privacy: <strong>${isLocked ? 'Strictly Isolated' : 'Candidate Only'}</strong></div>
          <div>Intake Testing Eligibility: <strong>${isLocked ? 'Ineligible (Prevents Leakage)' : 'Eligible for Intake Test'}</strong></div>
          <div>Dataset Version: <strong>v2.0-candidate</strong></div>
        </div>
      </div>

      ${isLocked ? `
        <div class="alert-banner warning" style="margin-bottom:0;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
          <div>
            <strong>Locked Benchmark Safeguard:</strong> This record belongs to the frozen locked-test partition. Expected items, labels, and message text are withheld from interactive testing to maintain uncompromised evaluation integrity.
          </div>
        </div>
      ` : `
        <div class="actions-row">
          <button class="btn btn-primary" id="btn-modal-load-intake">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
            Load into Order Workspace
          </button>
          <button class="btn btn-secondary" id="btn-modal-close-action">Close</button>
        </div>
      `}
    `;

    modal.style.display = 'flex';

    if (!isLocked) {
      $('btn-modal-load-intake').addEventListener('click', () => {
        modal.style.display = 'none';
        $('customer-message').value = record.input_message;
        $('char-count').textContent = `${record.input_message.length} / 2000 chars`;
        switchTab('workspace');
        showStatus(`Loaded record ${record.record_id} into Order Workspace. Click "Process Order via FastAPI" to test.`, 'info');
      });
      $('btn-modal-close-action').addEventListener('click', () => {
        modal.style.display = 'none';
      });
    }
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
      const unitsPerBox = p.units_per_box ? escapeHtml(p.units_per_box) : '<span style="color:var(--color-text-muted);">Not defined</span>';
      const priceDisplay = p.price && !isNaN(Number(p.price)) ?
        `<strong>${formatCurrency(p.price)}</strong>` :
        '<span class="status-badge NEEDS_CLARIFICATION">Not configured (Price Missing)</span>';

      return `
        <tr>
          <td><span class="sku-pill">${escapeHtml(p.sku)}</span></td>
          <td><strong>${escapeHtml(p.name)}</strong></td>
          <td>${aliases.map(a => `<span class="meta-pill" style="font-size:0.72rem; margin:0.1rem;">${escapeHtml(a)}</span>`).join(' ')}</td>
          <td>${escapeHtml(p.pack_size || '—')}</td>
          <td><strong>${escapeHtml(p.sellable_unit || '—')}</strong></td>
          <td>${unitsPerBox}</td>
          <td><code>${escapeHtml(p.supported_conversions || '—')}</code></td>
          <td>${priceDisplay}</td>
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

      // Update KPI Cards
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

      // Update Session Bar
      $('bar-orders-processed').textContent = data.orders_processed ?? 0;
      $('bar-verified-orders').textContent = data.verified_orders ?? 0;
      $('bar-clarification-orders').textContent = data.needs_clarification ?? 0;
      $('bar-approved-orders').textContent = data.approved_orders ?? 0;
      $('bar-catalogue-count').textContent = data.catalogue_records_loaded ?? 6;
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
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No orders processed in this session yet. Run an order in the Workspace!</td></tr>';
      $('audit-trace-container').innerHTML = '<p class="card-subtitle">No trace available.</p>';
      return;
    }

    tbody.innerHTML = state.orders.map(o => `
      <tr style="${state.selectedOrder && state.selectedOrder.id === o.id ? 'background: #f1f8f4;' : ''}">
        <td><span class="sku-pill">${escapeHtml(o.id.slice(0, 8))}…</span></td>
        <td>${formatTime(o.created_at)}</td>
        <td><code>${escapeHtml(o.original_message.slice(0, 30))}${o.original_message.length > 30 ? '…' : ''}</code></td>
        <td><span class="meta-pill" style="font-size:0.72rem;">${escapeHtml(o.parser?.method || 'rules')}</span></td>
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

    // Extraction Method Change Warning/Hint
    $('extraction-method').addEventListener('change', (e) => {
      const val = e.target.value;
      const callout = $('llm-config-text');
      if (val === 'llm') {
        if (state.healthData && state.healthData.llm_configured) {
          callout.textContent = `Live LLM selected: ${state.healthData.llm_model}. Requests will use OpenRouter chat completions.`;
        } else {
          callout.textContent = `LLM adapter is unconfigured in current environment. Safe automatic fallback to rules parser will occur.`;
        }
      } else {
        callout.textContent = `Deterministic rules-based parser active. Fast, local, offline-safe execution.`;
      }
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

    // Modal Close Button
    const btnCloseModal = $('btn-close-modal');
    if (btnCloseModal) {
      btnCloseModal.addEventListener('click', () => {
        $('record-detail-modal').style.display = 'none';
      });
    }

    // Close modal on escape key or backdrop click
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const m = $('record-detail-modal');
        if (m && m.style.display !== 'none') m.style.display = 'none';
      }
    });

    const modalBackdrop = $('record-detail-modal');
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', (e) => {
        if (e.target === modalBackdrop) modalBackdrop.style.display = 'none';
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
        const extractionMethod = $('extraction-method').value || 'rules';
        const result = await api('/api/orders/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, source_record_id: sourceRecordId, extraction_method: extractionMethod })
        });

        renderOrderResult(result);
        const statusType = result.state === 'VERIFIED' ? 'success' : 'warning';
        showStatus(`Order processed in ${result.processing_duration_ms} ms with state: ${result.state}`, statusType);
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

    $('eval-language-select').addEventListener('change', (e) => {
      state.evalFilter.language = e.target.value;
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

    // Products Search
    const productsSearch = $('products-search');
    if (productsSearch) {
      productsSearch.addEventListener('input', loadProductsTable);
    }

    const productsFilterActive = $('products-filter-active');
    if (productsFilterActive) {
      productsFilterActive.addEventListener('change', loadProductsTable);
    }

    // Inventory Low Stock Filter
    const inventoryLowStock = $('inventory-low-stock-only');
    if (inventoryLowStock) {
      inventoryLowStock.addEventListener('change', loadInventoryTable);
    }

    // Movements Search
    const movementsSearch = $('movements-search-sku');
    if (movementsSearch) {
      movementsSearch.addEventListener('input', loadMovementsTable);
    }

    // Shipments Filter
    const shipmentsFilterStatus = $('shipments-filter-status');
    if (shipmentsFilterStatus) {
      shipmentsFilterStatus.addEventListener('change', loadShipmentsTable);
    }
  }

  // -------------------------------------------------------------
  // SCREEN 3: COMPANY PRODUCTS
  // -------------------------------------------------------------
  async function loadProductsTable() {
    try {
      const search = $('products-search')?.value || '';
      const activeFilter = $('products-filter-active')?.value || '';
      const is_active = activeFilter === '' ? null : activeFilter === 'true';

      const data = await api(`/api/products?search=${encodeURIComponent(search)}&is_active=${is_active !== null ? is_active : ''}`);
      renderProductsTable(data.records || []);
    } catch (err) {
      console.error('Failed to load products:', err);
    }
  }

  function renderProductsTable(products) {
    const tbody = $('products-table-body');
    if (!tbody) return;

    if (!products.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No products found.</td></tr>';
      return;
    }

    tbody.innerHTML = products.map(p => `
      <tr>
        <td><span class="sku-pill">${escapeHtml(p.sku)}</span></td>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td>${escapeHtml(p.category)}</td>
        <td>${escapeHtml(p.base_unit)}</td>
        <td>${escapeHtml(p.sellable_unit)}</td>
        <td>${formatCurrency(p.unit_price)}</td>
        <td>${p.low_stock_threshold}</td>
        <td><span class="status-badge ${p.is_active ? 'VERIFIED' : 'DRAFT'}">${p.is_active ? 'Active' : 'Inactive'}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="showStatus('Edit product feature coming soon', 'info')">Edit</button>
        </td>
      </tr>
    `).join('');
  }

  // -------------------------------------------------------------
  // SCREEN 4: INVENTORY
  // -------------------------------------------------------------
  async function loadInventoryTable() {
    try {
      const lowStockOnly = $('inventory-low-stock-only')?.checked || false;
      const data = await api(`/api/inventory?low_stock_only=${lowStockOnly}`);
      renderInventoryTable(data.records || []);
    } catch (err) {
      console.error('Failed to load inventory:', err);
    }
  }

  function renderInventoryTable(inventory) {
    const tbody = $('inventory-table-body');
    if (!tbody) return;

    if (!inventory.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No inventory records found.</td></tr>';
      return;
    }

    tbody.innerHTML = inventory.map(inv => {
      const isLowStock = inv.available_quantity <= inv.low_stock_threshold;
      const statusClass = isLowStock ? 'warning' : 'VERIFIED';
      const statusText = isLowStock ? 'Low Stock' : 'OK';

      return `
      <tr>
        <td><span class="sku-pill">${escapeHtml(inv.sku)}</span></td>
        <td><strong>${escapeHtml(inv.name)}</strong></td>
        <td>${inv.on_hand_quantity} ${escapeHtml(inv.sellable_unit)}</td>
        <td>${inv.reserved_quantity}</td>
        <td><strong style="color: ${isLowStock ? 'var(--color-warning-text)' : 'var(--color-success-text)'}">${inv.available_quantity}</strong></td>
        <td>${inv.incoming_quantity}</td>
        <td>${inv.low_stock_threshold}</td>
        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="showStatus('Adjust stock feature coming soon', 'info')">Adjust</button>
        </td>
      </tr>
    `;
    }).join('');
  }

  // -------------------------------------------------------------
  // SCREEN 5: STOCK MOVEMENTS
  // -------------------------------------------------------------
  async function loadMovementsTable() {
    try {
      const sku = $('movements-search-sku')?.value || '';
      const data = await api(`/api/stock-movements?sku=${encodeURIComponent(sku)}`);
      renderMovementsTable(data.records || []);
    } catch (err) {
      console.error('Failed to load movements:', err);
    }
  }

  function renderMovementsTable(movements) {
    const tbody = $('movements-table-body');
    if (!tbody) return;

    if (!movements.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No stock movements found.</td></tr>';
      return;
    }

    tbody.innerHTML = movements.map(m => {
      const deltaClass = m.quantity > 0 ? 'success' : 'danger';
      const deltaPrefix = m.quantity > 0 ? '+' : '';

      return `
      <tr>
        <td>${m.id}</td>
        <td><span class="sku-pill">${escapeHtml(m.sku)}</span></td>
        <td>${escapeHtml(m.product_name)}</td>
        <td><span class="status-badge ${deltaClass}">${deltaPrefix}${m.quantity}</span></td>
        <td>${escapeHtml(m.movement_type)}</td>
        <td>${escapeHtml(m.reference_id || '—')}</td>
        <td>${escapeHtml(m.reason || '—')}</td>
        <td>${escapeHtml(m.actor)}</td>
        <td>${formatTime(m.created_at)}</td>
      </tr>
    `;
    }).join('');
  }

  // -------------------------------------------------------------
  // SCREEN 6: TRANSPORT & DELIVERY
  // -------------------------------------------------------------
  async function loadShipmentsTable() {
    try {
      const status = $('shipments-filter-status')?.value || '';
      const data = await api(`/api/shipments?status=${encodeURIComponent(status)}`);
      renderShipmentsTable(data.records || []);
    } catch (err) {
      console.error('Failed to load shipments:', err);
    }
  }

  function renderShipmentsTable(shipments) {
    const tbody = $('shipments-table-body');
    if (!tbody) return;

    if (!shipments.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No shipments found.</td></tr>';
      return;
    }

    tbody.innerHTML = shipments.map(s => {
      const statusClass = s.status === 'delivered' ? 'success' : s.status === 'in_transit' ? 'VERIFIED' : s.status === 'delayed' ? 'warning' : 'DRAFT';

      return `
      <tr>
        <td><span class="sku-pill">${escapeHtml(s.id.slice(0, 8))}…</span></td>
        <td><span class="sku-pill">${escapeHtml(s.order_id.slice(0, 8))}…</span></td>
        <td>${escapeHtml(s.transporter_name || '—')}</td>
        <td>${escapeHtml(s.tracking_reference || '—')}</td>
        <td><span class="status-badge ${statusClass}">${escapeHtml(s.status)}</span></td>
        <td>${s.dispatch_date ? formatTime(s.dispatch_date) : '—'}</td>
        <td>${s.expected_delivery_date ? formatTime(s.expected_delivery_date) : '—'}</td>
        <td>${s.actual_delivery_date ? formatTime(s.actual_delivery_date) : '—'}</td>
        <td>
          ${s.status === 'ready' ? '<button class="btn btn-success btn-sm" onclick="dispatchShipment(\'' + s.id + '\')">Dispatch</button>' : ''}
          ${s.status === 'in_transit' ? '<button class="btn btn-primary btn-sm" onclick="markDelivered(\'' + s.id + '\')">Delivered</button>' : ''}
        </td>
      </tr>
    `;
    }).join('');
  }

  async function dispatchShipment(shipmentId) {
    try {
      await api(`/api/shipments/${shipmentId}/dispatch`, { method: 'POST' });
      showStatus('Shipment dispatched successfully', 'success');
      loadShipmentsTable();
      loadInventoryTable();
    } catch (err) {
      showStatus(`Failed to dispatch: ${err.message}`, 'danger');
    }
  }

  async function markDelivered(shipmentId) {
    try {
      await api(`/api/shipments/${shipmentId}/deliver`, { method: 'POST' });
      showStatus('Shipment marked as delivered', 'success');
      loadShipmentsTable();
    } catch (err) {
      showStatus(`Failed to mark delivered: ${err.message}`, 'danger');
    }
  }

  // App Startup
  async function init() {
    setupEventListeners();
    await checkHealthAndLLM();
    await loadDatasetExplorer();
    await refreshMetrics();
    await refreshEvaluation();
    await updateDashboardSummary();

    const params = new URLSearchParams(window.location.search);
    const tabParam = params.get('tab');
    if (tabParam && ['workspace', 'dataset', 'products', 'inventory', 'movements', 'transport', 'review', 'metrics', 'evaluation', 'audit'].includes(tabParam)) {
      switchTab(tabParam);
    }
    const subtabParam = params.get('subtab');
    if (subtabParam && ['eval', 'health', 'catalogue', 'samples'].includes(subtabParam)) {
      switchDatasetSubTab(subtabParam);
    }
    const sampleParam = params.get('sample');
    if (sampleParam) {
      loadSampleById(sampleParam);
    }
    if (params.get('auto_process') === '1') {
      const btn = $('btn-process');
      if (btn) btn.click();
    }
  }

  async function updateDashboardSummary() {
    try {
      const summary = await api('/api/dashboard/summary');
      if ($('bar-low-stock')) $('bar-low-stock').textContent = summary.low_stock_products;
      if ($('bar-in-transit')) $('bar-in-transit').textContent = summary.in_transit_shipments;

      // Show demo stock label if demo mode is active
      if (summary.demo_mode && $('demo-stock-label')) {
        $('demo-stock-label').style.display = 'inline';
      }
    } catch (err) {
      console.error('Failed to load dashboard summary:', err);
    }
  }

  window.addEventListener('DOMContentLoaded', init);
})();
