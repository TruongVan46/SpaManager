(function () {
    'use strict';

    function getToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? (meta.getAttribute('content') || '') : '';
    }

    function isUnsafeMethod(method) {
        const upper = (method || 'GET').toUpperCase();
        return ['POST', 'PUT', 'PATCH', 'DELETE'].indexOf(upper) !== -1;
    }

    function isSameOrigin(url) {
        try {
            const resolved = new URL(url, window.location.origin);
            return resolved.origin === window.location.origin;
        } catch (error) {
            return true;
        }
    }

    function addTokenToHeaders(headers) {
        const merged = new Headers(headers || {});
        const token = getToken();
        if (token) {
            merged.set('X-CSRFToken', token);
        }
        if (!merged.has('X-Requested-With')) {
            merged.set('X-Requested-With', 'XMLHttpRequest');
        }
        return merged;
    }

    function csrfFetch(url, options) {
        const fetchOptions = options ? Object.assign({}, options) : {};
        const method = (fetchOptions.method || 'GET').toUpperCase();

        if (isUnsafeMethod(method) && isSameOrigin(url)) {
            fetchOptions.headers = addTokenToHeaders(fetchOptions.headers);
            if (!fetchOptions.credentials) {
                fetchOptions.credentials = 'same-origin';
            }
        }

        return fetch(url, fetchOptions);
    }

    function injectTokensIntoForms() {
        const token = getToken();
        if (!token) return;

        document.querySelectorAll('form').forEach(function (form) {
            const method = (form.getAttribute('method') || 'get').toUpperCase();
            if (!isUnsafeMethod(method)) return;
            if (form.querySelector('input[name="csrf_token"]')) return;

            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'csrf_token';
            hidden.value = token;
            form.appendChild(hidden);
            });
    }

    function ensureTokenBeforeSubmit(event) {
        const form = event.target;
        if (!form || form.tagName !== 'FORM') return;
        const method = (form.getAttribute('method') || 'get').toUpperCase();
        if (!isUnsafeMethod(method)) return;

        const token = getToken();
        if (!token) return;

        let hidden = form.querySelector('input[name="csrf_token"]');
        if (!hidden) {
            hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'csrf_token';
            form.appendChild(hidden);
        }
        hidden.value = token;
    }

    window.SpaCsrf = {
        getToken: getToken,
        fetch: csrfFetch,
        headers: addTokenToHeaders,
        injectForms: injectTokensIntoForms
    };

    window.csrfFetch = csrfFetch;

    document.addEventListener('DOMContentLoaded', injectTokensIntoForms);
    document.addEventListener('submit', ensureTokenBeforeSubmit, true);
})();
