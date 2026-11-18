// Squire Way - Question Bank Frontend Application Logic

// Application State
const state = {
    currentUser: JSON.parse(sessionStorage.getItem('qb_user') || 'null'),
    cart: JSON.parse(localStorage.getItem('qb_cart') || '[]'),
    selectedFiles: [],
    selectedIds: new Set(),
    useTemplate: true,
    theme: localStorage.getItem('qb_theme') || 'system',
    density: localStorage.getItem('qb_density') || 'comfortable',
    currentPage: 1,
    limit: 25,
    totalPages: 1,
    currentQuestions: [],
    filters: {
        search: '',
        subject: '',
        topic: '',
        source: ''
    },
    pageCache: new Map(),
    maxCacheEntries: 40
};

// Tactile Haptic Touch Feedback Utility
function triggerHaptic(type = 'light') {
    if (!navigator.vibrate) return;
    try {
        if (type === 'light') navigator.vibrate(10);
        else if (type === 'medium') navigator.vibrate(25);
        else if (type === 'success') navigator.vibrate([10, 30, 15]);
        else if (type === 'error') navigator.vibrate([30, 50, 30]);
    } catch (e) {}
}
window.triggerHaptic = triggerHaptic;

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
const densityComfortableBtn = document.getElementById('density-comfortable-btn');
const densityCompactBtn = document.getElementById('density-compact-btn');
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

// Backup & Restore Elements (In User Profile Dropdown)
const btnBackupLibrary = document.getElementById('btn-backup-library');
const btnRestoreLibrary = document.getElementById('btn-restore-library');
const restoreFileInput = document.getElementById('restore-file-input');

// Modern Toast Notification Container
const toastContainer = document.getElementById('toast-container');

// Mobile Collapsible Filters Elements
const toggleFiltersBtn = document.getElementById('toggle-filters-btn');
const filtersContainer = document.getElementById('filters-container');
const activeFiltersBadge = document.getElementById('active-filters-badge');

// Auth Overlay Elements
const authLockOverlay = document.getElementById('auth-lock-overlay');
const authForm = document.getElementById('auth-form');
const authUsernameInput = document.getElementById('auth-username-input');
const authPasswordInput = document.getElementById('auth-password-input');
const btnToggleLoginPwd = document.getElementById('btn-toggle-login-pwd');
const authLockoutBanner = document.getElementById('auth-lockout-banner');
const authErrorMsg = document.getElementById('auth-error-msg');
const authBtnText = document.getElementById('auth-btn-text');
const authBtnSpinner = document.getElementById('auth-btn-spinner');

// User Profile Elements (Unified Desktop & Mobile)
const userProfileContainer = document.getElementById('user-profile-container');
const userProfileBtn = document.getElementById('user-profile-btn');
const userDropdownMenu = document.getElementById('user-dropdown-menu');
const userAvatar = document.getElementById('user-avatar');
const userDisplayName = document.getElementById('user-display-name');
const userRoleBadge = document.getElementById('user-role-badge');
const dropdownUsername = document.getElementById('dropdown-username');
const dropdownRole = document.getElementById('dropdown-role');
const btnOpenManageUsers = document.getElementById('btn-open-manage-users');
const btnOpenChangePassword = document.getElementById('btn-open-change-password');
const btnLogout = document.getElementById('btn-logout');

// Theme Switcher Elements (Inside User Dropdown)
const themeBtnLight = document.getElementById('theme-btn-light');
const themeBtnDark = document.getElementById('theme-btn-dark');
const themeBtnSystem = document.getElementById('theme-btn-system');
const themeActiveLabel = document.getElementById('theme-active-label');

// User Management Modal Elements
const userMgmtModal = document.getElementById('user-mgmt-modal');
const closeUserMgmtBtn = document.getElementById('close-user-mgmt-btn');
const createUserForm = document.getElementById('create-user-form');
const newUsernameInput = document.getElementById('new-user-username');
const newDisplayNameInput = document.getElementById('new-user-displayname');
const newPasswordInput = document.getElementById('new-user-password');
const newUserRoleSelect = document.getElementById('new-user-role');
const createUserMsg = document.getElementById('create-user-msg');
const userMgmtTableBody = document.getElementById('user-mgmt-table-body');

// Change Password Modal Elements
const changePasswordModal = document.getElementById('change-password-modal');
const closeChangePwdBtn = document.getElementById('close-change-pwd-btn');
const cancelChangePwdBtn = document.getElementById('cancel-change-pwd-btn');
const changePwdForm = document.getElementById('change-pwd-form');
const oldPwdInput = document.getElementById('old-pwd-input');
const newPwdInput = document.getElementById('new-pwd-input');
const confirmNewPwdInput = document.getElementById('confirm-new-pwd-input');
const changePwdMsg = document.getElementById('change-pwd-msg');

// ================= Auth, Session & RBAC Core =================

// 15-Minute Inactivity Auto-Lock
let inactivityTimer = null;
const INACTIVITY_TIMEOUT_MS = 15 * 60 * 1000;

function resetInactivityTimer() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    const token = sessionStorage.getItem('qb_token');
    if (token) {
        inactivityTimer = setTimeout(() => {
            handleInactivityLogout();
        }, INACTIVITY_TIMEOUT_MS);
    }
}

function setupInactivityListeners() {
    ['mousemove', 'keydown', 'touchstart', 'scroll', 'click'].forEach(evt => {
        window.addEventListener(evt, resetInactivityTimer, { passive: true });
    });
}

async function handleInactivityLogout() {
    await performLogout(false);
    showAuthOverlay("Session locked after 15 minutes of inactivity. Please sign in again.");
}

function getPageCacheKey(page, limit, filters) {
    return `${page}_${limit}_${filters.search || ''}_${filters.subject || ''}_${filters.topic || ''}_${filters.source || ''}`;
}

function clearPageCache() {
    state.pageCache.clear();
}

let wakeupBannerTimer = null;
let isWakingUp = false;

function showWakeupBanner() {
    let banner = document.getElementById('render-wakeup-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.id = 'render-wakeup-banner';
        banner.className = 'fixed bottom-5 left-1/2 -translate-x-1/2 z-50 bg-slate-900/95 dark:bg-slate-800/95 text-white dark:text-slate-100 px-4 py-2 rounded-full shadow-2xl border border-slate-700/80 flex items-center space-x-2.5 text-xs font-semibold backdrop-blur-md transition-all duration-300';
        banner.innerHTML = `
            <span class="inline-block w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping"></span>
            <span>⚡ Connecting to server... (Waking from free tier idle)</span>
        `;
        document.body.appendChild(banner);
    }
    banner.classList.remove('hidden');
    isWakingUp = true;
}

function hideWakeupBanner() {
    const banner = document.getElementById('render-wakeup-banner');
    if (banner && isWakingUp) {
        banner.classList.add('hidden');
        isWakingUp = false;
    }
}

function getAuthHeaders(existingHeaders = {}) {
    const token = sessionStorage.getItem('qb_token');
    if (token) {
        return { ...existingHeaders, 'Authorization': `Bearer ${token}` };
    }
    return existingHeaders;
}

async function apiFetch(url, options = {}, retries = 1) {
    options.headers = getAuthHeaders(options.headers || {});
    
    // Set timer for polite wake-up feedback if request takes > 3.5s (free container wake-up)
    const wakeupTimer = setTimeout(() => {
        showWakeupBanner();
    }, 3500);

    try {
        const res = await fetch(url, options);
        clearTimeout(wakeupTimer);
        hideWakeupBanner();

        if (res.status === 401) {
            clearSession();
            showAuthOverlay("Session expired. Please sign in again.");
        }
        return res;
    } catch (err) {
        clearTimeout(wakeupTimer);
        if (retries > 0) {
            // Wait 2s and retry once in case network dropped during cold container start
            await new Promise(r => setTimeout(r, 2000));
            return apiFetch(url, options, retries - 1);
        }
        hideWakeupBanner();
        throw err;
    }
}

async function checkAuthStatus() {
    try {
        const token = sessionStorage.getItem('qb_token');
        if (!token) {
            const res = await fetch('/api/auth/status');
            if (res.ok) {
                const data = await res.json();
                if (!data.protected) {
                    state.currentUser = data.user || { username: 'admin', role: 'admin' };
                    updateUserProfileUI();
                    return true;
                }
            }
            showAuthOverlay();
            return false;
        }

        const res = await fetch('/api/auth/status', {
            headers: getAuthHeaders()
        });
        if (res.ok) {
            const data = await res.json();
            if (data.authenticated && data.user) {
                state.currentUser = data.user;
                sessionStorage.setItem('qb_user', JSON.stringify(data.user));
                updateUserProfileUI();
                resetInactivityTimer();
                return true;
            }
        }
    } catch (e) {
        console.error("Auth status check failed:", e);
    }
    clearSession();
    showAuthOverlay();
    return false;
}

function clearSession() {
    sessionStorage.removeItem('qb_token');
    sessionStorage.removeItem('qb_user');
    state.currentUser = null;
    if (inactivityTimer) clearTimeout(inactivityTimer);
    updateUserProfileUI();
}

function showAuthOverlay(customMessage = '') {
    if (authLockOverlay) {
        authLockOverlay.classList.remove('hidden');
        if (authPasswordInput) authPasswordInput.value = '';
        if (authErrorMsg) {
            if (customMessage) {
                authErrorMsg.textContent = customMessage;
                authErrorMsg.classList.remove('hidden');
            } else {
                authErrorMsg.classList.add('hidden');
            }
        }
        if (authUsernameInput) {
            authUsernameInput.focus();
        }
    }
}

function hideAuthOverlay() {
    if (authLockOverlay) {
        authLockOverlay.classList.add('hidden');
    }
}

// Modern Floating Toast Notification System
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-item toast-enter flex items-center space-x-2.5 p-3 sm:p-3.5 rounded-xl shadow-lg border text-xs font-semibold';

    let icon = 'ℹ️';
    let bgClasses = 'bg-white text-slate-800 border-slate-200';
    if (type === 'success') {
        icon = '✅';
        bgClasses = 'bg-emerald-50 text-emerald-900 border-emerald-200';
    } else if (type === 'error') {
        icon = '❌';
        bgClasses = 'bg-rose-50 text-rose-900 border-rose-200';
    } else if (type === 'warning') {
        icon = '⚠️';
        bgClasses = 'bg-amber-50 text-amber-900 border-amber-200';
    }
    toast.className += ` ${bgClasses}`;

    toast.innerHTML = `
        <span class="text-sm shrink-0 select-none">${icon}</span>
        <span class="flex-1 leading-snug">${escapeHtml(message)}</span>
        <button class="text-slate-400 hover:text-slate-600 font-bold px-1 cursor-pointer" title="Dismiss">✕</button>
    `;

    const closeBtn = toast.querySelector('button');
    const dismiss = () => {
        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 250);
    };

    closeBtn.addEventListener('click', dismiss);
    container.appendChild(toast);

    if (duration > 0) {
        setTimeout(dismiss, duration);
    }
}
window.showToast = showToast;

// User Profile Dropdown Helper
function toggleUserDropdown(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    if (userDropdownMenu) {
        userDropdownMenu.classList.toggle('hidden');
    }
}
window.toggleUserDropdown = toggleUserDropdown;

