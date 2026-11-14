// QuestionBank Studio - Frontend Application Logic

// Application State
const state = {
    cart: JSON.parse(localStorage.getItem('qb_cart') || '[]'),
    selectedFiles: [],
    selectedIds: new Set(),
    useTemplate: true,
    currentPage: 1,
    limit: 25,
    totalPages: 1,
    currentQuestions: [],
    filters: {
        search: '',
        subject: '',
        topic: '',
        source: ''
    }
};

// DOM Elements
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const selectedFilesList = document.getElementById('selected-files-list');
const filesContainer = document.getElementById('files-container');
const uploadForm = document.getElementById('upload-form');
const uploadBtn = document.getElementById('upload-btn');
const uploadSubjectInput = document.getElementById('upload-subject');
const uploadTopicInput = document.getElementById('upload-topic');
const uploadResultBanner = document.getElementById('upload-result-banner');

const statTotal = document.getElementById('stat-total');
const statMerged = document.getElementById('stat-merged');
const cartBadge = document.getElementById('cart-badge');
const openCartBtn = document.getElementById('open-cart-btn');
const closeCartBtn = document.getElementById('close-cart-btn');
const cartDrawer = document.getElementById('cart-drawer');
const cartBackdrop = document.getElementById('cart-backdrop');
const cartItemsContainer = document.getElementById('cart-items-container');
const cartCountSubtitle = document.getElementById('cart-count-subtitle');
const clearCartBtn = document.getElementById('clear-cart-btn');
const exportDocxBtn = document.getElementById('export-docx-btn');
const exportPdfBtn = document.getElementById('export-pdf-btn');
const paperTitleInput = document.getElementById('paper-title-input');
const styleDefaultBtn = document.getElementById('style-default-btn');
const styleNormalBtn = document.getElementById('style-normal-btn');
const styleDesc = document.getElementById('style-desc');

const searchInput = document.getElementById('search-input');
const filterSubject = document.getElementById('filter-subject');
const filterTopic = document.getElementById('filter-topic');
const filterSource = document.getElementById('filter-source');
const questionsContainer = document.getElementById('questions-container');
const paginationInfo = document.getElementById('pagination-info');
const prevPageBtn = document.getElementById('prev-page-btn');
const nextPageBtn = document.getElementById('next-page-btn');
const pageIndicator = document.getElementById('page-indicator');
const addPageToCartBtn = document.getElementById('add-page-to-cart-btn');

// Bulk Action Bar Elements
const bulkActionBar = document.getElementById('bulk-action-bar');
const bulkSelectedCount = document.getElementById('bulk-selected-count');
const selectAllPageCb = document.getElementById('select-all-page-cb');
const bulkAddCartBtn = document.getElementById('bulk-add-cart-btn');
const bulkDocxBtn = document.getElementById('bulk-docx-btn');
const bulkPdfBtn = document.getElementById('bulk-pdf-btn');
const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
const clearSelectionBtn = document.getElementById('clear-selection-btn');

// Edit Modal Elements
const editModal = document.getElementById('edit-modal');
const editIdInput = document.getElementById('edit-id');
const editTextInput = document.getElementById('edit-text');
const editSubjectInput = document.getElementById('edit-subject');
const editTopicInput = document.getElementById('edit-topic');
const cancelEditBtn = document.getElementById('cancel-edit-btn');
const closeEditBtn = document.getElementById('close-edit-btn');
const saveEditBtn = document.getElementById('save-edit-btn');

// Add Question Modal Elements
const openAddModalBtn = document.getElementById('open-add-modal-btn');
const addModal = document.getElementById('add-modal');
const addQText = document.getElementById('add-q-text');
const addQSubject = document.getElementById('add-q-subject');
const addQTopic = document.getElementById('add-q-topic');
const addQSource = document.getElementById('add-q-source');
const addModalMsg = document.getElementById('add-modal-msg');
const closeAddBtn = document.getElementById('close-add-btn');
const cancelAddBtn = document.getElementById('cancel-add-btn');
const saveAddBtn = document.getElementById('save-add-btn');

// Backup & Restore Elements
const btnBackupLibrary = document.getElementById('btn-backup-library');
const btnRestoreLibrary = document.getElementById('btn-restore-library');
const restoreFileInput = document.getElementById('restore-file-input');

// Auth Overlay Elements
const authLockOverlay = document.getElementById('auth-lock-overlay');
const authForm = document.getElementById('auth-form');
const authPasswordInput = document.getElementById('auth-password-input');
const authErrorMsg = document.getElementById('auth-error-msg');

// Auth Token is strictly in-memory per page session - resets on every reload/visit
let inMemoryAuthToken = '';

// Clear any legacy stored tokens so every reload requires entering passcode
sessionStorage.removeItem('app_auth_token');
localStorage.removeItem('app_auth_token');

