/* Shared keyboard, credential and navigation affordances. */
(() => {
  document.querySelectorAll('.login-form input[type="password"]').forEach(input => {
    const wrap = document.createElement('div'); wrap.className = 'password-control';
    input.replaceWith(wrap); wrap.append(input);
    const toggle = document.createElement('button'); toggle.type = 'button';
    toggle.className = 'password-toggle'; toggle.textContent = 'Show'; toggle.setAttribute('aria-pressed', 'false');
    toggle.setAttribute('aria-label', 'Show ' + (input.name === 'pin' ? 'PIN' : 'password'));
    toggle.onclick = () => {
      const visible = input.type === 'password'; input.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? 'Hide' : 'Show'; toggle.setAttribute('aria-pressed', String(visible));
      toggle.setAttribute('aria-label', (visible ? 'Hide ' : 'Show ') + (input.name === 'pin' ? 'PIN' : 'password'));
    };
    wrap.append(toggle);
  });
  document.querySelectorAll('.login-form').forEach(form => form.addEventListener('submit', () => {
    const button = form.querySelector('[type="submit"]'); button.disabled = true; button.textContent = 'Signing in…';
  }));
  window.addEventListener('pageshow', () => document.querySelectorAll('.login-form [type="submit"]').forEach(button => {
    if (button.disabled) { button.disabled = false; button.textContent = document.body.classList.contains('team-login-page') ? 'Enter the quest' : 'Sign in'; }
  }));
  const menu = document.getElementById('menu-toggle'), sidebar = document.getElementById('sidebar');
  if (menu && sidebar) {
    const shade = document.createElement('button'); shade.className = 'navigation-shade'; shade.setAttribute('aria-label', 'Close navigation'); shade.hidden = true; document.body.append(shade);
    const close = () => { sidebar.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); shade.hidden = true; };
    new MutationObserver(() => { const open = sidebar.classList.contains('open'); menu.setAttribute('aria-expanded', String(open)); shade.hidden = !open; }).observe(sidebar, {attributes:true, attributeFilter:['class']});
    shade.onclick = close;
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && sidebar.classList.contains('open')) { close(); menu.focus(); } });
  }
})();
