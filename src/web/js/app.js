/**
 * Mikage PromptTable v2 — gallery + model library + dual-scheme annotation editor.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    items: [], categories: [], models: [], roots: [], scanning: false,
    page: 'gallery', view: 'masonry',
    activeCategory: 'all', selectedId: null, selectedImageId: null,
    search: '', columns: 4, inspectorCollapsed: false,
    libType: '', libBase: '',
    families: [],                        // live folder-driven family options
    libFolder: '',                       // absolute folder path filter
    folderCollapsed: {},                 // fullPath -> true
    searchBy: { gallery: '', library: '' }
  };

  function api() { return window.pywebview && window.pywebview.api; }

  // ---- persisted display preferences ----
  var uiSettings = { cardTagFull: false, sidebarCollapsed: false };

  async function loadSettings() {
    if (!api() || !api().get_settings) return;
    try {
      var s = await api().get_settings();
      if (s && typeof s === 'object') {
        uiSettings.cardTagFull = !!s.cardTagFull;
        uiSettings.sidebarCollapsed = !!s.sidebarCollapsed;
      }
    } catch (e) { /* defaults are fine */ }
    applySettings();
  }

  function saveSetting(key, value) {
    uiSettings[key] = value;
    if (api() && api().save_settings) {
      var patch = {};
      patch[key] = value;
      api().save_settings(patch);
    }
    applySettings();
  }

  function applySettings() {
    document.body.classList.toggle('card-tag-full', !!uiSettings.cardTagFull);
    var check = $('tagFullCheck');
    if (check) check.classList.toggle('on', !!uiSettings.cardTagFull);

    var sb = $('sidebar');
    var mw = $('mainWorkspace');
    if (sb) sb.classList.toggle('collapsed', !!uiSettings.sidebarCollapsed);
    if (mw) mw.classList.toggle('sidebar-collapsed', !!uiSettings.sidebarCollapsed);
    // only re-flow when the masonry actually exists (boot order is not fixed)
    if (typeof applyColumns === 'function' && $('masonryView')) applyColumns();
  }

  function toggleSidebar(force) {
    var next = typeof force === 'boolean' ? force : !uiSettings.sidebarCollapsed;
    saveSetting('sidebarCollapsed', next);
  }

  // ================= utils =================

  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>'"]/g, function (t) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[t];
    });
  }

  var LORA_RE = /<lora:([^:>]+)(?::([\d.]+))?>/g;
  function parseLoras(prompt) {
    var out = [], m;
    LORA_RE.lastIndex = 0;
    while ((m = LORA_RE.exec(prompt || '')) !== null) out.push({ name: m[1], weight: m[2] || '1' });
    return out;
  }

  function showToast(msg, type) {
    var t = document.createElement('div');
    t.className = 'toast ' + (type || 'success');
    var icon = type === 'error'
      ? '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
      : '<polyline points="20 6 9 17 4 12"/>';
    t.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' + icon + '</svg><span>' + escapeHtml(msg) + '</span>';
    $('toastContainer').appendChild(t);
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 2900);
  }

  // ---- ask dialog (native confirm/prompt are blocked in WebView2) ----
  var askResolve = null;
  function ask(title, message, opts) {
    opts = opts || {};
    $('askTitle').textContent = title;
    $('askMessage').innerHTML = escapeHtml(message);
    if (opts.input) {
      $('askInput').style.display = '';
      $('askInput').value = opts.value || '';
      $('askInput').placeholder = opts.placeholder || '';
    } else {
      $('askInput').style.display = 'none';
      $('askInput').value = '';
    }
    $('askConfirm').textContent = opts.confirmText || '确定';
    $('askConfirm').className = 'glass-btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
    $('askModal').classList.add('show');
    if (opts.input) setTimeout(function () { $('askInput').focus(); }, 60);
    return new Promise(function (resolve) { askResolve = resolve; });
  }
  function setupAsk() {
    function done(val) {
      var r = askResolve; askResolve = null;
      $('askModal').classList.remove('show');
      if (r) r(val);
    }
    $('askConfirm').addEventListener('click', function () {
      done($('askInput').style.display !== 'none' ? $('askInput').value : true);
    });
    $('askCancel').addEventListener('click', function () { done(null); });
    $('askBackdrop').addEventListener('click', function () { done(null); });
    $('askInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('askConfirm').click(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && $('askModal').classList.contains('show')) done(null);
    });
  }

  function copyText(text, msg) {
    if (!text) return;
    var ok = function () { showToast(msg || '已复制到剪贴板'); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok, function () { fallbackCopy(text, ok); });
    } else fallbackCopy(text, ok);
  }
  function fallbackCopy(text, done) {
    if (api() && api().copy_text) { api().copy_text(text).then(done); return; }
    var ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    done();
  }

  // ================= data helpers =================

  function selected() {
    return state.items.find(function (i) { return i.id === state.selectedId; }) || null;
  }
  function selectedImage() {
    var it = selected();
    if (!it || !it.images || !it.images.length) return null;
    return it.images.find(function (im) { return im.id === state.selectedImageId; }) || it.images[0];
  }
  function catById(id) {
    return state.categories.find(function (c) { return c.id === id; }) || null;
  }
  function catOf(item) { return catById(item.category_id) || state.categories[0] || null; }
  function catColor(cat) { return cat ? (cat.color || '#6366f1') : '#64748b'; }
  function findModelByName(name) {
    if (!name) return null;
    var n = String(name).trim().toLowerCase();
    return state.models.find(function (m) { return (m.name || '').toLowerCase() === n; }) || null;
  }
  function computeResidual(fullPrompt, tags) {
    var set = {};
    (tags || []).forEach(function (t) { set[String(t).trim().toLowerCase()] = 1; });
    return (fullPrompt || '').split(',').map(function (tok) {
      return tok.replace(/\s*\n\s*/g, ' ').trim();
    }).filter(function (tok) { return tok && !set[tok.toLowerCase()]; }).join(', ');
  }
  function primaryImage(item) {
    return (item.images && item.images[0]) || null;
  }

  // Which image of an entry is currently shown on its card (slideshow aware).
  function currentImage(item) {
    if (!item || !item.images || !item.images.length) return null;
    if (item._ssIndex == null || item._ssIndex < 0 || item._ssIndex >= item.images.length) {
      item._ssIndex = 0;
    }
    return item.images[item._ssIndex];
  }

  // Prompt for a given image, honouring the scheme rules:
  //   Tag mode   -> each image carries its own full_prompt
  //   Model mode -> all images share item.shared_prompt
  function imagePrompt(item, im) {
    if (!item) return '';
    if ((item.scheme || 'tags') === 'model') return item.shared_prompt || '';
    return (im && im.full_prompt) || '';
  }

  // Models for an image: Tag mode shares at item level, Model mode is per image.
  function imageModels(item, im) {
    if (!item) return [];
    if ((item.scheme || 'tags') === 'model') return (im && im.models) || [];
    return item.models || [];
  }

  // Card tag block. The entry name sits above it, so here we surface what varies.
  function cardTagsHtml(item) {
    var out = [];
    var scheme = item.scheme || 'tags';

    if (scheme === 'tags') {
      (item.annotation_tags || []).forEach(function (t) {
        out.push('<span class="card-tag is-var">' + escapeHtml(t) + '</span>');
      });
      (item.models || []).slice(0, 4).forEach(function (m) {
        out.push('<span class="card-tag is-model">' + escapeHtml(m.name) + '</span>');
      });
    } else {
      var seen = {};
      (item.images || []).forEach(function (im, i) {
        (im.models || []).forEach(function (m) {
          var k = (m.name || '').toLowerCase();
          if (!k || seen[k]) return;
          seen[k] = 1;
          out.push('<span class="card-tag is-model" title="第 ' + (i + 1) + ' 张">' +
                   escapeHtml(m.name) + '</span>');
        });
      });
      (item.annotation_tags || []).forEach(function (t) {
        out.push('<span class="card-tag">' + escapeHtml(t) + '</span>');
      });
    }

    if (!out.length) {
      return '<div class="card-tags"><span class="card-tags-empty">暂无标注 / 模型</span></div>';
    }
    return '<div class="card-tags">' + out.join('') + '</div>';
  }

  // ---------------- slideshow ----------------

  // ---- one global ticker drives every playing slideshow ----
  //
  // Per-card setInterval timers had to be started/stopped from render(), which
  // runs constantly (selection, edits, filters). Any mismatch between who owned
  // a timer and who stopped it silently froze a slideshow. A single ticker that
  // derives "who should be playing" from state on every beat cannot get out of
  // sync, and it also lets each entry keep its own interval.
  var SS_TICK_MS = 250;

  function ssTick() {
    var now = Date.now();
    state.items.forEach(function (it) {
      var ss = ssOf(it);
      if (!ss.auto || ss.mode === 'off' || (it.images || []).length < 2) return;
      var iv = Math.max(300, parseInt(ss.interval, 10) || 1500);
      if (!it._ssNext) {
        it._ssNext = now + iv;
        return;
      }
      if (now >= it._ssNext) {
        it._ssNext = now + iv;
        stepSlideshow(it, 1);
      }
    });
  }

  function ensureTicker() {
    if (window.__ssTicker) return;
    window.__ssTicker = setInterval(ssTick, SS_TICK_MS);
  }

  // Slideshows play by default for multi-image entries. `touched` records that
  // the user changed the setting, so an explicit stop survives a reload instead
  // of being overridden by the default.
  function ssOf(item) {
    if (!item) return { mode: 'off', auto: false, interval: 1500, touched: false };
    var ss = item.slideshow;
    if (!ss || typeof ss !== 'object') ss = item.slideshow = {};
    if (typeof ss.mode !== 'string') ss.mode = 'off';
    if (typeof ss.auto !== 'boolean') ss.auto = false;
    if (typeof ss.touched !== 'boolean') ss.touched = false;
    if (!ss.touched && (item.images || []).length > 1 && ss.mode === 'off') {
      ss.mode = 'seq';
      ss.auto = true;
    }
    return ss;
  }

  function stepSlideshow(item, dir) {
    var n = (item.images || []).length;
    if (n < 2) return;
    var mode = (item.slideshow || {}).mode || 'off';
    if (mode === 'off') mode = 'seq';

    if (mode === 'shuffle') {
      var next = item._ssIndex;
      while (next === item._ssIndex) next = Math.floor(Math.random() * n);
      item._ssIndex = next;
    } else if (mode === 'rev') {
      item._ssIndex = ((item._ssIndex || 0) - dir + n) % n;
    } else {
      item._ssIndex = ((item._ssIndex || 0) + dir + n) % n;
    }
    paintCardImage(item);
  }

  // Warm a bitmap off-DOM so the swap below paints immediately (no empty frame).
  function preloadImage(src) {
    if (!src) return;
    var img = new Image();
    img.decoding = 'async';
    img.src = src;
  }

  function applyCoverInPlace(wrap, im) {
    var wantVideo = isVideoPath(im && im.path);
    var src = wantVideo ? fullSrc(im) : (hasRasterThumb(im) ? im.thumb_url : fullSrc(im));
    var node = wrap.querySelector('.card-img, .card-noimg, video.card-video');

    // switching medium type (image <-> video <-> empty) needs a real replacement
    var wantTag = wantVideo ? 'VIDEO' : (src ? 'IMG' : 'DIV');
    if (!node || node.tagName !== wantTag) {
      var tmp = document.createElement('div');
      tmp.innerHTML = coverHtml(im, 'card-img');
      if (tmp.firstElementChild) {
        if (node) wrap.replaceChild(tmp.firstElementChild, node);
        else wrap.insertBefore(tmp.firstElementChild, wrap.firstChild);
      }
      return;
    }

    if (wantTag === 'IMG') {
      if (node.getAttribute('src') === src) return;
      // decode first, then assign: assigning an undecoded data URL is what
      // produced the white flash between slides
      var loader = new Image();
      loader.decoding = 'async';
      loader.onload = loader.onerror = function () {
        if (node.getAttribute('src') !== src) node.src = src;
      };
      loader.src = src;
    }
  }

  function paintCardImage(item) {
    var card = document.querySelector('.gallery-card[data-id="' + item.id + '"]');
    if (!card) return;
    var im = currentImage(item);
    var wrap = card.querySelector('.card-img-wrap');
    if (wrap) applyCoverInPlace(wrap, im);

    // pre-warm the neighbours so the following steps are instant
    var ss = ssOf(item);
    if (ss.auto && ss.mode !== 'off' && !isVideoPath(im && im.path)) {
      var n = item.images.length;
      [1, 2].forEach(function (step) {
        var idx = ss.mode === 'shuffle'
          ? Math.floor(Math.random() * n)
          : (((item._ssIndex || 0) + step) % n + n) % n;
        var nb = item.images[idx];
        if (nb && !isVideoPath(nb.path)) {
          preloadImage(hasRasterThumb(nb) ? nb.thumb_url : fullSrc(nb));
        }
      });
    }
    var counter = card.querySelector('.ss-counter');
    if (counter) counter.textContent = (((item._ssIndex || 0) + 1) + '/' + item.images.length);
    var dim = card.querySelector('.card-dimension-tag');
    if (dim) dim.textContent = (im && im.width) ? (im.width + '×' + im.height) : '';
    var badgeBox = card.querySelector('.card-right-badges');
    if (badgeBox) {
      var cnt = item.images.length > 1
        ? '<span class="card-count-badge">' + item.images.length + ' 图</span>' : '';
      badgeBox.innerHTML = mediaBadge(im) + cnt;
    }
  }

  function toggleSlideshow(item) {
    var ss = ssOf(item);
    ss.touched = true;
    ss.auto = !ss.auto;
    if (ss.auto && (ss.mode || 'off') === 'off') ss.mode = 'seq';
    scheduleSave();
    if (ss.auto) startSlideshow(item); else stopSlideshow(item.id);
    var card = document.querySelector('.gallery-card[data-id="' + item.id + '"]');
    if (card) card.classList.toggle('ss-running', !!ss.auto);
    renderSlideshowBar();
    showToast(ss.auto ? '已开始连播' : '已暂停连播');
  }

  // Kept as thin helpers so the rest of the code (and the toolbar) can keep
  // saying "start/stop" without owning timers: the ticker handles the timing.
  function startSlideshow(item) {
    if (!item) return;
    var ss = ssOf(item);
    ensureTicker();
    if (ss.auto && ss.mode !== 'off' && (item.images || []).length > 1) {
      item._ssNext = Date.now() + Math.max(300, parseInt(ss.interval, 10) || 1500);
    }
  }

  function stopSlideshow(itemId) {
    var it = state.items.find(function (x) { return x.id === itemId; });
    if (it) it._ssNext = 0;
  }

  function stopAllSlideshows() {
    state.items.forEach(function (it) { it._ssNext = 0; });
  }

  function restartSlideshows() {
    ensureTicker();
    // nudge every playable entry so a freshly rendered card starts on beat
    state.items.forEach(function (it) {
      var ss = ssOf(it);
      if (ss.auto && ss.mode !== 'off' && (it.images || []).length > 1 && !it._ssNext) {
        it._ssNext = Date.now() + Math.max(300, parseInt(ss.interval, 10) || 1500);
      }
    });
  }
  function usedCount(model) {
    var n = (model.name || '').toLowerCase();
    return state.items.filter(function (it) {
      if ((it.models || []).some(function (m) {
        return (m.name || '').toLowerCase() === n;
      })) return true;
      if ((it.images || []).some(function (im) {
        return (im.models || []).some(function (m) {
          return (m.name || '').toLowerCase() === n;
        });
      })) return true;
      return (it.images || []).some(function (im) {
        return parseLoras(im.full_prompt).some(function (l) {
          return l.name.toLowerCase() === n;
        });
      });
    }).length;
  }

  function thumbSrc(im) {
    if (im && im.thumb_url && String(im.thumb_url).indexOf('data:') === 0) return im.thumb_url;
    return im && im.path ? '/api/image?path=' + encodeURIComponent(im.path) : '';
  }
  function fullSrc(im) {
    return im && im.path ? '/api/image?path=' + encodeURIComponent(im.path) : thumbSrc(im);
  }

  var VIDEO_EXTS = ['mp4', 'webm', 'mov', 'm4v'];
  var ANIM_EXTS = ['gif', 'webp', 'apng'];

  function extOf(path) {
    var m = String(path || '').toLowerCase().match(/\.([a-z0-9]+)$/);
    return m ? m[1] : '';
  }
  function isVideoPath(path) { return VIDEO_EXTS.indexOf(extOf(path)) !== -1; }
  function isAnimatedPath(path) { return ANIM_EXTS.indexOf(extOf(path)) !== -1; }

  // A real (raster) thumbnail only exists when thumb_url holds a data URL;
  // thumbSrc() falls back to the raw file path, which must NOT be used as an
  // <img> source for videos.
  function hasRasterThumb(im) {
    return !!(im && im.thumb_url && String(im.thumb_url).indexOf('data:') === 0);
  }

  function mediaBadge(im) {
    if (!im || !im.path) return '';
    if (isVideoPath(im.path)) {
      return '<span class="card-media-badge video"><svg viewBox="0 0 24 24" fill="currentColor">' +
        '<polygon points="6 3 20 12 6 21"/></svg>视频</span>';
    }
    if (isAnimatedPath(im.path)) {
      return '<span class="card-media-badge anim"><svg viewBox="0 0 24 24" fill="currentColor">' +
        '<polygon points="6 3 20 12 6 21"/></svg>动图</span>';
    }
    return '';
  }

  // Card / table cover: video files let the browser render the first frame
  // (no poster generation needed); animated files use their static thumb.
  function coverHtml(im, className) {
    if (!im || !im.path) {
      return '<div class="card-noimg">未绑定图片</div>';
    }
    if (hasRasterThumb(im)) {
      return '<img class="' + className + '" src="' + im.thumb_url + '" loading="lazy" alt="">';
    }
    if (isVideoPath(im.path)) {
      // let WebView2 decode and paint the first frame itself
      return '<video class="' + className + ' card-video" src="' + fullSrc(im) +
        '#t=0.1" preload="metadata" muted playsinline></video>';
    }
    if (im.path) {
      return '<img class="' + className + '" src="' + fullSrc(im) + '" loading="lazy" alt="">';
    }
    return '<div class="card-noimg">未绑定图片</div>';
  }

  function getFilteredItems() {
    var q = state.search.trim().toLowerCase();
    return state.items.filter(function (it) {
      if (state.activeCategory !== 'all' && it.category_id !== state.activeCategory) return false;
      if (!q) return true;
      var hay = [it.character, it.recommendation, (it.annotation_tags || []).join(' ')].join(' ').toLowerCase();
      (it.models || []).forEach(function (m) { hay += ' ' + String(m.name || '').toLowerCase(); });
      hay += ' ' + String(it.shared_prompt || '').toLowerCase();
      (it.images || []).forEach(function (im) {
        hay += ' ' + String(im.full_prompt || '').toLowerCase();
        (im.models || []).forEach(function (m) {
          hay += ' ' + String(m.name || '').toLowerCase();
        });
      });
      return hay.indexOf(q) !== -1;
    });
  }

  // ================= persistence =================

  var saveTimer = null;
  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      var it = selected();
      if (it && api()) api().save_item(JSON.parse(JSON.stringify(it)));
    }, 400);
  }
  function saveNow(it) {
    if (api()) api().save_item(JSON.parse(JSON.stringify(it)));
  }

  async function refreshState() {
    if (!api()) return;
    var res = await api().get_state();
    state.items = res.items || [];
    state.categories = res.categories || [];
    state.items.forEach(function (it) { ssOf(it); });   // default-on slideshow
    // drop placeholder entries left behind by earlier versions
    if (!purgeEmptyEntries._done) {
      purgeEmptyEntries._done = true;
      setTimeout(function () { purgeEmptyEntries(true); }, 800);
    }
    if (res.pruned && res.pruned.entries) {
      showToast('已自动清理 ' + res.pruned.entries + ' 个没有图片的空条目');
    }
    if (state.selectedId && !state.items.find(function (i) { return i.id === state.selectedId; })) {
      state.selectedId = state.items.length ? state.items[0].id : null;
      state.selectedImageId = null;
    }
    render();
  }

  // ================= render dispatch =================

  function render() {
    var vp = $('contentViewport');
    var keepScroll = vp ? vp.scrollTop : 0;
    var filtered = getFilteredItems();
    ensureTicker();                 // the single heartbeat for all slideshows
    var scopeText = state.activeCategory === 'all'
      ? '全部条目'
      : ((catById(state.activeCategory) || { name: '' }).name);

    $('tbScope').textContent = scopeText;
    $('tbCount').textContent = state.page === 'library'
      ? state.models.length + ' 模型'
      : filtered.length + ' 条';
    $('currentScopeLabel').textContent = scopeText;

    renderCategories();
    renderDatalist();

    if (state.page === 'library') { renderLibrary(); return; }

    if (!filtered.length) {
      $('masonryView').style.display = 'none';
      $('tableView').hidden = true;
      $('emptyState').hidden = false;
      renderEditor();
      return;
    }
    $('emptyState').hidden = true;
    if (state.view === 'masonry') {
      $('masonryView').style.display = '';
      $('tableView').hidden = true;
      renderMasonry(filtered);
    } else {
      $('masonryView').style.display = 'none';
      $('tableView').hidden = false;
      renderTable(filtered);
    }
    renderEditor();
    if (vp && keepScroll) vp.scrollTop = keepScroll;
  }

  // ================= sidebar =================

  function renderCategories() {
    var list = $('categoryList');
    list.innerHTML = '';
    var frag = document.createDocumentFragment();

    var all = document.createElement('div');
    all.className = 'category-item' + (state.activeCategory === 'all' ? ' active' : '');
    all.innerHTML = '<span class="cat-dot" style="background:#94a3b8"></span><span class="cat-name">全部条目</span><span class="cat-count">' + state.items.length + '</span>';
    all.addEventListener('click', function () { state.activeCategory = 'all'; render(); });
    frag.appendChild(all);

    state.categories.forEach(function (cat) {
      var count = state.items.filter(function (it) { return it.category_id === cat.id; }).length;
      var node = document.createElement('div');
      node.className = 'category-item' + (state.activeCategory === cat.id ? ' active' : '');
      node.title = '单击筛选 · 双击重命名';
      node.innerHTML = '<span class="cat-dot" style="background:' + escapeHtml(catColor(cat)) + '"></span>' +
        '<span class="cat-name">' + escapeHtml(cat.name) + '</span>' +
        '<span class="cat-count">' + count + '</span>' +
        '<button class="cat-del" title="删除分区">&times;</button>';

      node.addEventListener('click', function (e) {
        if (e.target.classList.contains('cat-del')) return;
        state.activeCategory = cat.id;
        render();
      });
      node.addEventListener('dblclick', function () { renameCategoryFlow(cat); });
      node.querySelector('.cat-del').addEventListener('click', function (e) {
        e.stopPropagation();
        deleteCategoryFlow(cat);
      });
      node.addEventListener('dragover', function (e) { e.preventDefault(); node.classList.add('drag-over'); });
      node.addEventListener('dragleave', function () { node.classList.remove('drag-over'); });
      node.addEventListener('drop', function (e) {
        e.preventDefault();
        node.classList.remove('drag-over');
        var id = e.dataTransfer.getData('text/plain');
        var it = state.items.find(function (i) { return i.id === id; });
        if (it && it.category_id !== cat.id) {
          it.category_id = cat.id;
          saveNow(it);
          showToast('「' + (it.character || '条目') + '」已移入 ' + cat.name);
          render();
        }
      });
      frag.appendChild(node);
    });
    list.appendChild(frag);
  }

  async function addCategoryFlow() {
    var name = await ask('新建展览分区', '输入分区名称：', { input: true, placeholder: '如：人物 / 服饰 / 画风' });
    if (name === null || !String(name).trim()) return;
    var res = await api().add_category(String(name).trim());
    if (res.success) { state.categories = res.categories; render(); }
    else showToast(res.message, 'error');
  }
  async function renameCategoryFlow(cat) {
    var name = await ask('重命名分区', '修改「' + cat.name + '」：', { input: true, value: cat.name });
    if (name === null || !String(name).trim()) return;
    var res = await api().rename_category(cat.id, String(name).trim());
    if (res.success) { state.categories = res.categories; render(); }
  }
  async function deleteCategoryFlow(cat) {
    var count = state.items.filter(function (i) { return i.category_id === cat.id; }).length;
    var ok = await ask('删除分区', '删除「' + cat.name + '」？其中 ' + count + ' 个条目将移入第一个分区。',
      { danger: true, confirmText: '删除' });
    if (!ok) return;
    var res = await api().delete_category(cat.id);
    if (res.success) {
      state.categories = res.categories;
      state.items = res.items;
      if (state.activeCategory === cat.id) state.activeCategory = 'all';
      render();
    } else showToast(res.message, 'error');
  }

  // ================= masonry =================

  var MIN_CARD_WIDTH = 158;

  // The slider is the *desired* maximum; on a narrow window (or with the editor
  // panel open) we render fewer columns so cards — and their text — stay legible.
  function effectiveColumns() {
    var viewport = $('contentViewport');
    if (!viewport) return state.columns;
    var avail = viewport.clientWidth - 36;            // horizontal padding
    if (avail <= 0) return state.columns;
    var maxFit = Math.max(2, Math.floor(avail / MIN_CARD_WIDTH));
    return Math.max(2, Math.min(state.columns, Math.min(6, maxFit)));
  }

  function applyColumns() {
    var view = $('masonryView');
    if (!view) return;
    var eff = effectiveColumns();
    view.className = 'masonry-container columns-' + eff;
    var label = $('columnsVal');
    if (label) {
      var clamped = eff < state.columns;
      label.textContent = clamped ? (eff + ' 列（窗口较窄）') : (eff + ' 列');
      label.classList.toggle('clamped', clamped);
    }
  }

  function renderMasonry(items) {
    var view = $('masonryView');
    view.innerHTML = '';
    applyColumns();
    var frag = document.createDocumentFragment();

    items.forEach(function (item) {
      var cat = catOf(item);
      var im = primaryImage(item) || {};
      var card = document.createElement('div');
      card.className = 'gallery-card' + (item.id === state.selectedId ? ' selected' : '');
      card.dataset.id = item.id;
      card.draggable = true;

      var imgHtml = coverHtml(im, 'card-img');
      var rightBadges = mediaBadge(im);
      if (item.images && item.images.length > 1) {
        rightBadges += '<span class="card-count-badge">' + item.images.length + ' 图</span>';
      }
      var extra = rightBadges ? '<div class="card-right-badges">' + rightBadges + '</div>' : '';

      var tagsHtml = cardTagsHtml(item);

      var ssControls = (item.images && item.images.length > 1)
        ? '<div class="card-ss-controls">' +
            '<button class="ss-btn ss-prev" title="上一张">‹</button>' +
            '<span class="ss-counter">1/' + item.images.length + '</span>' +
            '<button class="ss-btn ss-next" title="下一张">›</button>' +
            '<button class="ss-btn ss-play" title="开始 / 暂停连播">▶</button>' +
          '</div>'
        : '';

      card.innerHTML =
        '<div class="card-img-wrap">' +
          imgHtml + ssControls +
          '<div class="card-top-badges">' +
            (cat ? '<span class="character-badge" style="color:' + escapeHtml(catColor(cat)) + '">' + escapeHtml(cat.name) + '</span>' : '') +
          '</div>' + extra +
          '<div class="card-quick-actions">' +
            '<button class="action-icon-btn qa-zoom" title="查看大图"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg></button>' +
            '<button class="action-icon-btn qa-copy" title="复制主图 Prompt"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>' +
          '</div>' +
        '</div>' +
        '<div class="card-body">' +
          '<div class="card-name" title="' + escapeHtml(item.character || '未命名') + '">' +
            escapeHtml(item.character || '未命名') + '</div>' +
          tagsHtml +
          (item.recommendation
            ? '<div class="card-remark" title="' + escapeHtml(item.recommendation) + '">' +
                escapeHtml(item.recommendation) + '</div>'
            : '') +
          '<div class="card-footer-bar">' +
            '<span class="card-dimension-tag">' + (im && im.width ? im.width + '×' + im.height : '') + '</span>' +
            '<span class="card-copy-chip qa-copy2">复制词</span>' +
          '</div>' +
        '</div>';

      card.addEventListener('click', function (e) {
        if (e.target.closest('.qa-zoom')) {
          e.stopPropagation();
          openLightbox(item, currentImage(item));
          return;
        }
        if (e.target.closest('.qa-copy, .qa-copy2')) {
          e.stopPropagation();
          copyText(imagePrompt(item, currentImage(item)), '已复制当前图的 Prompt');
          return;
        }
        if (e.target.closest('.ss-prev')) { e.stopPropagation(); stepSlideshow(item, -1); return; }
        if (e.target.closest('.ss-next')) { e.stopPropagation(); stepSlideshow(item, 1); return; }
        if (e.target.closest('.ss-play')) { e.stopPropagation(); toggleSlideshow(item); return; }

        var ss = item.slideshow || {};
        if (ss.mode && ss.mode !== 'off' && item.images.length > 1
            && e.target.closest('.card-img-wrap')) {
          e.stopPropagation();
          stepSlideshow(item, 1);
          return;
        }
        selectItem(item.id);
      });
      if (ssOf(item).auto && ssOf(item).mode !== 'off') {
        card.classList.add('ss-running');
      }
      card.addEventListener('dragstart', function (e) {
        e.dataTransfer.setData('text/plain', item.id);
      });
      frag.appendChild(card);
    });

    view.appendChild(frag);
    restartSlideshows();
  }



  function renderImageStrip(item) {
    var strip = $('imgStrip');
    strip.innerHTML = '';
    $('imgCountHint').textContent = item.images.length ? ('共 ' + item.images.length + ' 张') : '';
    item.images.forEach(function (im, i) {
      var th = document.createElement('div');
      th.className = 'img-thumb' + (im.id === state.selectedImageId ? ' active' : '');
      th.innerHTML = (i === 0 ? '<span class="primary-star">★</span>' : '') +
        (hasRasterThumb(im)
          ? '<img src="' + im.thumb_url + '" loading="lazy">'
          : (isVideoPath(im.path)
              ? '<video src="' + fullSrc(im) + '#t=0.1" preload="metadata" muted playsinline></video>'
              : (im.path
                  ? '<img src="' + fullSrc(im) + '" loading="lazy">'
                  : '<span style="font-size:10px;color:var(--text-muted)">无图</span>'))) +
        '<button class="thumb-remove" title="移除该图">×</button>';
      th.addEventListener('click', function (e) {
        if (e.target.classList.contains('thumb-remove')) return;
        state.selectedImageId = im.id;
        renderEditor();
      });
      th.querySelector('.thumb-remove').addEventListener('click', function (e) {
        e.stopPropagation();
        removeImageFlow(im.id);
      });
      $('imgStrip').appendChild(th);
    });
  }

  function renderAnnotTags(item) {
    var flow = $('annotTagsFlow');
    flow.innerHTML = '';
    if (!(item.annotation_tags || []).length) {
      flow.innerHTML = '<span style="font-size:11px;color:var(--text-muted)">暂无标注 Tag</span>';
      return;
    }
    item.annotation_tags.forEach(function (tag) {
      var pill = document.createElement('span');
      pill.className = 'tag-pill annot';
      pill.title = '点击移除';
      pill.innerHTML = escapeHtml(tag) + '<span class="pill-x">×</span>';
      pill.addEventListener('click', function () {
        item.annotation_tags = item.annotation_tags.filter(function (t) { return t !== tag; });
        scheduleSave();
        renderEditor();
        refreshItemViews(item);
      });
      flow.appendChild(pill);
    });
  }

  // ---------------- model list editors ----------------

  // kind 'item'  : shared list (Tag mode)
  // kind 'image' : per-image list (Model mode)
  function renderModelList(container, item, im, kind) {
    if (!container) return;
    container.innerHTML = '';
    var models = kind === 'item' ? (item.models || []) : ((im && im.models) || []);

    if (!models.length) {
      container.innerHTML = '<div class="model-empty">暂无模型</div>';
      return;
    }

    models.forEach(function (m, i) {
      var row = document.createElement('div');
      row.className = 'model-row';
      row.innerHTML =
        '<input type="text" class="glass-input model-name-input" spellcheck="false" ' +
          'autocomplete="off" value="' + escapeHtml(m.name || '') + '">' +
        '<span class="model-type-chip hidden"></span>' +
        '<button class="mini-btn act-open" title="打开 Civitai 页面">Civitai</button>' +
        '<button class="mini-btn ghost act-del" title="移除该模型">×</button>';

      var input = row.querySelector('.model-name-input');
      var chip = row.querySelector('.model-type-chip');
      paintTypeChip(chip, m.name);

      var commit = function (inp) {
        m.name = inp.value;
        var lib = findModelByName(inp.value);
        m.type = lib ? lib.type : '';
        m.lib_id = lib ? lib.id : '';
        paintTypeChip(chip, inp.value);
        scheduleSave();
        refreshItemViews(item);
      };
      // typing refreshes the list live and claims ownership of the dropdown
      input.addEventListener('input', function () {
        suggest.input = this;
        commit(this);
        showModelSuggest(this.value, this);
      });
      input.addEventListener('focus', function () {
        suggest.input = this;          // the dropdown fills THIS input on pick
        showModelSuggest(this.value, this);
      });
      input.addEventListener('blur', scheduleHideSuggest);

      row.querySelector('.act-open').addEventListener('click', function () {
        openModelExternal(m.name);
      });
      row.querySelector('.act-del').addEventListener('click', function () {
        models.splice(i, 1);
        scheduleSave();
        renderEditor();
        refreshCardTags(item);
      });

      container.appendChild(row);
    });
  }

  // Repaint a single card's tag block after a model/tag edit, so the card and
  // the editor never drift apart while typing.
  // Repaint the card and the table row for an entry after an edit, so the
  // sidebar, the gallery and the table never disagree.
  function refreshItemViews(item) {
    if (!item) return;

    var card = document.querySelector('.gallery-card[data-id="' + item.id + '"]');
    if (card) {
      var name = card.querySelector('.card-name');
      if (name) {
        name.textContent = item.character || '未命名';
        name.title = item.character || '未命名';
      }
      refreshCardTags(item);

      // the remark block is created/removed on demand
      var body = card.querySelector('.card-body');
      var footer = card.querySelector('.card-footer-bar');
      var remark = card.querySelector('.card-remark');
      var text = (item.recommendation || '').trim();
      if (text) {
        if (remark) {
          remark.textContent = text;
          remark.title = text;
        } else if (body && footer) {
          var d = document.createElement('div');
          d.className = 'card-remark';
          d.textContent = text;
          d.title = text;
          body.insertBefore(d, footer);
        }
      } else if (remark) {
        remark.remove();
      }
    }

    var row = document.querySelector('.glass-table tbody tr[data-id="' + item.id + '"]');
    if (row) {
      var cells = row.querySelectorAll('td');
      if (cells.length >= 7) {
        var badge = cells[2].querySelector('.table-char-badge');
        if (badge) badge.textContent = item.character || '未命名';
        cells[3].textContent = (item.scheme || 'tags') === 'model'
          ? ((imageModels(item, currentImage(item)) || []).map(function (m) {
              return m.name;
            }).filter(Boolean).join(' + ') || '-')
          : ((item.annotation_tags || []).join(', ') || '-');
        var rec = cells[6].querySelector('.table-rec-text');
        if (rec) rec.textContent = item.recommendation || '-';
      }
    }
  }

  function refreshCardTags(item) {
    var card = document.querySelector('.gallery-card[data-id="' + item.id + '"]');
    if (!card) return;
    var box = card.querySelector('.card-tags');
    if (!box) return;
    var tmp = document.createElement('div');
    tmp.innerHTML = cardTagsHtml(item);
    var fresh = tmp.firstElementChild;
    if (fresh) box.parentNode.replaceChild(fresh, box);
  }

  function paintTypeChip(chip, name) {
    if (!chip) return;
    if (!name || !String(name).trim()) {
      chip.textContent = ''; chip.className = 'model-type-chip hidden'; return;
    }
    var lib = findModelByName(name);
    chip.classList.remove('hidden');
    if (lib) {
      chip.textContent = lib.type === 'checkpoint' ? 'Checkpoint' : 'LoRA';
      chip.className = 'model-type-chip ' + lib.type;
    } else {
      chip.textContent = '自定义';
      chip.className = 'model-type-chip';
    }
  }

  function addModelTo(kind) {
    var item = selected();
    if (!item) return;
    if (kind === 'item') {
      if (!Array.isArray(item.models)) item.models = [];
      item.models.push({
        name: '',
        type: item.models.length === 0 ? 'checkpoint' : 'lora',
        lib_id: ''
      });
    } else {
      var im = selectedImage();
      if (!im) { showToast('请先选择一张图片', 'error'); return; }
      if (!Array.isArray(im.models)) im.models = [];
      im.models.push({
        name: '',
        type: im.models.length === 0 ? 'checkpoint' : 'lora',
        lib_id: ''
      });
    }
    scheduleSave();
    renderEditor();
    refreshCardTags(item);
    // focus the freshly added row so the user can type immediately
    var list = kind === 'item' ? $('tagModelList') : $('imgModelList');
    var rows = list.querySelectorAll('.model-name-input');
    if (rows.length) rows[rows.length - 1].focus();
  }

  async function openModelExternal(name) {
    if (!name || !String(name).trim()) { showToast('请先填写模型名称', 'error'); return; }
    var lib = findModelByName(name);
    if (lib) {
      var r = await api().open_model_page(lib.id);
      if (!r.success) showToast(r.message, 'error');
    } else {
      await api().open_civitai_search(name);
    }
  }

  function renderLoraPills(container, prompt) {
    container.innerHTML = '';
    var loras = parseLoras(prompt);
    if (!loras.length) return;
    loras.forEach(function (l) {
      var pill = document.createElement('span');
      pill.className = 'lora-pill';
      pill.textContent = 'LoRA: ' + l.name + ' @ ' + l.weight;
      pill.title = '打开 Civitai 页面';
      pill.addEventListener('click', function () {
        var lib = findModelByName(l.name);
        if (lib) api().open_model_page(lib.id);
        else api().open_civitai_search(l.name);
      });
      container.appendChild(pill);
    });
  }


  async function refreshFamilies() {
    if (!api() || !api().get_family_options) return;
    try {
      var list = await api().get_family_options();
      state.families = list || [];
    } catch (e) { /* keep previous */ }
    renderFamilySelect();
  }

  function renderFamilySelect() {
    var sel = $('fieldFamily');
    if (!sel) return;
    var item = selected();
    var current = item ? (item.family || '') : '';
    sel.innerHTML = '';
    var none = document.createElement('option');
    none.value = '';
    none.textContent = '大类：未标记';
    sel.appendChild(none);
    var names = state.families.slice();
    // keep a stale value visible instead of silently dropping it
    if (current && names.map(function (n) { return n.toLowerCase(); }).indexOf(current.toLowerCase()) === -1) {
      names.push(current);
    }
    names.forEach(function (name) {
      var o = document.createElement('option');
      o.value = name;
      o.textContent = name;
      if (name.toLowerCase() === current.toLowerCase()) o.selected = true;
      sel.appendChild(o);
    });
    sel.classList.toggle('is-empty', !current);
  }

  function renderDatalist() {
    // nothing to prefetch; suggestions are built live in the dropdown
  }

  var SUGGEST_CAP = 500;
  var suggest = { showAll: false, input: null };
  var suggestHideTimer = null;

  function scheduleHideSuggest() {
    clearTimeout(suggestHideTimer);
    suggestHideTimer = setTimeout(hideModelSuggest, 180);
  }

  function famKey(name) {
    return String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  function showModelSuggest(query, anchorEl) {
    clearTimeout(suggestHideTimer);     // a pending hide must not close it
    var box = $('modelSuggest');
    // fixed-position element: lets it escape any clipping/overflow context
    if (anchorEl && anchorEl.getBoundingClientRect) {
      var r = anchorEl.getBoundingClientRect();
      box.style.left = Math.round(r.left) + 'px';
      box.style.top = Math.round(r.bottom + 6) + 'px';
      box.style.width = Math.round(Math.max(260, r.width)) + 'px';
      box.style.right = 'auto';
    }
    var q = (query || '').trim().toLowerCase();
    var it = selected();
    var fam = it && it.family ? String(it.family).toLowerCase() : '';
    var all = state.models;
    var scopedOut = 0;
    if (fam && !suggest.showAll) {
      // strict: only models belonging to the marked family folder
      var key = famKey(fam);
      var scoped = all.filter(function (m) {
        return famKey(m.family) === key;
      });
      if (scoped.length) {
        scopedOut = all.length - scoped.length;
        all = scoped;
      }
    }
    var matches;
    if (q) {
      var terms = q.split(/\s+/).filter(Boolean);
      matches = all.filter(function (m) {
        var hay = (m.name + ' ' + m.base_model + ' ' + m.version + ' ' + m.filename).toLowerCase();
        return terms.every(function (t) { return hay.indexOf(t) !== -1; });
      });
    } else {
      matches = all.slice().sort(function (a, b) {
        return (a.name || '').localeCompare(b.name || '');
      });
    }
    box.innerHTML = '';
    if (!matches.length) {
      box.innerHTML = '<div class="ms-empty">没有匹配的库内模型，可直接填写自定义名称</div>';
      box.classList.add('show');
      return;
    }
    var head = document.createElement('div');
    head.className = 'ms-count';
    if (fam && !suggest.showAll && scopedOut > 0) {
      head.innerHTML = '已按大类 <b style="color:#86efac">' + escapeHtml(it.family) + '</b> 筛选 · ' +
        matches.length + ' 个' +
        '<button type="button" id="msShowAll" style="float:right;border:none;background:none;color:#7dd3fc;font-size:10.5px;cursor:pointer">显示全部模型</button>';
    } else {
      head.textContent = matches.length > SUGGEST_CAP
        ? ('共 ' + matches.length + ' 个匹配，显示前 ' + SUGGEST_CAP + ' 个')
        : ('共 ' + matches.length + ' 个库内模型');
    }
    box.appendChild(head);
    var showAllBtn = head.querySelector('#msShowAll');
    if (showAllBtn) {
      showAllBtn.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();
        suggest.showAll = true;
        showModelSuggest(suggest.input ? suggest.input.value : '', suggest.input);
      });
    }
    matches.slice(0, SUGGEST_CAP).forEach(function (m) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ms-item';
      b.innerHTML = '<span class="ms-name">' + escapeHtml(m.name) +
          (m.family ? '<span class="ms-family">' + escapeHtml(m.family) + '</span>' : '') + '</span>' +
        '<span class="ms-meta"><span class="ms-type ' + escapeHtml(m.type) + '">' +
        (m.type === 'checkpoint' ? 'Checkpoint' : 'LoRA') + '</span>' +
        (m.base_model ? ' · ' + escapeHtml(m.base_model) : '') +
        (m.version ? ' · ' + escapeHtml(m.version) : '') + '</span>';
      b.addEventListener('mousedown', function (e) {
        e.preventDefault();               // keep focus in the input
        var target = suggest.input;
        if (target) {
          target.value = m.name;
          target.dispatchEvent(new Event('input', { bubbles: true }));
          try { target.focus(); } catch (err) {}
        }
        box.classList.remove('show');
      });
      box.appendChild(b);
    });
    box.classList.add('show');
  }
  function hideModelSuggest() {
    $('modelSuggest').classList.remove('show');
  }

  // ---------------- editor image actions ----------------

  async function addImagesToEntryFlow() {
    var it = selected();
    if (!it) return;
    var paths = await api().pick_images();
    if (!paths || !paths.length) return;
    var res = await api().add_images_to_entry(it.id, paths);
    if (res.success) {
      it.images = res.item.images;
      state.selectedImageId = it.images[it.images.length - 1].id;
      showToast('已添加 ' + res.added + ' 张图');
      render();
    }
  }

  async function replaceImageFlow() {
    var it = selected(), cur = selectedImage();
    if (!it || !cur) return;
    var res = await api().replace_entry_image(it.id, cur.id);
    if (res.success) {
      var nu = res.item.images.find(function (x) { return x.id === cur.id; });
      if (nu) Object.assign(cur, nu);
      showToast('图片已更换');
      render();
    } else if (res.message && res.message.indexOf('取消') === -1) {
      showToast(res.message, 'error');
    }
  }

  async function reparseImageFlow() {
    var it = selected(), cur = selectedImage();
    if (!it || !cur) return;
    var res = await api().reparse_entry_image(it.id, cur.id);
    if (res.success) {
      var nu = res.item.images.find(function (x) { return x.id === cur.id; });
      if (nu) Object.assign(cur, nu);
      it.recommendation = res.item.recommendation;
      it.negative_prompt = res.item.negative_prompt;
      showToast('已重读该图元数据');
      render();
    } else showToast(res.message || '解析失败', 'error');
  }

  async function setPrimaryImageFlow() {
    var it = selected(), cur = selectedImage();
    if (!it || !cur) return;
    var res = await api().set_primary_image(it.id, cur.id);
    if (res.success) { it.images = res.item.images; showToast('已设为主图'); render(); }
  }

  // ---- one-click apply to every image in the entry ----

  async function applyPromptToAll() {
    var item = selected(), cur = selectedImage();
    if (!item || !cur) return;
    var n = (item.images || []).length;
    if (n < 2) { showToast('该条目只有一张图，无需应用', 'error'); return; }
    var ok = await ask('应用到全部图片',
      '把当前这张图的「使用提示词」覆盖到本条目全部 ' + n + ' 张图？' +
      '其它图片原有的提示词会被替换。',
      { danger: true, confirmText: '覆盖全部 ' + n + ' 张' });
    if (!ok) return;
    item.images.forEach(function (im) { im.full_prompt = cur.full_prompt || ''; });
    scheduleSave();
    renderEditor();
    render();
    showToast('已应用到全部 ' + n + ' 张图');
  }

  async function applyResidualToAll() {
    var item = selected(), cur = selectedImage();
    if (!item || !cur) return;
    var n = (item.images || []).length;
    if (n < 2) { showToast('该条目只有一张图，无需应用', 'error'); return; }
    var ok = await ask('应用到全部图片',
      '把当前图的「细分提示词」覆盖到全部 ' + n + ' 张图？',
      { danger: true, confirmText: '覆盖全部 ' + n + ' 张' });
    if (!ok) return;
    item.images.forEach(function (im) { im.residual_prompt = cur.residual_prompt || ''; });
    scheduleSave();
    showToast('细分提示词已应用到全部图片');
  }

  async function removeImageFlow(imageId) {
    var it = selected();
    if (!it) return;
    var last = (it.images || []).length <= 1;
    var ok = await ask('移除图片',
      last
        ? '这是该条目的最后一张图片，移除后条目会一起删除（不会删除磁盘文件）。'
        : '从条目中移除该图？（不删除磁盘文件）',
      { danger: true, confirmText: last ? '移除并删除条目' : '移除' });
    if (!ok) return;
    var res = await api().remove_entry_image(it.id, imageId);
    if (!res.success) return;

    it.images = res.item.images;
    if (!it.images.length) {
      // the entry is now an empty placeholder: drop it so nothing is left behind
      await api().delete_item(it.id);
      state.items = state.items.filter(function (x) { return x.id !== it.id; });
      state.selectedId = state.items.length ? state.items[0].id : null;
      state.selectedImageId = null;
      showToast('最后一张图片已移除，空条目已自动删除');
    } else if (state.selectedImageId === imageId) {
      state.selectedImageId = it.images[0].id;
    }
    render();
  }

  // Sweep any placeholder entries that lost their images earlier.
  async function purgeEmptyEntries(silent) {
    var empties = state.items.filter(function (it) {
      return !(it.images || []).length && !(it.prompt || '').trim();
    });
    if (!empties.length) {
      if (!silent) showToast('没有空条目');
      return 0;
    }
    for (var i = 0; i < empties.length; i++) {
      await api().delete_item(empties[i].id);
    }
    state.items = state.items.filter(function (it) { return empties.indexOf(it) === -1; });
    if (!state.items.find(function (x) { return x.id === state.selectedId; })) {
      state.selectedId = state.items.length ? state.items[0].id : null;
    }
    render();
    if (!silent) showToast('已清理 ' + empties.length + ' 个空条目');
    return empties.length;
  }

  // ---------------- item flows ----------------

  async function deleteItemFlow(id) {
    var item = state.items.find(function (i) { return i.id === id; });
    if (!item) return;
    var ok = await ask('删除条目', '确定删除「' + (item.character || '未命名') + '」？无法撤销。',
      { danger: true, confirmText: '删除' });
    if (!ok) return;
    await api().delete_item(id);
    state.items = state.items.filter(function (i) { return i.id !== id; });
    if (state.selectedId === id) {
      state.selectedId = state.items.length ? state.items[0].id : null;
      state.selectedImageId = null;
    }
    showToast('已删除');
    render();
  }

  async function clearAllFlow() {
    var ok = await ask('清空所有条目', '将删除全部 ' + state.items.length + ' 条注释记录，无法撤销。',
      { danger: true, confirmText: '全部删除' });
    if (!ok) return;
    await api().clear_items();
    state.items = [];
    state.selectedId = null;
    state.selectedImageId = null;
    showToast('已清空');
    render();
  }


  async function addBlankFlow() {
    var catId = state.activeCategory === 'all'
      ? (state.categories[0] ? state.categories[0].id : '') : state.activeCategory;
    var res = await api().add_blank_item(catId);
    if (res.success) {
      state.items.push(res.item);
      selectItem(res.item.id);
      showToast('已新增空白条目');
    }
  }

  // ================= table =================

  function renderTable(items) {
    var body = $('tableBody');
    body.innerHTML = '';
    var frag = document.createDocumentFragment();

    items.forEach(function (item, idx) {
      var cat = catOf(item);
      var im = primaryImage(item) || {};
      var tr = document.createElement('tr');
      tr.className = item.id === state.selectedId ? 'selected' : '';
      tr.dataset.id = item.id;

      var tagCell = item.scheme === 'model'
        ? escapeHtml((imageModels(item, im) || []).map(function (x) {
            return x.name;
          }).filter(Boolean).join(' + ') || '-')
        : escapeHtml((item.annotation_tags || []).join(', ') || '-');

      tr.innerHTML =
        '<td class="table-idx">' + (idx + 1) + '</td>' +
        '<td>' + (cat ? '<span class="table-cat-badge">' + escapeHtml(cat.name) + '</span>' : '-') +
          (item.family ? ' <span class="lib-family-pill">' + escapeHtml(item.family) + '</span>' : '') + '</td>' +
        '<td><span class="table-char-badge">' + escapeHtml(item.character || '未命名') + '</span></td>' +
        '<td>' + tagCell + '</td>' +
        '<td><div class="table-prompt-box">' + escapeHtml(im.full_prompt || '') + '</div></td>' +
        '<td><div class="table-thumb-cell">' + (hasRasterThumb(im)
            ? '<img src="' + im.thumb_url + '" loading="lazy">'
            : (isVideoPath(im.path)
                ? '<video src="' + fullSrc(im) + '#t=0.1" preload="metadata" muted playsinline></video>'
                : (im.path ? '<img src="' + fullSrc(im) + '" loading="lazy">' : ''))) + '</div></td>' +
        '<td><div class="table-rec-text">' + escapeHtml(item.recommendation || '-') + '</div></td>' +
        '<td><div class="table-actions">' +
          '<button class="action-icon-btn ta-copy" title="复制 Prompt"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>' +
          '<button class="action-icon-btn ta-del" title="删除"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg></button>' +
        '</div></td>';

      tr.addEventListener('click', function (e) {
        if (e.target.closest('.table-thumb-cell')) { e.stopPropagation(); openLightbox(item, im); return; }
        if (e.target.closest('.ta-copy')) { e.stopPropagation(); copyText(im.full_prompt || '', '已复制'); return; }
        if (e.target.closest('.ta-del')) { e.stopPropagation(); deleteItemFlow(item.id); return; }
        selectItem(item.id);
      });
      frag.appendChild(tr);
    });
    body.appendChild(frag);
  }

  // ---------------- model folder tree ----------------

  function buildFolderTree() {
    var roots = [];
    (state.roots || []).forEach(function (root) {
      var base = String(root.path || '').replace(/\\/g, '/').replace(/\/+$/, '');
      if (!base) return;
      var node = { name: root.label || base.split('/').pop(), full: base, children: {}, count: 0 };
      state.models.forEach(function (m) {
        var p = String(m.path || '').replace(/\\/g, '/');
        if (p.toLowerCase().indexOf(base.toLowerCase()) !== 0) return;
        node.count++;
        var rel = p.slice(base.length).replace(/^\/+/, '');
        var parts = rel.split('/');
        parts.pop();                       // drop the file name
        var cursor = node;
        parts.forEach(function (part) {
          if (!cursor.children[part]) {
            cursor.children[part] = {
              name: part,
              full: cursor.full + '/' + part,
              children: {},
              count: 0
            };
          }
          cursor = cursor.children[part];
          cursor.count++;
        });
      });
      roots.push(node);
    });
    return roots;
  }

  function folderIconSvg(isOpen) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      (isOpen
        ? '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        : '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>') +
      '</svg>';
  }

  function samePath(a, b) {
    return String(a || '').replace(/\\/g, '/').toLowerCase() ===
           String(b || '').replace(/\\/g, '/').toLowerCase();
  }

  function renderFolderTree() {
    var box = $('folderTree');
    box.innerHTML = '';
    var roots = buildFolderTree();
    if (!roots.length) {
      box.innerHTML = '<div style="padding:10px 12px;font-size:11px;color:var(--text-muted)">还没有扫描目录</div>';
      return;
    }
    roots.forEach(function (r) { box.appendChild(renderTreeNode(r, 0)); });
  }

  function renderTreeNode(node, depth) {
    var wrap = document.createElement('div');
    var childKeys = Object.keys(node.children).sort(function (a, b) {
      return a.localeCompare(b, 'zh');
    });
    var isOpen = !state.folderCollapsed[node.full];
    var isActive = state.libFolder && samePath(state.libFolder, node.full);

    var row = document.createElement('div');
    row.className = 'ft-node' + (isActive ? ' active' : '');
    row.style.paddingLeft = (6 + depth * 12) + 'px';
    row.title = node.full + '（' + node.count + ' 个模型）';
    row.innerHTML =
      '<span class="ft-caret' + (childKeys.length ? (isOpen ? ' open' : '') : ' leaf') + '">' +
        '<svg viewBox="0 0 12 12"><path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>' +
      '</span>' +
      '<span class="ft-folder-ico">' + folderIconSvg(isOpen) + '</span>' +
      '<span class="ft-name">' + escapeHtml(node.name) + '</span>' +
      '<span class="ft-count">' + node.count + '</span>';

    row.addEventListener('click', function (e) {
      if (e.target.closest('.ft-caret') && childKeys.length) {
        state.folderCollapsed[node.full] = isOpen;
        renderFolderTree();
        return;
      }
      state.libFolder = isActive ? '' : node.full;   // click active folder clears it
      renderFolderTree();
      renderLibrary();
    });
    wrap.appendChild(row);

    if (childKeys.length) {
      var kids = document.createElement('div');
      kids.className = 'ft-children' + (isOpen ? '' : ' collapsed');
      childKeys.forEach(function (k) { kids.appendChild(renderTreeNode(node.children[k], depth + 1)); });
      wrap.appendChild(kids);
    }
    return wrap;
  }

  // ================= model library page =================

  function renderLibrary() {
    $('libScanHint').classList.toggle('hidden', !state.scanning);
    renderFolderTree();
    var grid = $('libGrid');
    grid.innerHTML = '';

    // roots row
    var roots = $('libRoots');
    roots.innerHTML = '';
    state.roots.forEach(function (r) {
      var chip = document.createElement('span');
      chip.className = 'lib-root-chip';
      chip.innerHTML = '📁 ' + escapeHtml(r.label) + ' · ' + escapeHtml(r.path) +
        '<button class="root-remove" title="移除该目录">×</button>';
      chip.querySelector('.root-remove').addEventListener('click', async function () {
        var ok = await ask('移除目录', '从模型库移除「' + r.path + '」？（不删除文件）', { danger: true, confirmText: '移除' });
        if (!ok) return;
        await api().remove_model_root(r.path);
        loadLibrary();
      });
      roots.appendChild(chip);
    });

    // base select options
    var bases = {};
    state.models.forEach(function (m) { if (m.base_model) bases[m.base_model] = (bases[m.base_model] || 0) + 1; });
    var sel = $('libBaseSelect');
    var current = sel.value || state.libBase;
    sel.innerHTML = '<option value="">全部大类</option>';
    Object.keys(bases).sort().forEach(function (b) {
      var o = document.createElement('option');
      o.value = b;
      o.textContent = b + ' (' + bases[b] + ')';
      if (b === current) o.selected = true;
      sel.appendChild(o);
    });
    state.libBase = current;

    var q = state.search.trim().toLowerCase();
    var folder = state.libFolder
      ? String(state.libFolder).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
      : '';
    var list = state.models.filter(function (m) {
      if (state.libType && m.type !== state.libType) return false;
      if (state.libBase && m.base_model !== state.libBase) return false;
      if (folder) {
        var mp = String(m.path || '').replace(/\\/g, '/').toLowerCase();
        if (mp.indexOf(folder + '/') !== 0) return false;
      }
      if (q && (m.name + ' ' + m.base_model + ' ' + m.version + ' ' + m.filename).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    list.sort(function (a, b) {
      return (a.base_model || '~').localeCompare(b.base_model || '~') ||
             (a.name || '').localeCompare(b.name || '');
    });

    var scopeBar = $('libScopeBar');
    if (state.libFolder) {
      scopeBar.hidden = false;
      scopeBar.innerHTML = '<span>当前目录：</span>' +
        '<span class="ft-scope-path" title="' + escapeHtml(state.libFolder) + '">' +
        escapeHtml(state.libFolder.replace(/\//g, '\\')) + '</span>' +
        '<span style="color:var(--text-muted)">' + list.length + ' 个模型</span>' +
        '<button id="btnClearFolder" title="清除目录筛选">&times;</button>';
      scopeBar.querySelector('#btnClearFolder').addEventListener('click', function () {
        state.libFolder = '';
        renderFolderTree();
        renderLibrary();
      });
    } else {
      scopeBar.hidden = true;
      scopeBar.innerHTML = '';
    }

    $('libEmpty').hidden = list.length > 0 || state.scanning;

    list.forEach(function (m) {
      var used = usedCount(m);
      var hashText = m.hash_status === 'hashing' ? '计算中'
        : m.hash_status === 'error' ? '失败'
        : m.sha256 ? '已哈希' : '未算哈希';
      var hashCls = m.hash_status === 'hashing' ? 'hashing'
        : m.hash_status === 'error' ? 'error'
        : m.sha256 ? 'done' : '';
      var typeText = m.type === 'checkpoint' ? 'Checkpoint'
        : m.type === 'lora' ? 'LoRA' : '未分类';
      var cover, coverCls = ' no-cover';
      if (m.preview_path) {
        cover = '<img src="/api/image?path=' + encodeURIComponent(m.preview_path) + '" loading="lazy">';
        coverCls = '';
      } else if (m.civitai && m.civitai.cover) {
        cover = '<img src="' + escapeHtml(m.civitai.cover) + '" loading="lazy" referrerpolicy="no-referrer">';
        coverCls = '';
      } else {
        cover = '<span class="cover-letter">' + escapeHtml((m.name || '?').charAt(0).toUpperCase()) + '</span>';
      }

      var node = document.createElement('div');
      node.className = 'lib-card';
      node.innerHTML =
        '<div class="lib-cover' + coverCls + '">' + cover +
          '<span class="lib-type-badge ' + escapeHtml(m.type) + '">' + typeText + '</span>' +
          '<span class="lib-hash-badge ' + hashCls + '">' + hashText + '</span>' +
        '</div>' +
        '<div class="lib-card-body">' +
          '<div class="lib-name" title="' + escapeHtml(m.name) + '">' + escapeHtml(m.name) + '</div>' +
          '<div class="lib-chips">' +
            (m.base_model
              ? '<span class="lib-chip-tag base">' + escapeHtml(m.base_model) + '</span>'
              : '<span class="lib-chip-tag">未设大类</span>') +
            (m.version ? '<span class="lib-chip-tag">' + escapeHtml(m.version) + '</span>' : '') +
            (m.civitai && m.civitai.trained_words
              ? '<span class="lib-chip-tag" title="' + escapeHtml(m.civitai.trained_words) + '">触发词</span>' : '') +
          '</div>' +
          '<div class="lib-filename">' + escapeHtml(m.filename || '手动登记') + '</div>' +
          '<div class="lib-used-count">用于 ' + used + ' 条注释</div>' +
        '</div>' +
        '<div class="lib-card-actions">' +
          '<button class="mini-btn act-sync" title="同步 Civitai 数据（缺哈希时自动计算）">同步</button>' +
          '<button class="mini-btn accent act-open" title="打开 Civitai">打开</button>' +
          '<button class="mini-btn act-edit" title="编辑名称/大类/微调">编辑</button>' +
          '<button class="mini-btn ghost act-del">删除</button>' +
        '</div>';

      node.querySelector('.act-sync').addEventListener('click', function () {
        syncOneModel(m.id);
      });
      node.querySelector('.act-open').addEventListener('click', function () {
        api().open_model_page(m.id).then(function (r) {
          if (!r.success) showToast(r.message, 'error');
        });
      });
      node.querySelector('.act-edit').addEventListener('click', function () { editModelFlow(m); });
      node.querySelector('.act-del').addEventListener('click', async function () {
        var ok = await ask('移除记录', '从模型库移除「' + m.name + '」？（不删除文件）', { danger: true, confirmText: '移除' });
        if (!ok) return;
        await api().delete_library_model(m.id);
        loadLibrary();
      });
      node.addEventListener('contextmenu', function (e) {
        e.preventDefault();
        var entries = [];
        entries.push({ label: '同步 Civitai 数据', fn: function () { syncOneModel(m.id); } });
        if (!m.sha256) entries.push({ label: '仅计算哈希', fn: function () {
          api().hash_model(m.id);
          showToast('已开始计算哈希…');
          pollLibrary();
        }});
        entries.push({ label: '打开 Civitai 页面', fn: function () {
          api().open_model_page(m.id);
        }});
        entries.push({ label: '编辑信息', fn: function () { editModelFlow(m); } });
        entries.push({ type: 'divider' });
        if (m.path) entries.push({ label: '定位文件', fn: function () { api().open_in_explorer(m.path); } });
        entries.push({ label: '删除记录', danger: true, fn: async function () {
          var ok = await ask('移除记录', '从模型库移除「' + m.name + '」？（不删除文件）', { danger: true, confirmText: '移除' });
          if (!ok) return;
          await api().delete_library_model(m.id);
          loadLibrary();
        }});
        showCtxMenu(e.clientX, e.clientY, entries);
      });

      grid.appendChild(node);
    });
  }

  async function syncOneModel(modelId) {
    var res = await api().sync_or_hash(modelId);
    if (res.success && res.queued) {
      showToast('正在计算哈希，完成后将自动同步 Civitai…');
      pollLibrary();
    } else if (res.success) {
      var mm = res.model || {};
      var nm = (mm.civitai && (mm.civitai.model_name || mm.civitai.version_name)) || mm.name || '模型';
      showToast('已同步：' + nm);
      loadLibrary();
    } else {
      showToast(res.message || '同步失败', 'error');
    }
  }

  async function editModelFlow(m) {
    var name = await ask('编辑模型', '显示名称：', { input: true, value: m.name });
    if (name === null) return;
    var base = await ask('编辑模型', '模型大类（如 Anima / SDXL / Pony）：', { input: true, value: m.base_model });
    if (base === null) return;
    var ver = await ask('编辑模型', '具体微调版本（可留空）：', { input: true, value: m.version });
    if (ver === null) return;
    var res = await api().update_library_model(m.id, {
      name: String(name).trim() || m.name,
      base_model: String(base).trim(),
      version: String(ver).trim()
    });
    if (res.success) { showToast('已更新'); loadLibrary(); }
  }

  async function addManualFlow() {
    var name = await ask('手动登记模型', '模型显示名称：', { input: true, placeholder: '如 miaomiaoHarem Anima v14' });
    if (name === null || !String(name).trim()) return;
    var type = await ask('手动登记模型', '类型（checkpoint / lora）：', { input: true, value: 'checkpoint' });
    if (type === null) return;
    var base = await ask('手动登记模型', '模型大类（可留空）：', { input: true, placeholder: '如 Anima' });
    if (base === null) return;
    var ver = await ask('手动登记模型', '具体微调版本（可留空）：', { input: true });
    if (ver === null) return;
    var res = await api().add_manual_model(String(name), String(type).trim().toLowerCase(),
      String(base).trim(), String(ver).trim());
    if (res.success) { showToast('已登记'); loadLibrary(); }
    else showToast(res.message, 'error');
  }

  async function addRootFlow() {
    var res = await api().add_model_root('');
    if (res.success) { showToast('已添加目录并开始扫描'); loadLibrary(); }
    else if (res.message && res.message.indexOf('取消') === -1) showToast(res.message, 'error');
  }

  var pollTimer = null;
  function pollLibrary() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async function () {
      if (!api()) return;
      var st = await api().get_library();
      state.models = st.models || [];
      state.roots = st.roots || [];
      state.families = st.families || [];
      state.scanning = !!st.scanning;
      renderLibrary();
      renderDatalist();
      renderFamilySelect();
      var busy = state.scanning || state.models.some(function (m) { return m.hash_status === 'hashing'; });
      if (busy && state.page === 'library') pollLibrary();
    }, 1500);
  }

  async function loadLibrary() {
    if (!api()) return;
    var st = await api().get_library();
    state.models = st.models || [];
    state.roots = st.roots || [];
    state.families = st.families || [];
    state.scanning = !!st.scanning;
    renderLibrary();
    renderDatalist();
    renderFamilySelect();
    var busy = state.scanning || state.models.some(function (m) { return m.hash_status === 'hashing'; });
    if (busy && state.page === 'library') pollLibrary();
  }


  // ---------------- right-click context menu ----------------

  function hideCtxMenu() {
    var m = $('ctxMenu');
    m.classList.remove('show');
    m.innerHTML = '';
  }
  function showCtxMenu(x, y, entries) {
    var m = $('ctxMenu');
    m.innerHTML = '';
    entries.forEach(function (en) {
      if (en.type === 'divider') {
        var d = document.createElement('div');
        d.className = 'dropdown-divider';
        m.appendChild(d);
        return;
      }
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ctx-item' + (en.danger ? ' danger' : '');
      b.textContent = en.label;
      b.addEventListener('click', function () { hideCtxMenu(); en.fn(); });
      m.appendChild(b);
    });
    m.style.left = Math.min(x, window.innerWidth - 190) + 'px';
    m.style.top = Math.min(y, window.innerHeight - 10 - entries.length * 34) + 'px';
    m.classList.add('show');
  }
  document.addEventListener('click', hideCtxMenu);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideCtxMenu(); });
  window.addEventListener('blur', hideCtxMenu);
  // ================= editor render & bindings =================

  function toggleInspector(force) {
    state.inspectorCollapsed = typeof force === 'boolean' ? force : !state.inspectorCollapsed;
    $('inspectorPanel').classList.toggle('collapsed', state.inspectorCollapsed);
    $('btnToggleInspector').classList.toggle('active-toggle', !state.inspectorCollapsed);
    applyColumns();
  }

  // Repaint only the selection highlight. A full render() rebuilds the whole
  // masonry (innerHTML = ''), which reset the scroll position — that is what
  // threw the view back to the top whenever a card was clicked.
  function syncSelectionUi() {
    Array.prototype.forEach.call(document.querySelectorAll('.gallery-card'), function (c) {
      c.classList.toggle('selected', c.dataset.id === state.selectedId);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.glass-table tbody tr'), function (r) {
      r.classList.toggle('selected', r.dataset.id === state.selectedId);
    });
  }

  function selectItem(id) {
    suggest.showAll = false;
    state.selectedId = id;
    var it = selected();
    state.selectedImageId = it && it.images && it.images.length ? it.images[0].id : null;

    // Expanding the inspector narrows the gallery, which re-flows the masonry and
    // makes the browser clamp the scroll offset (the "jump back to top" report).
    // Remember the position and restore it once the width transition has run.
    var vp = $('contentViewport');
    var keep = vp ? vp.scrollTop : 0;
    var wasCollapsed = state.inspectorCollapsed;
    if (wasCollapsed) toggleInspector(false);

    syncSelectionUi();
    renderEditor();

    if (vp && wasCollapsed) {
      vp.scrollTop = keep;
      setTimeout(function () { if (vp) vp.scrollTop = keep; }, 300);
      setTimeout(function () { if (vp) vp.scrollTop = keep; }, 620);
    }
  }

  function openLightbox(item, im) {
    if (!im) return;
    var img = $('lightboxImg');
    var vid = $('lightboxVideo');
    var src = fullSrc(im);

    if (isVideoPath(im.path)) {
      img.style.display = 'none';
      img.removeAttribute('src');
      vid.style.display = '';
      vid.src = src;
      vid.load();
      var p = vid.play();
      if (p && p.catch) p.catch(function () { /* autoplay blocked -> controls remain */ });
    } else {
      vid.pause();
      vid.style.display = 'none';
      vid.removeAttribute('src');
      vid.load();
      img.style.display = '';
      img.src = src;                 // resets animated GIF/WebP to frame 0
    }

    var kind = isVideoPath(im.path) ? '视频' : (isAnimatedPath(im.path) ? '动图' : '原图');
    $('lightboxTitle').textContent = (item.character || '未命名') + ' — ' + kind;
    $('lightboxPrompt').textContent = im.full_prompt || '';
    $('btnLightboxCopy').onclick = function () { copyText(im.full_prompt, '已复制'); };
    $('lightboxModal').classList.add('show');
  }
  function closeLightbox() {
    $('lightboxModal').classList.remove('show');
    var vid = $('lightboxVideo');
    if (vid) {
      try { vid.pause(); } catch (e) {}
      vid.removeAttribute('src');
      try { vid.load(); } catch (e) {}
    }
    var img = $('lightboxImg');
    if (img) img.removeAttribute('src');
  }

  function renderEditor() {
    var item = selected();
    if (!item) {
      $('noSelectionHint').style.display = 'flex';
      $('editorContent').hidden = true;
      $('editorFileMeta').textContent = '未选择条目';
      return;
    }
    $('noSelectionHint').style.display = 'none';
    $('editorContent').hidden = false;

    var im = selectedImage();
    $('fieldCharacter').value = item.character || '';

    var sel = $('fieldCategory');
    sel.innerHTML = '';
    state.categories.forEach(function (c) {
      var o = document.createElement('option');
      o.value = c.id; o.textContent = c.name;
      if (c.id === item.category_id) o.selected = true;
      sel.appendChild(o);
    });

    document.querySelectorAll('#schemeSwitch button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.scheme === (item.scheme || 'tags'));
    });
    $('schemeTags').hidden = item.scheme === 'model';
    $('schemeModel').hidden = item.scheme !== 'model';

    renderImageStrip(item);
    $('editorFileMeta').textContent =
      (im && im.path ? im.path.split(/[\\/]/).pop() : '未绑定图片') +
      (im && im.width ? ' · ' + im.width + '×' + im.height : '');
    $('imgCountHint').textContent = (item.images || []).length
      ? ('共 ' + item.images.length + ' 张，点击缩略图切换编辑') : '尚未添加图片';

    if (item.scheme !== 'model') {
      // Tag mode: per-image prompt, item-level (shared) models
      renderAnnotTags(item);
      $('fieldFullPrompt').value = (im && im.full_prompt) || '';
      $('imgStats').textContent = ((im && im.full_prompt) || '').length + ' 字符';
      renderLoraPills($('loraPills'), (im && im.full_prompt) || '');
      if (im && !im.residual_prompt && (item.annotation_tags || []).length) {
        im.residual_prompt = computeResidual(im.full_prompt, item.annotation_tags);
        scheduleSave();
      }
      $('fieldResidualPrompt').value = (im && im.residual_prompt) || '';
      renderModelList($('tagModelList'), item, im, 'item');
    } else {
      // Model mode: per-image models, item-level (shared) prompt
      renderModelList($('imgModelList'), item, im, 'image');
      $('fieldSharedPrompt').value = item.shared_prompt || '';
      $('fieldSharedStyle').value = item.shared_style || '';
      $('fieldSharedGeneric').value = item.shared_generic || '';
      renderLoraPills($('loraPillsShared'), item.shared_prompt || '');
    }

    $('fieldNegPrompt').value = item.negative_prompt || '';
    $('fieldRec').value = item.recommendation || '';
    renderFamilySelect();
    renderSlideshowBar();
  }

  // ---------------- slideshow bar (editor) ----------------

  function renderSlideshowBar() {
    var bar = $('ssModes');
    if (!bar) return;
    var item = selected();
    var ss = ssOf(item);
    var multi = !!(item && (item.images || []).length > 1);

    bar.querySelectorAll('button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.ss === (ss.mode || 'off'));
      b.disabled = !multi;
    });
    $('ssAuto').checked = !!ss.auto;
    $('ssAuto').disabled = !multi;
    $('ssInterval').value = String(ss.interval || 1500);
    $('ssInterval').disabled = !multi;
  }


  // ---------------- editor bindings (one place) ----------------

  function bindEditorEvents() {
    $('fieldCharacter').addEventListener('input', function () {
      var it = selected(); if (!it) return;
      it.character = this.value;
      // NOTE: .character-badge belongs to the *category*; the entry name lives
      // in .card-name. Writing into the badge renamed the category instead.
      refreshItemViews(it);
      scheduleSave();
    });
    $('fieldCategory').addEventListener('change', function () {
      var it = selected(); if (!it) return;
      it.category_id = this.value;
      scheduleSave();
      // the card belongs to another group now: re-render so it actually moves
      // (or disappears from the current filter), and refresh the counts
      render();
      showToast('已移动到「' + ((catById(this.value) || {}).name || '其它') + '」');
      renderCategories();
    });
    $('fieldFamily').addEventListener('change', function () {
      var it = selected(); if (!it) return;
      it.family = this.value;
      this.classList.toggle('is-empty', !this.value);
      scheduleSave();
      refreshItemViews(it);
      showToast(this.value ? ('已标记为大类：' + this.value) : '已清除大类标记');
    });

    document.querySelectorAll('#schemeSwitch button').forEach(function (b) {
      b.addEventListener('click', function () {
        var it = selected(); if (!it) return;
        it.scheme = b.dataset.scheme;
        scheduleSave(); render();
      });
    });

    $('btnAddImage').addEventListener('click', addImagesToEntryFlow);
    $('btnReplaceImage').addEventListener('click', replaceImageFlow);
    $('btnReparseImg').addEventListener('click', reparseImageFlow);
    $('btnPrimaryImage').addEventListener('click', setPrimaryImageFlow);
    $('btnRemoveImage').addEventListener('click', function () {
      var cur = selectedImage();
      if (cur) removeImageFlow(cur.id);
    });

    $('annotTagInput').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      var it = selected(); if (!it) return;
      var v = this.value.trim();
      if (!v) return;
      if (!it.annotation_tags) it.annotation_tags = [];
      if (it.annotation_tags.indexOf(v) === -1) it.annotation_tags.push(v);
      this.value = '';
      scheduleSave();
      renderEditor();
      refreshItemViews(it);
    });

    $('fieldFullPrompt').addEventListener('input', function () {
      var it = selected(), cur = selectedImage();
      if (!it || !cur) return;
      cur.full_prompt = this.value;
      $('imgStats').textContent = this.value.length + ' 字符';
      renderLoraPills($('loraPills'), this.value);
      scheduleSave();
    });
    $('btnFormatPrompt').addEventListener('click', function () {
      var cur = selectedImage(); if (!cur) return;
      cur.full_prompt = (cur.full_prompt || '').split(',')
        .map(function (s) { return s.trim(); }).filter(Boolean).join(',\n');
      $('fieldFullPrompt').value = cur.full_prompt;
      scheduleSave();
    });
    $('btnCompactPrompt').addEventListener('click', function () {
      var cur = selectedImage(); if (!cur) return;
      cur.full_prompt = (cur.full_prompt || '').split(/[\n\r]+/)
        .map(function (s) { return s.trim(); }).filter(Boolean).join(', ')
        .replace(/,\s*,/g, ',');
      $('fieldFullPrompt').value = cur.full_prompt;
      scheduleSave();
    });
    $('btnCopyPrompt').addEventListener('click', function () {
      copyText($('fieldFullPrompt').value, '已复制使用提示词');
    });
    $('btnRecalcResidual').addEventListener('click', function () {
      var it = selected(), cur = selectedImage();
      if (!it || !cur) return;
      cur.residual_prompt = computeResidual(cur.full_prompt, it.annotation_tags);
      $('fieldResidualPrompt').value = cur.residual_prompt;
      scheduleSave();
      showToast('已按标注 Tag 重算细分提示词');
    });
    $('fieldResidualPrompt').addEventListener('input', function () {
      var cur = selectedImage();
      if (cur) { cur.residual_prompt = this.value; scheduleSave(); }
    });

    // ---- shared prompt (Model mode: one prompt for the whole entry) ----
    $('fieldSharedPrompt').addEventListener('input', function () {
      var it = selected(); if (!it) return;
      it.shared_prompt = this.value;
      renderLoraPills($('loraPillsShared'), this.value);
      scheduleSave();
    });
    $('fieldSharedStyle').addEventListener('input', function () {
      var it = selected(); if (it) { it.shared_style = this.value; scheduleSave(); }
    });
    $('fieldSharedGeneric').addEventListener('input', function () {
      var it = selected(); if (it) { it.shared_generic = this.value; scheduleSave(); }
    });
    $('btnCopySharedPrompt').addEventListener('click', function () {
      copyText($('fieldSharedPrompt').value, '已复制共用提示词');
    });

    // ---- model list buttons ----
    $('btnAddTagModel').addEventListener('click', function () { addModelTo('item'); });
    $('btnAddImgModel').addEventListener('click', function () { addModelTo('image'); });
    document.addEventListener('click', function (e) {
      // clicks inside a model row or on the dropdown itself must not close it
      if (e.target.closest('.model-row') || e.target.closest('#modelSuggest')) return;
      hideModelSuggest();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideModelSuggest();
    });

    // ---- apply to every image ----
    $('btnApplyPromptAll').addEventListener('click', applyPromptToAll);
    $('btnApplyResidualAll').addEventListener('click', applyResidualToAll);

    // ---- slideshow controls ----
    function paintSs(item) {
      var ss = ssOf(item);
      var card = document.querySelector('.gallery-card[data-id="' + item.id + '"]');
      if (card) card.classList.toggle('ss-running', !!(ss.auto && ss.mode !== 'off'));
      renderSlideshowBar();
    }

    $('ssModes').addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn || btn.disabled) return;
      var it = selected(); if (!it) return;
      var ss = ssOf(it);
      ss.touched = true;                       // explicit choice, keep it
      ss.mode = btn.dataset.ss;
      if (ss.mode === 'off') {
        ss.auto = false;
        stopSlideshow(it.id);
      } else {
        ss.auto = true;                        // picking an order implies playing
        startSlideshow(it);
      }
      scheduleSave();
      paintSs(it);
      showToast('幻灯片：' + ({ off: '已停止', seq: '顺序循环', rev: '倒序循环',
                                shuffle: '随机循环' }[ss.mode]));
    });

    $('ssAuto').addEventListener('change', function () {
      var it = selected(); if (!it) return;
      var ss = ssOf(it);
      ss.touched = true;
      ss.auto = this.checked;
      if (this.checked && ss.mode === 'off') ss.mode = 'seq';
      scheduleSave();
      if (this.checked) startSlideshow(it); else stopSlideshow(it.id);
      paintSs(it);
    });

    $('ssInterval').addEventListener('change', function () {
      var it = selected(); if (!it) return;
      var ss = ssOf(it);
      ss.touched = true;
      ss.interval = parseInt(this.value, 10) || 1500;
      scheduleSave();
      if (ss.auto) startSlideshow(it);
    });

    $('fieldNegPrompt').addEventListener('input', function () {
      var it = selected(); if (it) { it.negative_prompt = this.value; scheduleSave(); }
    });
    $('fieldRec').addEventListener('input', function () {
      var it = selected(); if (!it) return;
      it.recommendation = this.value;
      refreshItemViews(it);          // the card shows it as the remark line
      scheduleSave();
    });
    $('btnCopyRec').addEventListener('click', function () { copyText($('fieldRec').value, '已复制'); });

    $('btnDeleteCurrent').addEventListener('click', function () {
      if (state.selectedId) deleteItemFlow(state.selectedId);
    });
    $('btnLocateFile').addEventListener('click', async function () {
      var cur = selectedImage();
      if (!cur || !cur.path) { showToast('该图未绑定原图', 'error'); return; }
      await api().open_in_explorer(cur.path);
    });

    $('btnCloseInspector').addEventListener('click', function () { toggleInspector(true); });
    $('btnToggleInspector').addEventListener('click', function () { toggleInspector(); });

    document.querySelectorAll('#schemeSwitch button').forEach(function (b) {
      b.addEventListener('click', function () {
        var it = selected(); if (!it) return;
        it.scheme = b.dataset.scheme;
        scheduleSave(); render();
      });
    });
  }

  // ---------------- page switch ----------------

  function setPage(page) {
    if (page === state.page) return;
    // independent search per page: stash current, load target page's query
    state.searchBy[state.page] = $('searchInput').value;
    state.page = page;
    state.search = state.searchBy[page] || '';
    $('searchInput').value = state.search;
    $('clearSearchBtn').style.display = state.search ? 'block' : 'none';
    document.body.dataset.page = page;
    $('tabGallery').classList.toggle('active', page === 'gallery');
    $('tabLibrary').classList.toggle('active', page === 'library');
    $('galleryPage').hidden = page !== 'gallery';
    $('libraryPage').hidden = page !== 'library';
    $('folderSection').hidden = page !== 'library';
    $('libraryControls').classList.toggle('hidden', page !== 'library');
    $('searchInput').placeholder = page === 'library'
      ? '搜索模型名称 / 大类…' : '搜索人物、Prompt 标签或备注…';
    // the model library needs the full width: collapse the editor there and
    // bring it back when returning to the gallery
    toggleInspector(page === 'library');
    if (page === 'library') { loadLibrary(); refreshFamilies(); }
    else render();
  }

  // ---------------- main event wiring ----------------

  function bindEvents() {
    setupAsk();
    bindWindowChrome();
    bindEditorEvents();

    $('searchInput').addEventListener('input', function (e) {
      state.search = e.target.value;
      state.searchBy[state.page] = state.search;
      $('clearSearchBtn').style.display = state.search ? 'block' : 'none';
      if (state.page === 'library') renderLibrary(); else render();
    });
    $('clearSearchBtn').addEventListener('click', function () {
      $('searchInput').value = '';
      state.search = '';
      state.searchBy[state.page] = '';
      $('clearSearchBtn').style.display = 'none';
      if (state.page === 'library') renderLibrary(); else render();
    });

    $('tabGallery').addEventListener('click', function () { setPage('gallery'); });
    $('tabLibrary').addEventListener('click', function () { setPage('library'); });

    $('btnViewMasonry').addEventListener('click', function () {
      state.view = 'masonry';
      $('btnViewMasonry').classList.add('active');
      $('btnViewTable').classList.remove('active');
      $('columnsSliderWrap').style.display = 'flex';
      render();
    });
    $('btnViewTable').addEventListener('click', function () {
      state.view = 'table';
      $('btnViewTable').classList.add('active');
      $('btnViewMasonry').classList.remove('active');
      $('columnsSliderWrap').style.display = 'none';
      render();
    });
    $('columnsRange').addEventListener('input', function (e) {
      state.columns = parseInt(e.target.value, 10);
      applyColumns();
    });

    // keep the effective column count honest while the window/panels resize
    var colTimer = null;
    window.addEventListener('resize', function () {
      clearTimeout(colTimer);
      colTimer = setTimeout(applyColumns, 120);
    });

    $('btnImportImages').addEventListener('click', importImagesFlow);
    $('btnEmptyImport').addEventListener('click', importImagesFlow);
    $('btnExportExcel').addEventListener('click', exportExcelFlow);
    $('btnImportExcel').addEventListener('click', importExcelFlow);
    $('btnAddEmptyItem').addEventListener('click', addBlankFlow);
    $('btnAddItemToScope').addEventListener('click', addBlankFlow);
    $('btnClearAll').addEventListener('click', clearAllFlow);
    var purgeBtn = $('btnPurgeEmpty');
    if (purgeBtn) purgeBtn.addEventListener('click', function () { purgeEmptyEntries(false); });

    var tagFullBtn = $('btnToggleTagFull');
    if (tagFullBtn) {
      tagFullBtn.addEventListener('click', function () {
        saveSetting('cardTagFull', !uiSettings.cardTagFull);
        showToast(uiSettings.cardTagFull ? '卡片显示完整标注 Tag' : '卡片标注 Tag 已收窄');
      });
    }

    var collapseBtn = $('btnCollapseSidebar');
    if (collapseBtn) collapseBtn.addEventListener('click', function () { toggleSidebar(true); });
    var expandBtn = $('btnExpandSidebar');
    if (expandBtn) expandBtn.addEventListener('click', function () { toggleSidebar(false); });
    $('btnAddCategory').addEventListener('click', addCategoryFlow);

    $('btnMoreMenu').addEventListener('click', function (e) {
      e.stopPropagation();
      $('moreDropdown').classList.toggle('show');
    });
    document.addEventListener('click', function () { $('moreDropdown').classList.remove('show'); });
    $('moreDropdown').addEventListener('click', function (e) { e.stopPropagation(); });

    // library toolbar
    $('btnRescan').addEventListener('click', function () {
      api().rescan_models();
      showToast('开始扫描模型目录…');
      pollLibrary();
    });
    $('btnAddRoot').addEventListener('click', addRootFlow);
    $('btnHashAll').addEventListener('click', function () {
      api().sync_all_models().then(function (res) {
        showToast('一键同步：哈希 ' + res.hash_queued + ' 个、直同步 ' + res.sync_queued + ' 个');
        pollLibrary();
      });
    });
    $('btnAddManual').addEventListener('click', addManualFlow);
    $('btnCollapseTree').addEventListener('click', function () {
      var expandedCount = 0;
      (function countOpen(nodes) {
        nodes.forEach(function (n) {
          if (Object.keys(n.children).length) {
            if (!state.folderCollapsed[n.full]) expandedCount++;
            countOpen(Object.keys(n.children).map(function (k) { return n.children[k]; }));
          }
        });
      })(buildFolderTree());
      state.folderCollapsed = {};
      if (expandedCount > 0) {
        (function collapseAll(nodes) {
          nodes.forEach(function (n) {
            if (Object.keys(n.children).length) {
              state.folderCollapsed[n.full] = true;
              collapseAll(Object.keys(n.children).map(function (k) { return n.children[k]; }));
            }
          });
        })(buildFolderTree());
      }
      renderFolderTree();
    });
    $('libBaseSelect').addEventListener('change', function (e) {
      state.libBase = e.target.value;
      renderLibrary();
    });
    document.querySelectorAll('.lib-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        state.libType = chip.dataset.type;
        document.querySelectorAll('.lib-chip').forEach(function (c) {
          c.classList.toggle('active', c === chip);
        });
        renderLibrary();
      });
    });

    // lightbox
    $('lightboxCloseBtn').addEventListener('click', closeLightbox);
    $('lightboxBackdrop').addEventListener('click', closeLightbox);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && $('lightboxModal').classList.contains('show')) closeLightbox();
    });

    // drag & drop import
    window.addEventListener('dragenter', function (e) {
      e.preventDefault();
      if (state.page !== 'gallery') return;
      var cat = catById(state.activeCategory);
      $('dragScopeHint').textContent = state.activeCategory === 'all'
        ? '将存入第一个分区，并自动解析内嵌 Prompt 元数据'
        : '将存入「' + (cat ? cat.name : '') + '」分区';
      $('dragDropOverlay').classList.add('show');
    });
    $('dragDropOverlay').addEventListener('dragover', function (e) { e.preventDefault(); });
    $('dragDropOverlay').addEventListener('dragleave', function (e) {
      if (!e.relatedTarget) $('dragDropOverlay').classList.remove('show');
    });
    $('dragDropOverlay').addEventListener('drop', async function (e) {
      e.preventDefault();
      $('dragDropOverlay').classList.remove('show');
      var files = Array.from(e.dataTransfer.files || []);
      var paths = files.map(function (f) { return f.path; }).filter(Boolean);
      if (!paths.length) {
        showToast('浏览器沙箱未提供文件路径，请使用「导入图片」按钮', 'error');
        return;
      }
      var catId = state.activeCategory === 'all'
        ? (state.categories[0] ? state.categories[0].id : '') : state.activeCategory;
      await api().import_image_paths(paths, catId);
      await refreshState();
      showToast('导入完成');
    });
    window.addEventListener('dragover', function (e) { e.preventDefault(); });
  }

  function bindWindowChrome() {
    $('btnWinMin').addEventListener('click', function () { api() && api().win32('min'); });
    $('btnWinMax').addEventListener('click', async function () {
      var isMax = await api().win32('max_toggle');
      document.body.classList.toggle('maximized', !!isMax);
    });
    $('btnWinClose').addEventListener('click', function () { api() && api().win32('close'); });

    // window dragging: custom Win32 bridge (pywebview's own drag region is
    // broken on Windows, so window-drag.js drives drag_begin/move/end)
    if (window.PTWindowDrag) window.PTWindowDrag.attach($('tbDrag'));

    // frameless resizing: no sizing border exists, so drive our own Win32
    // gesture (edge_begin / edge_move / edge_end) instead of WM_NCLBUTTONDOWN
    document.querySelectorAll('.resize-strip').forEach(function (strip) {
      if (window.PTWindowDrag) window.PTWindowDrag.attachResize(strip);
    });
    window.addEventListener('focus', function () {
      api() && api().win32('is_max').then(function (isMax) {
        document.body.classList.toggle('maximized', !!isMax);
      });
    });
  }

  // ---------------- flows ----------------

  async function importImagesFlow() {
    if (!api()) { showToast('接口初始化中…', 'error'); return; }
    var paths = await api().pick_images();
    if (!paths || !paths.length) return;
    showToast('正在解析 ' + paths.length + ' 张图片…');
    var catId = state.activeCategory === 'all'
      ? (state.categories[0] ? state.categories[0].id : '') : state.activeCategory;
    var added = await api().import_image_paths(paths, catId);
    await refreshState();
    showToast('成功导入 ' + (added ? added.length : 0) + ' 张');
  }

  async function exportExcelFlow() {
    if (!api()) return;
    showToast('正在生成 Excel…');
    var res = await api().export_excel(state.activeCategory === 'all' ? '' : state.activeCategory);
    if (res.success) showToast(res.message || '导出成功');
    else if (res.message !== '已取消保存') showToast(res.message, 'error');
  }

  async function importExcelFlow() {
    if (!api()) return;
    showToast('正在导入…');
    var res = await api().import_excel(state.activeCategory === 'all' ? '' : state.activeCategory);
    if (res.success) {
      state.items = res.items || [];
      state.categories = res.categories || state.categories;
      render();
      showToast(res.message || '导入成功');
    } else if (res.message !== '已取消选择') showToast(res.message, 'error');
  }

  // ---------------- init ----------------

  function boot() {
    if (!api()) return false;
    loadSettings();
    refreshState();
    loadLibrary();
    refreshFamilies();
    return true;
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindEvents();
    render();

    window.addEventListener('pywebviewready', function () {
      loadSettings();
      refreshState();
      loadLibrary();
      api().win32('is_max').then(function (isMax) {
        document.body.classList.toggle('maximized', !!isMax);
      });
    });
    if (!boot()) {
      var tries = 0;
      var timer = setInterval(function () {
        if (boot() || ++tries > 40) clearInterval(timer);
      }, 250);
    }
  });
})();