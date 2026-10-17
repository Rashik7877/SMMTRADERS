let state = {
    currentBookingId: null,
    currentPaymentBookingId: null,
    calendarDate: new Date(),
    settings: null,
    allUpcomingBookings: [],
    allScanBookings: [],
    bookingFromPage: 'search-booking',
    savingBooking: false,
    savingEdit: false,
    savingPayment: false,
    savingSettings: false,
    collectingBooking: false,
    scanSubmitting: false,
    lastScanToken: null,
    scanPreviewBooking: null,
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
function formatApiError(detail) {
    if (!detail) return 'Request failed';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail.map(function (d) {
            var loc = (d.loc || []).filter(function (p) { return p !== 'body'; }).join('.');
            return (d.msg || 'Invalid value') + (loc ? ' (' + loc + ')' : '');
        }).join(' ');
    }
    return String(detail);
}
var _csrfToken = null;

// Lightweight client-side timing. Every API call carries a correlation id and
// its Server-Timing breakdown is kept in a bounded in-memory log. Only the
// request path is stored - never the query string, which can carry a customer
// name, phone number or search term. Inspect with window.smmPerf.summary().
window.__perfLog = window.__perfLog || [];
function _newRequestId() {
    try {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    } catch (e) {}
    return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}
function _parseServerTiming(value) {
    var out = {};
    (value || '').split(',').forEach(function (part) {
        var bits = part.split(';');
        var name = (bits.shift() || '').trim();
        if (!name) return;
        bits.forEach(function (bit) {
            var kv = bit.split('=');
            var key = (kv[0] || '').trim();
            if (key === 'dur') out[name] = parseFloat(kv[1]);
            if (key === 'desc') out[name] = (kv[1] || '').replace(/"/g, '');
        });
    });
    return out;
}
function _recordPerf(entry) {
    var log = window.__perfLog;
    log.push(entry);
    if (log.length > 200) log.splice(0, log.length - 200);
}
window.smmPerf = {
    log: window.__perfLog,
    summary: function () { return window.__perfLog.slice(); },
    clear: function () { window.__perfLog.length = 0; }
};

async function api(method, url, body) {
    var requestId = _newRequestId();
    var opts = {
        method: method,
        headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId }
    };
    if (method !== 'GET' && _csrfToken) opts.headers['X-CSRF-Token'] = _csrfToken;
    if (body && method !== 'GET') opts.body = JSON.stringify(body);
    var fetchUrl = '/api' + url;
    if (method === 'GET') fetchUrl += (url.includes('?') ? '&' : '?') + '_t=' + Date.now();
    var started = (window.performance && performance.now) ? performance.now() : Date.now();
    try {
        var res = await fetch(fetchUrl, opts);
        if (res.status === 401) {
            window.location.href = '/login';
            throw new Error('Session expired');
        }
        if (!res.ok) {
            var err = await res.json().catch(function() { return { detail: 'Request failed' }; });
            throw new Error(formatApiError(err.detail));
        }
        var payload = await res.json();
        var finished = (window.performance && performance.now) ? performance.now() : Date.now();
        _recordPerf({
            rid: requestId,
            method: method,
            path: ('/api' + url).split('?')[0],
            status: res.status,
            clientMs: Math.round((finished - started) * 10) / 10,
            server: _parseServerTiming(res.headers.get('Server-Timing'))
        });
        return payload;
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}
async function logout() {
    try { await api('POST', '/auth/logout'); } catch (e) {}
    _csrfToken = null;
    window.location.href = '/login';
}
function escHtml(s) {
    var div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
}
function escJs(s) {
    return String(s == null ? '' : s)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\r?\n/g, ' ');
}
function setFieldError(id, msg) {
    var el = $(id);
    if (!el) return;
    el.textContent = msg || '';
    el.style.display = msg ? 'block' : 'none';
}
function clearFieldError(id) { setFieldError(id, ''); }
// Keep phone inputs to digits only, capped at 10, so a 10-digit number is all
// that can ever be typed or pasted.
function sanitizePhoneInput(el) {
    if (!el) return;
    var digits = String(el.value || '').replace(/\D/g, '');
    if (digits.length > 10) {
        if (digits.length === 12 && digits.slice(0, 2) === '91') digits = digits.slice(2);
        else if (digits.length === 11 && digits.charAt(0) === '0') digits = digits.slice(1);
    }
    if (digits.length > 10) digits = digits.slice(-10);
    if (el.value !== digits) {
        var atEnd = el.selectionStart === null || el.selectionStart >= el.value.length;
        el.value = digits;
        if (atEnd) {
            try { el.setSelectionRange(digits.length, digits.length); } catch(e) {}
        }
    }
}
function validatePhone(raw) {
    var text = String(raw == null ? '' : raw).trim();
    if (!text) return { ok: false, message: 'Phone number is required.' };
    var cleaned = text.replace(/\D/g, '');
    if (/[A-Za-z]/.test(text)) {
        return { ok: false, message: 'Phone number cannot contain letters.' };
    }
    if (cleaned.length === 12 && cleaned.slice(0, 2) === '91') cleaned = cleaned.slice(2);
    else if (cleaned.length === 11 && cleaned.charAt(0) === '0') cleaned = cleaned.slice(1);
    if (/^[6-9]\d{9}$/.test(cleaned)) return { ok: true, value: cleaned };
    return {
        ok: false,
        message: 'Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9 (e.g. 9876543210).'
    };
}
function genRequestId() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'req-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}
function computedFinancialYear() {
    var now = new Date();
    var y = now.getMonth() < 3 ? now.getFullYear() - 1 : now.getFullYear();
    return { start: y + '-04-01', end: (y + 1) + '-03-31' };
}
function getFinancialPeriod() {
    var s = state.settings || {};
    var start = s.financial_start_date || '';
    var end = s.financial_end_date || '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(start) && /^\d{4}-\d{2}-\d{2}$/.test(end) && end >= start) {
        return { start: start, end: end, configured: true };
    }
    var fallback = computedFinancialYear();
    fallback.configured = false;
    return fallback;
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
    // The scan terminal needs the full desktop width; the rest of the app keeps
    // its normal, narrower reading width.
    $('app').classList.toggle('wide', page === 'scan-collection');
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
        var fixedDate = (s.collection_date || '').trim();
        $('function-date').value = fixedDate ? formatDate(fixedDate) : '';
        var fixedTime = (s.collection_time || '').trim();
        $('pickup-time').value = fixedTime ? fmtTime(fixedTime) : '';
        var hint = $('collection-default-hint');
        if (hint) {
            hint.textContent = fixedDate
                ? 'Fixed by Settings - change it there, not here.'
                : 'Not set. Choose the collection date in Settings first.';
        }
        calcTotals();
        return fixedDate;
    } catch(e) {
        return '';
    }
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
    if (state.savingBooking) return false;
    var s = state.settings;
    if (!s || (s.mutton_biriyani_price === 0 && s.chicken_65_price === 0)) {
        showToast('Please set item prices in Settings first.', 'error');
        return false;
    }
    var phoneCheck = validatePhone($('customer-phone').value);
    if (!phoneCheck.ok) {
        setFieldError('phone-error', phoneCheck.message);
        showToast(phoneCheck.message, 'error');
        $('customer-phone').focus();
        return false;
    }
    clearFieldError('phone-error');
    var fixedDate = ((state.settings && state.settings.collection_date) || '').trim();
    if (!fixedDate) {
        showToast('Set the collection date in Settings before creating a booking.', 'error');
        return false;
    }
    var fixedTime = ((state.settings && state.settings.collection_time) || '').trim();
    var data = {
        customer_name: $('customer-name').value.trim(),
        phone: phoneCheck.value,
        village: $('customer-village').value.trim(),
        function_date: fixedDate,
        pickup_time: fixedTime,
        mutton_qty: parseFloat($('mutton-qty').value) || 0,
        chicken_qty: parseFloat($('chicken-qty').value) || 0,
        advance_paid: parseFloat($('advance-paid').value) || 0,
        notes: $('booking-notes').value.trim(),
    };
    if (!data.customer_name) { showToast('Please enter customer name.', 'error'); return false; }
    if (data.mutton_qty === 0 && data.chicken_qty === 0) {
        showToast('Please order at least one item.', 'error');
        return false;
    }
    if (!isValidQuantityStep(data.mutton_qty)) {
        showToast('Mutton Biriyani quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('mutton-qty').focus();
        return false;
    }
    if (!isValidQuantityStep(data.chicken_qty)) {
        showToast('Chicken 65 quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('chicken-qty').focus();
        return false;
    }
    state.savingBooking = true;
    var submitBtn = document.querySelector('#booking-form button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
        var booking = await api('POST', '/bookings', data);
        $('customer-phone').value = phoneCheck.value;
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
    } catch(e) {
    } finally {
        state.savingBooking = false;
        if (submitBtn) submitBtn.disabled = false;
    }
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
        '<button class="btn btn-accent btn-lg" onclick="openPaymentModal(' + b.id + ', \'' + escJs(b.customer_name) + '\', \'' + b.token_number + '\', ' + b.balance + ')">Update Payment</button>' +
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
    else if (target === 'scan-collection') initScanCollection();
    else if (target === 'reports') loadReport(currentReportPeriod, currentReportSort);
}

async function confirmCollection() {
    if (state.collectingBooking) return;
    var id = state.currentBookingId;
    var amountReceived = parseFloat($('col-amount').value) || 0;
    state.collectingBooking = true;
    var btn = document.querySelector('#collection-modal .btn-success');
    if (btn) btn.disabled = true;
    try {
        var b = await api('POST', '/bookings/' + id + '/collect', {
            amount_received: amountReceived,
            request_id: genRequestId()
        });
        closeModal('collection-modal');
        showToast('Booking marked as collected!');
        var currentPage = document.querySelector('.page-section.active');
        if (currentPage && currentPage.id === 'page-scan-collection') {
            loadScanTable();
            refreshScanPreview(id);
        } else if (currentPage && currentPage.id === 'page-booking-details') {
            viewBooking(id, state.bookingFromPage);
        } else if (currentPage && currentPage.id === 'page-pending-payments') {
            loadPendingPayments();
        } else {
            loadUpcoming(currentUpcomingFilter);
        }
    } catch(e) {
    } finally {
        state.collectingBooking = false;
        if (btn) btn.disabled = false;
    }
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
    if (state.savingPayment) return;
    var id = state.currentPaymentBookingId;
    var amount = parseFloat($('pmt-amount').value);
    var notes = $('pmt-notes').value.trim();
    if (!amount || amount <= 0) { showToast('Please enter a valid amount.', 'error'); return; }
    state.savingPayment = true;
    var btn = document.querySelector('#payment-modal .btn-success');
    if (btn) btn.disabled = true;
    try {
        var b = await api('POST', '/bookings/' + id + '/payment', {
            amount: amount,
            notes: notes,
            request_id: genRequestId()
        });
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
                    } else if (currentPage && currentPage.id === 'page-scan-collection') {
                        loadScanTable();
                        refreshScanPreview(id);
                    } else {
                        loadUpcoming(currentUpcomingFilter);
                    }
                } }
            ]
        });
    } catch(e) {
    } finally {
        state.savingPayment = false;
        if (btn) btn.disabled = false;
    }
}

