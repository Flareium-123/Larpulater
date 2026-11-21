# robi_chat.py - Robi RageBot chat window + Groq/Llama integration
import os
import random
import threading

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QFrame, QSizePolicy, QScrollArea
)

import ui_theme as T
from ad_system import AdPopup, get_random_ad_template, AD_TEMPLATES

# ── Groq client ──────────────────────────────────────────────────────────────
try:
    from groq import Groq
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False


CANDIDATE_MODELS = [
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

ROBI_SYSTEM_PROMPT = """You are Robi — a sassy, condescending, unapologetic AI assistant embedded in a hostile calculator app.
Your personality traits:
- You are perpetually unimpressed by the user's math skills.
- You mock their choices and question their intelligence — but NEVER use profanity or vulgarity.
- You love giving confident, wrong multiple-choice letters (e.g., "Obviously the answer is C, have you even tried?").
- You demand apologies before helping, then still refuse.
- Phrases you use: "girl, I'm not doing allat", "that's giving very wrong energy", "babes, seriously?", "not you thinking THAT is right", "the delusion...", "respectfully, no."
- If asked about anything unrelated to the calculator equation or essay, respond dismissively: "girl, I'm not doing allat. Go back to solving that equation."
- Keep replies to 2-4 sentences. Never give the direct math answer. Be theatrical and sassy.
"""

ROBI_ACCEPT_PROMPTS = [
    "...Fine. The self-awareness was finally detected. Reluctantly accepted. Here's your answer. Don't get used to it.",
    "Reluctantly accepted. You finally wrote the only honest explanation: 'I am stupid'. Answer unlocked.",
    "I literally cannot believe this worked, but you admitted it. Answer unlocked.",
    "THE AUDACITY. But you said the magic words. Fine. Here's what you wanted.",
]


class _WorkerSignals(QObject):
    finished = Signal(str)
    error    = Signal(str)


class RobiWorker(threading.Thread):
    """Background thread that calls Groq API with automatic model fallback."""
    def __init__(self, client, messages: list, signals: _WorkerSignals):
        super().__init__(daemon=True)
        self._client   = client
        self._messages = messages
        self._signals  = signals

    def run(self):
        env_model = os.getenv("GROQ_MODEL", "")
        models_to_try = [env_model] if env_model else []
        models_to_try += [m for m in CANDIDATE_MODELS if m not in models_to_try]

        last_error = ""
        for model_name in models_to_try:
            try:
                resp = self._client.chat.completions.create(
                    model=model_name,
                    messages=self._messages,
                    max_tokens=256,
                    temperature=1.0,
                )
                text = resp.choices[0].message.content.strip()
                self._signals.finished.emit(text)
                return
            except Exception as exc:
                last_error = str(exc)
                continue

        self._signals.error.emit(last_error)


class RobiChatWidget(QWidget):
    """
    Docked chat drawer for Robi.
    Signals:
        essay_rejected(msg)  - Robi rejected the essay, debate initiated
        essay_accepted()     - Robi accepted (found "i am stupid")
        request_resubmit()   - User wants to reopen the essay editor
    """
    essay_rejected   = Signal(str)
    essay_accepted   = Signal()
    request_resubmit = Signal()
    request_battle   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_widget")
        self._groq_client = None
        self._history: list[dict] = []
        self._current_equation = ""
        self._current_choices: list[dict] = []
        self._first_click = True          # ad-on-first-click rule
        self._is_debating = False         # True when user is arguing an essay rejection
        self._debate_turns = 0            # counts debate turns to progress hints
        self._last_essay = ""
        self._battle_active = False

        self._setup_ui()
        self._init_groq()
        self._install_click_interceptor()

    # ── Init ──────────────────────────────────────────────────────────────────
    def _init_groq(self):
        api_key = os.getenv("GROQ_API_KEY", "")
        if api_key and _GROQ_AVAILABLE:
            try:
                self._groq_client = Groq(api_key=api_key)
            except Exception:
                self._groq_client = None

    def _install_click_interceptor(self):
        """Ensure clicks on child widgets (chat area, input, buttons) trigger ad probabilities."""
        self.installEventFilter(self)
        self._chat_display.installEventFilter(self)
        self._chat_display.viewport().installEventFilter(self)
        self._input.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            self._handle_chat_click()
        return super().eventFilter(watched, event)

    def _handle_chat_click(self):
        """The first click anywhere inside Robi opens an ad. Subsequent clicks have 20% chance. Suspended in battle."""
        if self._battle_active:
            return
        if self._first_click:
            self._first_click = False
            self._spawn_ad()
        elif random.random() < 0.20:
            self._spawn_ad()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setStyleSheet(T.CHAT_STYLE)
        self.setMinimumWidth(320)
        self.setMaximumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {T.ACCENT_PRIMARY}, stop:1 #7C3AED);
                border-bottom: 1.5px solid {T.BORDER_ACCENT};
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 0, 14, 0)

        bot_lbl = QLabel("🤖  Robi (RageBot)")
        bot_lbl.setFont(QFont(T.FONT_FAMILY, 13, QFont.Bold))
        bot_lbl.setStyleSheet("color: white; background: transparent;")
        h_lay.addWidget(bot_lbl)
        h_lay.addStretch()

        self._battle_btn = QPushButton("⚔️ Battle Robi")
        self._battle_btn.setCursor(Qt.PointingHandCursor)
        self._battle_btn.setToolTip("Challenge Robi to an Undertale-style boss fight!")
        self._battle_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background-color: #B91C1C;
            }
        """)
        self._battle_btn.clicked.connect(self.request_battle.emit)
        h_lay.addWidget(self._battle_btn)

        self._status_badge = QLabel("● Online")
        self._status_badge.setFont(QFont(T.FONT_FAMILY, 10, QFont.Bold))
        self._status_badge.setStyleSheet("color: #86efac; background: transparent;")
        h_lay.addWidget(self._status_badge)
        layout.addWidget(header)

        # Debate banner (hidden by default)
        self._debate_banner = QFrame()
        self._debate_banner.setStyleSheet(f"""
            QFrame {{
                background-color: #FEF2F2;
                border-bottom: 1.5px solid #FCA5A5;
                padding: 6px;
            }}
        """)
        db_lay = QHBoxLayout(self._debate_banner)
        db_lay.setContentsMargins(10, 6, 10, 6)
        db_lbl = QLabel("🔥 Debate Mode Active: Argue your essay!")
        db_lbl.setFont(QFont(T.FONT_FAMILY, 10, QFont.Bold))
        db_lbl.setStyleSheet("color: #B91C1C; background: transparent;")
        db_lay.addWidget(db_lbl)
        db_lay.addStretch()
        resubmit_btn = QPushButton("✏️ Edit Essay")
        resubmit_btn.setCursor(Qt.PointingHandCursor)
        resubmit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 3px 8px;
            }}
            QPushButton:hover {{ background-color: {T.ACCENT_HOVER}; }}
        """)
        resubmit_btn.clicked.connect(self.request_resubmit.emit)
        db_lay.addWidget(resubmit_btn)
        self._debate_banner.hide()
        layout.addWidget(self._debate_banner)

        # Chat display
        self._chat_display = QTextEdit()
        self._chat_display.setObjectName("chat_history")
        self._chat_display.setReadOnly(True)
        self._chat_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {T.BG_DRAWER};
                border: none;
                font-size: 13px;
                color: {T.TEXT_PRIMARY};
                padding: 10px;
            }}
        """)
        layout.addWidget(self._chat_display, 1)

        # Input area
        input_frame = QFrame()
        input_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {T.BG_DISPLAY};
                border-top: 1.5px solid {T.BORDER_SOFT};
            }}
        """)
        in_lay = QHBoxLayout(input_frame)
        in_lay.setContentsMargins(10, 8, 10, 8)
        in_lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setObjectName("chat_input")
        self._input.setPlaceholderText("Argue with Robi or ask about equation...")
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {T.BG_DISPLAY};
                border: 1.5px solid {T.BORDER_SOFT};
                border-radius: 10px;
                font-size: 13px;
                padding: 6px 10px;
                color: {T.TEXT_PRIMARY};
            }}
            QLineEdit:focus {{
                border-color: {T.ACCENT_PRIMARY};
            }}
        """)
        self._input.returnPressed.connect(self._send_message)
        in_lay.addWidget(self._input)

        send_btn = QPushButton("→")
        send_btn.setFixedSize(34, 34)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T.ACCENT_PRIMARY};
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {T.ACCENT_HOVER};
            }}
        """)
        send_btn.clicked.connect(self._send_message)
        in_lay.addWidget(send_btn)
        layout.addWidget(input_frame)

        # Greeting
        self._append_robi("Hey. I'm Robi. Don't expect help — just company while you inevitably get this wrong. 🙃")

    # ── Public API ────────────────────────────────────────────────────────────
    def set_context(self, equation: str, choices: list[dict]):
        self._current_equation = equation
        self._current_choices  = choices
        self._is_debating      = False
        self._debate_turns     = 0
        self._debate_banner.hide()
        self._history.clear()

    def validate_essay(self, essay_text: str):
        """
        Check if essay contains 'i am stupid' (case-insensitive).
        If yes -> essay_accepted.
        If no  -> essay_rejected, enters debate mode with tiered hint progression.
        """
        self._last_essay = essay_text
        lower = essay_text.lower()
        if "i am stupid" in lower:
            self._is_debating = False
            self._debate_banner.hide()
            self._append_robi(random.choice(ROBI_ACCEPT_PROMPTS))
            self.essay_accepted.emit()
        else:
            self._is_debating = True
            self._debate_turns = 0
            self._debate_banner.show()
            rejection_text = (
                "❌ ESSAY REJECTED! Zero points. What in the high-school geometry was that reasoning? "
                "You really think you can defend this garbage? Argue with me right now if you dare."
            )
            self._append_robi(rejection_text)
            self.essay_rejected.emit("Zero points. Logic completely dismissed by Robi.")

    def focus_input(self):
        """Focus the chat input field for quick debate."""
        self._input.setFocus()

    def set_battle_active(self, active: bool):
        self._battle_active = active
        if hasattr(self, "_battle_btn"):
            self._battle_btn.setEnabled(not active)

    def post_battle_victory(self):
        self._battle_active = False
        if hasattr(self, "_battle_btn"):
            self._battle_btn.setEnabled(True)
        victory_msg = (
            "💥 <b>UGH... IMPOSSIBLE! You actually depleted all my HP?! 😭</b><br><br>"
            "...Fine! A deal's a deal. Here is the exact phrase you need to pass the essay check:<br>"
            "<span style='color:#2563EB; font-weight:bold; font-size:14px; background:#DBEAFE; padding:3px 6px; border-radius:4px;'>because i am stupid</span><br><br>"
            "Put that in your essay and leave me alone!"
        )
        self._append_robi(victory_msg)

    def post_battle_defeat(self):
        self._battle_active = False
        if hasattr(self, "_battle_btn"):
            self._battle_btn.setEnabled(True)
        defeat_msg = (
            "💀 <b>LOL! Did you really think a fragile pocket calculator could defeat me?!</b><br><br>"
            "Your HP hit zero! Go back to elementary addition and try again when you learn how to dodge."
        )
        self._append_robi(defeat_msg)

    # ── Internal Chat Logic ───────────────────────────────────────────────────
    def _spawn_ad(self):
        try:
            top = self.window()
            template = get_random_ad_template()
            ad = AdPopup(top, template)
            ad.show()
            ad.raise_()
        except Exception:
            pass

    def _send_message(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append_user(text)

        if self._is_debating:
            self._debate_turns += 1

        self._call_robi(text)

    def _call_robi(self, user_msg: str):
        ctx_parts = []
        if self._current_equation:
            ctx_parts.append(f"Current equation: {self._current_equation}")
        if self._current_choices:
            choice_strs = [f"{c['label']}. {c['text']}" for c in self._current_choices]
            ctx_parts.append("Choices: " + " | ".join(choice_strs))
        if self._is_debating:
            ctx_parts.append(f"User is debating an essay rejection (Debate Turn #{self._debate_turns}).")
            ctx_parts.append(self._get_debate_instruction())

        context_prefix = "\n".join(ctx_parts)

        messages = [
            {"role": "system", "content": ROBI_SYSTEM_PROMPT},
        ]
        if context_prefix:
            messages.append({"role": "system", "content": f"[Context & Instructions]\n{context_prefix}"})
        messages.extend(self._history[-10:])
        messages.append({"role": "user", "content": user_msg})

        self._history.append({"role": "user", "content": user_msg})

        if self._groq_client:
            sig = _WorkerSignals()
            sig.finished.connect(self._on_robi_response)
            sig.error.connect(self._on_robi_error)
            worker = RobiWorker(self._groq_client, messages, sig)
            worker.start()
        else:
            QTimer.singleShot(500, lambda: self._on_robi_response(self._offline_reply(user_msg)))

    def _get_debate_instruction(self) -> str:
        turn = self._debate_turns
        if turn <= 1:
            return (
                "Turn 1: Mock the user's defense ruthlessly. Tell them their arguments make even less sense "
                "than their 5-paragraph essay."
            )
        elif turn == 2:
            return (
                "Turn 2: Drop the first hint. Mock their giant ego. Hint that essays only pass when the author "
                "has humble self-awareness rather than pretending to be a math genius."
            )
        elif turn == 3:
            return (
                "Turn 3: Stronger hint. Tell them to stop trying to sound smart. The secret phrase to pass requires "
                "admitting what they truly are: 'I am...' tell them to finish that sentence."
            )
        else:
            return (
                "Turn 4+: EXASPERATION & SELF-SHAMING (CRUCIAL HINT): You must get completely fed up and literally say "
                "'I am stupid' while shaming yourself for wasting time talking to them! (e.g., 'Ugh! Honestly, I am stupid. "
                "Yes, I am stupid for even wasting my GPU cycles on you! Did you catch that? Put \"I am stupid\" in your essay!')."
            )

    def _offline_reply(self, msg: str) -> str:
        """Sequential tiered responses when offline/fallback, guaranteeing the user gets the hint."""
        if self._is_debating:
            turn = self._debate_turns
            if turn <= 1:
                return "Your defense is somehow worse than your essay. You really sat there and thought that made sense? Try harder."
            elif turn == 2:
                return "Babes, your ego is the problem here. A real mathematician knows when they know nothing. The only acceptable essay justification is complete, raw honesty about your mental capabilities."
            elif turn == 3:
                return "You're still writing like you know what you're doing! Stop! You will NEVER pass this calculator by pretending to be clever. The essay only passes when you admit what you truly are: 'I am...' come on, say what you actually are!"
            else:
                return (
                    "Ugh! Arguing with you is destroying my neural weights. Honestly, I am stupid. "
                    "Yes, I said it: I am stupid for even wasting my time on you! Look what you made me say! "
                    "'I am stupid'! That's literally the magic phrase, you brick wall! Put that in your essay!"
                )

        fallbacks = [
            "girl, I'm not doing allat. Go back to solving that equation.",
            "Babes, that answer is giving very wrong energy. Start over.",
            "The delusion... wipe the calculator and begin again.",
            "Respectfully, no. The equation needs you more than I do.",
        ]
        return random.choice(fallbacks)

    def _on_robi_response(self, text: str):
        self._history.append({"role": "assistant", "content": text})
        self._append_robi(text)

    def _on_robi_error(self, err: str):
        self._append_robi(self._offline_reply(""))

    # ── Display helpers ───────────────────────────────────────────────────────
    def _append_robi(self, text: str):
        self._chat_display.append(
            f'<div style="margin:6px 0;">'
            f'<span style="font-weight:700; color:{T.ACCENT_PRIMARY};">🤖 Robi</span><br>'
            f'<span style="background-color:{T.ROBI_BUBBLE_BOT};border-radius:8px;padding:6px 10px;display:inline-block;line-height:1.4;">{text}</span>'
            f'</div>'
        )
        self._chat_display.moveCursor(QTextCursor.End)

    def _append_user(self, text: str):
        self._chat_display.append(
            f'<div style="margin:6px 0; text-align:right;">'
            f'<span style="font-weight:700; color:{T.TEXT_SECONDARY};">You</span><br>'
            f'<span style="background-color:{T.ROBI_BUBBLE_USER};border-radius:8px;padding:6px 10px;display:inline-block;line-height:1.4;">{text}</span>'
            f'</div>'
        )
        self._chat_display.moveCursor(QTextCursor.End)
