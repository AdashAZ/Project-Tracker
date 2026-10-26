// Run with node tests/test_daily_utilization.cjs.
// Exercise the production live-total function with lightweight DOM stand-ins.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/js/main.js"), "utf8");
const start = source.indexOf("    function updateDailyTotals() {");
const end = source.indexOf("    const applyRowData", start);
assert.ok(start >= 0 && end > start);
let rows = [];
const elements = new Map();
const context = vm.createContext({
  dailyActivityList: { querySelectorAll: () => rows },
  getRowData: row => row.data,
  updateEndTime: () => {},
  renderSummaryList: () => {},
  formatHours: value => Number(value || 0).toFixed(2),
  document: { getElementById: id => {
    if (!elements.has(id)) elements.set(id, { textContent: "" });
    return elements.get(id);
  } },
});
vm.runInContext(source.slice(start, end), context);
const row = (hours, category = "Project", project = "1") => ({
  data: { duration_hours: hours, category, project_id: project },
  querySelector: () => ({ value: "Test" }),
});
function check(percent, hours) {
  context.updateDailyTotals();
  assert.equal(elements.get("daily-utilization-percent").textContent, percent);
  assert.equal(elements.get("daily-utilization-hours").textContent, hours);
}
check("0", "0.00");
rows = [row(0.5, "Project", "")];
check("0", "0.00");
rows = [row(6), row(2, "Admin")];
check("75", "6.00");
rows[0].data.duration_hours = 8;
check("100", "8.00");
rows[0].data.duration_hours = 10;
check("125", "10.00");
rows.push(row(10));
check("250", "20.00");
rows.pop();
check("125", "10.00");
rows[0].data.category = "Travel";
check("0", "0.00");
rows = [row(0.25)];
check("3.1", "0.25");
rows = [row(-2), row("bad"), row(Infinity), row(4, "Project", "")];
check("0", "0.00");
// Historical pages have no utilization elements; updating other totals must still work.
context.document.getElementById = () => null;
context.updateDailyTotals();
console.log("Live utilization checks passed.");
