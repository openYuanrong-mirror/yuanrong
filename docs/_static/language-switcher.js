function initLanguageSwitcher() {
  var buttons = document.querySelectorAll('#language-switcher-button');
  var dropdownMenus = document.querySelectorAll('#language-dropdown-menu');
  var switchLinksEn = document.querySelectorAll('#switch-to-en');
  var switchLinksZh = document.querySelectorAll('#switch-to-zh');

  var isChinese = window.location.pathname.indexOf('/zh-cn') !== -1 ||
                  document.querySelector('#switch-to-en') !== null;

  var allSwitchLinks = Array.from(switchLinksEn).concat(Array.from(switchLinksZh));
  allSwitchLinks.forEach(function(switchLink) {
    var currentPath = window.location.pathname;
    var newPath = isChinese ? currentPath.replace('/zh-cn', '/en') : currentPath.replace('/en', '/zh-cn');
    var targetUrl = window.location.origin + newPath + window.location.search + window.location.hash;
    switchLink.href = targetUrl;
    switchLink.setAttribute('data-target-url', targetUrl);

    switchLink.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      window.location.assign(this.getAttribute('data-target-url') || this.href);
      return false;
    });
  });

  buttons.forEach(function(button, index) {
    var dropdownMenu = dropdownMenus[index];
    if (!dropdownMenu) return;

    button.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();

      if (dropdownMenu.style.display === 'none' || dropdownMenu.style.display === '') {
        var rect = button.getBoundingClientRect();
        dropdownMenu.style.display = 'block';
        dropdownMenu.style.position = 'fixed';
        dropdownMenu.style.top = (rect.bottom + 4) + 'px';
        dropdownMenu.style.left = rect.left + 'px';
        dropdownMenu.style.right = 'auto';
        dropdownMenu.style.zIndex = '99999';
        dropdownMenu.style.minWidth = rect.width + 'px';
      } else {
        dropdownMenu.style.display = 'none';
      }
    });
  });

  document.addEventListener('click', function(e) {
    dropdownMenus.forEach(function(dropdownMenu) {
      var button = dropdownMenu.previousElementSibling;
      if (!dropdownMenu.contains(e.target) && e.target !== button) {
        dropdownMenu.style.display = 'none';
      }
    });
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initLanguageSwitcher);
} else {
  initLanguageSwitcher();
}
