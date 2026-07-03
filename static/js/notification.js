/**
 * notification.js - Unified Notification Service for SpaManager
 * Standardizes app notifications using elegant, interactive, stackable Toast notifications.
 * Supports Promises, progress bar timers, and contextual styling.
 */

(function () {
    'use strict';

    class NotificationService {
        constructor() {
            this.container = null;
            // Bind methods to this instance
            this.success = this.success.bind(this);
            this.error = this.error.bind(this);
            this.warning = this.warning.bind(this);
            this.info = this.info.bind(this);
        }

        /**
         * Initialize toast container in DOM if it does not exist
         * @private
         */
        _initContainer() {
            this.container = document.getElementById('toast-container');
            if (!this.container) {
                this.container = document.createElement('div');
                this.container.id = 'toast-container';
                this.container.className = 'toast-container';
                document.body.appendChild(this.container);
            }
        }

        /**
         * Display a contextual toast notification
         * @param {string} type - 'success', 'error', 'warning', 'info'
         * @param {string} message - The notification message
         * @param {number} duration - Auto-hide timeout in ms (default: 5000)
         * @returns {Promise<void>} Resolves when the toast is completely dismissed
         * @private
         */
        _show(type, message, duration = 5000) {
            return new Promise((resolve) => {
                this._initContainer();

                // Create Toast wrapper
                const toast = document.createElement('div');
                toast.className = `spa-toast spa-toast-${type} fade`;
                toast.setAttribute('role', 'alert');
                toast.setAttribute('aria-live', 'assertive');
                toast.setAttribute('aria-atomic', 'true');

                // Determine icon based on context type
                let iconClass = 'bi-check-circle-fill';
                if (type === 'error') {
                    iconClass = 'bi-x-circle-fill';
                } else if (type === 'warning') {
                    iconClass = 'bi-exclamation-triangle-fill';
                } else if (type === 'info') {
                    iconClass = 'bi-info-circle-fill';
                }

                // Internal template structure
                toast.innerHTML = `
                    <div class="spa-toast-body">
                        <span class="spa-toast-icon">
                            <i class="bi ${iconClass}"></i>
                        </span>
                        <div class="spa-toast-content">
                            <span class="spa-toast-message"></span>
                        </div>
                        <button type="button" class="spa-toast-close" aria-label="Close">
                            <i class="bi bi-x"></i>
                        </button>
                    </div>
                    <div class="spa-toast-progress">
                        <div class="spa-toast-progress-bar"></div>
                    </div>
                `;

                // Safe text injection to prevent XSS
                toast.querySelector('.spa-toast-message').textContent = message;

                this.container.appendChild(toast);

                // Trigger layout reflow for CSS transition
                toast.offsetHeight;
                toast.classList.add('show');

                let autoHideTimeout = null;
                let progressInterval = null;

                // Handle fade out and cleanup
                const dismiss = () => {
                    if (autoHideTimeout) clearTimeout(autoHideTimeout);
                    if (progressInterval) clearInterval(progressInterval);

                    toast.classList.remove('show');
                    toast.classList.add('fading-out');

                    // Listener for removal when transition finishes
                    const onTransitionEnd = (e) => {
                        if (e.propertyName === 'opacity' || e.propertyName === 'transform') {
                            toast.removeEventListener('transitionend', onTransitionEnd);
                            toast.remove();
                            resolve();
                        }
                    };

                    toast.addEventListener('transitionend', onTransitionEnd);

                    // Fallback cleanup if event does not fire
                    setTimeout(() => {
                        if (toast.parentNode) {
                            toast.remove();
                            resolve();
                        }
                    }, 500);
                };

                // Close button event
                const closeButton = toast.querySelector('.spa-toast-close');
                closeButton.addEventListener('click', (e) => {
                    e.stopPropagation();
                    dismiss();
                });

                // Progress Bar animation & Timer
                const progressBar = toast.querySelector('.spa-toast-progress-bar');
                const startTime = Date.now();

                progressInterval = setInterval(() => {
                    const elapsed = Date.now() - startTime;
                    const remainingPercent = Math.max(0, 100 - (elapsed / duration) * 100);
                    progressBar.style.width = `${remainingPercent}%`;

                    if (remainingPercent <= 0) {
                        clearInterval(progressInterval);
                    }
                }, 16); // ~60fps smooth progress bar updates

                autoHideTimeout = setTimeout(dismiss, duration);
            });
        }

        success(message, duration) {
            return this._show('success', message, duration);
        }

        error(message, duration) {
            return this._show('error', message, duration);
        }

        warning(message, duration) {
            return this._show('warning', message, duration);
        }

        info(message, duration) {
            return this._show('info', message, duration);
        }
    }

    /**
     * ========================================================================
     * SINGLETON LIFECYCLE REGISTRATION
     * ========================================================================
     * NotificationService is exposed globally as window.Notification and
     * window.NotificationService. This ensures a single, state-aware toast
     * manager handles stackable alerts, avoiding duplicate toast container elements.
     */
    const notificationInstance = new NotificationService();
    window.Notification = notificationInstance;
    window.NotificationService = notificationInstance;

})();
