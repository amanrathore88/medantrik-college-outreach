/**
 * Medantrik MedTech - Campus Outreach Platform
 * Phase 3 Redesigned Frontend Controller
 */

let allColleges = [];
let filteredColleges = [];
const selection = new CollegeSelection();
let campaignRunning = false;
let csrfToken = "";
let currentPage = 1;

// Auto-recovering fetch interceptor for multi-instance serverless resilience
if (typeof window !== 'undefined' && typeof window.fetch === 'function') {
  const _rawFetch = window.fetch.bind(window);
  window.fetch = async function(input, init) {
    let response = await _rawFetch(input, init);
    if (response && response.status === 403 && init && (init.method || '').toUpperCase() === 'POST') {
      try {
        const cloned = response.clone();
        const data = await cloned.json();
        if (data && data.message && typeof data.message === 'string' && data.message.includes('Reload the dashboard')) {
          const settingsRes = await _rawFetch('/api/settings');
          if (settingsRes.ok) {
            const settings = await settingsRes.json();
            if (settings.csrf_token) {
              csrfToken = settings.csrf_token;
              let headers = init.headers;
              if (typeof Headers !== 'undefined' && headers instanceof Headers) {
                headers.set('X-CSRF-Token', csrfToken);
              } else if (Array.isArray(headers)) {
                headers = headers.filter(([k]) => k.toLowerCase() !== 'x-csrf-token');
                headers.push(['X-CSRF-Token', csrfToken]);
              } else if (headers && typeof headers === 'object') {
                headers = { ...headers, 'X-CSRF-Token': csrfToken };
              } else {
                headers = { 'X-CSRF-Token': csrfToken };
              }
              const retryInit = { ...init, headers };
              response = await _rawFetch(input, retryInit);
            }
          }
        }
      } catch (e) {
        // Not JSON or parse error, ignore
      }
    }
    return response;
  };
}
let pageSize = 25;
let activeTab = 'overview';
let activePreviewCollege = null;
let editingCollege = null;
let currentImportToken = "";
let activeCategory = 'Colleges';
let availableCategories = [];

const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c]));

const statusNames = {
  'verified': 'Verified on official site',
  'directory-listed': 'Official directory only',
  'unverified': 'Unverified',
  'missing': 'Email missing'
};

const fieldLabels = {
  College_Name: 'Name / Organization',
  category: 'Category',
  City: 'Area',
  Campus: 'Campus / Branch',
  Location: 'Address / Locality',
  District: 'District',
  Type: 'Institution Type / Disciplines',
  Institution_ID: 'Official Institution ID (AISHE / Affiliation)',
  Aliases: 'Alternate Names',
  Website: 'Official Website URL',
  TPO_Email: 'Contact Email',
  contact_type: 'Contact Type',
  Contact_Person: 'Contact Role / Designation',
  Phone: 'Office Phone Number',
  source_url: 'Email Evidence Source URL',
  institution_source: 'Institution Directory Source URL',
  checked_on: 'Email Checked On Date',
  verification_status: 'Verification Status',
  notes: 'Review Notes & Documented Gaps'
};

// ==================== NAVIGATION ====================
function switchTab(tabId) {
  activeTab = tabId;
  if (typeof document !== 'undefined') {
    document.querySelectorAll('.nav-tab').forEach(t => {
      if (t.dataset.tab === tabId) t.classList.add('active');
      else t.classList.remove('active');
    });
    document.querySelectorAll('.tab-view').forEach(v => {
      const targetId = 'tab' + tabId.charAt(0).toUpperCase() + tabId.slice(1);
      if (v.id === targetId) v.classList.add('active');
      else v.classList.remove('active');
    });
  }
  if (tabId === 'overview') loadOverview();
  else if (tabId === 'campaigns') {
    updateCampaignRecipientList();
    loadCampaignHistory();
    refreshQueueStatus();
    updateCampaignDurationEstimate();
  }
  else if (tabId === 'templates') renderTemplatePreviewList();
}

// ==================== LOGGING ====================
function addLog(msg, type = '') {
  const box = document.getElementById('logBox');
  if (!box) return;
  const time = new Date().toLocaleTimeString();
  let colorClass = '';
  if (type === 'success') colorClass = 'log-success';
  else if (type === 'error') colorClass = 'log-error';
  else if (type === 'warn') colorClass = 'log-warn';
  box.innerHTML += `<div class="log-entry ${colorClass}">[${time}] ${escapeHtml(msg)}</div>`;
  box.scrollTop = box.scrollHeight;
}

function clearLog() {
  const box = document.getElementById('logBox');
  if (box) box.innerHTML = '<div class="log-entry">[CLEARED] Activity log reset.</div>';
}

// ==================== DATA INITIALIZATION ====================
async function loadColleges() {
  if (typeof fetch === 'undefined') return;
  try {
    const settingsResponse = await fetch('/api/settings');
    if (settingsResponse.ok) {
      const settings = await settingsResponse.json();
      csrfToken = settings.csrf_token || '';
      const emailEl = document.getElementById('senderEmail');
      const settingsEmailEl = document.getElementById('settingsSenderEmail');
      if (emailEl) emailEl.value = settings.sender_email || '';
      if (settingsEmailEl) settingsEmailEl.value = settings.sender_email || '';
      const subjEl = document.getElementById('subjectLine');
      const settingsSubjEl = document.getElementById('settingsSubject');
      if (subjEl) subjEl.value = settings.subject_line || '';
      if (settingsSubjEl) settingsSubjEl.value = settings.subject_line || '';
    }

    const res = await fetch('/api/colleges');
    if (!res.ok) throw new Error('Could not load college directory');
    allColleges = await res.json();

    const blockedEmails = new Set(allColleges.filter(c => c.do_not_contact).map(c => c.TPO_Email));
    allColleges.forEach(c => {
      if (blockedEmails.has(c.TPO_Email)) c.sendable = false;
    });

    if (typeof sessionStorage !== 'undefined') {
      try {
        const incoming = JSON.parse(sessionStorage.getItem('directorySelection') || '[]');
        incoming.forEach(id => {
          if (allColleges.some(c => c.id === id && c.sendable)) selection.set(id, true);
        });
        sessionStorage.removeItem('directorySelection');
      } catch (_) {}
    }

    await loadCategories();
    filterColleges();
    loadOverview();
    populateTemplateCollegeSelector();
    await loadTemplates();
  } catch (e) {
    addLog('Initialization notice: ' + e, 'warn');
  }
}

// ==================== OVERVIEW SCREEN ====================
async function loadOverview() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/overview');
    if (!res.ok) return;
    const data = await res.json();

    // KPIs
    const kpiTotal = document.getElementById('kpiTotal');
    if (kpiTotal) kpiTotal.innerText = data.total;
    const kpiSendable = document.getElementById('kpiSendable');
    if (kpiSendable) kpiSendable.innerText = data.sendable;
    const kpiDir = document.getElementById('kpiDirectoryListed');
    if (kpiDir) kpiDir.innerText = data.directory_listed;
    const kpiRev = document.getElementById('kpiNeedsReview');
    if (kpiRev) kpiRev.innerText = data.needs_review;
    const kpiMiss = document.getElementById('kpiMissing');
    if (kpiMiss) kpiMiss.innerText = data.missing;

    // Badges & Pills
    const navCollegesCount = document.getElementById('navCollegesCount');
    if (navCollegesCount) navCollegesCount.innerText = data.total;
    const navStatPill = document.getElementById('navStatPill');
    if (navStatPill) navStatPill.innerText = `${data.sendable} Verified & Sendable`;
    const dupBadge = document.getElementById('duplicateBadgeCount');
    if (dupBadge) dupBadge.innerText = `${data.duplicates_count} candidate pairs`;

    // Area Coverage Grid
    const areaGrid = document.getElementById('areaCardsGrid');
    if (areaGrid && data.coverage) {
      areaGrid.innerHTML = data.coverage.map(a => `
        <div class="area-card" onclick="filterByArea('${escapeHtml(a.area)}')">
          <div class="area-header">
            <span class="area-name">${escapeHtml(a.area)}</span>
            <span class="area-total">${a.identified}</span>
          </div>
          <div class="area-stats">
            <div><span class="area-tag-verified">${a.verified} verified</span> · ${a.directory_listed} directory</div>
            <div>${a.contact_found} contacts found · <span class="area-tag-missing">${a.missing} missing</span></div>
            <div style="color: var(--primary); font-weight: 600; margin-top: 4px;">${a.sendable} sendable →</div>
          </div>
        </div>
      `).join('');
    }

    // Records Needing Review
    const revBody = document.getElementById('overviewReviewBody');
    if (revBody && data.records_needing_review) {
      if (data.records_needing_review.length === 0) {
        revBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 14px;">All records verified!</td></tr>';
      } else {
        revBody.innerHTML = data.records_needing_review.map(r => `
          <tr>
            <td><strong>${escapeHtml(r.College_Name)}</strong><br><small style="color: var(--text-muted);">${escapeHtml(r.notes || '')}</small></td>
            <td><span class="tag-loc">${escapeHtml(r.City)}</span></td>
            <td><span class="badge ${r.verification_status === 'missing' ? 'badge-missing' : r.verification_status === 'directory-listed' ? 'badge-directory' : 'badge-unverified'}">${escapeHtml(statusNames[r.verification_status] || r.verification_status)}</span></td>
            <td><button class="btn btn-outline btn-sm" onclick="openDetailDrawer(${r.id})">Review</button></td>
          </tr>
        `).join('');
      }
    }

    // Dispatches and Failures
    const failBody = document.getElementById('overviewFailuresBody');
    if (failBody && data.failures) {
      if (data.failures.length === 0) {
        failBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 14px;">No dispatch failures recorded. System healthy.</td></tr>';
      } else {
        failBody.innerHTML = data.failures.map(f => `
          <tr>
            <td><strong>${escapeHtml(f.recipient_email)}</strong><br><small>${escapeHtml(f.college_name || '')}</small></td>
            <td><span class="badge badge-missing">Failed</span></td>
            <td style="color: var(--danger); font-size: 11.5px;">${escapeHtml(f.error_message || 'Error')}</td>
            <td><small>${escapeHtml(f.sent_at || '')}</small></td>
          </tr>
        `).join('');
      }
    }

    // Recruitment Pipeline Funnel & Follow-ups (Phase 6)
    if (data.pipeline) {
      renderPipelineOverview(data.pipeline);
    } else {
      loadPipelineOverview();
    }

    loadCampaignHistory();
  } catch (e) {
    console.error('Failed to load overview:', e);
  }
}

function renderPipelineOverview(pipelineData) {
  if (!pipelineData) return;
  const stages = pipelineData.stages || {};
  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.innerText = val || 0;
  };
  setEl('funnelNotContacted', stages.not_contacted);
  setEl('funnelContacted', stages.contacted);
  setEl('funnelReplied', stages.replied);
  setEl('funnelMeeting', stages.meeting_arranged);
  setEl('funnelActive', stages.partnership_active);
  setEl('funnelDeclined', stages.declined);

  const fu = pipelineData.follow_ups || {};
  const fuBadge = document.getElementById('followUpBadgeCount');
  if (fuBadge) {
    fuBadge.innerText = `${fu.total_pending || 0} pending`;
  }

  const fuBody = document.getElementById('overviewFollowUpsBody');
  if (fuBody) {
    const urgentItems = fu.urgent_items || [];
    if (urgentItems.length === 0) {
      fuBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 14px;">No urgent follow-ups pending.</td></tr>';
    } else {
      fuBody.innerHTML = urgentItems.map(item => `
        <tr>
          <td>
            <strong>${escapeHtml(item.College_Name)}</strong><br>
            <small style="color: var(--text-muted);">${escapeHtml(item.City)} · ${escapeHtml(item.Contact_Person || '')}</small>
          </td>
          <td><strong style="color: #b45309;">${escapeHtml(item.follow_up_date)}</strong></td>
          <td><span class="badge badge-stage-${item.recruitment_stage}">${escapeHtml(item.stage_label || item.recruitment_stage)}</span></td>
          <td><small>${escapeHtml(item.assigned_to || 'Hiring Team')}</small></td>
          <td><button class="btn btn-outline btn-sm" onclick="openDetailDrawer(${item.id})">Action</button></td>
        </tr>
      `).join('');
    }
  }
}

async function loadPipelineOverview() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/pipeline');
    if (res.ok) {
      const data = await res.json();
      renderPipelineOverview(data);
    }
  } catch (err) {
    console.error('Failed to fetch pipeline overview:', err);
  }
}

function filterByArea(area) {
  switchTab('colleges');
  const filterArea = document.getElementById('filterArea');
  if (filterArea) filterArea.value = area;
  filterColleges();
}

function filterByReviewNeeded() {
  switchTab('colleges');
  const filterStatus = document.getElementById('filterStatus');
  if (filterStatus) filterStatus.value = 'missing';
  filterColleges();
}

function filterByStage(stage) {
  switchTab('colleges');
  const filterStage = document.getElementById('filterStage');
  if (filterStage) filterStage.value = stage;
  filterColleges();
}

function exportPipelineCSV() {
  if (typeof window !== 'undefined') {
    window.location.href = '/api/export/pipeline';
  }
}

