/**
 * Window dragging and resizing for frameless Mikage PromptTable windows.
 *
 * pywebview's built-in .pywebview-drag-region helper is broken on Windows (its
 * move() raises a TypeError), and a frameless window has no sizing border, so
 * WM_NCLBUTTONDOWN with HT* codes does nothing. Both gestures are driven
 * through the app's own Win32 bridge with SetWindowPos:
 *   drag  : drag / drag_move / drag_end
 *   resize: edge_begin(<edge>) / edge_move / edge_end
 *
 * A single state machine owns both gestures so the pointer-up / blur handlers
 * can never leave a stale "in progress" flag behind.
 *
 * Movement is driven by mousemove rather than requestAnimationFrame: rAF is
 * throttled whenever the window loses focus or is occluded, which is exactly
 * what happens while dragging a window around.
 */
(function () {
  'use strict';

  function api() { return window.pywebview && window.pywebview.api; }
  function win32(action, arg) {
    var a = api();
    if (a && a.win32) return a.win32(action, arg);
    return Promise.resolve(false);
  }

  var MIN_INTERVAL = 8;                 // ms between IPC sends
  var active = null;                    // {kind:'drag'|'resize', lastSent:number}
  var lastSent = 0;

  function begin(kind, ev, edge) {
    if (ev.button !== 0) return false;
    if (ev.target.closest('button, input, select, a, textarea, video')) return false;
    if (active) return false;
    ev.preventDefault();
    active = { kind: kind, edge: edge || '' };
    lastSent = 0;
    document.body.classList.add(kind === 'drag' ? 'dragging' : 'resizing');
    if (kind === 'drag') win32('drag');
    else win32('edge_begin', edge);
    return true;
  }

  function move() {
    if (!active) return;
    var now = Date.now();
    if (now - lastSent < MIN_INTERVAL) return;
    lastSent = now;
    win32(active.kind === 'drag' ? 'drag_move' : 'edge_move');
  }

  function end() {
    if (!active) return;
    var kind = active.kind;
    active = null;
    document.body.classList.remove('dragging', 'resizing');
    win32(kind === 'drag' ? 'drag_end' : 'edge_end');
  }

  function attachDrag(handle) {
    if (!handle) return;
    handle.addEventListener('mousedown', function (e) { begin('drag', e); });
    handle.addEventListener('dblclick', function (e) {
      if (e.target.closest('button, input, select, a, textarea, video')) return;
      win32('max_toggle').then(function (isMax) {
        document.body.classList.toggle('maximized', !!isMax);
      });
    });
  }

  function attachResize(strip) {
    if (!strip || !strip.dataset) return;
    strip.addEventListener('mousedown', function (e) {
      begin('resize', e, strip.dataset.edge);
    });
  }

  window.addEventListener('mousemove', move, { passive: true });
  window.addEventListener('mouseup', end);
  window.addEventListener('blur', end);
  // a resize gesture that loses the cursor must not stick either
  document.addEventListener('mouseleave', function () { /* keep going; mouseup ends it */ });

  window.PTWindowDrag = {
    attach: attachDrag,
    attachResize: attachResize,
    isActive: function () { return !!active; }
  };
})();
