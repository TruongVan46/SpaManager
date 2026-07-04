/**
 * appointment-calendar.js - SpaManager Professional Calendar
 * Handles Month/Week/Day views with Summary Cards, Popovers, Offcanvas
 */

(function () {
    'use strict';

    /* ============================
       CONFIG & CONSTANTS
       ============================ */
    const STATUS_MAP = {
        Confirmed:  { label: 'Đã xác nhận',   icon: '✔', cls: 'confirmed', badge: 'cal-status-confirmed', bi: 'bi-check-circle-fill text-primary' },
        Pending:    { label: 'Chờ xử lý',   icon: '⏳', cls: 'pending',   badge: 'cal-status-pending',   bi: 'bi-clock-fill text-warning' },
        Completed:  { label: 'Hoàn thành',     icon: '✔', cls: 'completed', badge: 'cal-status-completed', bi: 'bi-check2-all text-success' },
        Cancelled:  { label: 'Đã hủy',         icon: '✖', cls: 'cancelled', badge: 'cal-status-cancelled', bi: 'bi-x-circle-fill text-danger' }
    };
    const STATUS_MAP_BY_KEY = {
        confirmed: STATUS_MAP.Confirmed,
        pending: STATUS_MAP.Pending,
        completed: STATUS_MAP.Completed,
        cancelled: STATUS_MAP.Cancelled,
        canceled: STATUS_MAP.Cancelled,
        no_show: { label: 'Không đến', icon: '✖', cls: 'no-show', badge: 'cal-status-no-show', bi: 'bi-person-x-fill text-secondary' },
        noshow: { label: 'Không đến', icon: '✖', cls: 'no-show', badge: 'cal-status-no-show', bi: 'bi-person-x-fill text-secondary' }
    };

    const EVENTS_URL = '/appointments/events';
    const UPDATE_STATUS_URL = '/appointments/update_status';

    let calendarInstance = null;
    let allEvents = [];
    let activePopover = null;
    let offcanvasInstance = null;
    const isMobile = () => window.innerWidth < 769;

    /* ============================
       HELPER FUNCTIONS
       ============================ */
    function fmt(n) {
        return new Intl.NumberFormat('vi-VN').format(n) + 'đ';
    }

    function fmtTime(dateStr) {
        if (!dateStr) return '--:--';
        const d = new Date(dateStr);
        return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function fmtDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function fmtDateShort(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function dateKey(dateStr) {
        const d = new Date(dateStr);
        // Use local date parts to avoid UTC shift (e.g. Vietnam UTC+7)
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function statusInfo(status) {
        const normalized = (status || '').toString().trim().toLowerCase();
        return STATUS_MAP[status] || STATUS_MAP_BY_KEY[normalized] || STATUS_MAP.Pending;
    }

    function destroyActivePopover() {
        if (activePopover) {
            activePopover.dispose();
            activePopover = null;
        }
        document.querySelectorAll('.cal-popover, .cal-day-popover').forEach(el => el.remove());
    }

    /* ============================
       GROUP EVENTS BY DATE
       ============================ */
    function groupByDate(events) {
        const map = {};
        events.forEach(ev => {
            const key = dateKey(ev.start || ev.startStr);
            if (!map[key]) map[key] = [];
            map[key].push(ev);
        });
        // Sort each day's events by start time
        Object.keys(map).forEach(k => {
            map[k].sort((a, b) => new Date(a.start || a.startStr) - new Date(b.start || b.startStr));
        });
        return map;
    }

    /* ============================
       GET EXT PROPS SAFELY
       ============================ */
    function ext(event) {
        return event.extendedProps || event;
    }

    /* ============================
       MONTH VIEW: SUMMARY CARDS
       ============================ */
    function renderMonthSummaries() {
        // Remove old summaries
        document.querySelectorAll('.spa-summary-card').forEach(el => el.remove());

        const grouped = groupByDate(allEvents);

        document.querySelectorAll('.fc-daygrid-day').forEach(cell => {
            const date = cell.getAttribute('data-date');
            if (!date) return;

            const dayEvents = grouped[date];
            if (!dayEvents || dayEvents.length === 0) return;

            const count = dayEvents.length;
            const revenue = dayEvents.reduce((sum, ev) => sum + (ext(ev).service_price || 0), 0);

            let colorClass = 'summary-green';
            if (count >= 8) colorClass = 'summary-red';
            else if (count >= 4) colorClass = 'summary-yellow';

            const card = document.createElement('div');
            card.className = `spa-summary-card ${colorClass}`;
            card.setAttribute('data-date', date);
            card.innerHTML = `
                <span class="spa-summary-count">🗓 ${count} lịch</span>
                ${revenue > 0 ? `<span class="spa-summary-revenue">💰 ${fmt(revenue)}</span>` : ''}
            `;

            // Hover popover (desktop only)
            if (!isMobile()) {
                card.addEventListener('mouseenter', function (e) {
                    destroyActivePopover();
                    showDayPopover(card, date, dayEvents);
                });
                card.addEventListener('mouseleave', function () {
                    setTimeout(() => {
                        const popEl = document.querySelector('.cal-day-popover:hover');
                        if (!popEl) destroyActivePopover();
                    }, 200);
                });
            }

            // Click => Offcanvas
            card.addEventListener('click', function (e) {
                e.stopPropagation();
                destroyActivePopover();
                document.querySelectorAll('.spa-summary-card').forEach(c => c.classList.remove('active-card'));
                card.classList.add('active-card');
                showDayOffcanvas(date, dayEvents);
            });

            const frame = cell.querySelector('.fc-daygrid-day-frame');
            if (frame) frame.appendChild(card);
        });
    }

    /* ============================
       MONTH VIEW: DAY POPOVER
       ============================ */
    function showDayPopover(triggerEl, date, dayEvents) {
        const count = dayEvents.length;
        const revenue = dayEvents.reduce((sum, ev) => sum + (ext(ev).service_price || 0), 0);

        let listHtml = '';
        dayEvents.forEach(ev => {
            const e = ext(ev);
            const s = statusInfo(e.status);
            listHtml += `
                <li class="cal-day-pop-item">
                    <span class="cal-day-pop-time">${fmtTime(ev.start || ev.startStr)}</span>
                    <div class="cal-day-pop-info">
                        <div class="cal-day-pop-name">${e.customer_name || ev.title}</div>
                        <div class="cal-day-pop-service">${e.service_name || ''} · <span class="cal-status-badge ${s.badge}">${e.display_status || s.label}</span></div>
                    </div>
                </li>`;
        });

        const html = `
            <div class="cal-day-pop-summary">
                <strong>🗓 ${count} lịch hẹn</strong>
                <span>💰 ${fmt(revenue)}</span>
            </div>
            <ul class="cal-day-pop-list">${listHtml}</ul>
        `;

        activePopover = new bootstrap.Popover(triggerEl, {
            html: true,
            trigger: 'manual',
            placement: 'right',
            fallbackPlacements: ['left', 'top', 'bottom'],
            customClass: 'cal-day-popover',
            title: `📅 ${fmtDate(date)}`,
            content: html,
            sanitize: false,
            container: 'body'
        });
        activePopover.show();
    }

    /* ============================
       DAY OFFCANVAS (Month click)
       ============================ */
    function showDayOffcanvas(date, dayEvents) {
        const oc = document.getElementById('calOffcanvas');
        const ocTitle = oc.querySelector('.offcanvas-title');
        const ocBody = oc.querySelector('.offcanvas-body');

        ocTitle.textContent = '📅 Lịch hẹn ngày ' + fmtDateShort(date);

        const count = dayEvents.length;
        const revenue = dayEvents.reduce((sum, ev) => sum + (ext(ev).service_price || 0), 0);

        let itemsHtml = '';
        if (count === 0) {
            itemsHtml = `<div class="cal-oc-empty"><i class="bi bi-calendar-x"></i>Không có lịch hẹn</div>`;
        } else {
            dayEvents.forEach(ev => {
                const e = ext(ev);
                const s = statusInfo(e.status);
                itemsHtml += `
                    <div class="cal-oc-item">
                        <div class="cal-oc-item-header">
                            <span class="cal-oc-time-badge">${fmtTime(ev.start || ev.startStr)}</span>
                            <span class="cal-oc-customer">${e.customer_name || ev.title}</span>
                            <span class="cal-status-badge ${s.badge}">${s.label}</span>
                        </div>
                        <div class="cal-oc-detail-grid">
                            <span class="cal-oc-label">SĐT:</span>
                            <span class="cal-oc-value">${e.customer_phone || '—'}</span>
                            <span class="cal-oc-label">Dịch vụ:</span>
                            <span class="cal-oc-value">${e.service_name || '—'}</span>
                            <span class="cal-oc-label">Thời lượng:</span>
                            <span class="cal-oc-value">${e.service_duration || 30} phút</span>
                            <span class="cal-oc-label">Giá:</span>
                            <span class="cal-oc-value">${fmt(e.service_price || 0)}</span>
                            ${e.notes ? `<span class="cal-oc-label">Ghi chú:</span><span class="cal-oc-value">${e.notes}</span>` : ''}
                        </div>
                        <div class="cal-oc-actions">
                            <a href="${e.edit_url || '#'}" class="btn btn-outline-primary btn-sm"><i class="bi bi-pencil"></i> Sửa</a>
                            <button class="btn btn-outline-warning btn-sm cal-oc-status-btn" data-id="${ev.id || e.id}"><i class="bi bi-arrow-repeat"></i> Trạng thái</button>
                            <a href="${e.detail_url || '#'}" class="btn btn-outline-secondary btn-sm"><i class="bi bi-eye"></i> Chi tiết</a>
                        </div>
                    </div>`;
            });
        }

        ocBody.innerHTML = `
            <div class="cal-oc-day-header">
                <h6>📋 ${fmtDate(date)}</h6>
                <span class="cal-oc-day-stats">${count} lịch · ${fmt(revenue)}</span>
            </div>
            <div class="cal-oc-list">${itemsHtml}</div>
        `;

        if (!offcanvasInstance) {
            offcanvasInstance = new bootstrap.Offcanvas(oc);
        }
        offcanvasInstance.show();
    }

    /* ============================
       EVENT OFFCANVAS (Week/Day click)
       ============================ */
    function showEventOffcanvas(event) {
        const e = ext(event);
        const s = statusInfo(e.status);
        const oc = document.getElementById('calOffcanvas');
        const ocTitle = oc.querySelector('.offcanvas-title');
        const ocBody = oc.querySelector('.offcanvas-body');
        const csrfToken = window.SpaCsrf ? window.SpaCsrf.getToken() : '';

        ocTitle.textContent = '📋 Chi tiết lịch hẹn';

        const statusDropdownHtml = Object.entries(STATUS_MAP).map(([key, val]) => {
            const active = key === e.status ? 'active fw-bold' : '';
            return `<li><a class="dropdown-item ${active}" href="#" data-status="${key}"><i class="bi ${val.bi} me-2"></i>${val.label}</a></li>`;
        }).join('');

        ocBody.innerHTML = `
            <div class="cal-oc-single">
                <div class="cal-oc-single-header">
                    <span class="cal-status-badge ${s.badge}" style="font-size:0.75rem;padding:4px 12px;">${s.label}</span>
                    <span class="cal-oc-single-name">${e.customer_name || event.title}</span>
                </div>
                <div class="cal-oc-single-grid">
                    <span class="cal-oc-single-label">Khách hàng</span>
                    <span class="cal-oc-single-value">${e.customer_name || event.title}</span>
                    <span class="cal-oc-single-label">SĐT</span>
                    <span class="cal-oc-single-value">${e.customer_phone || '—'}</span>
                    <span class="cal-oc-single-label">Dịch vụ</span>
                    <span class="cal-oc-single-value">${e.service_name || '—'}</span>
                    <span class="cal-oc-single-label">Ngày</span>
                    <span class="cal-oc-single-value">${fmtDateShort(event.start || event.startStr)}</span>
                    <span class="cal-oc-single-label">Giờ</span>
                    <span class="cal-oc-single-value">${fmtTime(event.start || event.startStr)} - ${fmtTime(event.end || event.endStr)}</span>
                    <span class="cal-oc-single-label">Thời lượng</span>
                    <span class="cal-oc-single-value">${e.service_duration || 30} phút</span>
                    <span class="cal-oc-single-label">Giá</span>
                    <span class="cal-oc-single-value fw-bold">${fmt(e.service_price || 0)}</span>
                    <span class="cal-oc-single-label">Trạng thái</span>
                    <span class="cal-oc-single-value">
                        <div class="dropdown cal-oc-status-dropdown">
                            <button class="btn btn-sm dropdown-toggle cal-status-badge ${s.badge}" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                                ${s.label}
                            </button>
                            <ul class="dropdown-menu">${statusDropdownHtml}</ul>
                        </div>
                    </span>
                    ${e.notes ? `<span class="cal-oc-single-label">Ghi chú</span><span class="cal-oc-single-value">${e.notes}</span>` : ''}
                </div>
                <div class="cal-oc-single-actions">
                    <a href="${e.edit_url || '#'}" class="btn btn-primary"><i class="bi bi-pencil me-1"></i>Sửa</a>
                    <a href="${e.detail_url || '#'}" class="btn btn-outline-secondary"><i class="bi bi-eye me-1"></i>Xem</a>
                    <form action="${e.delete_url || '#'}" method="POST" class="d-inline" onsubmit="return confirm('Bạn chắc chắn muốn xóa?')">
                        <input type="hidden" name="csrf_token" value="${csrfToken}">
                        <button type="submit" class="btn btn-outline-danger"><i class="bi bi-trash me-1"></i>Xóa</button>
                    </form>
                </div>
            </div>
        `;

        // Bind status dropdown actions
        ocBody.querySelectorAll('.cal-oc-status-dropdown .dropdown-item').forEach(item => {
            item.addEventListener('click', function (ev) {
                ev.preventDefault();
                const newStatus = this.getAttribute('data-status');
                updateEventStatus(event.id || e.id, newStatus);
            });
        });

        if (!offcanvasInstance) {
            offcanvasInstance = new bootstrap.Offcanvas(oc);
        }
        offcanvasInstance.show();
    }

    /* ============================
       UPDATE STATUS VIA API
       ============================ */
    async function updateEventStatus(id, newStatus) {
        try {
            const resp = await csrfFetch(UPDATE_STATUS_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id, status: newStatus })
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Failed');

            // Refresh calendar
            if (calendarInstance) {
                calendarInstance.refetchEvents();
            }

            // Close offcanvas
            if (offcanvasInstance) offcanvasInstance.hide();

            Notification.success('Đã cập nhật trạng thái thành công');
        } catch (err) {
            Notification.error('Không thể cập nhật trạng thái');
            console.error(err);
        }
    }

    /* ============================
       EVENT POPOVER (Hover, Week/Day)
       ============================ */
    function showEventPopover(info) {
        if (isMobile()) return;

        destroyActivePopover();
        const ev = info.event;
        const e = ext(ev);
        const s = statusInfo(e.status);

        const html = `
            <div class="cal-pop-row"><span class="cal-pop-label">Khách</span><span class="cal-pop-value">${e.customer_name || ev.title}</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">SĐT</span><span class="cal-pop-value">${e.customer_phone || '—'}</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Dịch vụ</span><span class="cal-pop-value">${e.service_name || '—'}</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Ngày</span><span class="cal-pop-value">${fmtDateShort(ev.start)}</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Giờ</span><span class="cal-pop-value">${fmtTime(ev.start)} - ${fmtTime(ev.end)}</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Thời lượng</span><span class="cal-pop-value">${e.service_duration || 30} phút</span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Trạng thái</span><span class="cal-pop-value"><span class="cal-status-badge ${s.badge}">${e.display_status || s.label}</span></span></div>
            <div class="cal-pop-row"><span class="cal-pop-label">Giá</span><span class="cal-pop-value fw-bold">${fmt(e.service_price || 0)}</span></div>
            ${e.notes ? `<div class="cal-pop-row"><span class="cal-pop-label">Ghi chú</span><span class="cal-pop-value">${e.notes}</span></div>` : ''}
        `;

        activePopover = new bootstrap.Popover(info.el, {
            html: true,
            trigger: 'manual',
            placement: 'right',
            fallbackPlacements: ['left', 'top', 'bottom'],
            customClass: 'cal-popover',
            title: e.customer_name || ev.title,
            content: html,
            sanitize: false,
            container: 'body'
        });
        activePopover.show();
    }

    /* ============================
       FULLCALENDAR INIT
       ============================ */
    function initCalendar() {
        const calEl = document.getElementById('calendar');
        if (!calEl) return;

        calendarInstance = new FullCalendar.Calendar(calEl, {
            /* -- Core -- */
            initialView: 'dayGridMonth',
            locale: 'vi',
            firstDay: 1,
            height: 'auto',
            navLinks: false,
            editable: false,
            selectable: false,
            dayMaxEvents: false,
            fixedWeekCount: false,

            /* -- Header Toolbar -- */
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay'
            },

            buttonText: {
                today: 'Hôm nay',
                month: 'Tháng',
                week: 'Tuần',
                day: 'Ngày'
            },

            /* -- Time Grid Config -- */
            slotMinTime: '00:00:00',
            slotMaxTime: '24:00:00',
            scrollTime: '08:00:00',
            slotDuration: '00:30:00',
            slotLabelFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
            eventMinHeight: 46,
            allDaySlot: false,

            /* -- Event Source -- */
            events: function (fetchInfo, successCallback, failureCallback) {
                fetch(EVENTS_URL)
                    .then(r => r.json())
                    .then(data => {
                        allEvents = data;
                        successCallback(data);
                    })
                    .catch(err => {
                        console.error('Error fetching events:', err);
                        failureCallback(err);
                    });
            },

            /* -- Month View: suppress default event rendering -- */
            eventContent: function (arg) {
                const viewType = arg.view.type;

                if (viewType === 'dayGridMonth') {
                    // Return empty so default events are hidden; we use Summary Cards
                    return { domNodes: [] };
                }

                // Week & Day: compact layout
                const e = ext(arg.event);
                const s = statusInfo(e.status);
                const time = fmtTime(arg.event.start);

                const wrapper = document.createElement('div');
                wrapper.className = 'cal-evt';
                wrapper.innerHTML = `
                    <div class="cal-evt-info">
                        <span class="cal-evt-time">${time}</span>
                        <span class="cal-evt-name">${e.customer_name || arg.event.title}</span>
                    </div>
                    <span class="cal-evt-icon" title="${e.display_status || s.label}">${s.icon}</span>
                `;

                return { domNodes: [wrapper] };
            },

            /* -- Apply status color classes & prevent URL navigation -- */
            eventDidMount: function (info) {
                // Remove href to prevent FullCalendar from navigating via event url
                info.el.removeAttribute('href');
                info.el.style.cursor = 'pointer';

                const viewType = info.view.type;
                if (viewType === 'dayGridMonth') return;

                const e = ext(info.event);
                const s = statusInfo(e.status);
                info.el.classList.add('fc-evt-' + s.cls);

                // Desktop hover popover
                if (!isMobile()) {
                    info.el.addEventListener('mouseenter', () => showEventPopover(info));
                    info.el.addEventListener('mouseleave', () => {
                        setTimeout(() => {
                            const popEl = document.querySelector('.cal-popover:hover');
                            if (!popEl) destroyActivePopover();
                        }, 200);
                    });
                }
            },

            /* -- Click: Offcanvas -- */
            eventClick: function (info) {
                info.jsEvent.preventDefault();
                info.jsEvent.stopPropagation();
                destroyActivePopover();

                const viewType = info.view.type;
                if (viewType === 'dayGridMonth') {
                    // Clicking in month view — handled by summary card
                    return;
                }

                document.querySelectorAll('.fc-event').forEach(el => el.classList.remove('active-event'));
                info.el.classList.add('active-event');

                showEventOffcanvas(info.event);
            },

            /* -- Month View: render summaries after events load -- */
            eventsSet: function () {
                const view = calendarInstance.view;
                if (view && view.type === 'dayGridMonth') {
                    setTimeout(renderMonthSummaries, 50);
                }
            },

            /* -- View change: cleanup -- */
            viewDidMount: function () {
                destroyActivePopover();
            },

            datesSet: function () {
                destroyActivePopover();
                const view = calendarInstance.view;
                if (view && view.type === 'dayGridMonth') {
                    setTimeout(renderMonthSummaries, 100);
                }
            }
        });

        calendarInstance.render();

        // Expose globally so view-toggle can call updateSize()
        window.spaCalendarInstance = calendarInstance;
    }

    /* ============================
       INIT ON DOM READY
       ============================ */

    // Expose init function globally so view-toggle can call it lazily
    window.spaCalendarInit = function () {
        if (calendarInstance) {
            // Already initialized, just refresh size
            calendarInstance.updateSize();
            return;
        }
        initCalendar();
    };

    document.addEventListener('DOMContentLoaded', function () {
        const container = document.getElementById('calendar-view-container');
        if (!container) return;

        const calEl = document.getElementById('calendar');
        if (!calEl) return;

        // If calendar container is already visible on load, init immediately
        if (container.offsetParent !== null || container.style.display !== 'none') {
            initCalendar();
        }
        // Otherwise, initCalendar will be called by the view-toggle in appointment.js

        // Listen to offcanvas close to clear active states
        const oc = document.getElementById('calOffcanvas');
        if (oc) {
            oc.addEventListener('hidden.bs.offcanvas', function () {
                document.querySelectorAll('.spa-summary-card').forEach(c => c.classList.remove('active-card'));
                document.querySelectorAll('.fc-event').forEach(el => el.classList.remove('active-event'));
            });
        }

        // Global click to destroy popovers
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.cal-popover, .cal-day-popover, .spa-summary-card, .fc-event')) {
                destroyActivePopover();
            }
        });
    });

})();
