"""
ui_controller.py — Context-Aware Adaptive UI Controller
Full CustomTkinter UI with 3 panels + state transition log.
Dynamically adapts layout, colors, and visibility based on FSM state.

Production Fixes:
  - Log only refreshes when entry count changes (prevents thrashing)
  - Idle overlay uses semi-transparent dark color
"""

import customtkinter as ctk
import time
import logging

logger = logging.getLogger("AdaptiveUI.Dashboard")


# ─── Color Palettes per State ──────────────────────────────────────────────────

STATE_THEMES = {
    "ACTIVE": {
        "bg": "#0a1628",
        "accent": "#00d4aa",
        "accent_hover": "#00b894",
        "text": "#e0f7fa",
        "panel_bg": "#0d2137",
        "panel_border": "#00d4aa",
        "header_bg": "#0d2137",
        "state_color": "#00d4aa",
        "state_glow": "#00ffcc",
        "button_fg": "#000000",
        "label": "⚡ ACTIVE",
        "description": "Cursor Activity Detected — UI optimized for rapid navigation",
    },
    "FOCUS": {
        "bg": "#0a0a0f",
        "accent": "#7c4dff",
        "accent_hover": "#651fff",
        "text": "#d1c4e9",
        "panel_bg": "#12111a",
        "panel_border": "#7c4dff",
        "header_bg": "#12111a",
        "state_color": "#7c4dff",
        "state_glow": "#b388ff",
        "button_fg": "#ffffff",
        "label": "🎯 FOCUS",
        "description": "Typing activity detected — workspace expanded for deep work",
    },
    "IDLE": {
        "bg": "#1a1a2e",
        "accent": "#4a4a6a",
        "accent_hover": "#5a5a7a",
        "text": "#6a6a8a",
        "panel_bg": "#16162a",
        "panel_border": "#2a2a4a",
        "header_bg": "#16162a",
        "state_color": "#4a4a6a",
        "state_glow": "#6a6a8a",
        "button_fg": "#ffffff",
        "label": "💤 IDLE",
        "description": "No activity detected — system paused, awaiting input",
    },
    "ERROR": {
        "bg": "#1a0a0a",
        "accent": "#ff5252",
        "accent_hover": "#ff1744",
        "text": "#ffcdd2",
        "panel_bg": "#1f0f0f",
        "panel_border": "#ff5252",
        "header_bg": "#1f0f0f",
        "state_color": "#ff5252",
        "state_glow": "#ff8a80",
        "button_fg": "#ffffff",
        "label": "⚠️ ERROR",
        "description": "Ambiguous input — Error Assistance Mode active",
    },
    "PAUSED": {
        "bg": "#121212",
        "accent": "#9e9e9e",
        "accent_hover": "#bdbdbd",
        "text": "#eeeeee",
        "panel_bg": "#1e1e1e",
        "panel_border": "#424242",
        "header_bg": "#1e1e1e",
        "state_color": "#9e9e9e",
        "state_glow": "#e0e0e0",
        "button_fg": "#000000",
        "label": "⏸ PAUSED",
        "description": "Monitoring is temporarily suspended by user",
    },
}


