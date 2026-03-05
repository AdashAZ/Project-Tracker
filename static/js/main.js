
flask
flask_sqlalchemy


// static/js/main.js
document.addEventListener("DOMContentLoaded", () => {
  const statusFilter = document.getElementById("status-filter");
  const projectsTable = document.getElementById("projects-table");

  if (statusFilter && projectsTable) {
    statusFilter.addEventListener("change", () => {
      const selected = statusFilter.value.trim();
      const rows = projectsTable.querySelectorAll("tbody tr");

      rows.forEach((row) => {
        const statusCell = row.querySelector("td:nth-child(6)");
        const statusText = statusCell ? statusCell.textContent.trim() : "";

        if (!selected || statusText === selected) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    });
  }
});