let lockoutTimer = null;
function startLockoutCountdown(totalSeconds) {
    if (lockoutTimer) clearInterval(lockoutTimer);
    const submitBtn = document.getElementById('btn-auth-unlock');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('opacity-50', 'cursor-not-allowed');
    }

    let remaining = totalSeconds;
    if (authLockoutBanner) {
        authLockoutBanner.classList.remove('hidden');
    }

    const updateMsg = () => {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
        if (authLockoutBanner) {
            authLockoutBanner.textContent = `Too many failed attempts. Login locked for ${timeStr}.`;
        }
    };

    updateMsg();

    lockoutTimer = setInterval(() => {
        remaining--;
        if (remaining <= 0) {
            clearInterval(lockoutTimer);
            lockoutTimer = null;
            if (authLockoutBanner) authLockoutBanner.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        } else {
            updateMsg();
        }
    }, 1000);
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const username = authUsernameInput ? authUsernameInput.value.trim() : '';
    const password = authPasswordInput ? authPasswordInput.value.trim() : '';
    if (!username || !password) return;

    if (authErrorMsg) authErrorMsg.classList.add('hidden');
    const submitBtn = document.getElementById('btn-auth-unlock');
    if (submitBtn) submitBtn.disabled = true;
    if (authBtnText) authBtnText.textContent = 'Signing in...';
    if (authBtnSpinner) authBtnSpinner.classList.remove('hidden');

    try {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (!res.ok) {
            const err = await res.json();
            if (res.status === 429) {
                const retryAfter = parseInt(res.headers.get('Retry-After') || '300');
                startLockoutCountdown(retryAfter);
                return;
            }
            clearSession();
            throw new Error(err.detail || 'Invalid username or password.');
        }

        const data = await res.json();
        sessionStorage.setItem('qb_token', data.token);
        sessionStorage.setItem('qb_user', JSON.stringify(data.user));
        state.currentUser = data.user;

        hideAuthOverlay();
        updateUserProfileUI();
        resetInactivityTimer();

        await loadMetadata();
        await loadQuestions();
    } catch (err) {
        clearSession();
        if (authErrorMsg) {
            authErrorMsg.textContent = err.message || 'Invalid username or password.';
            authErrorMsg.classList.remove('hidden');
        }
    } finally {
        if (submitBtn && !lockoutTimer) {
            submitBtn.disabled = false;
        }
        if (authBtnText) authBtnText.textContent = 'Sign In';
        if (authBtnSpinner) authBtnSpinner.classList.add('hidden');
    }
}

async function performLogout(askConfirm = true) {
    if (askConfirm && !confirm("Are you sure you want to log out of Squire Way Question Bank?")) return;
    const token = sessionStorage.getItem('qb_token');
    if (token) {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        } catch (e) {}
    }
    clearSession();
    showAuthOverlay();
}
window.performLogout = performLogout;

function applyRoleVisibility() {
    const isAdmin = state.currentUser && state.currentUser.role === 'admin';
    document.querySelectorAll('.admin-only').forEach(el => {
        if (isAdmin) {
            el.classList.remove('hidden');
        } else {
            el.classList.add('hidden');
        }
    });
}

function updateUserProfileUI() {
    const user = state.currentUser;
    if (!user) {
        if (userProfileContainer) userProfileContainer.classList.add('hidden');
        return;
    }

    if (userProfileContainer) userProfileContainer.classList.remove('hidden');

    const firstLetter = (user.display_name || user.username || 'U').charAt(0).toUpperCase();
    const isAdmin = user.role === 'admin';

    // Unified Profile Pill (Desktop & Mobile)
    if (userAvatar) userAvatar.textContent = firstLetter;
    if (userDisplayName) userDisplayName.textContent = user.display_name || user.username;
    if (userRoleBadge) {
        userRoleBadge.textContent = isAdmin ? 'Admin' : 'Teacher';
        userRoleBadge.className = `hidden sm:inline-block px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider ${
            isAdmin ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300' : 'bg-brand-100 dark:bg-brand-900/40 text-brand-800 dark:text-brand-300'
        }`;
    }
    if (dropdownUsername) dropdownUsername.textContent = `@${user.username}`;
    if (dropdownRole) dropdownRole.textContent = isAdmin ? '👑 Administrator' : '🎓 Teacher';

    const mobProfileLabel = document.getElementById('mob-nav-profile-label');
    if (mobProfileLabel) {
        mobProfileLabel.textContent = (user.display_name || user.username || 'Account').split(' ')[0];
    }

    updateThemeUI();
    applyRoleVisibility();
}

// ================= Theme & Appearance (Light / Dark / System) =================
function initTheme() {
    applyThemeToHtml(state.theme);
    updateThemeUI();
    if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
            if (state.theme === 'system') {
                applyThemeToHtml('system');
                updateThemeUI();
            }
        });
    }
}

function applyThemeToHtml(theme) {
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (theme === 'dark' || (theme === 'system' && prefersDark)) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
}

function setTheme(theme) {
    state.theme = theme;
    localStorage.setItem('qb_theme', theme);
    applyThemeToHtml(theme);
    updateThemeUI();
    showToast(`Theme switched to ${theme.charAt(0).toUpperCase() + theme.slice(1)}`, "info");
}

function updateThemeUI() {
    if (!themeActiveLabel) return;
    themeActiveLabel.textContent = state.theme;

    const themeButtons = [
        { btn: themeBtnLight, key: 'light' },
        { btn: themeBtnDark, key: 'dark' },
        { btn: themeBtnSystem, key: 'system' }
    ];

    themeButtons.forEach(({ btn, key }) => {
        if (!btn) return;
        if (state.theme === key) {
            btn.className = "theme-choice-btn flex items-center justify-center space-x-1 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer bg-white dark:bg-slate-800 text-brand-700 dark:text-brand-300 shadow-xs border border-brand-200/60 dark:border-brand-800/60";
        } else {
            btn.className = "theme-choice-btn flex items-center justify-center space-x-1 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white";
        }
    });
}

// ================= View Density (Comfortable vs Compact) =================
function initDensity() {
    updateDensityUI();
}

function setDensity(mode) {
    state.density = mode;
    localStorage.setItem('qb_density', mode);
    updateDensityUI();
    if (state.currentQuestions && state.currentQuestions.length > 0) {
        renderQuestions({ items: state.currentQuestions, total: statTotal ? statTotal.textContent : 0 });
    }
    showToast(`View density set to ${mode.charAt(0).toUpperCase() + mode.slice(1)}`, "info");
}

function updateDensityUI() {
    if (!densityComfortableBtn || !densityCompactBtn) return;
    if (state.density === 'compact') {
        densityCompactBtn.className = "px-2.5 py-1.5 rounded-lg text-xs font-bold flex items-center space-x-1 transition-all cursor-pointer bg-white dark:bg-slate-800 text-brand-700 dark:text-brand-300 shadow-xs border border-brand-200/60 dark:border-brand-800/60";
        densityComfortableBtn.className = "px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center space-x-1 transition-all cursor-pointer text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white";
    } else {
        densityComfortableBtn.className = "px-2.5 py-1.5 rounded-lg text-xs font-bold flex items-center space-x-1 transition-all cursor-pointer bg-white dark:bg-slate-800 text-brand-700 dark:text-brand-300 shadow-xs border border-brand-200/60 dark:border-brand-800/60";
        densityCompactBtn.className = "px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center space-x-1 transition-all cursor-pointer text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white";
    }
}

// ================= Quick Copy Question =================
window.copyQuestionText = async function(id) {
    const q = state.currentQuestions.find(item => item.id === id);
    if (!q || !q.question_text) return;
    try {
        await navigator.clipboard.writeText(q.question_text);
        showToast("Question copied to clipboard!", "success");
    } catch (err) {
        showToast("Failed to copy question text", "error");
    }
};

// User Management Modal Handlers
async function openUserMgmtModal() {
    if (state.currentUser?.role !== 'admin') return;
    if (createUserMsg) createUserMsg.classList.add('hidden');
    if (createUserForm) createUserForm.reset();
    if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
    if (userMgmtModal) userMgmtModal.classList.remove('hidden');
    await loadUsersList();
}

function closeUserMgmtModal() {
    if (userMgmtModal) userMgmtModal.classList.add('hidden');
}
window.openUserMgmtModal = openUserMgmtModal;
window.closeUserMgmtModal = closeUserMgmtModal;