function exportOutreachCSV() {
  if (typeof window !== 'undefined') {
    window.location.href = '/api/export/outreach';
  }
}

function exportCampaignCSV(campaignId) {
  if (typeof window !== 'undefined') {
    window.location.href = `/api/export/campaign?id=${campaignId}`;
  }
}

function exportCurrentCategoryCSV() {
  if (typeof window !== 'undefined') {
    const cat = activeCategory || 'Colleges';
    window.location.href = `/api/export/csv?category=${encodeURIComponent(cat)}`;
  }
}

function exportMultiCategoryWorkbook() {
  if (typeof window !== 'undefined') {
    window.location.href = '/api/export/sheets';
  }
}

// ==================== COLLEGES TABLE RENDERING & SELECTION ====================
function renderCollegesView() {
  const startIdx = (currentPage - 1) * pageSize;
  const pageItems = filteredColleges.slice(startIdx, startIdx + pageSize);

  renderTable(pageItems);

  // Pagination texts
  const total = filteredColleges.length;
  const maxPage = Math.max(1, Math.ceil(total / pageSize));
  const infoEl = document.getElementById('paginationInfo');
  if (infoEl) {
    const end = Math.min(startIdx + pageSize, total);
    infoEl.innerText = total > 0 ? `Showing ${startIdx + 1}–${end} of ${total} matching colleges` : 'No matching colleges';
  }
  const pageIndicator = document.getElementById('pageIndicator');
  if (pageIndicator) pageIndicator.innerText = `Page ${currentPage} of ${maxPage}`;

  const prevBtn = document.getElementById('btnPrevPage');
  if (prevBtn) prevBtn.disabled = currentPage <= 1;
  const nextBtn = document.getElementById('btnNextPage');
  if (nextBtn) nextBtn.disabled = currentPage >= maxPage;

  // Counts in action bar
  const visibleSendable = pageItems.filter(c => c.sendable).length;
  const totalMatchingSendable = filteredColleges.filter(c => c.sendable).length;
  const visCountEl = document.getElementById('visibleSendableCount');
  if (visCountEl) visCountEl.innerText = visibleSendable;
  const totCountEl = document.getElementById('totalMatchingSendableCount');
  if (totCountEl) totCountEl.innerText = totalMatchingSendable;

  const summaryEl = document.getElementById('collegesResultSummary');
  if (summaryEl) {
    const catLabel = activeCategory.toLowerCase() === 'all' ? 'All Categories' : activeCategory;
    summaryEl.innerText = `${total} ${catLabel.toLowerCase()} match current filters (${totalMatchingSendable} verified & sendable).`;
  }
}

