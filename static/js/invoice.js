document.addEventListener('DOMContentLoaded', function() {
    const servicesData = JSON.parse(document.getElementById('services-data')?.textContent || '[]');
    const itemsContainer = document.getElementById('invoice-items');
    const addRowBtn = document.getElementById('add-row-btn');
    const subtotalDisplay = document.getElementById('subtotal-display');
    const discountInput = document.getElementById('discount');
    const discountDisplay = document.getElementById('discount-display');
    const totalDisplay = document.getElementById('total-display');
    const invoiceForm = document.getElementById('invoice-form');

    if (!itemsContainer || !addRowBtn) return;



    function updateRowNumbering() {
        const rows = itemsContainer.querySelectorAll('tr');
        rows.forEach((row, index) => {
            row.querySelector('.row-number').textContent = index + 1;
        });
    }

    function calculateTotals() {
        let subtotal = 0;
        const rows = itemsContainer.querySelectorAll('tr');
        
        rows.forEach(row => {
            const price = parseFloat(row.querySelector('.item-price').value) || 0;
            const qty = parseInt(row.querySelector('.item-qty').value) || 0;
            subtotal += price * qty;
        });

        const discount = parseFloat(discountInput.value) || 0;
        const total = subtotal - discount;

        subtotalDisplay.textContent = formatCurrency(subtotal);
        discountDisplay.textContent = formatCurrency(discount);
        totalDisplay.textContent = formatCurrency(total < 0 ? 0 : total);
    }

    function addRow() {
        const rowId = Date.now();
        const row = document.createElement('tr');
        row.innerHTML = `
            <td class="text-center row-number">1</td>
            <td>
                <select class="form-select item-service" name="service_id[]" required>
                    <option value="">-- Chọn dịch vụ --</option>
                    ${servicesData.map(s => `<option value="${s.id}">${s.name}</option>`).join('')}
                </select>
            </td>
            <td class="text-center">
                <input type="number" class="form-control text-center item-qty" name="quantity[]" value="1" min="1" required>
            </td>
            <td class="text-end">
                <input type="number" class="form-control text-end item-price" name="price[]" step="0.01" required>
            </td>
            <td class="text-end fw-bold item-total">0đ</td>
            <td class="text-center">
                <button type="button" class="btn btn-sm btn-outline-danger btn-delete-row">
                    <i class="bi bi-trash"></i>
                </button>
            </td>
        `;
        itemsContainer.appendChild(row);
        updateRowNumbering();
        
        // Add event listeners to the new row
        const serviceSelect = row.querySelector('.item-service');
        const priceInput = row.querySelector('.item-price');
        const qtyInput = row.querySelector('.item-qty');
        const deleteBtn = row.querySelector('.btn-delete-row');

        serviceSelect.addEventListener('change', function() {
            const service = servicesData.find(s => s.id == this.value);
            if (service) {
                priceInput.value = service.price;
            }
            calculateRowTotal(row);
        });

        qtyInput.addEventListener('input', function() {
            calculateRowTotal(row);
        });

        priceInput.addEventListener('input', function() {
            calculateRowTotal(row);
        });

        deleteBtn.addEventListener('click', function() {
            row.remove();
            updateRowNumbering();
            calculateTotals();
        });

        calculateRowTotal(row);
    }

    function calculateRowTotal(row) {
        const price = parseFloat(row.querySelector('.item-price').value) || 0;
        const qty = parseInt(row.querySelector('.item-qty').value) || 0;
        const total = price * qty;
        row.querySelector('.item-total').textContent = formatCurrency(total);
        calculateTotals();
    }

    // Initial row
    addRow();

    // Event listeners
    addRowBtn.addEventListener('click', addRow);
    discountInput.addEventListener('input', calculateTotals);

    // Form validation
    invoiceForm.addEventListener('submit', function(e) {
        const rows = itemsContainer.querySelectorAll('tr');
        if (rows.length === 0) {
            e.preventDefault();
            Notification.warning('Vui lòng chọn ít nhất một dịch vụ.');
            return;
        }
        
        // Check if any service is not selected
        const unselected = itemsContainer.querySelectorAll('.item-service:invalid');
        if (unselected.length > 0) {
            e.preventDefault();
            Notification.warning('Vui lòng chọn dịch vụ cho tất cả các dòng.');
            return;
        }
    });
});