class AdaptiveUI:
    """
    Full adaptive UI with:
    - Header bar (state indicator + title)
    - Left panel: Behavior Analyzer (live metrics)
    - Center panel: Interactive Workspace (text area + buttons)
    - Right panel: System Performance (fake metrics)
    - Bottom panel: State Transition Log
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Adaptive UI Engine — Context-Aware Interface System")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)

        # Set dark mode
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._current_state = None
        self._prev_log_count = 0  # Track log entries for optimized refresh

        # ─── Build Layout ───
        self._build_header()
        self._build_main_area()
        self._build_log_panel()

        # ─── Idle Overlay ───
        self._build_idle_overlay()

    # ═══════════════════════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_header(self):
        """Top bar with title, state indicator, and description."""
        self.header_frame = ctk.CTkFrame(self.root, height=80, corner_radius=0)
        self.header_frame.pack(fill="x", padx=0, pady=0)
        self.header_frame.pack_propagate(False)

        # Left: Title
        title_container = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_container.pack(side="left", padx=20, pady=10)

        self.title_label = ctk.CTkLabel(
            title_container,
            text="🧠 Adaptive UI Engine",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#ffffff",
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            title_container,
            text="Context-Aware Interface System v1.0",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#888888",
        )
        self.subtitle_label.pack(anchor="w")

        # Right: State Badge
        state_container = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        state_container.pack(side="right", padx=20, pady=10)

        self.state_badge = ctk.CTkLabel(
            state_container,
            text="💤 IDLE",
            font=ctk.CTkFont(family="Consolas", size=20, weight="bold"),
            text_color="#4a4a6a",
        )
        self.state_badge.pack(anchor="e")

        self.state_desc = ctk.CTkLabel(
            state_container,
            text="Initializing system...",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#666666",
            wraplength=350,
            justify="right",
        )
        self.state_desc.pack(anchor="e")

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN 3-PANEL AREA
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_main_area(self):
        """Three-column layout: Metrics | Workspace | System."""
        self.main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=(5, 5))

        self.main_frame.grid_columnconfigure(0, weight=1)  # Left panel
        self.main_frame.grid_columnconfigure(1, weight=3)  # Center
        self.main_frame.grid_columnconfigure(2, weight=1)  # Right panel
        self.main_frame.grid_rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

    # ─── LEFT: Behavior Analyzer ──────────────────────────────────────────────

    def _build_left_panel(self):
        self.left_panel = ctk.CTkFrame(self.main_frame, corner_radius=12, border_width=1)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)

        # Panel Header
        ctk.CTkLabel(
            self.left_panel,
            text="📊 Behavior Analyzer",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff",
        ).pack(pady=(15, 5), padx=15, anchor="w")

        ctk.CTkLabel(
            self.left_panel,
            text="Real-time behavioral metrics",
            font=ctk.CTkFont(size=10),
            text_color="#666666",
        ).pack(padx=15, anchor="w")

        # Separator
        sep = ctk.CTkFrame(self.left_panel, height=1, fg_color="#333333")
        sep.pack(fill="x", padx=15, pady=10)

        # Metric Rows
        self.metric_labels = {}
        metrics_config = [
            ("clicks_per_sec", "Clicks / sec", "0.0"),
            ("keys_per_sec", "Keys / sec", "0.0"),
            ("movement_per_sec", "Movement / sec", "0.0"),
            ("scrolls_per_sec", "Scroll / sec", "0.0"),
            ("idle_time", "Idle Time", "0.0s"),
            ("state_duration", "State Duration", "0.0s"),
            ("confidence", "Confidence", "0.00"),
        ]

        for key, label, default in metrics_config:
            row = ctk.CTkFrame(self.left_panel, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=3)

            ctk.CTkLabel(
                row,
                text=label,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color="#999999",
            ).pack(side="left")

            val_label = ctk.CTkLabel(
                row,
                text=default,
                font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
                text_color="#00d4aa",
            )
            val_label.pack(side="right")
            self.metric_labels[key] = val_label

        # State indicator at bottom of panel
        ctk.CTkFrame(self.left_panel, height=1, fg_color="#333333").pack(
            fill="x", padx=15, pady=(15, 10)
        )

        self.fsm_state_label = ctk.CTkLabel(
            self.left_panel,
            text="FSM State: IDLE",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color="#4a4a6a",
        )
        self.fsm_state_label.pack(pady=(0, 15), padx=15, anchor="w")

    # ─── CENTER: Interactive Workspace ────────────────────────────────────────

    def _build_center_panel(self):
        self.center_panel = ctk.CTkFrame(self.main_frame, corner_radius=12, border_width=1)
        self.center_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        # Panel Header
        self.workspace_header = ctk.CTkLabel(
            self.center_panel,
            text="🖥️ Interactive Workspace",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff",
        )
        self.workspace_header.pack(pady=(15, 5), padx=15, anchor="w")

        self.workspace_desc = ctk.CTkLabel(
            self.center_panel,
            text="Adaptive interaction area — responds to your behavior",
            font=ctk.CTkFont(size=10),
            text_color="#666666",
        )
        self.workspace_desc.pack(padx=15, anchor="w")

        # Separator
        ctk.CTkFrame(self.center_panel, height=1, fg_color="#333333").pack(
            fill="x", padx=15, pady=10
        )

        # Text Area
        self.text_area = ctk.CTkTextbox(
            self.center_panel,
            font=ctk.CTkFont(family="Consolas", size=13),
            corner_radius=8,
            border_width=1,
            border_color="#333333",
            wrap="word",
        )
        self.text_area.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.text_area.insert("1.0", "Start typing here to trigger FOCUS state...\n\nClick rapidly to trigger ACTIVE state.\n\nStop all input for 5 seconds to trigger IDLE state.")

        # Button Row
        self.button_frame = ctk.CTkFrame(self.center_panel, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=15, pady=(0, 15))

        button_configs = [
            ("▶ Execute", "#00d4aa", "#000000"),
            ("⚡ Quick Action", "#7c4dff", "#ffffff"),
            ("📋 Copy Output", "#ff9800", "#000000"),
            ("🔄 Reset", "#78909c", "#ffffff"),
        ]

        self.buttons = []
        for text, color, fg in button_configs:
            btn = ctk.CTkButton(
                self.button_frame,
                text=text,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                fg_color=color,
                text_color=fg,
                hover_color=color,
                corner_radius=8,
                height=36,
            )
            btn.pack(side="left", padx=(0, 8), expand=True, fill="x")
            self.buttons.append(btn)

        # Shortcuts label (shown in ACTIVE state)
        self.shortcuts_label = ctk.CTkLabel(
            self.center_panel,
            text="⌨ Shortcuts: Ctrl+E Execute  |  Ctrl+Q Quick Action  |  Ctrl+C Copy  |  Ctrl+R Reset",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#00d4aa",
        )
        # Don't pack yet — shown conditionally

    # ─── RIGHT: System Performance ────────────────────────────────────────────

    def _build_right_panel(self):
        self.right_panel = ctk.CTkFrame(self.main_frame, corner_radius=12, border_width=1)
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(5, 5), pady=5)

        # Panel Header
        ctk.CTkLabel(
            self.right_panel,
            text="📈 System Performance",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff",
        ).pack(pady=(15, 5), padx=15, anchor="w")

        ctk.CTkLabel(
            self.right_panel,
            text="Adaptive Controller metrics",
            font=ctk.CTkFont(size=10),
            text_color="#666666",
        ).pack(padx=15, anchor="w")

        # Separator
        ctk.CTkFrame(self.right_panel, height=1, fg_color="#333333").pack(
            fill="x", padx=15, pady=10
        )

        # System metric rows
        self.sys_metric_labels = {}
        sys_metrics = [
            ("neural_latency", "Neural Latency", "—"),
            ("processing_cycle", "Processing Cycle", "—"),
            ("adaptation_response", "Adapt. Response", "—"),
            ("system_load", "System Load", "—"),
            ("throughput", "Throughput", "—"),
        ]

        for key, label, default in sys_metrics:
            row = ctk.CTkFrame(self.right_panel, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=3)

            ctk.CTkLabel(
                row,
                text=label,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color="#999999",
            ).pack(side="left")

            val_label = ctk.CTkLabel(
                row,
                text=default,
                font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
                text_color="#00e5ff",
            )
            val_label.pack(side="right")
            self.sys_metric_labels[key] = val_label

        # Status indicators
        ctk.CTkFrame(self.right_panel, height=1, fg_color="#333333").pack(
            fill="x", padx=15, pady=(15, 10)
        )

        # Engine status
        self.engine_status = ctk.CTkLabel(
            self.right_panel,
            text="● Engine: Online",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#00d4aa",
        )
        self.engine_status.pack(padx=15, anchor="w", pady=2)

        self.input_status = ctk.CTkLabel(
            self.right_panel,
            text="● Input Layer: Active",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#00d4aa",
        )
        self.input_status.pack(padx=15, anchor="w", pady=2)

        self.fsm_status = ctk.CTkLabel(
            self.right_panel,
            text="● FSM: Running",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#00d4aa",
        )
        self.fsm_status.pack(padx=15, anchor="w", pady=(2, 10))

        # Tray Icon Toggle
        self.tray_toggle = ctk.CTkSwitch(
            self.right_panel,
            text="Taskbar/Tray Icon",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            command=self._on_tray_toggle,
        )
        self.tray_toggle.select()
        self.tray_toggle.pack(padx=15, anchor="w", pady=(5, 15))

    def _on_tray_toggle(self):
        if hasattr(self, 'on_tray_toggle_callback') and self.on_tray_toggle_callback:
            self.on_tray_toggle_callback(self.tray_toggle.get() == 1)

    # ═══════════════════════════════════════════════════════════════════════════
    # BOTTOM: State Transition Log
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_log_panel(self):
        self.log_frame = ctk.CTkFrame(self.root, corner_radius=12, height=150, border_width=1)
        self.log_frame.pack(fill="x", padx=15, pady=(0, 10))
        self.log_frame.pack_propagate(False)

        # Header row
        log_header = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=15, pady=(10, 5))

        ctk.CTkLabel(
            log_header,
            text="📝 State Transition Log",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#ffffff",
        ).pack(side="left")

        self.log_count_label = ctk.CTkLabel(
            log_header,
            text="0 transitions",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#666666",
        )
        self.log_count_label.pack(side="right")

        # Log text
        self.log_text = ctk.CTkTextbox(
            self.log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=8,
            border_width=0,
            state="disabled",
            wrap="none",
            activate_scrollbars=True,
        )
        self.log_text.pack(fill="both", expand=True, padx=15, pady=(0, 10))

    # ═══════════════════════════════════════════════════════════════════════════
    # IDLE OVERLAY
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_idle_overlay(self):
        """Semi-transparent overlay shown during IDLE state (dark, not solid black)."""
        self.idle_overlay = ctk.CTkFrame(
            self.root,
            fg_color="#0a0a1a",
            corner_radius=0,
        )
        # Not placed yet — shown via .place() when IDLE

        self.idle_overlay_label = ctk.CTkLabel(
            self.idle_overlay,
            text="⏸  SYSTEM PAUSED",
            font=ctk.CTkFont(family="Consolas", size=32, weight="bold"),
            text_color="#4a4a6a",
        )
        self.idle_overlay_label.place(relx=0.5, rely=0.4, anchor="center")

        self.idle_overlay_sub = ctk.CTkLabel(
            self.idle_overlay,
            text="Move mouse or press any key to resume",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color="#3a3a5a",
        )
        self.idle_overlay_sub.place(relx=0.5, rely=0.5, anchor="center")

    # ═══════════════════════════════════════════════════════════════════════════
    # STATE APPLICATION (the core adaptation logic)
    # ═══════════════════════════════════════════════════════════════════════════

    def apply_state(self, state, metrics, state_duration, log_entries):
        """
        Apply full UI adaptation based on current state.
        This is called every 500ms by main.py.
        """
        theme = STATE_THEMES[state]

        # ─── Update Header ───
        self.header_frame.configure(fg_color=theme["header_bg"])
        self.state_badge.configure(text=theme["label"], text_color=theme["state_glow"])
        self.state_desc.configure(text=theme["description"])

        # ─── Update Behavioral Metrics ───
        self.metric_labels["clicks_per_sec"].configure(
            text=f"{metrics['clicks_per_sec']:.1f}",
            text_color=theme["accent"],
        )
        self.metric_labels["keys_per_sec"].configure(
            text=f"{metrics['keys_per_sec']:.1f}",
            text_color=theme["accent"],
        )
        self.metric_labels["movement_per_sec"].configure(
            text=f"{metrics['movement_per_sec']:.0f}",
            text_color=theme["accent"],
        )
        self.metric_labels["scrolls_per_sec"].configure(
            text=f"{metrics['scrolls_per_sec']:.1f}",
            text_color=theme["accent"],
        )
        self.metric_labels["idle_time"].configure(
            text=f"{metrics['idle_time']}s",
            text_color=theme["accent"],
        )
        self.metric_labels["state_duration"].configure(
            text=f"{state_duration}s",
            text_color=theme["accent"],
        )
        self.metric_labels["confidence"].configure(
            text=f"{metrics['classification_confidence']:.2f}",
            text_color=theme["accent"],
        )

        # FSM state label
        self.fsm_state_label.configure(
            text=f"FSM State: {state}",
            text_color=theme["state_color"],
        )

        # ─── Update System Metrics ───
        self.sys_metric_labels["neural_latency"].configure(
            text=f"{metrics['neural_latency']}ms",
            text_color="#00e5ff",
        )
        self.sys_metric_labels["processing_cycle"].configure(
            text=f"{metrics['processing_cycle']}ms",
            text_color="#00e5ff",
        )
        self.sys_metric_labels["adaptation_response"].configure(
            text=f"{metrics['adaptation_response']}ms",
            text_color="#00e5ff",
        )
        self.sys_metric_labels["system_load"].configure(
            text=f"{metrics['system_load']}%",
            text_color="#00e5ff",
        )
        self.sys_metric_labels["throughput"].configure(
            text=f"{metrics['throughput']} ops/s",
            text_color="#00e5ff",
        )

        # ─── Apply Panel Colors ───
        for panel in [self.left_panel, self.center_panel, self.right_panel, self.log_frame]:
            panel.configure(fg_color=theme["panel_bg"], border_color=theme["panel_border"])

        self.root.configure(fg_color=theme["bg"])
        self.text_area.configure(border_color=theme["panel_border"])

        # ─── State-Specific UI Changes ───
        if state != self._current_state:
            self._apply_state_specific(state, theme)
            self._current_state = state

        # ─── Update Log ───
        self._update_log(log_entries)

    def _apply_state_specific(self, state, theme):
        """Apply state-specific layout changes (only when state changes)."""

        # Reset everything first
        self._reset_layout()

        if state == "ACTIVE":
            # Bigger buttons, show shortcuts
            for btn in self.buttons:
                btn.configure(
                    height=44,
                    fg_color=theme["accent"],
                    hover_color=theme["accent_hover"],
                    text_color=theme["button_fg"],
                    font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                )
            self.shortcuts_label.pack(fill="x", padx=15, pady=(0, 10))

        elif state == "FOCUS":
            # Hide side panels, expand center
            self.left_panel.grid_remove()
            self.right_panel.grid_remove()
            self.main_frame.grid_columnconfigure(0, weight=0)
            self.main_frame.grid_columnconfigure(2, weight=0)
            self.main_frame.grid_columnconfigure(1, weight=1)
            self.workspace_header.configure(text="🎯 Focus Mode — Deep Work Workspace")
            for btn in self.buttons:
                btn.configure(
                    fg_color=theme["accent"],
                    hover_color=theme["accent_hover"],
                    text_color=theme["button_fg"],
                )

        elif state == "IDLE":
            # Show overlay
            self.idle_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            # Dim buttons
            for btn in self.buttons:
                btn.configure(
                    fg_color="#2a2a3a",
                    hover_color="#3a3a4a",
                    text_color="#5a5a6a",
                )

        elif state == "ERROR":
            # Red-tinted inputs, hint labels
            self.text_area.configure(border_color="#ff5252")
            for btn in self.buttons:
                btn.configure(
                    fg_color=theme["accent"],
                    hover_color=theme["accent_hover"],
                    text_color=theme["button_fg"],
                )
            self.workspace_header.configure(text="⚠️ Error Assistance Mode")

        elif state == "PAUSED":
            # Grey-tinted inputs, dim buttons, disabled look
            self.text_area.configure(border_color="#424242")
            for btn in self.buttons:
                btn.configure(
                    fg_color="#424242",
                    hover_color="#616161",
                    text_color="#bdbdbd",
                )
            self.workspace_header.configure(text="⏸ Monitoring Paused")

    def _reset_layout(self):
        """Reset all state-specific changes to default."""
        # Restore side panels
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(5, 5), pady=5)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=3)
        self.main_frame.grid_columnconfigure(2, weight=1)

        # Hide overlay
        self.idle_overlay.place_forget()

        # Reset workspace header
        self.workspace_header.configure(text="🖥️ Interactive Workspace")

        # Hide shortcuts
        self.shortcuts_label.pack_forget()

        # Reset buttons to default
        default_configs = [
            ("#00d4aa", "#000000"),
            ("#7c4dff", "#ffffff"),
            ("#ff9800", "#000000"),
            ("#78909c", "#ffffff"),
        ]
        for btn, (color, fg) in zip(self.buttons, default_configs):
            btn.configure(
                height=36,
                fg_color=color,
                hover_color=color,
                text_color=fg,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            )

        # Reset text area border
        self.text_area.configure(border_color="#333333")

    def _update_log(self, log_entries):
        """Update the transition log display (only when entry count changes)."""
        if not log_entries:
            return

        # Optimization: only rebuild log text when new entries arrive
        current_count = len(log_entries)
        if current_count == self._prev_log_count:
            return
        self._prev_log_count = current_count

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")

        for timestamp, old_state, new_state, duration in log_entries:
            line = f"  [{timestamp}]  {old_state:>8s}  →  {new_state:<8s}  (held for {duration}s)\n"
            self.log_text.insert("end", line)

        # Auto-scroll to bottom
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        self.log_count_label.configure(text=f"{current_count} transitions")
