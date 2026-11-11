<p align="center">
  <img src="./assets/hero-banner.svg" alt="Setu Voice Banner" width="100%" />
</p>

<h3 align="center">Zero-App, Voice-First Return-Freight Exchange</h3>

<p align="center">
  Connecting empty return trucks with agricultural cargo across regional Indian languages over a standard phone call.<br />
  Built by <strong>Varshith Kumar Anand</strong> and teammate for the <strong>Great Indian AI Internship Challenge</strong>.
</p>

---

## Test the Live Deployment

Dial **`08047289156`** from any basic phone or smartphone to speak naturally in your preferred regional language.

> **The phone call itself is the login.** No app downloads, no OTP forms, no typing. Your Caller ID automatically identifies your profile.

**Supported Languages:** Kannada, Hindi, Telugu, Tamil, Marathi, Gujarati, Bengali, Malayalam, and Indian English.

| Role | Example Language | Sample Call Phrase |
| :--- | :--- | :--- |
| **Truck Driver** | Kannada | *"Nanna gaadi Bengaluru ge hogbeku, 10 tonne capacity ide."* |
| **Farmer / Shipper** | Hindi | *"Mujhe Pune 5 tonne pyaaz bhejna hai, kiraya 12000 rupaye."* |
| **Driver / Shipper** | Telugu | *"Naa lorry Hyderabad veltundi, 12 tonne capacity undi."* |
| **Driver / Shipper** | Tamil | *"En truck Chennai poguthu, 8 tonne load venum."* |

---

## How Setu Works

Over 40% of commercial trucks return completely empty from wholesale agricultural markets, while farmers lose up to 30% of their produce margins to transport brokers. Setu eliminates both inefficiencies in a single natural voice conversation in any regional language.

<p align="center">
  <img src="./assets/how-it-works.svg" alt="How Setu Works" width="100%" />
</p>

---

## Visual System Architecture

Setu streams live 8kHz cellular PCM audio over bidirectional WebSockets between Exotel and our multilingual AI voice pipeline:

<p align="center">
  <img src="./assets/architecture.svg" alt="Setu Real-Time Architecture" width="100%" />
</p>

---

## Core Models & Pipeline

| Component | Model / Service | Role in Setu |
| :--- | :--- | :--- |
| **Telephony Gateway** | **Exotel AgentStream** | Streams bidirectional 8kHz 16-bit PCM audio over WebSockets (`/exotel/ws`). |
| **Speech-to-Text (STT)** | **Gnani Prisma v3.0** (`prisma-v3.0`) | Transcribes noisy mobile calls in real time across regional Indian languages (`indic-auto`). |
| **Conversational Brain** | **Gemini 2.5 Flash** | Automatically matches the caller's regional dialect, extracts route/tonnage/pricing, and pairs trucks with harvest. |
| **Text-to-Speech (TTS)** | **Gnani Timbre v2.5** (`timbre-v2.5`) | Synthesizes natural regional voices (*Kaveri*, *Bhavna*, *Lavanya*, *Oviya*, *Devika*, *Nalini*) across all supported Indian languages. |