function getAuthHeaders(existingHeaders = {}) {
    if (inMemoryAuthToken) {
        return { ...existingHeaders, 'X-App-Password': inMemoryAuthToken };
    }
    return existingHeaders;
}

async function apiFetch(url, options = {}) {
    options.headers = getAuthHeaders(options.headers || {});
    const res = await fetch(url, options);
    if (res.status === 401) {
        showAuthOverlay();
    }
    return res;
}

async function checkAuthStatus() {
    try {
        const res = await fetch('/api/auth/status', {
            headers: getAuthHeaders()
        });
        if (res.ok) {
            const data = await res.json();
            if (data.protected && !data.authenticated) {
                showAuthOverlay();
                return false;
            }
        }
    } catch (e) {
        console.error("Auth status check failed:", e);
    }
    return true;
}

function showAuthOverlay() {
    if (authLockOverlay) {
        authLockOverlay.classList.remove('hidden');
        if (authPasswordInput) {
            authPasswordInput.value = '';
            authPasswordInput.focus();
        }
    }
}

function hideAuthOverlay() {
    if (authLockOverlay) {
        authLockOverlay.classList.add('hidden');
    }
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const pass = authPasswordInput.value.trim();
    if (!pass) return;

    authErrorMsg.classList.add('hidden');
    const submitBtn = document.getElementById('btn-auth-unlock');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Verifying...';

    try {
        const res = await fetch('/api/auth/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pass })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Incorrect passcode');
        }

        inMemoryAuthToken = pass;
        hideAuthOverlay();
        await loadMetadata();
        await loadQuestions();
    } catch (err) {
        authErrorMsg.textContent = err.message;
        authErrorMsg.classList.remove('hidden');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Unlock Studio';
    }
}

async function handleBackupLibrary() {
    try {
        const url = inMemoryAuthToken ? `/api/backup?auth_token=${encodeURIComponent(inMemoryAuthToken)}` : '/api/backup';
        window.location.href = url;
    } catch (e) {
        alert("Failed to download backup: " + e.message);
    }
}

async function handleRestoreFileSelected(e) {
    const file = e.target.files[0];
    if (!file) return;

    if (!confirm(`Restore and merge questions from "${file.name}" into your library?`)) {
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await apiFetch('/api/restore', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to restore backup');
        }

        const result = await res.json();
        alert(`Restore Successful!\n\n${result.message}`);
        await loadMetadata();
        await loadQuestions();
    } catch (err) {
        alert(`Error restoring backup: ${err.message}`);
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    setupEventListeners();
    updateCartBadge();
    const isAuthed = await checkAuthStatus();
    if (isAuthed) {
        loadMetadata();
        loadQuestions();
    }
});

// Event Listeners Setup
function setupEventListeners() {
    // Dropzone Events
    dropzone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => handleFilesSelected(e.target.files));

    ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('border-brand-500', 'bg-brand-50/50');
        });
    });

    ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('border-brand-500', 'bg-brand-50/50');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length) {
            handleFilesSelected(dt.files);
        }
    });

    // Upload Form Submit
    uploadForm.addEventListener('submit', handleUploadSubmit);

    // Search and Filter Events (Debounced search)
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            state.filters.search = e.target.value;
            state.currentPage = 1;
            loadQuestions();
        }, 300);
    });

    filterSubject.addEventListener('change', (e) => {
        state.filters.subject = e.target.value;
        state.currentPage = 1;
        loadQuestions();
    });

    filterTopic.addEventListener('change', (e) => {
        state.filters.topic = e.target.value;
        state.currentPage = 1;
        loadQuestions();
    });

    filterSource.addEventListener('change', (e) => {
        state.filters.source = e.target.value;
        state.currentPage = 1;
        loadQuestions();
    });

    // Pagination
    prevPageBtn.addEventListener('click', () => {
        if (state.currentPage > 1) {
            state.currentPage--;
            loadQuestions();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        if (state.currentPage < state.totalPages) {
            state.currentPage++;
            loadQuestions();
        }
    });

    // Cart Drawer Controls
    openCartBtn.addEventListener('click', openCart);
    closeCartBtn.addEventListener('click', closeCart);
    cartBackdrop.addEventListener('click', closeCart);
    clearCartBtn.addEventListener('click', clearCart);
    exportDocxBtn.addEventListener('click', () => exportFromCart('docx'));
    exportPdfBtn.addEventListener('click', () => exportFromCart('pdf'));

    if (styleDefaultBtn && styleNormalBtn) {
        styleDefaultBtn.addEventListener('click', () => setTemplateMode(true));
        styleNormalBtn.addEventListener('click', () => setTemplateMode(false));
    }

    // Bulk Add to Cart
    addPageToCartBtn.addEventListener('click', addCurrentPageToCart);

    // Bulk Actions Toolbar Events
    selectAllPageCb.addEventListener('change', (e) => toggleSelectAllPage(e.target.checked));
    bulkAddCartBtn.addEventListener('click', handleBulkAddToCart);
    bulkDocxBtn.addEventListener('click', () => handleBulkDownload('docx'));
    bulkPdfBtn.addEventListener('click', () => handleBulkDownload('pdf'));
    bulkDeleteBtn.addEventListener('click', handleBulkDelete);
    clearSelectionBtn.addEventListener('click', clearSelection);

    // Edit Modal Events
    cancelEditBtn.addEventListener('click', closeEditModal);
    closeEditBtn.addEventListener('click', closeEditModal);
    saveEditBtn.addEventListener('click', handleSaveEdit);

    // Add Question Manually Events
    openAddModalBtn.addEventListener('click', openAddModal);
    closeAddBtn.addEventListener('click', closeAddModal);
    cancelAddBtn.addEventListener('click', closeAddModal);
    saveAddBtn.addEventListener('click', handleSaveManualQuestion);

    // Backup & Restore Events
    if (btnBackupLibrary) btnBackupLibrary.addEventListener('click', handleBackupLibrary);
    if (btnRestoreLibrary) btnRestoreLibrary.addEventListener('click', () => {
        if (restoreFileInput) {
            restoreFileInput.value = '';
            restoreFileInput.click();
        }
    });
    if (restoreFileInput) restoreFileInput.addEventListener('change', handleRestoreFileSelected);

    // Auth Form Event
    if (authForm) authForm.addEventListener('submit', handleAuthSubmit);
}

