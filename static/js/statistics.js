document.addEventListener("DOMContentLoaded", function () {
    const ctx = document.getElementById('revenueChart');
    if (!ctx) return;

    // Parse data from data-chart attribute
    const chartDataAttr = ctx.getAttribute('data-chart');
    let chartData = { labels: [], values: [] };
    
    try {
        if (chartDataAttr) {
            chartData = JSON.parse(chartDataAttr);
        }
    } catch (e) {
        console.error("Error parsing chart data:", e);
    }


    // Destroy existing chart if it exists to prevent overlapping
    const existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    const style = getComputedStyle(document.body);
    const primaryColor = style.getPropertyValue('--color-primary').trim() || 'var(--color-primary)';
    const primaryLight = style.getPropertyValue('--color-primary-tint').trim() || 'color-mix(in srgb, var(--color-primary) 10.0%, transparent)';
    const textSecondary = style.getPropertyValue('--color-text-muted').trim() || 'var(--color-text-muted)';
    const borderColor = style.getPropertyValue('--color-border').trim() || 'var(--color-border)';

    // Create Line Chart
    const revenueChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.labels || [],
            datasets: [{
                label: 'Doanh thu (VNĐ)',
                data: chartData.values || [],
                borderColor: primaryColor, // Brand Primary Brown
                backgroundColor: primaryLight, // Faded brand background
                fill: true,
                tension: 0.4, // Curved lines
                borderWidth: 2,
                pointBackgroundColor: primaryColor,
                pointBorderColor: 'transparent',
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            return `Doanh thu: ${formatCurrency(context.parsed.y)}`;
                        }
                    }
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: textSecondary
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        color: textSecondary,
                        callback: function (value) {
                            return formatCurrency(value);
                        }
                    },
                    grid: {
                        color: borderColor
                    }
                },
                x: {
                    ticks: {
                        color: textSecondary
                    },
                    grid: {
                        display: false
                    }
                }
            }
        }
    });

    // Theme integration: Dynamically update colors when theme changes
    if (window.ThemeManager) {
        window.ThemeManager.onThemeChanged(function() {
            if (revenueChartInstance) {
                const currentStyle = getComputedStyle(document.body);
                const currentPrimary = currentStyle.getPropertyValue('--color-primary').trim() || 'var(--color-primary)';
                const currentPrimaryLight = currentStyle.getPropertyValue('--color-primary-tint').trim() || 'color-mix(in srgb, var(--color-primary) 10.0%, transparent)';
                const currentTextSecondary = currentStyle.getPropertyValue('--color-text-muted').trim() || 'var(--color-text-muted)';
                const currentBorder = currentStyle.getPropertyValue('--color-border').trim() || 'var(--color-border)';

                // Update dataset colors
                if (revenueChartInstance.data.datasets && revenueChartInstance.data.datasets[0]) {
                    revenueChartInstance.data.datasets[0].borderColor = currentPrimary;
                    revenueChartInstance.data.datasets[0].backgroundColor = currentPrimaryLight;
                    revenueChartInstance.data.datasets[0].pointBackgroundColor = currentPrimary;
                }

                // Update legend labels color
                if (revenueChartInstance.options.plugins && revenueChartInstance.options.plugins.legend && revenueChartInstance.options.plugins.legend.labels) {
                    revenueChartInstance.options.plugins.legend.labels.color = currentTextSecondary;
                }

                // Update scales
                if (revenueChartInstance.options.scales) {
                    if (revenueChartInstance.options.scales.x) {
                        if (!revenueChartInstance.options.scales.x.ticks) revenueChartInstance.options.scales.x.ticks = {};
                        revenueChartInstance.options.scales.x.ticks.color = currentTextSecondary;
                        if (revenueChartInstance.options.scales.x.grid) {
                            revenueChartInstance.options.scales.x.grid.color = currentBorder;
                        }
                    }
                    if (revenueChartInstance.options.scales.y) {
                        if (!revenueChartInstance.options.scales.y.ticks) revenueChartInstance.options.scales.y.ticks = {};
                        revenueChartInstance.options.scales.y.ticks.color = currentTextSecondary;
                        if (revenueChartInstance.options.scales.y.grid) {
                            revenueChartInstance.options.scales.y.grid.color = currentBorder;
                        }
                    }
                }
                
                revenueChartInstance.update();
            }
        });
    }
});