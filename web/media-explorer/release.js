// Never replace an active page or discard unsaved work automatically.
(() => {
  const current = document.querySelector('meta[name="panther-release"]')?.content;
  if (!current) return;
  let checking = false, notified = false;
  async function check() {
    if (checking || notified || document.hidden) return;
    checking = true;
    try {
      const response = await fetch('/release.json', { cache: 'no-store', signal: AbortSignal.timeout(10000) });
      if (!response.ok) return;
      const { version } = await response.json();
      if (!/^[a-f0-9]{64}$/.test(version) || version === current) return;
      const notice = document.createElement('aside');
      notice.className = 'release-notice';
      notice.setAttribute('role', 'status');
      const text = document.createElement('span');
      text.textContent = 'A Panther update is available. Save any unfinished edits before reloading.';
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'quiet-button'; button.textContent = 'Reload Panther';
      button.addEventListener('click', () => location.reload());
      notice.append(text, button); document.body.prepend(notice);
      notified = true;
    } catch { /* Offline or unavailable update checks must not interrupt the app. */ }
    finally { checking = false; }
  }
  setInterval(check, 60000);
  document.addEventListener('visibilitychange', check);
  window.addEventListener('focus', check);
  check();
})();
