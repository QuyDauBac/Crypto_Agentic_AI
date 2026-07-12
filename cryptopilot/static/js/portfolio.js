/**
 * portfolio.js — CryptoPilot /portfolio and /portfolio/transactions
 *
 * Coin search in the add/edit transaction panel calls the real backend route
 * GET /market/api/search?q=... (see app/api/market.py::api_search), which
 * returns list[CoinResult] = [{coingecko_id, symbol, name, image_url}, ...].
 * normalizeResults() maps that JSON into the shape the dropdown renderer uses.
 *
 * window.CP_CHART_DATA -> {"7D": {unlocked, days_remaining, labels:[...], portfolio:[...], btc:[...]},
 *                           "30D": {...}, "90D": {...}, "1Y": {...}}
 *                          injected by dashboard.html (app/api/portfolio.py::dashboard,
 *                          _build_chart_data). unlocked=false means the window doesn't
 *                          have enough continuous daily snapshot history yet — its
 *                          button is rendered server-side as `disabled` (see
 *                          dashboard.html), so it never reaches renderChart() here.
 */
(function () {
  'use strict';

  var chartData = window.CP_CHART_DATA || null;
  var chartInstance = null;

  document.addEventListener('DOMContentLoaded', function () {
    initTimeframeChart();
    initTransactionPanel();
    initDeleteModal();
    initStaleBannerDismiss();
  });

  /* ---------------------------------------------------------------------
   * Dashboard — portfolio vs BTC performance chart
   * ------------------------------------------------------------------- */
  function initTimeframeChart() {
    var canvas = document.getElementById('cp-perf-chart');
    if (!canvas || !window.Chart || !chartData) return;

    var tfButtons = document.querySelectorAll('.cp-tf-btn');
    var activeTf = canvas.dataset.defaultTimeframe || '30D';

    function renderChart(tf) {
      var series = chartData[tf];
      if (!series || !series.labels.length) return;

      var ctx = canvas.getContext('2d');
      var gPort = ctx.createLinearGradient(0, 0, 0, 264);
      gPort.addColorStop(0, 'rgba(139,92,246,.38)');
      gPort.addColorStop(1, 'rgba(139,92,246,0)');
      var gBtc = ctx.createLinearGradient(0, 0, 0, 264);
      gBtc.addColorStop(0, 'rgba(34,211,238,.14)');
      gBtc.addColorStop(1, 'rgba(34,211,238,0)');

      updateLegend(series);

      if (chartInstance) chartInstance.destroy();
      chartInstance = new window.Chart(canvas, {
        type: 'line',
        data: {
          labels: series.labels,
          datasets: [
            {
              label: 'Danh mục', data: series.portfolio,
              borderColor: '#8b5cf6', backgroundColor: gPort,
              borderWidth: 2.4, fill: true, tension: .35, pointRadius: 0,
              pointHoverRadius: 5, pointHoverBackgroundColor: '#8b5cf6',
              pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2
            },
            {
              label: 'BTC', data: series.btc,
              borderColor: '#22d3ee', backgroundColor: gBtc,
              borderWidth: 2, fill: true, tension: .35, pointRadius: 0,
              pointHoverRadius: 5, pointHoverBackgroundColor: '#22d3ee',
              pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2,
              borderDash: [5, 4]
            }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: 'rgba(14,14,21,.96)', borderColor: 'rgba(255,255,255,.12)',
              borderWidth: 1, padding: 11, cornerRadius: 10,
              titleColor: 'rgba(255,255,255,.55)', titleFont: { size: 11 },
              bodyFont: { size: 12.5, weight: '600', family: 'JetBrains Mono' },
              usePointStyle: true, boxPadding: 5,
              callbacks: {
                label: function (c) {
                  return ' ' + c.dataset.label + ': ' + (c.parsed.y >= 0 ? '+' : '') + c.parsed.y.toFixed(2) + '%';
                }
              }
            }
          },
          scales: {
            x: { grid: { display: false }, border: { display: false },
              ticks: { color: 'rgba(255,255,255,.32)', font: { size: 10.5, family: 'JetBrains Mono' }, maxTicksLimit: 7, maxRotation: 0 } },
            y: { grid: { color: 'rgba(255,255,255,.05)' }, border: { display: false },
              ticks: { color: 'rgba(255,255,255,.32)', font: { size: 10.5, family: 'JetBrains Mono' },
                callback: function (v) { return (v >= 0 ? '+' : '') + v + '%'; } } }
          }
        }
      });
    }

    function updateLegend(series) {
      var portEl = document.querySelector('[data-role="legend-portfolio"]');
      var btcEl = document.querySelector('[data-role="legend-btc"]');
      var lastPort = series.portfolio[series.portfolio.length - 1];
      var lastBtc = series.btc[series.btc.length - 1];
      if (portEl) {
        portEl.textContent = (lastPort >= 0 ? '+' : '') + lastPort.toFixed(1) + '%';
        portEl.style.color = lastPort >= 0 ? '#34d399' : '#f8698a';
      }
      if (btcEl) {
        btcEl.textContent = (lastBtc >= 0 ? '+' : '') + lastBtc.toFixed(1) + '%';
        btcEl.style.color = lastBtc >= 0 ? '#34d399' : '#f8698a';
      }
    }

    tfButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        tfButtons.forEach(function (b) { b.classList.remove('is-active'); });
        btn.classList.add('is-active');
        activeTf = btn.dataset.timeframe;
        renderChart(activeTf);
      });
    });

    renderChart(activeTf);
  }

  function initStaleBannerDismiss() {
    var banner = document.querySelector('.cp-alert-stale');
    var dismiss = document.querySelector('[data-action="dismiss-stale-banner"]');
    if (banner && dismiss) {
      dismiss.addEventListener('click', function () { banner.remove(); });
    }
  }

  /* ---------------------------------------------------------------------
   * Coin color/initial — mirrors app/api/portfolio.py::_coin_color so the
   * client-side search dropdown looks consistent with server-rendered avatars.
   * ------------------------------------------------------------------- */
  var COIN_PALETTE = [
    '#f7931a', '#627eea', '#14b8a6', '#2a5ada', '#3468d1',
    '#e84142', '#e6007a', '#8247e5', '#3b4552', '#c2a633'
  ];
  function coinColor(symbol) {
    var s = symbol || '';
    var sum = 0;
    for (var i = 0; i < s.length; i++) sum += s.charCodeAt(i);
    return COIN_PALETTE[sum % COIN_PALETTE.length];
  }
  function coinMono(symbol) {
    return (symbol || '?').charAt(0).toUpperCase();
  }

  /** Maps CoinResult[] (coingecko_id, symbol, name, image_url) -> internal shape. */
  function normalizeResults(json) {
    return (json || []).map(function (c) {
      return {
        id: c.coingecko_id,
        symbol: (c.symbol || '').toLowerCase(),
        name: c.name,
        image: c.image_url || null
      };
    });
  }

  /* ---------------------------------------------------------------------
   * Transactions — slide-in add/edit panel
   * ------------------------------------------------------------------- */
  function initTransactionPanel() {
    var panel = document.getElementById('cp-tx-panel');
    if (!panel) return; // only present on /portfolio/transactions

    var backdrop = panel.querySelector('.cp-panel-backdrop');
    var closeBtns = panel.querySelectorAll('[data-action="close-panel"]');
    var form = document.getElementById('cp-tx-form');
    var titleEl = panel.querySelector('.cp-panel-head-title');
    var submitBtn = panel.querySelector('.cp-btn-submit');

    var buyBtn = panel.querySelector('.cp-buysell-btn.buy');
    var sellBtn = panel.querySelector('.cp-buysell-btn.sell');
    var typeInput = form.querySelector('input[name="type"]');

    var coinInput = panel.querySelector('#cp-coin-query');
    var coingeckoIdInput = form.querySelector('input[name="coingecko_id"]');
    var coinSymbolInput = form.querySelector('input[name="symbol"]');
    var coinNameInput = form.querySelector('input[name="name"]');
    var coinAvatar = panel.querySelector('.cp-coin-search-avatar');
    var dropdown = panel.querySelector('.cp-coin-dropdown');

    var qtyInput = form.querySelector('input[name="quantity"]');
    var priceInput = form.querySelector('input[name="price"]');
    var estimateValue = panel.querySelector('.cp-estimate-value');

    function openPanel() { panel.classList.add('is-open'); document.body.style.overflow = 'hidden'; }
    function closePanel() {
      panel.classList.remove('is-open');
      document.body.style.overflow = '';
      closeDropdown();
    }

    document.querySelectorAll('[data-action="open-add-transaction"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        resetForm();
        titleEl.textContent = 'Thêm giao dịch';
        submitBtn.textContent = 'Thêm giao dịch';
        form.action = form.dataset.createUrl;
        openPanel();
      });
    });

    document.querySelectorAll('[data-action="edit-transaction"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        clearFieldErrors();
        titleEl.textContent = 'Sửa giao dịch';
        submitBtn.textContent = 'Lưu thay đổi';
        form.action = form.dataset.updateUrlBase + btn.dataset.txId + '/edit';

        setType(btn.dataset.txType);
        selectCoin(btn.dataset.txCoingeckoId, btn.dataset.txSymbol, btn.dataset.txCoinName);
        qtyInput.value = btn.dataset.txQuantity;
        priceInput.value = btn.dataset.txPrice;
        form.querySelector('input[name="fee"]').value = btn.dataset.txFee || '';
        form.querySelector('input[name="executed_at"]').value = btn.dataset.txDatetime;
        form.querySelector('textarea[name="note"]').value = btn.dataset.txNote || '';
        updateEstimate();
        openPanel();
      });
    });

    if (backdrop) backdrop.addEventListener('click', closePanel);
    closeBtns.forEach(function (b) { b.addEventListener('click', closePanel); });

    function resetForm() {
      form.reset();
      setType('buy');
      selectCoin('', '', '');
      clearFieldErrors();
      updateEstimate();
    }

    function setType(type) {
      typeInput.value = type;
      buyBtn.classList.toggle('is-active', type === 'buy');
      sellBtn.classList.toggle('is-active', type === 'sell');
      updateEstimate();
    }
    if (buyBtn) buyBtn.addEventListener('click', function () { setType('buy'); });
    if (sellBtn) sellBtn.addEventListener('click', function () { setType('sell'); });

    /* ---- coin search (AJAX against /market/api/search) ---- */
    function selectCoin(id, symbol, name) {
      coingeckoIdInput.value = id || '';
      coinSymbolInput.value = symbol || '';
      coinNameInput.value = name || '';
      coinInput.value = name ? (name + ' (' + (symbol || '').toUpperCase() + ')') : '';
      if (coinAvatar) {
        coinAvatar.textContent = symbol ? coinMono(symbol) : '?';
        coinAvatar.style.background = symbol ? coinColor(symbol) : '#555';
      }
      closeDropdown();
    }

    function renderDropdown(matches) {
      dropdown.innerHTML = '';
      if (matches.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'cp-coin-no-results';
        empty.textContent = 'Không tìm thấy coin phù hợp';
        dropdown.appendChild(empty);
      } else {
        matches.forEach(function (c) {
          var opt = document.createElement('div');
          opt.className = 'cp-coin-option';
          var avatar = c.image
            ? '<img class="cp-coin-option-avatar" src="' + c.image + '" alt="" width="28" height="28">'
            : '<span class="cp-coin-option-avatar" style="background:' + coinColor(c.symbol) + '">' + coinMono(c.symbol) + '</span>';
          opt.innerHTML =
            avatar +
            '<div style="flex:1"><div class="cp-coin-option-name">' + c.name + '</div>' +
            '<div class="cp-coin-option-sym">' + c.symbol.toUpperCase() + '</div></div>';
          opt.addEventListener('click', function () { selectCoin(c.id, c.symbol, c.name); });
          dropdown.appendChild(opt);
        });
      }
      dropdown.classList.add('is-open');
    }
    function closeDropdown() { dropdown.classList.remove('is-open'); }

    var searchTimer = null;
    var searchSeq = 0;
    function runSearch(query) {
      var q = (query || '').trim();
      if (q.length < 2) { closeDropdown(); return; }
      var seq = ++searchSeq;
      fetch('/market/api/search?q=' + encodeURIComponent(q))
        .then(function (res) { return res.ok ? res.json() : []; })
        .then(function (json) {
          if (seq !== searchSeq) return; // stale response — a newer query already fired
          renderDropdown(normalizeResults(json).slice(0, 8));
        })
        .catch(function () { /* network error: ignore, don't break the form */ });
    }

    if (coinInput) {
      coinInput.addEventListener('input', function () {
        clearTimeout(searchTimer);
        var q = coinInput.value;
        searchTimer = setTimeout(function () { runSearch(q); }, 300);
      });
      document.addEventListener('click', function (e) {
        if (!panel.contains(e.target) || (!coinInput.contains(e.target) && !dropdown.contains(e.target))) {
          closeDropdown();
        }
      });
    }

    /* ---- live "total value" estimate ---- */
    var estimateWordEl = panel.querySelector('[data-role="estimate-word"]');

    function updateEstimate() {
      var qty = parseFloat(qtyInput.value);
      var price = parseFloat(priceInput.value);
      var isBuy = typeInput.value === 'buy';
      if (estimateWordEl) estimateWordEl.textContent = isBuy ? 'phải trả' : 'nhận về';
      if (qty > 0 && price > 0) {
        var total = qty * price;
        estimateValue.textContent = (isBuy ? '−' : '+') + formatUSD(total);
        estimateValue.style.color = isBuy ? '#f8698a' : '#34d399';
      } else {
        estimateValue.textContent = '—';
        estimateValue.style.color = 'rgba(255,255,255,.5)';
      }
    }
    if (qtyInput) qtyInput.addEventListener('input', updateEstimate);
    if (priceInput) priceInput.addEventListener('input', updateEstimate);

    function clearFieldErrors() {
      form.querySelectorAll('.cp-input.is-error').forEach(function (el) { el.classList.remove('is-error'); });
      form.querySelectorAll('.cp-error-text').forEach(function (el) { el.style.display = 'none'; });
    }

    /* client-side required-field check; server must still validate + re-render on error */
    form.addEventListener('submit', function (e) {
      clearFieldErrors();
      var qty = parseFloat(qtyInput.value);
      var price = parseFloat(priceInput.value);
      var hasError = false;
      if (!(qty > 0)) { markError(qtyInput); hasError = true; }
      if (!(price > 0)) { markError(priceInput); hasError = true; }
      if (hasError) e.preventDefault();
    });
    function markError(input) {
      input.classList.add('is-error');
      var errEl = input.parentElement.querySelector('.cp-error-text');
      if (errEl) errEl.style.display = 'block';
    }

    /* server-rendered "edit" panel (GET /portfolio/transactions?edit=ID) opens on load;
       form fields are already pre-filled server-side via Jinja, JS just reveals it. */
    updateEstimate();
    if (panel.dataset.openOnLoad === 'true') {
      titleEl.textContent = panel.dataset.editingId ? 'Sửa giao dịch' : 'Thêm giao dịch';
      submitBtn.textContent = panel.dataset.editingId ? 'Lưu thay đổi' : 'Thêm giao dịch';
      openPanel();
    }
  }

  function formatUSD(n) {
    var decimals = Math.abs(n) >= 1000 ? 0 : 2;
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  /* ---------------------------------------------------------------------
   * Delete confirmation modal
   * ------------------------------------------------------------------- */
  function initDeleteModal() {
    var modal = document.getElementById('cp-delete-modal');
    if (!modal) return;

    var backdrop = modal.querySelector('.cp-modal-backdrop');
    var descEl = modal.querySelector('[data-role="delete-desc"]');
    var form = modal.querySelector('form');
    var cancelBtns = modal.querySelectorAll('[data-action="cancel-delete"]');

    document.querySelectorAll('[data-action="delete-transaction"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        descEl.textContent = btn.dataset.txDesc || '';
        form.action = form.dataset.deleteUrlBase + btn.dataset.txId + '/delete';
        modal.classList.add('is-open');
      });
    });

    function close() { modal.classList.remove('is-open'); }
    if (backdrop) backdrop.addEventListener('click', close);
    cancelBtns.forEach(function (b) { b.addEventListener('click', close); });
  }
})();
