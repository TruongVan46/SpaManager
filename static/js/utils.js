/**
 * utils.js - Global Utilities for SpaManager
 * Consolidates duplicate helper methods across scripts.
 */

(function () {
    'use strict';

    const utils = {
        /**
         * Format numeric values as Vietnamese Dong (e.g., 150.000 đ)
         * @param {number} amount 
         * @returns {string}
         */
        formatCurrency: function (amount) {
            return new Intl.NumberFormat('vi-VN').format(amount) + ' đ';
        }
    };

    // Expose utility functions globally
    window.utils = utils;
    window.formatCurrency = utils.formatCurrency;

})();
