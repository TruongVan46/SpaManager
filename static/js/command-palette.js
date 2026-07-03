/* command-palette.js */

(function () {
    'use strict';

    // 1. Action Registry
    class ActionRegistry {
        constructor() {
            this.actions = [];
        }

        register(action) {
            // action: { id, title, shortcut, category, handler, icon }
            this.actions.push(action);
        }

        getActions() {
            return this.actions;
        }
    }

    // 2. Shortcut Manager
    class ShortcutManager {
        constructor(registry, paletteService) {
            this.registry = registry;
            this.paletteService = paletteService;
            this.initListeners();
        }

        isInputField(el) {
            if (!el) return false;
            const tagName = el.tagName;
            return tagName === 'INPUT' || 
                   tagName === 'TEXTAREA' || 
                   tagName === 'SELECT' || 
                   el.hasAttribute('contenteditable') || 
                   el.isContentEditable;
        }

        initListeners() {
            window.addEventListener('keydown', (e) => {
                const activeEl = document.activeElement;
                const isTyping = this.isInputField(activeEl);

                // Global keys active even while typing: Ctrl+K (Palette) and Escape (Close)
                const isCtrlK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k';
                if (isCtrlK) {
                    e.preventDefault();
                    this.paletteService.toggle();
                    return;
                }

                if (e.key === 'Escape') {
                    if (this.paletteService.isOpen) {
                        e.preventDefault();
                        this.paletteService.close();
                    } else {
                        // Close any open standard Bootstrap modals
                        const activeModals = document.querySelectorAll('.modal.show');
                        if (activeModals.length > 0) {
                            activeModals.forEach(modalEl => {
                                const modal = bootstrap.Modal.getInstance(modalEl);
                                if (modal) modal.hide();
                            });
                            e.preventDefault();
                        }
                    }
                    return;
                }

                // If currently typing, block all other global navigation/action shortcuts
                if (isTyping) {
                    return;
                }

                // Focus page search shortcut: Ctrl + /
                if ((e.ctrlKey || e.metaKey) && e.key === '/') {
                    e.preventDefault();
                    const searchInput = document.querySelector('[data-stf-search]') || 
                                        document.querySelector('input[name="q"]') || 
                                        document.querySelector('input[type="search"]');
                    if (searchInput) {
                        searchInput.focus();
                        searchInput.select();
                    }
                    return;
                }

                // Navigation Shortcuts: Ctrl + Shift + key
                if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
                    const key = e.key.toUpperCase();
                    let targetUrl = null;

                    switch (key) {
                        case 'D': targetUrl = '/'; break;
                        case 'C': targetUrl = '/customers'; break;
                        case 'S': targetUrl = '/services'; break;
                        case 'A': targetUrl = '/appointments'; break;
                        case 'I': targetUrl = '/invoices'; break;
                        case 'T': targetUrl = '/statistics'; break;
                        case 'R': targetUrl = '/recycle-bin'; break;
                        case 'O': targetUrl = '/activity-logs'; break;
                        case 'P': targetUrl = '/settings'; break;
                    }

                    if (targetUrl) {
                        e.preventDefault();
                        window.location.href = targetUrl;
                    }
                }
            });
        }
    }

    // 3. Command Palette Service
    class CommandPaletteService {
        constructor(registry) {
            this.registry = registry;
            this.isOpen = false;
            this.overlay = null;
            this.input = null;
            this.resultsContainer = null;
            this.selectedIndex = -1;
            this.filteredActions = [];
        }

        init() {
            this.overlay = document.getElementById('command-palette-overlay');
            if (!this.overlay) return;

            this.input = document.getElementById('command-palette-input');
            this.resultsContainer = document.getElementById('command-palette-results');

            // Prevent closing when clicking content
            const container = this.overlay.querySelector('.command-palette-container');
            container.addEventListener('click', (e) => e.stopPropagation());

            // Close when overlay backdrop is clicked
            this.overlay.addEventListener('click', () => this.close());

            // Handle typing inside search input
            this.input.addEventListener('input', () => {
                this.selectedIndex = 0;
                this.render();
            });

            // Handle keyboard navigation inside search input
            this.input.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.navigateSelection(1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.navigateSelection(-1);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    this.executeSelection();
                } else if (e.key === 'Tab') {
                    e.preventDefault(); // Maintain focus in input
                }
            });
        }

        toggle() {
            if (this.isOpen) {
                this.close();
            } else {
                this.open();
            }
        }

        open() {
            if (!this.overlay) this.init();
            if (!this.overlay) return;

            this.overlay.style.display = 'flex';
            this.isOpen = true;
            this.selectedIndex = 0;
            this.input.value = '';
            this.render();

            // Small delay to ensure display: flex is rendered before focus
            setTimeout(() => {
                this.input.focus();
            }, 50);
        }

        close() {
            if (!this.overlay) return;
            this.overlay.style.display = 'none';
            this.isOpen = false;
            this.selectedIndex = -1;
            this.input.blur();
        }

        navigateSelection(direction) {
            const items = this.resultsContainer.querySelectorAll('.command-palette-item');
            if (items.length === 0) return;

            this.selectedIndex += direction;

            if (this.selectedIndex < 0) {
                this.selectedIndex = items.length - 1;
            } else if (this.selectedIndex >= items.length) {
                this.selectedIndex = 0;
            }

            // Update active class on items
            items.forEach((item, index) => {
                if (index === this.selectedIndex) {
                    item.classList.add('active');
                    item.scrollIntoView({ block: 'nearest' });
                } else {
                    item.classList.remove('active');
                }
            });
        }

        executeSelection() {
            if (this.filteredActions.length === 0) return;
            const selectedAction = this.filteredActions[this.selectedIndex];
            if (selectedAction && typeof selectedAction.handler === 'function') {
                this.close();
                selectedAction.handler();
            }
        }

        highlightText(text, keyword) {
            if (!keyword) return text;
            const index = text.toLowerCase().indexOf(keyword.toLowerCase());
            if (index === -1) return text;
            const length = keyword.length;
            return text.substring(0, index) + 
                   '<mark class="search-highlight">' + 
                   text.substring(index, index + length) + 
                   '</mark>' + 
                   text.substring(index + length);
        }

        render() {
            const query = this.input.value.trim();
            const allActions = this.registry.getActions();
            
            let isActionPrefix = query.startsWith('>');
            let filterQuery = isActionPrefix ? query.substring(1).trim() : query;

            // Filter actions
            this.filteredActions = allActions.filter(action => {
                // If prefix is '>', restrict to category "Hành động"
                if (isActionPrefix && action.category !== 'Hành động') {
                    return false;
                }

                if (!filterQuery) return true;

                // Match query against title or category
                const titleMatch = action.title.toLowerCase().includes(filterQuery.toLowerCase());
                const categoryMatch = action.category.toLowerCase().includes(filterQuery.toLowerCase());
                return titleMatch || categoryMatch;
            });

            this.resultsContainer.innerHTML = '';

            if (this.filteredActions.length === 0) {
                this.resultsContainer.innerHTML = `
                    <div class="command-palette-no-results">
                        <i class="bi bi-search"></i>
                        Không tìm thấy lệnh hoặc trang nào phù hợp.
                    </div>
                `;
                return;
            }

            // Group filtered actions by category
            const groups = {};
            this.filteredActions.forEach((action, index) => {
                if (!groups[action.category]) {
                    groups[action.category] = [];
                }
                groups[action.category].push({ action, index });
            });

            // Build DOM elements
            let currentItemIndex = 0;
            Object.keys(groups).forEach(category => {
                // Render Group Header
                const groupHeader = document.createElement('div');
                groupHeader.className = 'command-palette-group-header';
                groupHeader.textContent = category;
                this.resultsContainer.appendChild(groupHeader);

                // Render group items
                groups[category].forEach(itemData => {
                    const action = itemData.action;
                    const index = itemData.index;

                    const item = document.createElement('div');
                    item.className = 'command-palette-item';
                    if (currentItemIndex === this.selectedIndex) {
                        item.classList.add('active');
                    }

                    // Left section: icon + highlighted title
                    const leftDiv = document.createElement('div');
                    leftDiv.className = 'command-palette-item-left';

                    const iconSpan = document.createElement('span');
                    iconSpan.className = 'command-palette-item-icon';
                    iconSpan.innerHTML = `<i class="bi ${action.icon || 'bi-chevron-right'}"></i>`;

                    const titleSpan = document.createElement('span');
                    titleSpan.className = 'command-palette-item-title';
                    titleSpan.innerHTML = this.highlightText(action.title, filterQuery);

                    leftDiv.appendChild(iconSpan);
                    leftDiv.appendChild(titleSpan);

                    // Right section: shortcut keys helper
                    const rightDiv = document.createElement('div');
                    rightDiv.className = 'command-palette-item-shortcut';
                    if (action.shortcut) {
                        action.shortcut.split('+').forEach(key => {
                            const kbd = document.createElement('kbd');
                            kbd.className = 'command-palette-key-badge';
                            kbd.textContent = key;
                            rightDiv.appendChild(kbd);
                        });
                    }

                    item.appendChild(leftDiv);
                    item.appendChild(rightDiv);

                    // Click handler
                    const itemSelectIndex = currentItemIndex;
                    item.addEventListener('click', () => {
                        this.selectedIndex = itemSelectIndex;
                        this.executeSelection();
                    });

                    // Mouseover to highlight on hover
                    item.addEventListener('mouseover', () => {
                        this.selectedIndex = itemSelectIndex;
                        const allItems = this.resultsContainer.querySelectorAll('.command-palette-item');
                        allItems.forEach((itm, idx) => {
                            if (idx === this.selectedIndex) {
                                itm.classList.add('active');
                            } else {
                                itm.classList.remove('active');
                            }
                        });
                    });

                    this.resultsContainer.appendChild(item);
                    currentItemIndex++;
                });
            });

            // Adjust index if out of bounds (e.g. after dynamic filter)
            if (this.selectedIndex >= currentItemIndex) {
                this.selectedIndex = 0;
                // Re-apply active class
                const items = this.resultsContainer.querySelectorAll('.command-palette-item');
                if (items.length > 0) items[0].classList.add('active');
            }
        }
    }

    /**
     * ========================================================================
     * LIFECYCLE & SINGLETON INITIALIZATION
     * ========================================================================
     * The command palette system consists of:
     * 1. ActionRegistry: Holds all navigation/action descriptors.
     * 2. CommandPaletteService (window.palette): Controls modal UI overlay state.
     * 3. ShortcutManager (window.shortcut): Manages global keydown shortcut triggers (e.g. Ctrl+K, Escape).
     *
     * These instances are constructed on DOMContentLoaded and bound to the IIFE closure,
     * protecting internal states from cross-module manipulation while keeping memory clean.
     */
    document.addEventListener('DOMContentLoaded', () => {
        const registry = new ActionRegistry();
        const palette = new CommandPaletteService(registry);
        const shortcut = new ShortcutManager(registry, palette);

        // --- Register Navigation Actions ---
        registry.register({
            id: 'nav-dashboard',
            title: 'Trang chủ',
            shortcut: 'Ctrl+Shift+D',
            category: 'Điều hướng',
            icon: 'bi-speedometer2',
            handler: () => window.location.href = '/'
        });

        registry.register({
            id: 'nav-customer',
            title: 'Khách hàng',
            shortcut: 'Ctrl+Shift+C',
            category: 'Điều hướng',
            icon: 'bi-people',
            handler: () => window.location.href = '/customers'
        });

        registry.register({
            id: 'nav-service',
            title: 'Dịch vụ',
            shortcut: 'Ctrl+Shift+S',
            category: 'Điều hướng',
            icon: 'bi-scissors',
            handler: () => window.location.href = '/services'
        });

        registry.register({
            id: 'nav-appointment',
            title: 'Lịch hẹn',
            shortcut: 'Ctrl+Shift+A',
            category: 'Điều hướng',
            icon: 'bi-calendar-check',
            handler: () => window.location.href = '/appointments'
        });

        registry.register({
            id: 'nav-invoice',
            title: 'Hóa đơn',
            shortcut: 'Ctrl+Shift+I',
            category: 'Điều hướng',
            icon: 'bi-receipt',
            handler: () => window.location.href = '/invoices'
        });

        registry.register({
            id: 'nav-statistics',
            title: 'Thống kê',
            shortcut: 'Ctrl+Shift+T',
            category: 'Điều hướng',
            icon: 'bi-graph-up-arrow',
            handler: () => window.location.href = '/statistics'
        });

        registry.register({
            id: 'nav-activity-log',
            title: 'Nhật ký hoạt động',
            shortcut: 'Ctrl+Shift+O',
            category: 'Điều hướng',
            icon: 'bi-clock-history',
            handler: () => window.location.href = '/activity-logs'
        });

        registry.register({
            id: 'nav-recycle-bin',
            title: 'Thùng rác',
            shortcut: 'Ctrl+Shift+R',
            category: 'Điều hướng',
            icon: 'bi-trash3',
            handler: () => window.location.href = '/recycle-bin'
        });

        registry.register({
            id: 'nav-setting',
            title: 'Cài đặt',
            shortcut: 'Ctrl+Shift+P',
            category: 'Điều hướng',
            icon: 'bi-gear',
            handler: () => window.location.href = '/settings'
        });

        // --- Register Action Commands (Prefixed with >) ---
        registry.register({
            id: 'action-new-customer',
            title: 'Thêm khách hàng mới',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-person-plus',
            handler: () => {
                if (window.location.pathname === '/customers') {
                    const btn = document.querySelector('a[href="/customers/create"]');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/customers/create';
                }
            }
        });

        registry.register({
            id: 'action-new-service',
            title: 'Thêm dịch vụ mới',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-plus-circle',
            handler: () => {
                if (window.location.pathname === '/services') {
                    const btn = document.querySelector('a[href="/services/create"]');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/services/create';
                }
            }
        });

        registry.register({
            id: 'action-new-appointment',
            title: 'Thêm lịch hẹn mới',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-calendar-plus',
            handler: () => {
                if (window.location.pathname === '/appointments') {
                    const btn = document.querySelector('a[href="/appointments/create"]');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/appointments/create';
                }
            }
        });

        registry.register({
            id: 'action-backup',
            title: 'Tạo bản sao lưu dữ liệu (Backup)',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-cloud-arrow-up',
            handler: () => {
                if (window.location.pathname === '/settings') {
                    const btn = document.querySelector('.btn-create-backup');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/settings?action=backup';
                }
            }
        });

        registry.register({
            id: 'action-restore',
            title: 'Khôi phục dữ liệu hệ thống (Restore)',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-cloud-arrow-down',
            handler: () => {
                if (window.location.pathname === '/settings') {
                    const card = document.getElementById('card-backup-center');
                    if (card) card.scrollIntoView({ behavior: 'smooth' });
                } else {
                    window.location.href = '/settings#card-backup-center';
                }
            }
        });

        registry.register({
            id: 'action-import',
            title: 'Nhập dữ liệu khách hàng/dịch vụ từ Excel (Import)',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-file-earmark-arrow-up',
            handler: () => {
                if (window.location.pathname === '/settings') {
                    const btn = document.querySelector('button[data-import-type="customers"]');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/settings?action=import';
                }
            }
        });

        registry.register({
            id: 'action-export',
            title: 'Xuất dữ liệu báo cáo (Export)',
            shortcut: '',
            category: 'Hành động',
            icon: 'bi-file-earmark-arrow-down',
            handler: () => {
                if (window.location.pathname === '/statistics') {
                    const btn = document.querySelector('.btn-success') || document.querySelector('.btn-danger');
                    if (btn) btn.click();
                } else {
                    window.location.href = '/statistics';
                }
            }
        });

        // Initialize elements
        palette.init();

        // Handle direct url actions (e.g. /settings?action=backup)
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('action') === 'backup') {
            const modalEl = document.getElementById('createBackupModal');
            if (modalEl) {
                setTimeout(() => {
                    const modal = new bootstrap.Modal(modalEl);
                    modal.show();
                }, 400);
            }
        } else if (urlParams.get('action') === 'import') {
            const btn = document.querySelector('button[data-import-type="customers"]');
            if (btn) {
                setTimeout(() => {
                    btn.click();
                }, 400);
            }
        }
    });

})();
