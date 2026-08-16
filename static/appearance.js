// Live palette preview.
//
// /palettes.css defines every palette as `html[data-palette="..."]`, so
// previewing is one attribute write — no colours are computed here and no
// request is made. The server has already rendered the saved palette onto
// <html>, so nothing flashes before this script runs.
(function () {
    var form = document.getElementById('appearance-form');
    if (!form) return;

    var root = document.documentElement;
    var saved = form.dataset.savedPalette || root.dataset.palette;
    var status = document.getElementById('preview-status');
    var resetBtn = document.getElementById('reset-preview');

    function apply(id) {
        root.setAttribute('data-palette', id);
        if (!status) return;
        status.textContent = id === saved
            ? ''
            : 'Previewing — press Save appearance to keep it.';
    }

    form.addEventListener('change', function (e) {
        if (e.target.name === 'palette') apply(e.target.value);
    });

    // Arrow-keying through the radio group fires `change`, so keyboard users get
    // the same preview. Clicking the label does too.

    if (resetBtn) {
        resetBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var input = form.querySelector('input[value="' + saved + '"]');
            if (input) input.checked = true;
            apply(saved);
        });
    }

    // Leaving the page without saving must not strand the user on a palette
    // they did not choose; the server would re-render the saved one anyway, but
    // restoring here avoids a visible repaint on back-navigation.
    window.addEventListener('pagehide', function () {
        root.setAttribute('data-palette', saved);
    });
})();
