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
  // Shared helpers: machine work type rows
  // ---------------------------
  const bindWorkTypeRowInteractions = (row) => {
    const select = row.querySelector(".machine-work-type-select");
    const otherInput = row.querySelector(".machine-work-type-other");
    const updateOtherVisibility = () => {
      if (!select || !otherInput) return;
      const showOther = select.value === "Other";
      otherInput.style.display = showOther ? "" : "none";
      if (!showOther) {
        otherInput.value = "";
      }
    };

    if (select) {
      select.addEventListener("change", updateOtherVisibility);
      updateOtherVisibility();
    }
  };

  const serializeWorkTypeRows = (rows) => {
    const payload = [];
    let hasError = false;

    rows.forEach((row) => {
      const select = row.querySelector(".machine-work-type-select");
      const otherInput = row.querySelector(".machine-work-type-other");
      if (!select) return;

      const workType = (select.value || "").trim();
      const otherDescription = (otherInput?.value || "").trim();

      if (!workType) {
        return;
      }

      if (workType === "Other" && !otherDescription) {
        hasError = true;
        return;
      }

      payload.push({ work_type: workType, other_description: otherDescription });
    });

    if (payload.length === 0) {
      hasError = true;
    }

    return { payload, hasError };
  };

  // ---------------------------
  // New project: dynamic machines + work types
  // ---------------------------
  const newProjectForm = document.getElementById("new-project-form");
  if (newProjectForm) {
    const productLineList = document.getElementById("product-line-builder-list");
    const productLineTemplate = document.getElementById("product-line-builder-template");
    const machineTemplate = document.getElementById("machine-builder-template");
    const workTypeTemplate = document.getElementById("machine-work-type-template");
    const addProductLineBtn = document.getElementById("add-product-line-btn");
    const productLinesPayloadInput = document.getElementById("product_lines_payload");

    const addWorkTypeRow = (machineItem) => {
      if (!workTypeTemplate || !machineItem) return;
      const container = machineItem.querySelector("[data-work-types-container]");
      if (!container) return;
      const row = workTypeTemplate.content.firstElementChild.cloneNode(true);
      container.appendChild(row);
      bindWorkTypeRowInteractions(row);
    };

    const refreshMachineRemoveButtons = (machineList) => {
      if (!machineList) return;
      const machineItems = Array.from(machineList.querySelectorAll("[data-machine-item]"));
      const showRemove = machineItems.length > 1;
      machineItems.forEach((item) => {
        const removeBtn = item.querySelector("[data-remove-machine]");
        if (!removeBtn) return;
        removeBtn.hidden = !showRemove;
        removeBtn.disabled = !showRemove;
      });
    };

    const bindMachineItem = (machineItem, machineList) => {
      const addWorkTypeBtn = machineItem.querySelector("[data-add-work-type]");
      const removeMachineBtn = machineItem.querySelector("[data-remove-machine]");

      if (addWorkTypeBtn) {
        addWorkTypeBtn.addEventListener("click", () => addWorkTypeRow(machineItem));
      }

      if (removeMachineBtn) {
        removeMachineBtn.addEventListener("click", () => {
          machineItem.remove();
          if (machineList && machineList.querySelectorAll("[data-machine-item]").length === 0) {
            addMachineItem(machineList);
          }
          refreshMachineRemoveButtons(machineList);
        });
      }

      const existingRows = machineItem.querySelectorAll("[data-work-type-row]");
      existingRows.forEach((row) => bindWorkTypeRowInteractions(row));
      if (existingRows.length === 0) {
        addWorkTypeRow(machineItem);
      }
    };

    const addMachineItem = (machineList) => {
      if (!machineTemplate || !machineList) return;
      const machineItem = machineTemplate.content.firstElementChild.cloneNode(true);
      machineList.appendChild(machineItem);
      bindMachineItem(machineItem, machineList);
      refreshMachineRemoveButtons(machineList);
    };

    const refreshProductLineRemoveButtons = () => {
      if (!productLineList) return;
      const lineItems = Array.from(productLineList.querySelectorAll("[data-product-line-item]"));
      const showRemove = lineItems.length > 1;
      lineItems.forEach((lineItem) => {
        const removeBtn = lineItem.querySelector("[data-remove-product-line]");
        if (!removeBtn) return;
        removeBtn.hidden = !showRemove;
        removeBtn.disabled = !showRemove;
      });
    };

    const bindProductLineItem = (productLineItem) => {
      const removeProductLineBtn = productLineItem.querySelector("[data-remove-product-line]");
      const addMachineBtn = productLineItem.querySelector("[data-add-machine-row-btn]");
      const machineList = productLineItem.querySelector("[data-machine-builder-list]");
      if (!machineList) return;

      if (addMachineBtn) {
        addMachineBtn.addEventListener("click", () => addMachineItem(machineList));
      }

      if (removeProductLineBtn) {
        removeProductLineBtn.addEventListener("click", () => {
          productLineItem.remove();
          if (productLineList && productLineList.querySelectorAll("[data-product-line-item]").length === 0) {
            addProductLineItem();
          }
          refreshProductLineRemoveButtons();
        });
      }

      machineList.querySelectorAll("[data-machine-item]").forEach((item) => bindMachineItem(item, machineList));
      if (machineList.querySelectorAll("[data-machine-item]").length === 0) {
        addMachineItem(machineList);
      }
      refreshMachineRemoveButtons(machineList);
    };

    const addProductLineItem = () => {
      if (!productLineTemplate || !productLineList) return;
      const lineItem = productLineTemplate.content.firstElementChild.cloneNode(true);
      productLineList.appendChild(lineItem);
      bindProductLineItem(lineItem);
      refreshProductLineRemoveButtons();
    };

    if (addProductLineBtn) {
      addProductLineBtn.addEventListener("click", addProductLineItem);
    }

    if (productLineList) {
      productLineList.querySelectorAll("[data-product-line-item]").forEach((item) => bindProductLineItem(item));
      refreshProductLineRemoveButtons();
    }

    newProjectForm.addEventListener("submit", (event) => {
      if (!productLineList || !productLinesPayloadInput) return;

      const productLinePayload = [];
      let hasError = false;
      let hasProductLine = false;

      productLineList.querySelectorAll("[data-product-line-item]").forEach((lineItem) => {
        const lineNameInput = lineItem.querySelector(".product-line-name-input");
        const lineName = (lineNameInput?.value || "").trim();
        const machineItems = lineItem.querySelectorAll("[data-machine-item]");
        const machinePayload = [];

        machineItems.forEach((machineItem) => {
          const nameInput = machineItem.querySelector(".machine-name-input");
          const machineName = (nameInput?.value || "").trim();
          if (!machineName) return;

          if (!lineName) {
            hasError = true;
            return;
          }

          const workTypeRows = machineItem.querySelectorAll("[data-work-type-row]");
          const { payload, hasError: rowError } = serializeWorkTypeRows(workTypeRows);
          if (rowError) {
            hasError = true;
            return;
          }

          machinePayload.push({ machine_name: machineName, work_types: payload });
        });

        if (!lineName && machinePayload.length === 0) {
          return;
        }

        if (!lineName) {
          hasError = true;
          return;
        }

        hasProductLine = true;
        productLinePayload.push({
          product_line_name: lineName,
          machines: machinePayload,
        });
      });

      if (!hasProductLine) {
        event.preventDefault();
        alert("Add at least one Product / Line before creating the project.");
        return;
      }

      if (hasError) {
        event.preventDefault();
        alert("Each machine must include at least one valid work type. Also make sure each machine is inside a named Product / Line.");
        return;
      }

      productLinesPayloadInput.value = JSON.stringify(productLinePayload);
    });
  }

  // ---------------------------
  // Project detail: machine work types + time entry work type selects
  // ---------------------------
  const machineWorkTypesMapScript = document.getElementById("machine-work-types-map");
  let machineWorkTypesMap = {};
  if (machineWorkTypesMapScript?.textContent) {
    try {
      machineWorkTypesMap = JSON.parse(machineWorkTypesMapScript.textContent);
    } catch {
      machineWorkTypesMap = {};
    }
  }

  const defaultWorkTypesScript = document.getElementById("default-work-type-options");
  let defaultWorkTypeOptions = [];
  if (defaultWorkTypesScript?.textContent) {
    try {
      defaultWorkTypeOptions = JSON.parse(defaultWorkTypesScript.textContent);
    } catch {
      defaultWorkTypeOptions = [];
    }
  }

  const refreshWorkTypeSelectForMachine = (workTypeSelect, machineSelect, preferredValue = "") => {
    if (!workTypeSelect || !machineSelect) return;
    const machineId = machineSelect.value || "";
    const machineSpecificOptions = (machineWorkTypesMap[machineId] || []).filter(Boolean);
    const options = machineSpecificOptions.length > 0 ? machineSpecificOptions : defaultWorkTypeOptions.filter(Boolean);

    workTypeSelect.innerHTML = "";
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = machineId ? "-- Select --" : "Select machine first";
    workTypeSelect.appendChild(defaultOption);

    if (!machineId) {
      workTypeSelect.disabled = true;
      workTypeSelect.required = false;
    } else if (options.length === 0) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "No work types configured (edit machine)";
      emptyOption.disabled = true;
      workTypeSelect.appendChild(emptyOption);
      workTypeSelect.disabled = true;
      workTypeSelect.required = false;
    } else {
      options.forEach((label) => {
        const option = document.createElement("option");
        option.value = label;
        option.textContent = label;
        workTypeSelect.appendChild(option);
      });
      workTypeSelect.disabled = false;
      workTypeSelect.required = true;
    }

    const candidateValue = preferredValue || workTypeSelect.dataset.currentValue || "";
    if (candidateValue && options.includes(candidateValue)) {
      workTypeSelect.value = candidateValue;
    } else {
      workTypeSelect.value = "";
    }
  };

  const allWorkTypeSelects = Array.from(document.querySelectorAll(".work-type-select[data-machine-select-id]"));
  allWorkTypeSelects.forEach((workTypeSelect) => {
    const machineSelectId = workTypeSelect.dataset.machineSelectId;
    if (!machineSelectId) return;
    const machineSelect = document.getElementById(machineSelectId);
    if (!machineSelect) return;

    const initValue = workTypeSelect.dataset.currentValue || workTypeSelect.value || "";
    refreshWorkTypeSelectForMachine(workTypeSelect, machineSelect, initValue);

    machineSelect.addEventListener("change", () => {
      refreshWorkTypeSelectForMachine(workTypeSelect, machineSelect);
    });

    workTypeSelect.addEventListener("focus", () => {
      if (workTypeSelect.disabled) {
        refreshWorkTypeSelectForMachine(workTypeSelect, machineSelect);
      }
    });
  });

  const machineWorkTypeRowTemplate = document.getElementById("machine-work-type-row-template");
  const machineEditors = Array.from(document.querySelectorAll("[data-machine-work-types-editor]"));
  machineEditors.forEach((editor) => {
    const list = editor.querySelector("[data-machine-work-types-list]");
    const addBtn = editor.querySelector("[data-machine-work-type-add]");
    const form = editor.closest("form");
    const payloadInput = form?.querySelector(".machine-work-types-payload");

    if (!list || !form || !payloadInput) return;

    const addRow = () => {
      if (!machineWorkTypeRowTemplate) return;
      const row = machineWorkTypeRowTemplate.content.firstElementChild.cloneNode(true);
      list.appendChild(row);
      bindWorkTypeRowInteractions(row);
    };

    if (addBtn) {
      addBtn.addEventListener("click", addRow);
    }

    list.querySelectorAll("[data-work-type-row]").forEach((row) => bindWorkTypeRowInteractions(row));
    if (list.querySelectorAll("[data-work-type-row]").length === 0) {
      addRow();
    }

    form.addEventListener("submit", (event) => {
      const rows = list.querySelectorAll("[data-work-type-row]");
      const { payload, hasError } = serializeWorkTypeRows(rows);
      if (hasError) {
        event.preventDefault();
        alert("Machine must include at least one valid work type. 'Other' requires a description.");
        return;
      }
      payloadInput.value = JSON.stringify(payload);
    });
  });

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
