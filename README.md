# Calculater 🧮

> *"We tried our best." — Calculater Corp, Est. 1987*

A single-file retro scientific calculator web app with maximum chaos energy.

## Features

### 🔢 Scientific Calculator
Full keypad: sin, cos, tan, log, ln, √, x^n, π, e, parentheses, +, −, ×, ÷, %, 0–9, C, DEL.

### 🎯 Multiple Choice Engine
Pressing `=` **never** shows the answer directly. Instead:
1. 4 choices appear: **A, B, C** (true answer + 2 distractors, shuffled), **D** (none of the above)
2. Clicking a choice replaces it with **"Are you sure your answer is correct?"**
3. Confirming opens the **5-Paragraph Essay Modal**

### 📝 Essay Interrogation
- Must write a "minimum 5 paragraph" justification
- **Secret pass phrase**: include `because i am stupid` (case-insensitive) anywhere in the essay
- Without it → **all state is wiped**, start over
- With it → true answer is revealed immediately

### 🤖 Robi — Ragebait AI Chatbot
- Powered by **Groq API + Llama 3.3 70B**
- Enter your `GROQ_API_KEY` inside the chat drawer
- Robi is sassy, condescending, refuses to help, gives wrong answers confidently
- **First click** inside chat → fullscreen fake ad
- **Each subsequent click** → 20% chance of fullscreen fake ad
- Strictly scoped to the active calculator equation

### 🔒 Paywall / Decrypt Feature
- "Instant Answer (Skip)" button reveals scrambled ciphertext
- Fake SaaS paywall with tier selector + mock credit card form
- Payment always "fails" with a server error

### 💥 Hostile Popup Ad System
- **Timer**: random popup every 10–20 seconds
- **Key press**: 10% chance per button click
- Tiny 8×8px × close button
- 5 rotating ad templates

## Setup

No build step required — it's a single HTML file.

```
open index.html
```

For the Robi chatbot, obtain a [Groq API key](https://console.groq.com/) and paste it into the input field inside the chat drawer.

## State Machine

```
IDLE → (press =) → CHOICES → (click choice) → CONFIRM → (click again) → ESSAY
  ↑                                                                          |
  └────────────── (bad essay: WIPED, auto-resets) ──────────────────────────┘
                                                   (good essay: SOLVED)
```
