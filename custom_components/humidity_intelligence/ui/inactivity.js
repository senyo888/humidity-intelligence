/* Self-contained inactivity custody for HI-owned details; no runtime writes. */
function hiDialogInactivity(dialog, owner, close, connection) {
  const idleMs = 120000;
  const activity = ['pointerdown', 'touchstart', 'touchmove', 'keydown', 'input', 'wheel', 'scroll'];
  const navigation = ['location-changed', 'popstate', 'pagehide'];
  let timer, generation = 0, disposed = false, lastIntent = -Infinity;
  const observer = new MutationObserver(() => {
    if (!owner.isConnected || !dialog.isConnected) finish();
  });
  function dispose() {
    if (disposed) return;
    disposed = true; generation++; clearTimeout(timer);
    observer.disconnect();
    for (const name of activity) dialog.removeEventListener(name, interact, true);
    for (const name of navigation) window.removeEventListener(name, finish);
    connection?.removeEventListener?.('disconnected', finish);
    dialog.removeEventListener('close', dispose);
  }
  function finish() {
    if (disposed) return;
    dispose(); close();
  }
  function arm() {
    if (disposed) return;
    clearTimeout(timer); const current = ++generation;
    timer = setTimeout(() => {
      if (!disposed && current === generation) finish();
    }, idleMs);
  }
  function interact(event) {
    // Programmatic clicks/keyboard dispatch and telemetry never extend custody.
    if (event.isTrusted !== true) return;
    // Browser-generated scroll can follow programmatic focus/telemetry changes.
    // Only count it in the wake of actual input within this panel.
    if (event.type === 'scroll') {
      if (Date.now() - lastIntent <= 1000) arm();
    } else {
      lastIntent = Date.now(); arm();
    }
  }
  for (const name of activity) dialog.addEventListener(name, interact, {capture:true, passive:name !== 'keydown'});
  for (const name of navigation) window.addEventListener(name, finish);
  connection?.addEventListener?.('disconnected', finish);
  dialog.addEventListener('close', dispose);
  let root = owner.getRootNode();
  while (root) {
    observer.observe(root, {childList:true, subtree:true});
    root = root.host ? root.host.getRootNode() : null;
  }
  arm();
  if (connection?.connected === false) finish();
  return dispose;
}
