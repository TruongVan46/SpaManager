/**
 * Settings Page JavaScript
 * Handles: Logo preview, Restore confirmation, Import wizard
 */

document.addEventListener('DOMContentLoaded', function () {

    // ──────────────────────────────────────────────
    // Logo Preview
    // ──────────────────────────────────────────────
    const logoInput = document.getElementById('logoInput');
    const logoPreview = document.getElementById('logoPreview');
    const logoPlaceholder = document.getElementById('logoPlaceholder');
    const btnDeleteLogo = document.getElementById('btnDeleteLogo');

    if (logoInput) {
        logoInput.addEventListener('change', function (e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function (event) {
                    if (logoPreview) {
                        logoPreview.src = event.target.result;
                        logoPreview.classList.remove('d-none');
                    }
                    if (logoPlaceholder) {
                        logoPlaceholder.classList.add('d-none');
                    }
                    if (btnDeleteLogo) {
                        btnDeleteLogo.style.display = 'inline-block';
                    }
                };
                reader.readAsDataURL(file);
            }
        });
    }

    if (btnDeleteLogo) {
        btnDeleteLogo.addEventListener('click', function () {
            if (confirm('Bạn có chắc chắn muốn xóa logo hiện tại?')) {
                // Clear any newly selected file first
                if (logoInput) {
                    logoInput.value = '';
                }

                // Request backend to delete saved logo
                csrfFetch('/settings/delete-logo', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (logoPreview) {
                            logoPreview.src = '';
                            logoPreview.classList.add('d-none');
                        }
                        if (logoPlaceholder) {
                            logoPlaceholder.classList.remove('d-none');
                        }
                        btnDeleteLogo.style.display = 'none';
                        Notification.success('Đã xóa logo thành công.');
                    } else {
                        Notification.error('Lỗi: ' + (data.message || 'Không thể xóa logo.'));
                    }
                })
                .catch(err => {
                    console.error(err);
                    Notification.error('Lỗi kết nối khi xóa logo.');
                });
            }
        });
    }

    // ──────────────────────────────────────────────
    // Collapse toggle icon rotation
    // ──────────────────────────────────────────────
    document.querySelectorAll('[data-bs-toggle="collapse"]').forEach(function (btn) {
        const targetId = btn.getAttribute('data-bs-target');
        const target = document.querySelector(targetId);
        if (target) {
            target.addEventListener('show.bs.collapse', function () {
                const icon = btn.querySelector('i');
                if (icon) icon.className = 'bi bi-chevron-up';
            });
            target.addEventListener('hide.bs.collapse', function () {
                const icon = btn.querySelector('i');
                if (icon) icon.className = 'bi bi-chevron-down';
            });
        }
    });

    // ──────────────────────────────────────────────
    // Restore Database
    // ──────────────────────────────────────────────
    const restoreFileInput = document.getElementById('restoreFileInput');
    const btnRestore = document.getElementById('btnRestore');
    const restoreForm = document.getElementById('restoreForm');
    const confirmRestoreBtn = document.getElementById('confirmRestore');
    const confirmRestoreBackupBtn = document.getElementById('confirmRestoreBackupBtn');
    const restoreConfirmCheck = document.getElementById('restoreConfirmCheck');

    if (restoreFileInput && btnRestore) {
        restoreFileInput.addEventListener('change', function () {
            btnRestore.disabled = !this.files.length;
        });

        btnRestore.addEventListener('click', function () {
            // Show confirmation modal
            const modal = new bootstrap.Modal(document.getElementById('restoreModal'));
            modal.show();
        });
    }

    if (confirmRestoreBtn && restoreForm) {
        confirmRestoreBtn.addEventListener('click', function () {
            // Close modal and submit form
            const modal = bootstrap.Modal.getInstance(document.getElementById('restoreModal'));
            if (modal) modal.hide();
            if (typeof restoreForm.requestSubmit === 'function') {
                restoreForm.requestSubmit();
            } else {
                restoreForm.submit();
            }
        });
    }

    if (restoreConfirmCheck && confirmRestoreBackupBtn) {
        restoreConfirmCheck.addEventListener('change', function () {
            confirmRestoreBackupBtn.disabled = !this.checked;
        });
    }

});


