"use strict";

(function () {
    function parsePayload() {
        var el = document.getElementById("rotta-dashboard-data");
        if (!el) {
            return null;
        }
        try {
            return JSON.parse(el.textContent);
        } catch (_error) {
            return null;
        }
    }

    function mergeOptions(base, extra) {
        return Object.assign({}, base, extra || {});
    }

    function renderApexChart(config) {
        if (typeof ApexCharts === "undefined") {
            return;
        }
        var selector = "#" + config.id;
        var target = document.querySelector(selector);
        if (!target) {
            return;
        }
        var options = {
            chart: {
                type: config.type || "line",
                height: config.height || 300,
                toolbar: { show: false },
            },
            series: config.series || [],
            labels: config.labels || [],
            xaxis: {
                categories: config.categories || [],
                labels: { style: { colors: "#8a92a6" } },
            },
            yaxis: {
                labels: { style: { colors: "#8a92a6" } },
            },
            stroke: { curve: "smooth", width: 2 },
            dataLabels: { enabled: false },
            grid: { borderColor: "rgba(138,146,166,0.2)" },
            legend: { position: "top", horizontalAlign: "left" },
            colors: ["#1D69D6", "#3AC977", "#F89D16", "#FF5E5E", "#6E6E6E"],
        };

        if (config.type === "donut") {
            options.plotOptions = { pie: { donut: { size: "70%" } } };
        }
        if (config.type === "radialBar") {
            options.plotOptions = { radialBar: { hollow: { size: "55%" } } };
        }
        if (config.type === "bar") {
            options.plotOptions = { bar: { borderRadius: 6, columnWidth: "45%" } };
        }

        options = mergeOptions(options, config.options);
        var chart = new ApexCharts(target, options);
        chart.render();
    }

    function renderChartJs(config) {
        if (typeof Chart === "undefined") {
            return;
        }
        var canvas = document.getElementById(config.id);
        if (!canvas) {
            return;
        }
        var datasets = (config.datasets || []).map(function (item, index) {
            var palette = ["#1D69D6", "#3AC977", "#F89D16", "#FF5E5E"];
            return {
                label: item.label || ("Série " + (index + 1)),
                data: item.data || [],
                borderColor: palette[index % palette.length],
                backgroundColor: "rgba(29, 105, 214, 0.08)",
                borderWidth: 2,
                tension: 0.4,
                fill: false,
                pointRadius: 2,
            };
        });
        new Chart(canvas.getContext("2d"), {
            type: config.type || "line",
            data: { labels: config.labels || [], datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true } },
                scales: {
                    x: { grid: { color: "rgba(138,146,166,0.15)" } },
                    y: { beginAtZero: true, grid: { color: "rgba(138,146,166,0.15)" } },
                },
            },
        });
    }

    function init() {
        var payload = parsePayload();
        if (!payload || !payload.charts) {
            return;
        }
        payload.charts.forEach(function (chartConfig) {
            if (chartConfig.library === "chartjs") {
                renderChartJs(chartConfig);
                return;
            }
            renderApexChart(chartConfig);
        });
    }

    window.addEventListener("load", function () {
        setTimeout(init, 100);
    });
})();
