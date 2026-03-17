(() => {
    const sidebarToggle = document.querySelector("[data-sidebar-toggle]");
    const backdrop = document.querySelector("[data-sidebar-backdrop]");

    if (!sidebarToggle || !backdrop) {
        return;
    }

    sidebarToggle.addEventListener("click", () => {
        document.body.classList.toggle("sidebar-open");
    });

    backdrop.addEventListener("click", () => {
        document.body.classList.remove("sidebar-open");
    });
})();
