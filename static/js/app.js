/**
 * app.js - SpaManager UI Motion & Interaction Module
 * Standardizes transitions, animations, loading states, and user interaction indicators.
 */

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        // 1. Dismiss Page Loader Overlay
        const loader = document.getElementById('page-loader');
        if (loader) {
            loader.classList.add('fade-out');
        }

        // 2. Initialize Tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        if (tooltipTriggerList.length > 0 && typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
            tooltipTriggerList.map(function (el) {
                return new bootstrap.Tooltip(el);
            });
        }

        // 3. Handle Form Submission Buttons (Lưu, Lọc, and other primary submits)
        document.addEventListener('submit', function (e) {
            const form = e.target;
            if (form && form.tagName === 'FORM') {
                // If form has custom validation and is invalid, let the validation run
                if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
                    return;
                }

                const submitBtns = form.querySelectorAll('button[type="submit"], input[type="submit"]');
                submitBtns.forEach(btn => {
                    const text = btn.textContent.trim().toLowerCase();
                    const isDelete = text.includes('xóa') || btn.classList.contains('btn-delete') || btn.classList.contains('btn-outline-danger');
                    
                    if (!isDelete) {
                        const originalHtml = btn.innerHTML;
                        btn.disabled = true;
                        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang xử lý...';

                        // Restore after 2.5 seconds in case the page does not reload (e.g., file downloads/exports, background validations)
                        setTimeout(() => {
                            btn.disabled = false;
                            btn.innerHTML = originalHtml;
                        }, 2500);
                    }
                });
            }
        });

        // 4. Handle Independent Action Buttons & Exports (Xuất Excel, Xuất PDF, Lọc, Lưu)
        document.addEventListener('click', function (e) {
            const btn = e.target.closest('a.btn, button.btn, a.app-btn, button.app-btn, button.btn-topbar');
            if (!btn) return;

            // If it's a submit button inside a form, let the form submit event handle it.
            if (btn.tagName === 'BUTTON' && btn.type === 'submit') {
                return;
            }

            const text = btn.textContent.trim().toLowerCase();
            const isExcel = text.includes('xuất excel') || btn.innerHTML.includes('bi-file-earmark-excel');
            const isPdf = text.includes('xuất pdf') || btn.innerHTML.includes('bi-file-earmark-pdf');
            const isFilter = text.includes('lọc') || btn.classList.contains('btn-filter');
            const isSave = text.includes('lưu');

            if (isExcel || isPdf || isFilter || isSave) {
                const originalHtml = btn.innerHTML;
                
                // Temporarily disable the action button to prevent double-clicks
                btn.style.pointerEvents = 'none';
                btn.classList.add('disabled');
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang xử lý...';

                // Re-enable after 2.5 seconds because exports do not redirect/unload the current page
                setTimeout(() => {
                    btn.style.pointerEvents = '';
                    btn.classList.remove('disabled');
                    btn.innerHTML = originalHtml;
                }, 2500);
            }
        });

        // 7. Focus Trap Implementation for Accessibility (WCAG 2.1 AA)
        const focusableElementsSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
        
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            
            // Find active open Bootstrap Modal or Offcanvas
            const openModal = document.querySelector('.modal.show, .offcanvas.show');
            if (!openModal) return;
            
            const focusableContent = openModal.querySelectorAll(focusableElementsSelector);
            if (focusableContent.length === 0) return;
            
            const firstFocusableElement = focusableContent[0];
            const lastFocusableElement = focusableContent[focusableContent.length - 1];
            
            if (e.shiftKey) { // Shift + Tab
                if (document.activeElement === firstFocusableElement) {
                    lastFocusableElement.focus();
                    e.preventDefault();
                }
            } else { // Tab
                if (document.activeElement === lastFocusableElement) {
                    firstFocusableElement.focus();
                    e.preventDefault();
                }
            }
        });

        // 8. Mobile Sidebar Navigation Drawer, Gestures, ESC Close, Overlay & Scroll Locking
        const sidebar = document.querySelector('.sidebar');
        const sidebarOverlay = document.getElementById('sidebar-overlay');
        const sidebarToggle = document.getElementById('sidebar-toggle');
        
        function openSidebar() {
            if (!sidebar) return;
            sidebar.classList.add('active');
            if (sidebarOverlay) {
                sidebarOverlay.style.display = 'block';
                // Trigger reflow
                sidebarOverlay.offsetHeight;
                sidebarOverlay.classList.add('active');
            }
            document.body.classList.add('sidebar-open');
        }
        
        function closeSidebar() {
            if (!sidebar) return;
            sidebar.classList.remove('active');
            if (sidebarOverlay) {
                sidebarOverlay.classList.remove('active');
                setTimeout(() => {
                    if (!sidebar.classList.contains('active')) {
                        sidebarOverlay.style.display = 'none';
                    }
                }, 250);
            }
            document.body.classList.remove('sidebar-open');
        }
        
        if (sidebarToggle) {
            sidebarToggle.addEventListener('click', openSidebar);
        }
        
        if (sidebarOverlay) {
            sidebarOverlay.addEventListener('click', closeSidebar);
        }
        
        // Escape key closes sidebar
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeSidebar();
            }
        });
        
        // Focus Trap within Sidebar when open
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            if (!sidebar || !sidebar.classList.contains('active')) return;
            
            // Only apply focus trap if sidebar is visible as a drawer (mobile/tablet screen size)
            if (window.innerWidth >= 992) return;
            
            const focusableContent = sidebar.querySelectorAll(focusableElementsSelector);
            if (focusableContent.length === 0) return;
            
            const firstFocusableElement = focusableContent[0];
            const lastFocusableElement = focusableContent[focusableContent.length - 1];
            
            if (e.shiftKey) {
                if (document.activeElement === firstFocusableElement) {
                    lastFocusableElement.focus();
                    e.preventDefault();
                }
            } else {
                if (document.activeElement === lastFocusableElement) {
                    firstFocusableElement.focus();
                    e.preventDefault();
                }
            }
        });
        
        // Swipe close gesture detection
        let touchStartX = 0;
        let touchEndX = 0;
        
        document.addEventListener('touchstart', function (e) {
            touchStartX = e.changedTouches[0].screenX;
        }, { passive: true });
        
        document.addEventListener('touchend', function (e) {
            touchEndX = e.changedTouches[0].screenX;
            handleSwipe();
        }, { passive: true });
        
        function handleSwipe() {
            // If sidebar is open and swipe left (more than 50px), close it
            if (sidebar && sidebar.classList.contains('active')) {
                if (touchStartX - touchEndX > 50) {
                    closeSidebar();
                }
            }
        }

        // 9. Pre-populate sidebar links with saved STF state to prevent double page loads
        document.querySelectorAll('.menu-item').forEach(link => {
            const href = link.getAttribute('href');
            if (!href) return;
            
            // Extract module name from url path
            let module = '';
            if (href.includes('/customers')) module = 'customer';
            else if (href.includes('/services')) module = 'service';
            else if (href.includes('/appointments')) module = 'appointment';
            else if (href.includes('/invoices')) module = 'invoice';
            else if (href.includes('/recycle-bin')) module = 'recycle_bin';
            else if (href.includes('/activity-logs')) module = 'activity_log';
            
            if (module) {
                try {
                    const saved = JSON.parse(localStorage.getItem('stf_' + module + '_state'));
                    if (saved && Object.keys(saved).length > 0) {
                        const u = new URL(href, window.location.origin);
                        if (saved.per_page && parseInt(saved.per_page) !== 25) {
                            u.searchParams.set('per_page', saved.per_page);
                        }
                        if (saved.sort_by) {
                            u.searchParams.set('sort_by', saved.sort_by);
                        }
                        if (saved.sort_dir) {
                            u.searchParams.set('sort_dir', saved.sort_dir);
                        }
                        link.setAttribute('href', u.pathname + u.search);
                    }
                } catch (e) {}
            }
        });
    });

    // 5. Restore page loader when navigating away (excluding anchors, tel, mailto, target="_blank", and download/export links)
    window.addEventListener('beforeunload', function (e) {
        const activeEl = document.activeElement;
        if (activeEl && activeEl.tagName === 'A') {
            const href = activeEl.getAttribute('href');
            const target = activeEl.getAttribute('target');
            const isDownload = href && (href.includes('template') || href.includes('download') || href.includes('export') || href.includes('backup') || href.includes('print') || activeEl.hasAttribute('download') || activeEl.classList.contains('no-loader'));
            if (href && !href.startsWith('#') && !href.startsWith('javascript:') && !href.startsWith('mailto:') && !href.startsWith('tel:') && target !== '_blank' && !isDownload) {
                const loader = document.getElementById('page-loader');
                if (loader) {
                    loader.classList.remove('fade-out');
                }
            }
        } else if (activeEl && (activeEl.tagName === 'BUTTON' || activeEl.type === 'submit')) {
            // Do not show loader if it's an export/download/backup button or export form submission
            const text = activeEl.textContent.trim().toLowerCase();
            const isExcel = text.includes('xuất excel') || activeEl.innerHTML.includes('bi-file-earmark-excel');
            const isPdf = text.includes('xuất pdf') || activeEl.innerHTML.includes('bi-file-earmark-pdf');
            
            const form = activeEl.closest('form');
            const action = form ? form.getAttribute('action') || '' : '';
            const isExportAction = action.includes('export') || action.includes('pdf') || action.includes('excel') || action.includes('backup') || action.includes('download') || action.includes('template') || action.includes('print');

            if (isExcel || isPdf || isExportAction) {
                return;
            }

            // Also show loader for forms that trigger page unload on submit
            const loader = document.getElementById('page-loader');
            if (loader) {
                loader.classList.remove('fade-out');
            }
        }
    });

    // 6. Dismiss Page Loader when page is shown (handles Back/Forward navigation from bfcache)
    window.addEventListener('pageshow', function (event) {
        const loader = document.getElementById('page-loader');
        if (loader) {
            loader.classList.add('fade-out');
            if (event.persisted) {
                // If loaded from Back/Forward Cache, force hide the loader immediately
                loader.style.display = 'none';
            }
        }
    });

})();
