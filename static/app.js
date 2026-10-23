// Auto-calculate line item amount from hours * rate
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();

    const hours = document.getElementById('line-hours');
    const rate = document.getElementById('line-rate');
    const amount = document.getElementById('line-amount');

    if (hours && rate && amount) {
        const calc = () => {
            const h = parseFloat(hours.value) || 0;
            const r = parseFloat(rate.value) || 0;
            if (h && r) {
                amount.value = (h * r).toFixed(2);
            }
        };
        hours.addEventListener('input', calc);
        rate.addEventListener('input', calc);
    }

    // Set default date to today on empty date inputs
    document.querySelectorAll('input[type="date"]').forEach(input => {
        if (!input.value && input.required) {
            input.value = new Date().toISOString().split('T')[0];
        }
    });

    // Pension form: show the relief and gross the server will calculate.
    // Integer pence with half-up rounding, matching pensions.split_contribution;
    // this is only a preview — the saved figures always come from the server.
    document.querySelectorAll('form[data-pension-form]').forEach(form => {
        const out = form.querySelector('[data-pension-preview]');
        const bp = Math.round(parseFloat(form.dataset.reliefRate) * 10000);
        const fmt = p => '£' + (p / 100).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        const update = () => {
            const net = Math.round(parseFloat(form.elements.amount_paid.value) * 100);
            if (!(net > 0)) { out.textContent = ''; return; }
            let gross = net;
            if (form.elements.relief_method.value === 'relief_at_source' && bp > 0) {
                const d = 10000 - bp;
                gross = Math.floor((2 * net * 10000 + d) / (2 * d));
            }
            out.textContent = 'Paid ' + fmt(net) + ' · Tax relief added ' + fmt(gross - net) +
                ' · Gross contribution ' + fmt(gross);
        };
        form.addEventListener('input', update);
        form.addEventListener('change', update);
        update();
    });

    document.querySelectorAll('form[data-confirm]').forEach(form => {
        form.addEventListener('submit', e => {
            if (!window.confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    document.querySelectorAll('[data-share-pdf]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const url = btn.dataset.sharePdf;
            const name = btn.dataset.shareName || 'invoice.pdf';
            const title = btn.dataset.shareTitle || name;
            btn.disabled = true;
            try {
                const res = await fetch(url, { credentials: 'same-origin' });
                if (!res.ok) throw new Error('Fetch failed: ' + res.status);
                const blob = await res.blob();
                const file = new File([blob], name, { type: 'application/pdf' });

                if (navigator.canShare && navigator.canShare({ files: [file] })) {
                    await navigator.share({ files: [file], title, text: title });
                } else {
                    const objectUrl = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = objectUrl;
                    a.download = name;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
                }
            } catch (err) {
                if (err && err.name !== 'AbortError') {
                    alert('Sharing failed: ' + err.message);
                }
            } finally {
                btn.disabled = false;
            }
        });
    });
});


// Navigation: the hamburger (narrow screens) and the Money / Settings
// disclosure menus. Each control's aria-expanded is the single source of
// truth — style.css shows a panel from it — so screen readers always hear the
// state that is on screen. Groups open on click/tap (never hover), close on an
// outside click, on Escape, when focus leaves them, or when a link is chosen.
function initNavigation() {
    const toggle = document.querySelector('.nav-toggle');
    const list = document.getElementById('nav-links');
    const groups = Array.from(document.querySelectorAll('[data-nav-group]'));
    if (!toggle || !list) return;

    const buttonOf = g => g.querySelector('.nav-group-toggle');
    const linksOf = g => Array.from(g.querySelectorAll('.nav-menu a'));
    const isOpen = el => el.getAttribute('aria-expanded') === 'true';
    const setGroup = (g, open) => buttonOf(g).setAttribute('aria-expanded', String(open));
    const closeGroups = (except) => groups.forEach(g => { if (g !== except) setGroup(g, false); });
    const setList = open => {
        list.classList.toggle('open', open);
        toggle.setAttribute('aria-expanded', String(open));
    };

    toggle.addEventListener('click', () => setList(!isOpen(toggle)));

    groups.forEach(g => {
        const button = buttonOf(g);

        button.addEventListener('click', () => {
            const open = !isOpen(button);
            closeGroups(g);
            setGroup(g, open);
        });

        // Down / Up on the button opens the panel at its first / last link.
        button.addEventListener('keydown', e => {
            if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
            e.preventDefault();
            closeGroups(g);
            setGroup(g, true);
            const links = linksOf(g);
            links[e.key === 'ArrowDown' ? 0 : links.length - 1].focus();
        });

        // Arrow keys / Home / End move between links; Tab works as normal.
        g.querySelector('.nav-menu').addEventListener('keydown', e => {
            const links = linksOf(g);
            const i = links.indexOf(document.activeElement);
            const next = {
                ArrowDown: (i + 1) % links.length,
                ArrowUp: (i - 1 + links.length) % links.length,
                Home: 0,
                End: links.length - 1,
            }[e.key];
            if (next === undefined) return;
            e.preventDefault();
            links[next].focus();
        });

        linksOf(g).forEach(a => a.addEventListener('click', () => setGroup(g, false)));

        g.addEventListener('focusout', e => {
            if (!g.contains(e.relatedTarget)) setGroup(g, false);
        });
    });

    document.addEventListener('click', e => {
        groups.forEach(g => { if (!g.contains(e.target)) setGroup(g, false); });
        if (isOpen(toggle) && !e.target.closest('nav')) setList(false);
    });

    document.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        const open = groups.find(g => isOpen(buttonOf(g)));
        if (open) {
            setGroup(open, false);
            buttonOf(open).focus();
        } else if (isOpen(toggle)) {
            setList(false);
            toggle.focus();
        }
    });

    // Back/forward can restore a page from cache with a menu still open.
    window.addEventListener('pageshow', e => {
        if (e.persisted) { closeGroups(); setList(false); }
    });
}