// File Selection Handler
function handleFilesSelected(fileList) {
    const validFiles = Array.from(fileList).filter(f => {
        const ext = f.name.toLowerCase();
        return ext.endsWith('.docx') || ext.endsWith('.pdf');
    });

    if (validFiles.length === 0) {
        alert("Please select valid Word (.docx) or PDF (.pdf) files.");
        return;
    }

    // Append to selected files
    state.selectedFiles.push(...validFiles);
    renderSelectedFiles();
}

function renderSelectedFiles() {
    if (state.selectedFiles.length === 0) {
        selectedFilesList.classList.add('hidden');
        uploadBtn.disabled = true;
        uploadBtn.className = "inline-flex items-center space-x-2 bg-slate-200 text-slate-400 px-5 py-2.5 rounded-xl text-sm font-semibold cursor-not-allowed transition-all";
        return;
    }

    selectedFilesList.classList.remove('hidden');
    uploadBtn.disabled = false;
    uploadBtn.className = "inline-flex items-center space-x-2 bg-brand-600 hover:bg-brand-700 text-white px-5 py-2.5 rounded-xl text-sm font-semibold cursor-pointer shadow-md shadow-brand-500/20 active:scale-95 transition-all";

    filesContainer.innerHTML = state.selectedFiles.map((file, idx) => `
        <span class="inline-flex items-center space-x-1.5 text-xs bg-white border border-slate-200 px-3 py-1.5 rounded-lg text-slate-700 shadow-sm">
            <span>📄 ${escapeHtml(file.name)}</span>
            <button type="button" onclick="removeSelectedFile(${idx})" class="text-slate-400 hover:text-rose-500 ml-1 font-bold">✕</button>
        </span>
    `).join('');
}

window.removeSelectedFile = function(index) {
    state.selectedFiles.splice(index, 1);
    renderSelectedFiles();
};

