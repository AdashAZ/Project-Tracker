// static/js/main.js

document.addEventListener("DOMContentLoaded", () => {
  // ---------------------------
  // Dashboard: status filter + search preview
  // ---------------------------
  const statusFilter = document.getElementById("status-filter");
  const searchInput = document.getElementById("dashboard-search");
  const searchPreview = document.getElementById("dashboard-search-preview");
  const noMatches = document.getElementById("dashboard-no-matches");
  const projectsTable = document.getElementById("projects-table");

  if (projectsTable) {
    const rows = Array.from(projectsTable.querySelectorAll("tbody tr"));

    const norm = (value) => (value || "").toString().toLowerCase().trim();
    const normCompact = (value) => norm(value).replace(/[^a-z0-9]/g, "");
    const splitMachineList = (value) =>
      (value || "")
        .split("||")
        .map((item) => item.trim())
        .filter(Boolean);

    const fieldMatchesQuery = (fieldValue, queryRaw, queryCompact) => {
      const fieldRaw = norm(fieldValue);
      if (fieldRaw.includes(queryRaw)) return true;
      if (!queryCompact) return false;
      return normCompact(fieldRaw).includes(queryCompact);
    };

    const renderPreview = (matchedRows, query) => {
      if (!searchPreview) return;

      if (query.length < 3) {
        searchPreview.hidden = true;
        searchPreview.innerHTML = "";
        return;
      }

      if (matchedRows.length === 0) {
        searchPreview.hidden = false;
        searchPreview.innerHTML = '<div class="dashboard-search-preview-empty">no matches found</div>';
        return;
      }

      const limited = matchedRows.slice(0, 20);
      const links = limited
        .map((row) => {
          const href = row.dataset.href || "#";
          const customer = row.dataset.customer || "";
          const location = row.dataset.location || "";
          const project = row.dataset.project || "";
          const status = row.dataset.status || "";
          const due = row.dataset.due || "";
          const machineMatch = row.dataset.machineMatch || "";
          const machineText = machineMatch ? ` | Machine: ${machineMatch}` : "";
          const text = `${customer} | ${location} | ${project} | ${status} | ${due}${machineText}`;
          return `<a class="dashboard-search-item" href="${href}">${text}</a>`;
        })
        .join("");

      searchPreview.hidden = false;
      searchPreview.innerHTML = links;
    };

    const applyDashboardFilters = () => {
      const selectedStatus = norm(statusFilter ? statusFilter.value : "");
      const queryRaw = norm(searchInput ? searchInput.value : "");
      const queryCompact = normCompact(queryRaw);
      const queryActive = queryRaw.length >= 3;

      const matchedRows = [];
      let visibleCount = 0;

      rows.forEach((row) => {
        const status = norm(row.dataset.status);
        const customer = row.dataset.customer || "";
        const location = row.dataset.location || "";
        const project = row.dataset.project || "";
        const machinesJoined = row.dataset.machines || "";
        const machineList = splitMachineList(row.dataset.machineList || "");

        const statusMatches = !selectedStatus || status === selectedStatus;
        let machineMatch = "";
        let queryMatches = true;

        if (queryActive) {
          const nonMachineMatch =
            fieldMatchesQuery(customer, queryRaw, queryCompact) ||
            fieldMatchesQuery(location, queryRaw, queryCompact) ||
            fieldMatchesQuery(project, queryRaw, queryCompact);

          const machineMatchFound = fieldMatchesQuery(machinesJoined, queryRaw, queryCompact);
          if (machineMatchFound) {
            machineMatch =
              machineList.find((machineName) => fieldMatchesQuery(machineName, queryRaw, queryCompact)) || "";
          }

          queryMatches = nonMachineMatch || machineMatchFound;
        }

        row.dataset.machineMatch = machineMatch;

        const shouldShow = statusMatches && queryMatches;
        row.style.display = shouldShow ? "" : "none";

        if (shouldShow) {
          visibleCount += 1;
          matchedRows.push(row);
        }
      });

      if (noMatches) {
        noMatches.hidden = !(queryActive && visibleCount === 0);
      }

      renderPreview(matchedRows, queryRaw);
    };

    if (statusFilter) {
      statusFilter.addEventListener("change", applyDashboardFilters);
    }

    if (searchInput) {
      searchInput.addEventListener("input", applyDashboardFilters);
    }

    const isInteractiveTarget = (target) =>
      Boolean(target.closest("a, button, select, option, input, textarea, label, form"));

    const isStatusCellTarget = (target) => Boolean(target.closest("td.status-cell"));

    const openRowHref = (row, newTab = false) => {
      const href = row.dataset.href;
      if (!href) return;
      if (newTab) {
        window.open(href, "_blank", "noopener");
      } else {
        window.location.href = href;
      }
    };

    rows.forEach((row) => {
      row.addEventListener("click", (event) => {
        if (isStatusCellTarget(event.target) || isInteractiveTarget(event.target)) return;
        openRowHref(row, event.ctrlKey || event.metaKey);
      });

      row.addEventListener("auxclick", (event) => {
        if (event.button !== 1) return;
        if (isStatusCellTarget(event.target) || isInteractiveTarget(event.target)) return;
        event.preventDefault();
        openRowHref(row, true);
      });
    });

    applyDashboardFilters();
  }

  // ---------------------------
  // Project detail: toggle edit form
  // ---------------------------
  const toggleBtn = document.getElementById("toggle-edit-btn");
  const summarySection = document.getElementById("project-summary");
  const editSection = document.getElementById("project-edit");
  const sectionToggleButtons = Array.from(document.querySelectorAll(".section-toggle-btn"));

  const setSectionVisibility = (sectionId, visible) => {
    const target = document.getElementById(sectionId);
    const button = document.querySelector(`.section-toggle-btn[data-target="${sectionId}"]`);
    if (target) {
      target.style.display = visible ? "" : "none";
    }
    if (button) {
      button.classList.toggle("is-active", visible);
    }
  };

  if (sectionToggleButtons.length > 0) {
    sectionToggleButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = button.dataset.target;
        if (!targetId) return;
        const target = document.getElementById(targetId);
        if (!target) return;

        const shouldShow = target.style.display === "none";
        setSectionVisibility(targetId, shouldShow);
      });
    });
  }

  if (toggleBtn && summarySection && editSection) {
    toggleBtn.addEventListener("click", () => {
      const isEditing = editSection.style.display !== "none";

      if (isEditing) {
        editSection.style.display = "none";
        setSectionVisibility("project-summary", true);
        toggleBtn.textContent = "Edit Project";
      } else {
        editSection.style.display = "";
        setSectionVisibility("project-summary", false);
        toggleBtn.textContent = "Cancel Edit";
      }
    });
  }
});
