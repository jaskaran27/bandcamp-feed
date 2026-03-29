function showToast(message, isError = false) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = isError
        ? 'toast bg-red-500 text-white px-4 py-3 rounded-lg shadow-lg font-medium max-w-sm'
        : 'toast bg-bc-teal text-white px-4 py-3 rounded-lg shadow-lg font-medium max-w-sm';
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

document.body.addEventListener('showToast', function(e) {
    const message = e.detail.value || e.detail;
    showToast(message, false);
});

document.body.addEventListener('htmx:responseError', function(e) {
    const status = e.detail.xhr.status;
    let message = 'Something went wrong. Please try again.';

    if (status === 403) {
        message = 'Request forbidden. Please refresh the page and try again.';
    } else if (status === 500) {
        message = 'Server error. Check your email credentials in .env file.';
    } else if (status === 0) {
        message = 'Network error. Please check your connection.';
    }

    showToast(message, true);
});

document.body.addEventListener('htmx:sendError', function(e) {
    showToast('Network error. Please check your connection.', true);
});
