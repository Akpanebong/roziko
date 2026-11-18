/* Small progressive enhancements. Everything works without them except the live helpers. */
(function () {
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // filter bars: submit when a drop-down changes
  $$('form[data-autosubmit]').forEach(f => {
    f.addEventListener('change', e => { if (e.target.matches('select, input[type=date]')) f.submit(); });
  });

  // clickable table rows
  document.addEventListener('click', e => {
    if (e.target.closest('a, button, input, select, textarea')) return;
    const tr = e.target.closest('tr[data-href]');
    if (tr) location.href = tr.dataset.href;
  });

  // copy phone numbers
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-copy]');
    if (!b) return;
    const t = b.dataset.copy;
    try { await navigator.clipboard.writeText(t); b.textContent = 'copied'; }
    catch (_) { window.prompt('Copy this number:', t); }
    setTimeout(() => { b.textContent = 'copy'; }, 1500);
  });

  // officer name: switch the drop-down list to match the chosen branch (you can still type any name)
  const branchSel = document.getElementById('id_branch');
  $$('[data-officer-input]').forEach(inp => {
    const sync = () => { inp.setAttribute('list', 'officers-' + ((branchSel && branchSel.value) || 'ALL')); };
    if (branchSel) branchSel.addEventListener('change', sync);
    sync();
  });

  // new-loan helpers: interest, total due, repayment date
  const cfgEl = document.getElementById('loan-settings');
  const cfg = cfgEl ? JSON.parse(cfgEl.textContent) : null;
  const P = document.getElementById('id_principal');
  if (cfg && P) {
    const I = document.getElementById('id_interest'), T = document.getElementById('id_total_due');
    const D = document.getElementById('id_date_issued'), U = document.getElementById('id_due_date');
    const touched = { i: false, u: false };
    const num = el => Number(el.value) || 0;
    const calc = () => {
      if (!touched.i) I.value = Math.round(num(P) * cfg.rate / 100);
      T.value = num(P) + num(I);
    };
    const due = () => {
      if (touched.u || !D.value) return;
      const [y, m, d] = D.value.split('-').map(Number);
      const days = branchSel && branchSel.value === 'A' ? cfg.termA : cfg.termG;
      const dt = new Date(y, m - 1, d + days);
      U.value = [dt.getFullYear(), String(dt.getMonth() + 1).padStart(2, '0'), String(dt.getDate()).padStart(2, '0')].join('-');
    };
    P.addEventListener('input', calc);
    I.addEventListener('input', () => { touched.i = true; T.value = num(P) + num(I); });
    U.addEventListener('input', () => { touched.u = true; });
    D.addEventListener('change', due);
    if (branchSel) branchSel.addEventListener('change', due);
    if (!U.value) due();
  }

  // daily reminder dialog
  const dlg = document.getElementById('daily-alert');
  if (dlg && dlg.showModal) dlg.showModal();
  $$('[data-close-dialog]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
})();
