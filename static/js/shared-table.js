/**
 * shared-table.js - Universal Table Framework for SpaManager
 * Handles: Sort, Per-page, State Retention, Column Resize, Column Visibility
 */

(function () {
    'use strict';

    var STF_NS = 'stf_';
    var DEFAULT_PER_PAGE = 25;
    var TABLE_REGISTRY = {};

    function storageKey(module, suffix) { return STF_NS + module + '_' + suffix; }

    function saveState(module, state) {
        try { localStorage.setItem(storageKey(module, 'state'), JSON.stringify(state)); } catch(e) {}
    }

    function loadState(module) {
        try { return JSON.parse(localStorage.getItem(storageKey(module, 'state'))) || {}; } catch(e) { return {}; }
    }

    function saveWidths(module, widths) {
        try { localStorage.setItem(storageKey(module, 'widths'), JSON.stringify(widths)); } catch(e) {}
    }

    function loadWidths(module) {
        try { return JSON.parse(localStorage.getItem(storageKey(module, 'widths'))) || {}; } catch(e) { return {}; }
    }

    function saveVisibility(module, vis) {
        try { localStorage.setItem(storageKey(module, 'vis'), JSON.stringify(vis)); } catch(e) {}
    }

    function loadVisibility(module) {
        try { return JSON.parse(localStorage.getItem(storageKey(module, 'vis'))) || {}; } catch(e) { return {}; }
    }

    function registerSharedTable(module, table, instance) {
        if (!module || !table) return;
        TABLE_REGISTRY[module] = {
            table: table,
            instance: instance
        };
    }

    function getSharedTableEntry(module) {
        return TABLE_REGISTRY[module] || null;
    }

    function getUniqueTableClassList(table) {
        var genericClasses = {
            'app-table': true,
            'table': true,
            'table-hover': true,
            'align-middle': true,
            'text-center': true,
            'text-start': true,
            'text-end': true,
            'table-responsive': true
        };

        return Array.from(table.classList || []).filter(function(className) {
            return genericClasses[className] !== true && /table$/i.test(className);
        });
    }

    function findMatchingTableInDocument(documentRoot, sourceTable) {
        if (!documentRoot || !sourceTable) return null;
        if (sourceTable.id) {
            var byId = documentRoot.getElementById(sourceTable.id);
            if (byId) return byId;
        }

        var classCandidates = getUniqueTableClassList(sourceTable);
        for (var i = 0; i < classCandidates.length; i++) {
            var candidate = classCandidates[i];
            var byClass = documentRoot.querySelector('.' + candidate);
            if (byClass) return byClass;
        }

        return null;
    }

    function findTableNearFooter(footer) {
        if (!footer) return null;
        var cardBody = footer.closest('.app-card-body');
        if (cardBody) {
            var tables = cardBody.querySelectorAll('table');
            if (tables.length === 1) return tables[0];
            if (tables.length > 1) {
                for (var i = tables.length - 1; i >= 0; i--) {
                    var candidate = tables[i];
                    if (footer.compareDocumentPosition(candidate) & Node.DOCUMENT_POSITION_PRECEDING) {
                        return candidate;
                    }
                }
                return tables[0];
            }
        }

        var tableWrap = footer.closest('.app-table-wrapper, .app-table-container, .table-responsive');
        if (tableWrap) {
            var wrappedTables = tableWrap.querySelectorAll('table');
            if (wrappedTables.length > 0) return wrappedTables[0];
        }

        return null;
    }

    function updatePerPageHiddenInputs(perPageParam, value) {
        if (!perPageParam) return;
        document.querySelectorAll('input[type="hidden"][name="' + perPageParam + '"]').forEach(function(hiddenInput) {
            hiddenInput.value = value;
        });
    }

    function replaceTableFromResponse(select, currentTable, currentFooter, responseHtml) {
        if (!currentTable || !currentFooter || !responseHtml) return false;

        var parser = new DOMParser();
        var responseDoc = parser.parseFromString(responseHtml, 'text/html');
        var replacementTable = findMatchingTableInDocument(responseDoc, currentTable);
        var replacementSelect = responseDoc.querySelector('[data-stf-per-page-module="' + (select.dataset.stfPerPageModule || 'table') + '"]');
        var replacementFooter = replacementSelect ? replacementSelect.closest('.stf-footer') : null;

        if (!replacementTable || !replacementFooter) return false;

        if (currentTable.tBodies && currentTable.tBodies[0] && replacementTable.tBodies && replacementTable.tBodies[0]) {
            currentTable.tBodies[0].innerHTML = replacementTable.tBodies[0].innerHTML;
        } else {
            currentTable.innerHTML = replacementTable.innerHTML;
        }

        currentFooter.innerHTML = replacementFooter.innerHTML;
        return true;
    }

    function fetchAndSwapPageSize(select) {
        var perPageParam = select.dataset.stfPerPageParam || 'per_page';
        var moduleName = select.dataset.stfPerPageModule || 'table';
        var currentUrl = new URL(window.location.href);
        currentUrl.searchParams.set(perPageParam, select.value);
        currentUrl.searchParams.set('page', '1');

        updatePerPageHiddenInputs(perPageParam, select.value);

        var registryEntry = getSharedTableEntry(moduleName);
        var sourceTable = registryEntry && registryEntry.table ? registryEntry.table : findTableNearFooter(select.closest('.stf-footer'));
        var sourceFooter = select.closest('.stf-footer');
        if (!sourceTable || !sourceFooter) return;

        select.disabled = true;

        fetch(currentUrl.toString(), {
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        })
        .then(function(response) {
            if (!response.ok) throw new Error('Không thể tải lại bảng dữ liệu');
            return response.text();
        })
        .then(function(html) {
            var swapped = replaceTableFromResponse(select, sourceTable, sourceFooter, html);
            if (swapped) {
                window.history.replaceState({}, '', currentUrl.toString());
            }
        })
        .catch(function(error) {
            console.error('Page-size refresh failed:', error);
        })
        .finally(function() {
            select.disabled = false;
        });
    }

    var LIVE_SEARCH_CONFIG = {
        customer:    { inputSelector: '#customer-filter-form input[name="q"]',       tableSelector: '#customer-table',           searchKeys: ['name', 'phone', 'email', 'address'], searchParam: 'q' },
        service:     { inputSelector: '#service-filter-form input[name="q"]',        tableSelector: '#service-table',            searchKeys: ['name', 'description'], searchParam: 'q' },
        appointment: { inputSelector: '.appointment-page .app-filter-bar input[name="search"]', tableSelector: '#appointment-table', searchKeys: ['customer', 'service'], searchParam: 'search' },
        invoice:     { inputSelector: '.app-filter-bar input[name="q"]',             tableSelector: '#invoice-table',            searchKeys: ['customer'], searchParam: 'q' },
        recycle_bin: { inputSelector: '#recycle-bin-filter-form input[name="q"]',    tableSelector: '.recycle-bin-table',        searchIndices: [0, 1, 3], searchParam: 'q' },
        customer_stats: { inputSelector: '#cust_q', tableSelector: '#customer-statistics-table', searchKeys: ['customer', 'phone'], searchParam: 'cust_q' },
        service_stats: { inputSelector: '#svc_q', tableSelector: '#service-statistics-table', searchKeys: ['service'], searchParam: 'svc_q' },
        activity_log: { inputSelector: '#activity-log-filter-form input[name="q"]', tableSelector: '.activity-log-table', rowSearchKeys: ['time', 'module', 'action', 'severity', 'description', 'reference'], searchParam: 'q' }
    };

    function getUrlParams() {
        var p = {};
        new URLSearchParams(window.location.search).forEach(function(v, k) { p[k] = v; });
        return p;
    }

    function reloadWithParams(extra, pageParamName) {
        var u = new URL(window.location.href);
        Object.keys(extra).forEach(function(k) {
            if (extra[k] !== null && extra[k] !== undefined && extra[k] !== '') {
                u.searchParams.set(k, extra[k]);
            } else {
                u.searchParams.delete(k);
            }
        });
        u.searchParams.set(pageParamName || 'page', '1');
        window.location.href = u.toString();
    }

    function normalizeSearchTerm(value) {
        return (value || '').toString().trim().toLowerCase().replace(/\s+/g, ' ');
    }

    function escapeRegExp(value) {
        return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function stripSearchMarks(html) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = html;
        wrapper.querySelectorAll('mark.search-highlight').forEach(function(mark) {
            mark.replaceWith(document.createTextNode(mark.textContent || ''));
        });
        return wrapper.innerHTML;
    }

    function getBaseHtml(cell) {
        if (!cell.dataset.stfBaseHtml) {
            cell.dataset.stfBaseHtml = stripSearchMarks(cell.innerHTML);
        }
        return cell.dataset.stfBaseHtml;
    }

    function getColumnIndexMap(table) {
        var map = {};
        table.querySelectorAll('thead th').forEach(function(th, index) {
            var key = th.dataset.colKey;
            if (key) map[key] = index;
        });
        return map;
    }

    function resolveSearchableIndexes(table, config) {
        if (config.rowSearchKeys && config.rowSearchKeys.length > 0) {
            return [];
        }
        if (config.searchIndices && config.searchIndices.length > 0) {
            return config.searchIndices.slice();
        }

        if (!config.searchKeys || config.searchKeys.length === 0) {
            return [];
        }

        var keyIndex = getColumnIndexMap(table);
        return config.searchKeys.map(function(key) {
            return keyIndex[key];
        }).filter(function(index) {
            return index !== undefined;
        });
    }

    function getSearchTokens(term) {
        var normalized = normalizeSearchTerm(term);
        if (!normalized) return [];
        return normalized.split(' ').filter(function(token) { return token.length > 0; });
    }

    function resetCellHtml(cell) {
        cell.innerHTML = getBaseHtml(cell);
    }

    function highlightCell(cell, tokens) {
        resetCellHtml(cell);
        tokens.forEach(function(token) {
            highlightKeyword(cell, token);
        });
    }

    function buildLiveEmptyState(table) {
        var wrap = table.closest('.stf-table-wrap, .table-responsive, .app-table-container') || table.parentElement;
        if (!wrap) return null;

        var state = wrap.querySelector('[data-stf-live-empty="' + (table.id || table.className || 'table') + '"]');
        if (state) return state;

        state = document.createElement('div');
        state.className = 'stf-empty-state stf-live-empty-state d-none';
        state.setAttribute('data-stf-live-empty', table.id || table.className || 'table');
        state.innerHTML = '<i class="bi bi-search stf-empty-state-icon"></i>' +
            '<p class="stf-empty-state-title">Không tìm thấy kết quả phù hợp</p>' +
            '<p class="stf-empty-state-desc">Thử một từ khóa khác hoặc xóa bộ lọc tìm kiếm.</p>';

        wrap.parentNode.insertBefore(state, wrap.nextSibling);
        return state;
    }

    function updateLiveUrl(input, term) {
        var url = new URL(window.location.href);
        var paramName = input.dataset.stfSearchParam || input.name || 'q';
        if (term) {
            url.searchParams.set(paramName, term);
            url.searchParams.set('page', '1');
        } else {
            url.searchParams.delete(paramName);
            url.searchParams.set('page', '1');
        }
        window.history.replaceState({}, '', url.toString());
    }

    function syncPaginationLinks(table, input, term) {
        var card = table.closest('.app-card') || table.parentElement;
        if (!card) return;

        var paramName = input.dataset.stfSearchParam || input.name || 'q';
        var links = card.querySelectorAll('.pagination .page-link[href]');
        links.forEach(function(link) {
            var href = link.getAttribute('href');
            if (!href || href === '#') return;

            try {
                var url = new URL(href, window.location.origin);
                if (term) {
                    url.searchParams.set(paramName, term);
                } else {
                    url.searchParams.delete(paramName);
                }
                link.setAttribute('href', url.pathname + url.search);
            } catch (e) {}
        });
    }

    function syncHiddenFormInputs(input, term) {
        var paramName = input.dataset.stfSearchParam || input.name || 'q';
        document.querySelectorAll('input[type="hidden"][name="' + paramName + '"]').forEach(function(hiddenInput) {
            hiddenInput.value = term;
        });
    }

    function bindLiveSearch(input, table, config) {
        if (!input || !table || input.dataset.stfLiveBound === 'true') return;
        input.dataset.stfLiveBound = 'true';
        table.dataset.stfLiveSearch = 'true';
        input.dataset.stfSearchParam = config.searchParam || input.name || 'q';

        var searchableIndexes = resolveSearchableIndexes(table, config);
        var rowMode = config.rowSearchKeys && config.rowSearchKeys.length > 0;
        if (searchableIndexes.length === 0 && !rowMode) return;

        var rows = Array.from(table.querySelectorAll('tbody tr'));
        var liveEmptyState = buildLiveEmptyState(table);
        function applyFilter() {
            var term = normalizeSearchTerm(input.value);
            var tokens = getSearchTokens(term);
            var visibleCount = 0;

        if (rowMode) {
            rows.forEach(function(row) {
                if (!row || row.cells.length === 0) return;
                if (row.querySelector('td[colspan]')) return;

                    var haystack = config.rowSearchKeys.map(function(key) {
                        return normalizeSearchTerm(row.dataset[key] || '');
                    }).join(' ');

                    var matches = tokens.length === 0 || tokens.every(function(token) {
                        return haystack.indexOf(token) !== -1;
                    });

                    row.style.display = matches ? '' : 'none';

                    var rowCells = Array.from(row.cells).filter(function(cell) {
                        return !cell.hasAttribute('colspan');
                    });

                    if (matches && tokens.length > 0) {
                        rowCells.forEach(function(cell) {
                            if (!cell.dataset.stfBaseHtml) {
                                cell.dataset.stfBaseHtml = stripSearchMarks(cell.innerHTML);
                            }
                            highlightCell(cell, tokens);
                        });
                    } else {
                        rowCells.forEach(function(cell) {
                            if (!cell.dataset.stfBaseHtml) {
                                cell.dataset.stfBaseHtml = stripSearchMarks(cell.innerHTML);
                            }
                            resetCellHtml(cell);
                        });
                    }

                    if (matches) visibleCount++;
                });

                if (liveEmptyState) {
                    var showEmptyRowMode = tokens.length > 0 && visibleCount === 0;
                    liveEmptyState.classList.toggle('d-none', !showEmptyRowMode);
                }

                updateLiveUrl(input, input.value.trim());
                syncHiddenFormInputs(input, input.value.trim());
                syncPaginationLinks(table, input, input.value.trim());
                return;
            }

            rows.forEach(function(row) {
                if (!row || row.cells.length === 0) return;
                if (row.querySelector('td[colspan]')) return;

                var searchableCells = searchableIndexes.map(function(index) {
                    return row.cells[index];
                }).filter(Boolean);

                if (searchableCells.length === 0) return;

                var haystack = searchableCells.map(function(cell) {
                    return normalizeSearchTerm(cell.textContent || '');
                }).join(' ');

                var matches = tokens.length === 0 || tokens.every(function(token) {
                    return haystack.indexOf(token) !== -1;
                });

                row.style.display = matches ? '' : 'none';

                searchableCells.forEach(function(cell) {
                    if (!cell.dataset.stfBaseHtml) {
                        cell.dataset.stfBaseHtml = stripSearchMarks(cell.innerHTML);
                    }
                    if (matches && tokens.length > 0) {
                        highlightCell(cell, tokens);
                    } else {
                        resetCellHtml(cell);
                    }
                });

                if (matches) visibleCount++;
            });

            if (liveEmptyState) {
                var showEmpty = tokens.length > 0 && visibleCount === 0;
                liveEmptyState.classList.toggle('d-none', !showEmpty);
            }

            updateLiveUrl(input, input.value.trim());
            syncHiddenFormInputs(input, input.value.trim());
            syncPaginationLinks(table, input, input.value.trim());
        }

        input.__stfLiveApply = applyFilter;
        applyFilter();

        input.addEventListener('input', function() {
            applyFilter();
        });
    }

    function initLiveSearch() {
        Object.keys(LIVE_SEARCH_CONFIG).forEach(function(module) {
            var config = LIVE_SEARCH_CONFIG[module];
            var input = document.querySelector(config.inputSelector);
            var table = document.querySelector(config.tableSelector);
            if (input && table) {
                bindLiveSearch(input, table, config);
            }
        });
    }

    /* ================================================================
       CLASS SharedTable
    ================================================================ */
    function SharedTable(tableEl, options) {
        if (!tableEl) return;
        options = options || {};
        this.table  = tableEl;
        this.opts   = {
            moduleName    : options.moduleName    || 'table',
            sortParam     : options.sortParam     || 'sort_by',
            dirParam      : options.dirParam      || 'sort_dir',
            perPageParam  : options.perPageParam  || 'per_page',
            pageParam     : options.pageParam     || 'page',
            sortableColumns: options.sortableColumns || [],
            colDefs       : options.colDefs       || [],
            restoreState  : options.restoreState  !== false
        };
        this.module = this.opts.moduleName;
        this.params = getUrlParams();

        this._initStateRestore();
        this._initSort();
        this._initPerPage();
        this._initColumnResize();
        this._initColumnVisibility();
        this._persistCurrentState();
        registerSharedTable(this.module, this.table, this);
    }

    SharedTable.prototype._initStateRestore = function() {
        if (!this.opts.restoreState) return;
        var params  = this.params;
        var watched = ['q','search',this.opts.sortParam,this.opts.dirParam,
                       this.opts.perPageParam,'page','status','from_date','to_date',
                       'payment_method','module','action','severity','sort_by','item_type'];
        var hasParams = Object.keys(params).some(function(k){ return watched.indexOf(k) !== -1; });
        if (hasParams) return;

        var saved = loadState(this.module);
        if (!saved || Object.keys(saved).length === 0) return;

        var redirect = {};
        if (saved.per_page && saved.per_page !== DEFAULT_PER_PAGE) redirect[this.opts.perPageParam] = saved.per_page;
        if (saved.sort_by)  redirect[this.opts.sortParam] = saved.sort_by;
        if (saved.sort_dir) redirect[this.opts.dirParam]  = saved.sort_dir;

        if (Object.keys(redirect).length > 0) {
            var u = new URL(window.location.href);
            Object.keys(redirect).forEach(function(k){ u.searchParams.set(k, redirect[k]); });
            u.searchParams.delete('page');
            window.location.replace(u.toString());
        }
    };

    SharedTable.prototype._initSort = function() {
        var sortParam = this.opts.sortParam;
        var dirParam  = this.opts.dirParam;
        var curField  = this.params[sortParam] || '';
        var curDir    = this.params[dirParam]  || 'asc';
        var self      = this;

        this.table.querySelectorAll('th.stf-sortable').forEach(function(th) {
            var field = th.dataset.sortField;
            if (!field) return;

            var icon = document.createElement('span');
            icon.className = 'stf-sort-icon bi';
            th.appendChild(icon);

            if (field === curField) {
                th.classList.add(curDir === 'asc' ? 'stf-sort-asc' : 'stf-sort-desc');
                icon.classList.add(curDir === 'asc' ? 'bi-arrow-up' : 'bi-arrow-down');
            } else {
                icon.classList.add('bi-arrow-down-up');
            }

            th.addEventListener('click', function() {
                var newDir = (field === curField && curDir === 'asc') ? 'desc' : 'asc';
                var p = {};
                p[sortParam] = field;
                p[dirParam]  = newDir;
                reloadWithParams(p, self.opts.pageParam);
            });
        });
    };

    SharedTable.prototype._initPerPage = function() {
        return;
    };

    SharedTable.prototype._persistCurrentState = function() {
        var state = {};
        var pp = this.params[this.opts.perPageParam];
        if (pp) state.per_page = parseInt(pp, 10);
        var sb = this.params[this.opts.sortParam];
        if (sb) state.sort_by = sb;
        var sd = this.params[this.opts.dirParam];
        if (sd) state.sort_dir = sd;
        if (Object.keys(state).length > 0) saveState(this.module, state);
    };

    SharedTable.prototype._initColumnResize = function() {
        var module  = this.module;
        var wrap    = this.table.closest('.stf-table-wrap');
        var savedW  = loadWidths(module);
        var startX, startW, activeTh, activeHandle;
        var allThs  = Array.from(this.table.querySelectorAll('thead th'));
        var self    = this;

        // Apply fixed table layout only if we have saved widths, otherwise let browser auto-fit
        var hasSavedWidths = Object.keys(savedW).length > 0;
        if (hasSavedWidths) {
            this.table.style.tableLayout = 'fixed';
        } else {
            this.table.style.tableLayout = 'auto';
        }

        allThs.forEach(function(th, idx) {
            var key = th.dataset.colKey || ('col' + idx);
            if (savedW[key]) th.style.width = savedW[key] + 'px';

            var handle = document.createElement('div');
            handle.className = 'stf-resize-handle';
            th.appendChild(handle);

            handle.addEventListener('mousedown', function(e) {
                e.preventDefault();
                self.table.style.tableLayout = 'fixed'; // Switch to fixed when dragging
                startX = e.clientX; startW = th.offsetWidth;
                activeHandle = handle; activeTh = th;
                handle.classList.add('stf-resizing');
                if (wrap) wrap.classList.add('stf-col-resizing');
            });
        });

        document.addEventListener('mousemove', function(e) {
            if (!activeTh) return;
            var newW = Math.max(60, startW + (e.clientX - startX));
            activeTh.style.width = newW + 'px';
        });

        document.addEventListener('mouseup', function() {
            if (!activeTh) return;
            var idx = allThs.indexOf(activeTh);
            var key = activeTh.dataset.colKey || ('col' + idx);
            savedW[key] = activeTh.offsetWidth;
            saveWidths(module, savedW);
            if (activeHandle) activeHandle.classList.remove('stf-resizing');
            if (wrap) wrap.classList.remove('stf-col-resizing');
            activeTh = null; activeHandle = null;
        });
    };

    SharedTable.prototype._setColVisible = function(key, visible, keyIndex) {
        var i = keyIndex[key];
        if (i === undefined) return;
        var cls  = 'stf-col-hidden';
        var ths  = this.table.querySelectorAll('thead th');
        var rows = this.table.querySelectorAll('tbody tr');
        if (ths[i]) ths[i].classList.toggle(cls, !visible);
        rows.forEach(function(tr) {
            if (tr.cells[i]) tr.cells[i].classList.toggle(cls, !visible);
        });
    };

    SharedTable.prototype._initColumnVisibility = function() {
        var colDefs = this.opts.colDefs;
        if (!colDefs || colDefs.length === 0) return;
        var module  = this.module;
        var saved   = loadVisibility(module);
        var self    = this;
        var ths     = Array.from(this.table.querySelectorAll('thead th'));

        var keyIndex = {};
        ths.forEach(function(th, i) {
            var key = th.dataset.colKey;
            if (key) keyIndex[key] = i;
        });

        colDefs.forEach(function(def) {
            if (!def.hideable) return;
            if (saved[def.key] === false) self._setColVisible(def.key, false, keyIndex);
        });

        var menuEl = document.querySelector('[data-stf-col-vis-menu="' + module + '"]');
        if (!menuEl) return;

        colDefs.forEach(function(def) {
            if (!def.hideable) return;
            var isVisible = saved[def.key] !== false;
            var item = document.createElement('label');
            item.className = 'dropdown-item';
            item.innerHTML = '<input type="checkbox" ' + (isVisible ? 'checked' : '') + ' data-col-key="' + def.key + '"> ' + def.label;
            menuEl.appendChild(item);
            item.querySelector('input').addEventListener('change', function(e) {
                var vis = e.target.checked;
                saved[def.key] = vis;
                saveVisibility(module, saved);
                self._setColVisible(def.key, vis, keyIndex);
            });
        });
    };

    /* ================================================================
       HIGHLIGHT KEYWORDS HELPER
       ================================================================ */
    function highlightKeyword(container, term) {
        if (!container || !term) return;
        var cleanTerm = term.trim().toLowerCase();
        if (cleanTerm.length === 0) return;

        function traverse(node) {
            if (node.nodeType === 3) { // TEXT_NODE
                var val = node.nodeValue;
                var idx = val.toLowerCase().indexOf(cleanTerm);
                if (idx !== -1) {
                    var parent = node.parentNode;
                    if (['SCRIPT', 'STYLE', 'INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'MARK'].indexOf(parent.tagName) !== -1) {
                        return;
                    }
                    
                    var fragment = document.createDocumentFragment();
                    var currentVal = val;
                    while (true) {
                        var matchIdx = currentVal.toLowerCase().indexOf(cleanTerm);
                        if (matchIdx === -1) {
                            fragment.appendChild(document.createTextNode(currentVal));
                            break;
                        }
                        if (matchIdx > 0) {
                            fragment.appendChild(document.createTextNode(currentVal.substring(0, matchIdx)));
                        }
                        var mark = document.createElement('mark');
                        mark.className = 'search-highlight';
                        mark.textContent = currentVal.substring(matchIdx, matchIdx + cleanTerm.length);
                        fragment.appendChild(mark);
                        currentVal = currentVal.substring(matchIdx + cleanTerm.length);
                    }
                    parent.replaceChild(fragment, node);
                }
            } else {
                for (var i = 0; i < node.childNodes.length; i++) {
                    var oldLen = node.childNodes.length;
                    traverse(node.childNodes[i]);
                    var newLen = node.childNodes.length;
                    if (newLen !== oldLen) {
                        i += (newLen - oldLen);
                    }
                }
            }
        }
        traverse(container);
    }

    /* ================================================================
     * INJECT SEARCH CLEAR BUTTONS
     * ================================================================ */
    function initSearchClearButtons() {
        var selector = '[data-stf-search], input[name="q"], input[name="search"], .app-search-box input[type="text"], .stf-toolbar input[type="text"]';
        document.querySelectorAll(selector).forEach(function(input) {
            if (input.dataset.clearInjected) return;
            if (input.closest('#activity-log-filter-form')) return;
            input.dataset.clearInjected = "true";

            // Add placeholder check compatibility for styling
            if (!input.getAttribute('placeholder')) {
                input.setAttribute('placeholder', 'Tìm kiếm...');
            }

            // Create wrapper
            var wrapper = document.createElement('div');
            wrapper.className = 'stf-search-wrapper';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);

            // Create clear button
            var clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.className = 'stf-search-clear';
            clearBtn.setAttribute('aria-label', 'Xóa tìm kiếm');
            clearBtn.innerHTML = '<i class="bi bi-x-circle-fill"></i>';
            wrapper.appendChild(clearBtn);

            var updateVisibility = function() {
                clearBtn.style.display = input.value ? 'flex' : 'none';
            };

            input.addEventListener('input', updateVisibility);
            updateVisibility();

            // Clear click handler
            clearBtn.addEventListener('click', function() {
                input.value = '';
                updateVisibility();
                input.focus();
                
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));

                if (typeof input.__stfLiveApply === 'function') {
                    input.__stfLiveApply();
                }
            });

            // ESC key handler for accessibility
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    input.value = '';
                    updateVisibility();
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    if (typeof input.__stfLiveApply === 'function') {
                        input.__stfLiveApply();
                    }
                }
            });
        });
    }

    /* ================================================================
       HELPERS auto-init
       ================================================================ */
    function initSearchDebounce() {
        var selector = '[data-stf-search], input[name="q"], input[name="search"], .app-search-box input[type="text"], .stf-toolbar input[type="text"]';
        document.querySelectorAll(selector).forEach(function(input) {
            if (input.dataset.stfLiveBound === 'true') return;
            var timer;
            input.addEventListener('input', function() {
                clearTimeout(timer);
                timer = setTimeout(function() {
                    if (typeof input.__stfLiveApply === 'function') {
                        input.__stfLiveApply();
                    }
                }, 300); // 300ms debounce for live filtering
            });
        });
    }

    function initFilterAutoSubmit() {
        document.querySelectorAll('[data-stf-filter]').forEach(function(sel) {
            sel.addEventListener('change', function() {
                var form = sel.closest('form');
                if (form) { form.submit(); }
            });
        });
    }

    function initPageSizeDelegation() {
        if (document.documentElement.dataset.stfPerPageBound === 'true') return;
        document.documentElement.dataset.stfPerPageBound = 'true';

        document.addEventListener('change', function(event) {
            var select = event.target.closest('[data-stf-per-page]');
            if (!select) return;
            fetchAndSwapPageSize(select);
        });
    }

    /* ================================================================
       EXPORTS
       ================================================================ */
    window.SharedTable = SharedTable;
    window.STF = { 
        initSearchDebounce: initSearchDebounce, 
        initFilterAutoSubmit: initFilterAutoSubmit,
        initSearchClearButtons: initSearchClearButtons,
        highlightKeyword: highlightKeyword,
        bindLiveSearch: bindLiveSearch,
        initLiveSearch: initLiveSearch,
        initPageSizeDelegation: initPageSizeDelegation,
        fetchAndSwapPageSize: fetchAndSwapPageSize
    };

    document.addEventListener('DOMContentLoaded', function() {
        initSearchClearButtons();
        initLiveSearch();
        initSearchDebounce();
        initFilterAutoSubmit();
        initPageSizeDelegation();

        // Highlight matching text on tables
        // Skip if server-side | highlight(q) filter already rendered <mark> tags
        var params = new URLSearchParams(window.location.search);
        var q = params.get('q') || params.get('search') || '';
        if (q) {
            document.querySelectorAll('.app-table, .stf-table').forEach(function(table) {
                if (table.dataset.stfLiveSearch === 'true') return;
                var tbody = table.querySelector('tbody');
                var container = tbody || table;
                // If server already injected <mark class="search-highlight">, skip client-side pass
                if (container.querySelector('mark.search-highlight')) return;
                highlightKeyword(container, q);
            });
        }
    });

})();
