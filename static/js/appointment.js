/**
 * appointment.js - SpaManager Script
 * Handles real-time search, status filtering, and delete confirmation for appointments.
 */

/* ========= Toggle Custom Date Range ========= */
function toggleCustomDates(useAnimation) {
    useAnimation = useAnimation || false;
    var period = document.getElementById('periodSelect');
    var customRow = document.getElementById('customDatesRow');
    var fromDateInput = document.getElementById('from_date');
    var toDateInput = document.getElementById('to_date');
    if (!period || !customRow) return;

    if (period.value === 'custom') {
        customRow.style.display = 'flex';
        if (useAnimation) {
            setTimeout(function() { customRow.classList.add('show'); }, 10);
        } else {
            customRow.classList.add('show');
        }
        if (fromDateInput) fromDateInput.disabled = false;
        if (toDateInput) toDateInput.disabled = false;
    } else {
        if (useAnimation) {
            customRow.classList.remove('show');
            setTimeout(function() {
                if (document.getElementById('periodSelect').value !== 'custom') {
                    customRow.style.display = 'none';
                }
            }, 250);
        } else {
            customRow.classList.remove('show');
            customRow.style.display = 'none';
        }
        if (fromDateInput) fromDateInput.disabled = true;
        if (toDateInput) toDateInput.disabled = true;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    /* Init custom dates toggle */
    toggleCustomDates(false);

    /* Init Bootstrap Tooltips */
    var tooltipEls = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipEls.forEach(function(el) { new bootstrap.Tooltip(el); });

    /* ========= View Mode Toggle: List ↔ Calendar ========= */
    const viewBtns = document.querySelectorAll('[data-view-mode]');
    const listContainer = document.getElementById('list-view-container');
    const calContainer = document.getElementById('calendar-view-container');

    viewBtns.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const mode = this.getAttribute('data-view-mode');

            // Update active state on buttons
            viewBtns.forEach(function(b) { b.classList.remove('active'); });
            this.classList.add('active');

            if (mode === 'calendar') {
                if (listContainer) {
                    listContainer.style.display = 'none';
                    listContainer.classList.remove('app-fade');
                }
                if (calContainer) {
                    calContainer.style.display = '';
                    calContainer.classList.add('app-fade');
                    // Initialize or resize FullCalendar after container becomes visible
                    setTimeout(function() {
                        if (window.spaCalendarInit) {
                            window.spaCalendarInit();
                        }
                    }, 50);
                }
            } else {
                if (calContainer) {
                    calContainer.style.display = 'none';
                    calContainer.classList.remove('app-fade');
                }
                if (listContainer) {
                    listContainer.style.display = '';
                    listContainer.classList.add('app-fade');
                }
            }
        });
    });

    const searchInput = document.querySelector('input[name="search"]');
    const statusSelect = document.querySelector('select[name="status"]');
    const tableBody = document.querySelector('tbody');
    
    if (!tableBody) return;

    const tableRows = Array.from(tableBody.querySelectorAll('tr'));

    /**
     * Filters the appointment table based on search term and status.
     */
    function filterTable() {
        const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
        const statusFilter = statusSelect ? statusSelect.value : '';
        let visibleCount = 0;

        // Map status values to their displayed text in the table
        const statusMap = {
            'Pending': 'Chờ xử lý',
            'Confirmed': 'Đã xác nhận',
            'Completed': 'Hoàn thành',
            'Cancelled': 'Đã hủy'
        };

        tableRows.forEach(row => {
            // Skip the "No appointments found" row (it has only 1 cell with colspan)
            if (row.cells.length === 1) {
                row.style.display = 'none';
                return;
            }

            // Column indices: 1: Customer, 2: Service, 4: Status
            const customerText = row.cells[1] ? row.cells[1].textContent.toLowerCase() : '';
            const serviceText = row.cells[2] ? row.cells[2].textContent.toLowerCase() : '';
            const statusText = row.cells[4] ? row.cells[4].textContent.trim() : '';

            const matchesSearch = customerText.includes(searchTerm) || serviceText.includes(searchTerm);
            const targetStatusText = statusMap[statusFilter] || statusFilter;
            const matchesStatus = statusFilter === '' || statusText.includes(targetStatusText);

            if (matchesSearch && matchesStatus) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Handle the "No appointments found" row
        const emptyRow = tableRows.find(row => row.cells.length === 1);
        if (emptyRow) {
            emptyRow.style.display = visibleCount === 0 ? '' : 'none';
        }
    }

    // Event listeners for real-time filtering
    if (searchInput) {
        searchInput.addEventListener('input', filterTable);
    }

    if (statusSelect) {
        statusSelect.addEventListener('change', filterTable);
    }

    /**
     * Delete confirmation using Bootstrap 5 Modal.
     */
    let formToDelete = null;
    let rowToDelete = null;
    const deleteModal = document.getElementById('deleteConfirmationModal');
    const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');

    if (deleteModal) {
        const bsDeleteModal = new bootstrap.Modal(deleteModal);

        document.addEventListener('click', function(e) {
            const deleteBtn = e.target.closest('.btn-delete');
            if (deleteBtn) {
                e.preventDefault();
                formToDelete = deleteBtn.closest('form');
                rowToDelete = deleteBtn.closest('tr');
                bsDeleteModal.show();
            }
        });

        if (confirmDeleteBtn) {
            confirmDeleteBtn.addEventListener('click', function() {
                if (formToDelete) {
                    const originalHtml = confirmDeleteBtn.innerHTML;
                    confirmDeleteBtn.disabled = true;
                    confirmDeleteBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>';
                    
                    csrfFetch(formToDelete.action, {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/json'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        bsDeleteModal.hide();
                        confirmDeleteBtn.disabled = false;
                        confirmDeleteBtn.innerHTML = originalHtml;
                        
                        if (data.success) {
                            Notification.success(data.message || 'Đã xóa lịch hẹn thành công.');
                            if (rowToDelete) {
                                rowToDelete.style.transition = 'opacity 0.4s ease';
                                rowToDelete.style.opacity = '0';
                                setTimeout(() => {
                                    rowToDelete.remove();
                                    // If table becomes empty, reload to show empty state
                                    const remainingRows = document.querySelectorAll('#appointment-table tbody tr');
                                    if (remainingRows.length === 0) {
                                        window.location.reload();
                                    }
                                }, 400);
                            }
                        } else {
                            Notification.error(data.message || 'Không thể xóa lịch hẹn.');
                        }
                    })
                    .catch(error => {
                        bsDeleteModal.hide();
                        confirmDeleteBtn.disabled = false;
                        confirmDeleteBtn.innerHTML = originalHtml;
                        console.error('Error:', error);
                        Notification.error('Không thể kết nối đến máy chủ.');
                    });
                }
            });
        }
    }



    // Handle Dropdown Status Update
    const statusConfig = {
        'Pending': {
            badgeClass: 'bg-warning text-dark',
            iconClass: 'bi-clock',
            label: 'Chờ xử lý'
        },
        'Confirmed': {
            badgeClass: 'bg-primary text-white',
            iconClass: 'bi-check-circle',
            label: 'Đã xác nhận'
        },
        'Completed': {
            badgeClass: 'bg-success text-white',
            iconClass: 'bi-check2-all',
            label: 'Hoàn thành'
        },
        'Cancelled': {
            badgeClass: 'bg-danger text-white',
            iconClass: 'bi-x-circle',
            label: 'Đã hủy'
        }
    };

    document.addEventListener('click', async function(e) {
        const menuItem = e.target.closest('.status-dropdown .dropdown-item');
        if (!menuItem) return;
        e.preventDefault();

        const dropdown = menuItem.closest('.status-dropdown');
        const badgeBtn = dropdown ? dropdown.querySelector('.status-badge-btn') : null;
        if (!dropdown || !badgeBtn) return;

        const appointmentId = dropdown.getAttribute('data-id');
        const menuItems = dropdown.querySelectorAll('.dropdown-item');
        const newStatus = menuItem.getAttribute('data-value');
        const oldStatus = badgeBtn.getAttribute('data-current-status');

        if (newStatus === oldStatus) return;

        try {
            const response = await csrfFetch('/appointments/update_status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    id: appointmentId,
                    status: newStatus
                }),
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || 'Failed to update status');
            }

            const cfg = statusConfig[newStatus];
            const displayStatus = result.appointment && result.appointment.display_status ? result.appointment.display_status : cfg.label;
            badgeBtn.className = `btn btn-sm dropdown-toggle status-badge-btn badge ${cfg.badgeClass} rounded-pill d-flex align-items-center justify-content-between`;
            badgeBtn.setAttribute('data-current-status', newStatus);
            badgeBtn.innerHTML = `<span><i class="bi ${cfg.iconClass} me-1"></i>${displayStatus}</span>`;

            menuItems.forEach(mi => {
                const miVal = mi.getAttribute('data-value');
                const checkIcon = mi.querySelector('.bi-check');

                if (miVal === newStatus) {
                    mi.classList.add('active', 'fw-bold', 'disabled');
                    if (!checkIcon) {
                        mi.insertAdjacentHTML('beforeend', '<i class="bi bi-check"></i>');
                    }
                } else {
                    mi.classList.remove('active', 'fw-bold', 'disabled');
                    if (checkIcon) {
                        checkIcon.remove();
                    }
                }
            });

            const row = dropdown.closest('tr');
            if (row && row.classList.contains('table-warning')) {
                const customerCell = row.cells[2];
                if (customerCell) {
                    const exclIcon = customerCell.querySelector('.bi-exclamation-circle-fill');
                    if (newStatus === 'Pending') {
                        if (!exclIcon) {
                            const dFlex = customerCell.querySelector('.d-flex');
                            if (dFlex) {
                                dFlex.insertAdjacentHTML('afterbegin', '<i class="bi bi-exclamation-circle-fill text-warning fs-6" title="Chờ xử lý"></i>');
                            }
                        }
                    } else if (exclIcon) {
                        exclIcon.remove();
                    }
                }
            }

            Notification.success('Đã cập nhật trạng thái thành công');
        } catch (error) {
            Notification.error('Không thể cập nhật trạng thái.');
            console.error('Error updating status:', error);
        }
    });
});