// Upload Submission
async function handleUploadSubmit(e) {
    e.preventDefault();
    if (state.selectedFiles.length === 0) return;

    uploadBtn.disabled = true;
    uploadBtn.innerHTML = `
        <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Extracting Questions...</span>
    `;

    const formData = new FormData();
    state.selectedFiles.forEach(f => formData.append('files', f));
    formData.append('subject', uploadSubjectInput.value.trim());
    formData.append('topic', uploadTopicInput.value.trim());

    try {
        const response = await apiFetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await response.json();

        // Show result banner with clear feedback
        if (data.total_extracted === 0) {
            uploadResultBanner.className = "mt-4 p-4 rounded-xl border bg-amber-50 border-amber-200 text-amber-800 text-sm space-y-1 block";
            uploadResultBanner.innerHTML = `
                <div class="flex items-center space-x-2 font-bold text-amber-900">
                    <svg class="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>0 Questions Extracted</span>
                </div>
                <p class="text-xs text-amber-700">
                    We could not find questions in the uploaded document. Please check that your questions are written on separate lines or prefixed with numbers (e.g. 1., 2., Q1.).
                </p>
            `;
        } else {
            uploadResultBanner.className = "mt-4 p-4 rounded-xl border bg-emerald-50 border-emerald-200 text-emerald-800 text-sm space-y-1 block";
            uploadResultBanner.innerHTML = `
                <div class="flex items-center space-x-2 font-bold">
                    <svg class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                    <span>Extraction Complete!</span>
                </div>
                <p class="text-xs text-emerald-700">
                    Extracted <strong>${data.total_extracted}</strong> questions total from ${data.total_files} file(s).
                    <strong>${data.total_new}</strong> added as new, and <strong>${data.total_merged}</strong> identical duplicates merged into existing entries.
                </p>
            `;
        }

        // Clear files
        state.selectedFiles = [];
        uploadSubjectInput.value = '';
        uploadTopicInput.value = '';
        renderSelectedFiles();

        // Refresh library and metadata
        await loadMetadata();
        await loadQuestions();

    } catch (error) {
        uploadResultBanner.className = "mt-4 p-4 rounded-xl border bg-rose-50 border-rose-200 text-rose-800 text-sm space-y-1 block";
        uploadResultBanner.innerHTML = `<strong>Error:</strong> ${escapeHtml(error.message)}`;
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = `<span>Extract & Add to Library</span>`;
    }
}

// Load Metadata for Stats & Dropdowns
async function loadMetadata() {
    try {
        const res = await apiFetch('/api/metadata');
        if (!res.ok) return;
        const data = await res.json();

        statTotal.textContent = data.total_unique || 0;
        statMerged.textContent = data.merged_duplicates || 0;

        // Populate Subjects
        const currentSub = filterSubject.value;
        filterSubject.innerHTML = '<option value="">All Subjects</option>' +
            data.subjects.map(s => `<option value="${escapeHtml(s)}"${s === currentSub ? ' selected' : ''}>${escapeHtml(s)}</option>`).join('');

        // Populate Topics
        const currentTopic = filterTopic.value;
        filterTopic.innerHTML = '<option value="">All Topics</option>' +
            data.topics.map(t => `<option value="${escapeHtml(t)}"${t === currentTopic ? ' selected' : ''}>${escapeHtml(t)}</option>`).join('');

        // Populate Sources
        const currentSrc = filterSource.value;
        filterSource.innerHTML = '<option value="">All Source Files</option>' +
            data.sources.map(src => `<option value="${escapeHtml(src)}"${src === currentSrc ? ' selected' : ''}>${escapeHtml(src)}</option>`).join('');

    } catch (err) {
        console.error("Error loading metadata:", err);
    }
}

// Load Questions List
async function loadQuestions() {
    questionsContainer.innerHTML = `
        <div class="py-12 text-center text-slate-400 space-y-2">
            <svg class="animate-spin mx-auto h-6 w-6 text-brand-600" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <p class="text-xs">Loading questions...</p>
        </div>
    `;

    const params = new URLSearchParams({
        page: state.currentPage,
        limit: state.limit
    });

    if (state.filters.search) params.append('search', state.filters.search);
    if (state.filters.subject) params.append('subject', state.filters.subject);
    if (state.filters.topic) params.append('topic', state.filters.topic);
    if (state.filters.source) params.append('source', state.filters.source);

    try {
        const res = await apiFetch(`/api/questions?${params.toString()}`);
        if (!res.ok) throw new Error("Failed to load questions");
        const data = await res.json();

        state.currentQuestions = data.items;
        state.totalPages = Math.max(1, Math.ceil(data.total / state.limit));

        renderQuestions(data);
    } catch (err) {
        questionsContainer.innerHTML = `
            <div class="p-6 text-center text-rose-600 bg-rose-50 rounded-xl border border-rose-200 text-sm">
                Failed to load questions: ${escapeHtml(err.message)}
            </div>
        `;
    }
}

