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
        isSubmitting: false
    };

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

    // 4. Client-Side Pure HTML5 Canvas Photo Compression (~200-250KB WebP/JPEG)
    // Zero external libraries. Uses native browser standard Canvas & FileReader.
    async function compressAnswerPhoto(file, maxDimension = 1600, targetMaxBytes = 250 * 1024) {
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

                    // 1. Maintain aspect ratio within maxDimension
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

                    // 4. Adaptive quality stepping to guarantee target bytes (~200-250KB)
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

            // Check if student already has a saved in-progress session
            const savedSession = loadSession(examState.code);
            if (savedSession && savedSession.status === 'in_progress') {
                const now = Date.now();
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
        const startTime = Date.now();
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
        examState.session.last_saved = Date.now();
        try {
            localStorage.setItem(`exam_session_${examState.code}`, JSON.stringify(examState.session));
            const indicator = document.getElementById('save-status-indicator');
            if (indicator) {
                const now = new Date();
                indicator.textContent = `✓ Saved locally at ${now.toLocaleTimeString()}`;
            }
        } catch (e) {
            console.warn('localStorage full or inaccessible:', e);
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

    // 8. Wall-Clock Synchronized Countdown Timer
    function startCountdownTimer() {
        if (examState.timerInterval) clearInterval(examState.timerInterval);

        function updateTimer() {
            const now = Date.now();
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

            // Urgency color cues
            if (totalSecs <= 60) {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full bg-rose-600 text-white font-mono font-extrabold text-xs sm:text-sm animate-pulse shadow-md";
            } else if (totalSecs <= 300) {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full bg-amber-100 dark:bg-amber-950/80 text-amber-900 dark:text-amber-200 border border-amber-300 font-mono font-bold text-xs sm:text-sm";
            } else {
                pill.className = "flex items-center space-x-1.5 px-3.5 py-1.5 rounded-full border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 shadow-xs font-mono font-bold text-xs sm:text-sm text-slate-800 dark:text-slate-100";
            }
        }

        updateTimer();
        examState.timerInterval = setInterval(updateTimer, 1000);
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
                        <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300">
                            Typed Answer:
                        </label>
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

    window.jumpToQuestion = function(qId) {
        const card = document.getElementById(`q-card-${qId}`);
        if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.classList.add('ring-2', 'ring-brand-500');
            setTimeout(() => card.classList.remove('ring-2', 'ring-brand-500'), 1500);
        }
    };

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

    // 12. Submit Exam Answers
    async function submitExam(isAutoSubmit = false) {
        if (examState.isSubmitting) return;
        examState.isSubmitting = true;

        if (examState.timerInterval) clearInterval(examState.timerInterval);

        const submitBtn = document.getElementById('btn-trigger-submit');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `<span>Submitting... ⏳</span>`;
        }

        const now = Date.now();
        const timeTakenSecs = Math.max(1, Math.round((now - examState.session.start_time) / 1000));

        const payloadAnswers = examState.exam.questions.map(q => {
            const a = examState.answers[q.id] || {};
            return {
                question_id: q.id,
                typed_answer: a.typed_answer || '',
                image_data: a.image_data || ''
            };
        });

        try {
            const res = await fetch(`/api/exams/${examState.code}/submit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    student_name: examState.student.name,
                    roll_number: examState.student.roll,
                    section: examState.student.section || '',
                    time_taken_seconds: timeTakenSecs,
                    answers: payloadAnswers
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Submission failed');
            }

            const data = await res.json();

            // Clear session upon verified submission
            clearSession(examState.code);
            window.onbeforeunload = null;

            // Show confirmation receipt
            showSubmissionReceipt(data, timeTakenSecs);
            showToast('Exam submitted successfully! Receipt generated.', 'success');
        } catch (err) {
            examState.isSubmitting = false;
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<span>Submit Exam 🚀</span>`;
            }
            showToast('Submission error: ' + err.message, 'error', 5000);
        }
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

    // 15. Student Photo Zoom Modal
    window.openStudentPhotoZoom = function(src) {
        const modal = document.getElementById('student-photo-zoom-modal');
        const img = document.getElementById('student-photo-zoom-img');
        if (!modal || !img) return;
        img.src = src;
        modal.classList.remove('hidden');
    };

    document.getElementById('close-student-photo-zoom')?.addEventListener('click', () => {
        document.getElementById('student-photo-zoom-modal')?.classList.add('hidden');
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
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initExamRoom);
    } else {
        initExamRoom();
    }

})();
