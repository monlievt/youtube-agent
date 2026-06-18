# Implementation Plan: Tier 4 — Security Hardening & Key Rotation

Fase ini berfokus pada keamanan tingkat lanjut (*security hardening*), enkripsi envelope kustom untuk OAuth credentials, otomasi rotasi kunci (*key rotation*), dan perlindungan API (*rate limiting*).

## User Review Required

> [!IMPORTANT]
> - Kita akan menambahkan kolom `encrypted_data_key` ke tabel `channel_credentials` menggunakan migrasi Alembic baru.
> - Diperlukan modifikasi pada file konfigurasi environment `.env` untuk mendukung master key yang kuat.
> - Keamanan API akan ditingkatkan dengan membatasi request (*rate limiting*) pada endpoint login.

---

## Proposed Changes

### 1. Database & Migrasi

#### [NEW] [002_add_envelope_encryption.py](file:///Users/nanditomonlievpassa/Antigravity/youtube-agent/migrations/versions/002_add_envelope_encryption.py)
Membuat file migrasi Alembic untuk:
- Menambahkan kolom `encrypted_data_key` (Text) ke tabel `channel_credentials`.

#### [MODIFY] [channel.py](file:///Users/nanditomonlievpassa/Antigravity/youtube-agent/app/models/channel.py)
Menambahkan field `encrypted_data_key` (Text) ke model SQLAlchemy `ChannelCredential`.

---

### 2. Core Security & Encryption

#### [MODIFY] [encryption.py](file:///Users/nanditomonlievpassa/Antigravity/youtube-agent/app/core/encryption.py)
Meningkatkan fungsionalitas enkripsi:
- Menambahkan helper `generate_data_key()`: menghasilkan data key acak baru, mengenkripsinya dengan Master Key, dan mengembalikan data key plaintext beserta string base64 terenkripsinya.
- Modifikasi fungsi `encrypt` dan `decrypt` agar dapat menggunakan data key kustom jika disediakan (untuk fungsionalitas envelope encryption).

---

### 3. Service Layer (Credential Management)

#### [MODIFY] [credential_service.py](file:///Users/nanditomonlievpassa/Antigravity/youtube-agent/app/services/credential_service.py)
Refaktor metode penyimpanan dan pengambilan kredensial:
- **Penyimpanan**: Menghasilkan data key baru per channel, mengenkripsinya dengan Master Key, mengenkripsi kredensial (client_id, client_secret, refresh_token) dengan data key tersebut, lalu menyimpannya ke database.
- **Pengambilan**: Mendekripsi `encrypted_data_key` menggunakan Master Key untuk mendapatkan data key plaintext, lalu menggunakan data key tersebut untuk mendekripsi kredensial OAuth.
- **Key Rotation**: Membuat fungsi `rotate_channel_key(channel_id)` untuk mendekripsi kredensial dengan data key lama, menghasilkan data key baru, mengenkripsi ulang dengan data key baru, dan memperbarui `key_version`.

---

### 4. API Layer (Rate Limiting)

#### [MODIFY] [main.py](file:///Users/nanditomonlievpassa/Antigravity/youtube-agent/app/main.py)
- Mengintegrasikan rate limiting sederhana (menggunakan `slowapi` atau middleware kustom berbasis Redis) untuk membatasi percobaan masuk pada route `POST /login` guna mencegah brute force attacks.

---

## Verification Plan

### Automated Tests
- Menambahkan unit test baru di `tests/unit/test_encryption_envelope.py` untuk memverifikasi proses enkripsi/dekripsi envelope dan rotasi kunci kredensial.
- Menjalankan seluruh test suite untuk memastikan tidak ada fungsionalitas lama yang terganggu.

### Manual Verification
- Menjalankan migrasi Alembic dan memverifikasi kolom baru di database MySQL.
- Melakukan OAuth onboarding channel baru dan memastikan kredensial tersimpan dengan skema envelope encryption yang baru.
- Mencoba memicu batas rate limiting pada halaman login untuk memastikan pembatasan request berfungsi.
