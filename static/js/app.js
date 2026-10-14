let state = {
    currentBookingId: null,
    currentPaymentBookingId: null,
    calendarDate: new Date(),
    settings: null,
    allUpcomingBookings: [],
    bookingFromPage: 'search-booking',
};

function $(id) { return document.getElementById(id); }
function showToast(msg, type) {
    if (type === undefined) type = 'success';
    var c = $('toast-container');
    var t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(function() { t.remove(); }, 3000);
}
function showModal(id) { $(id).classList.add('active'); }
function closeModal(id) { $(id).classList.remove('active'); }
function formatCurrency(n) {
    return '\u20B9' + Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function formatDate(d) {
    if (!d) return '';
    var dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}
function fmtCurrency(n) {
    var num = Number(n || 0);
    return 'Rs. ' + num.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}
function fmtDate(d) {
    if (!d) return '';
    var parts = d.split('-');
    if (parts.length === 3) return parts[2] + '-' + parts[1] + '-' + parts[0];
    var dt = new Date(d + 'T00:00:00');
    return String(dt.getDate()).padStart(2, '0') + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + dt.getFullYear();
}
function fmtTime(t) {
    if (!t) return '';
    var parts = t.split(':');
    var h = parseInt(parts[0], 10);
    var m = parts[1] || '00';
    var ampm = h >= 12 ? 'PM' : 'AM';
    if (h === 0) h = 12;
    else if (h > 12) h = h - 12;
    return h + ':' + m + ' ' + ampm;
}
function formatPhone(phone) {
    var p = phone.replace(/\D/g, '');
    if (p.length === 10) return '91' + p;
    if (p.length === 12 && p.startsWith('91')) return p;
    if (p.length === 11 && p.startsWith('0')) return '91' + p.slice(1);
    return null;
}
function openWhatsApp(phone, message) {
    var code = formatPhone(phone);
    if (!code) { showToast('Please enter a valid mobile number before sending a WhatsApp message.', 'error'); return; }
    var url = 'https://wa.me/' + code + '?text=' + encodeURIComponent(message);
    window.open(url, '_blank');
    showToast('WhatsApp message is ready to send.');
}
function bookingConfirmationMsg(b) {
    var s = state.settings || {};
    var biz = s.business_name || 'SM MOIDEEN TRADERS';
    var phone = s.phone || '';
    return '*' + biz + '*\n\n' +
        'Hello *' + b.customer_name + '*, \n\n' +
        'Your booking has been confirmed successfully.\n\n' +
        '----------------------------------------\n\n' +
        'Token Number\n' + b.token_number + '\n\n' +
        'Order Details\n\n' +
        'Mutton Biriyani : ' + (b.mutton_qty || '0') + ' Padi\n' +
        'Chicken 65      : ' + (b.chicken_qty || '0') + ' Kg\n\n' +
        '----------------------------------------\n\n' +
        'Payment Details\n\n' +
        'Total Amount    : ' + fmtCurrency(b.grand_total) + '\n' +
        'Advance Paid    : ' + fmtCurrency(b.advance_paid) + '\n' +
        'Balance Amount  : ' + fmtCurrency(b.balance) + '\n\n' +
        '----------------------------------------\n\n' +
        'Collection Details\n\n' +
        'Date : ' + fmtDate(s.collection_date || b.function_date) + '\n' +
        'Time : ' + fmtTime(s.collection_time || b.pickup_time) + '\n\n' +
        'Please bring your Token Number or Receipt during collection.\n\n' +
        'Thank you for choosing *' + biz + '*.\n\n' +
        'Contact : ' + phone;
}
function paymentReceiptMsg(b, amount) {
    var biz = state.settings?.business_name || 'SM MOIDEEN TRADERS';
    var phone = state.settings?.phone || '';
    var remaining = Number(b.balance || 0);
    var fullyPaid = remaining === 0;
    return '*' + biz + '*\n\n' +
        'Hello *' + b.customer_name + '*, \n\n' +
        'Your payment has been received successfully.\n\n' +
        '----------------------------------------\n\n' +
        'Token Number\n\n' +
        b.token_number + '\n\n' +
        'Amount Received : ' + fmtCurrency(amount) + '\n\n' +
        'Remaining Balance : ' + fmtCurrency(remaining) + '\n\n' +
        '----------------------------------------\n\n' +
        'Thank you for your payment.\n\n' +
        (fullyPaid ? 'Your booking is now fully paid.\n\n' : '') +
        'Contact : ' + phone;
}
async function sendWhatsAppMsg(id, type) {
    try {
        var b = await api('GET', '/bookings/' + id);
        if (type === 'collection') openWhatsApp(b.phone, collectionConfirmationMsg(b));
        else if (type === 'payment') {
            var payments = b.payments || [];
            var lastPmt = payments.length > 0 ? payments[payments.length - 1].amount : b.advance_paid;
            openWhatsApp(b.phone, paymentReceiptMsg(b, lastPmt));
        }
        else openWhatsApp(b.phone, bookingConfirmationMsg(b));
    } catch(e) { showToast('Could not load booking.', 'error'); }
}
function collectionConfirmationMsg(b) {
    var biz = state.settings?.business_name || 'SM MOIDEEN TRADERS';
    var phone = state.settings?.phone || '';
    var paidStatus = b.balance <= 0 ? 'Paid' : 'Pending';
    return '*' + biz + '*\n\n' +
        'Hello *' + b.customer_name + '*, \n\n' +
        'Your order has been collected successfully.\n\n' +
        '----------------------------------------\n\n' +
        'Token Number\n\n' +
        b.token_number + '\n\n' +
        'Mutton Biriyani : ' + (b.mutton_qty || '0') + ' Padi\n\n' +
        'Chicken 65 : ' + (b.chicken_qty || '0') + ' Kg\n\n' +
        '----------------------------------------\n\n' +
        'Payment Status : ' + paidStatus + '\n\n' +
        'Remaining Balance : ' + fmtCurrency(b.balance) + '\n\n' +
        '----------------------------------------\n\n' +
        'Thank you for choosing *' + biz + '*.\n\n' +
        'We look forward to serving you again.\n\n' +
        'Contact : ' + phone;
}
function showSuccessPopup(opts) {
    var modal = $('success-modal-content');
    var html = '<div class="modal-icon">' + (opts.icon || '&#x2714;') + '</div>' +
        '<h3>' + opts.title + '</h3>';
    if (opts.info) html += opts.info;
    html += '<div id="wa-error" class="wa-error" style="display:none;"></div>' +
        '<div class="btn-group">';
    for (var i = 0; i < opts.buttons.length; i++) {
        html += '<button class="btn ' + opts.buttons[i].cls + ' btn-lg" data-idx="' + i + '">' + opts.buttons[i].label + '</button>';
    }
    html += '</div>';
    modal.innerHTML = html;
    var btns = modal.querySelectorAll('.btn-group button');
    for (var i = 0; i < btns.length; i++) {
        btns[i].onclick = opts.buttons[i].action;
    }
    showModal('success-modal');
}
function sendWhatsAppFromPopup(b, type) {
    var errorEl = $('wa-error');
    var code = formatPhone(b.phone);
    if (!code) {
        errorEl.textContent = 'No valid customer mobile number is available. Please update the customer\'s phone number before sending a WhatsApp message.';
        errorEl.style.display = 'block';
        return;
    }
    errorEl.style.display = 'none';
    var msg;
    if (type === 'payment') {
        var payments = b.payments || [];
        var lastPmt = payments.length > 0 ? payments[payments.length - 1].amount : b.advance_paid;
        msg = paymentReceiptMsg(b, lastPmt);
    } else if (type === 'collection') {
        msg = collectionConfirmationMsg(b);
    } else {
        msg = bookingConfirmationMsg(b);
    }
    openWhatsApp(b.phone, msg);
}
function todayStr() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}
function getStatusBadge(status) {
    var labels = { pending: 'Pending', collected: 'Collected', cancelled: 'Cancelled' };
    return '<span class="status-badge ' + status + '"><span class="status-dot"></span>' + (labels[status] || status) + '</span>';
}
async function api(method, url, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body && method !== 'GET') opts.body = JSON.stringify(body);
    var fetchUrl = '/api' + url;
    if (method === 'GET') fetchUrl += (url.includes('?') ? '&' : '?') + '_t=' + Date.now();
    try {
        var res = await fetch(fetchUrl, opts);
        if (!res.ok) {
            var err = await res.json().catch(function() { return { detail: 'Request failed' }; });
            throw new Error(err.detail || 'Request failed');
        }
        return await res.json();
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}
function escHtml(s) {
    var div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
}
function showPage(page) {
    document.querySelectorAll('.page-section').forEach(function(s) { s.classList.remove('active'); });
    var target = $('page-' + page);
    if (target) target.classList.add('active');
    var titles = {
        dashboard: 'SM MOIDEEN TRADERS', 'new-booking': 'New Booking',
        'search-booking': 'Search Booking', 'upcoming-bookings': 'Upcoming Bookings',
        'pending-payments': 'Pending Payments', 'scan-collection': 'Scan Collection',
        reports: 'Reports', settings: 'Settings',
    };
    $('app-title').textContent = titles[page] || 'SM MOIDEEN TRADERS';
    switch (page) {
        case 'new-booking': initNewBooking(); break;
        case 'search-booking': initSearch(); break;
        case 'upcoming-bookings': initUpcoming(); break;
        case 'pending-payments': loadPendingPayments(); break;
        case 'scan-collection': initScanCollection(); break;
        case 'reports': initReports(); break;
        case 'settings': loadSettings(); break;
    }
}
function isValidQuantityStep(qty) {
    if (qty === 0 || !qty) return true;
    if (qty < 0) return false;
    // Must be in increments of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25)
    return Math.round(qty * 1000) % 250 === 0;
}

