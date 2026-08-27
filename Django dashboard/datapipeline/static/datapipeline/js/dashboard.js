(() => {
    "use strict";

    const payloadNode = document.getElementById("dashboard-chart-data");
    const chartElements = Array.from(document.querySelectorAll("[data-dashboard-chart]"));
    const chartInstances = [];

    let payload = {};
    if (payloadNode) {
        try {
            payload = JSON.parse(payloadNode.textContent);
        } catch (error) {
            console.error("Dashboard chart payload is invalid.", error);
        }
    }

    const colors = {
        cyan: "#20d9ff",
        teal: "#15e6c1",
        purple: "#a855f7",
        amber: "#f59e0b",
        red: "#ff4667",
        text: "#9cc8d9",
        muted: "#476b80",
        grid: "rgba(78, 144, 173, 0.12)",
        tooltip: "rgba(3, 12, 23, 0.96)",
    };
    const fontFamily = 'Inter, Pretendard, "Noto Sans KR", "Malgun Gothic", sans-serif';

    const compactNumber = (value) => new Intl.NumberFormat("ko-KR", {
        notation: Math.abs(Number(value)) >= 10000 ? "compact" : "standard",
        maximumFractionDigits: 1,
    }).format(value);

    const baseTooltip = (suffix = "") => ({
        trigger: "axis",
        backgroundColor: colors.tooltip,
        borderColor: "rgba(32, 217, 255, 0.35)",
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: "#d9f5ff", fontFamily, fontSize: 10 },
        axisPointer: { type: "line", lineStyle: { color: "rgba(32, 217, 255, 0.3)" } },
        valueFormatter: (value) => `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value)}${suffix}`,
    });

    const axisLabel = {
        color: colors.muted,
        fontFamily,
        fontSize: 9,
    };

    function lineOption(config) {
        const suffix = config.suffix || "";
        return {
            animationDuration: 900,
            animationEasing: "cubicOut",
            color: config.datasets.map((dataset) => dataset.color),
            tooltip: baseTooltip(suffix),
            legend: {
                top: 6,
                right: 10,
                itemWidth: 12,
                itemHeight: 2,
                textStyle: { color: colors.muted, fontFamily, fontSize: 9 },
            },
            grid: { top: 42, right: 17, bottom: 28, left: 47, containLabel: false },
            xAxis: {
                type: "category",
                boundaryGap: false,
                data: config.labels,
                axisLine: { lineStyle: { color: "rgba(71, 119, 143, 0.18)" } },
                axisTick: { show: false },
                axisLabel: { ...axisLabel, interval: config.labels.length > 8 ? 1 : 0 },
            },
            yAxis: {
                type: "value",
                scale: true,
                splitNumber: 4,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: { ...axisLabel, formatter: (value) => compactNumber(value) },
                splitLine: { lineStyle: { color: colors.grid } },
            },
            series: config.datasets.map((dataset) => ({
                name: dataset.label,
                type: "line",
                data: dataset.values,
                smooth: 0.34,
                showSymbol: false,
                symbol: "circle",
                lineStyle: {
                    width: 2,
                    color: dataset.color,
                    shadowBlur: 9,
                    shadowColor: dataset.color,
                },
                itemStyle: { color: dataset.color },
                areaStyle: dataset.fill ? {
                    opacity: 1,
                    color: new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: `${dataset.color}55` },
                        { offset: 1, color: `${dataset.color}00` },
                    ]),
                } : undefined,
                emphasis: { focus: "series" },
            })),
        };
    }

    function barOption(config) {
        const suffix = config.suffix || "";
        const horizontal = Boolean(config.horizontal);
        const categoryAxis = {
            type: "category",
            data: config.labels,
            inverse: horizontal,
            axisLine: { lineStyle: { color: "rgba(71, 119, 143, 0.18)" } },
            axisTick: { show: false },
            axisLabel: {
                ...axisLabel,
                interval: 0,
                width: horizontal ? 92 : 75,
                overflow: "truncate",
            },
        };
        const valueAxis = {
            type: "value",
            scale: false,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { ...axisLabel, formatter: (value) => compactNumber(value) },
            splitLine: { lineStyle: { color: colors.grid } },
        };

        return {
            animationDuration: 850,
            animationEasing: "cubicOut",
            color: config.datasets.map((dataset) => dataset.color),
            tooltip: baseTooltip(suffix),
            legend: config.datasets.length > 1 ? {
                top: 4,
                right: 8,
                itemWidth: 10,
                itemHeight: 5,
                textStyle: { color: colors.muted, fontFamily, fontSize: 9 },
            } : { show: false },
            grid: horizontal
                ? { top: 18, right: 22, bottom: 22, left: 98 }
                : { top: 29, right: 16, bottom: 35, left: 46 },
            xAxis: horizontal ? valueAxis : categoryAxis,
            yAxis: horizontal ? categoryAxis : valueAxis,
            series: config.datasets.map((dataset) => ({
                name: dataset.label,
                type: "bar",
                data: dataset.values,
                barMaxWidth: horizontal ? 9 : 24,
                barGap: "18%",
                itemStyle: {
                    borderRadius: horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0],
                    color: new window.echarts.graphic.LinearGradient(horizontal ? 0 : 0, horizontal ? 0 : 1, horizontal ? 1 : 0, horizontal ? 0 : 0, [
                        { offset: 0, color: `${dataset.color}66` },
                        { offset: 1, color: dataset.color },
                    ]),
                    shadowBlur: 7,
                    shadowColor: `${dataset.color}55`,
                },
                emphasis: { itemStyle: { shadowBlur: 14, shadowColor: dataset.color } },
            })),
        };
    }

    function doughnutOption(config) {
        const dataset = config.datasets[0];
        const total = dataset.values.reduce((sum, value) => sum + value, 0) || 1;
        return {
            animationDuration: 1000,
            animationEasing: "cubicOut",
            title: {
                text: config.centerText || compactNumber(total),
                subtext: config.centerLabel || "TOTAL",
                left: "center",
                top: "30%",
                textStyle: { color: "#e3f8ff", fontFamily, fontSize: 20, fontWeight: 700 },
                subtextStyle: { color: colors.muted, fontFamily, fontSize: 8, lineHeight: 16 },
            },
            tooltip: {
                trigger: "item",
                backgroundColor: colors.tooltip,
                borderColor: "rgba(168, 85, 247, 0.35)",
                textStyle: { color: "#e8f8ff", fontFamily, fontSize: 10 },
                formatter: ({ name, value, percent }) => `${name}<br><b>${compactNumber(value)}</b> · ${percent}%`,
            },
            legend: {
                bottom: 4,
                left: "center",
                itemWidth: 7,
                itemHeight: 7,
                itemGap: 12,
                textStyle: { color: colors.muted, fontFamily, fontSize: 8 },
            },
            series: [{
                name: config.centerLabel || "distribution",
                type: "pie",
                radius: ["58%", "76%"],
                center: ["50%", "40%"],
                avoidLabelOverlap: true,
                label: { show: false },
                labelLine: { show: false },
                itemStyle: {
                    borderColor: "#071323",
                    borderWidth: 3,
                    shadowBlur: 12,
                    shadowColor: "rgba(32, 217, 255, 0.12)",
                },
                emphasis: { scale: true, scaleSize: 6 },
                data: config.labels.map((label, index) => ({
                    name: label,
                    value: dataset.values[index],
                    itemStyle: { color: dataset.colors[index] },
                })),
            }],
        };
    }

    function buildOption(config) {
        if (config.type === "line") return lineOption(config);
        if (config.type === "bar") return barOption(config);
        if (config.type === "doughnut") return doughnutOption(config);
        return {};
    }

    if (!window.echarts && chartElements.length) {
        console.error("ECharts failed to load.");
        chartElements.forEach((element) => element.classList.add("chart-load-error"));
    } else if (window.echarts) {
        chartElements.forEach((element) => {
            const config = payload[element.dataset.dashboardChart];
            if (!config) return;
            const chart = window.echarts.init(element, null, {
                renderer: "canvas",
                devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
            });
            chart.setOption({
                backgroundColor: "transparent",
                textStyle: { fontFamily },
                aria: { enabled: true },
                ...buildOption(config),
            });
            chartInstances.push(chart);
        });
    }

    let resizeFrame = 0;
    const resizeCharts = () => {
        window.cancelAnimationFrame(resizeFrame);
        resizeFrame = window.requestAnimationFrame(() => chartInstances.forEach((chart) => chart.resize()));
    };
    window.addEventListener("resize", resizeCharts, { passive: true });

    const clock = document.querySelector(".clock");
    if (clock) {
        const formatter = new Intl.DateTimeFormat("ko-KR", {
            timeZone: "Asia/Seoul",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
        });
        const tick = () => {
            const now = new Date();
            clock.textContent = formatter.format(now);
            clock.dateTime = now.toISOString();
        };
        tick();
        window.setInterval(tick, 1000);
    }

    document.querySelectorAll("[data-refresh-button]").forEach((button) => {
        button.addEventListener("click", () => window.location.reload());
    });

    document.addEventListener("visibilitychange", () => {
        chartInstances.forEach((chart) => chart.setOption({ animation: !document.hidden }));
    });
})();
