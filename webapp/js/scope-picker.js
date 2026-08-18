/* ================================================================
   ScopePicker — reusable cascading Branch → Division → Unit selector.
   Division/Unit option lists are physically rebuilt on each parent
   change, so it is structurally impossible to pick a mismatched pair.
   ================================================================ */

window.ScopePicker = (() => {
  function render(container, orgData, opts = {}) {
    const branches = orgData.branches || [];
    const divisions = orgData.divisions || [];
    const units = orgData.units || [];
    const allowNoneBranch = !!opts.allowNoneBranch;
    const initial = opts.initial || {};
    const onChange = opts.onChange || (() => {});

    container.innerHTML = `
      <div class="scope-picker" style="display:flex; gap:8px; flex-wrap:wrap;">
        <select class="form-input" data-scope-role="branch" style="flex:1; min-width:140px;"></select>
        <select class="form-input" data-scope-role="division" style="flex:1; min-width:140px;"></select>
        <select class="form-input" data-scope-role="unit" style="flex:1; min-width:140px;"></select>
      </div>
    `;

    const branchSel = container.querySelector('[data-scope-role="branch"]');
    const divSel = container.querySelector('[data-scope-role="division"]');
    const unitSel = container.querySelector('[data-scope-role="unit"]');

    function fillBranch(selectedId) {
      const html = [];
      if (allowNoneBranch) html.push(`<option value="">All Branches</option>`);
      branches.forEach(b => html.push(`<option value="${b.id}">${App.esc(b.name)}</option>`));
      branchSel.innerHTML = html.join('');
      if (selectedId != null && branches.some(b => b.id === selectedId)) {
        branchSel.value = String(selectedId);
      } else if (!allowNoneBranch && branches.length) {
        branchSel.value = String(branches[0].id);
      } else {
        branchSel.value = '';
      }
    }

    function fillDivision(branchId, selectedId) {
      const html = [`<option value="">${branchId == null ? 'All Divisions' : 'No Division'}</option>`];
      divisions.filter(d => branchId != null && d.branch_id === branchId)
        .forEach(d => html.push(`<option value="${d.id}">${App.esc(d.name)}</option>`));
      divSel.innerHTML = html.join('');
      divSel.disabled = branchId == null;
      if (selectedId != null && divisions.some(d => d.id === selectedId && d.branch_id === branchId)) {
        divSel.value = String(selectedId);
      } else {
        divSel.value = '';
      }
    }

    function fillUnit(divisionId, selectedId) {
      const html = [`<option value="">No Unit</option>`];
      units.filter(u => divisionId != null && u.division_id === divisionId)
        .forEach(u => html.push(`<option value="${u.id}">${App.esc(u.name)}</option>`));
      unitSel.innerHTML = html.join('');
      unitSel.disabled = divisionId == null;
      if (selectedId != null && units.some(u => u.id === selectedId && u.division_id === divisionId)) {
        unitSel.value = String(selectedId);
      } else {
        unitSel.value = '';
      }
    }

    function currentValue() {
      return {
        branch_id: branchSel.value ? Number(branchSel.value) : null,
        division_id: divSel.value ? Number(divSel.value) : null,
        unit_id: unitSel.value ? Number(unitSel.value) : null,
      };
    }

    function emit() { onChange(currentValue()); }

    branchSel.onchange = () => {
      const branchId = branchSel.value ? Number(branchSel.value) : null;
      fillDivision(branchId, null);
      fillUnit(null, null);
      emit();
    };
    divSel.onchange = () => {
      const divisionId = divSel.value ? Number(divSel.value) : null;
      fillUnit(divisionId, null);
      emit();
    };
    unitSel.onchange = () => emit();

    const initBranchId = initial.branch_id != null ? Number(initial.branch_id) : null;
    const initDivisionId = initial.division_id != null ? Number(initial.division_id) : null;
    const initUnitId = initial.unit_id != null ? Number(initial.unit_id) : null;

    fillBranch(initBranchId);
    const effBranchId = branchSel.value ? Number(branchSel.value) : null;
    fillDivision(effBranchId, initDivisionId);
    const effDivisionId = divSel.value ? Number(divSel.value) : null;
    fillUnit(effDivisionId, initUnitId);
  }

  function getValue(container) {
    const branchSel = container.querySelector('[data-scope-role="branch"]');
    const divSel = container.querySelector('[data-scope-role="division"]');
    const unitSel = container.querySelector('[data-scope-role="unit"]');
    if (!branchSel) return { branch_id: null, division_id: null, unit_id: null };
    return {
      branch_id: branchSel.value ? Number(branchSel.value) : null,
      division_id: divSel && divSel.value ? Number(divSel.value) : null,
      unit_id: unitSel && unitSel.value ? Number(unitSel.value) : null,
    };
  }

  return { render, getValue };
})();
