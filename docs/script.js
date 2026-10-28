(() => {
  'use strict';
  const root = document.documentElement;
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const themeButton = document.querySelector('.theme-toggle');
  let manualTheme = root.dataset.theme || null;
  function updateThemeButton() {
    const dark = manualTheme ? manualTheme === 'dark' : systemTheme.matches;
    themeButton.setAttribute('aria-pressed', String(dark));
    themeButton.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
    themeButton.title = `Switch to ${dark ? 'light' : 'dark'} theme (Shift-click to follow system)`;
    document.querySelector('meta[name="theme-color"]').content = dark ? '#0a0a0b' : '#fbfbfd';
  }
  themeButton.hidden = false;
  updateThemeButton();
  themeButton.addEventListener('click', (event) => {
    if (event.shiftKey) {
      manualTheme = null;
      delete root.dataset.theme;
      try { localStorage.removeItem('euc2k-theme'); } catch (_) { /* Private mode may block storage. */ }
    } else {
      const dark = manualTheme ? manualTheme === 'dark' : systemTheme.matches;
      manualTheme = dark ? 'light' : 'dark';
      root.dataset.theme = manualTheme;
      try { localStorage.setItem('euc2k-theme', manualTheme); } catch (_) { /* The toggle still works. */ }
    }
    updateThemeButton();
  });
  systemTheme.addEventListener('change', updateThemeButton);

  const tabs = [...document.querySelectorAll('[data-os]')];
  const tablist = document.querySelector('.os-tabs');
  tablist.setAttribute('role', 'tablist');
  function selectTab(tab, focus = false) {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.classList.toggle('active', selected);
      item.setAttribute('role', 'tab');
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(item.getAttribute('aria-controls'));
      panel.hidden = !selected;
      panel.setAttribute('role', 'tabpanel');
      panel.tabIndex = 0;
    });
    document.getElementById('shell-label').textContent = tab.dataset.os === 'windows' ? 'CMD' : 'SHELL';
    if (focus) tab.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', (event) => {
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = tabs[(index + 1) % tabs.length];
      if (event.key === 'Home') next = tabs[0];
      if (event.key === 'End') next = tabs[tabs.length - 1];
      if (next) { event.preventDefault(); selectTab(next, true); }
    });
  });
  selectTab(tabs[0]);

  const copyStatus = document.getElementById('copy-status');
  let toastTimer;
  function notify(message) {
    clearTimeout(toastTimer);
    copyStatus.textContent = message;
    copyStatus.classList.add('active');
    toastTimer = setTimeout(() => copyStatus.classList.remove('active'), 2300);
  }
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) { /* Try a local fallback. */ }
    }
    const field = document.createElement('textarea');
    const focused = document.activeElement;
    field.value = text;
    field.setAttribute('readonly', '');
    field.style.cssText = 'position:fixed;top:0;left:-9999px';
    document.body.append(field);
    field.select();
    let success = false;
    try { success = document.execCommand('copy'); } catch (_) { /* Show an honest failure below. */ }
    field.remove();
    if (focused instanceof HTMLElement) focused.focus({ preventScroll: true });
    return success;
  }
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', async () => {
      const success = await copyText(document.getElementById(button.dataset.copy).textContent.trim());
      notify(success ? 'Copied to clipboard' : 'Copy unavailable. Select the command and copy it manually.');
      if (success) {
        const use = button.querySelector('use');
        use.setAttribute('href', '#i-check');
        const label = button.querySelector('span');
        if (label) label.textContent = 'Copied';
        setTimeout(() => { use.setAttribute('href', '#i-copy'); if (label) label.textContent = 'Copy'; }, 1800);
      }
    });
  });

  let revealObserver;
  if ('IntersectionObserver' in window && !reducedMotion.matches) {
    revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.06 });
    // Measure together before adding classes, to avoid repeated layout work.
    const initialReveals = [...document.querySelectorAll('.reveal')].map(element => ({
      element, inView: element.getBoundingClientRect().top < innerHeight
    }));
    initialReveals.forEach(({ element, inView }) => {
      if (inView) element.classList.add('visible');
      else { element.classList.add('reveal-pending'); revealObserver.observe(element); }
    });
  }

  const terminal = document.querySelector('.terminal');
  const typed = document.getElementById('typed-command');
  const cursor = document.querySelector('.terminal-cursor');
  const command = typed.textContent;
  const lines = [...document.querySelectorAll('.output-line')];
  let animationToken = 0;
  const timers = new Set();
  function pause(ms) { return new Promise(resolve => { const id = setTimeout(() => { timers.delete(id); resolve(); }, ms); timers.add(id); }); }
  function showTerminal() {
    animationToken++;
    timers.forEach(clearTimeout);
    timers.clear();
    typed.textContent = command;
    lines.forEach(line => line.classList.add('shown'));
    terminal.classList.remove('animating');
    cursor.classList.remove('typing');
    cursor.classList.add('finished');
  }
  async function animateTerminal() {
    const token = ++animationToken;
    terminal.classList.add('animating');
    typed.textContent = '';
    cursor.classList.add('typing');
    await pause(300);
    for (let i = 1; i <= command.length; i += 2) {
      if (token !== animationToken || reducedMotion.matches) return;
      typed.textContent = command.slice(0, Math.min(i + 1, command.length));
      await pause(23);
    }
    for (const line of lines) {
      await pause(230);
      if (token !== animationToken || reducedMotion.matches) return;
      line.classList.add('shown');
    }
    cursor.classList.remove('typing');
    cursor.classList.add('finished');
  }
  if (reducedMotion.matches) showTerminal();
  else animateTerminal();
  reducedMotion.addEventListener('change', () => {
    if (reducedMotion.matches) {
      showTerminal();
      if (revealObserver) revealObserver.disconnect();
      document.querySelectorAll('.reveal-pending').forEach(element => element.classList.add('visible'));
    }
  });
})();