function renderTable(list) {
  const tbody = document.getElementById('collegesBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const stageLabels = {
    'not_contacted': 'Not Contacted',
    'contacted': 'Contacted',
    'replied': 'Replied',
    'meeting_arranged': 'Meeting Arranged',
    'partnership_active': 'Partnership Active',
    'declined': 'Declined'
  };

  list.forEach(c => {
    const tr = document.createElement('tr');
    if (selection.has(c.id) && tr.classList) tr.classList.add('row-selected');
    const checkedAttr = selection.has(c.id) ? "checked" : "";
    const disabledAttr = c.sendable ? "" : "disabled";
    const statusBadgeClass = c.verification_status === 'verified' ? 'badge-verified' :
                             c.verification_status === 'directory-listed' ? 'badge-directory' :
                             c.verification_status === 'missing' ? 'badge-missing' : 'badge-unverified';
    const stage = c.recruitment_stage || 'not_contacted';
    const stageLabel = stageLabels[stage] || 'Not Contacted';

    tr.innerHTML = `
      <td><input type="checkbox" class="college-check" value="${c.id}" ${checkedAttr} ${disabledAttr} onchange="toggleCollege(this)"></td>
      <td>
        <strong>${escapeHtml(c.College_Name)}</strong>
        ${c.category && c.category.toLowerCase() !== 'colleges' ? `<span class="category-tag-badge">${escapeHtml(c.category)}</span>` : ''}
        <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">
          ${escapeHtml(c.Campus ? 'Campus: ' + c.Campus : c.Type || '')}
          ${c.Website ? ` · <a href="${escapeHtml(c.Website)}" target="_blank" rel="noopener" style="color: var(--primary);">Official Website ↗</a>` : ''}
        </div>
      </td>
      <td>
        <span class="tag-loc">${escapeHtml(c.City || c.Location || '')}</span>
        <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">${escapeHtml(c.Location || c.District || '')}</div>
      </td>
      <td style="color: #0369a1;">
        <strong>${escapeHtml(c.TPO_Email || 'Email not found')}</strong>
        <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 2px;">
          <span class="badge ${c.contact_type === 'placement' ? 'badge-placement' : 'badge-general'}">${escapeHtml(c.contact_type === 'general' ? 'General contact' : c.contact_type === 'placement' ? 'Placement Cell' : 'Unconfirmed')}</span>
          ${c.Contact_Person ? ' · ' + escapeHtml(c.Contact_Person) : ''}
          ${c.Phone ? ' · 📞 ' + escapeHtml(c.Phone) : ''}
          ${c.do_not_contact ? ' · <strong style="color: var(--danger);">Do not contact</strong>' : ''}
        </div>
      </td>
      <td>
        <div><span class="badge badge-stage-${stage}">${escapeHtml(stageLabel)}</span></div>
        <div style="margin-top: 4px;">
          <span class="badge ${statusBadgeClass}">${escapeHtml(statusNames[c.verification_status] || c.verification_status || 'Unknown')}</span>
        </div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
          ${c.checked_on ? 'Checked ' + escapeHtml(c.checked_on) : 'Not checked'}
          ${c.source_url ? ` · <a href="${escapeHtml(c.source_url)}" target="_blank" rel="noopener" style="color: var(--primary);">Source ↗</a>` : ''}
        </div>
      </td>
      <td>
        <div style="font-size: 11.5px; color: var(--text);">${escapeHtml(c.last_outreach || 'Never')}</div>
        ${c.recently_contacted ? `<div style="margin-top: 3px;"><span class="badge badge-warning-recent" title="Contacted within last 14 days">⚠️ Recently Contacted</span></div>` : ''}
        ${c.follow_up_date ? `<div style="font-size: 11px; color: #b45309; font-weight: 600; margin-top: 3px;">⏰ Due: ${escapeHtml(c.follow_up_date)}</div>` : ''}
      </td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="openDetailDrawer(${c.id})">Details</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  updateSelectedCount();
}

function toggleCollege(checkbox) {
  selection.set(Number(checkbox.value), checkbox.checked);
  updateSelectedCount();
}

function updateSelectedCount() {
  const count = selection.ids().length;
  const countEl = document.getElementById('selectedCount');
  if (countEl) countEl.innerText = count;

  const visible = [...document.querySelectorAll('.college-check')].filter(cb => !cb.disabled);
  const checked = visible.filter(cb => cb.checked).length;
  const master = document.getElementById('checkMaster');
  if (master) {
    master.checked = visible.length > 0 && checked === visible.length;
    master.indeterminate = checked > 0 && checked < visible.length;
  }

  const btnSend = document.getElementById('btnSendAll');
  if (btnSend) {
    btnSend.disabled = campaignRunning || count === 0;
  }

  updateFloatingBar();
}

function updateFloatingBar() {
  const bar = document.getElementById('floatingActionBar');
  const count = selection.ids().length;
  if (bar && bar.classList) {
    if (count > 0) bar.classList.add('active');
    else bar.classList.remove('active');
  }
  const barCount = document.getElementById('barSelectedCount');
  if (barCount) barCount.innerText = count;
  const navBadge = document.getElementById('navCampaignsSelected');
  if (navBadge) navBadge.innerText = count;
  const campBadge = document.getElementById('campaignRecipientsBadge');
  if (campBadge) campBadge.innerText = `${count} Selected`;
}

function selectAll(state) {
  if (!state) selection.clear();
  document.querySelectorAll('.college-check').forEach(cb => {
    if (cb.disabled) return;
    cb.checked = state;
    selection.set(Number(cb.value), state);
  });
  updateSelectedCount();
}

function toggleMaster(master) {
  document.querySelectorAll('.college-check').forEach(cb => {
    if (cb.disabled) return;
    cb.checked = master.checked;
    selection.set(Number(cb.value), master.checked);
  });
  updateSelectedCount();
}

function selectThisPage() {
  const startIdx = (currentPage - 1) * pageSize;
  const pageItems = filteredColleges.slice(startIdx, startIdx + pageSize);
  pageItems.forEach(c => {
    if (c.sendable) selection.set(c.id, true);
  });
  renderCollegesView();
}

function selectAllMatches() {
  filteredColleges.forEach(c => {
    if (c.sendable) selection.set(c.id, true);
  });
  renderCollegesView();
}

function clearAllSelection() {
  selection.clear();
  renderCollegesView();
}

function filterColleges() {
  const searchInput = document.getElementById('searchInput');
  const q = searchInput ? (searchInput.value || '').toLowerCase().replaceAll('gurgaon', 'gurugram') : '';
  const cityEl = document.getElementById('filterArea');
  const city = cityEl ? cityEl.value : '';
  const statusEl = document.getElementById('filterStatus');
  const status = statusEl ? statusEl.value : '';
  const kindEl = document.getElementById('filterKind');
  const kind = kindEl ? kindEl.value : '';
  const discEl = document.getElementById('filterDiscipline');
  const disc = discEl ? (discEl.value || '').toLowerCase() : '';
  const stageEl = document.getElementById('filterStage');
  const stage = stageEl ? stageEl.value : '';

  filteredColleges = allColleges.filter(c => {
    if (activeCategory && activeCategory.toLowerCase() !== 'all') {
      const cat = (c.category || 'Colleges').toLowerCase();
      if (cat !== activeCategory.toLowerCase()) return false;
    }
    if (city && c.City !== city) return false;
    if (status && c.verification_status !== status) return false;
    if (kind && c.contact_type !== kind) return false;
    if (disc && !(c.Type || '').toLowerCase().includes(disc)) return false;
    if (stage && (c.recruitment_stage || 'not_contacted') !== stage) return false;
    if (q) {
      const haystack = [c.College_Name, c.category, c.Location, c.City, c.District, c.Campus, c.Aliases, c.TPO_Email, c.Type].join(' ').toLowerCase().replaceAll('gurgaon', 'gurugram');
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  currentPage = 1;
  renderCollegesView();
}

function changePage(delta) {
  const maxPage = Math.max(1, Math.ceil(filteredColleges.length / pageSize));
  const newPage = currentPage + delta;
  if (newPage >= 1 && newPage <= maxPage) {
    currentPage = newPage;
    renderCollegesView();
  }
}

function changePageSize(newSize) {
  pageSize = Number(newSize);
  currentPage = 1;
  renderCollegesView();
}

// ==================== DETAIL SLIDEOUT DRAWER ====================
async function openDetailDrawer(collegeId) {
  const overlay = document.getElementById('drawerOverlay');
  const drawer = document.getElementById('collegeDrawer');
  const body = document.getElementById('drawerBody');
  if (!drawer || !body) return;

  const college = allColleges.find(c => c.id === collegeId);
  if (!college) return;

  const stageLabels = {
    'not_contacted': 'Not Contacted',
    'contacted': 'Contacted',
    'replied': 'Replied',
    'meeting_arranged': 'Meeting Arranged',
    'partnership_active': 'Partnership Active',
    'declined': 'Declined'
  };
  const currentStage = college.recruitment_stage || 'not_contacted';

  document.getElementById('drawerCollegeName').innerText = college.College_Name;
  document.getElementById('drawerCollegeSubtitle').innerText = `${college.City} · ${college.Campus || college.Type || 'Higher Education'}`;

  body.innerHTML = `
    <!-- Recruitment Pipeline Stage Card -->
    <div class="drawer-section" style="background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; padding: 12px;">
      <div class="drawer-section-title" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span>🎯 Recruitment Stage</span>
        <span class="badge badge-stage-${currentStage}">${stageLabels[currentStage] || currentStage}</span>
      </div>
      <div style="display: flex; gap: 8px; align-items: center;">
        <select id="drawerStageSelect" class="form-control" style="font-size: 12px; height: 32px;">
          <option value="not_contacted" ${currentStage === 'not_contacted' ? 'selected' : ''}>Not Contacted</option>
          <option value="contacted" ${currentStage === 'contacted' ? 'selected' : ''}>Contacted</option>
          <option value="replied" ${currentStage === 'replied' ? 'selected' : ''}>Replied</option>
          <option value="meeting_arranged" ${currentStage === 'meeting_arranged' ? 'selected' : ''}>Meeting Arranged</option>
          <option value="partnership_active" ${currentStage === 'partnership_active' ? 'selected' : ''}>Partnership Active</option>
          <option value="declined" ${currentStage === 'declined' ? 'selected' : ''}>Declined</option>
        </select>
        <button class="btn btn-primary btn-sm" onclick="submitStageUpdate(${college.id})">Update</button>
      </div>
      <input type="text" id="drawerStageNotes" class="form-control" style="font-size: 11.5px; margin-top: 6px;" placeholder="Optional transition notes (e.g. Dean agreed to meeting)...">
    </div>

    <!-- Follow-up Scheduling Section -->
    <div class="drawer-section" style="background: #fffbeb; border: 1px solid #fef3c7; border-radius: 6px; padding: 12px;">
      <div class="drawer-section-title" style="color: #92400e; margin-bottom: 6px;">⏰ Schedule Follow-up Reminder</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
        <div>
          <label style="font-size: 11px; font-weight: 700; color: #92400e; display: block; margin-bottom: 2px;">Follow-up Date</label>
          <input type="date" id="drawerFollowUpDate" class="form-control" style="font-size: 12px; height: 32px;" value="${college.follow_up_date || ''}">
        </div>
        <div>
          <label style="font-size: 11px; font-weight: 700; color: #92400e; display: block; margin-bottom: 2px;">Assigned To</label>
          <input type="text" id="drawerFollowUpAssigned" class="form-control" style="font-size: 12px; height: 32px;" value="${escapeHtml(college.assigned_to || '')}" placeholder="e.g. Hiring Team">
        </div>
      </div>
      <div style="display: flex; gap: 6px; margin-top: 6px;">
        <button type="button" class="btn btn-outline btn-sm" style="font-size: 11px; padding: 2px 8px;" onclick="setQuickFollowUpDate(3)">+3 Days</button>
        <button type="button" class="btn btn-outline btn-sm" style="font-size: 11px; padding: 2px 8px;" onclick="setQuickFollowUpDate(7)">+1 Week</button>
        <button type="button" class="btn btn-outline btn-sm" style="font-size: 11px; padding: 2px 8px;" onclick="setQuickFollowUpDate(14)">+2 Weeks</button>
      </div>
      <input type="text" id="drawerFollowUpNotes" class="form-control" style="font-size: 11.5px; margin-top: 6px;" placeholder="Follow-up instructions or agenda...">
      <div style="text-align: right; margin-top: 8px;">
        <button class="btn btn-sm btn-primary" onclick="submitFollowUp(${college.id})">Save Follow-up</button>
      </div>
    </div>

    <!-- Record Reply Section -->
    <div class="drawer-section" style="background: #f5f3ff; border: 1px solid #ede9fe; border-radius: 6px; padding: 12px;">
      <div class="drawer-section-title" style="color: #6b21a8; margin-bottom: 4px;">💬 Record Received Reply</div>
      <p style="font-size: 11px; color: #6b21a8; margin: 0 0 6px 0;">Automatically advances stage and halts pending follow-ups in the queue.</p>
      <textarea id="drawerReplyText" rows="2" class="form-control" style="font-size: 12px;" placeholder="Placement officer's response, student interest, proposed interview dates..."></textarea>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
        <select id="drawerReplyStage" class="form-control" style="font-size: 12px; height: 32px; width: auto;">
          <option value="replied" selected>Move to Replied</option>
          <option value="meeting_arranged">Move to Meeting Arranged</option>
          <option value="partnership_active">Move to Partnership Active</option>
          <option value="declined">Move to Declined</option>
        </select>
        <button class="btn btn-sm btn-primary" style="background: #7e22ce; border-color: #7e22ce;" onclick="submitReply(${college.id})">Record Reply</button>
      </div>
    </div>

    <!-- Contact Info Card -->
    <div class="drawer-section">
      <div class="drawer-section-title">Official Placement Contact</div>
      <div class="drawer-row">
        <span class="drawer-label">Email Address:</span>
        <span class="drawer-value" style="color: #0284c7;">${escapeHtml(college.TPO_Email || 'Missing / Not Found')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Contact Type:</span>
        <span class="drawer-value"><span class="badge ${college.contact_type === 'placement' ? 'badge-placement' : 'badge-general'}">${escapeHtml(college.contact_type || 'Unknown')}</span></span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Contact Role / Person:</span>
        <span class="drawer-value">${escapeHtml(college.Contact_Person || 'Not published')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Public Phone:</span>
        <span class="drawer-value">${escapeHtml(college.Phone || 'Not published')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Official Website:</span>
        <span class="drawer-value">${college.Website ? `<a href="${escapeHtml(college.Website)}" target="_blank" rel="noopener" style="color: var(--primary);">Open Website ↗</a>` : 'None'}</span>
      </div>
    </div>

    <!-- Provenance & Evidence -->
    <div class="drawer-section">
      <div class="drawer-section-title">Provenance & Verification Evidence</div>
      <div class="drawer-row">
        <span class="drawer-label">Verification Status:</span>
        <span class="drawer-value"><span class="badge ${college.verification_status === 'verified' ? 'badge-verified' : college.verification_status === 'directory-listed' ? 'badge-directory' : college.verification_status === 'missing' ? 'badge-missing' : 'badge-unverified'}">${escapeHtml(statusNames[college.verification_status] || college.verification_status)}</span></span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Checked Date:</span>
        <span class="drawer-value">${escapeHtml(college.checked_on || 'Not checked')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Email Evidence URL:</span>
        <span class="drawer-value">${college.source_url ? `<a href="${escapeHtml(college.source_url)}" target="_blank" rel="noopener" style="color: var(--primary); font-size: 12px;">View Official Source ↗</a>` : 'No URL'}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Directory Source URL:</span>
        <span class="drawer-value">${college.institution_source ? `<a href="${escapeHtml(college.institution_source)}" target="_blank" rel="noopener" style="color: var(--primary); font-size: 12px;">View Directory ↗</a>` : 'None'}</span>
      </div>
    </div>

    <!-- Institution Profile -->
    <div class="drawer-section">
      <div class="drawer-section-title">Institution Profile</div>
      <div class="drawer-row">
        <span class="drawer-label">Area / District:</span>
        <span class="drawer-value">${escapeHtml(college.City)} (${escapeHtml(college.District || college.City)})</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Locality / Address:</span>
        <span class="drawer-value">${escapeHtml(college.Location || '')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Type / Disciplines:</span>
        <span class="drawer-value">${escapeHtml(college.Type || '')}</span>
      </div>
      <div class="drawer-row">
        <span class="drawer-label">Alternate Names:</span>
        <span class="drawer-value">${escapeHtml(college.Aliases || 'None')}</span>
      </div>
    </div>

    <!-- Add Note / Call Log Section -->
    <div class="drawer-section">
      <div class="drawer-section-title">📝 Log Call / Meeting / Note</div>
      <div style="display: flex; gap: 8px; margin-top: 8px;">
        <select id="drawerNoteType" class="form-control" style="font-size: 12px; height: 32px; width: 120px;">
          <option value="note">Internal Note</option>
          <option value="call">Phone Call</option>
          <option value="meeting">Meeting</option>
        </select>
        <input type="text" id="drawerNoteText" class="form-control" style="font-size: 12px; height: 32px;" placeholder="Add call notes, interview updates...">
        <button class="btn btn-outline btn-sm" onclick="submitNote(${college.id})">Add</button>
      </div>
    </div>

    <!-- Unified CRM Activity Timeline -->
    <div class="drawer-section">
      <div class="drawer-section-title">📜 Unified Activity & Outreach Timeline</div>
      <div id="drawerTimelineContent" class="timeline-list">
        <div style="text-align: center; color: var(--text-muted); font-size: 12px; padding: 12px;">Loading activity timeline...</div>
      </div>
    </div>

    <!-- Actions -->
    <div style="display: flex; gap: 10px; margin-top: 20px; flex-wrap: wrap;">
      <button class="btn ${selection.has(college.id) ? 'btn-danger' : 'btn-primary'}" onclick="toggleDrawerSelection(${college.id})" ${college.sendable ? '' : 'disabled'}>
        ${selection.has(college.id) ? 'Remove from Selection' : 'Select for Campaign'}
      </button>
      <button class="btn btn-outline" onclick="openEditCollegeDialog(${college.id})">Edit / Verify Record</button>
      <button class="btn btn-outline" onclick="closeDetailDrawer()">Close Drawer</button>
    </div>
  `;

  if (overlay) overlay.classList.add('active');
  drawer.classList.add('active');

  // Load detailed audit & outreach & activities
  try {
    const res = await fetch(`/api/college-detail?id=${collegeId}`);
    if (res.ok) {
      const data = await res.json();
      const timelineDiv = document.getElementById('drawerTimelineContent');
      if (timelineDiv) {
        if (data.activities && data.activities.length > 0) {
          const typeIcons = {
            'email_sent': '✉️ Email Sent',
            'email_failed': '❌ Email Failed',
            'reply': '💬 Reply Received',
            'call': '📞 Call Log',
            'meeting': '🤝 Meeting Log',
            'stage_change': '🔄 Stage Change',
            'follow_up': '⏰ Follow-up Scheduled',
            'note': '📝 Internal Note'
          };
          timelineDiv.innerHTML = data.activities.map(a => `
            <div class="timeline-item item-${escapeHtml(a.type || 'note')}">
              <div class="timeline-meta">
                <strong>${typeIcons[a.type] || '📝 Note'}</strong>
                <span>${escapeHtml(a.author || 'Team')} · <small>${escapeHtml(a.timestamp || '')}</small></span>
              </div>
              <div class="timeline-body">${escapeHtml(a.notes || '')}</div>
            </div>
          `).join('');
        } else {
          timelineDiv.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 8px 0;">No activities or outreach logged yet.</div>';
        }
      }
    }
  } catch (_) {}
}

async function submitStageUpdate(collegeId) {
  const stageEl = document.getElementById('drawerStageSelect');
  const notesEl = document.getElementById('drawerStageNotes');
  if (!stageEl) return;
  const stage = stageEl.value;
  const notes = notesEl ? notesEl.value.trim() : '';
  try {
    const res = await fetch('/api/college/stage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN },
      body: JSON.stringify({ college_id: collegeId, stage: stage, notes: notes })
    });
    const result = await res.json();
    if (!res.ok) {
      if (typeof alert !== 'undefined') alert(result.message || 'Failed to update stage');
      return;
    }
    const local = allColleges.find(c => c.id === collegeId);
    if (local) {
      local.recruitment_stage = stage;
      if (result.sendable !== undefined) local.sendable = result.sendable;
    }
    await loadOverviewMetrics();
    renderCollegesView();
    openDetailDrawer(collegeId);
  } catch (err) {
    if (typeof alert !== 'undefined') alert('Error updating recruitment stage: ' + err.message);
  }
}

function setQuickFollowUpDate(days) {
  const input = document.getElementById('drawerFollowUpDate');
  if (!input) return;
  const d = new Date();
  d.setDate(d.getDate() + Number(days));
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  input.value = `${yyyy}-${mm}-${dd}`;
}

async function submitFollowUp(collegeId) {
  const dateEl = document.getElementById('drawerFollowUpDate');
  const assignedEl = document.getElementById('drawerFollowUpAssigned');
  const notesEl = document.getElementById('drawerFollowUpNotes');
  if (!dateEl || !dateEl.value) {
    if (typeof alert !== 'undefined') alert('Please choose a follow-up date (YYYY-MM-DD).');
    return;
  }
  try {
    const res = await fetch('/api/college/follow-up', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN },
      body: JSON.stringify({
        college_id: collegeId,
        date: dateEl.value,
        assigned_to: assignedEl ? assignedEl.value.trim() : '',
        notes: notesEl ? notesEl.value.trim() : ''
      })
    });
    const result = await res.json();
    if (!res.ok) {
      if (typeof alert !== 'undefined') alert(result.message || 'Failed to save follow-up');
      return;
    }
    const local = allColleges.find(c => c.id === collegeId);
    if (local) {
      local.follow_up_date = dateEl.value;
      if (assignedEl) local.assigned_to = assignedEl.value.trim();
    }
    await loadOverviewMetrics();
    renderCollegesView();
    openDetailDrawer(collegeId);
  } catch (err) {
    if (typeof alert !== 'undefined') alert('Error scheduling follow-up: ' + err.message);
  }
}

async function submitReply(collegeId) {
  const textEl = document.getElementById('drawerReplyText');
  const stageEl = document.getElementById('drawerReplyStage');
  if (!textEl || !textEl.value.trim()) {
    if (typeof alert !== 'undefined') alert('Please enter reply notes or summary.');
    return;
  }
  const replyNotes = textEl.value.trim();
  const nextStage = stageEl ? stageEl.value : 'replied';
  try {
    const res = await fetch('/api/college/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN },
      body: JSON.stringify({
        college_id: collegeId,
        notes: replyNotes,
        stage: nextStage
      })
    });
    const result = await res.json();
    if (!res.ok) {
      if (typeof alert !== 'undefined') alert(result.message || 'Failed to record reply');
      return;
    }
    const local = allColleges.find(c => c.id === collegeId);
    if (local) {
      local.recruitment_stage = nextStage;
      local.last_reply_at = new Date().toISOString();
      local.last_reply_notes = replyNotes;
      if (result.sendable !== undefined) local.sendable = result.sendable;
    }
    await loadOverviewMetrics();
    renderCollegesView();
    openDetailDrawer(collegeId);
  } catch (err) {
    if (typeof alert !== 'undefined') alert('Error recording reply: ' + err.message);
  }
}

async function submitNote(collegeId) {
  const typeEl = document.getElementById('drawerNoteType');
  const textEl = document.getElementById('drawerNoteText');
  if (!textEl || !textEl.value.trim()) {
    if (typeof alert !== 'undefined') alert('Please enter activity or note text.');
    return;
  }
  try {
    const res = await fetch('/api/college/note', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN },
      body: JSON.stringify({
        college_id: collegeId,
        type: typeEl ? typeEl.value : 'note',
        content: textEl.value.trim()
      })
    });
    const result = await res.json();
    if (!res.ok) {
      if (typeof alert !== 'undefined') alert(result.message || 'Failed to add activity note');
      return;
    }
    openDetailDrawer(collegeId);
  } catch (err) {
    if (typeof alert !== 'undefined') alert('Error logging note: ' + err.message);
  }
}

function closeDetailDrawer() {
  const overlay = document.getElementById('drawerOverlay');
  const drawer = document.getElementById('collegeDrawer');
  if (overlay) overlay.classList.remove('active');
  if (drawer) drawer.classList.remove('active');
}

function toggleDrawerSelection(id) {
  const isSelected = selection.has(id);
  selection.set(id, !isSelected);
  renderCollegesView();
  openDetailDrawer(id);
}

// ==================== TEMPLATES TAB & LIBRARY ====================
let allTemplates = [];
let currentTemplateId = null;
let currentTemplateVersion = 1;
let currentTemplateIsDefault = false;
let editorMode = 'visual'; // 'visual' | 'html'
let previewFormat = 'html'; // 'html' | 'text'
let previewDevice = 'desktop'; // 'desktop' | 'mobile'
let previewCollegeId = null;
let previewDebounceTimer = null;

function triggerPreviewUpdate() {
  if (typeof setTimeout === 'undefined') return;
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(refreshLivePreview, 250);
}

function getEditorHtml() {
  if (editorMode === 'html') {
    const textarea = document.getElementById('htmlSourceArea');
    return textarea ? textarea.value : '';
  } else {
    const rich = document.getElementById('richEditorArea');
    return rich ? rich.innerHTML : '';
  }
}

function syncEditorToSource() {
  const rich = document.getElementById('richEditorArea');
  const src = document.getElementById('htmlSourceArea');
  if (rich && src) src.value = rich.innerHTML;
  triggerPreviewUpdate();
}

function syncSourceToEditor() {
  const rich = document.getElementById('richEditorArea');
  const src = document.getElementById('htmlSourceArea');
  if (rich && src) rich.innerHTML = src.value;
  triggerPreviewUpdate();
}

function setEditorMode(mode) {
  editorMode = mode;
  const rich = document.getElementById('richEditorArea');
  const src = document.getElementById('htmlSourceArea');
  const btnV = document.getElementById('btnModeVisual');
  const btnH = document.getElementById('btnModeHtml');
  const toolbar = document.getElementById('editorToolbar');

  if (mode === 'html') {
    if (rich && src) src.value = rich.innerHTML;
    if (rich) rich.style.display = 'none';
    if (src) src.style.display = 'block';
    if (toolbar) toolbar.style.opacity = '0.5';
    if (btnH) btnH.classList.add('active');
    if (btnV) btnV.classList.remove('active');
  } else {
    if (rich && src) rich.innerHTML = src.value;
    if (src) src.style.display = 'none';
    if (rich) rich.style.display = 'block';
    if (toolbar) toolbar.style.opacity = '1';
    if (btnV) btnV.classList.add('active');
    if (btnH) btnH.classList.remove('active');
  }
}

function execEditorCmd(cmd, val = null) {
  if (editorMode === 'html') return;
  const rich = document.getElementById('richEditorArea');
  if (rich) rich.focus();
  if (typeof document !== 'undefined' && document.execCommand) {
    document.execCommand(cmd, false, val);
  }
  syncEditorToSource();
}

function insertEditorLink() {
  const url = prompt('Enter destination link URL (https://...):', 'https://');
  if (url && url !== 'https://') {
    execEditorCmd('createLink', url);
  }
}

function insertEditorImage() {
  const url = prompt('Enter image URL or asset path (e.g. assets/ht_news_clipping_opt.jpg):', '');
  if (url) {
    execEditorCmd('insertImage', url);
  }
}

function insertToken(token) {
  if (editorMode === 'html') {
    const textarea = document.getElementById('htmlSourceArea');
    if (!textarea) return;
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || 0;
    const text = textarea.value || '';
    textarea.value = text.substring(0, start) + token + text.substring(end);
    textarea.selectionStart = textarea.selectionEnd = start + token.length;
    textarea.focus();
    syncSourceToEditor();
  } else {
    const rich = document.getElementById('richEditorArea');
    if (!rich) return;
    rich.focus();
    if (typeof window !== 'undefined' && window.getSelection) {
      const sel = window.getSelection();
      if (sel && sel.getRangeAt && sel.rangeCount) {
        const range = sel.getRangeAt(0);
        range.deleteContents();
        const textNode = document.createTextNode(token);
        range.insertNode(textNode);
        range.setStartAfter(textNode);
        range.setEndAfter(textNode);
        sel.removeAllRanges();
        sel.addRange(range);
      } else {
        rich.innerHTML += token;
      }
    } else {
      rich.innerHTML += token;
    }
    syncEditorToSource();
  }
}

function generatePlainTextFromHtml(e) {
  if (e && e.preventDefault) e.preventDefault();
  const html = getEditorHtml();
  if (!html) return;
  let txt = html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<\/h[1-6]>/gi, '\n\n')
    .replace(/<li>/gi, '• ')
    .replace(/<\/li>/gi, '\n')
    .replace(/<a[^>]+href="([^"]+)"[^>]*>(.*?)<\/a>/gi, '$2 ($1)')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\n\s*\n\s*\n/g, '\n\n')
    .trim();
  const textInput = document.getElementById('tplTextInput');
  if (textInput) textInput.value = txt;
  triggerPreviewUpdate();
}

function populateTemplateCollegeSelector() {
  const sel = document.getElementById('previewCollegeSelect');
  if (!sel) return;
  const sendable = allColleges.filter(c => c.sendable);
  sel.innerHTML = '<option value="">Select a college to test personalization...</option>' +
    sendable.map(c => `<option value="${c.id}">${escapeHtml(c.College_Name)} (${escapeHtml(c.City)})</option>`).join('');
}

function onPreviewCollegeChange(collegeId) {
  previewCollegeId = collegeId ? Number(collegeId) : null;
  refreshLivePreview();
}

function setPreviewDevice(device) {
  previewDevice = device;
  const frame = document.getElementById('previewIframe');
  const btnD = document.getElementById('btnViewDesktop');
  const btnM = document.getElementById('btnViewMobile');
  if (!frame) return;
  if (device === 'mobile') {
    frame.classList.add('mobile-view');
    if (btnM) btnM.classList.add('active');
    if (btnD) btnD.classList.remove('active');
  } else {
    frame.classList.remove('mobile-view');
    if (btnD) btnD.classList.add('active');
    if (btnM) btnM.classList.remove('active');
  }
}

function setPreviewFormat(format) {
  previewFormat = format;
  const frame = document.getElementById('previewIframe');
  const textBox = document.getElementById('plainTextPreviewBox');
  const btnH = document.getElementById('btnViewHtml');
  const btnT = document.getElementById('btnViewText');
  if (format === 'text') {
    if (frame) frame.style.display = 'none';
    if (textBox) textBox.style.display = 'block';
    if (btnT) btnT.classList.add('active');
    if (btnH) btnH.classList.remove('active');
  } else {
    if (frame) frame.style.display = 'block';
    if (textBox) textBox.style.display = 'none';
    if (btnH) btnH.classList.add('active');
    if (btnT) btnT.classList.remove('active');
  }
  refreshLivePreview();
}

async function refreshLivePreview() {
  if (typeof fetch === 'undefined') return;
  const subject = document.getElementById('tplSubjectInput')?.value || '';
  const html_body = getEditorHtml();
  const text_body = document.getElementById('tplTextInput')?.value || '';
  const college_id = previewCollegeId;

  try {
    const res = await fetch('/api/templates/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ subject, html_body, text_body, college_id })
    });
    if (!res.ok) return;
    const data = await res.json();
    const subPreview = document.getElementById('templateSubjectPreview');
    if (subPreview) subPreview.innerText = data.subject || '(No subject specified)';
    const textPreview = document.getElementById('plainTextPreviewBox');
    if (textPreview) textPreview.innerText = data.text || '';
    const iframe = document.getElementById('previewIframe');
    if (iframe) {
      iframe.srcdoc = data.html || '';
    }
  } catch (_) {}
}

async function loadTemplates() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/templates');
    if (!res.ok) return;
    allTemplates = await res.json();
    
    const badge = document.getElementById('templateCountBadge');
    if (badge) badge.innerText = allTemplates.length;

    const campSelect = document.getElementById('campaignTemplateSelect');
    if (campSelect) {
      const prevVal = campSelect.value;
      campSelect.innerHTML = allTemplates.map(t => 
        `<option value="${t.id}" ${t.is_default ? 'selected' : ''}>${escapeHtml(t.name)} (v${t.version})${t.is_default ? ' [Default]' : ''}</option>`
      ).join('');
      if (prevVal && allTemplates.some(t => t.id === Number(prevVal))) {
        campSelect.value = prevVal;
      }
    }

    renderTemplatesList();

    if (!currentTemplateId || !allTemplates.some(t => t.id === currentTemplateId)) {
      const defaultTpl = allTemplates.find(t => t.is_default) || allTemplates[0];
      if (defaultTpl) {
        await selectTemplate(defaultTpl.id);
      }
    }
  } catch (e) {
    addLog('Error loading templates: ' + e, 'warn');
  }
}

function renderTemplatesList() {
  const container = document.getElementById('templateListContainer');
  if (!container) return;
  if (!allTemplates || allTemplates.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 20px;">No templates found.</div>';
    return;
  }
  container.innerHTML = allTemplates.map(t => `
    <div class="template-item ${t.id === currentTemplateId ? 'active' : ''}" onclick="selectTemplate(${t.id})">
      <div class="template-item-header">
        <span class="template-item-title">${escapeHtml(t.name)}</span>
      </div>
      <div class="template-item-sub">${escapeHtml(t.subject)}</div>
      <div class="template-item-meta">
        ${t.is_default ? '<span class="badge-default">Default</span>' : ''}
        <span class="badge-version">v${t.version}</span>
        <span style="color: var(--text-muted); margin-left: auto;">${escapeHtml(String(t.updated_at || '').substring(0, 10))}</span>
      </div>
    </div>
  `).join('');
}

async function selectTemplate(templateId) {
  if (typeof fetch === 'undefined') return;
  currentTemplateId = Number(templateId);
  renderTemplatesList();
  try {
    const res = await fetch(`/api/templates/detail?id=${templateId}`);
    if (!res.ok) throw new Error('Template not found');
    const tpl = await res.json();
    
    currentTemplateVersion = tpl.version;
    currentTemplateIsDefault = Boolean(tpl.is_default);

    const titleEl = document.getElementById('editorTitleDisplay');
    if (titleEl) titleEl.innerText = tpl.name;
    const verBadge = document.getElementById('editorVersionBadge');
    if (verBadge) verBadge.innerText = `v${tpl.version}`;
    const defBadge = document.getElementById('editorDefaultBadge');
    if (defBadge) defBadge.style.display = tpl.is_default ? 'inline-block' : 'none';

    const nameInput = document.getElementById('tplNameInput');
    if (nameInput) nameInput.value = tpl.name;
    const defCheck = document.getElementById('tplIsDefaultCheckbox');
    if (defCheck) defCheck.checked = Boolean(tpl.is_default);
    const subjInput = document.getElementById('tplSubjectInput');
    if (subjInput) subjInput.value = tpl.subject;
    
    const rich = document.getElementById('richEditorArea');
    if (rich) rich.innerHTML = tpl.html_body;
    const src = document.getElementById('htmlSourceArea');
    if (src) src.value = tpl.html_body;
    const textInput = document.getElementById('tplTextInput');
    if (textInput) textInput.value = tpl.text_body;

    const btnArchive = document.getElementById('btnArchiveTemplate');
    if (btnArchive) {
      btnArchive.disabled = Boolean(tpl.is_default);
      btnArchive.title = tpl.is_default ? 'Default template cannot be archived.' : 'Archive this template';
    }

    refreshLivePreview();
  } catch (e) {
    addLog(`Error selecting template #${templateId}: ${e}`, 'warn');
  }
}

function createNewTemplate() {
  currentTemplateId = null;
  currentTemplateVersion = 1;
  currentTemplateIsDefault = false;

  renderTemplatesList();

  const titleEl = document.getElementById('editorTitleDisplay');
  if (titleEl) titleEl.innerText = 'New Template (Draft)';
  const verBadge = document.getElementById('editorVersionBadge');
  if (verBadge) verBadge.innerText = 'v1';
  const defBadge = document.getElementById('editorDefaultBadge');
  if (defBadge) defBadge.style.display = 'none';

  const nameInput = document.getElementById('tplNameInput');
  if (nameInput) nameInput.value = 'New Campus Outreach Template';
  const defCheck = document.getElementById('tplIsDefaultCheckbox');
  if (defCheck) defCheck.checked = false;
  const subjInput = document.getElementById('tplSubjectInput');
  if (subjInput) subjInput.value = 'Campus Placement & Industry Project Mentorship — {{College_Name}}';

  const starterHtml = '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 600px; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">\\n<h2 style="color: #07172c; margin-top: 0;">Campus Placement Partnership</h2>\\n<p>Dear {{Contact_Person}},</p>\\n<p>Greetings from <strong>Medantrik MedTech Pvt Ltd</strong> (IIT Kanpur Incubated)!</p>\\n<p>We are excited to connect with <strong>{{College_Name}}</strong> in {{City}} for structured campus recruitment and industry project mentorship.</p>\\n<p>Could we schedule a brief 15-minute video call with your placement committee this week?</p>\\n<br>\\n<p>Warm regards,<br><strong>University Relations Team</strong><br>Medantrik MedTech · Noida Sector 63A</p>\\n</div>';
  
  const rich = document.getElementById('richEditorArea');
  if (rich) rich.innerHTML = starterHtml;
  const src = document.getElementById('htmlSourceArea');
  if (src) src.value = starterHtml;
  const textInput = document.getElementById('tplTextInput');
  if (textInput) textInput.value = 'Dear {{Contact_Person}},\\n\\nGreetings from Medantrik MedTech (IIT Kanpur Incubated)!\\n\\nWe would love to connect with {{College_Name}} in {{City}} for campus placements.\\n\\nWarm regards,\\nMedantrik MedTech Team';

  const btnArchive = document.getElementById('btnArchiveTemplate');
  if (btnArchive) btnArchive.disabled = true;

  refreshLivePreview();
}

async function saveCurrentTemplate() {
  if (typeof fetch === 'undefined') return;
  const name = (document.getElementById('tplNameInput')?.value || '').trim();
  const subject = (document.getElementById('tplSubjectInput')?.value || '').trim();
  const html_body = getEditorHtml().trim();
  let text_body = (document.getElementById('tplTextInput')?.value || '').trim();
  const is_default = Boolean(document.getElementById('tplIsDefaultCheckbox')?.checked);

  if (!name) {
    alert('Please provide a Template Name.');
    document.getElementById('tplNameInput')?.focus();
    return;
  }
  if (!subject) {
    alert('Please provide a Subject Line.');
    document.getElementById('tplSubjectInput')?.focus();
    return;
  }
  if (!html_body) {
    alert('Please enter email body content.');
    return;
  }
  if (!text_body) {
    generatePlainTextFromHtml();
    text_body = (document.getElementById('tplTextInput')?.value || '').trim();
  }

  const payload = {
    id: currentTemplateId,
    name,
    subject,
    html_body,
    text_body,
    is_default,
    note: currentTemplateId ? 'Updated via template editor' : 'Initial template creation'
  };

  try {
    const res = await fetch('/api/templates/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify(payload)
    });
    const saved = await res.json();
    if (saved.id) {
      addLog(`✅ Template "${saved.name}" saved as version v${saved.version}.`, 'success');
      currentTemplateId = saved.id;
      await loadTemplates();
      await selectTemplate(saved.id);
    } else {
      addLog(`❌ Failed to save template: ${saved.message || 'Error'}`, 'error');
      alert(`Error saving template: ${saved.message || 'Unknown error'}`);
    }
  } catch (e) {
    addLog(`❌ Network error saving template: ${e}`, 'error');
    alert(`Network error saving template: ${e}`);
  }
}

async function duplicateCurrentTemplate() {
  if (!currentTemplateId) {
    alert('Please select or save a template first before duplicating.');
    return;
  }
  try {
    const res = await fetch('/api/templates/duplicate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id: currentTemplateId })
    });
    const copy = await res.json();
    if (copy.id) {
      addLog(`📋 Template duplicated as "${copy.name}".`, 'success');
      currentTemplateId = copy.id;
      await loadTemplates();
      await selectTemplate(copy.id);
    } else {
      alert(`Failed to duplicate: ${copy.message}`);
    }
  } catch (e) {
    alert(`Network error: ${e}`);
  }
}

async function archiveCurrentTemplate() {
  if (!currentTemplateId) return;
  if (currentTemplateIsDefault) {
    alert('Cannot archive the default template. Set another template as default first.');
    return;
  }
  if (!confirm('Are you sure you want to archive this template? It will be removed from your active library.')) {
    return;
  }
  try {
    const res = await fetch('/api/templates/archive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id: currentTemplateId })
    });
    const result = await res.json();
    if (result.status === 'ok') {
      addLog('📦 Template archived.', 'success');
      currentTemplateId = null;
      await loadTemplates();
    } else {
      alert(`Error: ${result.message}`);
    }
  } catch (e) {
    alert(`Network error: ${e}`);
  }
}

async function openTemplateHistoryModal() {
  if (!currentTemplateId) {
    alert('Save this template first to inspect version history.');
    return;
  }
  const dialog = document.getElementById('templateHistoryDialog');
  const container = document.getElementById('templateHistoryList');
  if (dialog && container) {
    container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 20px;">Loading revision history...</div>';
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', 'true');
    try {
      const res = await fetch(`/api/templates/history?id=${currentTemplateId}`);
      const history = await res.json();
      if (!Array.isArray(history) || history.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 14px;">No history records found for this template.</div>';
        return;
      }
      container.innerHTML = history.map(h => `
        <div class="history-item">
          <div class="history-details">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="badge-version">v${h.version}</span>
              <strong style="font-size: 13px; color: var(--navy);">${escapeHtml(h.name)}</strong>
              <span style="font-size: 11px; color: var(--text-muted);">${escapeHtml(h.created_at || '')}</span>
            </div>
            <div style="font-size: 12px; color: var(--text-muted);">
              <strong>Subject:</strong> ${escapeHtml(h.subject)}
            </div>
            ${h.note ? `<div style="font-size: 11.5px; color: #0369a1; font-style: italic;">Note: ${escapeHtml(h.note)}</div>` : ''}
          </div>
          <div>
            <button class="btn btn-outline btn-sm" onclick="restoreTemplateVersion(${h.id}, ${h.version})">Restore v${h.version}</button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = `<div style="color: var(--danger); font-size: 12px; padding: 14px;">Failed to load history: ${e}</div>`;
    }
  }
}

function closeTemplateHistoryDialog() {
  const dialog = document.getElementById('templateHistoryDialog');
  if (dialog) {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }
}

async function restoreTemplateVersion(historyId, versionNum) {
  if (!confirm(`Restore template to version v${versionNum}? This will create a new current revision with that content.`)) {
    return;
  }
  try {
    const res = await fetch('/api/templates/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ template_id: currentTemplateId, history_id: historyId })
    });
    const restored = await res.json();
    if (restored.id) {
      addLog(`🔄 Restored template to version v${restored.version} (from historical v${versionNum}).`, 'success');
      closeTemplateHistoryDialog();
      await loadTemplates();
      await selectTemplate(restored.id);
    } else {
      alert(`Error restoring version: ${restored.message}`);
    }
  } catch (e) {
    alert(`Network error: ${e}`);
  }
}

function onCampaignTemplateChange(templateId) {
  const t = allTemplates.find(x => x.id === Number(templateId));
  if (t) {
    const subjInput = document.getElementById('subjectLine');
    if (subjInput) subjInput.value = t.subject;
  }
}

function renderTemplatePreviewList() {
  populateTemplateCollegeSelector();
  refreshLivePreview();
}

// ==================== CAMPAIGNS TAB & SENDING ====================
function updateCampaignRecipientList() {
  const container = document.getElementById('campaignRecipientList');
  const checkedIds = selectedRecipientIds();

  if (container) {
    if (checkedIds.length === 0) {
      container.innerHTML = `
        <div style="color: var(--text-muted); font-size: 12.5px; padding: 12px;">
          No colleges selected yet. <a href="#" onclick="switchTab('colleges'); return false;" style="color: var(--primary); font-weight: 600;">Open Colleges workspace to select recipients →</a>
        </div>
      `;
    } else {
      container.innerHTML = checkedIds.map(id => {
        const c = allColleges.find(x => x.id === id);
        if (!c) return '';
        return `
          <div class="recipient-pill">
            <span><strong>${escapeHtml(c.College_Name)}</strong> &lt;${escapeHtml(c.TPO_Email)}&gt;</span>
            <button title="Remove recipient" onclick="removeRecipientFromCampaign(${c.id})">&times;</button>
          </div>
        `;
      }).join('');
    }
  }

  const campBadge = document.getElementById('campaignRecipientsBadge');
  if (campBadge) campBadge.innerText = `${checkedIds.length} Selected`;

  const btnSend = document.getElementById('btnSendAll');
  if (btnSend) btnSend.disabled = campaignRunning || checkedIds.length === 0;

  updateCampaignDurationEstimate();
}

function removeRecipientFromCampaign(id) {
  selection.set(id, false);
  renderCollegesView();
  updateCampaignRecipientList();
}

function createCampaignFromSelection() {
  switchTab('campaigns');
  updateCampaignRecipientList();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function selectedRecipientIds() {
  const seen = new Set();
  return selection.ids().filter(id => {
    const college = allColleges.find(c => c.id === id);
    if (!college || !college.sendable || seen.has(college.TPO_Email)) return false;
    seen.add(college.TPO_Email);
    return true;
  });
}

async function sendTestEmail() {
  const email = (document.getElementById('senderEmail')?.value || document.getElementById('settingsSenderEmail')?.value || '').trim();
  const password = (document.getElementById('senderPassword')?.value || document.getElementById('settingsAppPassword')?.value || '').trim();
  const subject = (document.getElementById('subjectLine')?.value || document.getElementById('settingsSubject')?.value || '').trim();

  if (!email || !password || !subject) {
    alert('Provide a valid sender email, Google App Password, and subject line.');
    return;
  }

  const btn = document.getElementById('btnTest');
  if (btn) {
    btn.disabled = true;
    btn.innerText = '⏳ Sending Test Email...';
  }
  addLog(`Initiating test email to ${email}...`);

  try {
    const chosenTemplateId = currentTemplateId || (document.getElementById('campaignTemplateSelect')?.value ? Number(document.getElementById('campaignTemplateSelect').value) : undefined);
    const res = await fetch('/api/send-test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        email,
        password,
        subject,
        template_id: chosenTemplateId
      })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      addLog(`✅ Test email sent successfully to ${email}! Check your inbox.`, 'success');
      alert('Success! Test email accepted for sending to ' + email + '. Check your inbox to review the preview.');
    } else {
      addLog(`❌ Test email failed: ${data.message}`, 'error');
      alert('Error sending email: ' + data.message);
    }
  } catch (e) {
    addLog(`❌ Network error: ${e}`, 'error');
    alert('Network error: ' + e);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = 'Send Test Email to Sender';
    }
  }
}

function updateCampaignDurationEstimate() {
  const el = document.getElementById('campaignDurationCallout');
  if (!el) return;
  const count = selectedRecipientIds().length;
  if (count === 0) {
    el.innerText = '⏱️ Select colleges in the Colleges tab to see estimated campaign duration.';
    return;
  }
  const interval = Math.max(1, Number(document.getElementById('campaignInterval')?.value || 30));
  const hourlyCap = Math.max(1, Number(document.getElementById('campaignHourlyCap')?.value || 40));

  const staggerSec = (count - 1) * interval;
  const capSec = hourlyCap > 0 ? Math.floor(((count - 1) / hourlyCap) * 3600) : 0;
  const totalSec = Math.max(staggerSec, capSec);

  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;

  let timeStr = '';
  if (hours > 0) timeStr += `${hours} hr${hours > 1 ? 's' : ''} `;
  if (minutes > 0 || hours > 0) timeStr += `${minutes} min${minutes !== 1 ? 's' : ''}`;
  if (hours === 0 && minutes === 0) timeStr = `${seconds} sec${seconds !== 1 ? 's' : ''}`;

  el.innerText = `⏱️ Estimated duration: ~${timeStr.trim()} across ${count} recipient${count > 1 ? 's' : ''} (${interval}s stagger, max ${hourlyCap}/hr).`;
}

let isSteppingQueue = false;

async function stepQueue(passwordOverride) {
  if (typeof fetch === 'undefined' || isSteppingQueue) return;
  const password = passwordOverride || window.activeSessionPassword || (typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('medantrik_session_pass') : '') || '';
  if (!password) return;
  isSteppingQueue = true;
  try {
    const res = await fetch('/api/queue/step', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ sender_password: password })
    });
    if (res.ok) {
      const data = await res.json();
      if (data && data.acted) {
        await loadCampaignHistory();
        await refreshQueueStatus();
      }
    }
  } catch (_) {
  } finally {
    isSteppingQueue = false;
  }
}

async function startPersistentCampaign() {
  if (typeof fetch === 'undefined') return;
  if (campaignRunning) return;

  const nameInput = document.getElementById('campaignName');
  const emailInput = document.getElementById('senderEmail');
  const passInput = document.getElementById('senderPassword');
  const subjInput = document.getElementById('subjectLine');
  const tplSelect = document.getElementById('campaignTemplateSelect');
  const intervalInput = document.getElementById('campaignInterval');
  const hourlyCapInput = document.getElementById('campaignHourlyCap');
  const dailyCapInput = document.getElementById('campaignDailyCap');
  const schedInput = document.getElementById('campaignScheduledAt');
  const hoursStartInput = document.getElementById('campaignHoursStart');
  const hoursEndInput = document.getElementById('campaignHoursEnd');
  const weekdaysInput = document.getElementById('campaignWorkingDaysOnly');

  const name = (nameInput?.value || '').trim();
  const email = (emailInput?.value || '').trim();
  const password = (passInput?.value || '').trim();
  const subject = (subjInput?.value || '').trim();
  const templateId = tplSelect?.value ? Number(tplSelect.value) : undefined;
  const interval = Number(intervalInput?.value || 30);
  const hourlyCap = Number(hourlyCapInput?.value || 40);
  const dailyCap = Number(dailyCapInput?.value || 300);
  const scheduledAt = schedInput?.value ? schedInput.value.replace('T', ' ') + ':00' : null;
  const hoursStart = (hoursStartInput?.value || '00:00').trim();
  const hoursEnd = (hoursEndInput?.value || '23:59').trim();
  const workingDaysOnly = weekdaysInput ? weekdaysInput.checked : true;

  const checkedIds = selectedRecipientIds();

  if (!name) {
    if (typeof alert !== 'undefined') alert('Enter a campaign name.');
    return;
  }
  if (!email || !email.includes('@')) {
    if (typeof alert !== 'undefined') alert('Enter a valid sender email address.');
    return;
  }
  if (!password) {
    if (typeof alert !== 'undefined') alert('Enter your Google App Password for this session.');
    return;
  }
  window.activeSessionPassword = password;
  try { sessionStorage.setItem('medantrik_session_pass', password); } catch (_) {}
  if (!subject) {
    if (typeof alert !== 'undefined') alert('Enter an email subject line.');
    return;
  }
  if (checkedIds.length === 0) {
    if (typeof alert !== 'undefined') alert('Select at least one verified college from the directory.');
    return;
  }

  const schedMsg = scheduledAt ? ` scheduled for ${scheduledAt}` : ' starting immediately';
  if (typeof confirm !== 'undefined') {
    const ok = confirm(`Launch persistent campaign "${name}" with ${checkedIds.length} verified recipients${schedMsg}?\n\nStagger: ${interval}s per message\nHourly limit: ${hourlyCap}/hr\nIST window: ${hoursStart}–${hoursEnd}`);
    if (!ok) return;
  }

  const btn = document.getElementById('btnSendAll');
  if (btn) {
    btn.disabled = true;
    btn.innerText = '⏳ Enqueuing Campaign...';
  }

  addLog(`Creating staggered campaign "${name}" with ${checkedIds.length} recipients...`, 'warn');

  try {
    const res = await fetch('/api/campaigns/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        name,
        sender_email: email,
        sender_password: password,
        subject,
        template_id: templateId,
        interval_seconds: interval,
        hourly_cap: hourlyCap,
        daily_cap: dailyCap,
        scheduled_at: scheduledAt,
        sending_hours_start: hoursStart,
        sending_hours_end: hoursEnd,
        working_days_only: workingDaysOnly,
        college_ids: checkedIds
      })
    });

    let data;
    try {
      data = await res.json();
    } catch (_) {
      const errText = await res.text().catch(() => '');
      throw new Error(errText || `Server returned HTTP ${res.status}`);
    }
    if (res.ok && data.id) {
      addLog(`🚀 Campaign "${data.name}" enqueued successfully! (${data.total_recipients} messages). Background worker is active.`, 'success');
      if (passInput) passInput.value = '';
      if (typeof alert !== 'undefined') {
        alert(`Campaign "${data.name}" created!\n\n${data.total_recipients} recipients enqueued.\nThe background worker will send each email individually according to your schedule.\n\nYou can close your browser or navigate anywhere safely.`);
      }
      await stepQueue(password);
      await loadCampaignHistory();
      await refreshQueueStatus();
    } else {
      addLog(`❌ Failed to create campaign: ${data.message || 'Unknown error'}`, 'error');
      if (typeof alert !== 'undefined') alert(`Error creating campaign: ${data.message || 'Unknown error'}`);
    }
  } catch (e) {
    addLog(`❌ Network error while creating campaign: ${e}`, 'error');
    if (typeof alert !== 'undefined') alert(`Network error: ${e}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = '🚀 LAUNCH PERSISTENT STAGGERED CAMPAIGN';
    }
  }
}

// Backward-compatible alias
async function sendCampaign() {
  await startPersistentCampaign();
}

async function openInGmailWeb() {
  const checkedIds = selectedRecipientIds();
  if (checkedIds.length === 0) {
    if (typeof alert !== 'undefined') alert('Please select at least one verified college from the directory.');
    return;
  }

  const selectedEmails = allColleges
    .filter(c => checkedIds.includes(c.id))
    .map(c => c.TPO_Email.trim())
    .filter(e => e && e.includes('@'));

  const bccString = selectedEmails.join(',');
  const subject = document.getElementById('subjectLine')?.value.trim() || '';

  addLog(`Preparing 1-Click Gmail composer with ${selectedEmails.length} recipients in BCC...`, 'warn');

  try {
    const res = await fetch('/api/text-template');
    const data = await res.json();
    const bodyText = data.text || '';

    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(bodyText);
    }

    const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&bcc=${encodeURIComponent(bccString)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(bodyText)}`;
    if (typeof window !== 'undefined') window.open(gmailUrl, '_blank');
    addLog(`✅ Gmail composer launched in new tab with ${selectedEmails.length} college emails in BCC!`, 'success');
    if (typeof alert !== 'undefined') {
      alert(`Success!\n\n1. Gmail opened in a new tab with all ${selectedEmails.length} college emails in BCC.\n2. The full personalized text has been copied to your clipboard.`);
    }
  } catch (e) {
    addLog(`Error launching Gmail: ${e}`, 'error');
    if (typeof alert !== 'undefined') alert('Error: ' + e);
  }
}

async function refreshQueueStatus() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/queue/status');
    if (!res.ok) return;
    const data = await res.json();

    const wEl = document.getElementById('kpiWorkerState');
    if (wEl) {
      wEl.innerText = data.worker_running ? 'Running' : 'Stopped';
      wEl.style.color = data.worker_running ? '#16a34a' : '#ef4444';
    }

    const qEl = document.getElementById('kpiQueuedCount');
    if (qEl) qEl.innerText = data.queued_messages ?? 0;

    const sEl = document.getElementById('kpiSendingCount');
    if (sEl) sEl.innerText = data.sending_messages ?? 0;

    const lhEl = document.getElementById('kpiLastHourCount');
    if (lhEl) lhEl.innerText = data.sent_last_hour ?? 0;

    const tdEl = document.getElementById('kpiTodayCount');
    if (tdEl) tdEl.innerText = data.sent_today ?? 0;

    const tEl = document.getElementById('kpiIstTime');
    if (tEl) tEl.innerText = data.current_time_ist ? data.current_time_ist.replace('T', ' ') : '--';

    const winEl = document.getElementById('kpiWindowStatus');
    if (winEl) {
      winEl.innerText = data.worker_running ? 'Window: Active' : 'Window: Inactive';
      winEl.className = data.worker_running ? 'badge badge-placement' : 'badge badge-warning';
    }
  } catch (_) {}
}

async function loadCampaignHistory() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/campaigns');
    if (!res.ok) return;
    const list = await res.json();

    const monitor = document.getElementById('campaignsMonitorContainer');
    if (monitor) {
      if (!list || list.length === 0) {
        monitor.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 24px;">No campaigns created yet. Select colleges and launch above!</div>';
      } else {
        monitor.innerHTML = list.map(c => {
          const statusClass = c.status || 'queued';
          const isPaused = c.status === 'paused';
          const isRunning = ['queued', 'sending', 'scheduled'].includes(c.status);
          const isTerminal = ['completed', 'cancelled'].includes(c.status);
          const needsReview = (c.needs_review_count || 0) > 0;
          const hasFailed = (c.failed_count || 0) > 0;

          return `
            <div class="campaign-card">
              <div class="campaign-card-header">
                <div>
                  <div class="campaign-card-title">${escapeHtml(c.name)}</div>
                  <div class="campaign-card-meta">
                    <strong>${escapeHtml(c.sender_email || '')}</strong> · ${escapeHtml(c.subject || '')}
                    ${c.scheduled_at ? ` · 🕒 Sched: ${escapeHtml(c.scheduled_at)}` : ''}
                    · Interval: ${c.interval_seconds || 30}s
                  </div>
                </div>
                <span class="badge-status ${statusClass}">${escapeHtml(c.status)}</span>
              </div>

              <!-- Progress bar -->
              <div class="queue-progress-bar-wrap">
                <div class="queue-progress-bar-fill" style="width: ${c.progress_pct || 0}%;"></div>
              </div>

              <!-- Summary count chips -->
              <div class="campaign-counts-row">
                <span class="count-chip accepted">✓ ${c.accepted_count || 0} Accepted</span>
                <span class="count-chip queued">⏳ ${c.queued_count || 0} Queued</span>
                ${(c.sending_count || 0) > 0 ? `<span class="count-chip" style="background:#dbeafe; color:#1d4ed8;">⚡ ${c.sending_count} Sending</span>` : ''}
                ${hasFailed ? `<span class="count-chip failed">✗ ${c.failed_count} Failed</span>` : ''}
                ${needsReview ? `<span class="count-chip review">⚠️ ${c.needs_review_count} Review</span>` : ''}
                <span style="font-size: 11px; color: var(--text-muted); align-self: center; margin-left: auto;">
                  ${c.progress_pct || 0}% complete (${c.total_recipients} total)
                </span>
              </div>

              <!-- Action buttons -->
              <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; align-items: center;">
                ${isRunning ? `<button class="btn btn-outline btn-sm" onclick="pauseCampaign(${c.id})">⏸️ Pause</button>` : ''}
                ${isPaused ? `<button class="btn btn-primary btn-sm" onclick="openResumeCampaignDialog(${c.id})">▶️ Resume</button>` : ''}
                ${!isTerminal ? `<button class="btn btn-outline btn-sm" style="color: var(--danger);" onclick="cancelCampaign(${c.id})">🛑 Cancel</button>` : ''}
                ${(hasFailed || needsReview) && !isRunning ? `<button class="btn btn-outline btn-sm" onclick="retryFailedCampaign(${c.id})">🔄 Retry Failed (${(c.failed_count || 0) + (c.needs_review_count || 0)})</button>` : ''}
                <button class="btn btn-outline btn-sm" onclick="exportCampaignCSV(${c.id})" title="Download campaign delivery CSV">📥 Export CSV</button>
                <button class="btn btn-outline btn-sm" style="margin-left: auto;" onclick="inspectCampaignQueue(${c.id})">🔍 Inspect Queue</button>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    const historyBody = document.getElementById('campaignHistoryBody');
    if (historyBody) {
      if (!list || list.length === 0) {
        historyBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">No recorded campaigns yet.</td></tr>';
      } else {
        historyBody.innerHTML = list.map(c => `
          <tr>
            <td><strong>${escapeHtml(c.name)}</strong><br><small style="color: var(--text-muted);">${escapeHtml(c.subject)}</small></td>
            <td><small>${escapeHtml(c.created_at || '')}</small></td>
            <td>${c.accepted_count || c.successful_count || 0} / ${c.total_recipients} sent</td>
            <td><span class="badge ${c.status === 'completed' ? 'badge-verified' : 'badge-warning'}">${escapeHtml(c.status)}</span></td>
          </tr>
        `).join('');
      }
    }
  } catch (_) {}
}

async function pauseCampaign(id) {
  if (typeof fetch === 'undefined') return;
  try {
    addLog(`Pausing campaign #${id}...`, 'warn');
    const res = await fetch('/api/campaigns/pause', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (res.ok) {
      addLog(`⏸️ Campaign #${id} paused.`, 'warn');
      await loadCampaignHistory();
      await refreshQueueStatus();
    } else {
      addLog(`❌ Failed to pause campaign: ${data.message}`, 'error');
      if (typeof alert !== 'undefined') alert(data.message);
    }
  } catch (e) {
    addLog(`❌ Error pausing campaign: ${e}`, 'error');
  }
}

let resumeTargetCampaignId = null;

function openResumeCampaignDialog(id) {
  resumeTargetCampaignId = id;
  const dialog = document.getElementById('resumePasswordDialog');
  const passInput = document.getElementById('resumeAppPassword');
  if (passInput) passInput.value = '';
  if (dialog) {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }
}

function closeResumePasswordDialog() {
  const dialog = document.getElementById('resumePasswordDialog');
  if (dialog) {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }
}

async function confirmResumeCampaign() {
  if (typeof fetch === 'undefined') return;
  const id = resumeTargetCampaignId;
  if (!id) return;

  const passInput = document.getElementById('resumeAppPassword');
  const password = (passInput?.value || '').trim();

  addLog(`Resuming campaign #${id}...`, 'warn');
  try {
    const res = await fetch('/api/campaigns/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id, sender_password: password || undefined })
    });
    const data = await res.json();
    if (res.ok) {
      if (password) {
        window.activeSessionPassword = password;
        try { sessionStorage.setItem('medantrik_session_pass', password); } catch (_) {}
      }
      addLog(`▶️ Campaign #${id} resumed successfully! Worker is active.`, 'success');
      closeResumePasswordDialog();
      await stepQueue(password);
      await loadCampaignHistory();
      await refreshQueueStatus();
    } else {
      addLog(`❌ Failed to resume campaign: ${data.message}`, 'error');
      if (typeof alert !== 'undefined') alert(`Cannot resume: ${data.message}`);
    }
  } catch (e) {
    addLog(`❌ Error resuming campaign: ${e}`, 'error');
  }
}

async function cancelCampaign(id) {
  if (typeof fetch === 'undefined') return;
  if (typeof confirm !== 'undefined') {
    if (!confirm('Are you sure you want to cancel this campaign? All remaining unsent messages will be cancelled.')) {
      return;
    }
  }
  try {
    addLog(`Cancelling campaign #${id}...`, 'warn');
    const res = await fetch('/api/campaigns/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (res.ok) {
      addLog(`🛑 Campaign #${id} cancelled.`, 'warn');
      await loadCampaignHistory();
      await refreshQueueStatus();
    } else {
      addLog(`❌ Failed to cancel campaign: ${data.message}`, 'error');
      if (typeof alert !== 'undefined') alert(data.message);
    }
  } catch (e) {
    addLog(`❌ Error cancelling campaign: ${e}`, 'error');
  }
}

async function retryFailedCampaign(id) {
  if (typeof fetch === 'undefined') return;
  try {
    addLog(`Retrying failed messages for campaign #${id}...`, 'warn');
    const res = await fetch('/api/campaigns/retry-failed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ id })
    });
    const data = await res.json();
    if (res.ok) {
      addLog(`🔄 Failed messages in campaign #${id} reset to queued!`, 'success');
      await loadCampaignHistory();
      await refreshQueueStatus();
    } else {
      addLog(`❌ Failed to retry campaign: ${data.message}`, 'error');
      if (typeof alert !== 'undefined') alert(data.message);
    }
  } catch (e) {
    addLog(`❌ Error retrying campaign: ${e}`, 'error');
  }
}

let currentInspectorCampaignId = null;

async function inspectCampaignQueue(campaignId) {
  currentInspectorCampaignId = campaignId;
  const dialog = document.getElementById('campaignQueueInspectorDialog');
  if (dialog) {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  }
  await refreshCurrentInspector();
}

function closeCampaignQueueInspector() {
  const dialog = document.getElementById('campaignQueueInspectorDialog');
  if (dialog) {
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }
  currentInspectorCampaignId = null;
}

async function refreshCurrentInspector() {
  if (!currentInspectorCampaignId || typeof fetch === 'undefined') return;
  const id = currentInspectorCampaignId;

  const titleEl = document.getElementById('inspectorCampaignTitle');
  const metaEl = document.getElementById('inspectorCampaignMeta');
  const chipsEl = document.getElementById('inspectorSummaryChips');
  const bodyEl = document.getElementById('inspectorQueueTableBody');

  try {
    const res = await fetch(`/api/campaigns/detail?id=${id}`);
    if (!res.ok) return;
    const camp = await res.json();

    if (titleEl) titleEl.innerText = `Campaign Queue: ${camp.name || 'Outreach'}`;
    if (metaEl) {
      metaEl.innerText = `Sender: ${camp.sender_email || ''} · Stagger: ${camp.interval_seconds || 30}s · Caps: ${camp.hourly_cap || 40}/hr, ${camp.daily_cap || 300}/day · Status: ${camp.status || ''}`;
    }

    if (chipsEl && camp.counts) {
      const c = camp.counts;
      chipsEl.innerHTML = `
        <span class="count-chip accepted">✓ ${c.accepted || 0} Accepted</span>
        <span class="count-chip queued">⏳ ${c.queued || 0} Queued</span>
        ${(c.sending || 0) > 0 ? `<span class="count-chip" style="background:#dbeafe; color:#1d4ed8;">⚡ ${c.sending} Sending</span>` : ''}
        ${(c.failed || 0) > 0 ? `<span class="count-chip failed">✗ ${c.failed} Failed</span>` : ''}
        ${(c.needs_review || 0) > 0 ? `<span class="count-chip review">⚠️ ${c.needs_review} Needs Review</span>` : ''}
        ${(c.cancelled || 0) > 0 ? `<span class="count-chip cancelled">🛑 ${c.cancelled} Cancelled</span>` : ''}
        <span style="font-size: 11.5px; color: var(--text-muted); align-self: center; margin-left: auto;">
          ${camp.progress_pct || 0}% done · ${c.total || 0} total recipients
        </span>
      `;
    }

    if (bodyEl) {
      const messages = camp.messages || [];
      if (messages.length === 0) {
        bodyEl.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 16px;">No messages queued for this campaign.</td></tr>';
      } else {
        bodyEl.innerHTML = messages.map(m => {
          let badgeClass = m.status;
          let statusLabel = m.status;
          if (m.status === 'accepted') {
            statusLabel = 'Accepted by provider';
          }

          return `
            <tr>
              <td>
                <strong>${escapeHtml(m.recipient_email)}</strong><br>
                <small style="color: var(--text-muted);">${escapeHtml(m.college_name || '')}</small>
              </td>
              <td><span class="badge ${m.contact_type === 'placement' ? 'badge-placement' : 'badge-general'}">${escapeHtml(m.contact_type || 'placement')}</span></td>
              <td><span class="badge-status ${badgeClass}">${escapeHtml(statusLabel)}</span></td>
              <td style="text-align: center;">${m.retry_count || 0}</td>
              <td><small>${escapeHtml(m.sent_at || m.next_attempt_at || '--')}</small></td>
              <td>
                <small style="color: ${m.status === 'failed' ? 'var(--danger)' : m.status === 'needs_review' ? '#c2410c' : 'var(--text-muted)'};">
                  ${escapeHtml(m.error_message || (m.status === 'accepted' ? 'Accepted by SMTP server' : '--'))}
                </small>
              </td>
            </tr>
          `;
        }).join('');
      }
    }
  } catch (e) {
    if (bodyEl) bodyEl.innerHTML = `<tr><td colspan="6" style="color: var(--danger); padding: 16px;">Error loading queue: ${e}</td></tr>`;
  }
}

// ==================== SETTINGS & DIAGNOSTICS ====================
function syncSettingsInputs() {
  const sEmail = document.getElementById('settingsSenderEmail')?.value || '';
  const sSubj = document.getElementById('settingsSubject')?.value || '';
  const sPass = document.getElementById('settingsAppPassword')?.value || '';

  const cEmail = document.getElementById('senderEmail');
  const cSubj = document.getElementById('subjectLine');
  const cPass = document.getElementById('senderPassword');

  if (cEmail && sEmail) cEmail.value = sEmail;
  if (cSubj && sSubj) cSubj.value = sSubj;
  if (cPass && sPass) cPass.value = sPass;

  alert('Credentials synced to dispatcher successfully.');
}

async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    const appEl = document.getElementById('diagAppStatus');
    const dbEl = document.getElementById('diagDbStatus');
    const tplEl = document.getElementById('diagTplStatus');
    const cfgEl = document.getElementById('diagCfgStatus');

    if (appEl) {
      appEl.innerText = data.status === 'ok' ? 'Operational' : 'Degraded';
      appEl.style.color = data.status === 'ok' ? '#16a34a' : '#ef4444';
    }
    if (dbEl) dbEl.innerText = data.checks?.directory === 'ok' ? 'Connected' : 'Unavailable';
    if (tplEl) tplEl.innerText = data.checks?.templates === 'ok' ? 'Loaded' : 'Unavailable';
    if (cfgEl) cfgEl.innerText = data.checks?.settings === 'ok' ? 'Loaded' : 'Unavailable';
  } catch (e) {
    console.error('Health check failed:', e);
  }
}

