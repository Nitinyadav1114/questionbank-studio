/**
 * Squire Way — Interactive Digital Exam Room
 * Production-grade client logic: Wall-clock synchronized timer, crash-resilient
 * continuous auto-save, pure HTML5 canvas photo compression, and instant result scorecard.
 */

(function () {
    'use strict';

    // Application State
    const examState = {
        code: '',
        exam: null,
        student: {
            name: '',
            roll: '',
            section: ''
        },
        session: null,
        answers: {}, // question_id -> { typed_answer: '', image_data: '', size_bytes: 0 }
        timerInterval: null,
        autoSaveTimeout: null,
        isSubmitting: false,
        clockSkewMs: 0,
        retryInterval: null,
        lastPayloadAnswers: null,
        lastTimeTakenSecs: 0,
        currentQuestionIndex: 0,
        alerted5Min: false,
        alerted1Min: false
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

    // 0. Resilient IndexedDB Multi-Tier Storage Engine (bypasses mobile 5MB localStorage limit)
    const IDB_NAME = 'SquireWayExamStore';
    const IDB_STORE = 'exam_sessions';
    let idbInstance = null;

    function openExamIDB() {
        return new Promise((resolve) => {
            if (!window.indexedDB) return resolve(null);
            if (idbInstance) return resolve(idbInstance);
            try {
                const req = indexedDB.open(IDB_NAME, 1);
                req.onupgradeneeded = (e) => {
                    const db = e.target.result;
                    if (!db.objectStoreNames.contains(IDB_STORE)) {
                        db.createObjectStore(IDB_STORE, { keyPath: 'exam_code' });
                    }
                };
                req.onsuccess = (e) => {
                    idbInstance = e.target.result;
                    resolve(idbInstance);
                };
                req.onerror = () => resolve(null);
            } catch (e) {
                resolve(null);
            }
        });
    }

    async function saveSessionToIDB(session) {
        const db = await openExamIDB();
        if (!db) return false;
        return new Promise((resolve) => {
            try {
                const tx = db.transaction([IDB_STORE], 'readwrite');
                const store = tx.objectStore(IDB_STORE);
                store.put(session);
                tx.oncomplete = () => resolve(true);
                tx.onerror = () => resolve(false);
            } catch (e) {
                resolve(false);
            }
        });
    }

    async function loadSessionFromIDB(code) {
        const db = await openExamIDB();
        if (!db) return null;
        return new Promise((resolve) => {
            try {
                const tx = db.transaction([IDB_STORE], 'readonly');
                const store = tx.objectStore(IDB_STORE);
                const req = store.get(code);
                req.onsuccess = () => resolve(req.result || null);
                req.onerror = () => resolve(null);
            } catch (e) {
                resolve(null);
            }
        });
    }

    async function clearSessionFromIDB(code) {
        const db = await openExamIDB();
        if (!db) return;
        try {
            const tx = db.transaction([IDB_STORE], 'readwrite');
            tx.objectStore(IDB_STORE).delete(code);
        } catch (e) {}
    }

    // 0.1 Live Network Connectivity Monitor
    function initNetworkMonitor() {
        const banner = document.getElementById('offline-banner');
        const bannerText = document.getElementById('offline-banner-text');

        function updateOnlineStatus() {
            if (!navigator.onLine) {
                if (banner) {
                    banner.classList.remove('hidden');
                    banner.className = "fixed top-3 left-1/2 -translate-x-1/2 z-[70] px-4 py-2 rounded-full bg-amber-600 text-white text-xs font-bold shadow-lg flex items-center space-x-2 animate-bounce pointer-events-none";
                    if (bannerText) bannerText.textContent = "You are offline. Your answers are safely preserved locally.";
                }
                showToast("You are offline. Local auto-save is protecting your work.", "warning", 4000);
            } else {
                if (banner && !banner.classList.contains('hidden')) {
                    banner.className = "fixed top-3 left-1/2 -translate-x-1/2 z-[70] px-4 py-2 rounded-full bg-emerald-600 text-white text-xs font-bold shadow-lg flex items-center space-x-2 pointer-events-none";
                    if (bannerText) bannerText.textContent = "✓ Back online! Connection restored.";
                    setTimeout(() => banner.classList.add('hidden'), 2500);
                }
            }
        }

        window.addEventListener('online', updateOnlineStatus);
        window.addEventListener('offline', updateOnlineStatus);
        if (!navigator.onLine) updateOnlineStatus();
    }

    function getServerNow() {
        return Date.now() + examState.clockSkewMs;
    }

    // 1. Toast Notification Helper
    function showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const colors = {
            success: 'bg-emerald-600 text-white',
            error: 'bg-rose-600 text-white',
            warning: 'bg-amber-600 text-white',
            info: 'bg-slate-800 text-white dark:bg-slate-700'
        };

        const toast = document.createElement('div');
        toast.className = `p-3.5 rounded-xl shadow-lg text-xs font-semibold flex items-center space-x-2 transition-all duration-200 pointer-events-auto ${colors[type] || colors.info}`;
        toast.innerHTML = `<span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // 2. Extract Exam Code from Pathname
    function getExamCodeFromURL() {
        const parts = window.location.pathname.split('/').filter(Boolean);
        // Expecting /exam/{exam_code}
        const idx = parts.indexOf('exam');
        if (idx !== -1 && parts[idx + 1]) {
            return parts[idx + 1].toUpperCase();
        }
        return '';
    }

    // 3. View Switcher
    function showView(viewId) {
        const views = ['loading-view', 'error-view', 'entry-view', 'exam-room-view', 'receipt-view', 'result-view'];
        views.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                if (id === viewId) el.classList.remove('hidden');
                else el.classList.add('hidden');
            }
        });
    }

    // 4. Client-Side Pure HTML5 Canvas Photo Compression (~180-220KB WebP/JPEG)
    // Zero external libraries. Uses native browser standard Canvas & FileReader with memory cleanup.
    async function compressAnswerPhoto(file, maxDimension = 1280, targetMaxBytes = 220 * 1024) {
        return new Promise((resolve, reject) => {
            if (!file || !file.type.startsWith('image/')) {
                return reject(new Error('Selected file is not an image.'));
            }

            const reader = new FileReader();
            reader.onerror = () => reject(new Error('Failed to read image file.'));
            reader.onload = (e) => {
                const img = new Image();
                img.onerror = () => reject(new Error('Failed to decode image data.'));
                img.onload = () => {
                    let width = img.naturalWidth || img.width;
                    let height = img.naturalHeight || img.height;

                    // 1. Maintain aspect ratio within maxDimension (1280px for mobile RAM safety)
                    if (width > maxDimension || height > maxDimension) {
                        if (width > height) {
                            height = Math.round((height * maxDimension) / width);
                            width = maxDimension;
                        } else {
                            width = Math.round((width * maxDimension) / height);
                            height = maxDimension;
                        }
                    }

                    // 2. Offscreen Canvas setup
                    const canvas = document.createElement('canvas');
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');

                    ctx.imageSmoothingEnabled = true;
                    ctx.imageSmoothingQuality = 'high';

                    // White background to avoid dark artifacts on transparent PNGs converted to JPEG
                    ctx.fillStyle = '#FFFFFF';
                    ctx.fillRect(0, 0, width, height);
                    ctx.drawImage(img, 0, 0, width, height);

                    // 3. Format detection: WebP with JPEG fallback
                    let mimeType = 'image/webp';
                    const testData = canvas.toDataURL('image/webp', 0.5);
                    if (!testData.startsWith('data:image/webp')) {
                        mimeType = 'image/jpeg';
                    }

                    // 4. Adaptive quality stepping to guarantee target bytes (~180-220KB)
                    let quality = 0.80;
                    let dataUrl = canvas.toDataURL(mimeType, quality);
                    let byteLength = Math.round((dataUrl.length - dataUrl.indexOf(',') - 1) * 3 / 4);

                    if (byteLength > targetMaxBytes) {
                        const qualities = [0.70, 0.60, 0.50, 0.40];
                        for (const q of qualities) {
                            const candidate = canvas.toDataURL(mimeType, q);
                            const size = Math.round((candidate.length - candidate.indexOf(',') - 1) * 3 / 4);
                            dataUrl = candidate;
                            byteLength = size;
                            quality = q;
                            if (size <= targetMaxBytes) break;
                        }
                    }

                    // Low-memory browser cleanup
                    ctx.clearRect(0, 0, width, height);
                    canvas.width = 1;
                    canvas.height = 1;
                    img.src = '';

                    resolve({
                        dataUrl: dataUrl,
                        sizeBytes: byteLength,
                        format: mimeType.split('/')[1],
                        width: width,
                        height: height
                    });
                };
                img.src = e.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

    // 5. Initialize Exam Room & Fetch Public Metadata
    async function initExamRoom() {
        examState.code = getExamCodeFromURL();
        if (!examState.code) {
            showError('Invalid Exam URL', 'Please check your exam link or ask your instructor for the correct link.');
            return;
        }

        try {
            const res = await fetch(`/api/exams/${examState.code}`);
            if (!res.ok) {
                if (res.status === 404) {
                    showError('Exam Not Found', `No exam matching code "${examState.code}" exists.`);
                } else {
                    showError('Unable to Load Exam', 'An error occurred while loading this digital examination.');
                }
                return;
            }

            const data = await res.json();
            examState.exam = data;

            // Server Clock Synchronization: Anchors all timer logic to server wall-clock
            if (data.server_now_utc) {
                const serverTime = new Date(data.server_now_utc).getTime();
                examState.clockSkewMs = serverTime - Date.now();
            }

            // Check if student already has a saved in-progress session (try localStorage, then IDB fallback)
            let savedSession = loadSession(examState.code);
            if (!savedSession) {
                savedSession = await loadSessionFromIDB(examState.code);
            }

            if (savedSession && savedSession.status === 'in_progress') {
                const now = getServerNow();
                if (now < savedSession.effective_end_time) {
                    // Restore session immediately
                    restoreSession(savedSession);
                    return;
                }
            }

            // Otherwise show entry verification screen
            populateEntryScreen(data);
        } catch (err) {
            showError('Network Error', 'Could not connect to the examination server. Please check your connection.');
        }
    }

    function showError(title, message) {
        showView('error-view');
        const titleEl = document.getElementById('error-title');
        const msgEl = document.getElementById('error-message');
        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = message;

        document.getElementById('btn-error-lookup-result')?.addEventListener('click', () => {
            promptScorecardLookup();
        });
    }

    function populateEntryScreen(exam) {
        showView('entry-view');

        document.getElementById('entry-exam-code-badge').textContent = exam.exam_code;
        document.getElementById('entry-exam-title').textContent = exam.title;
        document.getElementById('entry-exam-subject').textContent = exam.subject || 'General Subject';
        document.getElementById('entry-duration').textContent = `${exam.duration_minutes}m`;
        document.getElementById('entry-total-marks').textContent = `${exam.total_marks} pts`;
        document.getElementById('entry-total-questions').textContent = `${exam.questions_count} Qs`;

        const instCard = document.getElementById('entry-instructions-card');
        const instText = document.getElementById('entry-instructions-text');
        if (exam.instructions && exam.instructions.trim()) {
            instText.textContent = exam.instructions;
            instCard.classList.remove('hidden');
        } else {
            instCard.classList.add('hidden');
        }

        // Attach entry form submission
        const form = document.getElementById('student-entry-form');
        form.onsubmit = (e) => {
            e.preventDefault();
            const name = document.getElementById('student-name-input').value.trim();
            const roll = document.getElementById('student-roll-input').value.trim().toUpperCase();
            const section = document.getElementById('student-section-input').value.trim();

            if (!name || !roll) {
                showToast('Please enter both your full name and roll number.', 'warning');
                return;
            }

            startExamSession(name, roll, section);
        };

        // Attach lookup button
        document.getElementById('btn-lookup-result-entry').onclick = () => {
            promptScorecardLookup();
        };
    }

    // 6. Session Persistence & Start
    function startExamSession(name, roll, section) {
        const startTime = getServerNow();
        const durationMs = examState.exam.duration_minutes * 60 * 1000;
        const computedEndTime = startTime + durationMs;
        const deadlineTime = new Date(examState.exam.deadline).getTime();
        const effectiveEndTime = Math.min(computedEndTime, deadlineTime);

        examState.student = { name, roll, section };
        examState.session = {
            exam_code: examState.code,
            student: examState.student,
            start_time: startTime,
            duration_minutes: examState.exam.duration_minutes,
            deadline: examState.exam.deadline,
            effective_end_time: effectiveEndTime,
            status: 'in_progress',
            answers: {}
        };

        saveSession();
        launchExamRoom();
    }

    function saveSession() {
        if (!examState.session) return;
        examState.session.answers = examState.answers;
        examState.session.last_saved = getServerNow();
        try {
            localStorage.setItem(`exam_session_${examState.code}`, JSON.stringify(examState.session));
        } catch (e) {
            console.warn('localStorage QuotaExceededError (5MB mobile limit). IndexedDB will preserve session:', e);
        }

        // Always replicate session to IndexedDB fallback
        saveSessionToIDB(examState.session);

        const indicator = document.getElementById('save-status-indicator');
        if (indicator) {
            const now = new Date(getServerNow());
            indicator.textContent = `✓ Saved locally at ${now.toLocaleTimeString()}`;
            indicator.classList.remove('text-slate-400');
            indicator.classList.add('text-emerald-500', 'dark:text-emerald-400');
            setTimeout(() => {
                indicator.classList.remove('text-emerald-500', 'dark:text-emerald-400');
                indicator.classList.add('text-slate-400');
            }, 1200);
        }
    }

    function loadSession(code) {
        try {
            const raw = localStorage.getItem(`exam_session_${code}`);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    function clearSession(code) {
        try {
            localStorage.removeItem(`exam_session_${code}`);
        } catch (e) {}
        clearSessionFromIDB(code);
    }

    function restoreSession(savedSession) {
        examState.session = savedSession;
        examState.student = savedSession.student;
        examState.answers = savedSession.answers || {};
        launchExamRoom();
        showToast('Restored previous exam session. All answers saved.', 'info');
    }

    // 7. Launch Exam Room
    function launchExamRoom() {
        showView('exam-room-view');

        // Top bar details
        document.getElementById('top-bar-exam-title').textContent = examState.exam.title;
        document.getElementById('top-bar-student-name').textContent = examState.student.name;
        document.getElementById('top-bar-student-roll').textContent = examState.student.roll;

        // Render questions
        renderExamQuestions();
        renderNavigator();
        initMobileExamControls();
        updateMobileExamDock();

        // Start synchronized timer
        startCountdownTimer();

        // Wire up submit button
        document.getElementById('btn-trigger-submit').onclick = () => {
            openSubmitConfirmModal();
        };

        // Warn before leaving tab
        window.onbeforeunload = (e) => {
            if (examState.session && examState.session.status === 'in_progress') {
                saveSession();
                e.preventDefault();
                e.returnValue = '';
            }
        };
    }

    // 8. Wall-Clock Synchronized Countdown Timer (Server Anchored)
    function startCountdownTimer() {
        if (examState.timerInterval) clearInterval(examState.timerInterval);

        function updateTimer() {
            const now = getServerNow();
            const remainingMs = Math.max(0, examState.session.effective_end_time - now);

            if (remainingMs <= 0) {
                clearInterval(examState.timerInterval);
                document.getElementById('timer-display').textContent = '00:00';
                showToast('Exam time expired! Auto-submitting answers...', 'warning');
                triggerAutoSubmit();
                return;
            }

            const totalSecs = Math.floor(remainingMs / 1000);
            const hours = Math.floor(totalSecs / 3600);
            const mins = Math.floor((totalSecs % 3600) / 60);
            const secs = totalSecs % 60;

            const pill = document.getElementById('timer-pill');
            const display = document.getElementById('timer-display');

            if (hours > 0) {
                display.textContent = `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
            } else {
                display.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
            }

            // Urgency color cues and tactile countdown alerts
            if (totalSecs <= 60) {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full bg-rose-600 text-white font-mono font-extrabold text-xs sm:text-sm animate-pulse shadow-md";
                if (!examState.alerted1Min) {
                    examState.alerted1Min = true;
                    triggerHaptic('error');
                    showToast('🚨 1 Minute Remaining! Prepare to submit your exam.', 'error', 8000);
                }
            } else if (totalSecs <= 300) {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full bg-amber-100 dark:bg-amber-950/80 text-amber-900 dark:text-amber-200 border border-amber-300 font-mono font-bold text-xs sm:text-sm";
                if (!examState.alerted5Min) {
                    examState.alerted5Min = true;
                    triggerHaptic('medium');
                    showToast('⏳ 5 Minutes Remaining! Please review your answers.', 'warning', 6000);
                }
            } else {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 shadow-xs font-mono font-bold text-xs sm:text-sm text-slate-800 dark:text-slate-100";
            }
        }

        updateTimer();
        examState.timerInterval = setInterval(updateTimer, 1000);
    }

    function formatWordCharCount(text) {
        const trimmed = (text || '').trim();
        const words = trimmed ? trimmed.split(/\s+/).length : 0;
        const chars = (text || '').length;
        return `${words} word${words === 1 ? '' : 's'} • ${chars} char${chars === 1 ? '' : 's'}`;
    }

    // 9. Render Question Cards
    function renderExamQuestions() {
        const container = document.getElementById('exam-questions-container');
        if (!container || !examState.exam || !examState.exam.questions) return;

        container.innerHTML = examState.exam.questions.map((q, idx) => {
            const savedAns = examState.answers[q.id] || { typed_answer: '', image_data: '' };
            const isAnswered = Boolean(savedAns.typed_answer.trim() || savedAns.image_data);

            return `
                <div id="q-card-${q.id}" class="bg-white dark:bg-slate-800 rounded-3xl border border-slate-200/80 dark:border-slate-700/80 p-5 sm:p-7 shadow-xs space-y-4 scroll-mt-24 transition-all">
                    <!-- Question Header -->
                    <div class="flex items-start justify-between gap-3 border-b border-slate-100 dark:border-slate-700/80 pb-3.5">
                        <div class="flex items-start space-x-3">
                            <span class="w-7 h-7 rounded-full bg-brand-100 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                                ${q.question_order || idx + 1}
                            </span>
                            <h3 class="text-sm sm:text-base font-bold text-slate-900 dark:text-white leading-relaxed select-text">
                                ${escapeHtml(q.question_text)}
                            </h3>
                        </div>
                        <div class="flex items-center space-x-2 shrink-0">
                            <span class="px-2.5 py-1 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-bold font-mono">
                                ${q.marks} pts
                            </span>
                            <span id="q-status-badge-${q.id}" class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                                isAnswered ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-slate-100 text-slate-400 dark:bg-slate-800'
                            }">
                                ${isAnswered ? '✓ Answered' : 'Pending'}
                            </span>
                        </div>
                    </div>

                    <!-- Typed Answer Input -->
                    <div class="space-y-1.5">
                        <div class="flex items-center justify-between">
                            <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                                Typed Answer:
                            </label>
                            <span id="q-counter-${q.id}" class="text-[10px] font-mono text-slate-400 dark:text-slate-500">
                                ${formatWordCharCount(savedAns.typed_answer || '')}
                            </span>
                        </div>
                        <textarea id="q-text-${q.id}" rows="4" placeholder="Type your answer here..." class="w-full text-xs sm:text-sm px-4 py-3 rounded-2xl border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 leading-relaxed">${escapeHtml(savedAns.typed_answer || '')}</textarea>
                    </div>

                    <!-- Handwritten Sheet Canvas Photo Upload -->
                    <div class="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-700/60">
                        <div class="flex items-center justify-between">
                            <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                                Handwritten Photo Sheet (Calculations, diagrams, formulas):
                            </label>
                            <span class="text-[10px] text-slate-400">Compressed to ~200KB WebP/JPEG</span>
                        </div>

                        <!-- Hidden File Input with Camera Support -->
                        <input type="file" id="q-file-${q.id}" accept="image/*" capture="environment" class="hidden">

                        <!-- Preview & Upload Dropzone -->
                        <div id="q-photo-container-${q.id}">
                            ${savedAns.image_data ? renderPhotoThumbnail(q.id, savedAns.image_data, savedAns.size_bytes) : renderPhotoUploadPrompt(q.id)}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Attach listeners for typed text
        examState.exam.questions.forEach(q => {
            const textarea = document.getElementById(`q-text-${q.id}`);
            if (textarea) {
                textarea.addEventListener('input', () => {
                    const counter = document.getElementById(`q-counter-${q.id}`);
                    if (counter) counter.textContent = formatWordCharCount(textarea.value);
                    handleAnswerUpdate(q.id, textarea.value, null);
                });
            }

            const fileInput = document.getElementById(`q-file-${q.id}`);
            if (fileInput) {
                fileInput.addEventListener('change', async (e) => {
                    const file = e.target.files && e.target.files[0];
                    if (!file) return;
                    await handlePhotoUpload(q.id, file);
                });
            }
        });
    }

    function renderPhotoUploadPrompt(qId) {
        return `
            <div onclick="document.getElementById('q-file-${qId}').click()" class="border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-brand-500 rounded-2xl p-4 text-center cursor-pointer transition bg-slate-50/50 dark:bg-slate-900/30 flex items-center justify-center space-x-2">
                <span class="text-xl">📷</span>
                <span class="text-xs font-semibold text-slate-600 dark:text-slate-300">Click to capture or upload handwritten sheet photo</span>
            </div>
        `;
    }

    function renderPhotoThumbnail(qId, dataUrl, sizeBytes) {
        const kb = sizeBytes ? Math.round(sizeBytes / 1024) : Math.round((dataUrl.length * 3 / 4) / 1024);
        return `
            <div class="flex items-center justify-between p-3 rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/60">
                <div class="flex items-center space-x-3 min-w-0">
                    <img src="${dataUrl}" alt="Photo sheet preview" onclick="openStudentPhotoZoom('${dataUrl}')" class="w-14 h-14 object-cover rounded-xl border border-slate-300 dark:border-slate-700 cursor-pointer shadow-xs hover:scale-105 transition shrink-0">
                    <div class="min-w-0">
                        <p class="text-xs font-bold text-slate-800 dark:text-slate-200 truncate">Handwritten Answer Sheet</p>
                        <p class="text-[10px] text-slate-400 font-mono mt-0.5">${kb} KB • Ready</p>
                        <button type="button" onclick="openStudentPhotoZoom('${dataUrl}')" class="text-[11px] font-semibold text-brand-600 dark:text-brand-400 hover:underline cursor-pointer">
                            🔍 Zoom & Inspect
                        </button>
                    </div>
                </div>
                <div class="flex items-center space-x-2 shrink-0">
                    <button type="button" onclick="document.getElementById('q-file-${qId}').click()" class="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer">
                        Retake
                    </button>
                    <button type="button" onclick="removeAnswerPhoto(${qId})" class="p-1.5 text-slate-400 hover:text-rose-600 font-bold text-xs cursor-pointer" title="Remove photo">
                        ✕
                    </button>
                </div>
            </div>
        `;
    }

    async function handlePhotoUpload(qId, file) {
        showToast('Compressing photo sheet...', 'info', 1500);
        try {
            const compressed = await compressAnswerPhoto(file);
            const container = document.getElementById(`q-photo-container-${qId}`);
            if (container) {
                container.innerHTML = renderPhotoThumbnail(qId, compressed.dataUrl, compressed.sizeBytes);
            }
            handleAnswerUpdate(qId, null, compressed.dataUrl, compressed.sizeBytes);
            triggerHaptic('success');
            showToast(`Photo compressed (${Math.round(compressed.sizeBytes / 1024)} KB) and attached!`, 'success');
        } catch (err) {
            showToast('Error compressing image: ' + err.message, 'error');
        }
    }

    window.removeAnswerPhoto = function(qId) {
        const container = document.getElementById(`q-photo-container-${qId}`);
        if (container) {
            container.innerHTML = renderPhotoUploadPrompt(qId);
        }
        handleAnswerUpdate(qId, null, '');
        triggerHaptic('medium');
        showToast('Photo sheet removed.', 'info');
    };

    function handleAnswerUpdate(qId, typedAnswer, imageData, sizeBytes) {
        if (!examState.answers[qId]) {
            examState.answers[qId] = { typed_answer: '', image_data: '', size_bytes: 0 };
        }
        if (typedAnswer !== null) {
            examState.answers[qId].typed_answer = typedAnswer;
        }
        if (imageData !== null) {
            examState.answers[qId].image_data = imageData;
            examState.answers[qId].size_bytes = sizeBytes || 0;
        }

        const isAnswered = Boolean(examState.answers[qId].typed_answer.trim() || examState.answers[qId].image_data);
        const badge = document.getElementById(`q-status-badge-${qId}`);
        if (badge) {
            badge.className = `px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                isAnswered ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-slate-100 text-slate-400 dark:bg-slate-800'
            }`;
            badge.textContent = isAnswered ? '✓ Answered' : 'Pending';
        }

        updateNavigatorPill(qId, isAnswered);
        updateMobileExamDock();

        // Debounced Auto-save
        clearTimeout(examState.autoSaveTimeout);
        examState.autoSaveTimeout = setTimeout(() => {
            saveSession();
        }, 400);
    }

    // 10. Question Navigator
    function renderNavigator() {
        const grid = document.getElementById('navigator-grid');
        if (!grid || !examState.exam || !examState.exam.questions) return;

        grid.innerHTML = examState.exam.questions.map((q, idx) => {
            const ans = examState.answers[q.id];
            const isAnswered = Boolean(ans && (ans.typed_answer.trim() || ans.image_data));
            return `
                <button type="button" id="nav-btn-${q.id}" onclick="jumpToQuestion(${q.id})" class="h-9 rounded-xl font-bold font-mono text-xs transition active:scale-95 cursor-pointer flex items-center justify-center ${
                    isAnswered ? 'bg-emerald-600 text-white shadow-xs' : 'border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:border-slate-400'
                }">
                    ${q.question_order || idx + 1}
                </button>
            `;
        }).join('');

        updateAnsweredSummary();
    }

    function updateNavigatorPill(qId, isAnswered) {
        const btn = document.getElementById(`nav-btn-${qId}`);
        if (btn) {
            btn.className = `h-9 rounded-xl font-bold font-mono text-xs transition active:scale-95 cursor-pointer flex items-center justify-center ${
                isAnswered ? 'bg-emerald-600 text-white shadow-xs' : 'border border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:border-slate-400'
            }`;
        }
        updateAnsweredSummary();
    }

    function updateAnsweredSummary() {
        if (!examState.exam || !examState.exam.questions) return;
        const total = examState.exam.questions.length;
        const answered = examState.exam.questions.filter(q => {
            const a = examState.answers[q.id];
            return Boolean(a && (a.typed_answer.trim() || a.image_data));
        }).length;

        const summary = document.getElementById('nav-answered-summary');
        if (summary) summary.textContent = `${answered} / ${total} Answered`;
    }

    window.jumpToQuestion = function(qId, triggerVibrate = true) {
        if (triggerVibrate) triggerHaptic('light');
        if (examState.exam && examState.exam.questions) {
            const idx = examState.exam.questions.findIndex(q => q.id === qId);
            if (idx !== -1) {
                examState.currentQuestionIndex = idx;
                updateMobileExamDock();
            }
        }
        const card = document.getElementById(`q-card-${qId}`);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.classList.add('ring-2', 'ring-brand-500');
            setTimeout(() => card.classList.remove('ring-2', 'ring-brand-500'), 1500);
        }
    };

    function updateMobileExamDock() {
        if (!examState.exam || !examState.exam.questions || examState.exam.questions.length === 0) return;
        const total = examState.exam.questions.length;
        const idx = examState.currentQuestionIndex || 0;
        const currentQ = examState.exam.questions[idx];
        const isAnswered = currentQ && examState.answers[currentQ.id] && 
            Boolean(examState.answers[currentQ.id].typed_answer.trim() || examState.answers[currentQ.id].image_data);

        const indicator = document.getElementById('mobile-exam-q-indicator');
        if (indicator) {
            indicator.innerHTML = `<span>Q ${idx + 1} of ${total}</span>${isAnswered ? ' <span class="text-emerald-500 font-bold text-[10px]">✓</span>' : ''}`;
        }

        const prevBtn = document.getElementById('btn-mobile-prev-q');
        if (prevBtn) {
            if (idx === 0) {
                prevBtn.classList.add('opacity-40', 'pointer-events-none');
            } else {
                prevBtn.classList.remove('opacity-40', 'pointer-events-none');
            }
        }

        const nextLabel = document.getElementById('btn-mobile-next-label');
        const nextArrow = document.getElementById('btn-mobile-next-arrow');
        if (nextLabel && nextArrow) {
            if (idx === total - 1) {
                nextLabel.textContent = 'Submit';
                nextArrow.textContent = '🚀';
            } else {
                nextLabel.textContent = 'Next';
                nextArrow.textContent = '→';
            }
        }
    }

    function goToPrevQuestion() {
        if (!examState.exam || !examState.exam.questions) return;
        if (examState.currentQuestionIndex > 0) {
            examState.currentQuestionIndex--;
            const prevQ = examState.exam.questions[examState.currentQuestionIndex];
            if (prevQ) jumpToQuestion(prevQ.id);
        }
    }

    function goToNextQuestion() {
        if (!examState.exam || !examState.exam.questions) return;
        const total = examState.exam.questions.length;
        if (examState.currentQuestionIndex < total - 1) {
            examState.currentQuestionIndex++;
            const nextQ = examState.exam.questions[examState.currentQuestionIndex];
            if (nextQ) jumpToQuestion(nextQ.id);
        } else {
            triggerHaptic('medium');
            openSubmitConfirmModal();
        }
    }

    function initMobileExamControls() {
        const prevBtn = document.getElementById('btn-mobile-prev-q');
        const nextBtn = document.getElementById('btn-mobile-next-q');

        prevBtn?.addEventListener('click', () => {
            goToPrevQuestion();
        });

        nextBtn?.addEventListener('click', () => {
            goToNextQuestion();
        });

        const container = document.getElementById('exam-questions-container');
        if (container) {
            let touchStartX = 0;
            let touchStartY = 0;
            let isFormInputTouch = false;

            container.addEventListener('touchstart', (e) => {
                // Ignore gestures initiated inside editable inputs or interactive elements
                if (e.target.closest('textarea, input, select, button, label, .no-swipe')) {
                    isFormInputTouch = true;
                    return;
                }
                isFormInputTouch = false;
                if (e.changedTouches && e.changedTouches.length) {
                    touchStartX = e.changedTouches[0].screenX;
                    touchStartY = e.changedTouches[0].screenY;
                }
            }, { passive: true });

            container.addEventListener('touchend', (e) => {
                if (isFormInputTouch) return;
                if (!e.changedTouches || !e.changedTouches.length) return;
                const touchEndX = e.changedTouches[0].screenX;
                const touchEndY = e.changedTouches[0].screenY;
                const diffX = touchEndX - touchStartX;
                const diffY = touchEndY - touchStartY;

                // Threshold: at least 60px horizontal flick, horizontal dominates vertical
                if (Math.abs(diffX) > 60 && Math.abs(diffX) > Math.abs(diffY) * 1.5) {
                    if (diffX < 0) {
                        goToNextQuestion();
                    } else {
                        goToPrevQuestion();
                    }
                }
            }, { passive: true });
        }
    }

    // 11. Submission Confirmation Dialog
    function openSubmitConfirmModal() {
        const modal = document.getElementById('submit-confirm-modal');
        if (!modal || !examState.exam || !examState.exam.questions) return;

        const total = examState.exam.questions.length;
        const answered = examState.exam.questions.filter(q => {
            const a = examState.answers[q.id];
            return Boolean(a && (a.typed_answer.trim() || a.image_data));
        }).length;
        const unanswered = total - answered;

        const warning = document.getElementById('modal-unanswered-warning');
        const countEl = document.getElementById('modal-unanswered-count');
        if (unanswered > 0) {
            countEl.textContent = unanswered;
            warning.classList.remove('hidden');
        } else {
            warning.classList.add('hidden');
        }

        modal.classList.remove('hidden');

        document.getElementById('btn-cancel-modal-submit').onclick = () => {
            modal.classList.add('hidden');
        };
        document.getElementById('btn-confirm-modal-submit').onclick = () => {
            modal.classList.add('hidden');
            submitExam(false);
        };
    }

    function triggerAutoSubmit() {
        submitExam(true);
    }

    // 12. Submit Exam Answers with Fault-Tolerant Auto-Retry & Emergency Export
    async function generateEmergencySquireFile() {
        const clientTimestamp = new Date(getServerNow()).toISOString();
        const answersList = examState.lastPayloadAnswers || examState.exam.questions.map(q => {
            const a = examState.answers[q.id] || {};
            return {
                question_id: q.id,
                typed_answer: a.typed_answer || '',
                image_data: a.image_data || ''
            };
        });

        const cleanRoll = (examState.student.roll || '').trim().toUpperCase();
        const rawMsg = `${examState.code.trim().toUpperCase()}:${cleanRoll}:${clientTimestamp}:${answersList.length}`;

        let integrityHash = '';
        try {
            const msgBuffer = new TextEncoder().encode(rawMsg);
            const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            integrityHash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        } catch (e) {
            let hash = 0;
            for (let i = 0; i < rawMsg.length; i++) {
                hash = ((hash << 5) - hash) + rawMsg.charCodeAt(i);
                hash |= 0;
            }
            integrityHash = 'sha256fallback_' + Math.abs(hash).toString(16);
        }

        const now = getServerNow();
        const timeTakenSecs = examState.lastTimeTakenSecs || Math.max(1, Math.round((now - (examState.session?.start_time || now)) / 1000));

        const emergencyPayload = {
            exam_code: examState.code,
            student_name: examState.student.name,
            roll_number: cleanRoll,
            section: examState.student.section || '',
            time_taken_seconds: timeTakenSecs,
            client_timestamp: clientTimestamp,
            answers: answersList,
            integrity_hash: integrityHash
        };

        const blob = new Blob([JSON.stringify(emergencyPayload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${examState.code}_${cleanRoll}_emergency_submission.squire`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('Emergency submission file (.squire) downloaded! Hand this to your teacher.', 'success', 6000);
    }

    function openRetryEmergencyModal(attempt, maxAttempts, delaySecs, isFinal = false) {
        const modal = document.getElementById('retry-emergency-modal');
        if (!modal) return;

        const titleEl = document.getElementById('retry-modal-title');
        const descEl = document.getElementById('retry-modal-desc');
        const iconEl = document.getElementById('retry-icon-container');

        if (isFinal) {
            titleEl.textContent = 'Submission Interrupted';
            descEl.innerHTML = 'Unable to establish connection to the examination server after multiple attempts. <strong>Please download your Emergency Submission file below</strong> and give it to your instructor.';
            iconEl.innerHTML = '⚠️';
            iconEl.className = "w-14 h-14 mx-auto rounded-full bg-rose-100 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center text-2xl";
        } else {
            titleEl.textContent = 'Connecting & Submitting Answers...';
            descEl.innerHTML = `Network was interrupted. Retrying in <span id="retry-countdown" class="font-bold font-mono text-amber-600 dark:text-amber-400">${delaySecs}</span>s (Attempt <span id="retry-attempt-num" class="font-bold">${attempt}</span> of ${maxAttempts})...`;
            iconEl.innerHTML = '⏳';
            iconEl.className = "w-14 h-14 mx-auto rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center text-2xl";
        }

        modal.classList.remove('hidden');

        document.getElementById('btn-download-emergency-squire').onclick = () => {
            generateEmergencySquireFile();
        };

        document.getElementById('btn-manual-retry-now').onclick = () => {
            if (examState.retryInterval) clearInterval(examState.retryInterval);
            attemptSubmissionNetworkCall();
        };

        document.getElementById('btn-close-retry-modal').onclick = () => {
            if (examState.retryInterval) clearInterval(examState.retryInterval);
            modal.classList.add('hidden');
            examState.isSubmitting = false;
            const submitBtn = document.getElementById('btn-trigger-submit');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<span>Submit Exam 🚀</span>`;
            }
        };
    }

    function startAutoRetrySequence(attempt = 1) {
        const maxAttempts = 4;
        const delays = [2, 5, 10, 20];

        if (attempt > maxAttempts) {
            openRetryEmergencyModal(maxAttempts, maxAttempts, 0, true);
            return;
        }

        const delay = delays[attempt - 1] || 10;
        openRetryEmergencyModal(attempt, maxAttempts, delay, false);

        let remaining = delay;
        const countdownEl = document.getElementById('retry-countdown');
        const progressEl = document.getElementById('retry-progress-bar');

        if (examState.retryInterval) clearInterval(examState.retryInterval);
        examState.retryInterval = setInterval(() => {
            remaining--;
            if (countdownEl) countdownEl.textContent = remaining;
            if (progressEl) {
                const pct = Math.max(0, Math.min(100, Math.round(((delay - remaining) / delay) * 100)));
                progressEl.style.width = `${pct}%`;
            }

            if (remaining <= 0) {
                clearInterval(examState.retryInterval);
                attemptSubmissionNetworkCall(attempt);
            }
        }, 1000);
    }

    async function attemptSubmissionNetworkCall(attempt = 1) {
        try {
            const res = await fetch(`/api/exams/${examState.code}/submit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    student_name: examState.student.name,
                    roll_number: examState.student.roll,
                    section: examState.student.section || '',
                    time_taken_seconds: examState.lastTimeTakenSecs,
                    answers: examState.lastPayloadAnswers
                })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                const errMsg = err.detail || `Server status ${res.status}`;
                if (res.status === 413 || res.status === 400) {
                    const error = new Error(errMsg);
                    error.nonRetriable = true;
                    throw error;
                }
                throw new Error(errMsg);
            }

            const data = await res.json();

            // Succeeded!
            if (examState.retryInterval) clearInterval(examState.retryInterval);
            document.getElementById('retry-emergency-modal')?.classList.add('hidden');
            clearSession(examState.code);
            window.onbeforeunload = null;

            showSubmissionReceipt(data, examState.lastTimeTakenSecs);
            triggerHaptic('success');
            showToast('Exam submitted successfully! Receipt generated.', 'success');
        } catch (err) {
            console.warn(`Submission attempt ${attempt} failed:`, err);
            const msg = err.message || '';
            const isNonRetriable = err.nonRetriable ||
                msg.includes('already exists') ||
                msg.includes('not currently active') ||
                msg.includes('deadline has passed') ||
                msg.includes('exceeds 12MB limit') ||
                msg.includes('12MB');

            if (isNonRetriable) {
                if (examState.retryInterval) clearInterval(examState.retryInterval);
                document.getElementById('retry-emergency-modal')?.classList.add('hidden');
                examState.isSubmitting = false;
                const submitBtn = document.getElementById('btn-trigger-submit');
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = `<span>Submit Exam 🚀</span>`;
                }
                triggerHaptic('error');
                showToast(msg, 'error', 6000);
            } else {
                startAutoRetrySequence(attempt + 1);
            }
        }
    }

    async function submitExam(isAutoSubmit = false) {
        if (examState.isSubmitting) return;
        examState.isSubmitting = true;
        triggerHaptic('medium');

        if (examState.timerInterval) clearInterval(examState.timerInterval);

        const submitBtn = document.getElementById('btn-trigger-submit');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<span>Submitting... ⏳</span>`;
        }

        const now = getServerNow();
        const timeTakenSecs = Math.max(1, Math.round((now - examState.session.start_time) / 1000));

        const payloadAnswers = examState.exam.questions.map(q => {
            const a = examState.answers[q.id] || {};
            return {
                question_id: q.id,
                typed_answer: a.typed_answer || '',
                image_data: a.image_data || ''
            };
        });

        examState.lastPayloadAnswers = payloadAnswers;
        examState.lastTimeTakenSecs = timeTakenSecs;

        // If currently offline, jump directly into retry modal
        if (!navigator.onLine) {
            startAutoRetrySequence(1);
            return;
        }

        await attemptSubmissionNetworkCall(1);
    }

    // 13. Post-Submission Confirmation Receipt
    function showSubmissionReceipt(subData, timeTakenSecs) {
        showView('receipt-view');

        document.getElementById('receipt-student-name').textContent = subData.student_name || examState.student.name;
        document.getElementById('receipt-roll').textContent = subData.roll_number || examState.student.roll;
        document.getElementById('receipt-time').textContent = new Date().toLocaleString();

        const mins = Math.floor(timeTakenSecs / 60);
        const secs = timeTakenSecs % 60;
        document.getElementById('receipt-duration').textContent = `${mins}m ${secs}s`;

        document.getElementById('btn-receipt-check-scorecard').onclick = () => {
            lookupScorecard(subData.roll_number || examState.student.roll);
        };
    }

    // 14. Graded Result / Scorecard Lookup
    function promptScorecardLookup() {
        const defaultRoll = examState.student.roll || '';
        const roll = prompt('Enter your Roll Number / Student ID to check your result:', defaultRoll);
        if (roll && roll.trim()) {
            lookupScorecard(roll.trim().toUpperCase());
        }
    }

    async function lookupScorecard(rollNumber) {
        showToast('Checking graded scorecard...', 'info', 1500);
        try {
            const res = await fetch(`/api/exams/${examState.code}/result?roll_number=${encodeURIComponent(rollNumber)}`);
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Result not found');
            }

            const data = await res.json();

            if (data.status === 'pending_evaluation') {
                showView('receipt-view');
                document.getElementById('receipt-student-name').textContent = data.student_name;
                document.getElementById('receipt-roll').textContent = data.roll_number;
                document.getElementById('receipt-time').textContent = new Date(data.submitted_at).toLocaleString();
                const mins = Math.floor(data.time_taken_seconds / 60);
                const secs = data.time_taken_seconds % 60;
                document.getElementById('receipt-duration').textContent = `${mins}m ${secs}s`;
                showToast('Your submission is recorded and awaiting instructor grading.', 'info', 4000);
                return;
            }

            if (data.status === 'published') {
                renderScorecardView(data);
                showToast('Graded scorecard loaded! 🎉', 'success');
            }
        } catch (err) {
            showToast('Result lookup: ' + err.message, 'error');
        }
    }

    function renderScorecardView(result) {
        showView('result-view');

        document.getElementById('scorecard-exam-code').textContent = examState.code;
        document.getElementById('scorecard-exam-title').textContent = (examState.exam && examState.exam.title) || 'Digital Examination';
        document.getElementById('scorecard-total-awarded').textContent = result.total_score;
        document.getElementById('scorecard-total-max').textContent = result.total_marks;
        document.getElementById('scorecard-percentage').textContent = `${result.percentage}%`;

        document.getElementById('scorecard-student-name').textContent = result.student_name;
        document.getElementById('scorecard-roll').textContent = result.roll_number;

        const secEl = document.getElementById('scorecard-section');
        const secWrap = document.getElementById('scorecard-section-wrapper');
        if (result.section) {
            secEl.textContent = result.section;
            secWrap.style.display = 'inline';
        } else {
            secWrap.style.display = 'none';
        }

        const fbCard = document.getElementById('scorecard-overall-feedback-card');
        const fbText = document.getElementById('scorecard-overall-feedback');
        if (result.feedback && result.feedback.trim()) {
            fbText.textContent = result.feedback;
            fbCard.classList.remove('hidden');
        } else {
            fbCard.classList.add('hidden');
        }

        // Questions breakdown
        const container = document.getElementById('scorecard-questions-breakdown');
        if (!container) return;

        container.innerHTML = (result.questions || []).map((q, idx) => {
            const hasImage = Boolean(q.image_data && q.image_data.startsWith('data:image/'));
            return `
                <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200/80 dark:border-slate-700/80 p-5 shadow-xs space-y-3">
                    <div class="flex items-start justify-between gap-3 border-b border-slate-100 dark:border-slate-700/80 pb-2.5">
                        <div class="flex items-start space-x-2.5">
                            <span class="w-6 h-6 rounded-full bg-brand-100 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                                ${q.question_order || idx + 1}
                            </span>
                            <p class="text-sm font-semibold text-slate-900 dark:text-white leading-relaxed">
                                ${escapeHtml(q.question_text)}
                            </p>
                        </div>
                        <div class="text-right shrink-0 font-mono">
                            <span class="text-xs text-slate-400">Awarded: </span>
                            <span class="text-sm font-bold text-emerald-600 dark:text-emerald-400">${q.marks_awarded !== null ? q.marks_awarded : '--'} / ${q.marks} pts</span>
                        </div>
                    </div>

                    <!-- Answers Provided -->
                    <div class="space-y-2 text-xs">
                        ${q.typed_answer ? `
                            <div class="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800 text-slate-800 dark:text-slate-200 whitespace-pre-wrap">
                                ${escapeHtml(q.typed_answer)}
                            </div>
                        ` : ''}

                        ${hasImage ? `
                            <div class="flex items-center space-x-3 p-2 rounded-xl border border-slate-200 dark:border-slate-700">
                                <img src="${q.image_data}" alt="Answer sheet" onclick="openStudentPhotoZoom('${q.image_data}')" class="w-14 h-14 object-cover rounded-lg cursor-pointer hover:scale-105 transition">
                                <div>
                                    <p class="font-bold text-slate-800 dark:text-slate-200">Handwritten Answer Sheet</p>
                                    <button type="button" onclick="openStudentPhotoZoom('${q.image_data}')" class="text-brand-600 dark:text-brand-400 font-semibold hover:underline">
                                        🔍 Click to view full image
                                    </button>
                                </div>
                            </div>
                        ` : ''}
                    </div>

                    <!-- Question Feedback -->
                    ${q.feedback ? `
                        <div class="p-3 rounded-xl bg-amber-50/70 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-900/60 text-xs text-amber-900 dark:text-amber-200">
                            <strong>Teacher Comment:</strong> ${escapeHtml(q.feedback)}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    }

    // 15. Student Photo Zoom Modal & Image Rotation Inspector
    let studentPhotoRotation = 0;

    window.openStudentPhotoZoom = function(src) {
        const modal = document.getElementById('student-photo-zoom-modal');
        const img = document.getElementById('student-photo-zoom-img');
        if (!modal || !img) return;
        studentPhotoRotation = 0;
        img.style.transform = 'rotate(0deg)';
        img.src = src;
        modal.classList.remove('hidden');
    };

    document.getElementById('btn-rotate-student-photo')?.addEventListener('click', () => {
        const img = document.getElementById('student-photo-zoom-img');
        if (!img) return;
        studentPhotoRotation = (studentPhotoRotation + 90) % 360;
        img.style.transform = `rotate(${studentPhotoRotation}deg)`;
        triggerHaptic('light');
    });

    document.getElementById('btn-reset-student-photo')?.addEventListener('click', () => {
        const img = document.getElementById('student-photo-zoom-img');
        if (!img) return;
        studentPhotoRotation = 0;
        img.style.transform = 'rotate(0deg)';
        triggerHaptic('light');
    });

    document.getElementById('close-student-photo-zoom')?.addEventListener('click', () => {
        document.getElementById('student-photo-zoom-modal')?.classList.add('hidden');
    });

    // Backdrop dismissal
    document.getElementById('student-photo-zoom-modal')?.addEventListener('click', (e) => {
        const modal = document.getElementById('student-photo-zoom-modal');
        const stage = document.getElementById('student-photo-zoom-stage');
        if (e.target === modal || e.target === stage) {
            modal.classList.add('hidden');
        }
    });

    // Global Escape key listener for student exam room
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const zoomModal = document.getElementById('student-photo-zoom-modal');
            if (zoomModal && !zoomModal.classList.contains('hidden')) {
                zoomModal.classList.add('hidden');
                return;
            }
            const confirmModal = document.getElementById('submit-confirm-modal');
            if (confirmModal && !confirmModal.classList.contains('hidden')) {
                confirmModal.classList.add('hidden');
                return;
            }
            const retryModal = document.getElementById('retry-emergency-modal');
            if (retryModal && !retryModal.classList.contains('hidden')) {
                retryModal.classList.add('hidden');
                return;
            }
        }
    });

    // Utility
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Bootstrap
    function bootstrap() {
        initNetworkMonitor();
        initExamRoom();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }

})();
