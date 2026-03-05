// static/js/main.js

document.addEventListener("DOMContentLoaded", () => {
  // ---------------------------
  // Dashboard: status filter
  // ---------------------------
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

  // ---------------------------
  // Project detail: toggle edit form
  // ---------------------------
  const toggleBtn = document.getElementById("toggle-edit-btn");
  const summarySection = document.getElementById("project-summary");
  const editSection = document.getElementById("project-edit");

  // Only attach behavior if we're on a project detail page
  if (toggleBtn && summarySection && editSection) {
    toggleBtn.addEventListener("click", () => {
      // Determine current state by checking edit section visibility
      const isEditing = editSection.style.display !== "none";

      if (isEditing) {
        // Currently editing -> hide form, show summary
        editSection.style.display = "none";
        summarySection.style.display = "";
        toggleBtn.textContent = "Edit Project";
      } else {
        // Currently viewing -> show form, hide summary
        editSection.style.display = "";
        summarySection.style.display = "none";
        toggleBtn.textContent = "Cancel Edit";
      }
    });
  }
});