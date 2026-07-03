/**
 * @fileoverview ThemeManager Singleton for SpaManager.
 * Controls Light, Dark, and Auto (system-based) themes.
 * Emits change events and updates the HTML body class accordingly.
 * 
 * Target path: static/js/core/theme-manager.js
 */

const ThemeManager = (function() {
    /**
     * Current theme preference.
     * Can be 'light', 'dark', or 'auto'.
     * @type {string}
     * @private
     */
    let _currentTheme = 'auto';

    /**
     * Array of callback functions to execute when the theme changes.
     * @type {Array<Function>}
     * @private
     */
    const _callbacks = [];

    /**
     * Key used to persist theme preference in localStorage.
     * @type {string}
     * @private
     */
    const STORAGE_KEY = 'spa-theme';

    /**
     * Media query instance for prefers-color-scheme.
     * @type {MediaQueryList|null}
     * @private
     */
    let _mediaQuery = null;

    /**
     * Detects system theme preference.
     * @returns {string} 'light' or 'dark'
     */
    function detectSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    /**
     * Saves theme preference to localStorage.
     * @param {string} theme - 'light' | 'dark' | 'auto'
     * @private
     */
    function saveTheme(theme) {
        localStorage.setItem(STORAGE_KEY, theme);
    }

    /**
     * Loads theme preference from localStorage.
     * @returns {string} 'light' | 'dark' | 'auto'
     * @private
     */
    function loadTheme() {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored === 'light' || stored === 'dark' || stored === 'auto') {
            return stored;
        }
        return 'auto';
    }

    /**
     * Gets the effective active theme ('light' or 'dark') based on the current preference.
     * @returns {string} 'light' or 'dark'
     * @private
     */
    function getEffectiveTheme() {
        if (_currentTheme === 'auto') {
            return detectSystemTheme();
        }
        return _currentTheme;
    }

    /**
     * Applies the current theme class to the document body.
     * Emits events to all registered callback subscribers.
     */
    function applyTheme() {
        const effectiveTheme = getEffectiveTheme();
        const body = document.body;

        if (body) {
            if (effectiveTheme === 'dark') {
                body.classList.add('dark-theme');
                body.classList.remove('light-theme');
            } else {
                body.classList.add('light-theme');
                body.classList.remove('dark-theme');
            }
        }

        // Notify subscribers of the change
        notifyThemeChanged(effectiveTheme);
    }

    /**
     * Notifies all callback subscribers of a theme change event.
     * @param {string} effectiveTheme - 'light' | 'dark'
     * @private
     */
    function notifyThemeChanged(effectiveTheme) {
        _callbacks.forEach(callback => {
            try {
                callback(effectiveTheme, _currentTheme);
            } catch (err) {
                console.error('Error in onThemeChanged callback subscriber:', err);
            }
        });
    }

    /**
     * Binds UI theme switcher elements (if present on the page).
     * @private
     */
    function _bindSwitcherUI() {
        const switcherBtn = document.getElementById('theme-switcher-btn');
        const themeMenu = document.getElementById('theme-menu');
        if (!switcherBtn || !themeMenu) return;

        const iconMap = {
            light: 'bi-sun-fill text-warning',
            dark: 'bi-moon-stars-fill text-primary',
            auto: 'bi-circle-half text-info'
        };

        const textMap = {
            light: 'Sáng',
            dark: 'Tối',
            auto: 'Tự động'
        };

        const onThemeChangeCallback = function(effectiveTheme, currentTheme) {
            // Update button icon & text based on current theme setting
            const currentIcon = document.getElementById('theme-current-icon');
            const currentText = document.getElementById('theme-current-text');
            if (currentIcon) {
                currentIcon.className = `bi ${iconMap[currentTheme] || 'bi-circle-half'}`;
            }
            if (currentText) {
                currentText.textContent = textMap[currentTheme] || 'Tự động';
            }

            // Update active state checkmark inside the dropdown menu
            const items = themeMenu.querySelectorAll('[data-theme]');
            items.forEach(item => {
                const itemTheme = item.getAttribute('data-theme');
                const check = item.querySelector('.theme-check-icon');
                if (itemTheme === currentTheme) {
                    item.classList.add('active');
                    if (check) check.classList.remove('d-none');
                } else {
                    item.classList.remove('active');
                    if (check) check.classList.add('d-none');
                }
            });
        };

        // Listen for theme changes to update the active state in UI
        if (!_callbacks.includes(onThemeChangeCallback)) {
            _callbacks.push(onThemeChangeCallback);
        }
        // Trigger immediate invocation to sync subscriber state
        onThemeChangeCallback(getEffectiveTheme(), _currentTheme);

        // Add click listener to theme menu buttons
        const buttons = themeMenu.querySelectorAll('[data-theme]');
        buttons.forEach(btn => {
            btn.addEventListener('click', function() {
                const selectedTheme = this.getAttribute('data-theme');
                ThemeManager.setTheme(selectedTheme);
            });
        });
    }

    /**
     * Event handler for system color scheme changes.
     * @private
     */
    function handleSystemThemeChange() {
        if (_currentTheme === 'auto') {
            applyTheme();
        }
    }

    return {
        /**
         * Initializes the ThemeManager.
         * Loads preference, binds system theme change listener, and applies the active theme.
         */
        init: function() {
            _currentTheme = loadTheme();

            // Setup system media query listener
            _mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            if (_mediaQuery.addEventListener) {
                _mediaQuery.addEventListener('change', handleSystemThemeChange);
            } else if (_mediaQuery.addListener) {
                // Compatibility fallback
                _mediaQuery.addListener(handleSystemThemeChange);
            }

            // Sync body class
            applyTheme();

            // Bind switcher UI elements safely
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', _bindSwitcherUI);
            } else {
                _bindSwitcherUI();
            }
        },

        /**
         * Gets the current theme preference ('light', 'dark', or 'auto').
         * @returns {string}
         */
        getTheme: function() {
            return _currentTheme;
        },

        /**
         * Sets the new theme preference and applies it.
         * @param {string} theme - 'light' | 'dark' | 'auto'
         */
        setTheme: function(theme) {
            if (theme !== 'light' && theme !== 'dark' && theme !== 'auto') {
                console.warn(`[ThemeManager] Invalid theme specified: ${theme}`);
                return;
            }
            _currentTheme = theme;
            saveTheme(theme);
            applyTheme();
        },

        /**
         * Toggles the active theme.
         * If current preference is 'auto', it toggles to the opposite of the current active system theme.
         * If current preference is specific ('light' or 'dark'), it toggles to the other.
         */
        toggle: function() {
            const currentEffective = getEffectiveTheme();
            const nextTheme = currentEffective === 'dark' ? 'light' : 'dark';
            this.setTheme(nextTheme);
        },

        /**
         * Applies the theme styles based on current preference.
         */
        applyTheme: applyTheme,

        /**
         * Detects the system color scheme theme.
         * @returns {string} 'light' or 'dark'
         */
        detectSystemTheme: detectSystemTheme,

        /**
         * Saves the current theme preference to localStorage.
         */
        saveTheme: function() {
            saveTheme(_currentTheme);
        },

        /**
         * Loads the theme preference from localStorage.
         * @returns {string}
         */
        loadTheme: function() {
            _currentTheme = loadTheme();
            return _currentTheme;
        },

        /**
         * Checks if the currently active theme is dark.
         * @returns {boolean}
         */
        isDark: function() {
            return getEffectiveTheme() === 'dark';
        },

        /**
         * Registers a callback function to listen to theme changes.
         * Immediately fires the callback with the initial theme states.
         * @param {Function} callback - Callback function taking (effectiveTheme, currentTheme)
         */
        onThemeChanged: function(callback) {
            if (typeof callback === 'function') {
                if (!_callbacks.includes(callback)) {
                    _callbacks.push(callback);
                }
                // Trigger immediate invocation to sync subscriber state
                callback(getEffectiveTheme(), _currentTheme);
            }
        }
    };
})();

// Register to window global scope
window.ThemeManager = ThemeManager;
