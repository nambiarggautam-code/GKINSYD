// Optional progressive enhancement only. The site works fully without JavaScript.
(function () {
  // Remember the last memory visited so the homepage can gently highlight it.
  try {
    var page = document.body.getAttribute('data-slug');
    if (page) { localStorage.setItem('oss:last', page); }
    var last = localStorage.getItem('oss:last');
    if (!page && last) {
      var el = document.querySelector('[data-place="' + last + '"]');
      if (el) { el.setAttribute('aria-current', 'true'); el.querySelector('.place-mark').textContent = '\u2665'; }
    }
  } catch (e) { /* storage blocked (private mode): ignore */ }
})();