/**
 * Setup import wizard for a given configuration
 */
    // ──────────────────────────────────────────────
    // Smart Import Wizard (Task D3.3 & UX Hot Fix)
    // ──────────────────────────────────────────────
    const importWizardModalEl = document.getElementById('importWizardModal');
    let importWizardInstance = null;
    
    // Wizard State variables
    let wCurrentStep = 1;
    let wImportType = 'customers'; // 'customers' or 'services'
    let wTempFileId = null;
    let wAnalysisData = null;
    let isExecutingImport = false;
    let isConfirmingClose = false;

    // Elements
    const wTitleTypeName = document.getElementById('importWizardTypeName');
    const wTemplateDownloadBtn = document.getElementById('importTemplateDownloadBtn');
    const wFileInput = document.getElementById('wizardImportFile');
    const wUploadAlert = document.getElementById('import-upload-alert');
    
    const wBtnCancel = document.getElementById('w-btn-cancel');
    const wBtnImportAnother = document.getElementById('w-btn-import-another');
    const wBtnRetry = document.getElementById('w-btn-retry');
    
    const wBtnBack = document.getElementById('w-btn-back');
    const wBtnNext = document.getElementById('w-btn-next');
    const wBtnExecute = document.getElementById('w-btn-execute');
    const wBtnCloseFinish = document.getElementById('w-btn-close-finish');
    const wBtnCloseHeader = document.getElementById('btn-close-import-wizard');

    // Steps containers
    const wStep1Content = document.getElementById('w-step-1-content');
    const wStep2Content = document.getElementById('w-step-2-content');
    const wStep3Content = document.getElementById('w-step-3-content');
    const wStep4Content = document.getElementById('w-step-4-content');

    // Reset Wizard to step 1 state
    function resetWizardState() {
        wCurrentStep = 1;
        wTempFileId = null;
        wAnalysisData = null;
        isExecutingImport = false;
        
        if (wFileInput) wFileInput.value = '';
        if (wUploadAlert) {
            wUploadAlert.classList.add('d-none');
            wUploadAlert.textContent = '';
        }
        
        wStep1Content.classList.remove('d-none');
        wStep2Content.classList.add('d-none');
        wStep3Content.classList.add('d-none');
        wStep4Content.classList.add('d-none');
        
        wBtnBack.disabled = true;
        wBtnNext.disabled = true;
        wBtnNext.classList.remove('d-none');
        wBtnExecute.classList.add('d-none');
        wBtnExecute.disabled = false;
        wBtnExecute.innerHTML = '<i class="bi bi-check-lg me-1"></i> Thực hiện nhập dữ liệu';
        
        wBtnCancel.classList.remove('d-none');
        wBtnCancel.disabled = false;
        wBtnImportAnother.classList.add('d-none');
        wBtnRetry.classList.add('d-none');
        wBtnCloseFinish.classList.add('d-none');
        wBtnCloseHeader.style.display = 'block';

        updateProgressHeader(1);
    }

    // Open Wizard
    document.querySelectorAll('.btn-open-import-wizard').forEach(btn => {
        btn.addEventListener('click', function() {
            wImportType = this.getAttribute('data-import-type');
            const templateUrl = this.getAttribute('data-template-url');
            
            resetWizardState();
            
            // Set Header & template download link
            if (wTitleTypeName) {
                wTitleTypeName.textContent = wImportType === 'customers' ? 'Khách hàng' : 'Dịch vụ';
            }
            if (wTemplateDownloadBtn) {
                wTemplateDownloadBtn.setAttribute('href', templateUrl);
                wTemplateDownloadBtn.innerHTML = `<i class="bi bi-download me-2"></i>Tải file mẫu ${wImportType === 'customers' ? 'Khách hàng' : 'Dịch vụ'} (.xlsx)`;
            }
            
            // Show modal
            importWizardInstance = new bootstrap.Modal(importWizardModalEl);
            importWizardInstance.show();
        });
    });

    // Helper to update progress step indicators
    function updateProgressHeader(step) {
        for (let i = 1; i <= 4; i++) {
            const el = document.getElementById(`p-step-${i}`);
            if (!el) continue;
            
            const badge = el.querySelector('.step-num');
            el.classList.remove('active', 'text-primary', 'text-success', 'text-muted');
            if (badge) {
                badge.classList.remove('bg-primary', 'bg-success', 'bg-secondary');
            }

            if (i === step) {
                el.classList.add('active', 'text-primary');
                if (badge) badge.classList.add('bg-primary');
            } else if (i < step) {
                el.classList.add('text-success');
                if (badge) badge.classList.add('bg-success');
            } else {
                el.classList.add('text-muted');
                if (badge) badge.classList.add('bg-secondary');
            }
        }
    }

    // Step 1: Upload & Auto-Analyze File
    if (wFileInput) {
        wFileInput.addEventListener('change', function() {
            const file = wFileInput.files[0];
            if (!file) {
                wBtnNext.disabled = true;
                return;
            }

            // Disable buttons during analysis
            wBtnNext.disabled = true;
            if (wUploadAlert) {
                wUploadAlert.classList.remove('d-none', 'alert-warning', 'alert-success', 'alert-danger');
                wUploadAlert.classList.add('alert-info');
                wUploadAlert.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang tải lên và phân tích tệp...';
            }

            const formData = new FormData();
            formData.append('import_file', file);
            formData.append('import_type', wImportType);

            csrfFetch('/settings/import/analyze', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    wTempFileId = data.temp_file_id;
                    wAnalysisData = data;
                    
                    wUploadAlert.classList.remove('alert-info');
                    wUploadAlert.classList.add('alert-success');
                    wUploadAlert.innerHTML = `<i class="bi bi-check-circle me-1"></i> Tệp hợp lệ! Đã phân tích thành công <strong>${data.total_rows}</strong> dòng dữ liệu.`;
                    wBtnNext.disabled = false;
                } else {
                    wTempFileId = null;
                    wAnalysisData = null;
                    wUploadAlert.classList.remove('alert-info');
                    wUploadAlert.classList.add('alert-danger');
                    wUploadAlert.innerHTML = `<i class="bi bi-x-circle me-1"></i> Lỗi định dạng: ${data.message}`;
                    wBtnNext.disabled = true;
                }
            })
            .catch(err => {
                console.error(err);
                wTempFileId = null;
                wAnalysisData = null;
                wUploadAlert.classList.remove('alert-info');
                wUploadAlert.classList.add('alert-danger');
                wUploadAlert.innerHTML = `<i class="bi bi-x-circle me-1"></i> Lỗi kết nối máy chủ khi phân tích file.`;
                wBtnNext.disabled = true;
            });
        });
    }

    // Step 2 logic: Fill Preview Table
    function fillPreviewTable() {
        const previewTableHeader = document.getElementById('previewTableHeader');
        const previewTableBody = document.getElementById('previewTableBody');
        const badgeRows = document.getElementById('preview-row-count-badge');
        
        if (!previewTableHeader || !previewTableBody || !wAnalysisData) return;

        // Headers
        let headerHtml = '<th>#</th>';
        wAnalysisData.headers.forEach(h => {
            headerHtml += `<th>${h}</th>`;
        });
        headerHtml += '<th>Trạng thái/Ghi chú kiểm tra</th>';
        previewTableHeader.innerHTML = headerHtml;

        // Preview Rows (up to 20 lines)
        let bodyHtml = '';
        wAnalysisData.preview_rows.forEach(pRow => {
            const valResult = wAnalysisData.validation_results.find(v => v.row_index === pRow.row_index);
            let rowClass = '';
            let statusText = '<span class="text-success small"><i class="bi bi-check-circle me-1"></i>Hợp lệ</span>';
            
            if (valResult) {
                if (valResult.errors && valResult.errors.length > 0) {
                    rowClass = 'table-danger';
                    statusText = `<span class="text-danger fw-semibold small" title="${valResult.errors.join('; ')}"><i class="bi bi-exclamation-octagon me-1"></i>Lỗi: ${valResult.errors.join('; ')}</span>`;
                } else if (valResult.is_duplicate) {
                    rowClass = 'table-warning';
                    statusText = `<span class="text-warning-emphasis fw-semibold small" title="${valResult.duplicate_reason}"><i class="bi bi-exclamation-triangle me-1"></i>Trùng: ${valResult.duplicate_reason}</span>`;
                }
            }

            bodyHtml += `<tr class="${rowClass}">`;
            bodyHtml += `<td class="fw-bold">${pRow.row_index}</td>`;
            pRow.cells.forEach(cellVal => {
                bodyHtml += `<td>${cellVal}</td>`;
            });
            bodyHtml += `<td>${statusText}</td>`;
            bodyHtml += '</tr>';
        });
        previewTableBody.innerHTML = bodyHtml;
        badgeRows.textContent = `Hiển thị ${wAnalysisData.preview_rows.length}/${wAnalysisData.total_rows} dòng`;

        // Validation Summary Statistics
        const summaryTotal = document.getElementById('summary-total-rows');
        const summaryError = document.getElementById('summary-error-rows');
        const summaryDuplicate = document.getElementById('summary-duplicate-rows');
        
        if (summaryTotal) summaryTotal.textContent = wAnalysisData.total_rows;
        
        const errorCount = wAnalysisData.validation_results.filter(v => v.errors && v.errors.length > 0).length;
        if (summaryError) summaryError.textContent = errorCount;
        
        const duplicateCount = wAnalysisData.validation_results.filter(v => v.is_duplicate && (!v.errors || v.errors.length === 0)).length;
        if (summaryDuplicate) summaryDuplicate.textContent = duplicateCount;
    }

    // Step Navigation
    wBtnNext.addEventListener('click', function() {
        if (wCurrentStep === 1) {
            if (!wTempFileId) return;
            // Go to Step 2
            wCurrentStep = 2;
            fillPreviewTable();
            
            wStep1Content.classList.add('d-none');
            wStep2Content.classList.remove('d-none');
            wBtnBack.disabled = false;
            updateProgressHeader(2);
        } else if (wCurrentStep === 2) {
            // Go to Step 3
            wCurrentStep = 3;
            wStep2Content.classList.add('d-none');
            wStep3Content.classList.remove('d-none');
            
            wBtnNext.classList.add('d-none');
            wBtnExecute.classList.remove('d-none');
            updateProgressHeader(3);
        }
    });

    wBtnBack.addEventListener('click', function() {
        if (wCurrentStep === 2) {
            wCurrentStep = 1;
            wStep2Content.classList.add('d-none');
            wStep1Content.classList.remove('d-none');
            wBtnBack.disabled = true;
            updateProgressHeader(1);
        } else if (wCurrentStep === 3) {
            wCurrentStep = 2;
            wStep3Content.classList.add('d-none');
            wStep2Content.classList.remove('d-none');
            
            wBtnNext.classList.remove('d-none');
            wBtnExecute.classList.add('d-none');
            updateProgressHeader(2);
        }
    });

    // Step 3: Execute Import Actual Action
    wBtnExecute.addEventListener('click', function() {
        if (!wTempFileId) return;

        // Collect inputs
        const dupActionEl = document.querySelector('input[name="duplicateAction"]:checked');
        const duplicateAction = dupActionEl ? dupActionEl.value : 'skip';
        const allOrNothing = document.getElementById('importAllOrNothing').checked;

        // Disable modal interactive controls during execution (Lock UX)
        isExecutingImport = true;
        wBtnExecute.disabled = true;
        wBtnBack.disabled = true;
        wBtnCancel.disabled = true;
        wBtnCloseHeader.style.display = 'none';
        wBtnExecute.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang tạo bản sao lưu và nhập dữ liệu...';

        csrfFetch('/settings/import/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                temp_file_id: wTempFileId,
                import_type: wImportType,
                duplicate_action: duplicateAction,
                all_or_nothing: allOrNothing
            })
        })
        .then(res => res.json())
        .then(data => {
            isExecutingImport = false;
            
            if (data.success && data.report) {
                const r = data.report;
                
                // Set Report numbers
                document.getElementById('report-total').textContent = r.total;
                document.getElementById('report-success').textContent = r.success;
                document.getElementById('report-overwritten').textContent = r.overwritten;
                document.getElementById('report-skipped').textContent = r.skipped;
                document.getElementById('report-failed').textContent = r.failed;

                // Configure error report download button
                const downloadContainer = document.getElementById('w-report-download-btn-container');
                const downloadBtn = document.getElementById('downloadErrorReportBtn');
                
                if (r.error_report_url) {
                    if (downloadContainer) downloadContainer.classList.remove('d-none');
                    if (downloadBtn) downloadBtn.setAttribute('href', r.error_report_url);
                } else {
                    if (downloadContainer) downloadContainer.classList.add('d-none');
                }

                // Adjust icon/title in case of failure or success
                const reportIcon = document.getElementById('w-report-icon');
                const reportTitle = document.getElementById('w-report-title');
                const reportDesc = document.getElementById('w-report-desc');

                if (r.failed === r.total && r.total > 0) {
                    // All failed
                    if (reportIcon) reportIcon.className = 'bi bi-x-circle-fill text-danger';
                    if (reportTitle) reportTitle.textContent = 'Nhập dữ liệu thất bại toàn bộ!';
                    if (reportDesc) reportDesc.textContent = 'Không có dòng dữ liệu nào được ghi nhận. Vui lòng kiểm tra báo cáo lỗi.';
                } else if (r.failed > 0) {
                    // Partial success
                    if (reportIcon) reportIcon.className = 'bi bi-exclamation-circle-fill text-warning';
                    if (reportTitle) reportTitle.textContent = 'Nhập dữ liệu hoàn tất với một số lỗi!';
                    if (reportDesc) reportDesc.textContent = 'Một số dòng hợp lệ đã được ghi nhận. Một số dòng lỗi bị bỏ qua.';
                } else {
                    // Success
                    if (reportIcon) reportIcon.className = 'bi bi-check-circle-fill text-success';
                    if (reportTitle) reportTitle.textContent = 'Nhập dữ liệu hoàn tất thành công!';
                    if (reportDesc) reportDesc.textContent = 'Toàn bộ dữ liệu trong tệp Excel đã được xử lý thành công.';
                }

                // Switch to Step 4
                wCurrentStep = 4;
                wStep3Content.classList.add('d-none');
                wStep4Content.classList.remove('d-none');
                
                // Hide default navigation buttons
                wBtnExecute.classList.add('d-none');
                wBtnBack.classList.add('d-none');
                wBtnCancel.classList.add('d-none');
                
                // Show result actions
                wBtnCloseFinish.classList.remove('d-none');
                wBtnCloseHeader.style.display = 'block';

                if (r.failed === r.total && r.total > 0) {
                    wBtnRetry.classList.remove('d-none');
                } else {
                    wBtnImportAnother.classList.remove('d-none');
                }

                updateProgressHeader(4);
            } else {
                Notification.error('Lỗi khi import: ' + (data.message || 'Không rõ lỗi'));
                wBtnExecute.disabled = false;
                wBtnBack.disabled = false;
                wBtnCancel.disabled = false;
                wBtnCloseHeader.style.display = 'block';
                wBtnExecute.innerHTML = '<i class="bi bi-check-lg me-1"></i> Thực hiện nhập dữ liệu';
            }
        })
        .catch(err => {
            isExecutingImport = false;
            console.error(err);
            Notification.error('Lỗi kết nối máy chủ khi thực hiện import.');
            wBtnExecute.disabled = false;
            wBtnBack.disabled = false;
            wBtnCancel.disabled = false;
            wBtnCloseHeader.style.display = 'block';
            wBtnExecute.innerHTML = '<i class="bi bi-check-lg me-1"></i> Thực hiện nhập dữ liệu';
        });
    });

    // Unified Exit & Cancel Handler (Task D3.3 Exit/ESC UX)
    importWizardModalEl.addEventListener('hide.bs.modal', function(e) {
        if (isExecutingImport) {
            e.preventDefault();
            Notification.warning("Đang nhập dữ liệu, vui lòng chờ hoàn tất.");
            return;
        }

        // If completed step 4, allow closing without confirm, it will trigger reload
        if (wCurrentStep === 4) {
            return;
        }

        // If file is selected and validated, ask user confirm
        if (wTempFileId || wAnalysisData) {
            if (!isConfirmingClose) {
                e.preventDefault();
                const confirmExit = confirm("Bạn có chắc muốn thoát khỏi Import? Mọi dữ liệu đang xem trước sẽ bị hủy.");
                if (confirmExit) {
                    isConfirmingClose = true;
                    resetWizardState();
                    const modal = bootstrap.Modal.getInstance(importWizardModalEl);
                    if (modal) modal.hide();
                    isConfirmingClose = false;
                }
            }
        }
    });

    // Reload page to refresh stats on modal hidden after successful import
    importWizardModalEl.addEventListener('hidden.bs.modal', function() {
        if (wCurrentStep === 4) {
            window.location.reload();
        }
    });

    // Close buttons & finish buttons handlers
    if (wBtnCloseFinish) {
        wBtnCloseFinish.addEventListener('click', function() {
            window.location.reload();
        });
    }

    if (wBtnCloseHeader) {
        wBtnCloseHeader.addEventListener('click', function() {
            // Under bs-dismiss, this will trigger hide.bs.modal naturally
            const modal = bootstrap.Modal.getInstance(importWizardModalEl);
            if (modal) modal.hide();
        });
    }

    // Try Again & Import Another logic
    if (wBtnRetry) {
        wBtnRetry.addEventListener('click', function() {
            resetWizardState();
        });
    }

    if (wBtnImportAnother) {
        wBtnImportAnother.addEventListener('click', function() {
            resetWizardState();
        });
    }