// Render Question Cards
function renderQuestions(data) {
    if (!data.items || data.items.length === 0) {
        questionsContainer.innerHTML = `
            <div class="bg-white rounded-2xl border border-slate-200/80 p-12 text-center text-slate-400 space-y-3">
                <div class="w-12 h-12 rounded-full bg-slate-100 mx-auto flex items-center justify-center text-slate-400">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                </div>
                <h3 class="font-bold text-slate-700 text-base">No questions found</h3>
                <p class="text-xs text-slate-500 max-w-sm mx-auto">Upload Word (.docx) or PDF question banks above or try a different search filter.</p>
            </div>
        `;
        paginationInfo.textContent = "Showing 0 questions";
        prevPageBtn.disabled = true;
        nextPageBtn.disabled = true;
        return;
    }

    const startIdx = (state.currentPage - 1) * state.limit + 1;
    const endIdx = Math.min(startIdx + data.items.length - 1, data.total);
    paginationInfo.textContent = `Showing ${startIdx}–${endIdx} of ${data.total} questions`;

    pageIndicator.textContent = `${state.currentPage} / ${state.totalPages}`;
    prevPageBtn.disabled = state.currentPage <= 1;
    nextPageBtn.disabled = state.currentPage >= state.totalPages;
    prevPageBtn.className = state.currentPage <= 1 ? "px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-400 cursor-not-allowed" : "px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer";
    nextPageBtn.className = state.currentPage >= state.totalPages ? "px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-400 cursor-not-allowed" : "px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer";

    questionsContainer.innerHTML = data.items.map((q) => {
        const inCart = isQuestionInCart(q.id);
        const freq = q.frequency || 1;
        const isRepeated = freq > 1;
        const isSelected = state.selectedIds.has(q.id);

        return `
            <div data-id="${q.id}" class="question-card bg-white p-5 rounded-2xl border ${isSelected ? 'border-brand-500 bg-brand-50/20 ring-1 ring-brand-500' : 'border-slate-200/80'} shadow-sm flex flex-col md:flex-row md:items-start justify-between gap-4">
                <div class="flex items-start space-x-3.5 flex-1">
                    <!-- Checkbox for multi-select -->
                    <input type="checkbox" onchange="toggleSelectQuestion(${q.id}, this.checked)" ${isSelected ? 'checked' : ''} class="w-4 h-4 rounded text-brand-600 focus:ring-brand-500 cursor-pointer mt-1 shrink-0" title="Select to delete or add to cart">

                    <div class="space-y-2 flex-1">
                        <!-- Badges Row -->
                        <div class="flex flex-wrap items-center gap-2">
                            ${isRepeated ? `
                                <span class="inline-flex items-center space-x-1 text-xs font-bold px-2.5 py-0.5 rounded-full high-frequency-badge shadow-xs">
                                    <span>🔥 Appeared ${freq}x</span>
                                </span>
                            ` : `
                                <span class="inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-600">
                                    Appeared 1x
                                </span>
                            `}

                            ${q.subject ? `
                                <span class="inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-100">
                                    📚 ${escapeHtml(q.subject)}
                                </span>
                            ` : ''}

                            ${q.topic ? `
                                <span class="inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                                    🏷️ ${escapeHtml(q.topic)}
                                </span>
                            ` : ''}

                            ${q.sources && q.sources.length ? `
                                <span class="inline-flex items-center text-[11px] text-slate-400 px-1.5 py-0.5" title="Found in: ${escapeHtml(q.sources.join(', '))}">
                                    📄 ${q.sources.length} source file(s)
                                </span>
                            ` : ''}
                        </div>

                        <!-- Question Text -->
                        <p class="text-sm font-medium text-slate-900 leading-relaxed pt-1">
                            ${escapeHtml(q.question_text)}
                        </p>
                    </div>
                </div>

                <!-- Action Buttons -->
                <div class="flex items-center space-x-2 shrink-0 self-end md:self-center">
                    <button onclick="toggleCartQuestion(${q.id})" class="inline-flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all ${
                        inCart
                            ? 'bg-emerald-600 text-white shadow-sm hover:bg-emerald-700'
                            : 'bg-brand-50 text-brand-700 border border-brand-200 hover:bg-brand-600 hover:text-white'
                    }">
                        ${inCart ? '✓ In Cart' : '+ Add to Cart'}
                    </button>
                    <button onclick="openEditModal(${q.id})" class="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer" title="Edit Question">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                        </svg>
                    </button>
                    <button onclick="deleteQuestion(${q.id})" class="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer" title="Delete Question">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                    </button>

                    <!-- Quick Download Word / PDF options on Question Card -->
                    <div class="flex items-center space-x-1 border-l border-slate-200 pl-2">
                        <button onclick="downloadSingleQuestion(${q.id}, 'docx')" class="px-2 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-brand-600 hover:bg-brand-50 transition-colors flex items-center space-x-1 cursor-pointer" title="Download this question as Word (.docx)">
                            <span>📄 Word</span>
                        </button>
                        <button onclick="downloadSingleQuestion(${q.id}, 'pdf')" class="px-2 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-rose-600 hover:bg-rose-50 transition-colors flex items-center space-x-1 cursor-pointer" title="Download this question as PDF (.pdf)">
                            <span>📕 PDF</span>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    updateBulkActionBar();
}

// Multi-Select & Bulk Actions
window.toggleSelectQuestion = function(id, isChecked) {
    if (isChecked) {
        state.selectedIds.add(id);
    } else {
        state.selectedIds.delete(id);
    }
    updateBulkActionBar();
    const card = document.querySelector(`.question-card[data-id="${id}"]`);
    if (card) {
        if (isChecked) {
            card.classList.add('border-brand-500', 'bg-brand-50/20', 'ring-1', 'ring-brand-500');
            card.classList.remove('border-slate-200/80');
        } else {
            card.classList.remove('border-brand-500', 'bg-brand-50/20', 'ring-1', 'ring-brand-500');
            card.classList.add('border-slate-200/80');
        }
    }
};

function toggleSelectAllPage(isChecked) {
    state.currentQuestions.forEach(q => {
        if (isChecked) {
            state.selectedIds.add(q.id);
        } else {
            state.selectedIds.delete(q.id);
        }
    });
    updateBulkActionBar();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
}

function clearSelection() {
    state.selectedIds.clear();
    updateBulkActionBar();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
}

function updateBulkActionBar() {
    const count = state.selectedIds.size;
    bulkSelectedCount.textContent = `${count} selected`;
    bulkDeleteBtn.innerHTML = `
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
        <span>Delete Selected (${count})</span>
    `;
    bulkAddCartBtn.textContent = `+ Add to Cart (${count})`;

    if (count > 0) {
        bulkActionBar.classList.remove('hidden');
    } else {
        bulkActionBar.classList.add('hidden');
    }

    if (state.currentQuestions.length > 0 && state.currentQuestions.every(q => state.selectedIds.has(q.id))) {
        selectAllPageCb.checked = true;
    } else {
        selectAllPageCb.checked = false;
    }
}

async function handleBulkDelete() {
    const ids = Array.from(state.selectedIds);
    if (ids.length === 0) return;

    if (!confirm(`Are you sure you want to permanently delete all ${ids.length} selected questions from the library?`)) {
        return;
    }

    bulkDeleteBtn.disabled = true;
    bulkDeleteBtn.innerHTML = `
        <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Deleting...</span>
    `;

    try {
        const res = await apiFetch('/api/questions/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question_ids: ids })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to delete questions');
        }

        // Also remove from cart if present
        state.cart = state.cart.filter(item => !state.selectedIds.has(item.id));
        saveCart();

        // Clear selection
        state.selectedIds.clear();
        updateBulkActionBar();

        await loadMetadata();
        await loadQuestions();

    } catch (err) {
        alert("Error deleting questions: " + err.message);
    } finally {
        bulkDeleteBtn.disabled = false;
        updateBulkActionBar();
    }
}

function handleBulkAddToCart() {
    const ids = Array.from(state.selectedIds);
    if (ids.length === 0) return;

    ids.forEach(id => {
        if (!isQuestionInCart(id)) {
            const question = state.currentQuestions.find(q => q.id === id);
            if (question) {
                state.cart.push({
                    id: question.id,
                    question_text: question.question_text,
                    subject: question.subject,
                    topic: question.topic
                });
            }
        }
    });

    saveCart();
    state.selectedIds.clear();
    updateBulkActionBar();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
}

// Cart State Management
function isQuestionInCart(id) {
    return state.cart.some(item => item.id === id);
}

function saveCart() {
    localStorage.setItem('qb_cart', JSON.stringify(state.cart));
    updateCartBadge();
    renderCartDrawer();
}

function updateCartBadge() {
    cartBadge.textContent = state.cart.length;
    openCartBtn.classList.remove('animate-cart-bounce');
    void openCartBtn.offsetWidth; // trigger reflow
    openCartBtn.classList.add('animate-cart-bounce');
}

window.toggleCartQuestion = function(id) {
    const existingIndex = state.cart.findIndex(item => item.id === id);
    if (existingIndex > -1) {
        state.cart.splice(existingIndex, 1);
    } else {
        const question = state.currentQuestions.find(q => q.id === id);
        if (question) {
            state.cart.push({
                id: question.id,
                question_text: question.question_text,
                subject: question.subject,
                topic: question.topic
            });
        }
    }
    saveCart();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
};

function addCurrentPageToCart() {
    let addedCount = 0;
    state.currentQuestions.forEach(q => {
        if (!isQuestionInCart(q.id)) {
            state.cart.push({
                id: q.id,
                question_text: q.question_text,
                subject: q.subject,
                topic: q.topic
            });
            addedCount++;
        }
    });
    saveCart();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
}

function openCart() {
    cartBackdrop.classList.remove('hidden');
    cartDrawer.classList.remove('translate-x-full');
    renderCartDrawer();
}

function closeCart() {
    cartBackdrop.classList.add('hidden');
    cartDrawer.classList.add('translate-x-full');
}

function clearCart() {
    if (state.cart.length === 0) return;
    if (confirm("Clear all selected questions from your cart?")) {
        state.cart = [];
        saveCart();
        renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
    }
}

function renderCartDrawer() {
    cartCountSubtitle.textContent = `${state.cart.length} questions in current paper`;

    if (state.cart.length === 0) {
        cartItemsContainer.innerHTML = `
            <div class="h-64 flex flex-col items-center justify-center text-slate-400 space-y-2">
                <svg class="w-10 h-10 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z" />
                </svg>
                <p class="text-sm font-medium">Your question cart is empty</p>
                <p class="text-xs text-slate-400">Click "+ Add to Cart" on any question to select it</p>
            </div>
        `;
        exportDocxBtn.disabled = true;
        exportDocxBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-slate-200 text-slate-400 font-bold py-3 rounded-xl cursor-not-allowed transition-all text-xs sm:text-sm";
        exportPdfBtn.disabled = true;
        exportPdfBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-slate-200 text-slate-400 font-bold py-3 rounded-xl cursor-not-allowed transition-all text-xs sm:text-sm";
        return;
    }

    exportDocxBtn.disabled = false;
    exportDocxBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-brand-600 hover:bg-brand-700 text-white font-bold py-3 rounded-xl transition-all shadow-md shadow-brand-500/25 active:scale-[0.98] cursor-pointer text-xs sm:text-sm";
    exportPdfBtn.disabled = false;
    exportPdfBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold py-3 rounded-xl transition-all shadow-md shadow-rose-600/25 active:scale-[0.98] cursor-pointer text-xs sm:text-sm";

    cartItemsContainer.innerHTML = state.cart.map((item, index) => `
        <div class="bg-slate-50 border border-slate-200/80 rounded-xl p-3 flex items-start justify-between gap-3 shadow-xs">
            <div class="flex items-start space-x-2 flex-1">
                <span class="w-5 h-5 rounded-full bg-brand-100 text-brand-700 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
                    ${index + 1}
                </span>
                <p class="text-xs text-slate-800 leading-snug line-clamp-3">
                    ${escapeHtml(item.question_text)}
                </p>
            </div>

            <!-- Controls: Move Up, Move Down, Remove -->
            <div class="flex items-center space-x-1 shrink-0">
                <button onclick="moveCartItem(${index}, -1)" ${index === 0 ? 'disabled' : ''} class="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-20 disabled:hover:text-slate-400" title="Move Up">
                    ▲
                </button>
                <button onclick="moveCartItem(${index}, 1)" ${index === state.cart.length - 1 ? 'disabled' : ''} class="p-1 rounded text-slate-400 hover:text-slate-700 disabled:opacity-20 disabled:hover:text-slate-400" title="Move Down">
                    ▼
                </button>
                <button onclick="removeFromCart(${index})" class="p-1 rounded text-slate-400 hover:text-rose-600 font-bold ml-1 cursor-pointer" title="Remove">
                    ✕
                </button>
            </div>
        </div>
    `).join('');
}

window.moveCartItem = function(index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= state.cart.length) return;
    const item = state.cart.splice(index, 1)[0];
    state.cart.splice(targetIndex, 0, item);
    saveCart();
};

window.removeFromCart = function(index) {
    state.cart.splice(index, 1);
    saveCart();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
};

function setTemplateMode(useTemplate) {
    state.useTemplate = useTemplate;
    if (useTemplate) {
        styleDefaultBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-bold cursor-pointer transition-all select-none bg-white text-brand-700 shadow-xs border border-brand-200";
        styleNormalBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-semibold cursor-pointer transition-all select-none text-slate-600 hover:text-slate-900";
        styleDesc.innerHTML = 'Uses your master printout layout: <strong>A4 size, 0.5" margins, double page border, and Times New Roman</strong>.';
    } else {
        styleNormalBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-bold cursor-pointer transition-all select-none bg-white text-brand-700 shadow-xs border border-brand-200";
        styleDefaultBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-semibold cursor-pointer transition-all select-none text-slate-600 hover:text-slate-900";
        styleDesc.innerHTML = 'Standard layout: <strong>Letter size, 1" margins, Calibri</strong>.';
    }
}

// Unified Export Function for Word and PDF
async function downloadQuestions(questionIds, format = 'docx', title = '') {
    if (!questionIds || questionIds.length === 0) return;

    const isPdf = format.toLowerCase() === 'pdf';
    const label = isPdf ? 'PDF' : 'Word';

    try {
        const response = await apiFetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_ids: questionIds,
                title: title,
                format: format,
                use_template: state.useTemplate
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Failed to generate ${label} document`);
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        const cleanName = title ? title.replace(/[^a-zA-Z0-9_-]/g, '_') : 'Question_Paper';
        a.download = `${cleanName}.${isPdf ? 'pdf' : 'docx'}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

    } catch (err) {
        alert(`Failed to export ${label}: ${err.message}`);
    }
}

// Download a single question directly from its Question Card
window.downloadSingleQuestion = function(id, format) {
    downloadQuestions([id], format, '');
};

// Download all questions currently in the Cart
function exportFromCart(format) {
    if (state.cart.length === 0) return;
    const questionIds = state.cart.map(item => item.id);
    const title = paperTitleInput.value.trim();
    downloadQuestions(questionIds, format, title);
}

// Download all selected questions from Bulk Selection Bar
function handleBulkDownload(format) {
    const ids = Array.from(state.selectedIds);
    if (ids.length === 0) {
        alert("Please select at least one question first.");
        return;
    }
    downloadQuestions(ids, format, '');
}

// Edit Question Modal Handling
window.openEditModal = function(id) {
    const q = state.currentQuestions.find(item => item.id === id);
    if (!q) return;

    editIdInput.value = q.id;
    editTextInput.value = q.question_text;
    editSubjectInput.value = q.subject || '';
    editTopicInput.value = q.topic || '';

    editModal.classList.remove('hidden');
};

function closeEditModal() {
    editModal.classList.add('hidden');
}

async function handleSaveEdit() {
    const id = editIdInput.value;
    const text = editTextInput.value.trim();
    const subject = editSubjectInput.value.trim();
    const topic = editTopicInput.value.trim();

    if (!text) {
        alert("Question text cannot be empty.");
        return;
    }

    try {
        const res = await apiFetch(`/api/questions/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_text: text,
                subject: subject,
                topic: topic
            })
        });

        if (!res.ok) throw new Error("Failed to save changes");

        closeEditModal();
        await loadMetadata();
        await loadQuestions();

        // Also update in cart if present
        const cartIndex = state.cart.findIndex(c => c.id === parseInt(id));
        if (cartIndex > -1) {
            state.cart[cartIndex].question_text = text;
            state.cart[cartIndex].subject = subject;
            state.cart[cartIndex].topic = topic;
            saveCart();
        }

    } catch (err) {
        alert("Error saving: " + err.message);
    }
}

