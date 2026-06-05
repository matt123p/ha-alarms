/**
 * Lovelace Card and Sidebar Panel for Alarms custom integration.
 * Fully self-contained Web Component with a premium glassmorphic UI.
 */

class AlarmsPanelCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._alarms = {};
    this._mediaPlayers = [];
    this._showModal = false;
    this._editingId = null;
    this._playingId = null;
    this._audio = null;
    
    // Default form state
    this._formState = {
      name: "",
      time: "07:00",
      color: "#3498db",
      sound: "digital.wav",
      days: [],
      snooze_duration: 9,
      media_player: "",
    };
  }

  // Set HASS object (Home Assistant context)
  set hass(hass) {
    this._hass = hass;
    
    // Extract media players
    const mps = Object.keys(hass.states)
      .filter((eid) => eid.startsWith("media_player."))
      .map((eid) => ({
        entity_id: eid,
        name: hass.states[eid].attributes.friendly_name || eid,
      }));
    this._mediaPlayers = mps;

    // Check if ringing alarms need browser audio playback
    this._syncBrowserAudio();
    this.render();
  }

  // Standard Lovelace Card config
  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 3;
  }

  // Web Component lifecycle
  connectedCallback() {
    this._connectWebSocket();
    this._clockInterval = setInterval(() => this._updateClock(), 1000);
    this.render();
  }

  disconnectedCallback() {
    if (this._wsUnsubscribe) this._wsUnsubscribe();
    if (this._clockInterval) clearInterval(this._clockInterval);
    this.stopAllAudio();
  }

  // WebSocket Connection
  async _connectWebSocket() {
    if (!this._hass) {
      setTimeout(() => this._connectWebSocket(), 100);
      return;
    }

    try {
      // Fetch initial list of alarms
      const alarms = await this._hass.connection.sendMessagePromise({
        type: "alarms/list",
      });
      this._alarms = alarms || {};
      this.render();

      // Subscribe to live updates
      this._hass.connection.subscribeMessage(
        (event) => {
          this._handleWsUpdate(event);
        },
        { type: "alarms/subscribe" }
      ).then((unsub) => {
        this._wsUnsubscribe = unsub;
      });
    } catch (err) {
      console.error("Alarms websocket error:", err);
    }
  }

  async _handleWsUpdate(event) {
    // Refresh the list when anything changes
    try {
      const alarms = await this._hass.connection.sendMessagePromise({
        type: "alarms/list",
      });
      this._alarms = alarms || {};
      this.render();
    } catch (err) {
      console.error("Failed to refresh alarms:", err);
    }
  }

  // Browser Audio Handling
  _syncBrowserAudio() {
    let ringingAlarm = null;
    for (const alarm of Object.values(this._alarms)) {
      if (alarm.status === "ringing") {
        ringingAlarm = alarm;
        break;
      }
    }

    if (ringingAlarm) {
      this.playAudio(ringingAlarm);
    } else {
      this.stopAllAudio();
    }
  }

  playAudio(alarm) {
    if (this._playingId === alarm.id) return;
    this.stopAllAudio();

    this._playingId = alarm.id;
    if (alarm.sound === "silent.wav") {
      return;
    }

    const soundUrl = `/alarms_static/sounds/${alarm.sound}`;
    this._audio = new Audio(soundUrl);
    this._audio.loop = true;
    
    // Play with fallback warning
    this._audio.play().catch((err) => {
      console.warn("Audio playback blocked. Click on the UI to play alarm sounds.", err);
    });
  }

  stopAllAudio() {
    if (this._audio) {
      this._audio.pause();
      this._audio = null;
    }
    this._playingId = null;
  }

  _updateClock() {
    const timeEl = this.shadowRoot.querySelector(".digital-clock");
    if (timeEl) {
      const now = new Date();
      timeEl.textContent = now.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }
  }

  // Service (Action) Helpers
  _callService(domain, service, data) {
    if (this._hass) {
      this._hass.callService(domain, service, data);
    }
  }

  async _deleteAlarm(alarmId) {
    if (confirm("Are you sure you want to delete this alarm?")) {
      await this._hass.connection.sendMessagePromise({
        type: "alarms/delete",
        alarm_id: alarmId,
      });
    }
  }

  async _toggleAlarm(alarmId, enabled) {
    // Update local state immediately for snappy UI
    if (this._alarms[alarmId]) {
      this._alarms[alarmId].enabled = enabled;
      this._alarms[alarmId].status = enabled ? "idle" : "disabled";
    }
    this.render();
    
    // Send backend switch request
    this._callService("switch", enabled ? "turn_on" : "turn_off", {
      entity_id: `switch.${this._alarms[alarmId].name.toLowerCase().replace(/ /g, "_")}_enabled`,
    });
  }

  async _snoozeAlarm(alarmId) {
    await this._hass.connection.sendMessagePromise({
      type: "alarms/action",
      alarm_id: alarmId,
      action: "snooze",
    });
  }

  async _dismissAlarm(alarmId) {
    await this._hass.connection.sendMessagePromise({
      type: "alarms/action",
      alarm_id: alarmId,
      action: "dismiss",
    });
  }

  async _toggleSkipNext(alarm) {
    await this._hass.connection.sendMessagePromise({
      type: "alarms/action",
      alarm_id: alarm.id,
      action: alarm.silenced ? "unskip_next" : "skip_next",
    });
  }

  // Modals & UI Actions
  _openAddModal() {
    this._editingId = null;
    this._formState = {
      name: "",
      time: "07:00",
      color: "#3498db",
      sound: "digital.wav",
      days: [],
      snooze_duration: 5,
      media_player: "",
    };
    this._showModal = true;
    this.render();
  }

  _openEditModal(alarm) {
    this._editingId = alarm.id;
    this._formState = {
      name: alarm.name,
      time: alarm.time.substring(0, 5), // HH:MM
      color: alarm.color,
      sound: alarm.sound,
      days: [...alarm.days],
      snooze_duration: alarm.snooze_duration,
      media_player: alarm.media_player || "",
    };
    this._showModal = true;
    this.render();
  }

  _closeModal() {
    this._showModal = false;
    this.render();
  }

  _handleDayToggle(dayIdx) {
    const idx = this._formState.days.indexOf(dayIdx);
    if (idx > -1) {
      this._formState.days.splice(idx, 1);
    } else {
      this._formState.days.push(dayIdx);
      this._formState.days.sort();
    }
    this.render();
  }

  _previewSound() {
    const btn = this.shadowRoot.querySelector(".preview-btn");
    const sound = this._formState.sound;
    
    if (this._previewAudio) {
      this._previewAudio.pause();
      this._previewAudio = null;
      btn.textContent = "🔊 Preview";
      return;
    }

    const soundUrl = `/alarms_static/sounds/${sound}`;
    this._previewAudio = new Audio(soundUrl);
    this._previewAudio.play().catch(e => console.warn(e));
    btn.textContent = "⏹️ Stop";
    
    this._previewAudio.onended = () => {
      this._previewAudio = null;
      btn.textContent = "🔊 Preview";
    };
  }

  async _saveAlarm(e) {
    e.preventDefault();
    const shadow = this.shadowRoot;
    
    const name = shadow.getElementById("name").value.trim() || "Alarm";
    const time = shadow.getElementById("time").value;
    const color = this._formState.color;
    const sound = shadow.getElementById("sound").value;
    const snooze_duration = parseInt(shadow.getElementById("snooze_duration").value, 10);
    const media_player = shadow.getElementById("media_player").value || null;
    const days = this._formState.days;

    if (this._previewAudio) {
      this._previewAudio.pause();
      this._previewAudio = null;
    }

    try {
      if (this._editingId) {
        // Edit existing
        await this._hass.connection.sendMessagePromise({
          type: "alarms/update",
          alarm_id: this._editingId,
          name,
          time: time + ":00",
          color,
          sound,
          snooze_duration,
          media_player,
          days,
        });
      } else {
        // Create new
        await this._hass.connection.sendMessagePromise({
          type: "alarms/create",
          name,
          time: time + ":00",
          color,
          sound,
          snooze_duration,
          media_player,
          days,
        });
      }
      this._showModal = false;
      this.render();
    } catch (err) {
      alert("Error saving alarm: " + err.message);
    }
  }

  // Render HTML Templates
  render() {
    if (!this._hass) return;

    const alarmsList = Object.values(this._alarms);
    const daysShort = ["M", "T", "W", "T", "F", "S", "S"];
    
    const colors = [
      "#3498db", // Blue
      "#2ecc71", // Green
      "#e67e22", // Orange
      "#9b59b6", // Purple
      "#e74c3c", // Red
      "#f1c40f", // Yellow
      "#e84393", // Pink
    ];

    const sounds = [
      { file: "digital.wav", name: "Digital Beep" },
      { file: "chime.wav", name: "Soft Chime" },
      { file: "soothing.wav", name: "Calm Wave" },
      { file: "buzzer.wav", name: "Retro Buzzer" },
      { file: "silent.wav", name: "Silent / None (Integration Trigger)" },
    ];

    // Check audio prompt click
    const showPlaybackPrompt = this._playingId !== null;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          color: #ffffff;
        }

        .container {
          background: rgba(20, 20, 30, 0.6);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 24px;
          padding: 24px;
          box-shadow: 0 16px 40px rgba(0,0,0,0.4);
          position: relative;
          overflow: hidden;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
          flex-wrap: wrap;
          gap: 16px;
        }

        .title-area h2 {
          margin: 0;
          font-size: 28px;
          font-weight: 700;
          background: linear-gradient(135deg, #ffffff 0%, #a4b0be 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }

        .clock-area {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .digital-clock {
          font-family: monospace;
          font-size: 20px;
          background: rgba(255, 255, 255, 0.05);
          padding: 6px 14px;
          border-radius: 12px;
          border: 1px solid rgba(255,255,255,0.05);
          letter-spacing: 1px;
          color: #2ecc71;
          text-shadow: 0 0 10px rgba(46, 204, 113, 0.3);
        }

        .btn-add {
          background: linear-gradient(135deg, #3498db 0%, #2980b9 100%);
          color: white;
          border: none;
          padding: 10px 20px;
          border-radius: 14px;
          font-weight: 600;
          font-size: 14px;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
        }

        .btn-add:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px rgba(52, 152, 219, 0.5);
        }

        /* Alarms Grid */
        .alarms-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 20px;
        }

        .empty-state {
          text-align: center;
          padding: 60px 20px;
          background: rgba(255, 255, 255, 0.02);
          border-radius: 18px;
          border: 1px dashed rgba(255,255,255,0.1);
        }

        .empty-state mdi-icon {
          font-size: 48px;
          color: rgba(255,255,255,0.3);
        }

        .empty-state p {
          color: #a4b0be;
          font-size: 15px;
          margin-top: 12px;
        }

        /* Alarm Card */
        .alarm-card {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.06);
          border-radius: 20px;
          padding: 20px;
          position: relative;
          transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          height: 190px;
        }

        .alarm-card:hover {
          transform: translateY(-4px);
          background: rgba(255, 255, 255, 0.05);
          border-color: rgba(255,255,255,0.12);
        }

        .alarm-card.status-disabled {
          opacity: 0.55;
          filter: grayscale(0.5);
          border-color: rgba(255, 255, 255, 0.03);
        }

        .alarm-card.status-ringing {
          animation: alarm-ring-pulse 1.2s infinite alternate;
          border-color: var(--alarm-color);
        }

        @keyframes alarm-ring-pulse {
          0% {
            box-shadow: 0 0 10px rgba(231, 76, 60, 0.1), inset 0 0 5px rgba(231, 76, 60, 0.05);
          }
          100% {
            box-shadow: 0 0 25px var(--alarm-color), inset 0 0 10px var(--alarm-color);
          }
        }

        .alarm-card-top {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
        }

        .time-display {
          font-size: 38px;
          font-weight: 700;
          font-family: monospace;
          letter-spacing: -1px;
          line-height: 1;
        }

        .alarm-name {
          font-size: 16px;
          font-weight: 600;
          color: #ffffff;
          margin: 6px 0 2px 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 170px;
        }

        /* Toggle switch styling */
        .switch {
          position: relative;
          display: inline-block;
          width: 46px;
          height: 24px;
        }

        .switch input {
          opacity: 0;
          width: 0;
          height: 0;
        }

        .slider {
          position: absolute;
          cursor: pointer;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: rgba(255, 255, 255, 0.1);
          transition: .3s;
          border-radius: 24px;
        }

        .slider:before {
          position: absolute;
          content: "";
          height: 18px;
          width: 18px;
          left: 3px;
          bottom: 3px;
          background-color: white;
          transition: .3s;
          border-radius: 50%;
        }

        input:checked + .slider {
          background-color: var(--alarm-color);
        }

        input:checked + .slider:before {
          transform: translateX(22px);
        }

        /* Badges */
        .status-badge {
          display: inline-block;
          font-size: 11px;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 8px;
          margin-top: 6px;
          text-transform: uppercase;
        }

        .badge-idle { background: rgba(52, 152, 219, 0.15); color: #3498db; }
        .badge-ringing { background: rgba(231, 76, 60, 0.2); color: #e74c3c; animation: flash-badge 0.8s infinite; }
        .badge-snoozed { background: rgba(230, 126, 34, 0.15); color: #e67e22; }
        .badge-silenced { background: rgba(149, 165, 166, 0.15); color: #95a5a6; }
        .badge-disabled { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.3); }

        @keyframes flash-badge {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }

        .alarm-card-middle {
          margin: 10px 0;
        }

        .days-row {
          display: flex;
          gap: 6px;
        }

        .day-dot {
          width: 22px;
          height: 22px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 9px;
          font-weight: 700;
          background: rgba(255, 255, 255, 0.05);
          color: rgba(255,255,255,0.3);
        }

        .day-dot.active {
          background: var(--alarm-color);
          color: white;
          box-shadow: 0 0 10px var(--alarm-color);
        }

        /* Action bar */
        .alarm-card-bottom {
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-top: 1px solid rgba(255,255,255,0.05);
          padding-top: 10px;
          margin-top: auto;
        }

        .action-buttons {
          display: flex;
          gap: 8px;
        }

        .btn-action {
          padding: 6px 12px;
          font-size: 12px;
          font-weight: 600;
          border-radius: 8px;
          border: none;
          cursor: pointer;
          transition: 0.2s;
        }

        .btn-snooze { background: #e67e22; color: white; }
        .btn-dismiss { background: #e74c3c; color: white; }
        .btn-skip { background: rgba(255,255,255,0.1); color: white; }
        .btn-skip.silenced { background: #2ecc71; color: white; }

        .btn-action:hover {
          filter: brightness(1.15);
        }

        .card-menu {
          display: flex;
          gap: 12px;
        }

        .icon-btn {
          background: transparent;
          border: none;
          color: rgba(255,255,255,0.4);
          cursor: pointer;
          font-size: 16px;
          padding: 2px;
          transition: color 0.2s;
        }

        .icon-btn:hover {
          color: #ffffff;
        }

        .icon-btn-delete:hover {
          color: #e74c3c;
        }

        /* Modal styling */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.6);
          backdrop-filter: blur(15px);
          -webkit-backdrop-filter: blur(15px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          opacity: 0;
          pointer-events: none;
          transition: opacity 0.3s;
        }

        .modal-overlay.open {
          opacity: 1;
          pointer-events: auto;
        }

        .modal-content {
          background: rgba(25, 25, 35, 0.95);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 24px;
          width: 90%;
          max-width: 440px;
          padding: 28px;
          box-shadow: 0 20px 50px rgba(0,0,0,0.5);
          transform: translateY(20px);
          transition: transform 0.3s;
        }

        .modal-overlay.open .modal-content {
          transform: translateY(0);
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
        }

        .modal-header h3 {
          margin: 0;
          font-size: 22px;
          font-weight: 700;
        }

        .close-modal-btn {
          background: transparent;
          border: none;
          color: rgba(255,255,255,0.4);
          font-size: 22px;
          cursor: pointer;
        }

        .form-group {
          margin-bottom: 16px;
        }

        .form-group label {
          display: block;
          font-size: 13px;
          font-weight: 600;
          color: #a4b0be;
          margin-bottom: 6px;
        }

        .input-text, .select-input {
          width: 100%;
          padding: 12px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          border-radius: 12px;
          color: white;
          font-size: 14px;
          box-sizing: border-box;
          outline: none;
        }

        .input-text:focus, .select-input:focus {
          border-color: #3498db;
        }

        .sound-row {
          display: flex;
          gap: 10px;
        }

        .preview-btn {
          background: rgba(255,255,255,0.1);
          color: white;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 12px;
          padding: 0 15px;
          cursor: pointer;
          font-size: 13px;
          font-weight: 600;
          transition: 0.2s;
          white-space: nowrap;
        }

        .preview-btn:hover {
          background: rgba(255,255,255,0.15);
        }

        /* Custom Day Selector in Form */
        .day-select-row {
          display: flex;
          justify-content: space-between;
          margin-top: 4px;
        }

        .day-select-btn {
          width: 38px;
          height: 38px;
          border-radius: 50%;
          border: 1px solid rgba(255, 255, 255, 0.1);
          background: rgba(255, 255, 255, 0.03);
          color: #a4b0be;
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }

        .day-select-btn:hover {
          background: rgba(255, 255, 255, 0.08);
          border-color: rgba(255,255,255,0.2);
        }

        .day-select-btn.active {
          background: var(--form-color, #3498db);
          color: white;
          border-color: var(--form-color, #3498db);
          box-shadow: 0 0 12px var(--form-color, #3498db);
        }

        /* Color Selection Swatches */
        .color-swatches {
          display: flex;
          gap: 10px;
          margin-top: 4px;
        }

        .color-swatch {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          cursor: pointer;
          transition: transform 0.2s;
          border: 2px solid transparent;
        }

        .color-swatch:hover {
          transform: scale(1.15);
        }

        .color-swatch.active {
          border-color: white;
          transform: scale(1.1);
          box-shadow: 0 0 10px var(--swatch-color);
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          margin-top: 24px;
        }

        .btn-cancel {
          background: transparent;
          color: #a4b0be;
          border: 1px solid rgba(255,255,255,0.1);
          padding: 12px 20px;
          border-radius: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: 0.2s;
        }

        .btn-cancel:hover {
          background: rgba(255,255,255,0.05);
          color: white;
        }

        .btn-save {
          background: var(--form-color, #3498db);
          color: white;
          border: none;
          padding: 12px 24px;
          border-radius: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: 0.2s;
          box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
        }

        .btn-save:hover {
          filter: brightness(1.1);
        }

        /* Playback/Audio Prompt banner */
        .audio-prompt {
          background: rgba(231, 76, 60, 0.2);
          border: 1px solid rgba(231, 76, 60, 0.3);
          border-radius: 12px;
          padding: 10px 16px;
          margin-bottom: 20px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 13px;
          animation: banner-glow 1.5s infinite alternate;
        }

        @keyframes banner-glow {
          0% { box-shadow: 0 0 5px rgba(231, 76, 60, 0.1); }
          100% { box-shadow: 0 0 15px rgba(231, 76, 60, 0.3); }
        }

        .audio-prompt-btn {
          background: #e74c3c;
          border: none;
          color: white;
          padding: 6px 12px;
          border-radius: 8px;
          font-weight: 600;
          font-size: 11px;
          cursor: pointer;
        }
      </style>

      <div class="container">
        <!-- Playback helper if browser blocks autoplay -->
        ${
          showPlaybackPrompt
            ? `
          <div class="audio-prompt">
            <span>🚨 An alarm is triggering! Click here to hear the alarm sound.</span>
            <button class="audio-prompt-btn" id="btn-audio-sync">🔔 Play Sound</button>
          </div>
        `
            : ""
        }

        <div class="header">
          <div class="title-area">
            <h2>Alarm System</h2>
          </div>
          <div class="clock-area">
            <div class="digital-clock">00:00:00</div>
            <button class="btn-add">+ Add Alarm</button>
          </div>
        </div>

        ${
          alarmsList.length === 0
            ? `
          <div class="empty-state">
            <p>No alarms configured. Click "+ Add Alarm" to create your first alarm or reminder.</p>
          </div>
        `
            : `
          <div class="alarms-grid">
            ${alarmsList
              .map((alarm) => {
                const isRinging = alarm.status === "ringing";
                const isSnoozed = alarm.status === "snoozed";
                const isSilenced = alarm.status === "silenced";
                const nextTimeStr = alarm.next_trigger
                  ? new Date(alarm.next_trigger).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "";

                return `
                <div class="alarm-card status-${alarm.status}" style="--alarm-color: ${alarm.color || "#3498db"}">
                  <div class="alarm-card-top">
                    <div>
                      <div class="time-display">${alarm.time.substring(0, 5)}</div>
                      <div class="alarm-name">${alarm.name || "Alarm"}</div>
                      <span class="status-badge badge-${alarm.status}">
                        ${alarm.status === "silenced" ? "Skipped Next" : alarm.status}
                      </span>
                    </div>
                    
                    <label class="switch">
                      <input type="checkbox" class="toggle-enabled" data-id="${alarm.id}" ${
                        alarm.enabled ? "checked" : ""
                      }>
                      <span class="slider"></span>
                    </label>
                  </div>

                  <div class="alarm-card-middle">
                    ${
                      alarm.days && alarm.days.length > 0
                        ? `
                      <div class="days-row">
                        ${daysShort
                          .map((day, idx) => {
                            const active = alarm.days.includes(idx);
                            return `<div class="day-dot ${
                              active ? "active" : ""
                            }" style="${active ? `--alarm-color: ${alarm.color}` : ""}">${day}</div>`;
                          })
                          .join("")}
                      </div>
                    `
                        : `<div style="font-size: 12px; color: #a4b0be;">One-off Alarm</div>`
                    }
                  </div>

                  <div class="alarm-card-bottom">
                    <div class="action-buttons">
                      ${
                        isRinging
                          ? `
                        <button class="btn-action btn-snooze" data-id="${alarm.id}">Snooze</button>
                        <button class="btn-action btn-dismiss" data-id="${alarm.id}">Dismiss</button>
                      `
                          : ""
                      }
                      ${
                        isSnoozed
                          ? `
                        <button class="btn-action btn-dismiss" data-id="${alarm.id}">Dismiss</button>
                      `
                          : ""
                      }
                      ${
                        !isRinging && !isSnoozed && alarm.enabled
                          ? `
                        <button class="btn-action btn-skip ${isSilenced ? "silenced" : ""}" data-id="${alarm.id}">
                          ${isSilenced ? "Unskip" : "Skip Next"}
                        </button>
                      `
                          : ""
                      }
                    </div>

                    <div class="card-menu">
                      <button class="icon-btn icon-btn-edit" data-id="${alarm.id}" title="Edit Alarm">✏️</button>
                      <button class="icon-btn icon-btn-delete" data-id="${alarm.id}" title="Delete Alarm">🗑️</button>
                    </div>
                  </div>
                </div>
              `;
              })
              .join("")}
          </div>
        `
        }

        <!-- Add/Edit Modal -->
        <div class="modal-overlay ${this._showModal ? "open" : ""}">
          <div class="modal-content" style="--form-color: ${this._formState.color}">
            <div class="modal-header">
              <h3>${this._editingId ? "Edit Alarm" : "Add Alarm"}</h3>
              <button class="close-modal-btn">&times;</button>
            </div>
            
            <form id="alarm-form">
              <div class="form-group">
                <label for="name">Alarm Name / Label</label>
                <input type="text" id="name" class="input-text" placeholder="e.g. Wake Up, Remind pills..." value="${
                  this._formState.name
                }">
              </div>

              <div class="form-group">
                <label for="time">Time</label>
                <input type="time" id="time" class="input-text" style="font-size: 18px; font-weight: 700; width: 140px;" value="${
                  this._formState.time
                }">
              </div>

              <div class="form-group">
                <label>Repeat Days (Leave empty for one-off)</label>
                <div class="day-select-row">
                  ${daysShort
                    .map((day, idx) => {
                      const active = this._formState.days.includes(idx);
                      return `
                      <button type="button" class="day-select-btn ${
                        active ? "active" : ""
                      }" data-day="${idx}">${day}</button>
                    `;
                    })
                    .join("")}
                </div>
              </div>

              <div class="form-group">
                <label>Theme Color</label>
                <div class="color-swatches">
                  ${colors
                    .map((c) => {
                      const active = this._formState.color === c;
                      return `
                      <div class="color-swatch ${
                        active ? "active" : ""
                      }" style="background: ${c}; --swatch-color: ${c}" data-color="${c}"></div>
                    `;
                    })
                    .join("")}
                </div>
              </div>

              <div class="form-group">
                <label for="sound">Alarm Sound</label>
                <div class="sound-row">
                  <select id="sound" class="select-input">
                    ${sounds
                      .map(
                        (s) => `
                      <option value="${s.file}" ${this._formState.sound === s.file ? "selected" : ""}>${
                          s.name
                        }</option>
                    `
                      )
                      .join("")}
                  </select>
                  <button type="button" class="preview-btn">🔊 Preview</button>
                </div>
              </div>

              <div class="form-group">
                <label for="snooze_duration">Snooze Duration (minutes)</label>
                <input type="number" id="snooze_duration" class="input-text" min="1" max="60" style="width: 80px;" value="${
                  this._formState.snooze_duration
                }">
              </div>

              <div class="form-group">
                <label for="media_player">Output Speaker (Optional, plays in house)</label>
                <select id="media_player" class="select-input">
                  <option value="">Browser Only</option>
                  ${this._mediaPlayers
                    .map(
                      (mp) => `
                    <option value="${mp.entity_id}" ${
                        this._formState.media_player === mp.entity_id ? "selected" : ""
                      }>${mp.name}</option>
                  `
                    )
                    .join("")}
                </select>
              </div>

              <div class="modal-footer">
                <button type="button" class="btn-cancel">Cancel</button>
                <button type="submit" class="btn-save">${this._editingId ? "Save Changes" : "Create Alarm"}</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    `;

    this._setupEventListeners();
    this._updateClock();
  }

  // Setup Event Handlers
  _setupEventListeners() {
    const shadow = this.shadowRoot;

    // Sync audio button
    const btnSync = shadow.getElementById("btn-audio-sync");
    if (btnSync) {
      btnSync.addEventListener("click", () => {
        // Interacting with document allows audio
        let ringing = Object.values(this._alarms).find((a) => a.status === "ringing");
        if (ringing) {
          this.playAudio(ringing);
        }
      });
    }

    // Add alarm button
    shadow.querySelector(".btn-add").addEventListener("click", () => this._openAddModal());

    // Toggle enabled switches
    shadow.querySelectorAll(".toggle-enabled").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = e.target.getAttribute("data-id");
        this._toggleAlarm(id, e.target.checked);
      });
    });

    // Quick action buttons
    shadow.querySelectorAll(".btn-snooze").forEach((btn) => {
      btn.addEventListener("click", () => this._snoozeAlarm(btn.getAttribute("data-id")));
    });

    shadow.querySelectorAll(".btn-dismiss").forEach((btn) => {
      btn.addEventListener("click", () => this._dismissAlarm(btn.getAttribute("data-id")));
    });

    shadow.querySelectorAll(".btn-skip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const alarm = this._alarms[btn.getAttribute("data-id")];
        if (alarm) this._toggleSkipNext(alarm);
      });
    });

    // Edit and Delete
    shadow.querySelectorAll(".icon-btn-edit").forEach((btn) => {
      btn.addEventListener("click", () => {
        const alarm = this._alarms[btn.getAttribute("data-id")];
        if (alarm) this._openEditModal(alarm);
      });
    });

    shadow.querySelectorAll(".icon-btn-delete").forEach((btn) => {
      btn.addEventListener("click", () => this._deleteAlarm(btn.getAttribute("data-id")));
    });

    // Modal Close
    shadow.querySelector(".close-modal-btn").addEventListener("click", () => this._closeModal());
    shadow.querySelector(".btn-cancel").addEventListener("click", () => this._closeModal());

    // Day multi-selector
    shadow.querySelectorAll(".day-select-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dayIdx = parseInt(btn.getAttribute("data-day"), 10);
        this._handleDayToggle(dayIdx);
      });
    });

    // Color swatches
    shadow.querySelectorAll(".color-swatch").forEach((swatch) => {
      swatch.addEventListener("click", () => {
        this._formState.color = swatch.getAttribute("data-color");
        this.render();
      });
    });

    // Sound preview button
    const previewBtn = shadow.querySelector(".preview-btn");
    if (previewBtn) {
      previewBtn.addEventListener("click", () => this._previewSound());
    }

    // Form submit
    shadow.getElementById("alarm-form").addEventListener("submit", (e) => this._saveAlarm(e));
  }
}

// Define the Web Component
customElements.define("alarms-panel", AlarmsPanelCard);

// Lovelace card registration helper (so it displays in the card list)
window.customCards = window.customCards || [];
window.customCards.push({
  type: "alarms-panel",
  name: "Alarms Card",
  preview: true,
  description: "A gorgeous interface to control and configure your custom alarms.",
});