async function openEditModal(id) {
    try {
        var b = await api('GET', '/bookings/' + id);
        $('edit-name').value = b.customer_name;
        $('edit-phone').value = b.phone;
        $('edit-village').value = b.village || '';
        state.editFuncDate = b.function_date;
        $('edit-func-date').value = formatDate(b.function_date);
        $('edit-pickup').value = b.pickup_time ? fmtTime(b.pickup_time) : '';
        $('edit-mutton').value = b.mutton_qty;
        $('edit-chicken').value = b.chicken_qty;
        $('edit-notes').value = b.notes || '';
        showModal('edit-modal');
        state.currentBookingId = id;
    } catch(e) {}
}

async function submitEdit(e) {
    e.preventDefault();
    if (state.savingEdit) return false;
    var id = state.currentBookingId;
    var phoneCheck = validatePhone($('edit-phone').value);
    if (!phoneCheck.ok) {
        setFieldError('edit-phone-error', phoneCheck.message);
        showToast(phoneCheck.message, 'error');
        $('edit-phone').focus();
        return false;
    }
    clearFieldError('edit-phone-error');
    var data = {
        customer_name: $('edit-name').value.trim(),
        phone: phoneCheck.value,
        village: $('edit-village').value.trim(),
        mutton_qty: parseFloat($('edit-mutton').value) || 0,
        chicken_qty: parseFloat($('edit-chicken').value) || 0,
        notes: $('edit-notes').value.trim(),
    };
    if (!data.customer_name) {
        showToast('Please fill in required fields.', 'error');
        return false;
    }
    if (!isValidQuantityStep(data.mutton_qty)) {
        showToast('Mutton Biriyani quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('edit-mutton').focus();
        return false;
    }
    if (!isValidQuantityStep(data.chicken_qty)) {
        showToast('Chicken 65 quantity must be in steps of 0.25 (e.g. 0.25, 0.50, 0.75, 1.00, 1.25).', 'error');
        $('edit-chicken').focus();
        return false;
    }
    state.savingEdit = true;
    try {
        await api('PUT', '/bookings/' + id, data);
        closeModal('edit-modal');
        showToast('Booking updated successfully!');
        viewBooking(id, state.bookingFromPage);
    } catch(e) {
    } finally {
        state.savingEdit = false;
    }
    return false;
}

async function printReceipt(id) {
    var win = window.open('', '_blank');
    if (!win) { showToast('Please allow popups for this site to print receipts.', 'error'); return; }
    win.document.write('<html><head><title>Loading...</title></head><body><p style="font-family:sans-serif;padding:40px;text-align:center;">Loading receipt...</p></body></html>');
    win.document.close();
    try {
        var results = await Promise.all([
            api('GET', '/bookings/' + id),
            api('GET', '/settings')
        ]);
        var b = results[0];
        var s = results[1];
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
            ((s.receipt_footer || '').trim()
                ? '<div class="receipt-footer"><p>' + escHtml(s.receipt_footer.trim()) + '</p></div>'
                : '') +
            '</div>';
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

var upcomingSearchTimeout = null;

function filterUpcoming(filter) {
    if (filter === undefined || filter === null || filter === '') {
        filter = currentUpcomingFilter;
    }
    currentUpcomingFilter = filter;
    document.querySelectorAll('#upcoming-filters .filter-btn').forEach(function(b) { b.classList.remove('active'); });
    var btn = document.querySelector('#upcoming-filters .filter-btn[data-filter="' + filter + '"]');
    if (btn) btn.classList.add('active');
    loadUpcoming(filter);
}

function onUpcomingSearch() {
    clearTimeout(upcomingSearchTimeout);
    upcomingSearchTimeout = setTimeout(function () {
        loadUpcoming(currentUpcomingFilter);
    }, 250);
}

function getSeasonBounds() {
    // The financial/reporting period is configurable in Settings. When it is
    // not configured we fall back to the Indian financial year (Apr-Mar).
    return getFinancialPeriod();
}

async function loadUpcoming(filter) {
    if (filter === undefined) filter = currentUpcomingFilter;
    var container = $('upcoming-list');
    var sortSelect = $('sort-upcoming');
    var sortBy = sortSelect ? sortSelect.value : 'function_date ASC';
    var searchInput = $('upcoming-search');
    var query = searchInput ? searchInput.value.trim() : '';
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
        if (query) params += '&search=' + encodeURIComponent(query);
        var bookings = await api('GET', '/bookings' + params);
        state.allUpcomingBookings = bookings;
        renderUpcoming(bookings, query);
    } catch(e) {
        container.innerHTML = '<div class="empty-state"><h3>Error loading bookings</h3><p>Please try again</p></div>';
    }
}

function renderUpcoming(bookings, query) {
    var container = $('upcoming-list');
    if (!bookings || bookings.length === 0) {
        var emptyMsg = query
            ? 'No bookings match "' + escHtml(query) + '". Try a different name, phone or token.'
            : 'Bookings will appear here';
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">??</div><h3>No bookings found</h3><p>' + emptyMsg + '</p></div>';
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

var pendingSearchTimeout = null;

function onPendingSearch() {
    clearTimeout(pendingSearchTimeout);
    pendingSearchTimeout = setTimeout(function () {
        loadPendingPayments();
    }, 250);
}

async function loadPendingPayments() {
    var container = $('pending-list');
    var searchInput = $('pending-search');
    var query = searchInput ? searchInput.value.trim() : '';
    try {
        var season = getSeasonBounds();
        var url = '/bookings?balance_due=true&start_date=' + season.start + '&end_date=' + season.end
            + '&order_by=' + encodeURIComponent('token_number ASC');
        if (query) url += '&search=' + encodeURIComponent(query);
        var bookings = await api('GET', url);
        if (bookings.length === 0) {
            var msg = query
                ? 'No pending payments match "' + escHtml(query) + '". Clear the search to see all pending payments.'
                : 'All bookings are fully paid';
            var title = query ? 'No matching pending payments' : 'No pending payments';
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">?</div><h3>' + title + '</h3><p>' + msg + '</p></div>';
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
                '<button class="btn btn-primary btn-lg btn-block" onclick="openPaymentModal(' + b.id + ', \'' + escJs(b.customer_name) + '\', \'' + b.token_number + '\', ' + b.balance + ')">Receive Payment</button>' +
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
        var start = mon.getFullYear() + '-' + String(mon.getMonth() + 1).padStart(2, '0') + '-' + String(mon.getDate()).padStart(2, '0');
        var end = sun.getFullYear() + '-' + String(sun.getMonth() + 1).padStart(2, '0') + '-' + String(sun.getDate()).padStart(2, '0');
        return { start: start, end: end, label: 'Weekly Report (' + formatDate(start) + ' to ' + formatDate(end) + ')' };
    } else if (period === 'monthly') {
        var now2 = new Date();
        var y = now2.getFullYear();
        var m = now2.getMonth();
        var start2 = y + '-' + String(m + 1).padStart(2, '0') + '-01';
        var lastDay = new Date(y, m + 1, 0).getDate();
        var end2 = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(lastDay).padStart(2, '0');
        var monthName = now2.toLocaleString('en-IN', { month: 'long', year: 'numeric' });
        return { start: start2, end: end2, label: 'Monthly Report - ' + monthName };
    } else if (period === 'custom') {
        var startInput = $('custom-start');
        var endInput = $('custom-end');
        var cs = startInput ? startInput.value : '';
        var ce = endInput ? endInput.value : '';
        if (!cs || !ce) {
            var fp = getFinancialPeriod();
            cs = cs || fp.start;
            ce = ce || fp.end;
        }
        return {
            start: cs, end: ce, custom: true,
            label: 'Custom Report (User selected range: ' + formatDate(cs) + ' to ' + formatDate(ce) + ')'
        };
    } else {
        var period2 = getFinancialPeriod();
        var suffix = period2.configured ? '' : ' - default Apr-Mar';
        return {
            start: period2.start, end: period2.end,
            label: 'Financial Year Report (' + formatDate(period2.start) + ' to ' + formatDate(period2.end) + ')' + suffix
        };
    }
}

function onReportPeriodChange(period) {
    var row = $('custom-range-row');
    if (!row) return;
    if (period === 'custom') {
        var fp = getFinancialPeriod();
        var startInput = $('custom-start');
        var endInput = $('custom-end');
        if (startInput && !startInput.value) startInput.value = fp.start;
        if (endInput && !endInput.value) endInput.value = fp.end;
        row.style.display = 'flex';
    } else {
        row.style.display = 'none';
    }
}

function applyCustomRange() {
    var cs = $('custom-start').value;
    var ce = $('custom-end').value;
    if (!cs || !ce) { showToast('Select both a start and end date.', 'error'); return; }
    if (ce < cs) { showToast('End date cannot be earlier than the start date.', 'error'); return; }
    loadReport('custom', currentReportSort);
}

function initReports() {
    loadReport(currentReportPeriod || 'season', currentReportSort || 'token_number ASC');
}

async function loadReport(period, sort) {
    if (period !== undefined) currentReportPeriod = period;
    if (sort !== undefined) currentReportSort = sort;

    var btnMap = { season: 0, daily: 1, weekly: 2, monthly: 3, custom: 4 };
    var btns = document.querySelectorAll('#report-filters .filter-btn');
    if (btns && btns.length > 0) {
        btns.forEach(function(b) { b.classList.remove('active'); });
        if (btns[btnMap[currentReportPeriod]]) {
            btns[btnMap[currentReportPeriod]].classList.add('active');
        }
    }
    onReportPeriodChange(currentReportPeriod);

    var range = getReportDateRange(currentReportPeriod);
    var container = $('report-content');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-secondary);">Loading ordered report data...</div>';

    try {
        var results = await Promise.all([
            api('GET', '/reports/custom?start_date=' + range.start + '&end_date=' + range.end),
            api('GET', '/bookings?start_date=' + range.start + '&end_date=' + range.end + '&order_by=' + encodeURIComponent(currentReportSort) + '&limit=5000')
        ]);
        var data = results[0];
        var bookings = results[1];
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

    var rng = getReportDateRange(currentReportPeriod);
    var html = '<div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">' +
        '<h3 style="color:var(--primary);font-size:1.1rem;margin:0;">' + escHtml(title) + '</h3>' +
        '<span style="font-size:0.85rem;color:var(--text-secondary);font-weight:600;">' + bookings.length + ' Orders Found</span>' +
        '</div>' +
        '<div class="report-period-note">Reporting period: <strong>' + formatDate(rng.start) + ' to ' + formatDate(rng.end) + '</strong>' +
        (currentReportPeriod === 'custom' ? ' &middot; <span class="badge-custom">User selected custom range</span>' : ' &middot; <span class="badge-configured">Configured financial period</span>') +
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
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
        '<button class="btn btn-primary" onclick="downloadPDF()">Download PDF (A4)</button>' +
        '<button class="btn btn-secondary" onclick="printReport()">Print</button>' +
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

function downloadPDF() {
    var range = getReportDateRange(currentReportPeriod);
    if (!range.start || !range.end) { showToast('Select a valid reporting period first.', 'error'); return; }
    if (range.end < range.start) { showToast('End date cannot be earlier than the start date.', 'error'); return; }
    var url = '/api/reports/pdf?start_date=' + encodeURIComponent(range.start)
        + '&end_date=' + encodeURIComponent(range.end)
        + '&order_by=' + encodeURIComponent(currentReportSort)
        + '&label=' + encodeURIComponent(range.label);
    window.open(url, '_blank');
}

async function printReport() {
    var range = getReportDateRange(currentReportPeriod);
    try {
        var results = await Promise.all([
            currentReportData ? Promise.resolve(currentReportData) : api('GET', '/reports/custom?start_date=' + range.start + '&end_date=' + range.end),
            api('GET', '/bookings?start_date=' + range.start + '&end_date=' + range.end + '&order_by=' + encodeURIComponent(currentReportSort) + '&limit=5000'),
            api('GET', '/settings')
        ]);
        var data = results[0];
        var bookings = results[1];
        var s = results[2];
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
            '</table>' +
            ((s.receipt_footer || '').trim() ? '<div class="rp-footer">' + escHtml(s.receipt_footer.trim()) + '</div>' : '') +
            '</div>';
        win.document.write(
            '<html><head><title>Report - ' + s.business_name + '</title>' +
            '<style>' +
            '* { margin: 0; padding: 0; box-sizing: border-box; }' +
            '@page { size: A4 portrait; margin: 10mm; }' +
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
            '.rp-table { width: 100%; border-collapse: collapse; table-layout: fixed; }' +
            '.rp-table th { background: #f5f5f5; padding: 6px 8px; text-align: left; font-size: 10px; text-transform: uppercase; border: 1px solid #ddd; }' +
            '.rp-table td { padding: 5px 8px; border: 1px solid #ddd; font-size: 11px; word-wrap: break-word; overflow-wrap: anywhere; }' +
            '.rp-table tr:nth-child(even) { background: #fafafa; }' +
            '.rp-footer { margin-top: 16px; padding-top: 10px; border-top: 1px dashed #999; text-align: center; font-size: 11px; color: #555; }' +
            '@media print { body { padding: 0; } .rp-header { border-bottom-color: #000; } thead { display: table-header-group; } tr { break-inside: avoid; } .report-print { max-width: none; } }' +
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
        state.settings = s;
        $('setting-business').value = s.business_name;
        $('setting-address').value = s.address || '';
        $('setting-phone').value = s.phone || '';
        $('setting-mutton').value = s.mutton_biriyani_price;
        $('setting-chicken').value = s.chicken_65_price;
        $('setting-collection-date').value = s.collection_date || '';
        $('setting-collection-time').value = s.collection_time || '';
        $('setting-fin-start').value = s.financial_start_date || '';
        $('setting-fin-end').value = s.financial_end_date || '';
        $('setting-footer').value = s.receipt_footer || '';
        updateFinancialPeriodSummary();
    } catch(e) {}
}

function updateFinancialPeriodSummary() {
    var el = $('financial-period-summary');
    if (!el) return;
    var fp = getFinancialPeriod();
    el.textContent = fp.configured
        ? 'Configured reporting period: ' + formatDate(fp.start) + ' to ' + formatDate(fp.end)
        : 'No period configured. Reports currently default to ' + formatDate(fp.start) + ' to ' + formatDate(fp.end) + ' (Apr-Mar).';
}

async function saveSettings(e) {
    e.preventDefault();
    if (state.savingSettings) return false;
    var finStart = $('setting-fin-start').value;
    var finEnd = $('setting-fin-end').value;
    if ((finStart && !finEnd) || (!finStart && finEnd)) {
        setFieldError('financial-period-error', 'Provide both the financial period start and end date.');
        showToast('Provide both the financial period start and end date.', 'error');
        return false;
    }
    if (finStart && finEnd && finEnd < finStart) {
        setFieldError('financial-period-error', 'Financial period end date cannot be earlier than the start date.');
        showToast('Financial period end date cannot be earlier than the start date.', 'error');
        return false;
    }
    clearFieldError('financial-period-error');
    var data = {
        business_name: $('setting-business').value.trim(),
        address: $('setting-address').value.trim(),
        phone: $('setting-phone').value.trim(),
        mutton_biriyani_price: parseFloat($('setting-mutton').value) || 0,
        chicken_65_price: parseFloat($('setting-chicken').value) || 0,
        collection_date: $('setting-collection-date').value,
        collection_time: $('setting-collection-time').value,
        receipt_footer: $('setting-footer').value.trim(),
        financial_start_date: finStart,
        financial_end_date: finEnd,
    };
    if (!data.business_name) { showToast('Business name is required.', 'error'); return false; }
    if (data.mutton_biriyani_price === 0 && data.chicken_65_price === 0) {
        showToast('Set at least one item price.', 'error');
        return false;
    }
    state.savingSettings = true;
    try {
        var res = await api('PUT', '/settings', data);
        state.settings = res;
        updateFinancialPeriodSummary();
        showToast('Settings saved successfully!');
    } catch(e) {
    } finally {
        state.savingSettings = false;
    }
    return false;
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

function setScanRecordsVisible(visible) {
    var rec = $('scan-records-section');
    if (rec) rec.style.display = visible ? 'block' : 'none';
}

function showScanWaiting() {
    $('scan-result').style.display = 'none';
    $('scan-result').innerHTML = '';
    $('scan-waiting').style.display = 'block';
    setScanRecordsVisible(true);
    $('scan-input').value = '';
    state.lastScanToken = null;
    state.scanPreviewBooking = null;
    setTimeout(function() { $('scan-input').focus(); }, 100);
}

function showScanError(message) {
    state.scanPreviewBooking = null;
    $('scan-waiting').style.display = 'none';
    setScanRecordsVisible(false);
    $('scan-result').innerHTML = '<div class="sc-panel sc-panel-error">' +
        '<div class="sc-error-body" role="alert">' +
        '<div class="scan-alert-icon">&#x26A0;</div>' +
        '<div><strong>Scan Not Recognised</strong>' +
        '<p>' + escHtml(message) + '</p>' +
        '<p class="sc-error-hint">Expected an SMM QR code such as <strong>SMM0001</strong>.</p>' +
        '</div></div>' +
        '<div class="sc-action-row sc-action-row-center">' +
        '<button type="button" class="btn btn-primary btn-lg" onclick="showScanWaiting()">Scan Next</button>' +
        '</div>' +
        '</div>';
    $('scan-result').style.display = 'block';
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
    loadScanTable();
}

async function loadScanTable() {
    var loading = $('scan-table-loading');
    var wrapper = $('scan-table-wrapper');
    if (loading) loading.style.display = 'block';
    if (wrapper) wrapper.style.display = 'none';
    try {
        var res = await api('GET', '/bookings?order_by=' + encodeURIComponent('function_date ASC'));
        state.allScanBookings = Array.isArray(res) ? res : [];
        renderScanTable();
    } catch(e) {
        if (loading) loading.textContent = 'Could not load the scan table. Please try again.';
    }
}

function renderScanTable() {
    var loading = $('scan-table-loading');
    var wrapper = $('scan-table-wrapper');
    var body = $('scan-table-body');
    var empty = $('scan-table-empty');
    if (!body) return;

    var filter = $('scan-table-filter') ? $('scan-table-filter').value : 'all';
    var all = state.allScanBookings || [];
    var rows = all.filter(function(b) {
        if (filter === 'pending') return b.status !== 'collected';
        if (filter === 'collected') return b.status === 'collected';
        return true;
    });

    if (loading) loading.style.display = 'none';

    if (rows.length === 0) {
        body.innerHTML = '';
        if (wrapper) wrapper.style.display = 'none';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (wrapper) wrapper.style.display = 'block';
    if (empty) empty.style.display = 'none';

    body.innerHTML = rows.map(function(b) {
        var collected = b.status === 'collected';
        var statusBadge = collected
            ? '<span class="status-badge collected">Collected</span>'
            : '<span class="status-badge pending">Pending</span>';
        var balanceClass = b.balance > 0 ? 'style="color:var(--danger);font-weight:700;"' : '';
        var action = collected
            ? '<span class="scan-table-done">&#10003; Done</span>'
            : '<button class="btn btn-success btn-sm" onclick="openCollectionModal(' + b.id + ')">Collect</button>';
        return '<tr class="scan-row-' + b.status + '">' +
            '<td data-label="Booking ID"><strong>' + escHtml(b.token_number) + '</strong></td>' +
            '<td data-label="Customer">' + escHtml(b.customer_name) + '</td>' +
            '<td data-label="Phone">' + escHtml(b.phone) + '</td>' +
            '<td data-label="Items">' + scanItemsText(b) + '</td>' +
            '<td data-label="Quantity">' + scanQtyText(b) + '</td>' +
            '<td data-label="Total Amount" class="num">' + formatCurrency(b.grand_total) + '</td>' +
            '<td data-label="Paid" class="num">' + formatCurrency(b.advance_paid) + '</td>' +
            '<td data-label="Remaining" class="num"' + balanceClass + '>' + formatCurrency(b.balance) + '</td>' +
            '<td data-label="Status">' + statusBadge + '</td>' +
            '<td data-label="Collection Date">' + formatDate(b.function_date) + '</td>' +
            '<td data-label="Action">' + action + '</td>' +
            '</tr>';
    }).join('');
}

function scanItemsText(b) {
    var items = [];
    if (parseFloat(b.mutton_qty) > 0 || b.mutton_qty) items.push('Mutton Biriyani');
    if (parseFloat(b.chicken_qty) > 0 || b.chicken_qty) items.push('Chicken 65');
    return items.length ? escHtml(items.join(', ')) : '&mdash;';
}

function scanQtyText(b) {
    var parts = [];
    if (b.mutton_qty) parts.push(escHtml(scanFmtQty(b.mutton_qty)) + ' Padi');
    if (b.chicken_qty) parts.push(escHtml(scanFmtQty(b.chicken_qty)) + ' Kg');
    return parts.length ? parts.join(' &middot; ') : '&mdash;';
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
    if (state.scanSubmitting) return;
    if (!token) return;
    if (state.lastScanToken === token && state.scanPreviewBooking) {
        showToast('This code is already shown below.', 'info');
        return;
    }
    state.scanSubmitting = true;
    try {
        var b = await api('GET', '/scan?code=' + encodeURIComponent(token));
        if (!b || !b.id) throw new Error('Booking not found.');
        state.lastScanToken = token;
        playBeep(true);
        showToast('\u2705 Booking Found', 'success');
        showScanPreview(b);
    } catch(e) {
        playBeep(false);
        var msg = (e && e.message) ? e.message : 'Invalid or unrecognised QR code.';
        showToast('\u274C ' + msg, 'error');
        showScanError(msg);
    } finally {
        state.scanSubmitting = false;
    }
}

function scanFmtQty(qty) {
    var n = Number(qty);
    if (!isFinite(n)) return String(qty);
    return String(Math.round(n * 100) / 100);
}

function scanMetaCell(label, valueHtml) {
    return '<div class="sc-meta-cell">' +
        '<span class="sc-meta-label">' + label + '</span>' +
        '<span class="sc-meta-value">' + valueHtml + '</span>' +
        '</div>';
}

function buildScanHeader(b) {
    var statusBadge = getStatusBadge(b.status);
    var paymentBadge = getPaymentStatusBadge(b.balance);
    var collectionDate = formatDate(b.function_date) || '&mdash;';
    if (b.pickup_time) collectionDate += ' <span class="sc-meta-sub">' + fmtTime(b.pickup_time) + '</span>';

    return '<div class="sc-header">' +
        '<div class="sc-header-main">' +
        '<div class="sc-title-row">' +
        '<h2 class="sc-customer-name">' + escHtml(b.customer_name) + '</h2>' +
        '<span class="sc-badges">' + statusBadge + paymentBadge + '</span>' +
        '</div>' +
        '<div class="sc-meta">' +
        scanMetaCell('Booking ID', '<span class="sc-token">' + escHtml(b.token_number) + '</span>') +
        scanMetaCell('Phone', escHtml(b.phone) || '&mdash;') +
        scanMetaCell('Booking Date', formatDate(b.booking_date) || '&mdash;') +
        scanMetaCell('Function Date', collectionDate) +
        '</div>' +
        '</div>' +
        '<div class="sc-header-actions">' +
        '<button type="button" class="btn btn-secondary" onclick="showScanWaiting()">Scan Next</button>' +
        '</div>' +
        '</div>';
}

function scanItemRows(b) {
    var rows = [];
    var mQty = Number(b.mutton_qty) || 0;
    var cQty = Number(b.chicken_qty) || 0;
    if (mQty > 0) rows.push({ name: 'Mutton Biriyani', qty: mQty, unit: 'Padi', rate: Number(b.mutton_price_per_kg) || 0 });
    if (cQty > 0) rows.push({ name: 'Chicken 65', qty: cQty, unit: 'Kg', rate: Number(b.chicken_price_per_kg) || 0 });
    return rows;
}

function buildScanItems(b) {
    var rows = scanItemRows(b);
    var body;
    if (rows.length === 0) {
        body = '<tr><td colspan="6" class="sc-items-empty">No items recorded for this booking.</td></tr>';
    } else {
        body = rows.map(function(r) {
            return '<tr>' +
                '<td class="sc-item-name">' + escHtml(r.name) + '</td>' +
                '<td class="num sc-item-qty">' + scanFmtQty(r.qty) + '</td>' +
                '<td class="sc-item-unit">' + r.unit + '</td>' +
                '<td class="num">' + formatCurrency(r.rate) + '</td>' +
                '<td class="num sc-item-amount">' + formatCurrency(r.qty * r.rate) + '</td>' +
                '<td class="sc-item-notes">&mdash;</td>' +
                '</tr>';
        }).join('');
    }
    var notes = (b.notes || '').trim();
    return '<div class="sc-section">' +
        '<div class="sc-section-head">' +
        '<h3>Order Quantities</h3>' +
        '<span class="sc-section-note">' + rows.length + ' item' + (rows.length === 1 ? '' : 's') + ' ordered</span>' +
        '</div>' +
        '<div class="sc-items-wrap"><table class="sc-items-table">' +
        '<thead><tr>' +
        '<th class="sc-th-item">Item Name</th>' +
        '<th class="num">Quantity</th>' +
        '<th>Unit</th>' +
        '<th class="num">Rate</th>' +
        '<th class="num">Amount</th>' +
        '<th>Notes</th>' +
        '</tr></thead>' +
        '<tbody>' + body + '</tbody>' +
        '</table></div>' +
        (notes ? '<p class="sc-items-notes"><strong>Booking notes:</strong> ' + escHtml(notes) + '</p>' : '') +
        '</div>';
}

function scanSummaryTile(cls, label, value, note) {
    return '<div class="sc-sum-tile ' + cls + '">' +
        '<span class="sc-sum-label">' + label + '</span>' +
        '<span class="sc-sum-value">' + value + '</span>' +
        '<span class="sc-sum-note">' + note + '</span>' +
        '</div>';
}

function buildScanSummary(b) {
    var total = Number(b.grand_total) || 0;
    var paid = Number(b.advance_paid) || 0;
    var bal = Number(b.balance) || 0;
    var due = bal > 0.000001;

    var dueTile = due
        ? scanSummaryTile('sc-sum-due', 'Remaining Balance', formatCurrency(bal), 'Due now &middot; settle at collection')
        : scanSummaryTile('sc-sum-cleared', 'Remaining Balance', formatCurrency(0), 'Nothing due &middot; fully paid');

    return '<div class="sc-section">' +
        '<div class="sc-section-head"><h3>Payment Summary</h3></div>' +
        '<div class="sc-summary">' +
        scanSummaryTile('sc-sum-total', 'Total Amount', formatCurrency(total), 'Order value') +
        scanSummaryTile('sc-sum-paid', 'Paid So Far', formatCurrency(paid), 'Received to date') +
        dueTile +
        '</div>' +
        '</div>';
}

function buildScanAction(b) {
    var bal = Number(b.balance) || 0;
    var due = bal > 0.000001;
    var collectedOn = formatDate(b.function_date);

    if (b.status === 'collected') {
        return '<div class="sc-section sc-action-section">' +
            '<div class="sc-notice sc-notice-done" role="status">' +
            '<span class="sc-notice-icon">&#10003;</span>' +
            '<div><strong>Already Collected</strong>' +
            '<p>Collected on ' + collectedOn + '. ' +
            (due ? 'An outstanding balance of ' + formatCurrency(bal) + ' still remains on this booking.' : 'This booking is fully paid.') +
            '</p></div></div>' +
            '<div class="sc-action-row">' +
            '<button type="button" class="btn btn-primary btn-lg" onclick="showScanWaiting()">Scan Next Customer</button>' +
            '</div>' +
            '</div>';
    }

    if (due) {
        return '<div class="sc-section sc-action-section">' +
            '<div class="sc-section-head">' +
            '<h3>Record Collection</h3>' +
            '<span class="sc-section-note">Partial payments allowed</span>' +
            '</div>' +
            '<div class="sc-action-row">' +
            '<div class="sc-action-field">' +
            '<label class="form-label" for="scan-received">Amount Received</label>' +
            '<div class="sc-amount-wrap">' +
            '<span class="sc-amount-symbol">&#8377;</span>' +
            '<input type="number" class="form-input sc-amount-input" id="scan-received" min="0" step="0.01" inputmode="decimal" placeholder="0.00" autocomplete="off" oninput="onScanAmountInput()">' +
            '</div>' +
            '<span class="field-error" id="scan-action-error" role="alert"></span>' +
            '</div>' +
            '<div class="sc-action-side">' +
            '<div class="sc-after-balance">' +
            '<span class="sc-after-label">Balance after collection</span>' +
            '<strong class="sc-after-value" id="scan-after-balance">' + formatCurrency(bal) + '</strong>' +
            '</div>' +
            '<div class="sc-action-buttons">' +
            '<button type="button" class="btn btn-success btn-lg sc-confirm" onclick="confirmScanCollection(' + b.id + ')">Confirm Collection</button>' +
            '<button type="button" class="btn btn-secondary btn-lg" onclick="showScanWaiting()">Skip</button>' +
            '</div>' +
            '</div>' +
            '</div>' +
            '</div>';
    }

    return '<div class="sc-section sc-action-section">' +
        '<div class="sc-notice sc-notice-paid" role="status">' +
        '<span class="sc-notice-icon">&#10003;</span>' +
        '<div><strong>No Outstanding Balance</strong>' +
        '<p>This order is fully paid. Confirm to mark it as collected.</p>' +
        '</div></div>' +
        '<div class="sc-action-row">' +
        '<button type="button" class="btn btn-success btn-lg sc-confirm" onclick="confirmScanCollection(' + b.id + ')">Mark as Collected</button>' +
        '<button type="button" class="btn btn-secondary btn-lg" onclick="showScanWaiting()">Scan Next</button>' +
        '</div>' +
        '</div>';
}

function showScanPreview(b) {
    state.scanPreviewBooking = b;
    $('scan-waiting').style.display = 'none';
    setScanRecordsVisible(false);
    $('scan-result').innerHTML = '<div class="sc-panel">' +
        buildScanHeader(b) +
        buildScanItems(b) +
        buildScanSummary(b) +
        buildScanAction(b) +
        '</div>';
    $('scan-result').style.display = 'block';
    if ($('scan-received')) {
        setTimeout(function() {
            var inp = $('scan-received');
            if (inp) inp.focus();
        }, 100);
    }
}

function setScanActionError(msg) {
    setFieldError('scan-action-error', msg);
    var inp = $('scan-received');
    if (inp) inp.classList.toggle('input-error', !!msg);
}

function onScanAmountInput() {
    var inp = $('scan-received');
    var out = $('scan-after-balance');
    if (!inp) return;
    var bal = state.scanPreviewBooking ? (Number(state.scanPreviewBooking.balance) || 0) : 0;
    var raw = String(inp.value == null ? '' : inp.value).trim();
    var n = raw === '' ? NaN : Number(raw);

    if (out) {
        var valid = raw !== '' && isFinite(n) && !isNaN(n) && n >= 0;
        out.textContent = formatCurrency(valid ? Math.max(0, Math.round((bal - n) * 100) / 100) : bal);
    }
    if (raw !== '' && isFinite(n) && !isNaN(n) && n > bal + 0.000001) {
        setScanActionError('Amount exceeds the outstanding balance of ' + formatCurrency(bal) + '.');
    } else {
        setScanActionError('');
    }
}

async function refreshScanPreview(id) {
    if (!state.scanPreviewBooking || state.scanPreviewBooking.id !== id) return;
    var active = document.querySelector('.page-section.active');
    if (!active || active.id !== 'page-scan-collection') return;
    var before = state.scanPreviewBooking;
    try {
        var fresh = await api('GET', '/bookings/' + id);
        if (!fresh || !fresh.id) return;
        if (fresh.balance !== before.balance || fresh.status !== before.status ||
            fresh.advance_paid !== before.advance_paid || fresh.grand_total !== before.grand_total) {
            showScanPreview(fresh);
        }
    } catch(e) {}
}

async function confirmScanCollection(id) {
    if (state.scanSubmitting) return;
    state.scanSubmitting = true;
    try {
        var preview = state.scanPreviewBooking;
        if (!preview || preview.id !== id) {
            preview = await api('GET', '/bookings/' + id);
            state.scanPreviewBooking = preview;
        }
        var outstanding = Number(preview.balance) || 0;
        var amount = 0;
        var inp = $('scan-received');

        if (inp) {
            var raw = String(inp.value == null ? '' : inp.value).trim();
            if (raw === '') {
                setScanActionError('Enter the amount received.');
                inp.focus();
                return;
            }
            var n = Number(raw);
            if (!isFinite(n) || isNaN(n)) {
                setScanActionError('Enter a valid amount.');
                inp.focus();
                return;
            }
            if (n < 0) {
                setScanActionError('Amount cannot be negative.');
                inp.focus();
                return;
            }
            if (n === 0) {
                setScanActionError('Amount must be greater than zero.');
                inp.focus();
                return;
            }
            if (n > outstanding + 0.000001) {
                setScanActionError('Amount exceeds the outstanding balance of ' + formatCurrency(outstanding) + '.');
                inp.focus();
                return;
            }
            amount = Math.round(n * 100) / 100;
        }
        setScanActionError('');

        var btnList = document.querySelectorAll('#scan-result .btn');
        btnList.forEach(function(x) { x.disabled = true; });
        try {
            var updated = await api('POST', '/bookings/' + id + '/collect', {
                amount_received: amount,
                request_id: genRequestId()
            });
            // Only the confirmed backend response updates what is on screen.
            state.scanPreviewBooking = updated;
            loadScanTable();
            showScanPreview(updated);
            showSuccessPopup({
                title: 'Order Collected Successfully',
                info: '<p>Remaining Balance</p><div class="token-display">' + formatCurrency(updated.balance || 0) + '</div>',
                buttons: [
                    { label: 'Send WhatsApp', cls: 'btn-success', action: function() { sendWhatsAppFromPopup(updated, 'collection'); } },
                    { label: 'Scan Next Customer', cls: 'btn-accent', action: function() { closeModal('success-modal'); showScanWaiting(); } },
                    { label: 'Home', cls: 'btn-secondary', action: function() { closeModal('success-modal'); showPage('dashboard'); } }
                ]
            });
        } finally {
            btnList.forEach(function(x) { x.disabled = false; });
        }
    } catch(e) {
    } finally {
        state.scanSubmitting = false;
    }
}

// ─── End Scan Collection ────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async function() {
    try {
        var sess = await fetch('/api/auth/session').then(function(r) { return r.json(); });
        if (!sess || !sess.authenticated) {
            window.location.replace('/login');
            return;
        }
        _csrfToken = sess.csrf_token || null;
    } catch (e) {
        window.location.replace('/login');
        return;
    }
    try {
        var s = await api('GET', '/settings');
        if (s && s.business_name) {
            $('app-title').textContent = s.business_name;
        }
        state.settings = s;
    } catch(e) {}
    showPage('dashboard');
});
