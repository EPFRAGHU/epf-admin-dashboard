App.registerPage('challans', async (container) => {
    container.innerHTML = '';
    const view = document.getElementById('challans-view').cloneNode(true);
    view.style.display = 'block';
    container.appendChild(view);
    Challans.init();
    await Challans.load();
});

const Challans = {
    remittances: [],
    
    init() {
        this.cacheDOM();
        this.bindEvents();
    },

    cacheDOM() {
        this.$tbody = document.querySelector('#challans-table tbody');
        this.$btnAdd = document.getElementById('btn-add-challan');
        
        // Ensure Modal container exists (we inject it dynamically if not present)
        if (!document.getElementById('challan-modal')) {
            const modalHTML = `
            <div id="challan-modal" class="modal">
                <div class="modal-content" style="max-width: 600px;">
                    <div class="modal-header">
                        <h3 id="challan-modal-title">Add Challan</h3>
                        <span class="close-modal">&times;</span>
                    </div>
                    <div class="modal-body">
                        <form id="challan-form">
                            <input type="hidden" id="challan-idx">
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label>Wage Month</label>
                                    <select id="challan-month" required class="form-control">
                                        <option value="April">April</option>
                                        <option value="May">May</option>
                                        <option value="June">June</option>
                                        <option value="July">July</option>
                                        <option value="August">August</option>
                                        <option value="September">September</option>
                                        <option value="October">October</option>
                                        <option value="November">November</option>
                                        <option value="December">December</option>
                                        <option value="January">January</option>
                                        <option value="February">February</option>
                                        <option value="March">March</option>
                                    </select>
                                </div>
                                <div class="form-group col-6" style="display:flex; align-items:flex-end;">
                                    <button type="button" class="btn btn-secondary w-100" id="btn-calc-challan">Auto-fill from Wages</button>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label>TRRN</label>
                                    <input type="text" id="challan-trrn" class="form-control" required>
                                </div>
                                <div class="form-group col-6">
                                    <label>CRRN</label>
                                    <input type="text" id="challan-crrn" class="form-control">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group col-6">
                                    <label>Members</label>
                                    <input type="number" id="challan-members" value="0" class="form-control" required>
                                </div>
                                <div class="form-group col-6">
                                    <label>Credit Date</label>
                                    <input type="date" id="challan-date" class="form-control">
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group col-4">
                                    <label>A/c 1</label>
                                    <input type="number" id="challan-ac1" value="0" class="form-control calc-total" required>
                                </div>
                                <div class="form-group col-4">
                                    <label>A/c 2</label>
                                    <input type="number" id="challan-ac2" value="0" class="form-control calc-total" required>
                                </div>
                                <div class="form-group col-4">
                                    <label>A/c 10</label>
                                    <input type="number" id="challan-ac10" value="0" class="form-control calc-total" required>
                                </div>
                            </div>
                            <div class="form-row">
                                <div class="form-group col-4">
                                    <label>A/c 21</label>
                                    <input type="number" id="challan-ac21" value="0" class="form-control calc-total" required>
                                </div>
                                <div class="form-group col-4">
                                    <label>A/c 22</label>
                                    <input type="number" id="challan-ac22" value="0" class="form-control calc-total" required>
                                </div>
                                <div class="form-group col-4">
                                    <label>Total</label>
                                    <input type="text" id="challan-total" disabled class="form-control" style="font-weight: bold; background: #eee;">
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer flex-end">
                        <button class="btn btn-secondary close-modal">Cancel</button>
                        <button class="btn btn-primary" id="btn-save-challan">Save Challan</button>
                    </div>
                </div>
            </div>`;
            document.body.insertAdjacentHTML('beforeend', modalHTML);
        }
        
        this.$modal = document.getElementById('challan-modal');
        this.$form = document.getElementById('challan-form');
        this.$btnSave = document.getElementById('btn-save-challan');
        this.$btnCalc = document.getElementById('btn-calc-challan');
        this.$inputs = document.querySelectorAll('.calc-total');
        this.$total = document.getElementById('challan-total');
    },

    bindEvents() {
        if(this.$btnAdd) {
            this.$btnAdd.addEventListener('click', () => this.showModal());
        }
        
        if(this.$btnSave) {
            this.$btnSave.addEventListener('click', (e) => {
                e.preventDefault();
                if (this.$form.checkValidity()) {
                    this.saveChallan();
                } else {
                    this.$form.reportValidity();
                }
            });
        }
        
        if(this.$btnCalc) {
            this.$btnCalc.addEventListener('click', () => this.autoCalc());
        }
        
        this.$inputs.forEach(inp => {
            inp.addEventListener('input', () => this.updateTotal());
        });
        
        const closeBtns = this.$modal.querySelectorAll('.close-modal');
        closeBtns.forEach(btn => {
            btn.addEventListener('click', () => this.closeModal());
        });
    },

    async load() {
        if (!currentYearKey) return;
        try {
            const res = await App.get('/api/years/' + encodeURIComponent(currentYearKey) + '/remittances');
            this.remittances = res.remittances || [];
            this.render();
        } catch(e) {
            console.error('Failed to load remittances', e);
        }
    },

    render() {
        if (!this.$tbody) return;
        
        this.$tbody.innerHTML = '';
        if (this.remittances.length === 0) {
            this.$tbody.innerHTML = '<tr><td colspan="12" class="text-center">No challans recorded for this year.</td></tr>';
            return;
        }
        
        this.remittances.forEach(r => {
            const total = r.acc_01 + r.acc_02 + r.acc_10 + r.acc_21 + r.acc_22;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${r.month_label}</td>
                <td>${r.trrn}</td>
                <td>${r.crrn || '-'}</td>
                <td>${r.members}</td>
                <td>${r.acc_01}</td>
                <td>${r.acc_02}</td>
                <td>${r.acc_10}</td>
                <td>${r.acc_21}</td>
                <td>${r.acc_22}</td>
                <td><strong>${total}</strong></td>
                <td>${r.credit_date || '-'}</td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="Challans.edit(${r.id})">Edit</button>
                    <button class="btn btn-sm btn-danger" onclick="Challans.del(${r.id})">Delete</button>
                </td>
            `;
            this.$tbody.appendChild(tr);
        });
    },

    showModal(r = null) {
        if (r) {
            document.getElementById('challan-modal-title').textContent = 'Edit Challan';
            document.getElementById('challan-idx').value = r.id;
            document.getElementById('challan-month').value = r.month_label;
            document.getElementById('challan-trrn').value = r.trrn;
            document.getElementById('challan-crrn').value = r.crrn || '';
            document.getElementById('challan-members').value = r.members;
            document.getElementById('challan-date').value = r.credit_date || '';
            document.getElementById('challan-ac1').value = r.acc_01;
            document.getElementById('challan-ac2').value = r.acc_02;
            document.getElementById('challan-ac10').value = r.acc_10;
            document.getElementById('challan-ac21').value = r.acc_21;
            document.getElementById('challan-ac22').value = r.acc_22;
        } else {
            document.getElementById('challan-modal-title').textContent = 'Add Challan';
            this.$form.reset();
            document.getElementById('challan-idx').value = '';
        }
        this.updateTotal();
        this.$modal.style.display = 'block';
    },

    closeModal() {
        this.$modal.style.display = 'none';
    },

    updateTotal() {
        let total = 0;
        this.$inputs.forEach(inp => {
            total += parseInt(inp.value) || 0;
        });
        if(this.$total) this.$total.value = total;
    },

    async autoCalc() {
        if (!currentYearKey) return;
        const month = document.getElementById('challan-month').value;
        const btn = this.$btnCalc;
        btn.disabled = true;
        btn.textContent = "Calculating...";
        try {
            const res = await App.get('/api/years/' + encodeURIComponent(currentYearKey) + '/remittances/calculate?month=' + encodeURIComponent(month));
            document.getElementById('challan-ac1').value = res.acc_01 || 0;
            document.getElementById('challan-ac2').value = res.acc_02 || 0;
            document.getElementById('challan-ac10').value = res.acc_10 || 0;
            document.getElementById('challan-ac21').value = res.acc_21 || 0;
            document.getElementById('challan-ac22').value = res.acc_22 || 0;
            document.getElementById('challan-members').value = res.members || 0;
            this.updateTotal();
        } catch(e) {
            alert("Calculation failed.");
            console.error(e);
        } finally {
            btn.disabled = false;
            btn.textContent = "Auto-fill from Wages";
        }
    },

    async saveChallan() {
        const payload = {
            month_label: document.getElementById('challan-month').value,
            trrn: document.getElementById('challan-trrn').value,
            crrn: document.getElementById('challan-crrn').value,
            members: parseInt(document.getElementById('challan-members').value) || 0,
            acc_01: parseInt(document.getElementById('challan-ac1').value) || 0,
            acc_02: parseInt(document.getElementById('challan-ac2').value) || 0,
            acc_10: parseInt(document.getElementById('challan-ac10').value) || 0,
            acc_21: parseInt(document.getElementById('challan-ac21').value) || 0,
            acc_22: parseInt(document.getElementById('challan-ac22').value) || 0,
            credit_date: document.getElementById('challan-date').value
        };
        
        const idx = document.getElementById('challan-idx').value;
        try {
            if (idx !== '') {
                await App.put('/api/years/' + encodeURIComponent(currentYearKey) + '/remittances/' + idx, payload);
            } else {
                await App.post('/api/years/' + encodeURIComponent(currentYearKey) + '/remittances', payload);
            }
            this.closeModal();
            this.load();
        } catch(e) {
            alert('Error saving challan');
            console.error(e);
        }
    },

    edit(id) {
        const r = this.remittances.find(x => x.id === id);
        if(r) this.showModal(r);
    },

    async del(id) {
        if (!confirm('Are you sure you want to delete this challan?')) return;
        try {
            await App.del('/api/years/' + encodeURIComponent(currentYearKey) + '/remittances/' + id);
            this.load();
        } catch(e) {
            alert('Error deleting challan');
            console.error(e);
        }
    }
};
