/* ── API ── */
const token = () => localStorage.getItem('session_token') || '';
const hdrs  = () => ({ 'Content-Type': 'application/json', 'X-Session': token() });
const api   = (path, opts = {}) => fetch(path, { credentials: 'include', headers: hdrs(), ...opts });

/* ── Toast ── */
function showToast(msg) {
  let t = document.getElementById('toast');
  if (!t) { t = Object.assign(document.createElement('div'), { id: 'toast' }); document.body.appendChild(t); }
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.classList.remove('show'), 2400);
}

/* ── Escape HTML ── */
function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Format number ── */
function fmt(n) { return Number(n || 0).toLocaleString('ru'); }

/* ── Auth guard ── */
async function requireAuth(role = null) {
  try {
    const r = await api('/api/auth/me');
    if (!r.ok) { window.location.href = '/login'; return null; }
    const d = await r.json();
    if (role && d.role !== role) {
      window.location.href = d.role === 'admin' ? '/dashboard' : '/chat';
      return null;
    }
    return d;
  } catch { window.location.href = '/login'; return null; }
}

/* ── Logout ── */
async function logout() {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  localStorage.clear();
  window.location.href = '/login';
}

/* ── Nav ── */
function initNav() {
  document.querySelectorAll('.nav-item[data-screen]').forEach(el => {
    el.addEventListener('click', () => goScreen(el.dataset.screen));
  });
  const menuBtn = document.getElementById('menu-btn');
  const sidebar  = document.getElementById('sidebar');
  const overlay  = document.getElementById('overlay');
  if (menuBtn) menuBtn.addEventListener('click', () => { sidebar.classList.toggle('open'); overlay.classList.toggle('show'); });
  if (overlay)  overlay.addEventListener('click', () => { sidebar.classList.remove('open'); overlay.classList.remove('show'); });
}

function goScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('screen-' + name)?.classList.add('active');
  const nav = document.querySelector(`.nav-item[data-screen="${name}"]`);
  nav?.classList.add('active');
  const el = document.getElementById('topbar-title');
  if (el && nav?.dataset.title) el.textContent = nav.dataset.title;
  sidebar?.classList.remove('open');
  overlay?.classList.remove('show');
}

/* ── Health check ── */
async function checkHealth() {
  const pill = document.getElementById('status-pill');
  const txt  = document.getElementById('status-text');
  const dot  = document.getElementById('status-dot');
  if (!pill) return;
  try {
    const r = await api('/api/health');
    if (r.ok) { pill.className = 'status-pill'; txt.textContent = 'Модель активна'; dot.style.background = '#3B6D11'; }
    else throw 0;
  } catch { pill.className = 'status-pill offline'; txt.textContent = 'Недоступна'; }
}

/* ── Charts ── */
const PAL  = ['#378ADD','#0C447C','#85B7EB','#B5D4F4','#D0E6F8'];
const CIRC = 2 * Math.PI * 40;

function renderBars(id, depts) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!depts?.length) { el.innerHTML = '<div class="text-muted text-sm">Нет данных</div>'; return; }
  const mx = depts[0].count;
  el.innerHTML = depts.slice(0, 7).map((d, i) =>
    `<div class="bar-row">
      <div class="bar-name">${esc(d.name)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(d.count/mx*100).toFixed(0)}%;background:${PAL[i]||PAL[4]}"></div></div>
      <div class="bar-count">${d.count}</div>
    </div>`
  ).join('');
}

function renderDonut(svgId, legId, total, depts) {
  const svg = document.getElementById(svgId);
  const leg = document.getElementById(legId);
  const tot = document.getElementById(svgId + '-total');
  if (!svg) return;
  svg.querySelectorAll('.arc').forEach(a => a.remove());
  if (tot) tot.textContent = fmt(total);
  if (!total || !depts?.length) { if (leg) leg.innerHTML = '<div class="text-muted text-sm">Нет данных</div>'; return; }
  let off = 0;
  depts.slice(0, 4).forEach((d, i) => {
    const len = (d.count / total) * CIRC;
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.classList.add('arc');
    c.setAttribute('cx','53'); c.setAttribute('cy','53'); c.setAttribute('r','40');
    c.setAttribute('fill','none'); c.setAttribute('stroke', PAL[i]);
    c.setAttribute('stroke-width','15');
    c.setAttribute('stroke-dasharray',`${len} ${CIRC-len}`);
    c.setAttribute('stroke-dashoffset', String(-off));
    c.setAttribute('transform','rotate(-90 53 53)');
    off += len; svg.appendChild(c);
  });
  if (leg) leg.innerHTML = depts.slice(0,4).map((d,i) =>
    `<div class="legend-row"><div class="legend-dot" style="background:${PAL[i]}"></div><span>${esc(d.name)}</span><span class="legend-val">${d.count}</span></div>`
  ).join('');
}

/* ── CSV ── */
function exportCSV(data, filename) {
  if (!data.length) { showToast('Нет данных'); return; }
  const keys = Object.keys(data[0]);
  const rows = [keys.join(','), ...data.map(r => keys.map(k => `"${String(r[k]||'').replace(/"/g,'""')}"`).join(','))];
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([rows.join('\n')], {type:'text/csv'}));
  a.download = filename; a.click();
}
