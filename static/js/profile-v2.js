(() => {
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
