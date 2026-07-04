(function () {
    const HISTORY_SECTIONS = {
        'appointment-history': {
            partial: 'appointments',
            pageParam: 'appointment_page',
            perPageParam: 'appointment_per_page'
        },
        'invoice-history': {
            partial: 'invoices',
            pageParam: 'invoice_page',
            perPageParam: 'invoice_per_page'
        }
    };

    function getSectionConfig(element) {
        if (!element) {
            return null;
        }
        return HISTORY_SECTIONS[element.id] || null;
    }

    function buildFetchUrl(url, partial) {
        const requestUrl = new URL(url, window.location.origin);
        requestUrl.searchParams.set('partial', partial);
        return requestUrl;
    }

    function replaceSectionHtml(sectionId, html) {
        const existingSection = document.getElementById(sectionId);
        if (!existingSection) {
            return;
        }
        const template = document.createElement('template');
        template.innerHTML = html.trim();
        const newSection = template.content.firstElementChild;
        if (newSection) {
            existingSection.replaceWith(newSection);
        }
    }

    async function loadHistorySection(sectionId, requestUrl) {
        const response = await fetch(requestUrl.toString(), {
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.message || 'Không thể tải lại lịch sử.');
        }
        replaceSectionHtml(sectionId, payload.html);
        const nextUrl = payload.url ? `${payload.url}#${sectionId}` : window.location.pathname + window.location.search;
        window.history.replaceState({}, '', nextUrl);
    }

    function handlePaginationClick(event) {
        const link = event.target.closest('#appointment-history a.page-link, #invoice-history a.page-link');
        if (!link || link.closest('.page-item.disabled') || link.getAttribute('href') === '#') {
            return;
        }
        const section = link.closest('[id$="-history"]');
        const config = getSectionConfig(section);
        if (!config) {
            return;
        }
        event.preventDefault();
        const requestUrl = buildFetchUrl(link.href, config.partial);
        loadHistorySection(section.id, requestUrl).catch(() => {
            window.location.href = link.href;
        });
    }

    function handlePageSizeChange(event) {
        const select = event.target.closest('#appointment-history select[name="appointment_per_page"], #invoice-history select[name="invoice_per_page"]');
        if (!select) {
            return;
        }
        const section = select.closest('[id$="-history"]');
        const config = getSectionConfig(section);
        if (!config) {
            return;
        }
        event.preventDefault();
        const requestUrl = new URL(window.location.href);
        requestUrl.searchParams.set(config.pageParam, '1');
        requestUrl.searchParams.set(config.perPageParam, select.value);
        requestUrl.searchParams.set('partial', config.partial);
        loadHistorySection(section.id, requestUrl).catch(() => {
            const fallbackUrl = new URL(window.location.href);
            fallbackUrl.searchParams.set(config.pageParam, '1');
            fallbackUrl.searchParams.set(config.perPageParam, select.value);
            window.location.href = fallbackUrl.toString();
        });
    }

    document.addEventListener('click', handlePaginationClick);
    document.addEventListener('change', handlePageSizeChange);
})();
