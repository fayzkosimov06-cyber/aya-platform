(() => {
  const menus = [...document.querySelectorAll('.pv2-account-menu')];
  document.addEventListener('click', event => {
    for (const menu of menus) if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    for (const menu of menus) if (menu.open) {
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
  const links = [...document.querySelectorAll('.pv2-nav a[href^="#"]')];
  if (!links.length) return;
  const activate = id => {
    for (const link of links) {
      if (link.hash === id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  };
  const selectHash = () => {
    if (links.some(link => link.hash === location.hash)) activate(location.hash);
  };
  for (const link of links) link.addEventListener('click', () => activate(link.hash));
  window.addEventListener('hashchange', selectHash);
  selectHash();
})();