// ──────────────────────────────────────────────
// Backup Center Search & Sort Logic (Task D3.1)
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    const backupSearchInput = document.getElementById('backup-search');
    const backupSortSelect = document.getElementById('backup-sort');
    const backupListTbody = document.getElementById('backup-list-tbody');
    
    if (backupSearchInput && backupListTbody) {
        backupSearchInput.addEventListener('input', function() {
            const q = backupSearchInput.value.trim().toLowerCase();
            const rows = Array.from(backupListTbody.querySelectorAll('tr'));
            rows.forEach(row => {
                const name = row.getAttribute('data-name') || '';
                const filename = row.getAttribute('data-filename') || '';
                const notes = row.getAttribute('data-notes') || '';
                if (name.includes(q) || filename.includes(q) || notes.includes(q)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }

    if (backupSortSelect && backupListTbody) {
        backupSortSelect.addEventListener('change', function() {
            const val = backupSortSelect.value;
            const rows = Array.from(backupListTbody.querySelectorAll('tr'));
            
            rows.sort((a, b) => {
                if (val === 'newest') {
                    return parseFloat(b.getAttribute('data-time')) - parseFloat(a.getAttribute('data-time'));
                } else if (val === 'oldest') {
                    return parseFloat(a.getAttribute('data-time')) - parseFloat(b.getAttribute('data-time'));
                } else if (val === 'largest') {
                    return parseFloat(b.getAttribute('data-size')) - parseFloat(a.getAttribute('data-size'));
                } else if (val === 'smallest') {
                    return parseFloat(a.getAttribute('data-size')) - parseFloat(b.getAttribute('data-size'));
                } else if (val === 'name_asc') {
                    return (a.getAttribute('data-name') || '').localeCompare(b.getAttribute('data-name') || '');
                } else if (val === 'name_desc') {
                    return (b.getAttribute('data-name') || '').localeCompare(a.getAttribute('data-name') || '');
                }
                return 0;
            });
            
            rows.forEach(row => backupListTbody.appendChild(row));
        });
    }

    // ──────────────────────────────────────────────
    // Backup Center Operations (Task D3.2)
    // ──────────────────────────────────────────────
    
    // Create Backup Form Submit
    const createBackupForm = document.getElementById('createBackupForm');
    const btnConfirmCreateBackup = document.getElementById('btnConfirmCreateBackup');
    if (createBackupForm && btnConfirmCreateBackup) {
        createBackupForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Disable button and show spinner
            btnConfirmCreateBackup.disabled = true;
            const originalHTML = btnConfirmCreateBackup.innerHTML;
            btnConfirmCreateBackup.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang tạo...';
            
            const formData = new FormData(createBackupForm);
            formData.append('format', 'json');
            
            csrfFetch('/settings/backup', {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Hide Modal
                    const modalEl = document.getElementById('createBackupModal');
                    const modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                    
                    // Trigger download
                    window.location.href = data.download_url;
                    
                    // Show message
                    Notification.success('Đã tạo bản sao lưu thành công. Đang tải xuống...');
                    
                    // Reload page to refresh list after 1 second
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    Notification.error('Lỗi: ' + (data.message || 'Không thể tạo bản sao lưu.'));
                    btnConfirmCreateBackup.disabled = false;
                    btnConfirmCreateBackup.innerHTML = originalHTML;
                }
            })
            .catch(err => {
                console.error(err);
                Notification.error('Lỗi kết nối khi tạo bản sao lưu.');
                btnConfirmCreateBackup.disabled = false;
                btnConfirmCreateBackup.innerHTML = originalHTML;
            });
        });
    }

    // Edit Notes buttons click
    let activeBackupId = null;
    const editBackupNoteModalEl = document.getElementById('editBackupNoteModal');
    const editBackupNoteForm = document.getElementById('editBackupNoteForm');
    const editBackupNotesInput = document.getElementById('editBackupNotes');
    
    document.querySelectorAll('.btn-edit-backup-note').forEach(btn => {
        btn.addEventListener('click', function() {
            activeBackupId = this.getAttribute('data-id');
            const currentNotes = this.getAttribute('data-notes') || '';
            
            if (editBackupNotesInput) {
                editBackupNotesInput.value = currentNotes;
            }
            
            const modal = new bootstrap.Modal(editBackupNoteModalEl);
            modal.show();
        });
    });
    
    // Save Notes Form Submit
    if (editBackupNoteForm) {
        editBackupNoteForm.addEventListener('submit', function(e) {
            e.preventDefault();
            if (!activeBackupId) return;
            
            const newNotes = editBackupNotesInput.value.trim();
            
            csrfFetch(`/settings/backup/notes/${activeBackupId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ notes: newNotes })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const modal = bootstrap.Modal.getInstance(editBackupNoteModalEl);
                    if (modal) modal.hide();
                    Notification.success(data.message || 'Cập nhật ghi chú thành công.');
                    
                    const editBtn = document.querySelector(`.btn-edit-backup-note[data-id="${activeBackupId}"]`);
                    if (editBtn) {
                        editBtn.setAttribute('data-notes', newNotes);
                        const row = editBtn.closest('tr');
                        if (row) {
                            row.setAttribute('data-notes', newNotes.toLowerCase());
                            const noteSpan = row.querySelector('.btn-edit-backup-note').previousElementSibling;
                            if (noteSpan) {
                                noteSpan.textContent = newNotes;
                                noteSpan.setAttribute('title', newNotes);
                            }
                        }
                    }
                } else {
                    Notification.error('Lỗi: ' + (data.message || 'Không thể cập nhật ghi chú.'));
                }
            })
            .catch(err => {
                console.error(err);
                Notification.error('Lỗi kết nối khi cập nhật ghi chú.');
            });
        });
    }

    // Restore Backup buttons click
// Restore Backup Wizard
const restoreWizardModalEl = document.getElementById('restoreWizardModal');
let wizardBackupId = null;
let isExecutingRestore = false;

// Step elements
const wizardStep1 = document.getElementById('wizard-step-1');
const wizardStep2 = document.getElementById('wizard-step-2');
const wizardStep3 = document.getElementById('wizard-step-3');
const wizardStep4 = document.getElementById('wizard-step-4');

const wizardBackupName = document.getElementById('wizard-backup-name');
const wizardBackupDate = document.getElementById('wizard-backup-date');
const wizardBackupSize = document.getElementById('wizard-backup-size');
const wizardBackupDbVersion = document.getElementById('wizard-backup-db-version');
const wizardBackupAppVersion = document.getElementById('wizard-backup-app-version');
const wizardBackupNotes = document.getElementById('wizard-backup-notes');

const wizardBtnContinue1 = document.getElementById('wizard-btn-continue-1');
const wizardBtnContinue2 = document.getElementById('wizard-btn-continue-2');
const wizardBtnConfirm = document.getElementById('wizard-btn-confirm');
const wizardRestoreConfirmCheck = document.getElementById('wizardRestoreConfirmCheck');
const wizardValidationResult = document.getElementById('wizard-validation-result');
const wizardWarningMsg = document.getElementById('wizard-warning-msg');
const wizardResultMsg = document.getElementById('wizard-result-msg');

// Reusable helper to open Restore Wizard
function triggerRestoreWizard(info) {
    wizardBackupId = info.id;
    wizardBackupName.textContent = info.name || '';
    wizardBackupDate.textContent = info.date || '';
    wizardBackupSize.textContent = info.size || '';
    wizardBackupDbVersion.textContent = info.version_db || '';
    wizardBackupAppVersion.textContent = info.version_app || '';
    wizardBackupNotes.textContent = info.notes || '';
    
    wizardStep1.classList.remove('d-none');
    wizardStep2.classList.add('d-none');
    wizardStep3.classList.add('d-none');
    wizardStep4.classList.add('d-none');
    
    // Reset buttons
    const restoreCloseHeader = restoreWizardModalEl.querySelector('.btn-close');
    const closeStep4Btn = document.getElementById('wizard-btn-close-step4');
    const iconSuccess = document.getElementById('wizard-result-icon-success');
    const iconError = document.getElementById('wizard-result-icon-error');
    const reloadContainer = document.getElementById('wizard-reload-container');
    
    if (restoreCloseHeader) {
        restoreCloseHeader.style.display = 'block';
        restoreCloseHeader.disabled = false;
    }
    if (closeStep4Btn) {
        closeStep4Btn.style.display = 'inline-block';
        closeStep4Btn.disabled = false;
        closeStep4Btn.textContent = 'Đóng';
    }
    if (iconSuccess) iconSuccess.style.display = 'none';
    if (iconError) iconError.style.display = 'none';
    if (reloadContainer) reloadContainer.classList.add('d-none');
    
    // Re-enable and reset confirm button
    if (wizardBtnConfirm) {
        wizardBtnConfirm.disabled = false;
        wizardBtnConfirm.innerHTML = 'Xác nhận khôi phục';
    }
    if (wizardRestoreConfirmCheck) {
        wizardRestoreConfirmCheck.checked = false;
    }
    if (wizardBtnConfirm) {
        wizardBtnConfirm.disabled = true;
    }
    
    // Disable all dismiss attributes on cancel buttons during active restore
    document.querySelectorAll('#restoreWizardModal .btn-close, #restoreWizardModal [data-bs-dismiss="modal"]').forEach(btn => {
        btn.disabled = false;
    });

    const modal = new bootstrap.Modal(restoreWizardModalEl);
    modal.show();
}

if (wizardRestoreConfirmCheck && wizardBtnConfirm) {
    wizardRestoreConfirmCheck.addEventListener('change', function () {
        wizardBtnConfirm.disabled = !this.checked || isExecutingRestore;
    });
}

// Open wizard on restore button click
document.querySelectorAll('.btn-restore-backup').forEach(btn => {
    btn.addEventListener('click', function () {
        const row = this.closest('tr');
        const ts = parseFloat(row.getAttribute('data-time')) * 1000;
        const info = {
            id: this.getAttribute('data-id'),
            name: row.getAttribute('data-name') || '',
            date: new Date(ts).toLocaleString(),
            size: row.getAttribute('data-size') || '',
            version_db: row.dataset.versionDb || '',
            version_app: row.dataset.versionApp || '',
            notes: row.getAttribute('data-notes') || ''
        };
        triggerRestoreWizard(info);
    });
});

// Drag and Drop & Upload Backup logic
const dragDropZone = document.getElementById('backup-drag-drop-zone');
const backupFileInput = document.getElementById('backupFile');
const selectedFileInfo = document.getElementById('selected-file-info');
const selectedFilename = document.getElementById('selected-filename');
const btnConfirmUploadBackup = document.getElementById('btnConfirmUploadBackup');
const uploadBackupForm = document.getElementById('uploadBackupForm');

if (dragDropZone && backupFileInput) {
    // Highlight drop zone when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dragDropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dragDropZone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dragDropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dragDropZone.classList.remove('dragover');
        }, false);
    });

    // Handle dropped files
    dragDropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            backupFileInput.files = files;
            handleFileSelection(files[0]);
        }
    }, false);

    // Handle selected file input
    backupFileInput.addEventListener('change', function () {
        if (this.files.length > 0) {
            handleFileSelection(this.files[0]);
        }
    });
}

function handleFileSelection(file) {
    if (!file) return;
    
    // Check file extension
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    const validExtensions = ['.db', '.sqlite', '.sqlite3'];
    if (!validExtensions.includes(ext)) {
        Notification.error("Định dạng tệp không hợp lệ. Chỉ chấp nhận tệp tin .db, .sqlite, .sqlite3.");
        resetFileSelection();
        return;
    }
    
    // Check file size (limit 100MB)
    const maxSize = 100 * 1024 * 1024;
    if (file.size > maxSize) {
        Notification.error("Kích thước tệp vượt quá giới hạn (Tối đa 100MB).");
        resetFileSelection();
        return;
    }
    
    // Update UI info
    if (selectedFilename) selectedFilename.textContent = `${file.name} (${formatSize(file.size)})`;
    if (selectedFileInfo) selectedFileInfo.classList.remove('d-none');
    if (btnConfirmUploadBackup) btnConfirmUploadBackup.disabled = false;
}

function resetFileSelection() {
    if (backupFileInput) backupFileInput.value = '';
    if (selectedFilename) selectedFilename.textContent = '';
    if (selectedFileInfo) selectedFileInfo.classList.add('d-none');
    if (btnConfirmUploadBackup) btnConfirmUploadBackup.disabled = true;
}

function formatSize(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' Bytes';
}

if (uploadBackupForm) {
    uploadBackupForm.addEventListener('submit', function (e) {
        e.preventDefault();
        
        if (!backupFileInput.files || backupFileInput.files.length === 0) return;
        
        btnConfirmUploadBackup.disabled = true;
        const originalHTML = btnConfirmUploadBackup.innerHTML;
        btnConfirmUploadBackup.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang tải lên...';
        
        const formData = new FormData(uploadBackupForm);
        
        csrfFetch('/settings/backup/upload', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            btnConfirmUploadBackup.disabled = false;
            btnConfirmUploadBackup.innerHTML = originalHTML;
            
            if (data.success) {
                Notification.success(data.message || 'Tải lên bản sao lưu thành công.');
                
                // Reset file form selection for future uses
                resetFileSelection();
                document.getElementById('uploadNotes').value = '';
                
                // Hide Upload Modal
                const uploadModalEl = document.getElementById('uploadBackupModal');
                const uploadModal = bootstrap.Modal.getInstance(uploadModalEl);
                if (uploadModal) uploadModal.hide();
                
                // Auto trigger restore wizard for the imported backup
                const backupInfo = data.backup_info;
                const ts = parseFloat(backupInfo.created_at_timestamp) * 1000;
                const info = {
                    id: backupInfo.id,
                    name: backupInfo.display_name,
                    date: new Date(ts).toLocaleString(),
                    size: backupInfo.size_friendly,
                    version_db: backupInfo.version_db,
                    version_app: backupInfo.version_app,
                    notes: backupInfo.notes
                };
                
                // Small delay to ensure modal backdrop animation completes
                setTimeout(() => {
                    triggerRestoreWizard(info);
                }, 400);
            } else {
                Notification.error('Lỗi: ' + (data.message || 'Không thể tải lên bản sao lưu.'));
            }
        })
        .catch(err => {
            console.error(err);
            Notification.error('Lỗi kết nối khi tải lên bản sao lưu.');
            btnConfirmUploadBackup.disabled = false;
            btnConfirmUploadBackup.innerHTML = originalHTML;
        });
    });
}

// Step 1 -> Step 2: Validate backup
if (wizardBtnContinue1) { wizardBtnContinue1.addEventListener('click', function () {
    if (!wizardBackupId) return;
    fetch(`/settings/restore-wizard/validate/${wizardBackupId}`)
        .then(res => res.json())
        .then(data => {
            if (data.blocked) {
                wizardValidationResult.innerHTML = `<strong>Trạng thái:</strong> Bị khóa<br><strong>Thông báo:</strong> ${data.message || 'Trung tâm sao lưu đang tạm khóa trong chế độ PostgreSQL.'}`;
                if (wizardBtnContinue1) wizardBtnContinue1.disabled = true;
                if (wizardBtnContinue2) wizardBtnContinue2.disabled = true;
                if (wizardBtnConfirm) wizardBtnConfirm.disabled = true;
                if (wizardWarningMsg) wizardWarningMsg.textContent = data.message || 'Trung tâm sao lưu đang tạm khóa trong chế độ PostgreSQL.';
                return;
            }
            const integrity = data.integrity || 'Unknown';
            const compatible = data.compatible ? 'Có' : 'Không';
            wizardValidationResult.innerHTML = `<strong>Trạng thái:</strong> ${integrity}<br><strong>Khả năng tương thích:</strong> ${compatible}`;
            wizardStep1.classList.add('d-none');
            wizardStep2.classList.remove('d-none');
        })
        .catch(err => {
            console.error(err);
            Notification.error('Lỗi khi kiểm tra backup.');
        });
}); }

// Step 2 -> Step 3: Show warning / confirm
if (wizardBtnContinue2) { wizardBtnContinue2.addEventListener('click', function () {
    wizardStep2.classList.add('d-none');
    wizardStep3.classList.remove('d-none');
    wizardWarningMsg.textContent = 'Bạn chắc chắn muốn khôi phục? Thao tác này sẽ ghi đè dữ liệu hiện tại.';
}); }

// Confirm restore
if (wizardBtnConfirm) { wizardBtnConfirm.addEventListener('click', function () {
    if (!wizardBackupId) return;
    if (wizardRestoreConfirmCheck && !wizardRestoreConfirmCheck.checked) return;
    
    isExecutingRestore = true;
    wizardBtnConfirm.disabled = true;
    const originalBtnText = wizardBtnConfirm.innerHTML;
    wizardBtnConfirm.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Đang khôi phục...';
    
    const restoreCloseHeader = restoreWizardModalEl.querySelector('.btn-close');
    
    // Show Loading Overlay
    const loadingOverlay = document.getElementById('restore-loading-overlay');
    if (loadingOverlay) loadingOverlay.style.setProperty('display', 'flex', 'important');
    
    if (restoreCloseHeader) restoreCloseHeader.style.display = 'none';
    
    // Lock cancel buttons
    document.querySelectorAll('#restoreWizardModal .btn-close, #restoreWizardModal [data-bs-dismiss="modal"]').forEach(btn => {
        btn.disabled = true;
    });

    csrfFetch('/settings/restore-wizard/confirm', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({ backup_id: wizardBackupId })
    })
        .then(res => res.json())
        .then(data => {
            isExecutingRestore = false;
            
            // Hide Loading Overlay
            if (loadingOverlay) loadingOverlay.style.setProperty('display', 'none', 'important');
            
            wizardStep3.classList.add('d-none');
            wizardStep4.classList.remove('d-none');
            wizardResultMsg.textContent = data.message || (data.success ? 'Khôi phục thành công' : 'Khôi phục thất bại');
            
            const iconSuccess = document.getElementById('wizard-result-icon-success');
            const iconError = document.getElementById('wizard-result-icon-error');
            const reloadContainer = document.getElementById('wizard-reload-container');
            const closeStep4Btn = document.getElementById('wizard-btn-close-step4');
            
            if (data.success) {
                if (iconSuccess) iconSuccess.style.display = 'block';
                if (iconError) iconError.style.display = 'none';
                if (reloadContainer) reloadContainer.classList.remove('d-none');
                if (closeStep4Btn) closeStep4Btn.style.display = 'none'; // User must click "Reload"
                if (restoreCloseHeader) restoreCloseHeader.style.display = 'none'; // Lock closing
                Notification.success(data.message || 'Khôi phục cơ sở dữ liệu thành công!');
            } else {
                if (iconSuccess) iconSuccess.style.display = 'none';
                if (iconError) iconError.style.display = 'block';
                if (reloadContainer) reloadContainer.classList.add('d-none');
                if (closeStep4Btn) {
                    closeStep4Btn.style.display = 'inline-block';
                    closeStep4Btn.disabled = false;
                }
                if (restoreCloseHeader) {
                    restoreCloseHeader.style.display = 'block';
                    restoreCloseHeader.disabled = false;
                }
                Notification.error(data.message || 'Khôi phục thất bại.');
            }
        })
        .catch(err => {
            isExecutingRestore = false;
            // Hide Loading Overlay
            if (loadingOverlay) loadingOverlay.style.setProperty('display', 'none', 'important');
            
            console.error(err);
            Notification.error('Lỗi khi thực hiện khôi phục.');
            wizardBtnConfirm.disabled = false;
            wizardBtnConfirm.innerHTML = originalBtnText;
            
            document.querySelectorAll('#restoreWizardModal .btn-close, #restoreWizardModal [data-bs-dismiss="modal"]').forEach(btn => {
                btn.disabled = false;
            });
            if (restoreCloseHeader) restoreCloseHeader.style.display = 'block';
        });
}); }

// Block close / escape during restore database execution
if (restoreWizardModalEl) { restoreWizardModalEl.addEventListener('hide.bs.modal', function (e) {
    if (isExecutingRestore) {
        e.preventDefault();
        Notification.warning("Đang khôi phục cơ sở dữ liệu, vui lòng chờ hoàn tất.");
        return;
    }
}); }
    // Duplicate simple restore modal handler deactivated in favor of Restore Wizard

    // Delete Backup buttons click
    const deleteBackupModalEl = document.getElementById('deleteBackupModal');
    const deleteBackupNameSpan = document.getElementById('deleteBackupName');
    const confirmDeleteBackupBtn = document.getElementById('confirmDeleteBackupBtn');
    const deleteBackupConfirmCheck = document.getElementById('deleteBackupConfirmCheck');
    
    document.querySelectorAll('.btn-delete-backup').forEach(btn => {
        btn.addEventListener('click', function() {
            activeBackupId = this.getAttribute('data-id');
            const name = this.getAttribute('data-name');
            
            if (deleteBackupNameSpan) {
                deleteBackupNameSpan.textContent = name;
            }
            if (deleteBackupConfirmCheck) {
                deleteBackupConfirmCheck.checked = false;
            }
            if (confirmDeleteBackupBtn) {
                confirmDeleteBackupBtn.disabled = true;
            }
            
            const modal = new bootstrap.Modal(deleteBackupModalEl);
            modal.show();
        });
    });

    if (deleteBackupConfirmCheck && confirmDeleteBackupBtn) {
        deleteBackupConfirmCheck.addEventListener('change', function () {
            confirmDeleteBackupBtn.disabled = !this.checked;
        });
    }
    
    // Confirm Delete Button Click
    if (confirmDeleteBackupBtn) {
        confirmDeleteBackupBtn.addEventListener('click', function() {
            if (!activeBackupId) return;
            if (deleteBackupConfirmCheck && !deleteBackupConfirmCheck.checked) return;
            
            confirmDeleteBackupBtn.disabled = true;
            
            csrfFetch(`/settings/backup/delete/${activeBackupId}`, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(res => res.json())
            .then(data => {
                confirmDeleteBackupBtn.disabled = false;
                if (data.success) {
                    const modal = bootstrap.Modal.getInstance(deleteBackupModalEl);
                    if (modal) modal.hide();
                    
                    Notification.success(data.message || 'Đã xóa bản sao lưu vĩnh viễn.');
                    
                    const deleteBtn = document.querySelector(`.btn-delete-backup[data-id="${activeBackupId}"]`);
                    if (deleteBtn) {
                        const row = deleteBtn.closest('tr');
                        if (row) {
                            row.style.transition = 'opacity 0.4s ease';
                            row.style.opacity = '0';
                            setTimeout(() => {
                                row.remove();
                                const remainingRows = document.querySelectorAll('#backup-list-tbody tr');
                                if (remainingRows.length === 0) {
                                    window.location.reload();
                                }
                            }, 400);
                        }
                    }
                } else {
                    Notification.error('Lỗi: ' + (data.message || 'Xóa thất bại.'));
                }
            })
            .catch(err => {
                console.error(err);
                Notification.error('Lỗi kết nối khi xóa bản sao lưu.');
                confirmDeleteBackupBtn.disabled = false;
            });
        });
    }
});