// ==================== DIALOGS & MODALS ====================
function openAddCollegeDialog() {
  openEditorDialog(null);
}

function openEditCollegeDialog(collegeId) {
  openEditorDialog(collegeId);
}

function openEditorDialog(id) {
  editingCollege = id ? allColleges.find(c => c.id === id) : null;
  const dialog = document.getElementById('editor');
  const title = document.getElementById('editorTitle');
  const fields = document.getElementById('fields');
  if (!dialog || !fields) return;

  if (title) title.innerText = editingCollege ? 'Review / Edit Institution' : 'Add New Institution';

  fields.innerHTML = Object.entries(fieldLabels).map(([key, label]) => {
    const value = editingCollege?.[key] || '';
    let control = '';
    if (key === 'category') {
      const catList = availableCategories.map(c => c.name);
      if (!catList.includes('Colleges')) catList.unshift('Colleges');
      if (!catList.includes('Gyms')) catList.push('Gyms');
      if (!catList.includes('Offices')) catList.push('Offices');
      if (!catList.includes('Households')) catList.push('Households');
      const curCat = value || (activeCategory !== 'all' ? activeCategory : 'Colleges');
      control = `<select id="field_${key}" class="form-control">${catList.map(o => `<option value="${o}" ${o.toLowerCase() === curCat.toLowerCase() ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    } else if (key === 'City') {
      const opts = ['Delhi', 'Noida', 'Greater Noida', 'Ghaziabad', 'Gurugram'];
      control = `<select id="field_${key}" class="form-control">${opts.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    } else if (key === 'contact_type') {
      const opts = ['placement', 'general', 'unknown'];
      control = `<select id="field_${key}" class="form-control">${opts.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
    } else if (key === 'verification_status') {
      const opts = ['verified', 'directory-listed', 'unverified', 'missing'];
      control = `<select id="field_${key}" class="form-control">${opts.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${statusNames[o] || o}</option>`).join('')}</select>`;
    } else {
      const inputType = key === 'checked_on' ? 'date' : key === 'TPO_Email' ? 'email' : ['Website', 'source_url', 'institution_source'].includes(key) ? 'url' : 'text';
      control = `<input id="field_${key}" class="form-control" value="${escapeHtml(value)}" type="${inputType}" ${key === 'College_Name' ? 'required' : ''}>`;
    }
    return `<label style="display:flex; flex-direction:column; margin-bottom:8px; font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">${label} ${control}</label>`;
  }).join('');

  const blocked = document.getElementById('blocked');
  if (blocked) blocked.checked = !!editingCollege?.do_not_contact;
  const confirmed = document.getElementById('confirmed');
  if (confirmed) confirmed.checked = false;
  const errEl = document.getElementById('formError');
  if (errEl) errEl.innerText = '';
  const hist = document.getElementById('historyText');
  if (hist) { hist.style.display = 'none'; hist.innerText = ''; }

  dialog.showModal();
}

function closeEditorDialog() {
  const dialog = document.getElementById('editor');
  if (dialog) dialog.close();
}

async function viewRecordHistory() {
  if (!editingCollege) return;
  const histEl = document.getElementById('historyText');
  if (!histEl) return;
  try {
    const res = await fetch(`/api/history?id=${editingCollege.id}`);
    const data = await res.json();
    histEl.innerText = JSON.stringify(data, null, 2);
    histEl.style.display = 'block';
  } catch (e) {
    histEl.innerText = 'Error loading history: ' + e;
    histEl.style.display = 'block';
  }
}

// Form submit
if (typeof document !== 'undefined') {
  const cForm = document.getElementById('collegeForm');
  if (cForm) {
    cForm.onsubmit = async (e) => {
      e.preventDefault();
      const errEl = document.getElementById('formError');
      try {
        const record = Object.fromEntries(Object.keys(fieldLabels).map(k => [k, document.getElementById('field_' + k)?.value]));
        record.do_not_contact = document.getElementById('blocked')?.checked;
        const confirmed = document.getElementById('confirmed')?.checked;

        const res = await fetch('/api/directory/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
          body: JSON.stringify({
            record,
            id: editingCollege?.id,
            version: editingCollege?.version,
            verification_confirmed: confirmed
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.message || 'Save failed');
        closeEditorDialog();
        await loadColleges();
        alert('Institution saved successfully!');
      } catch (err) {
        if (errEl) errEl.innerText = err.message;
      }
    };
  }
}

// Import Dialog
function openImportDialog() {
  const d = document.getElementById('importDialog');
  if (d) d.showModal();
}
function closeImportDialog() {
  const d = document.getElementById('importDialog');
  if (d) d.close();
}

async function previewImportAction() {
  const text = document.getElementById('importText')?.value || '';
  const sumEl = document.getElementById('importSummary');
  const rowsEl = document.getElementById('importRows');
  const commitBtn = document.getElementById('commitImportBtn');

  try {
    const res = await fetch('/api/import/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);

    currentImportToken = data.token;
    if (sumEl) sumEl.innerText = `${data.add} records to add · ${data.duplicates} exact duplicates skipped · ${data.errors} errors`;
    if (commitBtn) commitBtn.disabled = data.errors > 0 || data.add === 0;

    if (rowsEl) {
      rowsEl.innerHTML = '<table><thead><tr><th>Row</th><th>Action</th><th>Institution / Message</th></tr></thead><tbody>' +
        data.rows.map(r => `<tr><td>${r.row}</td><td>${escapeHtml(r.action)}</td><td>${escapeHtml(r.record?.College_Name || r.message)}</td></tr>`).join('') +
        '</tbody></table>';
    }
  } catch (err) {
    if (sumEl) sumEl.innerText = 'Preview Error: ' + err.message;
  }
}

async function commitImportAction() {
  const sumEl = document.getElementById('importSummary');
  try {
    const res = await fetch('/api/import/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ token: currentImportToken })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);
    if (sumEl) sumEl.innerText = `Success: Saved ${data.added} institutions, skipped ${data.skipped}.`;
    await loadColleges();
  } catch (err) {
    if (sumEl) sumEl.innerText = 'Commit Error: ' + err.message;
  }
}

// Duplicate Dialog
async function openDuplicateDialog() {
  const dialog = document.getElementById('duplicateDialog');
  const rows = document.getElementById('duplicateRows');
  if (!dialog || !rows) return;

  dialog.showModal();
  rows.innerHTML = '<p style="color:var(--text-muted);">Scanning directory for candidate duplicate pairs...</p>';

  try {
    const res = await fetch('/api/duplicates');
    const pairs = await res.json();
    if (pairs.length === 0) {
      rows.innerHTML = '<p style="padding:16px; color:#16a34a;">No duplicate candidate pairs found. Inventory is cleanly separated.</p>';
      return;
    }

    rows.innerHTML = pairs.map(p => {
      const a = allColleges.find(r => r.id === p.first);
      const b = allColleges.find(r => r.id === p.second);
      if (!a || !b) return '';
      return `
        <div style="background:#f8fafc; border:1px solid var(--border); padding:12px; border-radius:6px; margin-bottom:10px;">
          <div style="font-size:13px; font-weight:700; color:var(--navy);">${escapeHtml(a.College_Name)} (#${a.id}) ↔ ${escapeHtml(b.College_Name)} (#${b.id})</div>
          <div style="font-size:12px; color:var(--text-muted); margin:4px 0;">Reason: ${escapeHtml(p.reason)} | Shared Email: ${escapeHtml(a.TPO_Email || 'None')}</div>
          <div style="display:flex; gap:8px; margin-top:8px;">
            <button class="btn btn-outline btn-sm" onclick="closeDuplicateDialog(); openDetailDrawer(${a.id})">Inspect #${a.id}</button>
            <button class="btn btn-outline btn-sm" onclick="closeDuplicateDialog(); openDetailDrawer(${b.id})">Inspect #${b.id}</button>
            <button class="btn btn-danger btn-sm" onclick="mergeDuplicatePair(${a.id}, ${b.id})">Merge #${a.id} into #${b.id}</button>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    rows.innerHTML = '<p style="color:var(--danger);">Error scanning duplicates: ' + e + '</p>';
  }
}

async function mergeDuplicatePair(sourceId, targetId) {
  const a = allColleges.find(r => r.id === sourceId);
  const b = allColleges.find(r => r.id === targetId);
  if (!a || !b) return;

  if (!confirm(`Are you sure you want to merge "${a.College_Name}" into "${b.College_Name}"?\nThe target record keeps its contact; source details are archived in audit history.`)) {
    return;
  }

  try {
    const res = await fetch('/api/directory/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        source_id: a.id,
        target_id: b.id,
        source_version: a.version,
        target_version: b.version,
        confirmed: true
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message);
    alert('Records merged successfully!');
    closeDuplicateDialog();
    await loadColleges();
  } catch (err) {
    alert('Merge failed: ' + err.message);
  }
}

function closeDuplicateDialog() {
  const d = document.getElementById('duplicateDialog');
  if (d) d.close();
}

// Recipient Review Modal
function openRecipientReviewModal() {
  const modal = document.getElementById('recipientReviewModal');
  const tbody = document.getElementById('recipientReviewBody');
  if (!modal || !tbody) return;

  const checkedIds = selectedRecipientIds();
  if (checkedIds.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px;">No colleges selected.</td></tr>';
  } else {
    tbody.innerHTML = checkedIds.map(id => {
      const c = allColleges.find(x => x.id === id);
      if (!c) return '';
      return `
        <tr>
          <td><strong>${escapeHtml(c.College_Name)}</strong></td>
          <td><span class="tag-loc">${escapeHtml(c.City)}</span></td>
          <td style="color:#0284c7;">${escapeHtml(c.TPO_Email)}</td>
          <td>${escapeHtml(c.Contact_Person || 'Placement Cell')}</td>
          <td><button class="btn btn-outline btn-sm" onclick="removeRecipientFromCampaign(${c.id}); openRecipientReviewModal();">Remove</button></td>
        </tr>
      `;
    }).join('');
  }
  modal.showModal();
}

function closeRecipientReviewModal() {
  const modal = document.getElementById('recipientReviewModal');
  if (modal) modal.close();
}

function exportDirectoryResults() {
  const blob = new Blob([JSON.stringify(filteredColleges, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `college-directory-${new Date().toISOString().split('T')[0]}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// Auto-polling for active campaign queue monitor
if (typeof window !== 'undefined' && typeof setInterval !== 'undefined') {
  setInterval(async () => {
    if (typeof activeTab !== 'undefined' && activeTab === 'campaigns') {
      await stepQueue();
      await loadCampaignHistory();
      await refreshQueueStatus();
    }
    if (typeof currentInspectorCampaignId !== 'undefined' && currentInspectorCampaignId) {
      await stepQueue();
      refreshCurrentInspector();
    }
  }, 5000);
}

// ==================== CATEGORIES SYSTEM ====================
async function loadCategories() {
  if (typeof fetch === 'undefined') return;
  try {
    const res = await fetch('/api/categories');
    if (res.ok) {
      availableCategories = await res.json();
      renderCategoryTabs();
    }
  } catch (e) {
    console.warn('Could not load categories:', e);
  }
}

function renderCategoryTabs() {
  const container = document.getElementById('categoryTabsContainer');
  if (!container) return;

  const totalCount = allColleges.length;
  const icons = {
    'colleges': '🎓',
    'gyms': '🏋️',
    'offices': '🏢',
    'households': '🏠'
  };

  let html = '';
  availableCategories.forEach(cat => {
    const name = cat.name;
    const key = name.toLowerCase();
    const icon = icons[key] || '📁';
    const count = allColleges.filter(c => (c.category || 'Colleges').toLowerCase() === key).length;
    const isActive = activeCategory.toLowerCase() === key;
    html += `
      <button type="button" class="category-pill ${isActive ? 'active' : ''}" onclick="selectCategory('${escapeHtml(name)}')">
        <span>${icon}</span> ${escapeHtml(name)} <span class="pill-count">${count}</span>
      </button>
    `;
  });

  const isAllActive = activeCategory.toLowerCase() === 'all';
  html += `
    <button type="button" class="category-pill ${isAllActive ? 'active' : ''}" onclick="selectCategory('all')">
      <span>🌐</span> All <span class="pill-count">${totalCount}</span>
    </button>
  `;

  container.innerHTML = html;
}

function selectCategory(catName) {
  activeCategory = catName;
  renderCategoryTabs();
  filterColleges();
}

function openAddCategoryModal() {
  const modal = document.getElementById('addCategoryModal');
  const input = document.getElementById('newCategoryName');
  const desc = document.getElementById('newCategoryDesc');
  const err = document.getElementById('addCategoryError');
  if (input) input.value = '';
  if (desc) desc.value = '';
  if (err) { err.style.display = 'none'; err.innerText = ''; }
  if (modal) modal.showModal();
}

function closeAddCategoryModal() {
  const modal = document.getElementById('addCategoryModal');
  if (modal) modal.close();
}

async function submitNewCategory() {
  const input = document.getElementById('newCategoryName');
  const desc = document.getElementById('newCategoryDesc');
  const err = document.getElementById('addCategoryError');
  const name = (input?.value || '').trim();
  const description = (desc?.value || '').trim();
  if (!name) {
    if (err) { err.innerText = 'Enter a category name.'; err.style.display = 'block'; }
    return;
  }
  try {
    const res = await fetch('/api/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ name, description })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Failed to create category');
    closeAddCategoryModal();
    activeCategory = name;
    await loadCategories();
    filterColleges();
    addLog(`Created new category "${name}". A separate tab has been automatically added to your Google Sheet / Excel workbook.`, 'success');
  } catch (e) {
    if (err) { err.innerText = e.message; err.style.display = 'block'; }
  }
}

// ==================== DIRECT IMMEDIATE EMAIL SEND ====================
function openDirectSendModal() {
  const modal = document.getElementById('directSendModal');
  if (!modal) return;

  const tplSelect = document.getElementById('directTemplateSelect');
  if (tplSelect && typeof allTemplates !== 'undefined' && allTemplates.length > 0) {
    tplSelect.innerHTML = '<option value="">-- Custom Message (No Template) --</option>' +
      allTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.subject || 'No Subject')})</option>`).join('');
  }

  const directSenderEmail = document.getElementById('directSenderEmail');
  const defaultSender = document.getElementById('senderEmail')?.value || '';
  if (directSenderEmail && !directSenderEmail.value) {
    directSenderEmail.value = defaultSender;
  }

  const statusEl = document.getElementById('directSendStatus');
  if (statusEl) statusEl.style.display = 'none';

  modal.showModal();
}

function closeDirectSendModal() {
  const modal = document.getElementById('directSendModal');
  if (modal) modal.close();
}

function onDirectTemplateChange(templateId) {
  if (!templateId) return;
  const tpl = (typeof allTemplates !== 'undefined') ? allTemplates.find(t => String(t.id) === String(templateId)) : null;
  if (!tpl) return;
  const subjInput = document.getElementById('directSubject');
  const bodyInput = document.getElementById('directMessageBody');
  if (subjInput && tpl.subject) subjInput.value = tpl.subject;
  if (bodyInput) bodyInput.value = tpl.html_body || tpl.text_body || '';
}

async function executeDirectSend() {
  const toEmailEl = document.getElementById('directRecipientEmail');
  const toNameEl = document.getElementById('directRecipientName');
  const tplSelect = document.getElementById('directTemplateSelect');
  const subjEl = document.getElementById('directSubject');
  const bodyEl = document.getElementById('directMessageBody');
  const senderEl = document.getElementById('directSenderEmail');
  const passEl = document.getElementById('directSenderPassword');
  const statusEl = document.getElementById('directSendStatus');
  const btn = document.getElementById('btnDirectSend');

  const recipient_email = (toEmailEl?.value || '').trim();
  const recipient_name = (toNameEl?.value || '').trim();
  const subject = (subjEl?.value || '').trim();
  const message_body = (bodyEl?.value || '').trim();
  const sender_email = (senderEl?.value || '').trim();
  const sender_password = (passEl?.value || '').trim();
  const template_id = tplSelect?.value || undefined;

  if (!recipient_email) {
    alert('Enter a valid recipient email address.');
    toEmailEl?.focus();
    return;
  }
  if (!subject) {
    alert('Enter an email subject.');
    subjEl?.focus();
    return;
  }
  if (!message_body) {
    alert('Enter your email message content.');
    bodyEl?.focus();
    return;
  }
  if (!sender_email) {
    alert('Enter your sender email.');
    senderEl?.focus();
    return;
  }
  if (sender_password) {
    window.activeSessionPassword = sender_password;
    try { sessionStorage.setItem('medantrik_session_pass', sender_password); } catch (_) {}
  }

  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.style.background = '#eff6ff';
    statusEl.style.color = '#1e40af';
    statusEl.style.border = '1px solid #bfdbfe';
    statusEl.innerHTML = 'Connecting to mail server and dispatching email... ⏳';
  }
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/send-direct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        sender_email,
        sender_password,
        recipient_email,
        recipient_name,
        subject,
        html_body: message_body,
        text_body: message_body.replace(/<[^>]+>/g, ' '),
        template_id: template_id ? Number(template_id) : undefined
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Dispatch failed');

    if (statusEl) {
      statusEl.style.background = '#f0fdf4';
      statusEl.style.color = '#166534';
      statusEl.style.border = '1px solid #bbf7d0';
      statusEl.innerHTML = `✅ <strong>Success!</strong> ${escapeHtml(data.message || 'Email sent successfully.')}`;
    }
    addLog(`Direct email sent to ${recipient_email} (${subject}).`, 'success');
    if (btn) btn.disabled = false;
    setTimeout(() => {
      closeDirectSendModal();
      loadOverview();
    }, 2000);
  } catch (err) {
    if (statusEl) {
      statusEl.style.background = '#fef2f2';
      statusEl.style.color = '#991b1b';
      statusEl.style.border = '1px solid #fecaca';
      statusEl.innerHTML = `❌ <strong>Failed:</strong> ${escapeHtml(err.message)}`;
    }
    addLog(`Direct send failure to ${recipient_email}: ${err.message}`, 'error');
    if (btn) btn.disabled = false;
  }
}

// ==================== AUTOSTART ====================
loadColleges();