// Delete Question Handling
window.deleteQuestion = async function(id) {
    if (!confirm("Are you sure you want to delete this question from the library?")) return;

    try {
        const res = await apiFetch(`/api/questions/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error("Failed to delete question");

        // Remove from cart if present
        const cartIndex = state.cart.findIndex(c => c.id === id);
        if (cartIndex > -1) {
            state.cart.splice(cartIndex, 1);
            saveCart();
        }

        await loadMetadata();
        await loadQuestions();
    } catch (err) {
        alert("Error deleting question: " + err.message);
    }
};

// Add Question Manually Modal Handling
function openAddModal() {
    addQText.value = '';
    addQSubject.value = '';
    addQTopic.value = '';
    addQSource.value = 'Manual Entry';
    addModalMsg.className = 'hidden text-xs p-3 rounded-xl';
    addModalMsg.innerHTML = '';
    saveAddBtn.disabled = false;
    saveAddBtn.innerHTML = `<span>Save to Library</span>`;
    addModal.classList.remove('hidden');
    setTimeout(() => addQText.focus(), 50);
}

function closeAddModal() {
    addModal.classList.add('hidden');
}

async function handleSaveManualQuestion() {
    const text = addQText.value.trim();
    const subject = addQSubject.value.trim();
    const topic = addQTopic.value.trim();
    const source = addQSource.value.trim() || 'Manual Entry';

    if (!text) {
        addModalMsg.className = 'text-xs p-3 rounded-xl bg-rose-50 text-rose-700 border border-rose-200 block';
        addModalMsg.textContent = 'Please enter question text.';
        return;
    }

    saveAddBtn.disabled = true;
    saveAddBtn.innerHTML = `
        <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Saving...</span>
    `;

    try {
        const res = await apiFetch('/api/questions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_text: text,
                subject: subject,
                topic: topic,
                source: source
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to add question');
        }

        const data = await res.json();

        // Show feedback inside modal before closing
        if (data.is_merged) {
            addModalMsg.className = 'text-xs p-3 rounded-xl bg-amber-50 text-amber-800 border border-amber-200 block';
            addModalMsg.textContent = 'Duplicate found: This question already existed in the library, so its frequency counter was increased!';
        } else {
            addModalMsg.className = 'text-xs p-3 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200 block';
            addModalMsg.textContent = 'Question added to library successfully!';
        }

        await loadMetadata();
        await loadQuestions();

        setTimeout(() => {
            closeAddModal();
        }, 1100);

    } catch (err) {
        addModalMsg.className = 'text-xs p-3 rounded-xl bg-rose-50 text-rose-700 border border-rose-200 block';
        addModalMsg.textContent = 'Error: ' + err.message;
        saveAddBtn.disabled = false;
        saveAddBtn.innerHTML = `<span>Save to Library</span>`;
    }
}

// Utility function to escape HTML to prevent XSS
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
