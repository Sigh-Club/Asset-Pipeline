/* IoA Asset Gallery — JavaScript
 * Uses template literals (backticks) to avoid Python escaping issues.
 * All HTML generation is done client-side via DOM API and template strings.
 */

/* global state */
let frameData = {};

/* ─── API helpers ─────────────────────────────────────────── */

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json();
}

/* ─── Modal ───────────────────────────────────────────────── */

function openModal(src, infoHtml, frameThumbs) {
  const m = document.getElementById('modal');
  document.getElementById('modal-img').src = src;
  document.getElementById('modal-info').innerHTML = infoHtml || '';
  const fg = document.getElementById('modal-frames');
  if (frameThumbs && frameThumbs.length) {
    fg.innerHTML = `<b>Frames (${frameThumbs.length}):</b><br>` +
      frameThumbs.map((t, i) =>
        `<img src="${t}" onclick="event.stopPropagation();openModal(this.src)" title="Frame ${i + 1}">`
      ).join('');
    fg.style.display = '';
  } else {
    fg.style.display = 'none';
  }
  m.classList.add('open');
}

function closeModal(e) {
  if (!e || e.target === e.currentTarget) {
    document.getElementById('modal').classList.remove('open');
  }
}
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeModal();
});

/* ─── Sanitize user-controlled values for HTML ────────────── */
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ─── Folder listing ──────────────────────────────────────── */

async function loadFolders() {
  const el = document.getElementById('folder-list');
  if (!el) return;
  try {
    const data = await api('/api/folders');
    if (!data.folders || data.folders.length === 0) {
      el.innerHTML =
        '<div class="empty-state"><h3>No releases found</h3>' +
        '<p>Run <code>pipeline release</code> to create a snapshot, or use the pipeline CLI to pack assets.</p></div>';
      return;
    }
    el.innerHTML = data.folders.map(f => {
      const badge = f.type === 'release'
        ? '<span class="badge badge-release">release</span>'
        : f.type === 'version'
          ? '<span class="badge badge-version">version</span>'
          : '<span class="badge badge-current">current</span>';
      const cls = 'folder-card' + (f.is_latest ? ' latest' : '');
      return `<div class="${esc(cls)}" data-path="${esc(f.rel_path)}">
        <h3>${esc(f.name)}</h3>
        <div class="meta">${badge} · ${esc(f.date || 'unknown date')}</div>
        <div class="file-count">${f.file_count} atlas file(s)</div>
      </div>`;
    }).join('');

    // Attach click handlers — no inline onclick
    el.querySelectorAll('.folder-card').forEach(card => {
      card.addEventListener('click', () => browseFolder(card.dataset.path));
    });

  } catch (err) {
    el.innerHTML = `<div class="error-banner">Failed to load folders: ${esc(err.message)}</div>`;
  }
}

/* ─── Browse folder ───────────────────────────────────────── */

function browseFolder(relPath) {
  const gv = document.getElementById('gallery-view');
  gv.style.display = 'block';
  document.getElementById('folder-list').style.display = 'none';
  document.getElementById('breadcrumb').innerHTML =
    `<a href="#" id="back-link">&larr; Back to folders</a>` +
    ` <span class="sep">/</span> <span>${esc(relPath)}</span>`;
  document.getElementById('back-link').addEventListener('click', e => {
    e.preventDefault();
    showFolders();
  });
  loadGallery(relPath);
}

function showFolders() {
  document.getElementById('gallery-view').style.display = 'none';
  document.getElementById('folder-list').style.display = '';
}

/* ─── Gallery (atlas listing) ─────────────────────────────── */