function initNewBooking() {
    $('booking-date').value = formatDate(todayStr());
    $('token-number').value = 'Auto-generated (e.g. SMM0001)';
    loadPricesAndDefaults();
    calcTotals();
}

async function loadPricesAndDefaults() {
    try {
        var s = await api('GET', '/settings');
        state.settings = s;
$('display-mutton-price').textContent = formatCurrency(s.mutton_biriyani_price) + ' / Padi';
        $('display-chicken-price').textContent = formatCurrency(s.chicken_65_price) + ' / Kg';
        $('function-date').value = s.collection_date || todayStr();
        if (s.collection_time) $('pickup-time').value = s.collection_time;
        calcTotals();
    } catch(e) {}
}

function calcTotals() {
    var s = state.settings;
    if (!s) return;
    var mQty = parseFloat($('mutton-qty').value) || 0;
    var cQty = parseFloat($('chicken-qty').value) || 0;
    var mTotal = mQty * s.mutton_biriyani_price;
    var cTotal = cQty * s.chicken_65_price;
    var grand = mTotal + cTotal;
    var adv = parseFloat($('advance-paid').value) || 0;
    var bal = grand - adv;
    $('mutton-total').textContent = formatCurrency(mTotal);
    $('chicken-total').textContent = formatCurrency(cTotal);
    $('grand-total').textContent = formatCurrency(grand);
    $('balance').value = formatCurrency(bal);
}

