# Adaptive UI Engine
A Context-Aware Interface System Using Real-Time Behavioral Analysis
The Adaptive UI Engine is a real-time background assistant that transforms the static desktop experience into a reactive environment. By capturing global user interaction patterns—keyboard telemetry, mouse dynamics, and touchpad gestures—the engine uses a Finite State Machine (FSM) to dynamically adapt system overlays and behavioral feedback.

# 🧠 Core Engineering Concepts
1. Finite State Machine (FSM) Logic
The system classifies user behavior into four distinct states based on interaction intensity:

ACTIVE (Cyan): High-intensity navigation; triggers telemetry widgets and live stats.

FOCUS (Purple): Sustained typing with low cursor movement; enters "Deep Work" mode with minimal distractions.

IDLE (Dark): 5 seconds of total inactivity; triggers "System Paused" overlay and energy-saving brightness.

ERROR (Red): Ambiguous or conflicting behavioral signals; triggers fallback assistance mode.

2. Global Event Interception
Unlike standard apps, this engine operates at the OS level using an Input Abstraction Layer. Using pynput and multi-threaded listeners, it captures:

Keyboard: Keys per second (KPS)

Mouse: Clicks per second and Manhattan Distance (dx + dy) movement estimation.

Touchpad: Scroll delta detection for advanced activity tracking.

# 🛠️ Technical Architecture
The project follows a 4-Layer Modular Pipeline for low-latency execution (<10ms):

Input Layer: High-frequency event listeners (Threaded).

Analysis Layer: Normalization, debouncing, and moving average smoothing to prevent data spikes.

FSM Engine: Decision-making layer using threshold-based behavioral confidence.

Output Layer: Non-blocking Tkinter overlay rendering engine with hardware-accelerated fade animations.

# 🚀 Key Bug Fixes & Optimizations
The "Scroll-Sync" Breakthrough
Problem: Early versions entered IDLE mode while users were actively scrolling through long documents, as standard listeners ignored scroll deltas.
Solution: Implemented Idle Timer Synchronization across all input vectors. Now, any scroll or touchpad gesture resets the global idle clock, ensuring seamless interaction during content consumption.

Anti-Flicker Debouncing
Problem: "State Jitter" occurred when interaction intensity hovered near a threshold.
Solution: Developed Candidate State Buffering. A state transition is only committed if the behavioral data persists for 2 consecutive cycles (1000ms), ensuring a stable UI experience.

# 📂 Project Structure
Plaintext
├── main.py              # System Orchestrator
├── event_capture.py     # Global Listeners (Keyboard/Mouse/Scroll)
├── state_engine.py      # FSM Logic & Thresholding
├── analyzer.py          # Metrics & Smoothing (Moving Averages)
├── overlay_manager.py   # Adaptive UI Rendering Engine
└── ui_controller.py     # Dashboard & Telemetry Visualization
# ⚡ Setup & Installation
**Clone the Repo:**

git clone https://github.com/nishantchakravarthy/Adaptive-UI.git

**Install Dependencies:**


pip install pynput customtkinter screeninfo Pillow

**Run the Engine:**

python main.py
# 👥 Authors
**Nishant Chakravarthy** - System Architecture & FSM Design

**Parth** - UI Design & OS Integration
