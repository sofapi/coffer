// Financial performance chart.
//
// Deliberately hand-rolled SVG: Coffer ships no build pipeline and no runtime
// JS dependencies, and a grouped bar + line chart is not worth importing a
// charting library for. Every colour is read from the active palette's CSS
// custom properties, so the chart re-themes with the rest of the app.
//
// Layout: grouped bars for the flow measures (revenue, costs, and optionally
// invoiced) with a line for net, all on ONE value axis — the measures share a
// currency, so a second axis would invent a comparison that isn't there.
(function () {
    'use strict';

    var root = document.getElementById('performance-chart');
    if (!root) return;

    var frame = root.querySelector('.chart-frame');
    var legendEl = root.querySelector('.chart-legend');
    var tableEl = document.getElementById('performance-table');

    // Series definitions. `kind` picks the mark; `token` names the palette
    // variable. Adding a measure is one entry plus a field in the payload.
    var SERIES = [
        { key: 'revenue',  label: 'Revenue',  kind: 'bar',  token: '--chart-revenue',  on: true },
        { key: 'costs',    label: 'Costs',    kind: 'bar',  token: '--chart-cost',     on: true },
        { key: 'net',      label: 'Net',      kind: 'line', token: '--chart-net',      on: true },
        { key: 'invoiced', label: 'Invoiced', kind: 'bar',  token: '--chart-invoiced', on: false }
    ];

    var state = {
        data: null,
        error: null,
        loading: false,
        visible: SERIES.reduce(function (acc, s) { acc[s.key] = s.on; return acc; }, {})
    };

    // draw() runs again on every resize and legend toggle, so its tooltip
    // teardown is registered once here and re-pointed rather than re-bound —
    // otherwise listeners pile up on the (persistent) frame element.
    var dismissTooltip = function () {};
    frame.addEventListener('mouseleave', function () { dismissTooltip(); });

    var NS = 'http://www.w3.org/2000/svg';

    function el(name, attrs, parent) {
        var node = document.createElementNS(NS, name);
        for (var k in attrs) {
            if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
        }
        if (parent) parent.appendChild(node);
        return node;
    }

    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
    }

    // ---- formatting ------------------------------------------------------

    function currencyCode() {
        return (state.data && state.data.currency && state.data.currency.code) || 'GBP';
    }

    function fmtMoney(value) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency', currency: currencyCode(),
                minimumFractionDigits: 2, maximumFractionDigits: 2
            }).format(value);
        } catch (e) {
            var sym = (state.data && state.data.currency && state.data.currency.symbol) || '';
            return sym + value.toFixed(2);
        }
    }

    // Axis labels stay short so a 12-month chart fits on a phone: 1.2k, 3.4M.
    function fmtAxis(value) {
        var abs = Math.abs(value);
        var unit = '', scaled = value;
        if (abs >= 1e9) { scaled = value / 1e9; unit = 'B'; }
        else if (abs >= 1e6) { scaled = value / 1e6; unit = 'M'; }
        else if (abs >= 1e3) { scaled = value / 1e3; unit = 'k'; }
        var digits = unit && Math.abs(scaled) < 10 ? 1 : 0;
        var num = scaled.toFixed(digits).replace(/\.0$/, '');
        var sym = (state.data && state.data.currency && state.data.currency.symbol) || '';
        return (value < 0 ? '-' : '') + sym + num.replace('-', '') + unit;
    }

    // ---- scale -----------------------------------------------------------

    function niceTicks(min, max, count) {
        if (min === max) { max = min + 1; }
        var span = max - min;
        var raw = span / Math.max(1, count);
        var mag = Math.pow(10, Math.floor(Math.log10(raw)));
        var norm = raw / mag;
        // Snap to the NEAREST of 1/2/5/10, not the next one up: rounding up
        // turned a £10k range into £5k steps and padded the axis with empty
        // space far below the lowest value.
        var step = (norm <= 1.5 ? 1 : norm <= 3 ? 2 : norm <= 7 ? 5 : 10) * mag;
        var lo = Math.floor(min / step) * step;
        var hi = Math.ceil(max / step) * step;
        var ticks = [];
        for (var v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
        return ticks;
    }

    // ---- render ----------------------------------------------------------

    function activeSeries() {
        return SERIES.filter(function (s) { return state.visible[s.key]; });
    }

    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

    function renderState(className, html) {
        dismissTooltip = function () {};   // the old tooltip is about to be discarded
        clear(frame);
        var box = document.createElement('div');
        box.className = className;
        box.innerHTML = html;
        frame.appendChild(box);
    }

    function render() {
        if (state.loading) {
            renderState('chart-status', '<div class="chart-skeleton" role="status" aria-label="Loading chart"></div>');
            return;
        }
        if (state.error) {
            renderState('chart-status',
                '<div class="empty empty-inline">' +
                '<span class="empty-title">Chart could not load</span>' +
                '<p>' + state.error + '</p>' +
                '<button type="button" class="btn btn-quiet" id="chart-retry">Try again</button>' +
                '</div>');
            var retry = document.getElementById('chart-retry');
            if (retry) retry.addEventListener('click', function () { load(currentQuery()); });
            return;
        }

        var data = state.data;
        if (!data || !data.series.length) {
            renderState('chart-status',
                '<div class="empty empty-inline">' +
                '<span class="empty-title">Nothing to chart yet</span>' +
                '<p>Add income, expenses or invoices and this chart will show how each month compares.</p>' +
                '</div>');
            return;
        }

        var hasValues = data.series.some(function (p) {
            return p.revenue || p.costs || p.invoiced;
        });
        if (!hasValues) {
            // Distinguish "you have no data at all" from "nothing landed in this
            // window" — telling a brand new user to widen the period is useless
            // advice, and `has_data` is what tells the two apart.
            renderState('chart-status', data.has_data
                ? '<div class="empty empty-inline">' +
                  '<span class="empty-title">No activity in this period</span>' +
                  '<p>There are no invoices, income entries or expenses dated within ' +
                  data.window.label.toLowerCase() + '. Try a wider period.</p>' +
                  '</div>'
                : '<div class="empty empty-inline">' +
                  '<span class="empty-title">Nothing to chart yet</span>' +
                  '<p>Add an invoice, an income entry or an expense and this chart ' +
                  'will show how each month compares.</p>' +
                  '</div>');
            return;
        }

        draw(data);
    }

    function draw(data) {
        clear(frame);

        var points = data.series;
        var series = activeSeries();
        var bars = series.filter(function (s) { return s.kind === 'bar'; });
        var lines = series.filter(function (s) { return s.kind === 'line'; });

        var width = Math.max(320, frame.clientWidth || 640);
        var compact = width < 560;
        var height = compact ? 260 : 320;
        var pad = { top: 12, right: 8, bottom: 34, left: compact ? 44 : 56 };
        var plotW = width - pad.left - pad.right;
        var plotH = height - pad.top - pad.bottom;

        var values = [0];
        points.forEach(function (p) {
            series.forEach(function (s) { values.push(p[s.key]); });
        });
        var ticks = niceTicks(Math.min.apply(null, values), Math.max.apply(null, values), compact ? 4 : 5);
        var yMin = ticks[0], yMax = ticks[ticks.length - 1];
        var y = function (v) { return pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH; };

        var bandW = plotW / points.length;
        var groupW = Math.min(bandW * 0.72, 88);
        var barW = bars.length ? Math.max(3, groupW / bars.length - 2) : 0;

        var svg = el('svg', {
            class: 'chart-svg', width: width, height: height,
            viewBox: '0 0 ' + width + ' ' + height,
            role: 'img',
            'aria-label': 'Monthly ' + series.map(function (s) { return s.label.toLowerCase(); }).join(', ') +
                          ' for ' + data.window.label + '. The same figures are in the table below.'
        }, frame);

        // Grid first, so marks always sit on top of it.
        ticks.forEach(function (t) {
            el('line', {
                class: t === 0 ? 'chart-zero-line' : 'chart-grid-line',
                x1: pad.left, x2: width - pad.right, y1: y(t), y2: y(t)
            }, svg);
            el('text', {
                class: 'chart-axis-text', x: pad.left - 8, y: y(t) + 4, 'text-anchor': 'end'
            }, svg).textContent = fmtAxis(t);
        });

        // One hover band per month drives both the tooltip and the highlight,
        // so the hit target is the whole column rather than a thin bar.
        var bandLayer = el('g', {}, svg);
        var markLayer = el('g', {}, svg);

        var labelEvery = compact && points.length > 6 ? Math.ceil(points.length / 4) : 1;

        points.forEach(function (p, i) {
            var x0 = pad.left + i * bandW;
            var cx = x0 + bandW / 2;

            var band = el('rect', {
                class: 'chart-hover-band', x: x0, y: pad.top,
                width: bandW, height: plotH, rx: 4
            }, bandLayer);
            band.dataset.index = i;

            bars.forEach(function (s, bi) {
                var v = p[s.key];
                var bx = cx - groupW / 2 + bi * (groupW / bars.length) + 1;
                var top = y(Math.max(0, v));
                var h = Math.abs(y(v) - y(0));
                if (h < 1 && v === 0) return;         // nothing to draw for a zero month
                el('rect', {
                    class: 'chart-bar', x: bx, y: top, width: barW,
                    height: Math.max(h, 1.5), rx: 4, ry: 4,
                    fill: token(s.token)
                }, markLayer);
            });

            if (i % labelEvery === 0 || i === points.length - 1) {
                var isLast = i === points.length - 1;
                el('text', {
                    class: 'chart-axis-text' + (isLast ? ' is-current' : ''),
                    x: cx, y: height - 12, 'text-anchor': 'middle'
                }, svg).textContent = compact ? p.label.split(' ')[0] : p.label.replace(' ', ' ');
            }
        });

        lines.forEach(function (s) {
            var d = points.map(function (p, i) {
                var cx = pad.left + i * bandW + bandW / 2;
                return (i ? 'L' : 'M') + cx.toFixed(1) + ' ' + y(p[s.key]).toFixed(1);
            }).join(' ');
            el('path', { class: 'chart-net-line', d: d, stroke: token(s.token) }, markLayer);
            points.forEach(function (p, i) {
                var cx = pad.left + i * bandW + bandW / 2;
                el('circle', {
                    class: 'chart-net-dot', cx: cx, cy: y(p[s.key]),
                    r: points.length > 12 ? 3.5 : 4.5, fill: token(s.token)
                }, markLayer);
            });
        });

        // Bands live above the marks so hovering never falls into a gap.
        svg.appendChild(bandLayer);

        var tip = document.createElement('div');
        tip.className = 'chart-tooltip';
        tip.setAttribute('role', 'presentation');
        frame.appendChild(tip);

        function showTip(i, clientX) {
            var p = points[i];
            var rows = series.map(function (s) {
                return '<div class="tooltip-row"><span class="tooltip-key">' +
                    '<span class="legend-swatch' + (s.kind === 'line' ? ' is-line' : '') +
                    '" style="background:' + token(s.token) + '"></span>' + s.label +
                    '</span><span class="tooltip-value">' + fmtMoney(p[s.key]) + '</span></div>';
            }).join('');
            tip.innerHTML = '<div class="tooltip-title">' + p.label + '</div>' + rows;
            tip.classList.add('is-visible');

            var rect = frame.getBoundingClientRect();
            var w = tip.offsetWidth;
            var x = (clientX !== undefined ? clientX - rect.left : pad.left + i * bandW + bandW / 2) - w / 2;
            tip.style.left = Math.max(4, Math.min(x, rect.width - w - 4)) + 'px';
            tip.style.top = '8px';

            Array.prototype.forEach.call(bandLayer.children, function (b, bi) {
                b.classList.toggle('is-active', bi === i);
            });
        }

        function hideTip() {
            tip.classList.remove('is-visible');
            Array.prototype.forEach.call(bandLayer.children, function (b) {
                b.classList.remove('is-active');
            });
        }

        Array.prototype.forEach.call(bandLayer.children, function (band) {
            var i = Number(band.dataset.index);
            band.addEventListener('mouseenter', function (e) { showTip(i, e.clientX); });
            band.addEventListener('mousemove', function (e) { showTip(i, e.clientX); });
            band.addEventListener('mouseleave', hideTip);
            band.addEventListener('touchstart', function (e) {
                showTip(i, e.touches[0].clientX);
            }, { passive: true });
        });
        dismissTooltip = hideTip;
    }

    // ---- legend ----------------------------------------------------------

    function renderLegend() {
        if (!legendEl) return;
        clear(legendEl);
        SERIES.forEach(function (s) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'legend-item';
            btn.setAttribute('aria-pressed', String(!!state.visible[s.key]));
            btn.innerHTML = '<span class="legend-swatch' + (s.kind === 'line' ? ' is-line' : '') +
                '" style="background:' + token(s.token) + '"></span>' + s.label;
            btn.addEventListener('click', function () {
                var on = !state.visible[s.key];
                // Hiding the last visible series would leave an axis and nothing
                // else, so the final one stays on.
                if (!on && activeSeries().length === 1) return;
                state.visible[s.key] = on;
                btn.setAttribute('aria-pressed', String(on));
                render();
            });
            legendEl.appendChild(btn);
        });
    }

    // ---- summary tiles ---------------------------------------------------
    //
    // Server-rendered on first paint; rewritten here when the period changes
    // without a reload. Only the value and footnote text change — the tiles,
    // their labels and their explanatory notes stay as Jinja rendered them.
    // `polarity` is which direction is good, so rising costs read as a loss.

    var TILES = {
        invoiced:    { polarity: 1 },
        revenue:     { polarity: 1 },
        costs:       { polarity: -1 },
        net:         { polarity: 1 }
    };

    function fmtMoney0(value) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency', currency: currencyCode(),
                minimumFractionDigits: 0, maximumFractionDigits: 0
            }).format(value);
        } catch (e) {
            var sym = (state.data && state.data.currency && state.data.currency.symbol) || '';
            return sym + Math.round(value).toLocaleString();
        }
    }

    function changeHtml(cmp, polarity) {
        if (cmp.pct !== null && cmp.pct !== undefined) {
            var good = (cmp.pct > 0) === (polarity === 1);
            var cls = cmp.pct === 0 ? 'trend-flat' : (good ? 'trend-up' : 'trend-down');
            var arrow = cmp.pct > 0 ? '▲' : (cmp.pct < 0 ? '▼' : '●');
            return '<span class="trend ' + cls + '"><span class="trend-arrow" aria-hidden="true">' +
                arrow + '</span>' + Math.abs(cmp.pct * 100).toFixed(1) + '%</span> vs previous';
        }
        if (cmp.delta) {
            var ok = (cmp.delta > 0) === (polarity === 1);
            return '<span class="trend ' + (ok ? 'trend-up' : 'trend-down') + '">' +
                fmtMoney0(cmp.delta) + '</span> vs previous';
        }
        return '<span class="trend trend-flat">No change</span> vs previous';
    }

    function setTile(key, value, foot, negative) {
        var tile = document.querySelector('[data-metric="' + key + '"]');
        if (!tile) return;
        var v = tile.querySelector('.metric-value');
        var f = tile.querySelector('.metric-foot');
        v.textContent = value;
        v.classList.toggle('is-negative', !!negative);
        f.innerHTML = foot;
    }

    function renderTiles() {
        var data = state.data;
        if (!data) return;
        Object.keys(TILES).forEach(function (key) {
            var cmp = data.comparison[key];
            setTile(key, fmtMoney0(data.totals[key]),
                    changeHtml(cmp, TILES[key].polarity),
                    data.totals[key] < 0);
        });

        var margin = data.totals.margin;
        var mDelta = data.comparison.margin.delta;
        setTile('margin',
            margin === null ? '—' : (margin * 100).toFixed(1) + '%',
            margin === null
                ? 'No revenue in period'
                : (mDelta === null || mDelta === undefined
                    ? 'No comparable period'
                    : (mDelta >= 0 ? '+' : '') + (mDelta * 100).toFixed(1) + ' pts vs previous'),
            margin !== null && margin < 0);

        var o = data.outstanding;
        setTile('outstanding', fmtMoney0(o.total),
            o.overdue_total
                ? '<span class="trend trend-down">' + fmtMoney0(o.overdue_total) + ' overdue</span>'
                : o.count + ' unpaid invoice' + (o.count === 1 ? '' : 's'),
            false);
    }

    // ---- data table (accessible equivalent) ------------------------------

    function renderTable() {
        if (!tableEl || !state.data) return;
        var points = state.data.series;
        var head = '<thead><tr><th scope="col">Month</th><th scope="col" class="num">Invoiced</th>' +
            '<th scope="col" class="num">Revenue</th><th scope="col" class="num">Costs</th>' +
            '<th scope="col" class="num">Net</th></tr></thead>';
        var body = points.map(function (p) {
            return '<tr><th scope="row">' + p.label + '</th>' +
                '<td class="num">' + fmtMoney(p.invoiced) + '</td>' +
                '<td class="num">' + fmtMoney(p.revenue) + '</td>' +
                '<td class="num">' + fmtMoney(p.costs) + '</td>' +
                '<td class="num">' + fmtMoney(p.net) + '</td></tr>';
        }).join('');
        tableEl.innerHTML = head + '<tbody>' + body + '</tbody>';
    }

    // ---- loading ---------------------------------------------------------

    function currentQuery() {
        return window.location.search;
    }

    function load(query) {
        state.loading = true;
        state.error = null;
        render();
        fetch('/api/dashboard/performance' + (query || ''), {
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }).then(function (res) {
            if (!res.ok) throw new Error('Server responded ' + res.status);
            return res.json();
        }).then(function (json) {
            state.data = json;
            state.loading = false;
            render();
            renderLegend();
            renderTable();
            renderTiles();
            var heading = document.querySelector('h1 .subtitle');
            if (heading) heading.textContent = json.window.label;
        }).catch(function (err) {
            state.loading = false;
            state.error = err.message || 'Unknown error';
            render();
        });
    }

    // First paint uses the payload the server already embedded, so the chart
    // appears with the page instead of after a round trip.
    var seed = document.getElementById('performance-data');
    if (seed) {
        try { state.data = JSON.parse(seed.textContent); } catch (e) { state.error = 'Malformed chart data.'; }
    }
    render();
    renderLegend();
    renderTable();

    var resizeTimer;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () { if (!state.loading && !state.error) render(); }, 120);
    });

    // Period controls are real links, so the dashboard works without JS. With
    // JS we fetch instead, which keeps scroll position and shows the loading
    // state rather than blanking the page.
    document.querySelectorAll('[data-period-link]').forEach(function (link) {
        link.addEventListener('click', function (e) {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            var url = new URL(link.href, window.location.origin);
            window.history.replaceState({}, '', url.pathname + url.search);
            document.querySelectorAll('[data-period-link]').forEach(function (other) {
                other.classList.toggle('active', other === link);
            });
            load(url.search);
        });
    });
})();