async function loadUsersList() {
    if (!userMgmtTableBody) return;
    userMgmtTableBody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-slate-400">Loading registered accounts...</td></tr>`;
    try {
        const res = await apiFetch('/api/admin/users');
        if (!res.ok) throw new Error("Failed to load users");
        const users = await res.json();

        userMgmtTableBody.innerHTML = users.map(u => {
            const isSelf = state.currentUser && state.currentUser.id === u.id;
            const isAdmin = u.role === 'admin';
            const createdDate = u.created_at ? u.created_at.split('T')[0] : '-';
            return `
                <tr class="hover:bg-slate-50 transition-colors">
                    <td class="p-3">
                        <div class="font-bold text-slate-800">${escapeHtml(u.display_name)}</div>
                        <div class="text-[11px] text-slate-400">@${escapeHtml(u.username)}</div>
                    </td>
                    <td class="p-3">
                        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                            isAdmin ? 'bg-amber-100 text-amber-800' : 'bg-brand-100 text-brand-800'
                        }">
                            ${isAdmin ? '👑 Admin' : '🎓 Teacher'}
                        </span>
                    </td>
                    <td class="p-3 text-slate-500">${createdDate}</td>
                    <td class="p-3 text-right space-x-1.5 whitespace-nowrap">
                        <button onclick="handleResetUserPasswordPrompt(${u.id}, '${escapeHtml(u.username)}')" class="px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer">
                            Reset Pass
                        </button>
                        ${!isSelf ? `
                            <button onclick="handleDeleteUser(${u.id}, '${escapeHtml(u.username)}')" class="px-2.5 py-1 rounded-lg text-xs font-semibold bg-rose-50 hover:bg-rose-100 text-rose-600 border border-rose-200 cursor-pointer">
                                Delete
                            </button>
                        ` : `
                            <span class="text-[10px] text-slate-400 italic">You</span>
                        `}
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        userMgmtTableBody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-rose-600">Error loading users: ${escapeHtml(err.message)}</td></tr>`;
    }
}

async function handleCreateUserSubmit(e) {
    e.preventDefault();
    const username = newUsernameInput.value.trim();
    const displayName = newDisplayNameInput.value.trim();
    const password = newPasswordInput.value.trim();
    const role = newUserRoleSelect.value;

    if (!username || !displayName || !password) return;

    try {
        const res = await apiFetch('/api/admin/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username,
                display_name: displayName,
                password,
                role
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to create user');
        }

        createUserMsg.className = 'text-xs p-2.5 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200 block';
        createUserMsg.textContent = `Account created successfully for @${username}!`;
        createUserForm.reset();
        await loadUsersList();
    } catch (err) {
        createUserMsg.className = 'text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block';
        createUserMsg.textContent = 'Error: ' + err.message;
    }
}

window.handleResetUserPasswordPrompt = async function(userId, username) {
    const newPass = prompt(`Enter new password for @${username} (min 4 characters):`);
    if (!newPass) return;
    if (newPass.length < 4) {
        showToast("Password must be at least 4 characters long.", "warning");
        return;
    }

    try {
        const res = await apiFetch(`/api/admin/users/${userId}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: newPass })
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to reset password');
        }
        showToast(`Password for @${username} has been reset successfully!`, "success");
    } catch (err) {
        showToast("Error resetting password: " + err.message, "error");
    }
};

window.handleDeleteUser = async function(userId, username) {
    if (!confirm(`Are you sure you want to permanently delete account @${username}?`)) return;

    try {
        const res = await apiFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to delete user');
        }
        showToast(`Account @${username} deleted successfully`, "info");
        await loadUsersList();
    } catch (err) {
        showToast("Error deleting user: " + err.message, "error");
    }
};

// Change Password Modal Handlers
function openChangePasswordModal() {
    if (changePwdForm) changePwdForm.reset();
    if (changePwdMsg) changePwdMsg.classList.add('hidden');
    if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
    if (changePasswordModal) changePasswordModal.classList.remove('hidden');
}

function closeChangePasswordModal() {
    if (changePasswordModal) changePasswordModal.classList.add('hidden');
}
window.openChangePasswordModal = openChangePasswordModal;
window.closeChangePasswordModal = closeChangePasswordModal;

async function handleChangePasswordSubmit(e) {
    e.preventDefault();
    const oldPass = oldPwdInput.value;
    const newPass = newPwdInput.value;
    const confirmPass = confirmNewPwdInput.value;

    if (newPass !== confirmPass) {
        changePwdMsg.className = 'text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block';
        changePwdMsg.textContent = 'New passwords do not match.';
        return;
    }
    if (newPass.length < 4) {
        changePwdMsg.className = 'text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block';
        changePwdMsg.textContent = 'New password must be at least 4 characters.';
        return;
    }

    try {
        const res = await apiFetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPass, new_password: newPass })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to change password');
        }

        changePwdMsg.className = 'text-xs p-2.5 rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200 block';
        changePwdMsg.textContent = 'Password changed successfully!';
        setTimeout(() => {
            closeChangePasswordModal();
        }, 1200);
    } catch (err) {
        changePwdMsg.className = 'text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block';
        changePwdMsg.textContent = 'Error: ' + err.message;
    }
}

async function handleBackupLibrary() {
    try {
        const token = sessionStorage.getItem('qb_token');
        const url = token ? `/api/backup?auth_token=${encodeURIComponent(token)}` : '/api/backup';
        showToast("Generating library backup...", "info", 2000);
        window.location.href = url;
    } catch (e) {
        showToast("Failed to download backup: " + e.message, "error");
    }
}

async function handleFullSystemBackup() {
    try {
        const token = sessionStorage.getItem('qb_token');
        const url = token ? `/api/admin/backup?auth_token=${encodeURIComponent(token)}` : '/api/admin/backup';
        showToast("Generating complete disaster recovery system backup...", "info", 2500);
        window.location.href = url;
    } catch (e) {
        showToast("Failed to download system backup: " + e.message, "error");
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
    showToast("Restoring question bank from file...", "info", 2500);

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
        showToast(result.message || "Library restored successfully!", "success");
        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);
    } catch (err) {
        showToast(`Error restoring backup: ${err.message}`, "error");
    }
}

// Mobile Bottom Navigation Dock Controller
function initMobileBottomDock() {
    const mobNavBank = document.getElementById('mob-nav-bank');
    const mobNavCart = document.getElementById('mob-nav-cart');
    const mobNavExams = document.getElementById('mob-nav-exams');
    const mobNavProfile = document.getElementById('mob-nav-profile');

    if (mobNavBank) {
        mobNavBank.addEventListener('click', () => {
            triggerHaptic('light');
            window.location.hash = '#bank';
        });
    }

    if (mobNavCart) {
        mobNavCart.addEventListener('click', () => {
            triggerHaptic('light');
            openCart();
        });
    }

    if (mobNavExams) {
        mobNavExams.addEventListener('click', () => {
            triggerHaptic('light');
            window.location.hash = '#exams';
        });
    }

    if (mobNavProfile) {
        mobNavProfile.addEventListener('click', () => {
            triggerHaptic('light');
            const profileBtn = document.getElementById('user-profile-btn');
            if (profileBtn) {
                profileBtn.click();
            }
        });
    }

    // Auto-hide mobile dock when on-screen keyboard is visible
    if (window.visualViewport) {
        let initialHeight = window.visualViewport.height;
        window.visualViewport.addEventListener('resize', () => {
            const dock = document.getElementById('mobile-bottom-dock');
            if (!dock) return;
            // When virtual keyboard opens on mobile, height drops significantly (> 150px)
            if (window.visualViewport.height < initialHeight - 150) {
                dock.classList.add('translate-y-full');
            } else {
                dock.classList.remove('translate-y-full');
            }
        });
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    initDensity();
    setupEventListeners();
    setupInactivityListeners();
    initMobileBottomDock();
    updateCartBadge();
    const isAuthed = await checkAuthStatus();
    if (isAuthed) {
        updateUserProfileUI();
        loadMetadata();
        loadQuestions();
        resetInactivityTimer();
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

    // Backup & Restore Events (Inside User Dropdown)
    const btnFullSystemBackup = document.getElementById('btn-full-system-backup');
    if (btnFullSystemBackup) {
        btnFullSystemBackup.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            handleFullSystemBackup();
        });
    }
    if (btnBackupLibrary) {
        btnBackupLibrary.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            handleBackupLibrary();
        });
    }
    if (btnRestoreLibrary) {
        btnRestoreLibrary.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            if (restoreFileInput) {
                restoreFileInput.value = '';
                restoreFileInput.click();
            }
        });
    }
    if (restoreFileInput) restoreFileInput.addEventListener('change', handleRestoreFileSelected);

    // User Profile Dropdown Events (Unified Desktop & Mobile)
    if (userProfileBtn && userDropdownMenu) {
        userProfileBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            userDropdownMenu.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!userDropdownMenu.contains(e.target) && !userProfileBtn.contains(e.target)) {
                userDropdownMenu.classList.add('hidden');
            }
        });
    }

    if (btnOpenManageUsers) {
        btnOpenManageUsers.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            openUserMgmtModal();
        });
    }
    if (btnOpenChangePassword) {
        btnOpenChangePassword.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            openChangePasswordModal();
        });
    }
    if (btnLogout) {
        btnLogout.addEventListener('click', (e) => {
            e.stopPropagation();
            if (userDropdownMenu) userDropdownMenu.classList.add('hidden');
            performLogout(true);
        });
    }

    // User Management Modal Events
    if (closeUserMgmtBtn) closeUserMgmtBtn.addEventListener('click', closeUserMgmtModal);
    if (userMgmtModal) {
        userMgmtModal.addEventListener('click', (e) => {
            if (e.target === userMgmtModal) closeUserMgmtModal();
        });
    }
    if (createUserForm) createUserForm.addEventListener('submit', handleCreateUserSubmit);

    // Change Password Modal Events
    if (closeChangePwdBtn) closeChangePwdBtn.addEventListener('click', closeChangePasswordModal);
    if (cancelChangePwdBtn) cancelChangePwdBtn.addEventListener('click', closeChangePasswordModal);
    if (changePasswordModal) {
        changePasswordModal.addEventListener('click', (e) => {
            if (e.target === changePasswordModal) closeChangePasswordModal();
        });
    }
    if (changePwdForm) changePwdForm.addEventListener('submit', handleChangePasswordSubmit);

    // Global Escape Key to dismiss modals / dropdowns
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (userDropdownMenu && !userDropdownMenu.classList.contains('hidden')) {
                userDropdownMenu.classList.add('hidden');
            }
            if (userMgmtModal && !userMgmtModal.classList.contains('hidden')) {
                closeUserMgmtModal();
            }
            if (changePasswordModal && !changePasswordModal.classList.contains('hidden')) {
                closeChangePasswordModal();
            }
        }
    });

    // Toggle Login Password Visibility
    if (btnToggleLoginPwd && authPasswordInput) {
        btnToggleLoginPwd.addEventListener('click', () => {
            const isPassword = authPasswordInput.type === 'password';
            authPasswordInput.type = isPassword ? 'text' : 'password';
            btnToggleLoginPwd.textContent = isPassword ? '🙈' : '👁️';
        });
    }

    // Mobile Collapsible Filters Events
    if (toggleFiltersBtn && filtersContainer) {
        toggleFiltersBtn.addEventListener('click', () => {
            filtersContainer.classList.toggle('hidden');
        });
    }

    // Theme Switcher Click Events
    if (themeBtnLight) themeBtnLight.addEventListener('click', () => setTheme('light'));
    if (themeBtnDark) themeBtnDark.addEventListener('click', () => setTheme('dark'));
    if (themeBtnSystem) themeBtnSystem.addEventListener('click', () => setTheme('system'));

    // View Density Switcher Click Events
    if (densityComfortableBtn) densityComfortableBtn.addEventListener('click', () => setDensity('comfortable'));
    if (densityCompactBtn) densityCompactBtn.addEventListener('click', () => setDensity('compact'));

    const updateFiltersBadge = () => {
        let count = 0;
        if (filterSubject && filterSubject.value) count++;
        if (filterTopic && filterTopic.value) count++;
        if (filterSource && filterSource.value) count++;
        if (activeFiltersBadge) {
            if (count > 0) {
                activeFiltersBadge.textContent = count;
                activeFiltersBadge.classList.remove('hidden');
            } else {
                activeFiltersBadge.classList.add('hidden');
            }
        }
    };
    filterSubject.addEventListener('change', updateFiltersBadge);
    filterTopic.addEventListener('change', updateFiltersBadge);
    filterSource.addEventListener('change', updateFiltersBadge);

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
        showToast("Please select valid Word (.docx) or PDF (.pdf) files.", "warning");
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

        // Invalidate page cache and refresh library and metadata
        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);

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

        if (statTotal) statTotal.textContent = data.total_unique || 0;
        if (statMerged) statMerged.textContent = data.merged_duplicates || 0;

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

function renderSkeletonCards(count = 4) {
    if (!questionsContainer) return;
    questionsContainer.innerHTML = Array.from({ length: count }).map(() => `
        <div class="bg-white p-4 sm:p-5 rounded-2xl border border-slate-200/80 shadow-xs space-y-3">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <div class="w-4 h-4 rounded skeleton-shimmer"></div>
                    <div class="w-16 h-5 rounded-md skeleton-shimmer"></div>
                    <div class="w-20 h-5 rounded-md skeleton-shimmer"></div>
                </div>
                <div class="w-12 h-4 rounded skeleton-shimmer"></div>
            </div>
            <div class="space-y-2">
                <div class="w-full h-4 rounded skeleton-shimmer"></div>
                <div class="w-3/4 h-4 rounded skeleton-shimmer"></div>
            </div>
            <div class="flex justify-between items-center pt-2">
                <div class="w-24 h-4 rounded skeleton-shimmer"></div>
                <div class="flex space-x-2">
                    <div class="w-14 h-7 rounded-lg skeleton-shimmer"></div>
                    <div class="w-14 h-7 rounded-lg skeleton-shimmer"></div>
                </div>
            </div>
        </div>
    `).join('');
}

// Load Questions List with Client-Side Page Caching
async function loadQuestions(skipCache = false) {
    const cacheKey = getPageCacheKey(state.currentPage, state.limit, state.filters);

    if (!skipCache && state.pageCache.has(cacheKey)) {
        const cached = state.pageCache.get(cacheKey);
        state.currentQuestions = cached.items;
        state.totalPages = Math.max(1, Math.ceil(cached.total / state.limit));
        renderQuestions(cached);
        return;
    }

    renderSkeletonCards(4);

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

        // Save into LRU in-memory page cache
        if (state.pageCache.size >= state.maxCacheEntries) {
            const firstKey = state.pageCache.keys().next().value;
            state.pageCache.delete(firstKey);
        }
        state.pageCache.set(cacheKey, data);

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
            <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200/80 dark:border-slate-700/80 p-12 text-center text-slate-400 space-y-3">
                <div class="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-700/60 mx-auto flex items-center justify-center text-slate-400">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                </div>
                <h3 class="font-bold text-slate-700 dark:text-slate-200 text-base">No questions found</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto">Upload Word (.docx) or PDF question banks above or try a different search filter.</p>
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
    prevPageBtn.className = state.currentPage <= 1 ? "px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-medium text-slate-400 dark:text-slate-500 cursor-not-allowed" : "px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer";
    nextPageBtn.className = state.currentPage >= state.totalPages ? "px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-medium text-slate-400 dark:text-slate-500 cursor-not-allowed" : "px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer";

    const isCompact = state.density === 'compact';

    questionsContainer.innerHTML = data.items.map((q) => {
        const inCart = isQuestionInCart(q.id);
        const freq = q.frequency || 1;
        const isRepeated = freq > 1;
        const isSelected = state.selectedIds.has(q.id);

        if (isCompact) {
            // Compact Dense Row Layout
            return `
                <div data-id="${q.id}" class="question-card compact-view bg-white dark:bg-slate-800 p-3 sm:py-2.5 sm:px-4 rounded-xl border ${isSelected ? 'border-brand-500 bg-brand-50/20 dark:bg-brand-950/20 ring-1 ring-brand-500' : 'border-slate-200/80 dark:border-slate-700/80'} shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 transition-all">
                    <div class="flex items-center space-x-3 flex-1 min-w-0">
                        <input type="checkbox" onchange="toggleSelectQuestion(${q.id}, this.checked)" ${isSelected ? 'checked' : ''} class="w-4 h-4 rounded text-brand-600 focus:ring-brand-500 cursor-pointer shrink-0" title="Select question">
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-1.5 flex-wrap mb-0.5">
                                ${isRepeated ? `<span class="inline-flex items-center text-[10px] font-bold px-1.5 py-0.2 rounded-full high-frequency-badge">🔥 ${freq}x</span>` : ''}
                                ${q.subject ? `<span class="inline-flex items-center text-[10px] font-semibold px-2 py-0.2 rounded-full bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 border border-brand-100 dark:border-brand-800/60">📚 ${escapeHtml(q.subject)}</span>` : ''}
                                ${q.topic ? `<span class="inline-flex items-center text-[10px] font-medium px-1.5 py-0.2 rounded-full bg-slate-100 dark:bg-slate-700/60 text-slate-600 dark:text-slate-300">🏷️ ${escapeHtml(q.topic)}</span>` : ''}
                            </div>
                            <p onclick="this.closest('.question-card').classList.toggle('expanded')" class="question-body text-xs font-medium text-slate-900 dark:text-slate-100 cursor-pointer hover:text-brand-600 dark:hover:text-brand-400" title="Click to expand/collapse full question">
                                ${escapeHtml(q.question_text)}
                            </p>
                        </div>
                    </div>

                    <!-- Compact Action Buttons -->
                    <div class="flex items-center space-x-1 shrink-0 justify-end pt-1 sm:pt-0 border-t sm:border-t-0 border-slate-100 dark:border-slate-700/60">
                        <button onclick="toggleCartQuestion(${q.id})" class="inline-flex items-center space-x-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                            inCart
                                ? 'bg-emerald-600 text-white'
                                : 'bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 hover:bg-brand-600 hover:text-white'
                        }" title="${inCart ? 'Remove from Cart' : 'Add to Cart'}">
                            <span>${inCart ? '✓ In Cart' : '+ Cart'}</span>
                        </button>
                        <button onclick="copyQuestionText(${q.id})" class="p-1.5 rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer text-xs" title="Copy question text">
                            📋
                        </button>
                        <button onclick="downloadSingleQuestion(${q.id}, 'docx')" class="p-1.5 rounded-lg text-slate-500 hover:text-brand-600 dark:text-slate-400 dark:hover:text-brand-400 hover:bg-brand-50 dark:hover:bg-brand-900/30 transition-colors cursor-pointer text-xs" title="Download Word (.docx)">
                            📄
                        </button>
                        <button onclick="downloadSingleQuestion(${q.id}, 'pdf')" class="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30 transition-colors cursor-pointer text-xs" title="Download PDF (.pdf)">
                            📕
                        </button>
                        <button onclick="openEditModal(${q.id})" class="p-1.5 rounded-lg text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer text-xs" title="Edit Question">
                            ✏️
                        </button>
                        ${(state.currentUser && state.currentUser.role === 'admin') ? `
                        <button onclick="deleteQuestion(${q.id})" class="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 dark:text-slate-400 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30 transition-colors cursor-pointer text-xs" title="Delete Question">
                            🗑️
                        </button>
                        ` : ''}
                    </div>
                </div>
            `;
        }

        // Comfortable Academic Card Layout
        return `
            <div data-id="${q.id}" class="question-card bg-white dark:bg-slate-800 p-5 rounded-2xl border ${isSelected ? 'border-brand-500 bg-brand-50/20 dark:bg-brand-950/20 ring-1 ring-brand-500' : 'border-slate-200/80 dark:border-slate-700/80'} shadow-sm flex flex-col md:flex-row md:items-start justify-between gap-4 transition-all">
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
                                <span class="inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700/60 text-slate-600 dark:text-slate-300">
                                    Appeared 1x
                                </span>
                            `}

                            ${q.subject ? `
                                <span class="inline-flex items-center text-xs font-semibold px-2.5 py-0.5 rounded-full bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 border border-brand-100 dark:border-brand-800/60">
                                    📚 ${escapeHtml(q.subject)}
                                </span>
                            ` : ''}

                            ${q.topic ? `
                                <span class="inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700/60 text-slate-600 dark:text-slate-300">
                                    🏷️ ${escapeHtml(q.topic)}
                                </span>
                            ` : ''}

                            ${q.sources && q.sources.length ? `
                                <span class="inline-flex items-center text-[11px] text-slate-400 dark:text-slate-500 px-1.5 py-0.5" title="Found in: ${escapeHtml(q.sources.join(', '))}">
                                    📄 ${q.sources.length} source file(s)
                                </span>
                            ` : ''}
                        </div>

                        <!-- Question Text -->
                        <p class="text-sm font-medium text-slate-900 dark:text-slate-100 leading-relaxed pt-1">
                            ${escapeHtml(q.question_text)}
                        </p>
                    </div>
                </div>

                <!-- Action Buttons: Responsive 2-Tier on Mobile, Single Row on Desktop -->
                <div class="w-full sm:w-auto flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-2 shrink-0 pt-2.5 sm:pt-0 border-t sm:border-t-0 border-slate-100 dark:border-slate-700/60">
                    <!-- Primary Actions (Add to Cart & Quick Exports) -->
                    <div class="flex items-center space-x-2 w-full sm:w-auto">
                        <button onclick="toggleCartQuestion(${q.id})" class="flex-1 sm:flex-none inline-flex items-center justify-center space-x-1.5 px-3.5 py-2 sm:py-1.5 rounded-xl text-xs font-bold transition-all min-h-[38px] sm:min-h-0 cursor-pointer ${
                            inCart
                                ? 'bg-emerald-600 text-white shadow-sm hover:bg-emerald-700'
                                : 'bg-brand-50 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 border border-brand-200 dark:border-brand-800 hover:bg-brand-600 dark:hover:bg-brand-600 hover:text-white'
                        }">
                            ${inCart ? '✓ In Cart' : '+ Add to Cart'}
                        </button>
                        
                        <!-- Quick Download Word / PDF & Copy options on Question Card -->
                        <div class="flex items-center space-x-1 border-l border-slate-200 dark:border-slate-700 pl-2">
                            <button onclick="copyQuestionText(${q.id})" class="px-2.5 py-2 sm:py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-brand-600 dark:hover:text-brand-400 hover:bg-brand-50 dark:hover:bg-brand-900/30 transition-colors flex items-center space-x-1 cursor-pointer min-h-[38px] sm:min-h-0" title="Copy question text to clipboard">
                                <span>📋 Copy</span>
                            </button>
                            <button onclick="downloadSingleQuestion(${q.id}, 'docx')" class="px-2.5 py-2 sm:py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-brand-600 dark:hover:text-brand-400 hover:bg-brand-50 dark:hover:bg-brand-900/30 transition-colors flex items-center space-x-1 cursor-pointer min-h-[38px] sm:min-h-0" title="Download this question as Word (.docx)">
                                <span>📄 Word</span>
                            </button>
                            <button onclick="downloadSingleQuestion(${q.id}, 'pdf')" class="px-2.5 py-2 sm:py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30 transition-colors flex items-center space-x-1 cursor-pointer min-h-[38px] sm:min-h-0" title="Download this question as PDF (.pdf)">
                                <span>📕 PDF</span>
                            </button>
                        </div>
                    </div>

                    <!-- Secondary Actions (Edit & Delete) -->
                    <div class="flex items-center justify-end space-x-2 sm:space-x-1 sm:border-l sm:border-slate-200 sm:dark:border-slate-700 sm:pl-2">
                        <button onclick="openEditModal(${q.id})" class="inline-flex items-center space-x-1 px-2.5 py-1.5 sm:p-1.5 rounded-lg text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer text-xs sm:text-inherit" title="Edit Question">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                            </svg>
                            <span class="sm:hidden font-medium">Edit</span>
                        </button>
                        ${(state.currentUser && state.currentUser.role === 'admin') ? `
                        <button onclick="deleteQuestion(${q.id})" class="inline-flex items-center space-x-1 px-2.5 py-1.5 sm:p-1.5 rounded-lg text-slate-500 dark:text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30 transition-colors cursor-pointer text-xs sm:text-inherit" title="Delete Question">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            <span class="sm:hidden font-medium">Delete</span>
                        </button>
                        ` : ''}
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
            card.classList.add('border-brand-500', 'bg-brand-50/20', 'dark:bg-brand-950/20', 'ring-1', 'ring-brand-500');
            card.classList.remove('border-slate-200/80', 'dark:border-slate-700/80');
        } else {
            card.classList.remove('border-brand-500', 'bg-brand-50/20', 'dark:bg-brand-950/20', 'ring-1', 'ring-brand-500');
            card.classList.add('border-slate-200/80', 'dark:border-slate-700/80');
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
    const isAdmin = state.currentUser && state.currentUser.role === 'admin';

    if (bulkDeleteBtn) {
        if (isAdmin) {
            bulkDeleteBtn.classList.remove('hidden');
        } else {
            bulkDeleteBtn.classList.add('hidden');
        }
        bulkDeleteBtn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            <span>Delete Selected (${count})</span>
        `;
    }
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

        showToast(`Successfully deleted ${ids.length} questions`, "info");
        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);

    } catch (err) {
        showToast("Error deleting questions: " + err.message, "error");
    } finally {
        bulkDeleteBtn.disabled = false;
        updateBulkActionBar();
    }
}