async function loadGallery(relPath) {
  const atlasGallery = document.getElementById('atlas-gallery');
  const frameGallery = document.getElementById('frame-gallery');
  const tabBar = document.getElementById('tab-bar');

  atlasGallery.innerHTML = '<div class="loading">Loading atlases...</div>';
  tabBar.innerHTML = '';

  try {
    const data = await api(`/api/browse?folder=${encodeURIComponent(relPath)}`);
    if (data.error || !data.atlases || data.atlases.length === 0) {
      atlasGallery.innerHTML =
        '<div class="empty-state"><h3>No atlas images</h3>' +
        `<p>${esc(data.error || 'This folder contains no PNG atlas files.')}</p></div>`;
      return;
    }

    tabBar.innerHTML =
      `<button class="active" data-tab="atlas">Atlases (${data.atlases.length})</button>` +
      `<button data-tab="frames">Individual Frames</button>`;

    tabBar.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab, btn));
    });

    atlasGallery.innerHTML = data.atlases.map(a => {
      const sizeStr = a.size ? `${a.size.w}x${a.size.h}` : 'unknown';
      return `<div class="gallery-item" data-url="${esc(a.url)}" data-unit="${esc(a.unit)}" data-path="${esc(a.rel_path)}">
        <img src="${esc(a.thumb)}" loading="lazy" alt="${esc(a.name)}">
        <div class="caption"><span class="name">${esc(a.name)}</span><span class="size">${sizeStr}</span></div>
      </div>`;
    }).join('');

    atlasGallery.querySelectorAll('.gallery-item').forEach(item => {
      item.addEventListener('click', () => {
        openAtlas(item.dataset.url, item.dataset.unit, item.dataset.path);
      });
    });

    // Preload frame info
    frameData = {};
    for (const a of data.atlases) {
      try {
        const fd = await api(`/api/frames?atlas=${encodeURIComponent(a.rel_path)}&unit=${encodeURIComponent(a.unit)}`);
        frameData[a.unit] = fd.frames || [];
      } catch (_) { /* skip */ }
    }

  } catch (err) {
    atlasGallery.innerHTML = `<div class="error-banner">Failed to load gallery: ${esc(err.message)}</div>`;
  }
}

/* ─── Tab switching ───────────────────────────────────────── */

function switchTab(tab, btn) {
  document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');
  if (tab === 'frames') renderFrames();
}

function renderFrames() {
  const fg = document.getElementById('frame-gallery');
  const allFrames = [];
  for (const unit of Object.keys(frameData)) {
    for (const f of frameData[unit]) {
      allFrames.push(f);
    }
  }
  if (allFrames.length === 0) {
    fg.innerHTML = '<div class="empty-state"><h3>No frame data</h3><p>Individual frames not available.</p></div>';
    return;
  }
  fg.innerHTML = allFrames.map(f =>
    `<div class="gallery-item">
      <img src="${esc(f.thumb)}" loading="lazy" alt="${esc(f.name)}">
      <div class="caption"><span class="name">${esc(f.name)}</span><span class="size">${esc(f.size)}</span></div>
    </div>`
  ).join('');

  fg.querySelectorAll('.gallery-item img').forEach(img => {
    img.addEventListener('click', function () { openModal(this.src); });
  });
}

/* ─── Atlas detail ────────────────────────────────────────── */

async function openAtlas(url, unit, relPath) {
  try {
    const data = await api(`/api/frames?atlas=${encodeURIComponent(relPath)}&unit=${encodeURIComponent(unit)}`);
    const attrInfo = `<b>Unit:</b> ${esc(unit)}<br><b>Frames:</b> ${data.frames ? data.frames.length : 0}` +
      (data.size ? `<br><b>Frame size:</b> ${data.size.w}x${data.size.h}` : '');
    openModal(url, attrInfo, data.frames ? data.frames.map(f => f.thumb) : null);
  } catch (err) {
    openModal(url, `<b>Unit:</b> ${esc(unit)}<br><span style="color:#a33">Error: ${esc(err.message)}</span>`);
  }
}

/* ─── Boot ────────────────────────────────────────────────── */

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadFolders);
} else {
  loadFolders();
}
