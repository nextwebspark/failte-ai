/**
 * Compatibility shim for a pre-rename widget filename (dograh-widget.js).
 *
 * The real widget now ships as fallcha-widget.js. Snippets pasted onto customer
 * sites before the rename still request THIS path, so it must keep working
 * indefinitely: it re-injects the real widget with the same query string and
 * data-* attributes, then re-fires `load` on the legacy tag so host pages that
 * wait for it (the documented headless bootstrap) still see the widget ready.
 *
 * Do not add behaviour here. All widget logic lives in fallcha-widget.js.
 */

(function () {
  'use strict';

  var legacy =
    document.currentScript ||
    document.querySelector('script[src*="dograh-widget.js"]');
  if (!legacy) return;

  if (window.FallchaWidget || document.querySelector('script[src*="fallcha-widget.js"]')) {
    return;
  }

  var src;
  try {
    src = new URL(legacy.src, window.location.href);
  } catch {
    console.error('Fallcha.ai Widget: could not resolve the legacy script URL');
    return;
  }
  src.pathname = src.pathname.replace(/dograh-widget\.js$/, 'fallcha-widget.js');

  var script = document.createElement('script');
  script.src = src.toString();
  script.async = true;

  // Carry over every data-* attribute (data-dograh-context in old snippets);
  // the widget reads them off the script tag it was loaded from.
  for (var i = 0; i < legacy.attributes.length; i++) {
    var attr = legacy.attributes[i];
    if (attr.name.indexOf('data-') === 0) {
      script.setAttribute(attr.name, attr.value);
    }
  }

  script.addEventListener('load', function () {
    // Host pages written against the old snippet listen for `load` on the tag
    // with id="dograh-widget"; that already fired for this shim, so fire it
    // again now that the widget itself is actually present.
    legacy.dispatchEvent(new Event('load'));
  });

  (legacy.parentNode || document.head || document.documentElement).appendChild(script);
})();