function handleBulkAddToCart() {
    const ids = Array.from(state.selectedIds);
    if (ids.length === 0) return;

    let addedCount = 0;
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
                addedCount++;
            }
        }
    });

    saveCart();
    state.selectedIds.clear();
    updateBulkActionBar();
    renderQuestions({ items: state.currentQuestions, total: statTotal.textContent });
    showToast(`Added ${addedCount} questions to Question Cart`, "success");
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

    // Synchronize mobile bottom dock cart badge
    const mobCartBadge = document.getElementById('mob-cart-badge');
    if (mobCartBadge) {
        mobCartBadge.textContent = state.cart.length;
        if (state.cart.length > 0) {
            mobCartBadge.classList.remove('hidden');
        } else {
            mobCartBadge.classList.add('hidden');
        }
    }
}

window.toggleCartQuestion = function(id) {
    const existingIndex = state.cart.findIndex(item => item.id === id);
    if (existingIndex > -1) {
        state.cart.splice(existingIndex, 1);
        triggerHaptic('medium');
        showToast("Removed from Question Cart", "info", 2000);
    } else {
        const question = state.currentQuestions.find(q => q.id === id);
        if (question) {
            state.cart.push({
                id: question.id,
                question_text: question.question_text,
                subject: question.subject,
                topic: question.topic
            });
            triggerHaptic('light');
            showToast("Added to Question Cart", "success", 2000);
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
    if (addedCount > 0) {
        showToast(`Added ${addedCount} page questions to Question Cart`, "success");
    } else {
        showToast("All questions on this page are already in your cart", "info");
    }
}

function openCart() {
    triggerHaptic('light');
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
        triggerHaptic('medium');
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
        exportDocxBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-slate-200 dark:bg-slate-700 text-slate-400 dark:text-slate-500 font-bold py-3 rounded-xl cursor-not-allowed transition-all text-xs sm:text-sm";
        exportPdfBtn.disabled = true;
        exportPdfBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-slate-200 dark:bg-slate-700 text-slate-400 dark:text-slate-500 font-bold py-3 rounded-xl cursor-not-allowed transition-all text-xs sm:text-sm";
        return;
    }

    exportDocxBtn.disabled = false;
    exportDocxBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-brand-600 hover:bg-brand-700 text-white font-bold py-3 rounded-xl transition-all shadow-md shadow-brand-500/25 active:scale-[0.98] cursor-pointer text-xs sm:text-sm";
    exportPdfBtn.disabled = false;
    exportPdfBtn.className = "w-full flex items-center justify-center space-x-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold py-3 rounded-xl transition-all shadow-md shadow-rose-600/25 active:scale-[0.98] cursor-pointer text-xs sm:text-sm";

    cartItemsContainer.innerHTML = state.cart.map((item, index) => `
        <div class="bg-slate-50 dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/80 rounded-xl p-3 flex items-start justify-between gap-3 shadow-xs">
            <div class="flex items-start space-x-2 flex-1">
                <span class="w-5 h-5 rounded-full bg-brand-100 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
                    ${index + 1}
                </span>
                <p class="text-xs text-slate-800 dark:text-slate-100 leading-snug line-clamp-3">
                    ${escapeHtml(item.question_text)}
                </p>
            </div>

            <!-- Controls: Move Up, Move Down, Remove with comfortable touch targets -->
            <div class="flex items-center space-x-1 shrink-0">
                <button onclick="moveCartItem(${index}, -1)" ${index === 0 ? 'disabled' : ''} class="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-100 hover:bg-slate-200/60 dark:hover:bg-slate-700/60 disabled:opacity-20 disabled:hover:text-slate-400 cursor-pointer" title="Move Up">
                    ▲
                </button>
                <button onclick="moveCartItem(${index}, 1)" ${index === state.cart.length - 1 ? 'disabled' : ''} class="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-100 hover:bg-slate-200/60 dark:hover:bg-slate-700/60 disabled:opacity-20 disabled:hover:text-slate-400 cursor-pointer" title="Move Down">
                    ▼
                </button>
                <button onclick="removeFromCart(${index})" class="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 dark:text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 font-bold ml-0.5 cursor-pointer" title="Remove">
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
        styleDefaultBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-bold cursor-pointer transition-all select-none bg-white dark:bg-slate-800 text-brand-700 dark:text-brand-300 shadow-xs border border-brand-200/60 dark:border-brand-800/60";
        styleNormalBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-semibold cursor-pointer transition-all select-none text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white";
        styleDesc.innerHTML = 'Uses your master printout layout: <strong>A4 size, 0.5" margins, double page border, and Times New Roman</strong>.';
    } else {
        styleNormalBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-bold cursor-pointer transition-all select-none bg-white dark:bg-slate-800 text-brand-700 dark:text-brand-300 shadow-xs border border-brand-200/60 dark:border-brand-800/60";
        styleDefaultBtn.className = "flex items-center justify-center space-x-1.5 py-1.5 px-3 rounded-lg text-xs font-semibold cursor-pointer transition-all select-none text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white";
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
        showToast(`Failed to export ${label}: ${err.message}`, "error");
    }
}

// Download a single question directly from its Question Card
window.downloadSingleQuestion = function(id, format) {
    downloadQuestions([id], format, '');
};

// Download all questions currently in the Cart
function exportFromCart(format) {
    if (state.cart.length === 0) {
        showToast("Your cart is empty. Please add questions first.", "info");
        return;
    }
    const questionIds = state.cart.map(item => item.id);
    const title = paperTitleInput.value.trim();
    showToast(`Generating ${format.toUpperCase()} question paper...`, "info", 2000);
    downloadQuestions(questionIds, format, title);
}

// Download all selected questions from Bulk Selection Bar
function handleBulkDownload(format) {
    const ids = Array.from(state.selectedIds);
    if (ids.length === 0) {
        showToast("Please select at least one question first.", "info");
        return;
    }
    showToast(`Generating ${format.toUpperCase()} export...`, "info", 2000);
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
        showToast("Question text cannot be empty.", "warning");
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
        showToast("Question updated successfully", "success");
        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);

        // Also update in cart if present
        const cartIndex = state.cart.findIndex(c => c.id === parseInt(id));
        if (cartIndex > -1) {
            state.cart[cartIndex].question_text = text;
            state.cart[cartIndex].subject = subject;
            state.cart[cartIndex].topic = topic;
            saveCart();
        }

    } catch (err) {
        showToast("Error saving: " + err.message, "error");
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

        showToast("Question deleted from library", "info");
        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);
    } catch (err) {
        showToast("Error deleting question: " + err.message, "error");
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
            showToast("Duplicate merged into existing question frequency", "info");
        } else {
            addModalMsg.className = 'text-xs p-3 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200 block';
            addModalMsg.textContent = 'Question added to library successfully!';
            showToast("Question added to library successfully!", "success");
        }

        clearPageCache();
        await loadMetadata();
        await loadQuestions(true);

        setTimeout(() => {
            closeAddModal();
        }, 1100);

    } catch (err) {
        addModalMsg.className = 'text-xs p-3 rounded-xl bg-rose-50 text-rose-700 border border-rose-200 block';
        addModalMsg.textContent = 'Error: ' + err.message;
        showToast("Error adding question: " + err.message, "error");
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

// ==========================================
// Digital Exams & Evaluation Studio (Feature #5)
// ==========================================

const examsState = {
    currentExams: [],
    activeExamId: null,
    activeSubmissions: [],
    activeSubmissionDetail: null,
    photoZoom: { scale: 1.0, rotation: 0 }
};

// 1. Hash Routing and Tab Switching
function switchView(viewName, param) {
    const navTabBank = document.getElementById('nav-tab-bank');
    const navTabExams = document.getElementById('nav-tab-exams');
    const mobNavBank = document.getElementById('mob-nav-bank');
    const mobNavExams = document.getElementById('mob-nav-exams');
    const bankView = document.getElementById('bank-view');
    const examsView = document.getElementById('exams-view');
    const examsDashView = document.getElementById('exams-dashboard-view');
    const subView = document.getElementById('submissions-subview');

    if (!bankView || !examsView) return;

    if (viewName === 'exams' || viewName === 'submissions') {
        bankView.classList.add('hidden');
        examsView.classList.remove('hidden');

        if (navTabBank && navTabExams) {
            navTabBank.className = "px-3 py-1.5 rounded-lg text-xs font-medium transition-all text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white flex items-center space-x-1.5 cursor-pointer";
            navTabExams.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-brand-700 dark:text-brand-300 bg-white dark:bg-slate-700 shadow-xs flex items-center space-x-1.5 cursor-pointer";
        }
        if (mobNavBank && mobNavExams) {
            mobNavBank.className = "flex flex-col items-center justify-center py-1 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white font-medium pressable cursor-pointer";
            mobNavExams.className = "relative flex flex-col items-center justify-center py-1 text-brand-600 dark:text-brand-400 font-bold pressable cursor-pointer";
        }

        if (viewName === 'submissions' && param) {
            examsDashView?.classList.add('hidden');
            subView?.classList.remove('hidden');
            loadSubmissionsList(param);
        } else {
            subView?.classList.add('hidden');
            examsDashView?.classList.remove('hidden');
            loadExamsList();
        }
    } else {
        examsView.classList.add('hidden');
        bankView.classList.remove('hidden');

        if (navTabBank && navTabExams) {
            navTabBank.className = "px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-brand-700 dark:text-brand-300 bg-white dark:bg-slate-700 shadow-xs flex items-center space-x-1.5 cursor-pointer";
            navTabExams.className = "px-3 py-1.5 rounded-lg text-xs font-medium transition-all text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white flex items-center space-x-1.5 cursor-pointer";
        }
        if (mobNavBank && mobNavExams) {
            mobNavBank.className = "flex flex-col items-center justify-center py-1 text-brand-600 dark:text-brand-400 font-bold pressable cursor-pointer";
            mobNavExams.className = "relative flex flex-col items-center justify-center py-1 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white font-medium pressable cursor-pointer";
        }
    }
}

function handleHashRoute() {
    const hash = window.location.hash || '#bank';
    if (hash.startsWith('#exams/submissions/')) {
        const examId = hash.replace('#exams/submissions/', '');
        switchView('submissions', parseInt(examId));
    } else if (hash.startsWith('#exams')) {
        switchView('exams');
    } else {
        switchView('bank');
    }
}

window.addEventListener('hashchange', handleHashRoute);

// 2. Exam Setup Modal Logic
function openExamSetupModal() {
    if (!state.cart || state.cart.length === 0) {
        showToast("Please add at least 1 question to your cart first.", "warning");
        return;
    }

    // Close cart drawer
    if (typeof closeCart === 'function') closeCart();

    const setupModal = document.getElementById('exam-setup-modal');
    const titleInput = document.getElementById('setup-exam-title');
    const subjInput = document.getElementById('setup-exam-subject');
    const durationInput = document.getElementById('setup-exam-duration');
    const deadlineInput = document.getElementById('setup-exam-deadline');
    const instructionsInput = document.getElementById('setup-exam-instructions');

    // Pre-populate Title
    const paperTitleVal = document.getElementById('paper-title-input')?.value.trim();
    const subjects = state.cart.map(q => q.subject).filter(Boolean);
    const mostFreqSubject = subjects.length ? subjects[0] : "";
    titleInput.value = paperTitleVal || (mostFreqSubject ? `${mostFreqSubject} Examination 2026` : "General Digital Examination");
    subjInput.value = mostFreqSubject || "General";
    durationInput.value = 60;

    // Pre-populate Deadline (Tomorrow at 23:59 local time)
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(23, 59, 0, 0);
    const yyyy = tomorrow.getFullYear();
    const mm = String(tomorrow.getMonth() + 1).padStart(2, '0');
    const dd = String(tomorrow.getDate()).padStart(2, '0');
    const hh = String(tomorrow.getHours()).padStart(2, '0');
    const min = String(tomorrow.getMinutes()).padStart(2, '0');
    deadlineInput.value = `${yyyy}-${mm}-${dd}T${hh}:${min}`;

    if (!instructionsInput.value.trim()) {
        instructionsInput.value = "1. Answer all questions.\n2. You can type answers or upload clear photos of your handwritten sheets.\n3. Verify your answers before submitting. Submission is final.";
    }

    renderSetupMarksAllocation();
    setupModal?.classList.remove('hidden');
}

function renderSetupMarksAllocation() {
    const isCustom = document.getElementById('marks-mode-custom')?.checked;
    const equalContainer = document.getElementById('equal-marks-container');
    const customContainer = document.getElementById('custom-marks-container');
    const totalMarksLabel = document.getElementById('setup-total-marks-label');
    const equalValInput = document.getElementById('setup-equal-marks-val');

    if (isCustom) {
        equalContainer?.classList.add('hidden');
        customContainer?.classList.remove('hidden');

        customContainer.innerHTML = state.cart.map((q, idx) => `
            <div class="flex items-center justify-between text-xs p-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                <span class="font-bold text-slate-500 mr-2 shrink-0">Q${idx + 1}</span>
                <p class="text-slate-800 dark:text-slate-200 truncate flex-1 mr-3">${escapeHtml(q.question_text)}</p>
                <div class="flex items-center space-x-1 shrink-0">
                    <input type="number" min="0.5" step="0.5" value="5" data-idx="${idx}" class="setup-custom-mark-input w-16 text-center text-xs px-2 py-1 rounded border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 font-bold">
                    <span class="text-slate-400">pts</span>
                </div>
            </div>
        `).join('');

        updateCustomTotalMarks();
        customContainer.querySelectorAll('.setup-custom-mark-input').forEach(input => {
            input.addEventListener('input', updateCustomTotalMarks);
        });
    } else {
        customContainer?.classList.add('hidden');
        equalContainer?.classList.remove('hidden');
        const eqVal = parseFloat(equalValInput?.value || 5.0);
        const total = state.cart.length * eqVal;
        if (totalMarksLabel) totalMarksLabel.textContent = total;
    }
}

function updateCustomTotalMarks() {
    const inputs = document.querySelectorAll('.setup-custom-mark-input');
    let total = 0;
    inputs.forEach(inp => {
        total += parseFloat(inp.value || 0);
    });
    const totalMarksLabel = document.getElementById('setup-total-marks-label');
    if (totalMarksLabel) totalMarksLabel.textContent = total;
}

// 3. Publishing Exam to Backend
async function handlePublishExam(e) {
    if (e) e.preventDefault();

    const titleInput = document.getElementById('setup-exam-title');
    const subjInput = document.getElementById('setup-exam-subject');
    const durationInput = document.getElementById('setup-exam-duration');
    const deadlineInput = document.getElementById('setup-exam-deadline');
    const instructionsInput = document.getElementById('setup-exam-instructions');
    const isCustom = document.getElementById('marks-mode-custom')?.checked;
    const equalValInput = document.getElementById('setup-equal-marks-val');
    const publishBtn = document.getElementById('btn-publish-exam-submit');

    const title = titleInput.value.trim();
    const subject = subjInput.value.trim();
    const duration = parseInt(durationInput.value) || 60;
    const deadline = deadlineInput.value;
    const instructions = instructionsInput.value.trim();

    if (!title) {
        showToast("Please enter an exam title.", "warning");
        return;
    }
    if (!deadline) {
        showToast("Please select a scheduled deadline.", "warning");
        return;
    }

    const eqVal = parseFloat(equalValInput?.value || 5.0);
    const questionsPayload = state.cart.map((q, idx) => {
        let marks = eqVal;
        if (isCustom) {
            const customInp = document.querySelector(`.setup-custom-mark-input[data-idx="${idx}"]`);
            marks = customInp ? parseFloat(customInp.value || 0) : eqVal;
        }
        return {
            question_id: q.id,
            question_text: q.question_text,
            marks: marks,
            question_order: idx + 1
        };
    });

    const totalMarks = questionsPayload.reduce((sum, q) => sum + q.marks, 0);

    publishBtn.disabled = true;
    publishBtn.innerHTML = `<span>Publishing... ⏳</span>`;

    try {
        const res = await apiFetch('/api/exams', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                subject: subject,
                duration_minutes: duration,
                deadline: new Date(deadline).toISOString(),
                instructions: instructions,
                total_marks: totalMarks,
                questions: questionsPayload
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to create exam');
        }

        const data = await res.json();
        document.getElementById('exam-setup-modal')?.classList.add('hidden');
        showExamSuccessModal(data);
        showToast("Digital Exam Published Successfully! 🚀", "success");
    } catch (err) {
        showToast("Error publishing exam: " + err.message, "error");
    } finally {
        publishBtn.disabled = false;
        publishBtn.innerHTML = `<span>Publish Exam 🚀</span>`;
    }
}

// 4. Success Modal
function showExamSuccessModal(data) {
    const successModal = document.getElementById('exam-success-modal');
    const codeEl = document.getElementById('success-exam-code');
    const urlInput = document.getElementById('success-exam-url');
    const qrContainer = document.getElementById('success-qr-container');
    const whatsappBtn = document.getElementById('btn-whatsapp-share');
    const openRoomBtn = document.getElementById('btn-open-exam-room');

    if (codeEl) codeEl.textContent = data.exam_code;
    if (urlInput) urlInput.value = data.exam_url;
    if (qrContainer) qrContainer.innerHTML = data.qr_svg;

    if (openRoomBtn) openRoomBtn.href = data.exam_url;
    if (whatsappBtn) {
        const msg = encodeURIComponent(`Join the ${data.title} exam:\n${data.exam_url}\nCode: ${data.exam_code}`);
        whatsappBtn.href = `https://wa.me/?text=${msg}`;
    }

    // QR Download
    const downloadQrBtn = document.getElementById('btn-download-qr');
    if (downloadQrBtn) {
        downloadQrBtn.onclick = () => {
            const blob = new Blob([data.qr_svg], { type: 'image/svg+xml' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${data.exam_code}-qr.svg`;
            a.click();
            URL.revokeObjectURL(url);
        };
    }

    successModal?.classList.remove('hidden');
}

// 5. Load and Render Exams Dashboard
function renderExamsSkeleton(container) {
    if (!container) return;
    container.innerHTML = `
        <div class="p-4 sm:p-6 space-y-3">
            ${Array.from({ length: 4 }).map(() => `
                <div class="p-4 rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-800/60 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div class="space-y-2 flex-1">
                        <div class="flex items-center space-x-2">
                            <div class="w-20 h-6 rounded-lg skeleton-shimmer"></div>
                            <div class="w-36 h-5 rounded-md skeleton-shimmer"></div>
                        </div>
                        <div class="w-48 h-4 rounded skeleton-shimmer"></div>
                    </div>
                    <div class="flex items-center space-x-3">
                        <div class="w-20 h-6 rounded-full skeleton-shimmer"></div>
                        <div class="w-24 h-8 rounded-xl skeleton-shimmer"></div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderSubmissionsSkeleton(container) {
    if (!container) return;
    container.innerHTML = `
        <div class="p-4 sm:p-6 space-y-3">
            ${Array.from({ length: 4 }).map(() => `
                <div class="p-4 rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-800/60 shadow-xs flex items-center justify-between">
                    <div class="space-y-2">
                        <div class="w-32 h-5 rounded-md skeleton-shimmer"></div>
                        <div class="w-24 h-4 rounded skeleton-shimmer"></div>
                    </div>
                    <div class="flex items-center space-x-2">
                        <div class="w-16 h-6 rounded-full skeleton-shimmer"></div>
                        <div class="w-20 h-8 rounded-xl skeleton-shimmer"></div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

async function loadExamsList() {
    const statusFilter = document.getElementById('filter-exam-status')?.value || "";
    const container = document.getElementById('exams-table-container');
    if (!container) return;

    renderExamsSkeleton(container);

    try {
        let url = '/api/exams?limit=100';
        if (statusFilter) url += `&status=${statusFilter}`;
        const res = await apiFetch(url);
        if (!res.ok) throw new Error('Failed to load exams');

        const data = await res.json();
        examsState.currentExams = data.exams || [];

        // Update stats
        const total = examsState.currentExams.length;
        const active = examsState.currentExams.filter(e => e.status === 'active').length;
        const totalSubs = examsState.currentExams.reduce((sum, e) => sum + (e.submissions_count || 0), 0);
        const pendingGrading = examsState.currentExams.reduce((sum, e) => sum + (e.pending_count || 0), 0);

        const statTotal = document.getElementById('stat-total-exams');
        const statActive = document.getElementById('stat-active-exams');
        const statSubs = document.getElementById('stat-total-submissions');
        const statPending = document.getElementById('stat-pending-grading');

        if (statTotal) statTotal.textContent = total;
        if (statActive) statActive.textContent = active;
        if (statSubs) statSubs.textContent = totalSubs;
        if (statPending) statPending.textContent = pendingGrading;

        const navBadge = document.getElementById('nav-exams-badge');
        const mobNavBadge = document.getElementById('mob-exams-badge');
        if (pendingGrading > 0) {
            if (navBadge) {
                navBadge.textContent = pendingGrading;
                navBadge.classList.remove('hidden');
            }
            if (mobNavBadge) {
                mobNavBadge.textContent = pendingGrading;
                mobNavBadge.classList.remove('hidden');
            }
        } else {
            if (navBadge) navBadge.classList.add('hidden');
            if (mobNavBadge) mobNavBadge.classList.add('hidden');
        }

        renderExamsList(examsState.currentExams);
    } catch (err) {
        container.innerHTML = `
            <div class="p-8 text-center text-rose-500 text-xs font-medium">
                Error loading exams: ${escapeHtml(err.message)}
            </div>
        `;
    }
}

function renderExamsList(exams) {
    const container = document.getElementById('exams-table-container');
    if (!container) return;

    if (!exams || exams.length === 0) {
        container.innerHTML = `
            <div class="p-12 text-center text-slate-400 dark:text-slate-500">
                <span class="text-3xl block mb-2">📝</span>
                <p class="text-sm font-semibold">No digital exams found</p>
                <p class="text-xs mt-1">Select questions into your cart and click "Generate Digital Exam 🚀" to publish one.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <table class="w-full text-left text-xs">
            <thead class="bg-slate-50 dark:bg-slate-900/60 text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-700/80 uppercase font-semibold">
                <tr>
                    <th class="py-3 px-4">Code</th>
                    <th class="py-3 px-4">Exam Info</th>
                    <th class="py-3 px-4">Duration & Deadline</th>
                    <th class="py-3 px-4">Questions & Marks</th>
                    <th class="py-3 px-4">Submissions</th>
                    <th class="py-3 px-4">Status</th>
                    <th class="py-3 px-4 text-right">Actions</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                ${exams.map(e => {
                    const isClosed = e.status === 'closed';
                    const deadlineDate = new Date(e.deadline);
                    const isExpired = new Date() > deadlineDate;
                    const origin = window.location.origin;
                    const examUrl = `${origin}/exam/${e.exam_code}`;

                    return `
                        <tr class="hover:bg-slate-50/75 dark:hover:bg-slate-700/30 transition-colors">
                            <td class="py-3.5 px-4 font-mono font-bold text-brand-600 dark:text-brand-400">
                                <span class="bg-brand-50 dark:bg-brand-950/60 px-2.5 py-1 rounded-lg border border-brand-200/60 dark:border-brand-800/60">
                                    ${escapeHtml(e.exam_code)}
                                </span>
                            </td>
                            <td class="py-3.5 px-4">
                                <p class="font-bold text-slate-900 dark:text-white">${escapeHtml(e.title)}</p>
                                <p class="text-[11px] text-slate-400 dark:text-slate-400">${escapeHtml(e.subject || 'General')}</p>
                            </td>
                            <td class="py-3.5 px-4">
                                <p class="font-medium text-slate-700 dark:text-slate-300">⏱ ${e.duration_minutes} min</p>
                                <p class="text-[11px] ${isExpired ? 'text-rose-500 font-semibold' : 'text-slate-400'}">
                                    ${isExpired ? '⚠️ Expired: ' : '📅 '} ${deadlineDate.toLocaleString()}
                                </p>
                            </td>
                            <td class="py-3.5 px-4">
                                <span class="font-semibold text-slate-800 dark:text-slate-200">${e.questions_count} Qs</span>
                                <span class="text-slate-400">• ${e.total_marks} pts</span>
                            </td>
                            <td class="py-3.5 px-4">
                                <button onclick="openExamSubmissions(${e.id})" class="inline-flex items-center space-x-1 font-semibold text-brand-600 hover:text-brand-700 dark:text-brand-400 dark:hover:text-brand-300 hover:underline cursor-pointer">
                                    <span>${e.submissions_count || 0} Submissions</span>
                                    ${e.pending_count > 0 ? `<span class="px-1.5 py-0.2 bg-amber-500 text-white text-[10px] rounded-full font-bold">${e.pending_count} pending</span>` : ''}
                                </button>
                            </td>
                            <td class="py-3.5 px-4">
                                <button onclick="toggleExamStatus(${e.id})" class="px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider transition cursor-pointer ${
                                    isClosed 
                                        ? 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-300'
                                        : 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200'
                                }" title="Click to toggle active/closed">
                                    ${isClosed ? 'Closed' : 'Active'}
                                </button>
                            </td>
                            <td class="py-3.5 px-4 text-right space-x-1.5 shrink-0">
                                <button onclick="openExamSubmissions(${e.id})" class="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold transition cursor-pointer" title="View Submissions & Grade">
                                    📋 Grade
                                </button>
                                <button onclick="copyExamLink('${escapeHtml(examUrl)}')" class="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold transition cursor-pointer" title="Copy Student Room Link">
                                    🔗 Link
                                </button>
                                <button onclick="openExamQrModal('${escapeHtml(e.exam_code)}', '${escapeHtml(e.title)}')" class="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 font-semibold transition cursor-pointer" title="Show QR Code">
                                    📱 QR
                                </button>
                                <button onclick="deleteExam(${e.id})" class="px-2.5 py-1.5 rounded-lg border border-rose-200 dark:border-rose-900/60 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-rose-600 dark:text-rose-400 font-semibold transition cursor-pointer" title="Delete Exam">
                                    🗑️
                                </button>
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

window.copyExamLink = function(url) {
    navigator.clipboard.writeText(url).then(() => {
        showToast("Exam room link copied to clipboard! 📋", "success");
    }).catch(() => {
        showToast("Link: " + url, "info");
    });
};

window.toggleExamStatus = async function(examId) {
    try {
        const res = await apiFetch(`/api/exams/${examId}/toggle`, { method: 'PATCH' });
        if (!res.ok) throw new Error('Failed to toggle status');
        const data = await res.json();
        showToast(`Exam status changed to ${data.status}.`, "info");
        loadExamsList();
    } catch (err) {
        showToast("Error updating status: " + err.message, "error");
    }
};

window.deleteExam = async function(examId) {
    if (!confirm("Are you sure you want to delete this exam? All student submissions and grades will be permanently deleted.")) return;

    try {
        const res = await apiFetch(`/api/exams/${examId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete exam');
        showToast("Exam deleted successfully.", "info");
        loadExamsList();
    } catch (err) {
        showToast("Error deleting exam: " + err.message, "error");
    }
};

// 6. Submissions & Grading Studio View
window.openExamSubmissions = function(examId) {
    window.location.hash = `#exams/submissions/${examId}`;
};

async function loadSubmissionsList(examId) {
    examsState.activeExamId = examId;
    const container = document.getElementById('submissions-table-container');
    if (!container) return;

    renderSubmissionsSkeleton(container);

    try {
        const res = await apiFetch(`/api/exams/${examId}/submissions`);
        if (!res.ok) throw new Error('Failed to load submissions');

        const data = await res.json();
        const exam = data.exam;
        examsState.activeSubmissions = data.submissions || [];

        // Update header metadata
        const codeBadge = document.getElementById('sub-view-code-badge');
        const titleEl = document.getElementById('sub-view-title');
        const metaEl = document.getElementById('sub-view-meta');

        if (codeBadge) codeBadge.textContent = exam.exam_code;
        if (titleEl) titleEl.textContent = exam.title;
        if (metaEl) metaEl.textContent = `${exam.subject || 'General'} • Total Marks: ${exam.total_marks} • Duration: ${exam.duration_minutes} min`;

        renderSubmissionsTable(examsState.activeSubmissions, exam);
    } catch (err) {
        container.innerHTML = `
            <div class="p-8 text-center text-rose-500 text-xs font-medium">
                Error loading submissions: ${escapeHtml(err.message)}
            </div>
        `;
    }
}

function renderSubmissionsTable(submissions, exam) {
    const container = document.getElementById('submissions-table-container');
    if (!container) return;

    if (!submissions || submissions.length === 0) {
        container.innerHTML = `
            <div class="p-12 text-center text-slate-400 dark:text-slate-500">
                <span class="text-3xl block mb-2">📥</span>
                <p class="text-sm font-semibold">No student submissions yet</p>
                <p class="text-xs mt-1">Share the exam link or QR code with your students to start receiving submissions.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <table class="w-full text-left text-xs">
            <thead class="bg-slate-50 dark:bg-slate-900/60 text-slate-500 dark:text-slate-400 border-b border-slate-100 dark:border-slate-700/80 uppercase font-semibold">
                <tr>
                    <th class="py-3 px-4">Roll Number</th>
                    <th class="py-3 px-4">Student Name</th>
                    <th class="py-3 px-4">Section</th>
                    <th class="py-3 px-4">Submitted At & Time Taken</th>
                    <th class="py-3 px-4">Evaluation Status</th>
                    <th class="py-3 px-4">Total Score</th>
                    <th class="py-3 px-4 text-right">Actions</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                ${submissions.map(s => {
                    const isGraded = s.status === 'graded';
                    const submittedAt = new Date(s.submitted_at);
                    const timeMins = Math.floor(s.time_taken_seconds / 60);
                    const timeSecs = s.time_taken_seconds % 60;

                    return `
                        <tr class="hover:bg-slate-50/75 dark:hover:bg-slate-700/30 transition-colors">
                            <td class="py-3.5 px-4 font-mono font-bold text-slate-900 dark:text-white">
                                <div>${escapeHtml(s.roll_number)}</div>
                                ${s.is_emergency ? `<span class="inline-flex items-center space-x-1 mt-0.5 px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800 text-[10px] font-sans font-bold"><span>⚠️</span><span>Emergency Import</span></span>` : ''}
                            </td>
                            <td class="py-3.5 px-4 font-semibold text-slate-800 dark:text-slate-200">
                                ${escapeHtml(s.student_name)}
                            </td>
                            <td class="py-3.5 px-4 text-slate-500 dark:text-slate-400">
                                ${escapeHtml(s.section || '—')}
                            </td>
                            <td class="py-3.5 px-4">
                                <p class="text-slate-700 dark:text-slate-300 font-medium">${submittedAt.toLocaleString()}</p>
                                <p class="text-[11px] text-slate-400">⏱ ${timeMins}m ${timeSecs}s taken</p>
                            </td>
                            <td class="py-3.5 px-4">
                                <span class="px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-wider ${
                                    isGraded
                                        ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                                        : 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 animate-pulse'
                                }">
                                    ${isGraded ? 'Graded ✓' : 'Pending Evaluation'}
                                </span>
                            </td>
                            <td class="py-3.5 px-4 font-mono font-bold ${isGraded ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}">
                                ${isGraded ? `${s.total_score} / ${s.total_marks}` : `— / ${s.total_marks}`}
                            </td>
                            <td class="py-3.5 px-4 text-right">
                                <button onclick="openGradingStudio(${s.id})" class="px-3.5 py-1.5 rounded-xl font-bold transition shadow-xs active:scale-95 cursor-pointer ${
                                    isGraded
                                        ? 'bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 text-slate-800 dark:text-slate-100 border border-slate-200 dark:border-slate-600'
                                        : 'bg-brand-600 hover:bg-brand-700 text-white shadow-brand-500/20'
                                }">
                                    ${isGraded ? 'Review / Edit ✎' : 'Grade Answer Sheet 🚀'}
                                </button>
                            </td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

// 7. Grading Workspace Modal Logic
window.openGradingStudio = async function(submissionId) {
    const modal = document.getElementById('grading-workspace-modal');
    const container = document.getElementById('grading-questions-container');
    if (!modal || !container) return;

    container.innerHTML = `
        <div class="p-12 text-center text-slate-400">
            <span class="inline-block animate-spin text-3xl mb-2">⏳</span>
            <p class="text-sm font-semibold">Loading student answer sheet...</p>
        </div>
    `;
    modal.classList.remove('hidden');

    try {
        const res = await apiFetch(`/api/submissions/${submissionId}`);
        if (!res.ok) throw new Error('Failed to load submission details');

        const sub = await res.json();
        examsState.activeSubmissionDetail = sub;

        // Populate header
        document.getElementById('grade-student-name').textContent = sub.student_name;
        document.getElementById('grade-roll-badge').textContent = sub.roll_number;
        const secBadge = document.getElementById('grade-section-badge');
        if (secBadge) {
            secBadge.textContent = sub.section ? `Section: ${sub.section}` : '';
            secBadge.style.display = sub.section ? 'inline-block' : 'none';
        }
        let metaText = `${sub.exam_title} • Submitted: ${new Date(sub.submitted_at).toLocaleString()} • Duration: ${Math.floor(sub.time_taken_seconds/60)}m ${sub.time_taken_seconds%60}s`;
        if (sub.is_emergency) {
            metaText += ' • ⚠️ Offline Emergency Import (Verified)';
        }
        document.getElementById('grade-exam-meta').textContent = metaText;
        document.getElementById('grade-max-score').textContent = sub.total_marks;
        document.getElementById('grade-overall-feedback').value = sub.feedback || '';

        renderGradingQuestions(sub.answers);
        updateLiveAwardedScore();
    } catch (err) {
        container.innerHTML = `
            <div class="p-8 text-center text-rose-500 text-xs font-medium">
                Error loading submission: ${escapeHtml(err.message)}
            </div>
        `;
    }
};

function renderGradingQuestions(answers) {
    const container = document.getElementById('grading-questions-container');
    if (!container) return;

    if (!answers || answers.length === 0) {
        container.innerHTML = `<p class="text-center text-slate-400 text-xs">No questions found.</p>`;
        return;
    }

    container.innerHTML = answers.map((ans, idx) => {
        const defaultMarks = ans.marks_awarded !== null ? ans.marks_awarded : 0;
        const hasImage = Boolean(ans.image_data && ans.image_data.startsWith('data:image/'));

        return `
            <div class="bg-white dark:bg-slate-900/80 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-xs space-y-4" data-q-id="${ans.question_id}">
                <!-- Question Header -->
                <div class="flex items-start justify-between gap-3 border-b border-slate-100 dark:border-slate-800 pb-3">
                    <div class="flex items-start space-x-2.5">
                        <span class="w-6 h-6 rounded-full bg-brand-100 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
                            ${ans.question_order || idx + 1}
                        </span>
                        <div>
                            <p class="text-sm font-semibold text-slate-900 dark:text-white leading-relaxed">
                                ${escapeHtml(ans.question_text)}
                            </p>
                        </div>
                    </div>
                    <span class="px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-bold shrink-0">
                        Max: ${ans.max_marks} pts
                    </span>
                </div>

                <!-- Student Answer Body (Typed Text & Photo) -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <!-- Typed Answer Box -->
                    <div class="space-y-1.5">
                        <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Typed Response:</span>
                        <div class="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 text-xs text-slate-800 dark:text-slate-200 min-h-[90px] whitespace-pre-wrap leading-relaxed select-text">
                            ${ans.typed_answer ? escapeHtml(ans.typed_answer) : '<span class="text-slate-400 italic">No typed text submitted.</span>'}
                        </div>
                    </div>

                    <!-- Photo Sheet Box -->
                    <div class="space-y-1.5">
                        <span class="text-[11px] font-bold uppercase tracking-wider text-slate-400">Handwritten Photo Sheet:</span>
                        ${hasImage ? `
                            <div class="relative group border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-950 flex items-center justify-center h-[90px]">
                                <img src="${ans.image_data}" alt="Answer Sheet Photo" class="object-cover w-full h-full">
                                <div class="absolute inset-0 bg-slate-950/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                    <button type="button" onclick="openPhotoZoomModal('${ans.image_data}', 'Question ${ans.question_order || idx + 1}')" class="px-3 py-1.5 rounded-lg bg-white/90 dark:bg-slate-900/90 text-xs font-bold text-slate-900 dark:text-white shadow-md hover:scale-105 transition cursor-pointer flex items-center space-x-1">
                                        <span>🔍</span>
                                        <span>Zoom & Inspect</span>
                                    </button>
                                </div>
                            </div>
                        ` : `
                            <div class="p-3.5 rounded-xl border border-dashed border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/30 text-xs text-slate-400 italic flex items-center justify-center h-[90px]">
                                No photo sheet uploaded.
                            </div>
                        `}
                    </div>
                </div>

                <!-- Teacher Marks & Feedback Inputs -->
                <div class="pt-3 border-t border-slate-100 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50/60 dark:bg-slate-950/30 -mx-5 -mb-5 p-4 rounded-b-2xl">
                    <div class="flex items-center space-x-2">
                        <label class="text-xs font-bold text-slate-700 dark:text-slate-300">Awarded Marks:</label>
                        <input type="number" min="0" max="${ans.max_marks}" step="0.5" value="${defaultMarks}" data-max="${ans.max_marks}" class="grade-marks-input w-20 text-center font-bold text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-brand-600 dark:text-brand-400 text-sm">
                        <span class="text-xs text-slate-400">/ ${ans.max_marks} pts</span>
                    </div>
                    <div class="flex-1 max-w-md">
                        <input type="text" placeholder="Question-specific feedback / note..." value="${escapeHtml(ans.feedback || '')}" class="grade-feedback-input w-full text-xs px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200">
                    </div>
                </div>
            </div>
        `;
    }).join('');

    // Attach live score calculation listener
    container.querySelectorAll('.grade-marks-input').forEach(inp => {
        inp.addEventListener('input', () => {
            const max = parseFloat(inp.getAttribute('data-max') || 100);
            let val = parseFloat(inp.value || 0);
            if (val > max) inp.value = max;
            if (val < 0) inp.value = 0;
            updateLiveAwardedScore();
        });
    });
}

function updateLiveAwardedScore() {
    const inputs = document.querySelectorAll('.grade-marks-input');
    let total = 0;
    inputs.forEach(inp => {
        total += parseFloat(inp.value || 0);
    });
    const label = document.getElementById('live-awarded-score');
    if (label) label.textContent = total;
}

async function handlePublishEvaluation() {
    if (!examsState.activeSubmissionDetail) return;
    const subId = examsState.activeSubmissionDetail.id;
    const overallFeedback = document.getElementById('grade-overall-feedback')?.value.trim() || '';
    const qCards = document.querySelectorAll('#grading-questions-container > div');

    const grades = [];
    qCards.forEach(card => {
        const qId = parseInt(card.getAttribute('data-q-id'));
        const marksInp = card.querySelector('.grade-marks-input');
        const fbInp = card.querySelector('.grade-feedback-input');
        grades.push({
            question_id: qId,
            marks_awarded: parseFloat(marksInp?.value || 0),
            feedback: fbInp?.value.trim() || ''
        });
    });

    const publishBtn = document.getElementById('btn-publish-evaluation');
    publishBtn.disabled = true;
    publishBtn.innerHTML = `<span>Publishing... ⏳</span>`;

    try {
        const res = await apiFetch(`/api/submissions/${subId}/grade`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                grades: grades,
                overall_feedback: overallFeedback,
                is_published: true
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to publish grades');
        }

        document.getElementById('grading-workspace-modal')?.classList.add('hidden');
        showToast("Student grades published successfully! 🎉", "success");

        // Refresh submissions table
        if (examsState.activeExamId) {
            loadSubmissionsList(examsState.activeExamId);
        }
    } catch (err) {
        showToast("Error publishing evaluation: " + err.message, "error");
    } finally {
        publishBtn.disabled = false;
        publishBtn.innerHTML = `<span>Publish Evaluation & Marks 🚀</span>`;
    }
}

// 8. Photo Zoom Modal / Lightbox Logic
window.openPhotoZoomModal = function(imgSrc, title) {
    const modal = document.getElementById('photo-zoom-modal');
    const img = document.getElementById('photo-zoom-img');
    const titleEl = document.getElementById('photo-zoom-title');
    if (!modal || !img) return;

    if (titleEl) titleEl.textContent = title || "Handwritten Answer Sheet";
    img.src = imgSrc;
    examsState.photoZoom.scale = 1.0;
    examsState.photoZoom.rotation = 0;
    applyPhotoZoomTransform();
    modal.classList.remove('hidden');
};

function applyPhotoZoomTransform() {
    const img = document.getElementById('photo-zoom-img');
    if (!img) return;
    img.style.transform = `scale(${examsState.photoZoom.scale}) rotate(${examsState.photoZoom.rotation}deg)`;
}

// 9. Dashboard QR Modal
window.openExamQrModal = function(examCode, title) {
    const modal = document.getElementById('exam-qr-modal');
    const titleEl = document.getElementById('dash-qr-title');
    const codeEl = document.getElementById('dash-qr-code');
    const container = document.getElementById('dash-qr-container');
    const downloadBtn = document.getElementById('btn-download-dash-qr');
    if (!modal) return;

    if (titleEl) titleEl.textContent = title || "Exam QR Code";
    if (codeEl) codeEl.textContent = examCode;
    const origin = window.location.origin;
    const examUrl = `${origin}/exam/${examCode}`;

    if (container) {
        container.innerHTML = `<img src="/api/exams/${examCode}/qr" alt="QR Code" class="w-full h-full object-contain">`;
    }

    if (downloadBtn) {
        downloadBtn.onclick = async () => {
            try {
                const res = await fetch(`/api/exams/${examCode}/qr`);
                const svgText = await res.text();
                const blob = new Blob([svgText], { type: 'image/svg+xml' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${examCode}-qr.svg`;
                a.click();
                URL.revokeObjectURL(url);
            } catch (err) {
                showToast("Download failed: " + err.message, "error");
            }
        };
    }

    modal.classList.remove('hidden');
};

// 10. Initialization & Event Listeners Attachment
function initExamsStudio() {
    // Navigation tabs
    document.getElementById('nav-tab-bank')?.addEventListener('click', () => {
        window.location.hash = '#bank';
    });
    document.getElementById('nav-tab-exams')?.addEventListener('click', () => {
        window.location.hash = '#exams';
    });

    // Cart "Generate Digital Exam" button
    document.getElementById('btn-generate-exam')?.addEventListener('click', openExamSetupModal);

    // Dashboard create exam button
    document.getElementById('btn-dashboard-create-exam')?.addEventListener('click', () => {
        if (!state.cart || state.cart.length === 0) {
            showToast("Your cart is empty. Add questions from the Question Bank first.", "info");
            window.location.hash = '#bank';
            return;
        }
        openExamSetupModal();
    });

    // Refresh buttons
    document.getElementById('btn-refresh-exams')?.addEventListener('click', loadExamsList);
    document.getElementById('btn-refresh-submissions')?.addEventListener('click', () => {
        if (examsState.activeExamId) loadSubmissionsList(examsState.activeExamId);
    });

    // Emergency offline submission import (.squire)
    const btnImportEmergencySub = document.getElementById('btn-import-emergency-sub');
    const emergencyFileInput = document.getElementById('emergency-file-input');
    if (btnImportEmergencySub && emergencyFileInput) {
        btnImportEmergencySub.addEventListener('click', () => {
            emergencyFileInput.value = '';
            emergencyFileInput.click();
        });

        emergencyFileInput.addEventListener('change', async (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;

            try {
                showToast("Reading emergency submission file...", "info", 1500);
                const text = await file.text();
                const payload = JSON.parse(text);

                if (!payload.exam_code || !payload.roll_number || !payload.integrity_hash) {
                    throw new Error("Invalid emergency file format. Missing exam_code, roll_number, or integrity_hash.");
                }

                const res = await apiFetch(`/api/exams/${payload.exam_code}/import-emergency`, {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || "Failed to import emergency submission.");
                }

                const result = await res.json();
                showToast(`Emergency submission for Roll ${result.roll_number} verified and imported!`, "success", 4000);
                if (examsState.activeExamId) {
                    loadSubmissionsList(examsState.activeExamId);
                }
            } catch (err) {
                showToast("Import error: " + err.message, "error", 5000);
            }
        });
    }

    document.getElementById('filter-exam-status')?.addEventListener('change', loadExamsList);

    // Back to exams
    document.getElementById('btn-back-to-exams')?.addEventListener('click', () => {
        window.location.hash = '#exams';
    });

    // Exam setup modal events
    document.getElementById('close-exam-setup-modal')?.addEventListener('click', () => {
        document.getElementById('exam-setup-modal')?.classList.add('hidden');
    });
    document.getElementById('cancel-exam-setup-btn')?.addEventListener('click', () => {
        document.getElementById('exam-setup-modal')?.classList.add('hidden');
    });
    document.getElementById('marks-mode-equal')?.addEventListener('change', renderSetupMarksAllocation);
    document.getElementById('marks-mode-custom')?.addEventListener('change', renderSetupMarksAllocation);
    document.getElementById('setup-equal-marks-val')?.addEventListener('input', renderSetupMarksAllocation);
    document.getElementById('exam-setup-form')?.addEventListener('submit', handlePublishExam);

    // Success popup events
    document.getElementById('btn-copy-exam-link')?.addEventListener('click', () => {
        const urlInput = document.getElementById('success-exam-url');
        if (urlInput) {
            navigator.clipboard.writeText(urlInput.value).then(() => {
                const icon = document.getElementById('copy-btn-icon');
                const text = document.getElementById('copy-btn-text');
                if (icon) icon.textContent = '✓';
                if (text) text.textContent = 'Copied!';
                setTimeout(() => {
                    if (icon) icon.textContent = '📋';
                    if (text) text.textContent = 'Copy';
                }, 2000);
            });
        }
    });
    document.getElementById('btn-success-to-dashboard')?.addEventListener('click', () => {
        document.getElementById('exam-success-modal')?.classList.add('hidden');
        window.location.hash = '#exams';
    });

    // Grading modal events
    document.getElementById('close-grading-modal')?.addEventListener('click', () => {
        document.getElementById('grading-workspace-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-cancel-grading')?.addEventListener('click', () => {
        document.getElementById('grading-workspace-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-publish-evaluation')?.addEventListener('click', handlePublishEvaluation);

    // Photo zoom modal events
    document.getElementById('close-photo-zoom-modal')?.addEventListener('click', () => {
        document.getElementById('photo-zoom-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-photo-zoom-in')?.addEventListener('click', () => {
        examsState.photoZoom.scale = Math.min(3.0, examsState.photoZoom.scale + 0.25);
        applyPhotoZoomTransform();
    });
    document.getElementById('btn-photo-zoom-out')?.addEventListener('click', () => {
        examsState.photoZoom.scale = Math.max(0.5, examsState.photoZoom.scale - 0.25);
        applyPhotoZoomTransform();
    });
    document.getElementById('btn-photo-rotate')?.addEventListener('click', () => {
        examsState.photoZoom.rotation = (examsState.photoZoom.rotation + 90) % 360;
        applyPhotoZoomTransform();
    });
    document.getElementById('btn-photo-reset')?.addEventListener('click', () => {
        examsState.photoZoom.scale = 1.0;
        examsState.photoZoom.rotation = 0;
        applyPhotoZoomTransform();
    });

    // Dashboard QR modal events
    document.getElementById('close-exam-qr-modal')?.addEventListener('click', () => {
        document.getElementById('exam-qr-modal')?.classList.add('hidden');
    });

    // Keyboard Esc shortcut
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('photo-zoom-modal')?.classList.add('hidden');
            document.getElementById('exam-qr-modal')?.classList.add('hidden');
        }
    });

    // Initial route check
    handleHashRoute();
}

// Automatically initialize exams studio when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initExamsStudio);
} else {
    initExamsStudio();
}
