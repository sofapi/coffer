// Auto-calculate line item amount from hours * rate
document.addEventListener('DOMContentLoaded', () => {
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