async function saveBooking(e) {
    e.preventDefault();
    var s = state.settings;
    if (!s || (s.mutton_biriyani_price === 0 && s.chicken_65_price === 0)) {
        showToast('Please set item prices in Settings first.', 'error');
        return;
    }
    var data = {
        customer_name: $('customer-name').value.trim(),
        phone: $('customer-phone').value.trim(),
        village: $('customer-village').value.trim(),
        function_date: $('function-date').value,
        pickup_time: $('pickup-time').value,
        mutton_qty: parseFloat($('mutton-qty').value) || 0,
        chicken_qty: parseFloat($('chicken-qty').value) || 0,
        advance_paid: parseFloat($('advance-paid').value) || 0,
        notes: $('booking-notes').value.trim(),
    };
    if (!data.customer_name) { showToast('Please enter customer name.', 'error'); return; }
    if (!data.phone) { showToast('Please enter phone number.', 'error'); return; }
    if (!data.function_date) { showToast('Please select collection date.', 'error'); return; }
    if (data.mutton_qty === 0 && data.chicken_qty === 0) {
        showToast('Please order at least one item.', 'error');
        return;
    }
    if (!isValidQuantityStep(data.mutton_qty)) {
        showToast('Mutton Biriyani quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('mutton-qty').focus();
        return;
    }
    if (!isValidQuantityStep(data.chicken_qty)) {
        showToast('Chicken 65 quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('chicken-qty').focus();
        return;
    }
    try {
        var booking = await api('POST', '/bookings', data);
        state.currentBookingId = booking.id;
        state.lastBooking = booking;
        resetBookingForm();
        showSuccessPopup({
            title: 'Booking Created Successfully',
            info: '<p>Token Number</p><div class="token-display">' + booking.token_number + '</div>',
            buttons: [
                { label: 'Print Receipt', cls: 'btn-primary', action: function() { printReceipt(booking.id); } },
                { label: 'Send WhatsApp', cls: 'btn-success', action: function() { sendWhatsAppFromPopup(booking, 'booking'); } },
                { label: 'New Booking', cls: 'btn-accent', action: function() { closeModal('success-modal'); resetBookingForm(); showPage('new-booking'); } },
                { label: 'Home', cls: 'btn-secondary', action: function() { closeModal('success-modal'); showPage('dashboard'); } }
            ]
        });
    } catch(e) {}
}

function resetBookingForm() {
    $('booking-form').reset();
    $('booking-notes').value = '';
    $('booking-date').value = formatDate(todayStr());
    $('token-number').value = 'Auto-generated (e.g. SMM0001)';
    calcTotals();
    loadPricesAndDefaults();
}
var searchTimeout = null;

function initSearch() {
    $('search-input').value = '';
    $('search-results').innerHTML = '';
    $('search-input').focus();
}

function searchBookings() {
    clearTimeout(searchTimeout);
    var q = $('search-input').value.trim();
    if (q.length < 1) { $('search-results').innerHTML = ''; return; }
    searchTimeout = setTimeout(async function () {
        try {
            var bookings = await api('GET', '/bookings?search=' + encodeURIComponent(q) + '&limit=30');
            renderSearchResults(bookings);
        } catch(e) {}
    }, 300);
}

function renderSearchResults(bookings) {
    var container = $('search-results');
    if (!bookings || bookings.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">??</div><h3>No bookings found</h3><p>Try a different search term</p></div>';
        return;
    }
    container.innerHTML = bookings.map(function (b) {
        return '<div class="card">' +
            '<div class="card-header"><span class="card-token">' + b.token_number + '</span>' + getStatusBadge(b.status) + '</div>' +
            '<div class="card-body">' +
            '<p><strong>Customer</strong> ' + escHtml(b.customer_name) + '</p>' +
            '<p><strong>Phone</strong> ' + escHtml(b.phone) + '</p>' +
            '<p><strong>Collection</strong> ' + formatDate(b.function_date) + '</p>' +
            '<p><strong>Total</strong> <span class="card-highlight">' + formatCurrency(b.grand_total) + '</span></p>' +
            '<p><strong>Advance</strong> ' + formatCurrency(b.advance_paid) + '</p>' +
            '<p><strong>Balance</strong> <span style="color:' + (b.balance > 0 ? 'var(--danger)' : 'var(--success)') + '">' + formatCurrency(b.balance) + '</span></p>' +
            '<p><strong>Payment</strong> ' + getPaymentStatusBadge(b.balance) + '</p>' +
            '</div>' +
            '<div class="card-actions"><button class="btn btn-primary btn-sm" onclick="viewBooking(' + b.id + ', \'search-booking\')">View Details</button>' +
            (b.status === 'collected' ? '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'collection\')">\uD83D\uDCAC WhatsApp</button>' :
             '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'booking\')">\uD83D\uDCAC WhatsApp</button>') + '</div>' +
            '</div>';
    }).join('');
}

async function viewBooking(id, fromPage) {
    try {
        var b = await api('GET', '/bookings/' + id);
        state.currentBookingId = b.id;
        if (fromPage) state.bookingFromPage = fromPage;
        showPage('booking-details');
        renderBookingDetail(b);
    } catch(e) {}
}

function renderBookingDetail(b) {
    $('detail-title').textContent = 'Booking #' + b.token_number;
    var paymentRows = (b.payments || []).map(function (p) {
        return '<div class="payment-item">' +
            '<span class="payment-date">' + formatDate(p.payment_date) + '</span>' +
            '<span class="payment-amount">' + formatCurrency(p.amount) + '</span>' +
            '<span style="color:var(--text-light);font-size:0.8rem;">' + (p.notes || '') + '</span></div>';
    }).join('');
    if (!paymentRows) paymentRows = '<div style="color:var(--text-light);font-size:0.85rem;">No payments recorded</div>';

    $('booking-detail-content').innerHTML =
        '<div class="form-section"><div class="form-section-title">Customer Details</div><div class="detail-grid">' +
        '<div class="detail-item"><span class="detail-label">Name</span><span class="detail-value">' + escHtml(b.customer_name) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Phone</span><span class="detail-value">' + escHtml(b.phone) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Village</span><span class="detail-value">' + (escHtml(b.village) || '-') + '</span></div></div></div>' +
        '<div class="form-section"><div class="form-section-title">Booking Details</div><div class="detail-grid">' +
        '<div class="detail-item"><span class="detail-label">Token</span><span class="detail-value" style="font-weight:700;color:var(--primary);">' + b.token_number + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Status</span><span class="detail-value">' + getStatusBadge(b.status) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Payment Status</span><span class="detail-value">' + getPaymentStatusBadge(b.balance) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Booking Date</span><span class="detail-value">' + formatDate(b.booking_date) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Collection Date</span><span class="detail-value">' + formatDate(b.function_date) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Collection Time</span><span class="detail-value">' + (b.pickup_time || '-') + '</span></div></div></div>' +
        '<div class="form-section"><div class="form-section-title">Ordered Items</div><div class="detail-grid">' +
'<div class="detail-item"><span class="detail-label">Mutton Biriyani</span><span class="detail-value">' + b.mutton_qty + ' Padi x ' + formatCurrency(b.mutton_price_per_kg) + ' = ' + formatCurrency(b.mutton_qty * b.mutton_price_per_kg) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Chicken 65</span><span class="detail-value">' + b.chicken_qty + ' Kg x ' + formatCurrency(b.chicken_price_per_kg) + ' = ' + formatCurrency(b.chicken_qty * b.chicken_price_per_kg) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Grand Total</span><span class="detail-value amount" style="font-size:1.2rem;">' + formatCurrency(b.grand_total) + '</span></div></div></div>' +
        '<div class="form-section"><div class="form-section-title">Payment Details</div><div class="detail-grid">' +
        '<div class="detail-item"><span class="detail-label">Advance Paid</span><span class="detail-value paid">' + formatCurrency(b.advance_paid) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Balance</span><span class="detail-value balance">' + formatCurrency(b.balance) + '</span></div></div>' +
        '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border-light);">' +
        '<div style="font-size:0.85rem;font-weight:600;color:var(--text-secondary);margin-bottom:8px;">Payment History</div>' + paymentRows + '</div></div>' +
        '<div class="form-section"><div class="form-section-title">Notes</div>' +
        '<p style="color:var(--text-secondary);font-size:0.9rem;">' + (b.notes || 'No notes') + '</p></div>' +
        '<div class="card-actions" style="margin-top:16px;">' +
        (b.status === 'pending' ? '<button class="btn btn-success btn-lg" onclick="openCollectionModal(' + b.id + ')">Mark as Collected</button>' : '') +
        '<button class="btn btn-accent btn-lg" onclick="openPaymentModal(' + b.id + ', \'' + escHtml(b.customer_name) + '\', \'' + b.token_number + '\', ' + b.balance + ')">Update Payment</button>' +
        (b.status === 'collected' ? '<button class="btn btn-success btn-lg" onclick="sendWhatsAppMsg(' + b.id + ', \'collection\')">\uD83D\uDCAC Send Collection Confirmation</button>' : '') +
        (b.status !== 'collected' && b.advance_paid > 0 ? '<button class="btn btn-success btn-lg" onclick="sendWhatsAppMsg(' + b.id + ', \'payment\')">\uD83D\uDCAC Send Payment Receipt</button>' : '') +
        (b.status !== 'collected' && b.advance_paid === 0 ? '<button class="btn btn-success btn-lg" onclick="sendWhatsAppMsg(' + b.id + ', \'booking\')">\uD83D\uDCAC Send Booking Confirmation</button>' : '') +
        '<button class="btn btn-secondary btn-lg" onclick="printReceipt(' + b.id + ')">Print Receipt</button>' +
        '<button class="btn btn-secondary btn-lg" onclick="openEditModal(' + b.id + ')">Edit Booking</button></div>' +
        '<button class="btn btn-ghost btn-block mt-16" onclick="goBackFromBooking()" style="color:var(--text-secondary);">Back</button>';
}
function getPaymentStatusBadge(balance) {
    if (balance <= 0) {
        return '<span class="status-badge paid">&#10003; Paid</span>';
    }
    return '<span class="status-badge pending-balance">&#128992; Pending Balance</span>';
}

function openCollectionModal(id) {
    api('GET', '/bookings/' + id).then(function(b) {
        if (b.status === 'collected') {
            showToast('Already collected!', 'error');
            return;
        }
        state.currentBookingId = id;
        $('col-customer').textContent = b.customer_name;
        $('col-token').textContent = b.token_number;
        $('col-total').textContent = '\u20B9' + b.grand_total.toFixed(2);
        $('col-advance').textContent = '\u20B9' + b.advance_paid.toFixed(2);
        $('col-balance').textContent = '\u20B9' + b.balance.toFixed(2);
        $('col-balance').dataset.balance = b.balance;
        $('col-amount').value = 0;
        $('col-amount').step = '0.01';
        calcCollectionBalance();
        showModal('collection-modal');
        setTimeout(function() { $('col-amount').focus(); }, 100);
    }).catch(function() {});
}

function calcCollectionBalance() {
    var balance = parseFloat($('col-balance').dataset.balance) || 0;
    var received = parseFloat($('col-amount').value) || 0;
    var newBalance = Math.max(0, balance - received);
    $('col-new-balance').value = '\u20B9' + newBalance.toFixed(2);
}

function goBackFromBooking() {
    var target = state.bookingFromPage || 'search-booking';
    showPage(target);
    if (target === 'upcoming-bookings') loadUpcoming(currentUpcomingFilter);
    else if (target === 'pending-payments') loadPendingPayments();
    else if (target === 'search-booking') initSearch();
    else if (target === 'reports') loadReport(currentReportPeriod, currentReportSort);
}

async function confirmCollection() {
    var id = state.currentBookingId;
    var amountReceived = parseFloat($('col-amount').value) || 0;
    try {
        await api('POST', '/bookings/' + id + '/collect', { amount_received: amountReceived });
        closeModal('collection-modal');
        showToast('Booking marked as collected!');
        var currentPage = document.querySelector('.page-section.active');
        if (currentPage && currentPage.id === 'page-booking-details') {
            viewBooking(id, state.bookingFromPage);
        } else {
            loadUpcoming(currentUpcomingFilter);
        }
    } catch(e) {}
}

function openPaymentModal(id, name, token, balance) {
    state.currentPaymentBookingId = id;
    $('pmt-customer').textContent = name;
    $('pmt-token').textContent = token;
    $('pmt-balance').textContent = '\u20B9' + balance.toFixed(2);
    $('pmt-amount').value = '';
    $('pmt-notes').value = '';
    $('pmt-amount').max = balance;
    $('pmt-amount').step = '0.01';
    $('pmt-amount').placeholder = 'Enter amount (max ' + balance.toFixed(2) + ')';
    showModal('payment-modal');
    setTimeout(function() { $('pmt-amount').focus(); }, 100);
}

async function submitPayment() {
    var id = state.currentPaymentBookingId;
    var amount = parseFloat($('pmt-amount').value);
    var notes = $('pmt-notes').value.trim();
    if (!amount || amount <= 0) { showToast('Please enter a valid amount.', 'error'); return; }
    try {
        var b = await api('POST', '/bookings/' + id + '/payment', { amount: amount, notes: notes });
        closeModal('payment-modal');
        showSuccessPopup({
            title: 'Payment Updated Successfully',
            buttons: [
                { label: 'Send WhatsApp', cls: 'btn-success', action: function() { sendWhatsAppFromPopup(b, 'payment'); } },
                { label: 'Close', cls: 'btn-secondary', action: function() {
                    closeModal('success-modal');
                    var currentPage = document.querySelector('.page-section.active');
                    if (currentPage && currentPage.id === 'page-pending-payments') {
                        loadPendingPayments();
                    } else if (currentPage && currentPage.id === 'page-booking-details') {
                        viewBooking(id, state.bookingFromPage);
                    } else {
                        loadUpcoming(currentUpcomingFilter);
                    }
                } }
            ]
        });
    } catch(e) {}
}

async function openEditModal(id) {
    try {
        var b = await api('GET', '/bookings/' + id);
        $('edit-name').value = b.customer_name;
        $('edit-phone').value = b.phone;
        $('edit-village').value = b.village || '';
        $('edit-func-date').value = b.function_date;
        $('edit-pickup').value = b.pickup_time || '';
        $('edit-mutton').value = b.mutton_qty;
        $('edit-chicken').value = b.chicken_qty;
        $('edit-notes').value = b.notes || '';
        showModal('edit-modal');
        state.currentBookingId = id;
    } catch(e) {}
}

async function submitEdit(e) {
    e.preventDefault();
    var id = state.currentBookingId;
    var data = {
        customer_name: $('edit-name').value.trim(),
        phone: $('edit-phone').value.trim(),
        village: $('edit-village').value.trim(),
        function_date: $('edit-func-date').value,
        pickup_time: $('edit-pickup').value,
        mutton_qty: parseFloat($('edit-mutton').value) || 0,
        chicken_qty: parseFloat($('edit-chicken').value) || 0,
        notes: $('edit-notes').value.trim(),
    };
    if (!data.customer_name || !data.phone || !data.function_date) {
        showToast('Please fill in required fields.', 'error');
        return;
    }
    if (!isValidQuantityStep(data.mutton_qty)) {
        showToast('Mutton Biriyani quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('edit-mutton').focus();
        return;
    }
    if (!isValidQuantityStep(data.chicken_qty)) {
        showToast('Chicken 65 quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('edit-chicken').focus();
        return;
    }
    try {
        await api('PUT', '/bookings/' + id, data);
        closeModal('edit-modal');
        showToast('Booking updated successfully!');
        viewBooking(id, state.bookingFromPage);
    } catch(e) {}
}

async function printReceipt(id) {
    var win = window.open('', '_blank');
    if (!win) { showToast('Please allow popups for this site to print receipts.', 'error'); return; }
    win.document.write('<html><head><title>Loading...</title></head><body><p style="font-family:sans-serif;padding:40px;text-align:center;">Loading receipt...</p></body></html>');
    win.document.close();
    try {
        var b = await api('GET', '/bookings/' + id);
        var s = await api('GET', '/settings');
        var receipt = '<div class="receipt" id="receipt-content">' +
            '<div class="receipt-header">' +
            '<h2>' + escHtml(s.business_name) + '</h2>' +
            (s.address ? '<p>' + escHtml(s.address) + '</p>' : '') +
            (s.phone ? '<p>Phone: ' + escHtml(s.phone) + '</p>' : '') +
            '<p style="font-size:1.1rem;font-weight:700;text-align:center;margin:8px 0;">RECEIPT</p></div>' +
            '<div style="text-align:center;margin:12px 0;">' +
            '<svg id="barcode"></svg></div>' +
            '<div class="receipt-body">' +
            '<div class="receipt-row"><span>Token</span><strong>' + b.token_number + '</strong></div>' +
            '<div class="receipt-row"><span>Customer</span><strong>' + escHtml(b.customer_name) + '</strong></div>' +
            '<div class="receipt-row"><span>Phone</span><span>' + escHtml(b.phone) + '</span></div>' +
            (b.village ? '<div class="receipt-row"><span>Village</span><span>' + escHtml(b.village) + '</span></div>' : '') +
            '<div class="receipt-row"><span>Booking Date</span><span>' + formatDate(b.booking_date) + '</span></div>' +
            '<div class="receipt-row"><span>Collection Date</span><span>' + formatDate(b.function_date) + '</span></div>' +
            (b.pickup_time ? '<div class="receipt-row"><span>Collection Time</span><span>' + b.pickup_time + '</span></div>' : '') +
            '<div style="border-top:1px dashed #ccc;margin:8px 0;padding-top:8px;">' +
            (b.mutton_qty > 0 ? '<div class="receipt-row"><span>Mutton Biriyani</span><span>' + b.mutton_qty + ' Padi x ' + formatCurrency(b.mutton_price_per_kg) + '</span></div>' : '') +
            (b.chicken_qty > 0 ? '<div class="receipt-row"><span>Chicken 65</span><span>' + b.chicken_qty + ' Kg x ' + formatCurrency(b.chicken_price_per_kg) + '</span></div>' : '') +
            '</div>' +
            '<div class="receipt-row total"><span>Total Amount</span><span>' + formatCurrency(b.grand_total) + '</span></div>' +
            '<div class="receipt-row"><span>Advance Paid</span><span>' + formatCurrency(b.advance_paid) + '</span></div>' +
            '<div class="receipt-row"><span>Balance</span><span>' + formatCurrency(b.balance) + '</span></div></div>' +
            '<div class="receipt-footer">' +
            '<p>' + escHtml(s.receipt_footer) + '</p>' +
            '<p style="margin-top:8px;">Thank you for your order!</p></div></div>';
        win.document.clear();
        win.document.write(
            '<html><head><title>Receipt - ' + b.token_number + '</title>' +
            '<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.6/dist/JsBarcode.all.min.js"><\/script>' +
            '<style>' +
            '@import url(' + "'https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap'" + ');' +
            '* { margin: 0; padding: 0; box-sizing: border-box; }' +
            'body { font-family: Inter, sans-serif; display: flex; justify-content: center; padding: 20px; background: #f5f5f5; }' +
            '@media print { body { background: white; padding: 0; } }' +
            '.receipt { background: white; padding: 32px; max-width: 320px; margin: 0 auto; font-size: 0.85rem; }' +
            '@media print { .receipt { width: 80mm; padding: 16px; } }' +
            '.receipt-header { text-align: center; border-bottom: 2px dashed #000; padding-bottom: 12px; margin-bottom: 12px; }' +
            '.receipt-header h2 { font-size: 1rem; font-weight: 800; color: #14532D; }' +
            '.receipt-header p { font-size: 0.75rem; color: #6B7280; margin: 2px 0; }' +
            '.receipt-body { margin-bottom: 12px; }' +
            '.receipt-row { display: flex; justify-content: space-between; padding: 3px 0; font-size: 0.8rem; }' +
            '.receipt-row.total { border-top: 2px solid #000; margin-top: 8px; padding-top: 8px; font-weight: 700; font-size: 0.9rem; }' +
            '.receipt-footer { text-align: center; border-top: 1px dashed #000; padding-top: 12px; font-size: 0.75rem; color: #6B7280; }' +
            '</style></head><body>' + receipt + '<script>JsBarcode("#barcode", "' + b.token_number + '", {format:"CODE128",width:1.5,height:40,displayValue:true,margin:0});window.onload=function(){window.print();}<\/script></body></html>'
        );
        win.document.close();
    } catch(e) { win.document.write('<p>Error loading receipt</p>'); win.document.close(); }
}
var currentUpcomingFilter = 'season';

function initUpcoming() {
    loadUpcoming(currentUpcomingFilter);
}

function filterUpcoming(filter) {
    currentUpcomingFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(function(b) { b.classList.remove('active'); });
    var btn = document.querySelector('.filter-btn[data-filter="' + filter + '"]');
    if (btn) btn.classList.add('active');
    loadUpcoming(filter);
}

function getSeasonBounds() {
    var now = new Date();
    var y = now.getMonth() < 3 ? now.getFullYear() - 1 : now.getFullYear();
    var start = y + '-04-01';
    var end = (y + 1) + '-03-31';
    return { start: start, end: end };
}

async function loadUpcoming(filter) {
    if (filter === undefined) filter = currentUpcomingFilter;
    var container = $('upcoming-list');
    var sortSelect = $('sort-upcoming');
    var sortBy = sortSelect ? sortSelect.value : 'function_date ASC';
    try {
        var params = '?order_by=' + encodeURIComponent(sortBy);
        var season = getSeasonBounds();
        if (filter === 'all') {
            params += '&start_date=' + season.start + '&end_date=' + season.end;
        } else if (filter === 'pending') {
            params += '&status=pending&start_date=' + todayStr() + '&end_date=' + season.end;
        } else if (filter === 'collected') {
            params += '&status=collected&start_date=' + season.start + '&end_date=' + season.end;
        } else if (filter === 'season') {
            params += '&start_date=' + season.start + '&end_date=' + season.end;
        }
        var bookings = await api('GET', '/bookings' + params);
        state.allUpcomingBookings = bookings;
        renderUpcoming(bookings);
    } catch(e) {
        container.innerHTML = '<div class="empty-state"><h3>Error loading bookings</h3><p>Please try again</p></div>';
    }
}

function renderUpcoming(bookings) {
    var container = $('upcoming-list');
    if (!bookings || bookings.length === 0) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">??</div><h3>No bookings found</h3><p>Bookings will appear here</p></div>';
        return;
    }
    container.innerHTML = bookings.map(function (b) {
        var isOverdue = b.status === 'pending' && b.function_date < todayStr();
        return '<div class="card' + (isOverdue ? ' card-overdue' : '') + '">' +
            '<div class="card-header"><span class="card-token">' + b.token_number + '</span>' + getStatusBadge(b.status) + '</div>' +
            '<div class="card-body">' +
            '<p><strong>Customer</strong> ' + escHtml(b.customer_name) + '</p>' +
            '<p><strong>Phone</strong> ' + escHtml(b.phone) + '</p>' +
            '<p><strong>Collection</strong> ' + formatDate(b.function_date) + (b.pickup_time ? ' at ' + b.pickup_time : '') + '</p>' +
            '<p><strong>Total</strong> <span class="card-highlight">' + formatCurrency(b.grand_total) + '</span></p>' +
            '<p><strong>Advance</strong> ' + formatCurrency(b.advance_paid) + '</p>' +
            '<p><strong>Balance</strong> <span style="color:' + (b.balance > 0 ? 'var(--danger)' : 'var(--success)') + '">' + formatCurrency(b.balance) + '</span></p>' +
            '<p><strong>Payment</strong> ' + getPaymentStatusBadge(b.balance) + '</p>' +
            '</div>' +
            '<div class="card-actions">' +
            (b.status === 'pending' ? '<button class="btn btn-success btn-sm" onclick="openCollectionModal(' + b.id + ')">Mark Collected</button>' : '') +
            '<button class="btn btn-primary btn-sm" onclick="viewBooking(' + b.id + ', \'upcoming-bookings\')">View Details</button>' +
            (b.status === 'collected' ? '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'collection\')">\uD83D\uDCAC WhatsApp</button>' :
             (b.advance_paid > 0 ? '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'payment\')">\uD83D\uDCAC WhatsApp</button>' :
              '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'booking\')">\uD83D\uDCAC WhatsApp</button>')) +
            '</div></div>';
    }).join('');
}
var currentCalendarDate = new Date();

function navigateCalendar(dir) {
    var m = currentCalendarDate.getMonth() + dir;
    var y = currentCalendarDate.getFullYear();
    if (m < 0) { m = 11; y--; }
    if (m > 11) { m = 0; y++; }
    currentCalendarDate = new Date(y, m, 1);
    renderCalendar();
}

function renderCalendar() {
    var grid = $('calendar-grid');
    var label = $('calendar-label');
    if (!grid || !label) return;
    var y = currentCalendarDate.getFullYear();
    var m = currentCalendarDate.getMonth();
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    label.textContent = months[m] + ' ' + y;
    var firstDay = new Date(y, m, 1).getDay();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var cells = '';
    cells += '<div class="cal-header">Sun</div><div class="cal-header">Mon</div><div class="cal-header">Tue</div><div class="cal-header">Wed</div><div class="cal-header">Thu</div><div class="cal-header">Fri</div><div class="cal-header">Sat</div>';
    for (var i = 0; i < firstDay; i++) { cells += '<div class="cal-day cal-day-empty"></div>'; }
    var bookingsByDate = {};
    (state.allUpcomingBookings || []).forEach(function(b) {
        if (b.function_date) {
            if (!bookingsByDate[b.function_date]) bookingsByDate[b.function_date] = [];
            bookingsByDate[b.function_date].push(b);
        }
    });
    for (var d = 1; d <= daysInMonth; d++) {
        var dateStr = y + '-' + String(m + 1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        var dayBookings = bookingsByDate[dateStr] || [];
        var hasPending = dayBookings.some(function(b) { return b.status === 'pending'; });
        var cls = 'cal-day';
        if (hasPending) cls += ' cal-day-pending';
        if (dateStr === todayStr()) cls += ' cal-day-today';
        cells += '<div class="' + cls + '" onclick="selectCalendarDate(\'' + dateStr + '\')">' +
            '<span class="cal-day-num">' + d + '</span>' +
            (dayBookings.length > 0 ? '<span class="cal-day-count">' + dayBookings.length + '</span>' : '') +
            '</div>';
    }
    grid.innerHTML = cells;
}

function toggleCalendar() {
    var cal = $('calendar-container');
    var list = $('upcoming-list');
    var toggleBtn = $('toggle-calendar-btn');
    if (cal.style.display === 'none') {
        cal.style.display = 'block';
        list.style.display = 'none';
        toggleBtn.textContent = 'List';
        renderCalendar();
    } else {
        cal.style.display = 'none';
        list.style.display = 'block';
        toggleBtn.textContent = 'Calendar';
        loadUpcoming(currentUpcomingFilter);
    }
}

function selectCalendarDate(dateStr) {
    var filtered = (state.allUpcomingBookings || []).filter(function(b) { return b.function_date === dateStr; });
    var list = $('upcoming-list');
    var cal = $('calendar-container');
    var toggleBtn = $('toggle-calendar-btn');
    cal.style.display = 'none';
    list.style.display = 'block';
    toggleBtn.textContent = 'Calendar';
    renderUpcoming(filtered);
}

async function loadPendingPayments() {
    var container = $('pending-list');
    try {
        var season = getSeasonBounds();
        var bookings = await api('GET', '/bookings?balance_due=true&start_date=' + season.start + '&end_date=' + season.end);
        if (bookings.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">?</div><h3>No pending payments</h3><p>All bookings are fully paid</p></div>';
            $('pending-count').textContent = '0';
            return;
        }
        $('pending-count').textContent = bookings.length;
        container.innerHTML = bookings.map(function(b) {
            var isOverdue = b.function_date < todayStr();
            return '<div class="card' + (isOverdue ? ' card-overdue' : '') + '">' +
                '<div class="card-header"><span class="card-token">' + b.token_number + '</span>' + getStatusBadge(b.status) + '</div>' +
                '<div class="card-body">' +
                '<p><strong>' + escHtml(b.customer_name) + '</strong> | ' + escHtml(b.phone) + '</p>' +
                '<p><strong>Collection</strong> ' + formatDate(b.function_date) + '</p>' +
                '<p><strong>Balance Amount</strong> <span style="color:var(--danger);font-size:1.2rem;font-weight:700;">' + formatCurrency(b.balance) + '</span></p>' +
                '<p><strong>Payment Status</strong> ' + getPaymentStatusBadge(b.balance) + '</p>' +
                '</div>' +
                '<div class="card-actions">' +
                '<button class="btn btn-primary btn-lg btn-block" onclick="openPaymentModal(' + b.id + ', \'' + escHtml(b.customer_name) + '\', \'' + b.token_number + '\', ' + b.balance + ')">Receive Payment</button>' +
                '<button class="btn btn-secondary btn-sm" onclick="viewBooking(' + b.id + ', \'pending-payments\')">View Details</button>' +
                '<button class="btn btn-success btn-sm" onclick="sendWhatsAppMsg(' + b.id + ', \'payment\')">\uD83D\uDCAC WhatsApp</button></div></div>';
        }).join('');
    } catch(e) {
        container.innerHTML = '<div class="empty-state"><h3>Error</h3><p>Please try again</p></div>';
    }
}
var currentReportPeriod = 'season';
var currentReportSort = 'token_number ASC';
var currentReportData = null;
var currentReportBookings = [];

function getReportDateRange(period) {
    var today = todayStr();
    if (period === 'daily') {
        return { start: today, end: today, label: 'Daily Report - ' + formatDate(today) };
    } else if (period === 'weekly') {
        var now = new Date();
        var day = now.getDay();
        var diffToMon = now.getDate() - day + (day === 0 ? -6 : 1);
        var mon = new Date(now.setDate(diffToMon));
        var sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);
        var start = mon.toISOString().slice(0, 10);
        var end = sun.toISOString().slice(0, 10);
        return { start: start, end: end, label: 'Weekly Report (' + formatDate(start) + ' to ' + formatDate(end) + ')' };
    } else if (period === 'monthly') {
        var now = new Date();
        var y = now.getFullYear();
        var m = now.getMonth();
        var start = y + '-' + String(m + 1).padStart(2, '0') + '-01';
        var lastDay = new Date(y, m + 1, 0).getDate();
        var end = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(lastDay).padStart(2, '0');
        var monthName = now.toLocaleString('en-IN', { month: 'long', year: 'numeric' });
        return { start: start, end: end, label: 'Monthly Report - ' + monthName };
    } else {
        var season = getSeasonBounds();
        return { start: season.start, end: season.end, label: 'Season Report (' + formatDate(season.start) + ' to ' + formatDate(season.end) + ')' };
    }
}

function initReports() {
    loadReport(currentReportPeriod || 'season', currentReportSort || 'token_number ASC');
}

async function loadReport(period, sort) {
    if (period !== undefined) currentReportPeriod = period;
    if (sort !== undefined) currentReportSort = sort;

    var btnMap = { season: 0, daily: 1, weekly: 2, monthly: 3 };
    var btns = document.querySelectorAll('#report-filters .filter-btn');
    if (btns && btns.length > 0) {
        btns.forEach(function(b) { b.classList.remove('active'); });
        if (btns[btnMap[currentReportPeriod]]) {
            btns[btnMap[currentReportPeriod]].classList.add('active');
        }
    }

    var range = getReportDateRange(currentReportPeriod);
    var container = $('report-content');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-secondary);">Loading ordered report data...</div>';

    try {
        var data = await api('GET', '/reports/custom?start_date=' + range.start + '&end_date=' + range.end);
        var bookings = await api('GET', '/bookings?start_date=' + range.start + '&end_date=' + range.end + '&order_by=' + encodeURIComponent(currentReportSort) + '&limit=5000');
        currentReportData = data;
        currentReportBookings = bookings;
        renderReportView(range.label, data, bookings);
    } catch(e) {
        container.innerHTML = '<div class="empty-state"><h3>Error loading report</h3><p>Please try again</p></div>';
    }
}

function renderReportView(title, data, bookings) {
    var container = $('report-content');
    if (!container) return;
    var sortOptions = [
        { val: 'token_number ASC', text: 'Token Number (SMM0001 First)' },
        { val: 'token_number DESC', text: 'Token Number (Latest First)' },
        { val: 'function_date ASC', text: 'Collection Date (Earliest)' },
        { val: 'function_date DESC', text: 'Collection Date (Latest)' },
        { val: 'customer_name ASC', text: 'Customer Name (A-Z)' },
        { val: 'customer_name DESC', text: 'Customer Name (Z-A)' },
    ];
    var sortSelectHtml = '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
        '<label style="font-size:0.85rem;color:var(--text-secondary);font-weight:600;">Order By:</label>' +
        '<select class="form-select" id="report-sort-select" onchange="onReportSortChange(this.value)" style="width:auto;padding:6px 12px;font-size:0.85rem;">' +
        sortOptions.map(function(opt) {
            return '<option value="' + opt.val + '"' + (opt.val === currentReportSort ? ' selected' : '') + '>' + opt.text + '</option>';
        }).join('') +
        '</select></div>';

    var html = '<div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">' +
        '<h3 style="color:var(--primary);font-size:1.1rem;margin:0;">' + escHtml(title) + '</h3>' +
        '<span style="font-size:0.85rem;color:var(--text-secondary);font-weight:600;">' + bookings.length + ' Orders Found</span>' +
        '</div>' +
        '<div class="report-metrics">' +
        '<div class="metric-card"><span class="metric-label">Total Bookings</span><span class="metric-value">' + data.total_bookings + '</span></div>' +
        '<div class="metric-card"><span class="metric-label">Total Revenue</span><span class="metric-value">' + formatCurrency(data.total_revenue) + '</span></div>' +
        '<div class="metric-card"><span class="metric-label">Total Advance</span><span class="metric-value">' + formatCurrency(data.total_advance) + '</span></div>' +
        '<div class="metric-card" style="border:2px solid #dc2626;background:#fef2f2;"><span class="metric-label" style="color:#dc2626;font-weight:700;">TOTAL BALANCE</span><span class="metric-value" style="color:#dc2626;font-weight:800;">' + formatCurrency(data.pending_balance) + '</span></div>' +
        '<div class="metric-card"><span class="metric-label">Mutton Total</span><span class="metric-value">' + data.total_mutton_qty.toFixed(2) + ' Padi</span></div>' +
        '<div class="metric-card"><span class="metric-label">Chicken Total</span><span class="metric-value">' + data.total_chicken_qty.toFixed(2) + ' Kg</span></div>' +
        '</div>' +
        '<div style="margin-top:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">' +
        sortSelectHtml +
        '<div style="display:flex;gap:8px;">' +
        '<button class="btn btn-primary" onclick="printReport()">Print PDF</button>' +
        '<button class="btn btn-accent" onclick="downloadCSV()">Download CSV</button>' +
        '</div></div>';

    if (!bookings || bookings.length === 0) {
        html += '<div class="empty-state" style="margin-top:16px;"><h3>No Bookings In This Period</h3><p>No bookings match the selected date range</p></div>';
    } else {
        html += '<div class="report-table-wrapper">' +
            '<table class="report-data-table">' +
            '<thead><tr>' +
            '<th>Token</th><th>Customer</th><th>Phone</th><th>Collection Date</th>' +
            '<th style="text-align:right;">Mutton</th><th style="text-align:right;">Chicken</th>' +
            '<th style="text-align:right;">Total</th><th style="text-align:right;">Advance</th>' +
            '<th style="text-align:right;">Balance</th><th>Status</th><th>Action</th>' +
            '</tr></thead>' +
            '<tbody>' +
            bookings.map(function(b) {
                return '<tr>' +
                    '<td style="font-weight:700;color:var(--primary);">' + b.token_number + '</td>' +
                    '<td>' + escHtml(b.customer_name) + '</td>' +
                    '<td>' + escHtml(b.phone) + '</td>' +
                    '<td>' + formatDate(b.function_date) + (b.pickup_time ? ' ' + b.pickup_time : '') + '</td>' +
                    '<td style="text-align:right;">' + b.mutton_qty + ' Padi</td>' +
                    '<td style="text-align:right;">' + b.chicken_qty + ' Kg</td>' +
                    '<td style="text-align:right;font-weight:600;">' + formatCurrency(b.grand_total) + '</td>' +
                    '<td style="text-align:right;">' + formatCurrency(b.advance_paid) + '</td>' +
                    '<td style="text-align:right;color:' + (b.balance > 0 ? 'var(--danger)' : 'var(--success)') + ';font-weight:700;">' + formatCurrency(b.balance) + '</td>' +
                    '<td>' + getStatusBadge(b.status) + '</td>' +
                    '<td><button class="btn btn-ghost btn-sm" onclick="viewBooking(' + b.id + ', \'reports\')">View</button></td>' +
                    '</tr>';
            }).join('') +
            '</tbody>' +
            '<tfoot><tr style="font-weight:700;">' +
            '<td colspan="4" style="text-align:right;">TOTAL (' + bookings.length + ' ORDERS):</td>' +
            '<td style="text-align:right;">' + data.total_mutton_qty.toFixed(2) + ' Padi</td>' +
            '<td style="text-align:right;">' + data.total_chicken_qty.toFixed(2) + ' Kg</td>' +
            '<td style="text-align:right;">' + formatCurrency(data.total_revenue) + '</td>' +
            '<td style="text-align:right;">' + formatCurrency(data.total_advance) + '</td>' +
            '<td style="text-align:right;color:#dc2626;font-size:0.95rem;">' + formatCurrency(data.pending_balance) + '</td>' +
            '<td colspan="2"></td>' +
            '</tr></tfoot>' +
            '</table></div>';
    }

    container.innerHTML = html;
}

function onReportSortChange(newSort) {
    currentReportSort = newSort;
    loadReport(currentReportPeriod, newSort);
}

function dailyReport() {
    loadReport('daily', currentReportSort);
}

function weeklyReport() {
    loadReport('weekly', currentReportSort);
}

function monthlyReport() {
    loadReport('monthly', currentReportSort);
}

async function printReport() {
    var range = getReportDateRange(currentReportPeriod);
    try {
        var data = currentReportData || await api('GET', '/reports/custom?start_date=' + range.start + '&end_date=' + range.end);
        var bookings = await api('GET', '/bookings?start_date=' + range.start + '&end_date=' + range.end + '&order_by=' + encodeURIComponent(currentReportSort) + '&limit=5000');
        var s = await api('GET', '/settings');
        var win = window.open('', '_blank');
        if (!win) { showToast('Please allow popups for printing.', 'error'); return; }
        var now = new Date();
        var dateStr = now.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) + ' ' + now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
        var html = '<div class="report-print">' +
            '<div class="rp-header">' +
            '<h1>' + escHtml(s.business_name) + '</h1>' +
            (s.address ? '<p>' + escHtml(s.address) + '</p>' : '') +
            (s.phone ? '<p>Phone: ' + escHtml(s.phone) + '</p>' : '') +
            '<h2>' + escHtml(range.label) + '</h2>' +
            '<p>Period: ' + formatDate(range.start) + ' to ' + formatDate(range.end) + '</p>' +
            '<p>Generated: ' + dateStr + '</p>' +
            '</div>' +
            '<div class="rp-summary">' +
            '<div class="rp-metric"><span class="rp-label">Total Bookings</span><span class="rp-value">' + data.total_bookings + '</span></div>' +
            '<div class="rp-metric"><span class="rp-label">Total Revenue</span><span class="rp-value">' + formatCurrency(data.total_revenue) + '</span></div>' +
            '<div class="rp-metric"><span class="rp-label">Advance Collected</span><span class="rp-value">' + formatCurrency(data.total_advance) + '</span></div>' +
            '<div class="rp-metric" style="border:2px solid #dc2626;background:#fef2f2;"><span class="rp-label" style="color:#dc2626;font-weight:700;">TOTAL BALANCE</span><span class="rp-value" style="color:#dc2626;">' + formatCurrency(data.pending_balance) + '</span></div>' +
            '<div class="rp-metric"><span class="rp-label">Mutton Biriyani</span><span class="rp-value">' + data.total_mutton_qty.toFixed(2) + ' Padi</span></div>' +
            '<div class="rp-metric"><span class="rp-label">Chicken 65</span><span class="rp-value">' + data.total_chicken_qty.toFixed(2) + ' Kg</span></div>' +
            '</div>' +
            '<table class="rp-table">' +
            '<thead><tr><th>Token</th><th>Customer</th><th>Phone</th><th>Collection Date</th><th>Mutton</th><th>Chicken</th><th>Total</th><th>Advance</th><th>Balance</th><th>Status</th></tr></thead>' +
            '<tbody>' +
            (bookings || []).map(function(b) {
                return '<tr><td>' + b.token_number + '</td><td>' + escHtml(b.customer_name) + '</td><td>' + escHtml(b.phone) + '</td><td>' + formatDate(b.function_date) + '</td>' +
                    '<td style="text-align:right;">' + b.mutton_qty + ' Padi</td><td style="text-align:right;">' + b.chicken_qty + ' Kg</td>' +
                    '<td style="text-align:right;">' + formatCurrency(b.grand_total) + '</td><td style="text-align:right;">' + formatCurrency(b.advance_paid) + '</td>' +
                    '<td style="text-align:right;font-weight:600;">' + formatCurrency(b.balance) + '</td><td>' + b.status + '</td></tr>';
            }).join('') +
            '</tbody>' +
            '<tfoot><tr style="font-weight:700;background:#f3f4f6;border-top:2px solid #333;">' +
            '<td colspan="4" style="text-align:right;font-weight:700;">TOTAL:</td>' +
            '<td style="text-align:right;font-weight:700;">' + data.total_mutton_qty.toFixed(2) + ' Padi</td>' +
            '<td style="text-align:right;font-weight:700;">' + data.total_chicken_qty.toFixed(2) + ' Kg</td>' +
            '<td style="text-align:right;font-weight:700;">' + formatCurrency(data.total_revenue) + '</td>' +
            '<td style="text-align:right;font-weight:700;">' + formatCurrency(data.total_advance) + '</td>' +
            '<td style="text-align:right;font-weight:700;color:#dc2626;">' + formatCurrency(data.pending_balance) + '</td>' +
            '<td></td></tr></tfoot>' +
            '</table></div>';
        win.document.write(
            '<html><head><title>Report - ' + s.business_name + '</title>' +
            '<style>' +
            '* { margin: 0; padding: 0; box-sizing: border-box; }' +
            'body { font-family: Arial, sans-serif; font-size: 12px; padding: 20px; }' +
            '.report-print { max-width: 1000px; margin: 0 auto; }' +
            '.rp-header { text-align: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #333; }' +
            '.rp-header h1 { font-size: 18px; margin-bottom: 4px; }' +
            '.rp-header h2 { font-size: 14px; margin: 8px 0 4px; color: #555; }' +
            '.rp-header p { font-size: 11px; color: #777; margin: 2px 0; }' +
            '.rp-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 20px; }' +
            '.rp-metric { border: 1px solid #ddd; padding: 8px 12px; text-align: center; border-radius: 4px; }' +
            '.rp-label { display: block; font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }' +
            '.rp-value { display: block; font-size: 16px; font-weight: 700; margin-top: 4px; }' +
            '.rp-table { width: 100%; border-collapse: collapse; }' +
            '.rp-table th { background: #f5f5f5; padding: 6px 8px; text-align: left; font-size: 10px; text-transform: uppercase; border: 1px solid #ddd; }' +
            '.rp-table td { padding: 5px 8px; border: 1px solid #ddd; font-size: 11px; }' +
            '.rp-table tr:nth-child(even) { background: #fafafa; }' +
            '@media print { body { padding: 10px; } .rp-header { border-bottom-color: #000; } }' +
            '</style></head><body>' + html + '<script>window.onload=function(){window.print();window.close();}<\/script></body></html>'
        );
        win.document.close();
    } catch(e) { showToast('Error generating report', 'error'); }
}

async function downloadCSV(type) {
    var range = getReportDateRange(currentReportPeriod);
    if (type === 'upcoming') {
        var sortSelect = $('sort-upcoming');
        var sortBy = sortSelect ? sortSelect.value : 'token_number ASC';
        var bookings = await api('GET', '/bookings?order_by=' + encodeURIComponent(sortBy) + '&limit=5000');
        csvDownloadFromBookings(bookings, 'Upcoming_Bookings_' + todayStr() + '.csv',
            ['Token','Customer','Phone','Booking Date','Collection Date','Mutton (Padi)','Chicken (Kg)','Total','Advance','Balance','Status','Payment Status']);
    } else if (type === 'pending') {
        var season = getSeasonBounds();
        var bookings = await api('GET', '/bookings?balance_due=true&start_date=' + season.start + '&end_date=' + season.end + '&order_by=token_number ASC&limit=5000');
        csvDownloadFromBookings(bookings, 'Pending_Payments_' + todayStr() + '.csv',
            ['Token','Customer','Phone','Total','Advance','Balance','Status']);
    } else {
        try {
            var bookings = await api('GET', '/bookings?start_date=' + range.start + '&end_date=' + range.end + '&order_by=' + encodeURIComponent(currentReportSort) + '&limit=5000');
            csvDownloadFromBookings(bookings, 'catering_report_' + range.start + '_to_' + range.end + '.csv',
                ['Token','Customer','Phone','Village','Collection Date','Collection Time','Mutton (Padi)','Chicken (Kg)','Total','Advance','Balance','Status','Notes']);
        } catch(e) { showToast('Error exporting CSV', 'error'); }
    }
}

function csvDownloadFromBookings(bookings, filename, headers) {
    var rows = [headers];
    var totalMutton = 0, totalChicken = 0, grandTotal = 0, totalAdvance = 0, totalBalance = 0;
    (bookings || []).forEach(function(b) {
        var mQty = parseFloat(b.mutton_qty) || 0;
        var cQty = parseFloat(b.chicken_qty) || 0;
        var total = parseFloat(b.grand_total) || 0;
        var adv = parseFloat(b.advance_paid) || 0;
        var bal = parseFloat(b.balance) || 0;
        totalMutton += mQty;
        totalChicken += cQty;
        grandTotal += total;
        totalAdvance += adv;
        totalBalance += bal;
        var map = {
            'Token': b.token_number, 'Customer': b.customer_name, 'Phone': b.phone,
            'Village': b.village || '', 'Booking Date': b.booking_date || '',
            'Collection Date': b.function_date || '', 'Collection Time': b.pickup_time || '',
            'Mutton (Padi)': mQty, 'Chicken (Kg)': cQty,
            'Total': total.toFixed(2), 'Advance': adv.toFixed(2), 'Balance': bal.toFixed(2),
            'Status': b.status, 'Payment Status': bal <= 0 ? 'Paid' : 'Pending Balance',
            'Notes': b.notes || ''
        };
        rows.push(headers.map(function(h) { return map[h] !== undefined ? map[h] : ''; }));
    });
    if (bookings && bookings.length > 0) {
        var totalRowMap = {
            'Token': 'TOTAL',
            'Customer': bookings.length + ' Bookings',
            'Phone': '',
            'Village': '',
            'Booking Date': '',
            'Collection Date': '',
            'Collection Time': '',
            'Mutton (Padi)': totalMutton.toFixed(2),
            'Chicken (Kg)': totalChicken.toFixed(2),
            'Total': grandTotal.toFixed(2),
            'Advance': totalAdvance.toFixed(2),
            'Balance': totalBalance.toFixed(2),
            'Status': '',
            'Payment Status': 'Total Balance: ' + totalBalance.toFixed(2),
            'Notes': ''
        };
        rows.push(headers.map(function(h) { return totalRowMap[h] !== undefined ? totalRowMap[h] : ''; }));
    }
    var csv = rows.map(function(r) { return r.map(function(c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(','); }).join('\n');
    var blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
}

async function loadSettings() {
    try {
        var s = await api('GET', '/settings');
        $('setting-business').value = s.business_name;
        $('setting-address').value = s.address || '';
        $('setting-phone').value = s.phone || '';
        $('setting-mutton').value = s.mutton_biriyani_price;
        $('setting-chicken').value = s.chicken_65_price;
        $('setting-collection-date').value = s.collection_date || '';
        $('setting-collection-time').value = s.collection_time || '';
        $('setting-footer').value = s.receipt_footer;
    } catch(e) {}
}

async function saveSettings(e) {
    e.preventDefault();
    var data = {
        business_name: $('setting-business').value.trim(),
        address: $('setting-address').value.trim(),
        phone: $('setting-phone').value.trim(),
        mutton_biriyani_price: parseFloat($('setting-mutton').value) || 0,
        chicken_65_price: parseFloat($('setting-chicken').value) || 0,
        collection_date: $('setting-collection-date').value,
        collection_time: $('setting-collection-time').value,
        receipt_footer: $('setting-footer').value.trim(),
    };
    if (!data.business_name) { showToast('Business name is required.', 'error'); return; }
    if (data.mutton_biriyani_price === 0 && data.chicken_65_price === 0) {
        showToast('Set at least one item price.', 'error');
        return;
    }
    try {
        var res = await api('PUT', '/settings', data);
        state.settings = data;
        showToast('Settings saved successfully!');
    } catch(e) {}
}

// ─── Scan Collection ────────────────────────────────────────────

function playBeep(success) {
    try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = success ? 1200 : 300;
        osc.type = 'sine';
        gain.gain.value = 0.3;
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + (success ? 0.15 : 0.4));
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + (success ? 0.15 : 0.4));
    } catch(e) {}
}

