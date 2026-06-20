# Dokumentasi Fitur & Sistem: Hermes YouTube Agent

Dokumen ini menyajikan rekapitulasi menyeluruh mengenai arsitektur, alur kerja, dan seluruh fitur yang telah dikembangkan dalam aplikasi **Hermes YouTube Agent**.

---

## ── Arsitektur & Teknologi Utama ──

Aplikasi dirancang dengan arsitektur modern berkinerja tinggi:
*   **Backend**: FastAPI (Python) — asinkron, cepat, dan terstruktur.
*   **Database**: MySQL (SQLAlchemy Async ORM) untuk penyimpanan data persisten & Alembic untuk manajemen migrasi skema.
*   **Task Queue & Scheduler**: Celery & Redis — memproses unggahan video, pembuatan metadata AI, dan pemindaian folder di background secara asinkron tanpa mengganggu web utama.
*   **Frontend**: HTML5, Vanilla CSS, dan Javascript interaktif dengan visualisasi data grafik berbasis **Chart.js**.
*   **AI Integration**: OpenRouter Gateway dengan fallback chain (Llama 3.3, Mistral, Gemma) untuk pembuatan metadata dinamis.
*   **Telegram Bot API**: Sebagai pusat kendali operasional nirkabel (interaktif dua arah).

---

## ── Modul & Fitur Utama Sistem ──

### 1. Ingest Video & Pemantauan Folder (OMV NAS Integration)
*   **Watch Folder Scanner**: Background task Celery (`scan_omv_storage`) memantau direktori NFS/OMV (diatur di `.env`).
*   **Pemetaan Otomatis**: Subfolder di dalam OMV (misalnya `/mnt/omv-videos/tokyo_lofi/`) secara otomatis dipetakan ke channel YouTube yang bersangkutan.
*   **Anti-Duplikasi (SHA-256 Checksum)**: Setiap video dihitung nilai hash SHA-256-nya sebelum masuk antrean. Sistem otomatis menolak file yang sama untuk menghindari unggahan ganda meskipun file telah diganti namanya.
*   **Staging Safe-Copy**: Video disalin terlebih dahulu ke direktori staging lokal dan diverifikasi kembali checksum-nya sebelum diproses lebih lanjut.

### 2. Alur Kerja Unggahan Hybrid & Sequential (Sequential Upload Flow)
*   **Idempotency & Atomic State Machine**: Transisi status antrean diatur secara ketat melalui mesin status:
    `PENDING` ➔ `METADATA_READY` ➔ `AWAITING_APPROVAL` ➔ `SCHEDULED` ➔ `UPLOADING` ➔ `PRIVATE_UPLOADED` ➔ `THUMBNAIL_ATTACHED` ➔ `SCHEDULED_PUBLIC` ➔ `DONE`.
*   **Upload Draf Terlebih Dahulu**: Video selalu diunggah ke YouTube API sebagai **Private (Draf)** di background.
*   **Mekanisme Persetujuan Terjadwal**:
    *   *Channel TRUSTED*: Otomatis dijadwalkan publik sesuai slot waktu optimal.
    *   *Channel NEW*: Video tetap aman sebagai Private di YouTube, status antrean berada di `AWAITING_APPROVAL`. Begitu disetujui (via Web/Telegram), Hermes akan memanggil API YouTube untuk menjadwalkannya.
*   **Sequential Upload Enforcement**: Pembatasan concurrency worker Celery ke **1 worker** menjamin video diunggah satu per satu secara berurutan guna menghemat bandwidth server dan menjaga batas kuota API YouTube.
*   **GCP Quota Tracker**: Sistem memantau dan mencatat penggunaan kuota harian API YouTube (1650 unit per upload video) secara real-time untuk mencegah kegagalan akibat kuota habis.

### 3. Pola Metadata Kustom & AI Playground (A/B Testing)
*   **Metadata Patterns**: Pengguna dapat membuat, menyunting, dan menghapus pola/gaya penulisan judul dan deskripsi video (misalnya pola Cozy Lofi, Phonk Drift, dll) per channel.
*   **LLM Playground Simulation**: Antarmuka bagi pengguna untuk mengetik draf judul/deskripsi template, lalu menyimulasikannya secara real-time ke Hermes AI untuk melihat hasil jadinya sebelum diaktifkan secara otomatis.
*   **Pencegahan Judul Duplikat**: AI diinstruksikan untuk menganalisis nama file dan menghasilkan teks yang bervariasi serta unik untuk setiap video.

### 4. Dashboard Analitik Premium & Chart Performa
*   **Metrik Global**: Menampilkan total Subscribers, estimasi Views, dan rata-rata CTR secara real-time.
*   **Chart.js Integration**:
    *   *Grafik Garis (Line Chart)*: Tren performa penayangan harian channel dalam 28 hari terakhir.
    *   *Grafik Batang A/B Testing*: Membandingkan performa views dan CTR video secara visual berdasarkan **Pola Metadata** yang digunakan. Memudahkan Anda melihat template metadata mana yang mendatangkan audiens terbanyak.
*   **Riwayat Video Terbit**: Menyajikan tabel histori video yang telah sukses dipublikasikan di YouTube beserta link tontonan langsung.

### 5. Komunikasi Interaktif Dua Arah via Telegram Bot
*   **Pemisahan Bot**: Menggunakan bot Telegram terpisah khusus untuk operasional aplikasi (misalnya `@HermesUploadManagerBot`).
*   **Notifikasi & Tombol Inline Interaktif**:
    *   *Persetujuan Unggahan*: Bot mengirimkan detail metadata video yang siap dipublikasikan beserta tombol inline `[ ✅ Setujui ]` dan `[ ❌ Tolak ]`.
    *   *Persetujuan Thumbnail*: Bot mengirimkan foto pratinjau thumbnail hasil olahan AI beserta tombol `[ ✅ Setujui ]` dan `[ 🔄 Generate Ulang ]`.
*   **Webhook Handler**: Setiap klik tombol pada aplikasi Telegram Anda ditangkap secara real-time oleh endpoint `/api/queue/telegram-webhook` pada backend aplikasi FastAPI untuk langsung memproses perubahan status video.

### 6. Pengerasan Keamanan (Security Hardening)
*   **Envelope Encryption**: Kredensial OAuth YouTube (Client ID, Client Secret, Refresh Token) dienkripsi menggunakan metode envelope:
    `Master Key (variabel lingkungan) ➔ Data Key Kustom (unik per channel di DB) ➔ Kredensial OAuth`.
*   **Key Rotation**: Tombol rotasi kunci otomatis untuk memperbarui enkripsi kredensial channel secara berkala.
*   **Redis Rate Limiting**: Batasan login pada rute `POST /login` untuk memblokir bot brute-force.
*   **Immutable Audit Logs**: Log audit sistem mencatat seluruh aktivitas sensitif (seperti penambahan channel, rotasi key, dll) dan datanya bersifat *read-only* (tidak dapat diubah/dihapus).
*   **Cookie & HTTP Security Headers**: 
    *   Session cookie menggunakan flag `HttpOnly`, `Secure` (di production), dan `SameSite=Strict`.
    *   Strict Content Security Policy (CSP), X-Frame-Options (Anti-Clickjacking), dan X-Content-Type-Options diaktifkan secara global di tingkat middleware API.
