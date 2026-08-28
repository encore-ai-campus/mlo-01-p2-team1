(() => {
    "use strict";

    const payloadNode = document.getElementById("gold-feature-data");
    if (!payloadNode) return;

    let features = [];
    try {
        features = JSON.parse(payloadNode.textContent);
    } catch (error) {
        console.error("Gold feature payload is invalid.", error);
    }

    const featureIndex = new Map(features.map((feature) => [String(feature.manager_id), feature]));
    const rows = Array.from(document.querySelectorAll("[data-gold-row]"));
    const search = document.querySelector("[data-gold-search]");
    const department = document.querySelector("[data-gold-department]");
    const position = document.querySelector("[data-gold-position]");
    const modeButtons = Array.from(document.querySelectorAll("[data-gold-mode]"));
    const visibleCount = document.querySelector("[data-visible-manager-count]");
    const drawer = document.querySelector("[data-gold-drawer]");
    const backdrop = document.querySelector("[data-gold-drawer-backdrop]");
    let currentMode = "all";

    function matchesMode(row) {
        if (currentMode === "cross") return row.dataset.cross === "1";
        if (currentMode === "unassigned") return row.dataset.unassigned === "1";
        if (currentMode === "active") return row.dataset.active === "1";
        return true;
    }

    function applyFilters() {
        const query = (search?.value || "").trim().toLocaleLowerCase("ko-KR");
        const selectedDepartment = department?.value || "";
        const selectedPosition = position?.value || "";
        let count = 0;

        rows.forEach((row) => {
            const managerId = row.dataset.managerId.toLocaleLowerCase("ko-KR");
            const matches = (
                (!query || managerId.includes(query))
                && (!selectedDepartment || row.dataset.department === selectedDepartment)
                && (!selectedPosition || row.dataset.position === selectedPosition)
                && matchesMode(row)
            );
            row.hidden = !matches;
            if (matches) count += 1;
        });
        if (visibleCount) visibleCount.textContent = new Intl.NumberFormat("ko-KR").format(count);
    }

    function openDrawer(managerId) {
        const feature = featureIndex.get(String(managerId));
        if (!feature || !drawer) return;

        drawer.querySelectorAll("[data-detail-field]").forEach((element) => {
            const key = element.dataset.detailField;
            element.textContent = feature[key] ?? "-";
        });
        drawer.classList.add("open");
        drawer.setAttribute("aria-hidden", "false");
        if (backdrop) backdrop.hidden = false;

        rows.forEach((row) => row.classList.toggle("selected", row.dataset.managerId === String(managerId)));
    }

    function closeDrawer() {
        if (!drawer) return;
        drawer.classList.remove("open");
        drawer.setAttribute("aria-hidden", "true");
        if (backdrop) backdrop.hidden = true;
    }

    search?.addEventListener("input", applyFilters);
    department?.addEventListener("change", applyFilters);
    position?.addEventListener("change", applyFilters);
    modeButtons.forEach((button) => {
        button.addEventListener("click", () => {
            currentMode = button.dataset.goldMode;
            modeButtons.forEach((item) => item.classList.toggle("active", item === button));
            applyFilters();
        });
    });

    rows.forEach((row) => {
        row.addEventListener("click", () => openDrawer(row.dataset.managerId));
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openDrawer(row.dataset.managerId);
            }
        });
    });

    document.querySelectorAll("[data-manager-select]").forEach((button) => {
        button.addEventListener("click", () => openDrawer(button.dataset.managerSelect));
    });
    document.querySelector("[data-gold-drawer-close]")?.addEventListener("click", closeDrawer);
    backdrop?.addEventListener("click", closeDrawer);
    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeDrawer();
    });
    window.addEventListener("gold:manager-selected", (event) => {
        openDrawer(event.detail?.managerId);
    });

    document.querySelector("[data-gold-export]")?.addEventListener("click", () => {
        const keys = [
            "manager_id",
            "manager_department_name",
            "manager_position_name",
            "manager_active_flag",
            "manager_tenure_days",
            "managed_area_count",
            "managed_top_area_count",
            "managed_parent_area_count",
            "top_level_area_count",
            "average_area_age_days",
            "max_area_age_days",
            "cross_top_area_flag",
        ];
        const escapeCsv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
        const visibleFeatures = rows
            .filter((row) => !row.hidden)
            .map((row) => featureIndex.get(row.dataset.managerId))
            .filter(Boolean);
        const csv = [
            keys.join(","),
            ...visibleFeatures.map((feature) => keys.map((key) => escapeCsv(feature[key])).join(",")),
        ].join("\r\n");
        const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "gold_manager_features.csv";
        document.body.append(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    });

    applyFilters();
})();
