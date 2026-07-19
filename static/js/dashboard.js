// dashboard.js - SpaManager Script

function initDashboard() {
    const canvas = document.getElementById('revenueChart');
    let revenueChartInstance = null;

    // Helper to initialize the Chart
    function initChart(chartData) {
        if (!canvas) return;

        const skeleton = document.getElementById('chart-skeleton');
        
        if (typeof Chart === 'undefined') {
            console.error('Chart.js is not loaded.');
            if (skeleton) {
                skeleton.innerHTML = '<div class="text-center py-5 text-muted"><i class="bi bi-exclamation-triangle" style="font-size: 32px; color: var(--color-primary);"></i><p class="m-0 mt-2">Không thể tải biểu đồ doanh thu. Vui lòng kiểm tra kết nối mạng.</p></div>';
                skeleton.classList.remove('stf-skeleton');
                skeleton.classList.remove('d-flex');
                skeleton.classList.add('d-block');
                skeleton.querySelectorAll('.stf-skeleton').forEach(function(el) {
                    el.classList.remove('stf-skeleton');
                });
            }
            return;
        }

        if (skeleton) {
            skeleton.classList.add('d-none');
            skeleton.classList.remove('d-flex');
        }
        
        if (revenueChartInstance) {
            // Update existing chart instance
            revenueChartInstance.data.labels = chartData.labels;
            revenueChartInstance.data.datasets[0].data = chartData.values;
            revenueChartInstance.update('none'); // silent update
            return;
        }

        const style = getComputedStyle(document.body);
        const primaryColor = style.getPropertyValue('--color-primary').trim() || 'var(--color-primary)';
        const primaryLight = style.getPropertyValue('--color-primary-tint').trim() || 'color-mix(in srgb, var(--color-primary) 10.0%, transparent)';
        const textSecondary = style.getPropertyValue('--color-text-muted').trim() || 'var(--color-text-muted)';
        const borderColor = style.getPropertyValue('--color-border').trim() || 'var(--color-border)';

        revenueChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'Doanh thu (VNĐ)',
                    data: chartData.values,
                    borderColor: primaryColor,
                    backgroundColor: primaryLight,
                    borderWidth: 3,
                    tension: 0,
                    fill: true,
                    pointRadius: 4,
                    pointBackgroundColor: primaryColor
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: textSecondary,
                            callback: function(value) {
                                return new Intl.NumberFormat('vi-VN').format(value) + 'đ';
                            }
                        },
                        grid: {
                            drawBorder: false,
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
                    const style = getComputedStyle(document.body);
                    const primaryColor = style.getPropertyValue('--color-primary').trim() || 'var(--color-primary)';
                    const primaryLight = style.getPropertyValue('--color-primary-tint').trim() || 'color-mix(in srgb, var(--color-primary) 10.0%, transparent)';
                    const textSecondary = style.getPropertyValue('--color-text-muted').trim() || 'var(--color-text-muted)';
                    const borderColor = style.getPropertyValue('--color-border').trim() || 'var(--color-border)';

                    // Update dataset colors
                    if (revenueChartInstance.data.datasets && revenueChartInstance.data.datasets[0]) {
                        revenueChartInstance.data.datasets[0].borderColor = primaryColor;
                        revenueChartInstance.data.datasets[0].backgroundColor = primaryLight;
                        revenueChartInstance.data.datasets[0].pointBackgroundColor = primaryColor;
                    }

                    // Update scales
                    if (revenueChartInstance.options.scales) {
                        if (revenueChartInstance.options.scales.x) {
                            if (!revenueChartInstance.options.scales.x.ticks) revenueChartInstance.options.scales.x.ticks = {};
                            revenueChartInstance.options.scales.x.ticks.color = textSecondary;
                            if (revenueChartInstance.options.scales.x.grid) {
                                revenueChartInstance.options.scales.x.grid.color = borderColor;
                            }
                        }
                        if (revenueChartInstance.options.scales.y) {
                            if (!revenueChartInstance.options.scales.y.ticks) revenueChartInstance.options.scales.y.ticks = {};
                            revenueChartInstance.options.scales.y.ticks.color = textSecondary;
                            if (revenueChartInstance.options.scales.y.grid) {
                                revenueChartInstance.options.scales.y.grid.color = borderColor;
                            }
                        }
                    }
                    
                    revenueChartInstance.update();
                }
            });
        }
    }

    // Read initial chart data from dataset attribute
    if (canvas) {
        const chartDataAttr = canvas.getAttribute('data-revenue-chart');
        if (chartDataAttr) {
            try {
                const initialChartData = JSON.parse(chartDataAttr);
                initChart(initialChartData);
            } catch (e) {
                console.error('Error parsing initial chart data:', e);
            }
        }
    }

    // Function to perform dynamic UI updates for all widgets using Fetch API
    function refreshDashboardData() {
        fetch('/api/dashboard/data')
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok');
                return res.json();
            })
            .then(data => {
                // 1. Update KPIs
                const kpiRevenue = document.getElementById('kpi-revenue');
                const kpiCustomers = document.getElementById('kpi-customers');
                const kpiAppointments = document.getElementById('kpi-appointments');
                const kpiInvoices = document.getElementById('kpi-invoices');

                if (kpiRevenue && data.stats.revenue) kpiRevenue.textContent = data.stats.revenue.value;
                if (kpiCustomers && data.stats.customers) kpiCustomers.textContent = data.stats.customers.value;
                if (kpiAppointments && data.stats.appointments) kpiAppointments.textContent = data.stats.appointments.value;
                if (kpiInvoices && data.stats.invoices) kpiInvoices.textContent = data.stats.invoices.value;

                // 2. Update today appointments list
                if (window.updateDashboardAppointments) {
                    window.updateDashboardAppointments(data.today_appointments);
                } else {
                    const scheduleList = document.getElementById('dashboard-schedule-list');
                    if (scheduleList) {
                        if (data.today_appointments && data.today_appointments.length > 0) {
                            let html = '';
                            data.today_appointments.forEach(appt => {
                                let badgeClass = 'app-badge-default';
                                if (appt.status === 'Chờ xử lý') badgeClass = 'app-badge-pending';
                                else if (appt.status === 'Đã xác nhận') badgeClass = 'app-badge-confirmed';
                                else if (appt.status === 'Hoàn thành') badgeClass = 'app-badge-completed';
                                else if (appt.status === 'Đã hủy') badgeClass = 'app-badge-cancelled';

                                html += `
                                    <div class="appointment-item schedule-item">
                                        <div class="appointment-time schedule-time">${appt.time}</div>
                                        <div class="appointment-details schedule-details">
                                            <div class="appointment-customer schedule-customer">${appt.customer}</div>
                                            <div class="appointment-service schedule-service">${appt.service}</div>
                                        </div>
                                        <div class="appointment-status schedule-status">
                                            <span class="app-badge badge status-badge ${badgeClass}">
                                                ${appt.status}
                                            </span>
                                        </div>
                                    </div>
                                `;
                            });
                            scheduleList.innerHTML = html;
                        } else {
                            scheduleList.innerHTML = `
                                <div class="text-center py-4 text-muted" id="schedule-empty-state">
                                    <div class="mb-2"><i class="bi bi-calendar-check" style="font-size: 32px; color: var(--color-text-subtle);"></i></div>
                                    <p class="app-text m-0">Không có lịch hẹn nào cho hôm nay</p>
                                </div>
                            `;
                        }
                    }
                }

                // 3. Update Chart
                if (data.revenue_chart) {
                    initChart(data.revenue_chart);
                }

                // 4. Update latest invoices table
                const invoicesTable = document.getElementById('dashboard-latest-invoices');
                if (invoicesTable) {
                    if (data.latest_invoices && data.latest_invoices.length > 0) {
                        let html = '';
                        data.latest_invoices.forEach(inv => {
                            html += `
                                <tr>
                                    <td>#${inv.id}</td>
                                    <td>${inv.customer}</td>
                                    <td>${inv.total}</td>
                                    <td>${inv.date}</td>
                                    <td>
                                        <span class="app-badge app-badge-completed badge status-completed">${inv.status}</span>
                                    </td>
                                </tr>
                            `;
                        });
                        invoicesTable.innerHTML = html;
                    } else {
                        invoicesTable.innerHTML = `
                            <tr id="invoices-empty-state">
                                <td colspan="5" class="text-center py-4 text-muted">
                                    <div class="mb-2"><i class="bi bi-receipt" style="font-size: 32px; color: var(--color-text-subtle);"></i></div>
                                    <p class="app-text m-0">Không có hóa đơn gần đây</p>
                                </td>
                            </tr>
                        `;
                    }
                }

                // 5. Update Recent Activity timeline
                const activitiesTimeline = document.getElementById('dashboard-recent-activities');
                if (activitiesTimeline) {
                    if (data.recent_activities && data.recent_activities.length > 0) {
                        let html = '';
                        data.recent_activities.forEach(log => {
                            let badgeBg = 'bg-info';
                            if (log.severity === 'SUCCESS') badgeBg = 'bg-success';
                            else if (log.severity === 'WARNING') badgeBg = 'bg-warning text-dark';
                            else if (log.severity === 'ERROR') badgeBg = 'bg-danger';

                            html += `
                                <div class="activity-item d-flex align-items-center mb-3">
                                    <div class="activity-icon me-3">
                                        <span class="badge ${badgeBg}">
                                            ${log.action}
                                        </span>
                                    </div>
                                    <div class="activity-content flex-grow-1">
                                        <div class="small fw-semibold text-dark">${log.description}</div>
                                        <div class="text-muted small" style="font-size: 11px;">${log.time} - Phân hệ: ${log.module}</div>
                                    </div>
                                </div>
                            `;
                        });
                        activitiesTimeline.innerHTML = html;
                    } else {
                        activitiesTimeline.innerHTML = `
                            <div class="text-center py-4 text-muted" id="activities-empty-state">
                                <div class="mb-2"><i class="bi bi-clock-history" style="font-size: 32px; color: var(--color-text-subtle);"></i></div>
                                <p class="app-text m-0">Không có hoạt động nào gần đây</p>
                            </div>
                        `;
                    }
                }
            })
            .catch(err => {
                console.error('Error refreshing dashboard data:', err);
            });
    }
    // Also trigger immediate update if visibility state changes back to visible
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            refreshDashboardData();
        }
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDashboard);
} else {
    initDashboard();
}
