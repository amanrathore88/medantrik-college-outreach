class CollegeSelection {
  constructor() { this.selected = new Set(); }
  set(id, checked) { checked ? this.selected.add(id) : this.selected.delete(id); }
  has(id) { return this.selected.has(id); }
  ids() { return [...this.selected]; }
  clear() { this.selected.clear(); }
}
if (typeof module !== 'undefined') module.exports = CollegeSelection;
