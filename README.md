# 📚 QuestionBank Studio

**QuestionBank Studio** is a smart, cloud-ready web application designed to eliminate repetitive typing and manual copy-pasting of questions. Upload your existing Word (`.docx`) and PDF (`.pdf`) question papers, automatically extract all serial-numbered questions into a centralized library with exact-match deduplication, select questions into an interactive **Cart**, and download your newly compiled question paper in an editable Word document with a single click.

---

## ✨ Features

- **Automatic Extraction:** Upload one or multiple `.docx` or `.pdf` files. Automatically parses serial numbers (`1.`, `2.`, `Q1.`, `Question 1:`, etc.) and multi-line question descriptions.
- **Manual Question Entry:** Add individual questions directly to your library at any time without uploading a document, complete with Subject, Topic, and custom Source tags.
- **Smart Exact Deduplication:** Repeated questions across past years or manual entries are merged into one entry with an **"🔥 Appeared X times"** counter and a list of all source documents where the question was found.
- **Full-Text Search & Filters:** Instantly search questions by keyword, or filter by Subject, Topic, and Source document.
- **Question Cart (Paper Builder):**
  - Add questions with one click.
  - Reorder questions using **▲ Move Up** and **▼ Move Down** controls to customize your paper's sequence.
  - Persistent cart saved in browser local storage so work is never lost on refresh.
- **Custom Printout Master Template (`Default_page.docx`):** Choose between **Normal** (Letter, 1" margins, Calibri) or **Default Page** (A4 size, compact 0.5" margins, elegant double-line page border, **"The Squire's Way"** diagonal watermark, and Times New Roman). The app directly inherits your master template's exact visual design so question papers come out print-ready!
- **Dual Export Options (Word & PDF):** Choose between downloading as Microsoft Word (`.docx`) with native numbered list styles or as a publication-ready PDF (`.pdf`) document. Download options are available directly on each Question Card, in the Question Cart (Paper Builder), and in the Bulk Selection Bar.
- **1-Click Backup & Restore (JSON):** Export your entire question bank as a portable JSON backup file with one click (`📥 Backup`), or restore and merge questions from any backup file (`📤 Restore`). This makes transferring your local library to the cloud effortless.
- **Cloud Security & Passcode (PIN) Protection:** Secure your public cloud deployment with a master passcode via `APP_PASSWORD`. Protects against unauthorized edits while keeping local offline development friction-free.
- **Dual-Mode Database Architecture:** Runs locally using fast, zero-config SQLite (`questions.db`). When deployed to cloud environments like Render with `DATABASE_URL` configured, seamlessly connects to a free PostgreSQL database (Neon or Supabase) so your question bank persists forever.

---

## 🚀 Quick Start (Local Run)

### 1. Install Dependencies
Make sure you have Python 3.10+ installed:
```bash
pip install -r requirements.txt
```

### 2. Launch the Application
Simply run:
```bash
python run.py
```
This automatically launches your browser and opens the app at `http://127.0.0.1:8000`.

*(Alternatively, run manually via Uvicorn):*
```bash
uvicorn backend.main:app --reload --port 8000
```

---

## ☁️ Cloud Deployment Guide (Render.com + Free Postgres)

### Step 1: Create a Free Forever Cloud Database (Neon or Supabase)
1. Go to [neon.tech](https://neon.tech) (or [supabase.com](https://supabase.com)) and sign up for free (using GitHub or Google).
2. Create a new project (e.g. `questionbank-db`).
3. Copy your connection string (`DATABASE_URL`), which looks like:
   `postgresql://username:password@ep-xyz.aws.neon.tech/neondb?sslmode=require`

### Step 2: Push Your Code to GitHub
1. Create a new private or public repository on [GitHub](https://github.com/new) named `questionbank-studio`.
2. Push your project code:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/questionbank-studio.git
   git branch -M main
   git push -u origin main
   ```

### Step 3: Deploy on Render.com (100% Free)
1. Sign up / Log in to [Render.com](https://render.com).
2. Click **New +** -> **Web Service** -> Select your `questionbank-studio` GitHub repository.
3. Configure the following:
   - **Name:** `questionbank-studio`
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
4. Under **Environment Variables**, add:
   - `DATABASE_URL` = `<Your Neon or Supabase connection string>`
   - `APP_PASSWORD` = `<Your chosen passcode, e.g. squire123>` *(optional but recommended)*
5. Click **Create Web Service**.
6. Render will build and deploy in ~2 minutes, giving you a live URL like `https://questionbank-studio.onrender.com`.

### Step 4: Transfer Existing Local Questions to the Cloud
1. On your local machine at `http://127.0.0.1:8000`, click **📥 Backup** to download `questionbank_backup.json`.
2. Open your live Render URL in your browser, enter your passcode, and click **📤 Restore**.
3. Select your backup file. All your questions, frequencies, and sources are instantly restored to your cloud database!

---

## 🧪 Testing

To run the automated test suite (database adapter, backup/restore, parser, deduplicator, API, Word, and PDF generation tests):
```bash
python -m pytest tests/ -v
```

---

## 📁 Sample Files Included

We have included two ready-to-test past exam papers in the `samples/` directory:
- `samples/Physics_Paper_2022.docx` (10 questions)
- `samples/Physics_Paper_2023.docx` (10 questions, including 4 repeated questions)

Upload both to test the extraction and watch the **Duplicates Merged** counter increase in real time!
