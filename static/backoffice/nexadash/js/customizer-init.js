"use strict";

(function ($) {
    function applySettings(patch) {
        if (typeof dzSettingsOptions === "undefined" || typeof dzSettings === "undefined") {
            return;
        }
        dzSettingsOptions = { ...dzSettingsOptions, ...patch };
        new dzSettings(dzSettingsOptions);
    }

    function restoreCustomizerUI() {
        $("#flexSwitchCheckDefault").prop(
            "checked",
            (localStorage.getItem("dz-version") || "light") === "dark",
        );
        $("#sidebar_position").prop(
            "checked",
            (localStorage.getItem("dz-sidebarPosition") || "fixed") === "fixed",
        );
        $("#header_position").prop(
            "checked",
            (localStorage.getItem("dz-headerPosition") || "fixed") === "fixed",
        );
        $("#theme_layout").prop(
            "checked",
            (localStorage.getItem("dz-layout") || "vertical") === "horizontal",
        );
        $('input[name="btnradio"]')
            .filter(`[value="${localStorage.getItem("dz-sidebarStyle") || "full"}"]`)
            .prop("checked", true);
        $('input[name="primary_bg"]')
            .filter(`[value="${localStorage.getItem("dz-primary") || "color_1"}"]`)
            .prop("checked", true);
        $('input[name="navigation_header"]')
            .filter(`[value="${localStorage.getItem("dz-navheaderBg") || "color_1"}"]`)
            .prop("checked", true);
        $('input[name="header_bg"]')
            .filter(`[value="${localStorage.getItem("dz-headerBg") || "color_1"}"]`)
            .prop("checked", true);
        $('input[name="sidebar_bg"]')
            .filter(`[value="${localStorage.getItem("dz-sidebarBg") || "color_1"}"]`)
            .prop("checked", true);
    }

    $(function () {
        $(document).on("click", ".sidebar-right-trigger", function (e) {
            e.preventDefault();
            $(".sidebar-right").addClass("show");
        });
        $(document).on("click", ".sidebar-close-trigger, .bg-overlay", function (e) {
            e.preventDefault();
            $(".sidebar-right").removeClass("show");
        });

        restoreCustomizerUI();

        $("#flexSwitchCheckDefault").on("change", function () {
            const version = this.checked ? "dark" : "light";
            localStorage.setItem("dz-version", version);
            applySettings({ version });
        });

        $("#sidebar_position").on("change", function () {
            const sidebarPosition = this.checked ? "fixed" : "static";
            localStorage.setItem("dz-sidebarPosition", sidebarPosition);
            applySettings({ sidebarPosition });
        });

        $("#header_position").on("change", function () {
            const headerPosition = this.checked ? "fixed" : "static";
            localStorage.setItem("dz-headerPosition", headerPosition);
            applySettings({ headerPosition });
        });

        $("#theme_layout").on("change", function () {
            const layout = this.checked ? "horizontal" : "vertical";
            localStorage.setItem("dz-layout", layout);
            applySettings({ layout });
        });

        $('input[name="btnradio"]').on("change", function () {
            const sidebarStyle = $(this).val();
            localStorage.setItem("dz-sidebarStyle", sidebarStyle);
            applySettings({ sidebarStyle });
        });

        $('input[name="primary_bg"]').on("change", function () {
            const primary = $(this).val();
            localStorage.setItem("dz-primary", primary);
            applySettings({ primary });
        });

        $('input[name="navigation_header"]').on("change", function () {
            const navheaderBg = $(this).val();
            localStorage.setItem("dz-navheaderBg", navheaderBg);
            applySettings({ navheaderBg });
        });

        $('input[name="header_bg"]').on("change", function () {
            const headerBg = $(this).val();
            localStorage.setItem("dz-headerBg", headerBg);
            applySettings({ headerBg });
        });

        $('input[name="sidebar_bg"]').on("change", function () {
            const sidebarBg = $(this).val();
            localStorage.setItem("dz-sidebarBg", sidebarBg);
            applySettings({ sidebarBg });
        });

        $("#reset_customizer").on("click", function (e) {
            e.preventDefault();
            for (let i = localStorage.length - 1; i >= 0; i -= 1) {
                const key = localStorage.key(i);
                if (key && key.startsWith("dz-")) {
                    localStorage.removeItem(key);
                }
            }
            window.location.reload();
        });
    });
})(jQuery);
