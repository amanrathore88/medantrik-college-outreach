const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('UI selection survives filtering, visible selection and clear-all behave correctly', () => {
  const elements = new Map();
  let rows = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', innerText: '', checked: false, disabled: false,
      set innerHTML(value) { if (id === 'collegesBody') rows = []; },
      appendChild(row) { rows.push(row); }
    });
    return elements.get(id);
  };
  const document = {
    getElementById: get,
    createElement() { return { set innerHTML(html) {
      this.value = html.match(/value="(\d+)"/)[1];
      this.checked = /value="\d+" checked/.test(html);
      this.disabled = /disabled/.test(html);
    }}; },
    querySelectorAll() { return rows; }
  };
  const context = vm.createContext({document});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/selection.js'), 'utf8'), context);
  let script = fs.readFileSync(path.join(__dirname, '../static/dashboard.js'), 'utf8');
  script = script.replace(/loadColleges\(\);\s*$/, '');
  vm.runInContext(script, context);
  vm.runInContext(`allColleges = [
    {id:1, College_Name:'A', Location:'Delhi', TPO_Email:'a@example.org', sendable:true},
    {id:2, College_Name:'B', Location:'Noida', TPO_Email:'b@example.org', sendable:true},
    {id:3, College_Name:'C', Location:'Delhi', TPO_Email:'', sendable:false}
  ]; renderTable(allColleges);`, context);
  assert.equal(get('selectedCount').innerText, 0);
  rows[0].checked = true;
  context.toggleCollege(rows[0]);
  get('searchInput').value = 'Noida';
  context.filterColleges();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].checked, false);
  assert.equal(get('selectedCount').innerText, 1);
  context.selectAll(true);
  assert.equal(get('selectedCount').innerText, 2);
  get('searchInput').value = '';
  context.filterColleges();
  assert.ok(rows.filter(row => !row.disabled).every(row => row.checked));
  assert.ok(rows.filter(row => row.disabled).every(row => !row.checked));
  context.selectAll(false);
  assert.equal(get('selectedCount').innerText, 0);
  assert.equal(get('btnSendAll').disabled, true);
});

test('Phase 3: selectThisPage and selectAllMatches distinguish pagination scope', () => {
  const elements = new Map();
  let rows = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', innerText: '', checked: false, disabled: false,
      classList: { add() {}, remove() {} },
      set innerHTML(value) { if (id === 'collegesBody') rows = []; },
      appendChild(row) { rows.push(row); }
    });
    return elements.get(id);
  };
  const document = {
    getElementById: get,
    createElement() { return {
      classList: { add() {}, remove() {} },
      set innerHTML(html) {
        this.value = html.match(/value="(\d+)"/)[1];
        this.checked = /value="\d+" checked/.test(html);
        this.disabled = /disabled/.test(html);
      }
    }; },
    querySelectorAll() { return rows; }
  };
  const context = vm.createContext({document});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/selection.js'), 'utf8'), context);
  let script = fs.readFileSync(path.join(__dirname, '../static/dashboard.js'), 'utf8');
  script = script.replace(/loadColleges\(\);\s*$/, '');
  vm.runInContext(script, context);
  
  // Set up 30 test colleges (2 pages at pageSize=25)
  const colleges = [];
  for (let i = 1; i <= 30; i++) {
    colleges.push({
      id: i,
      College_Name: 'College ' + i,
      Location: i <= 15 ? 'Delhi' : 'Noida',
      City: i <= 15 ? 'Delhi' : 'Noida',
      Type: i % 2 === 0 ? 'Engineering & Technology' : 'Management & Business',
      TPO_Email: 'college' + i + '@example.org',
      sendable: true,
      verification_status: 'verified'
    });
  }
  vm.runInContext(`allColleges = ${JSON.stringify(colleges)}; filteredColleges = [...allColleges]; pageSize = 25; currentPage = 1; renderCollegesView();`, context);

  // Initial state: page 1 has 25 items
  assert.equal(rows.length, 25);
  assert.equal(get('selectedCount').innerText, 0);

  // selectThisPage should only select the 25 items on page 1
  context.selectThisPage();
  assert.equal(get('selectedCount').innerText, 25);

  // clear
  context.clearAllSelection();
  assert.equal(get('selectedCount').innerText, 0);

  // selectAllMatches should select all 30 items across all pages
  context.selectAllMatches();
  assert.equal(get('selectedCount').innerText, 30);

  // Filtering by area Noida
  get('filterArea').value = 'Noida';
  context.filterColleges();
  assert.equal(vm.runInContext('filteredColleges.length', context), 15);

  // Filtering by discipline
  get('filterDiscipline').value = 'Engineering';
  context.filterColleges();
  assert.equal(vm.runInContext('filteredColleges.length', context), 8);
});