function showScanWaiting() {
    $('scan-result').style.display = 'none';
    $('scan-result').innerHTML = '';
    $('scan-waiting').style.display = 'block';
    $('scan-input').value = '';
    setTimeout(function() { $('scan-input').focus(); }, 100);
}

function initScanCollection() {
    showScanWaiting();
    $('scan-input').onkeydown = function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            var token = $('scan-input').value.trim();
            if (!token) return;
            processScan(token);
        }
    };
}

document.addEventListener('keydown', function(e) {
    var scanPage = $('page-scan-collection');
    if (!scanPage || !scanPage.classList.contains('active')) return;
    if (e.key === 'Escape') {
        showPage('dashboard');
        e.preventDefault();
    }
    if (e.key === 'F2') {
        $('scan-input').focus();
        e.preventDefault();
    }
});

async function processScan(token) {
    try {
        var b = await api('GET', '/bookings/by-token/' + encodeURIComponent(token));
        if (!b || !b.id) throw new Error('Not found');
        playBeep(true);
        showToast('\u2705 Booking Found', 'success');
        showScanPreview(b);
    } catch(e) {
        playBeep(false);
        showToast('\u274C Invalid Token', 'error');
        showScanWaiting();
    }
}

function showScanPreview(b) {
    $('scan-waiting').style.display = 'none';
    var statusColor = b.status === 'collected' ? 'var(--success)' : 'var(--accent)';
    var paymentLabel = b.balance <= 0 ? '<span class="status-badge paid">&#10003; Paid</span>' : '<span class="status-badge pending-balance">&#128992; Pending</span>';
    var isCollected = b.status === 'collected';

    var html = '<div class="scan-preview">' +
        '<div class="scan-preview-header">' +
        '<span class="card-token">' + b.token_number + '</span>' +
        '<span class="status-badge ' + b.status + '">' + b.status.charAt(0).toUpperCase() + b.status.slice(1) + '</span>' +
        '</div>' +
        '<div class="detail-grid" style="margin-bottom:16px;">' +
        '<div class="detail-item"><span class="detail-label">Customer Name</span><span class="detail-value">' + escHtml(b.customer_name) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Phone Number</span><span class="detail-value">' + escHtml(b.phone) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Booking Date</span><span class="detail-value">' + formatDate(b.booking_date) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Function Date</span><span class="detail-value">' + formatDate(b.function_date) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Mutton Biriyani (Padi)</span><span class="detail-value">' + (b.mutton_qty || '0') + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Chicken 65 (Kg)</span><span class="detail-value">' + (b.chicken_qty || '0') + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Total Amount</span><span class="detail-value amount">' + formatCurrency(b.grand_total) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Advance Paid</span><span class="detail-value" style="color:var(--success);">' + formatCurrency(b.advance_paid) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Remaining Balance</span><span class="detail-value" style="color:var(--danger);font-weight:700;">' + formatCurrency(b.balance) + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Collection Status</span><span class="detail-value" style="color:' + statusColor + ';font-weight:700;">' + (b.status === 'collected' ? 'Collected' : 'Pending') + '</span></div>' +
        '<div class="detail-item"><span class="detail-label">Payment Status</span><span class="detail-value">' + paymentLabel + '</span></div>' +
        '</div>';

    if (isCollected) {
        html += '<div class="scan-already" role="alert">' +
            '<div class="scan-alert-icon">&#x26A0;</div>' +
            '<div><strong>Already Collected</strong>' +
            '<p style="font-size:0.85rem;color:var(--text-secondary);margin-top:4px;">This booking was collected on ' + formatDate(b.function_date) + '</p></div>' +
            '</div>' +
            '<div class="btn-group" style="margin-top:16px;">' +
            '<button class="btn btn-secondary btn-lg btn-block" onclick="showScanWaiting()">Scan Next</button>' +
            '</div>';
    } else if (b.balance > 0) {
        html += '<div class="scan-balance-due">' +
            '<p style="font-weight:700;margin-bottom:8px;">Remaining Balance: <span style="color:var(--danger);font-size:1.3rem;">' + formatCurrency(b.balance) + '</span></p>' +
            '<div class="form-group">' +
            '<label class="form-label" for="scan-received">Amount Received Today (?)</label>' +
            '<input type="number" class="form-input form-input-lg" id="scan-received" min="0.01" step="0.01" placeholder="Enter amount received..." autocomplete="off">' +
            '</div>' +
            '<div class="btn-group">' +
            '<button class="btn btn-success btn-lg btn-block" onclick="confirmScanCollection(' + b.id + ')">Confirm Collection</button>' +
            '<button class="btn btn-secondary btn-lg btn-block" onclick="showScanWaiting()">Skip</button>' +
            '</div>' +
            '</div>';
    } else {
        html += '<div class="scan-balance-due" style="text-align:center;">' +
            '<p style="font-size:1.1rem;color:var(--success);font-weight:700;margin-bottom:16px;">No Pending Balance</p>' +
            '<div class="btn-group">' +
            '<button class="btn btn-success btn-lg btn-block" onclick="confirmScanCollection(' + b.id + ')">Mark as Collected</button>' +
            '<button class="btn btn-secondary btn-lg btn-block" onclick="showScanWaiting()">Scan Next</button>' +
            '</div>' +
            '</div>';
    }

    html += '</div>';
    $('scan-result').innerHTML = html;
    $('scan-result').style.display = 'block';
    if (b.balance > 0) {
        setTimeout(function() { var inp = $('scan-received'); if (inp) inp.focus(); }, 100);
    }
}

async function confirmScanCollection(id) {
    var inp = $('scan-received');
    var amount = inp ? (parseFloat(inp.value) || 0) : 0;
    try {
        var b = await api('POST', '/bookings/' + id + '/collect', { amount_received: amount });
        closeModal('collection-modal');
        showSuccessPopup({
            title: 'Order Collected Successfully',
            buttons: [
                { label: 'Send WhatsApp', cls: 'btn-success', action: function() { sendWhatsAppFromPopup(b, 'collection'); } },
                { label: 'Scan Next Customer', cls: 'btn-accent', action: function() { closeModal('success-modal'); showScanWaiting(); } },
                { label: 'Home', cls: 'btn-secondary', action: function() { closeModal('success-modal'); showPage('dashboard'); } }
            ]
        });
    } catch(e) {}
}

// ─── End Scan Collection ────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function() {
    try {
        var s = await api('GET', '/settings');
        if (s && s.business_name) {
            $('app-title').textContent = s.business_name;
        }
        state.settings = s;
    } catch(e) {}
    showPage('dashboard');
});
