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
    this._soundDropdownOpen = false;
    this._mpDropdownOpen = false;

    // Default form state
    this._formState = {
      name: "",
      time: "07:00",
      color: "#3498db",
      sound: "digital.wav",
      days: [],
      snooze_duration: 9,
      media_player: "",
      area_id: "",
    };
    this._areaDropdownOpen = false;
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

    const mpsChanged = JSON.stringify(mps) !== JSON.stringify(this._mediaPlayers);
    this._mediaPlayers = mps;

    // Sync alarms from the master sensor if available
    let alarmsChanged = false;
    const systemState = hass.states["sensor.alarm_clock_system"];
    if (systemState && systemState.attributes && systemState.attributes.configured_alarms) {
      const configuredAlarms = systemState.attributes.configured_alarms;
      const newAlarms = {};
      for (const a of configuredAlarms) {
        newAlarms[a.alarm_id] = {
          id: a.alarm_id,
          name: a.name,
          time: a.time,
          enabled: a.enabled,
          status: a.status,
          days: a.days,
          color: a.color,
          sound: a.sound,
          snooze_duration: a.snooze_duration,
          media_player: a.media_player,
          area_id: a.area_id,
          next_trigger: a.next_trigger,
          snoozed_until: a.snoozed_until,
          silenced: a.silenced,
        };
      }
      
      if (JSON.stringify(newAlarms) !== JSON.stringify(this._alarms)) {
        this._alarms = newAlarms;
        alarmsChanged = true;
      }
    }

    // Check if ringing alarms need browser audio playback
    this._syncBrowserAudio();

    // Render if first time, media players changed, or alarms changed,
    // and the modal is not currently open to avoid disrupting user input.
    if ((!this._hasRendered || mpsChanged || alarmsChanged) && !this._showModal) {
      this._hasRendered = true;
      this.render();
    }
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

      // Delay render if the modal is currently open to prevent disrupting the user
      if (!this._showModal) {
        this.render();
      }
    } catch (err) {
      console.error("Failed to refresh alarms:", err);
    }
  }

  // Browser Audio Handling
  _syncBrowserAudio() {
    let ringingAlarm = null;
    const cardArea = this._config && this._config.area;
    for (const alarm of Object.values(this._alarms)) {
      if (alarm.status === "ringing") {
        const alarmArea = alarm.area_id;
        if (!alarmArea || (cardArea && cardArea === alarmArea)) {
          ringingAlarm = alarm;
          break;
        }
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

  _getAlarmSwitchEntityId(alarmId) {
    if (!this._hass) return null;
    // Try to find by attribute alarm_id
    for (const [entityId, stateObj] of Object.entries(this._hass.states)) {
      if (
        entityId.startsWith("switch.") &&
        entityId.endsWith("_enabled") &&
        stateObj.attributes &&
        stateObj.attributes.alarm_id === alarmId
      ) {
        return entityId;
      }
    }
    // Fallback to slugged name
    const alarm = this._alarms[alarmId];
    if (alarm) {
      const slug = alarm.name.toLowerCase().replace(/ /g, "_");
      return `switch.${slug}_enabled`;
    }
    return null;
  }

  async _toggleAlarm(alarmId, enabled) {
    // Update local state immediately for snappy UI
    if (this._alarms[alarmId]) {
      this._alarms[alarmId].enabled = enabled;
      this._alarms[alarmId].status = enabled ? "idle" : "disabled";
    }
    this.render();

    const entityId = this._getAlarmSwitchEntityId(alarmId);
    if (entityId) {
      this._callService("switch", enabled ? "turn_on" : "turn_off", {
        entity_id: entityId,
      });
    }
  }

  async _snoozeAlarm(alarmId) {
    await this._hass.connection.sendMessagePromise({
      type: "alarms/action",
      alarm_id: alarmId,
      action: "snooze",
    });
  }

  async _stopAlarm(alarmId) {
    await this._hass.connection.sendMessagePromise({
      type: "alarms/action",
      alarm_id: alarmId,
      action: "stop",
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
      area_id: "",
    };
    this._showModal = true;
    this._soundDropdownOpen = false;
    this._mpDropdownOpen = false;
    this._areaDropdownOpen = false;
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
      area_id: alarm.area_id || "",
    };
    this._showModal = true;
    this._soundDropdownOpen = false;
    this._mpDropdownOpen = false;
    this._areaDropdownOpen = false;
    this.render();
  }

  _closeModal() {
    this._showModal = false;
    this._soundDropdownOpen = false;
    this._mpDropdownOpen = false;
    this._areaDropdownOpen = false;
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
    const sound = this._formState.sound;
    const snooze_duration = parseInt(shadow.getElementById("snooze_duration").value, 10);
    const media_player = this._formState.media_player || null;
    const area_id = this._formState.area_id || null;
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
          area_id,
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
          area_id,
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

    const currentSound = sounds.find(s => s.file === this._formState.sound) || sounds[0];
    const currentSoundName = currentSound ? currentSound.name : "Digital Beep";

    const currentMp = this._mediaPlayers.find(mp => mp.entity_id === this._formState.media_player);
    const currentMpName = currentMp ? currentMp.name : "Browser Only";

    const areas = Object.values(this._hass.areas || {});
    const currentArea = areas.find(a => a.area_id === this._formState.area_id);
    const currentAreaName = currentArea ? currentArea.name : "No Area";

    // Check audio prompt click
    const cardArea = this._config && this._config.area;
    const ringingAlarm = Object.values(this._alarms).find((a) => {
      if (a.status !== "ringing") return false;
      const alarmArea = a.area_id;
      return !alarmArea || (cardArea && cardArea === alarmArea);
    });

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: flex;
          flex-direction: column;
          font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          color: #2d3748;
          height: 100%;
          box-sizing: border-box;
        }

        .container {
          background: rgba(255, 255, 255, 0.4);
          backdrop-filter: blur(30px);
          -webkit-backdrop-filter: blur(30px);
          border: 1px solid rgba(255, 255, 255, 0.8);
          border-radius: 32px;
          padding: 40px;
          box-shadow: 0 30px 60px rgba(0,0,0,0.1);
          position: relative;
          overflow: hidden;
          flex: 1;
          display: flex;
          flex-direction: column;
          box-sizing: border-box;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 32px;
          flex-wrap: wrap;
          gap: 16px;
        }

        .title-area h2 {
          margin: 0;
          font-size: 36px;
          font-weight: 700;
          color: #1a202c;
          letter-spacing: -0.5px;
        }

        .clock-area {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 8px;
          color: #2d3748;
        }

        .clock-icon {
          width: 24px;
          height: 24px;
          stroke: #2d3748;
        }

        .digital-clock {
          font-size: 28px;
          font-weight: 500;
          letter-spacing: -0.5px;
          color: #1a202c;
        }

        .btn-add {
          background: linear-gradient(135deg, #2b7a94 0%, #1c566a 100%);
          color: white;
          border: none;
          padding: 12px 24px;
          border-radius: 20px;
          font-weight: 600;
          font-size: 15px;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          box-shadow: 0 8px 20px rgba(43, 122, 148, 0.3);
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .btn-add:hover {
          transform: translateY(-2px);
          box-shadow: 0 12px 25px rgba(43, 122, 148, 0.45);
        }

        /* Alarms List */
        .alarms-list {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .empty-state {
          text-align: center;
          padding: 60px 20px;
          background: rgba(255, 255, 255, 0.5);
          border-radius: 24px;
          border: 1px dashed rgba(0,0,0,0.1);
        }

        .empty-state p {
          color: #718096;
          font-size: 16px;
          margin-top: 12px;
          font-weight: 500;
        }

        /* Alarm Row */
        .alarm-row {
          background: rgba(255, 255, 255, 0.75);
          border: 1px solid rgba(255, 255, 255, 0.5);
          border-radius: 24px;
          padding: 20px 32px;
          box-shadow: 0 8px 24px rgba(0,0,0,0.03);
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          display: flex;
          align-items: center;
          gap: 32px;
          position: relative;
        }

        .alarm-row:hover {
          transform: translateY(-2px);
          background: rgba(255, 255, 255, 0.85);
          box-shadow: 0 12px 30px rgba(0,0,0,0.06);
        }

        .alarm-row.status-disabled {
          opacity: 0.6;
        }

        .alarm-row.status-ringing {
          animation: alarm-row-ring-pulse 1.5s infinite alternate;
          border-color: var(--alarm-color);
        }

        @keyframes alarm-row-ring-pulse {
          0% { box-shadow: 0 0 10px rgba(231, 76, 60, 0.1); }
          100% { box-shadow: 0 0 25px var(--alarm-color); }
        }

        .time-display {
          font-size: 48px;
          font-weight: 700;
          color: #1a202c;
          letter-spacing: -1px;
          min-width: 140px;
        }

        .alarm-details {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 4px;
          min-width: 180px;
        }

        .alarm-name {
          font-size: 20px;
          font-weight: 600;
          color: #1a202c;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .status-area {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          font-weight: 700;
          color: #718096;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #718096;
        }

        .status-dot.idle { background: #2ecc71; }
        .status-dot.ringing { background: #e74c3c; animation: flash-dot 0.8s infinite; }
        .status-dot.snoozed { background: #e67e22; }
        .status-dot.silenced { background: #95a5a6; }

        @keyframes flash-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }

        /* Switch toggle styling */
        .switch-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          min-width: 120px;
        }

        .switch {
          position: relative;
          display: inline-block;
          width: 68px;
          height: 32px;
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
          background-color: #d1d5db;
          transition: .4s cubic-bezier(0.4, 0, 0.2, 1);
          border-radius: 32px;
          border: 1px solid rgba(0,0,0,0.05);
          box-shadow: inset 0 2px 4px rgba(0,0,0,0.08);
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 10px;
          font-size: 10px;
          font-weight: 800;
          color: white;
          box-sizing: border-box;
          user-select: none;
        }

        .slider::after {
          content: "OFF";
          margin-left: auto;
          color: #4b5563;
        }

        .slider:before {
          position: absolute;
          content: "";
          height: 26px;
          width: 26px;
          left: 3px;
          bottom: 2.5px;
          background: radial-gradient(circle, #f3f4f6 0%, #d1d5db 60%, #9ca3af 100%);
          border: 1px solid #9ca3af;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.6);
          transition: .4s cubic-bezier(0.4, 0, 0.2, 1);
          border-radius: 50%;
          z-index: 2;
        }

        input:checked + .slider {
          background-color: #488a99;
        }

        input:checked + .slider::after {
          content: "ON";
          margin-right: auto;
          margin-left: 0;
          color: white;
        }

        input:checked + .slider:before {
          transform: translateX(34px);
        }

        .skip-next-text {
          font-size: 11px;
          font-weight: 700;
          color: #488a99;
          cursor: pointer;
          text-decoration: underline;
          transition: color 0.2s;
        }

        .skip-next-text:hover {
          color: #1c566a;
        }

        /* Badges */
        .days-row {
          display: flex;
          gap: 8px;
          margin-right: 16px;
        }

        .day-dot {
          width: 32px;
          height: 32px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          font-weight: 700;
          background: #e2e8f0;
          color: #718096;
          border: 1px solid rgba(0,0,0,0.03);
          transition: all 0.2s;
        }

        .day-dot.active {
          background: #e2b46c;
          color: white;
          box-shadow: 0 4px 10px rgba(226, 180, 108, 0.25);
        }

        /* Action buttons */
        .btn-action {
          padding: 8px 16px;
          font-size: 13px;
          font-weight: 700;
          border-radius: 10px;
          border: none;
          cursor: pointer;
          transition: all 0.2s;
        }

        .btn-snooze { background: #e67e22; color: white; }
        .btn-stop { background: #e74c3c; color: white; }

        .btn-action:hover {
          filter: brightness(1.15);
          transform: translateY(-1px);
        }

        /* Three dots options menu */
        .options-container {
          position: relative;
        }

        .btn-options {
          background: transparent;
          border: none;
          color: #718096;
          cursor: pointer;
          font-size: 20px;
          font-weight: 700;
          padding: 8px;
          border-radius: 50%;
          width: 40px;
          height: 40px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }

        .btn-options:hover {
          background: rgba(0, 0, 0, 0.05);
          color: #1a202c;
        }

        .dropdown-menu {
          position: absolute;
          top: 100%;
          right: 0;
          background: #ffffff !important;
          border: 1px solid rgba(0,0,0,0.08);
          border-radius: 12px;
          box-shadow: 0 10px 25px rgba(0,0,0,0.1);
          z-index: 100;
          min-width: 120px;
          display: none;
          flex-direction: column;
          padding: 6px 0;
          animation: dropdown-slide-in 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .dropdown-menu.open {
          display: flex;
        }

        @keyframes dropdown-slide-in {
          from { transform: translateY(-10px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }

        .dropdown-item {
          padding: 10px 16px;
          font-size: 14px;
          font-weight: 600;
          color: #4a5568 !important;
          text-align: left;
          background: #ffffff !important;
          border: none;
          width: 100%;
          cursor: pointer;
          transition: background 0.15s;
        }

        .dropdown-item:hover {
          background: #f7fafc !important;
          color: #1a202c !important;
        }

        .dropdown-item-delete {
          color: #e53e3e !important;
          background: #ffffff !important;
        }

        .dropdown-item-delete:hover {
          background: #fff5f5 !important;
          color: #e53e3e !important;
        }

        /* Modal styling */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.3);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
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
          background: rgba(255, 255, 255, 0.95);
          border: 1px solid rgba(255, 255, 255, 0.8);
          border-radius: 28px;
          width: 90%;
          max-width: 460px;
          max-height: 90vh;
          overflow-y: auto;
          box-sizing: border-box;
          padding: 32px;
          box-shadow: 0 25px 60px rgba(0,0,0,0.15);
          transform: translateY(20px);
          transition: transform 0.3s;
          color: #2d3748;
        }

        .modal-overlay.open .modal-content {
          transform: translateY(0);
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
        }

        .modal-header h3 {
          margin: 0;
          font-size: 24px;
          font-weight: 700;
          color: #1a202c;
        }

        .close-modal-btn {
          background: transparent;
          border: none;
          color: #718096;
          font-size: 24px;
          cursor: pointer;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: block;
          font-size: 14px;
          font-weight: 700;
          color: #4a5568;
          margin-bottom: 8px;
        }

        .input-text, .select-input {
          width: 100%;
          padding: 12px 16px;
          background: #f7fafc;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          color: #2d3748;
          font-size: 15px;
          box-sizing: border-box;
          outline: none;
          transition: all 0.2s;
        }

        .input-text:focus, .select-input:focus {
          border-color: #488a99;
          background: white;
          box-shadow: 0 0 0 3px rgba(72, 138, 153, 0.15);
        }

        .select-input option {
          background-color: white;
          color: #2d3748;
        }

        .sound-row {
          display: flex;
          gap: 10px;
          align-items: stretch;
          width: 100%;
        }

        .preview-btn {
          background: #f7fafc;
          color: #2d3748;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          padding: 0 15px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 600;
          transition: 0.2s;
          white-space: nowrap;
        }

        .preview-btn:hover {
          background: #edf2f7;
        }

        /* Custom Dropdown Styling */
        .custom-dropdown-container {
          position: relative;
          width: 100%;
        }

        .custom-dropdown-trigger {
          width: 100%;
          padding: 12px 16px;
          background: #f7fafc;
          border: 1px solid #e2e8f0;
          border-radius: 12px;
          color: #2d3748;
          font-size: 15px;
          font-weight: 600;
          text-align: left;
          cursor: pointer;
          display: flex;
          justify-content: space-between;
          align-items: center;
          outline: none;
          transition: all 0.2s;
          box-sizing: border-box;
        }

        .custom-dropdown-trigger:focus {
          border-color: #488a99;
          background: white;
          box-shadow: 0 0 0 3px rgba(72, 138, 153, 0.15);
        }

        .custom-dropdown-options {
          position: absolute;
          top: calc(100% + 4px);
          left: 0;
          right: 0;
          background: white;
          border: 1px solid rgba(0,0,0,0.08);
          border-radius: 12px;
          box-shadow: 0 10px 25px rgba(0,0,0,0.1);
          z-index: 1000;
          display: none;
          flex-direction: column;
          max-height: 200px;
          overflow-y: auto;
          padding: 6px 0;
        }

        .custom-dropdown-options.open {
          display: flex;
        }

        .custom-dropdown-option {
          padding: 10px 16px;
          font-size: 14px;
          font-weight: 600;
          color: #4a5568;
          cursor: pointer;
          transition: background 0.15s;
        }

        .custom-dropdown-option:hover {
          background: #f7fafc;
          color: #1a202c;
        }

        .custom-dropdown-option.selected {
          background: #edf2f7;
          color: #488a99;
          font-weight: 700;
        }

        /* Custom Day Selector in Form */
        .day-select-row {
          display: flex;
          justify-content: space-between;
          margin-top: 4px;
        }

        .day-select-btn {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          border: 1px solid #e2e8f0;
          background: #f7fafc;
          color: #718096;
          font-size: 13px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }

        .day-select-btn:hover {
          background: #edf2f7;
        }

        .day-select-btn.active {
          background: var(--form-color, #2b7a94);
          color: white;
          border-color: var(--form-color, #2b7a94);
          box-shadow: 0 4px 12px rgba(43, 122, 148, 0.2);
        }

        /* Color Selection Swatches */
        .color-swatches {
          display: flex;
          gap: 10px;
          margin-top: 4px;
        }

        .color-swatch {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          cursor: pointer;
          transition: transform 0.2s;
          border: 2px solid transparent;
        }

        .color-swatch:hover {
          transform: scale(1.15);
        }

        .color-swatch.active {
          border-color: #2d3748;
          transform: scale(1.1);
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          margin-top: 28px;
        }

        .btn-cancel {
          background: transparent;
          color: #718096;
          border: 1px solid #e2e8f0;
          padding: 12px 20px;
          border-radius: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: 0.2s;
        }

        .btn-cancel:hover {
          background: #f7fafc;
          color: #1a202c;
        }

        .btn-save {
          background: var(--form-color, #2b7a94);
          color: white;
          border: none;
          padding: 12px 24px;
          border-radius: 12px;
          font-weight: 600;
          cursor: pointer;
          transition: 0.2s;
          box-shadow: 0 4px 12px rgba(43, 122, 148, 0.2);
        }

        .btn-save:hover {
          filter: brightness(1.1);
        }

        /* Ringing/Active Alarm Banner */
        .audio-prompt {
          background: rgba(254, 215, 215, 0.9);
          border: 1px solid rgba(254, 178, 178, 0.8);
          border-radius: 20px;
          padding: 16px 24px;
          margin-bottom: 24px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          color: #9b2c2c;
          box-shadow: 0 10px 20px rgba(155, 44, 44, 0.05);
          animation: banner-glow 1.5s infinite alternate;
        }

        @keyframes banner-glow {
          0% { box-shadow: 0 0 5px rgba(229, 62, 62, 0.1); }
          100% { box-shadow: 0 0 20px rgba(229, 62, 62, 0.3); }
        }
      </style>

      <div class="container">
        <!-- Ringing Alarm Banner -->
        ${ringingAlarm
        ? `
          <div class="audio-prompt">
            <span style="font-weight: 700; display: flex; align-items: center; gap: 8px;">
              🚨 Alarm "${ringingAlarm.name || 'Alarm'}" is ringing!
            </span>
            <div style="display: flex; gap: 12px; align-items: center;">
              <button class="btn-action btn-snooze" data-id="${ringingAlarm.id}">Snooze</button>
              <button class="btn-action btn-stop" data-id="${ringingAlarm.id}">Stop</button>
            </div>
          </div>
        `
        : ""
      }

        <div class="header">
          <div class="title-area">
            <h2>Alarm System</h2>
            <div class="clock-area">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="clock-icon"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              <div class="digital-clock">00:00:00</div>
            </div>
          </div>
          <button class="btn-add">+ Add Alarm</button>
        </div>

        ${alarmsList.length === 0
        ? `
          <div class="empty-state">
            <p>No alarms configured. Click "+ Add Alarm" to create your first alarm or reminder.</p>
          </div>
        `
        : `
          <div class="alarms-list">
            ${alarmsList
          .map((alarm) => {
            const isRinging = alarm.status === "ringing";
            const isSnoozed = alarm.status === "snoozed";
            const isSilenced = alarm.status === "silenced";

            let statusText = alarm.status;
            if (alarm.status === "silenced") statusText = "Skipped Next";

            return `
              <div class="alarm-row status-${alarm.status}" style="--alarm-color: ${alarm.color || '#e2b46c'}">
                <div class="time-display">${alarm.time.substring(0, 5)}</div>
                
                <div class="alarm-details">
                  <div class="alarm-name">${alarm.name || 'Alarm'}</div>
                  <div class="status-area">
                    <span class="status-dot ${alarm.status}"></span>
                    <span>Status: ${statusText}${alarm.area_id ? ` • ${areas.find(a => a.area_id === alarm.area_id)?.name || alarm.area_id}` : ""}</span>
                  </div>
                </div>

                ${alarm.days && alarm.days.length > 0
                ? `
                  <div class="days-row">
                    ${daysShort
                  .map((day, idx) => {
                    const active = alarm.days.includes(idx);
                    return `<div class="day-dot ${active ? "active" : ""}" style="${active ? `background: ${alarm.color || '#e2b46c'}; box-shadow: 0 4px 10px ${alarm.color}40;` : ""}">${day}</div>`;
                  })
                  .join("")}
                  </div>
                `
                : `<div class="days-row"><div style="font-size: 13px; font-weight: 600; color: #718096; background: #e2e8f0; padding: 6px 12px; border-radius: 8px;">One-off Alarm</div></div>`
              }

                <div class="switch-container">
                  ${isRinging || isSnoozed
                  ? `
                    <div style="display: flex; gap: 8px;">
                      ${isRinging ? `<button class="btn-action btn-snooze" data-id="${alarm.id}" style="padding: 6px 12px; font-size: 12px; border-radius: 8px;">Snooze</button>` : ""}
                      <button class="btn-action btn-stop" data-id="${alarm.id}" style="padding: 6px 12px; font-size: 12px; border-radius: 8px;">Stop</button>
                    </div>
                  `
                  : `
                    <label class="switch">
                      <input type="checkbox" class="toggle-enabled" data-id="${alarm.id}" ${alarm.enabled ? "checked" : ""}>
                      <span class="slider"></span>
                    </label>
                    ${alarm.enabled && alarm.days && alarm.days.length > 0
                    ? `<span class="skip-next-text btn-skip ${isSilenced ? 'silenced' : ''}" data-id="${alarm.id}">${isSilenced ? 'Unskip' : 'Skip Next'}</span>`
                    : ""
                    }
                  `
                  }
                </div>

                <div class="options-container">
                  <button class="btn-options" title="Options">•••</button>
                  <div class="dropdown-menu">
                    <button class="dropdown-item icon-btn-edit" data-id="${alarm.id}">Edit</button>
                    <button class="dropdown-item dropdown-item-delete icon-btn-delete" data-id="${alarm.id}">Delete</button>
                  </div>
                </div>
              </div>
            `;
          })
          .join("")}
          </div>
        `
      }
      </div>

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
                <input type="text" id="name" class="input-text" placeholder="Alarm name..." value="${this._formState.name
      }">
              </div>

              <div class="form-group">
                <label for="time">Time</label>
                <input type="time" id="time" class="input-text" style="font-size: 18px; font-weight: 700; width: 140px;" value="${this._formState.time
      }">
              </div>

              <div class="form-group">
                <label>Repeat Days (Leave empty for one-off)</label>
                <div class="day-select-row">
                  ${daysShort
        .map((day, idx) => {
          const active = this._formState.days.includes(idx);
          return `
                      <button type="button" class="day-select-btn ${active ? "active" : ""
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
                      <div class="color-swatch ${active ? "active" : ""
            }" style="background: ${c}; --swatch-color: ${c}" data-color="${c}"></div>
                    `;
        })
        .join("")}
                </div>
              </div>

              <div class="form-group">
                <label>Alarm Sound</label>
                <div class="sound-row">
                  <div class="custom-dropdown-container">
                    <button type="button" class="custom-dropdown-trigger" id="sound-trigger">
                      <span>${currentSoundName}</span>
                      <span class="arrow">&#9662;</span>
                    </button>
                    <div class="custom-dropdown-options sound-options ${this._soundDropdownOpen ? 'open' : ''}">
                      ${sounds
                        .map(
                          (s) => `
                            <div class="custom-dropdown-option ${this._formState.sound === s.file ? 'selected' : ''}" data-value="${s.file}">
                              ${s.name}
                            </div>
                          `
                        )
                        .join("")}
                    </div>
                  </div>
                  <button type="button" class="preview-btn">🔊 Preview</button>
                </div>
              </div>

              <div class="form-group">
                <label for="snooze_duration">Snooze Duration (minutes)</label>
                <input type="number" id="snooze_duration" class="input-text" min="1" max="60" style="width: 80px;" value="${this._formState.snooze_duration
      }">
              </div>

              <div class="form-group">
                <label>Output Speaker (Optional, plays in house)</label>
                <div class="custom-dropdown-container">
                  <button type="button" class="custom-dropdown-trigger" id="mp-trigger">
                    <span>${currentMpName}</span>
                    <span class="arrow">&#9662;</span>
                  </button>
                  <div class="custom-dropdown-options mp-options ${this._mpDropdownOpen ? 'open' : ''}">
                    <div class="custom-dropdown-option ${this._formState.media_player === '' ? 'selected' : ''}" data-value="">
                      Browser Only
                    </div>
                    ${this._mediaPlayers
                      .map(
                        (mp) => `
                          <div class="custom-dropdown-option ${this._formState.media_player === mp.entity_id ? 'selected' : ''}" data-value="${mp.entity_id}">
                            ${mp.name}
                          </div>
                        `
                      )
                      .join("")}
                  </div>
                </div>
              </div>

              <div class="form-group">
                <label>Area (Optional)</label>
                <div class="custom-dropdown-container">
                  <button type="button" class="custom-dropdown-trigger" id="area-trigger">
                    <span>${currentAreaName}</span>
                    <span class="arrow">&#9662;</span>
                  </button>
                  <div class="custom-dropdown-options area-options ${this._areaDropdownOpen ? 'open' : ''}">
                    <div class="custom-dropdown-option ${this._formState.area_id === '' ? 'selected' : ''}" data-value="">
                      No Area
                    </div>
                    ${areas
                      .map(
                        (area) => `
                          <div class="custom-dropdown-option ${this._formState.area_id === area.area_id ? 'selected' : ''}" data-value="${area.area_id}">
                            ${area.name}
                          </div>
                        `
                      )
                      .join("")}
                  </div>
                </div>
              </div>

              <div class="modal-footer">
                <button type="button" class="btn-cancel">Cancel</button>
                <button type="submit" class="btn-save">${this._editingId ? "Save Changes" : "Create Alarm"}</button>
              </div>
            </form>
          </div>
        </div>
      `;

    this._setupEventListeners();
    this._updateClock();
  }

  // Setup Event Handlers
  _setupEventListeners() {
    const shadow = this.shadowRoot;

    // Add alarm button
    const btnAdd = shadow.querySelector(".btn-add");
    if (btnAdd) {
      btnAdd.addEventListener("click", () => this._openAddModal());
    }

    // Toggle enabled switches
    shadow.querySelectorAll(".toggle-enabled").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = e.target.getAttribute("data-id");
        this._toggleAlarm(id, e.target.checked);
      });
    });

    // Quick action buttons
    shadow.querySelectorAll(".btn-snooze").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._snoozeAlarm(btn.getAttribute("data-id"));
      });
    });

    shadow.querySelectorAll(".btn-stop").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._stopAlarm(btn.getAttribute("data-id"));
      });
    });

    shadow.querySelectorAll(".btn-skip").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const alarm = this._alarms[btn.getAttribute("data-id")];
        if (alarm) this._toggleSkipNext(alarm);
      });
    });

    // Three dots options menu
    shadow.querySelectorAll(".btn-options").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = btn.nextElementSibling;
        const wasOpen = menu.classList.contains("open");
        
        // Close all other menus first
        shadow.querySelectorAll(".dropdown-menu").forEach((m) => {
          m.classList.remove("open");
        });
        
        if (!wasOpen) {
          menu.classList.add("open");
        }
      });
    });

    // Edit and Delete dropdown buttons
    shadow.querySelectorAll(".icon-btn-edit").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const alarm = this._alarms[btn.getAttribute("data-id")];
        if (alarm) this._openEditModal(alarm);
      });
    });

    shadow.querySelectorAll(".icon-btn-delete").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._deleteAlarm(btn.getAttribute("data-id"));
      });
    });

    // Custom sound and media player dropdown triggers
    const soundTrigger = shadow.getElementById("sound-trigger");
    if (soundTrigger) {
      soundTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        this._soundDropdownOpen = !this._soundDropdownOpen;
        this._mpDropdownOpen = false;
        this._areaDropdownOpen = false;
        this.render();
      });
    }

    const mpTrigger = shadow.getElementById("mp-trigger");
    if (mpTrigger) {
      mpTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        this._mpDropdownOpen = !this._mpDropdownOpen;
        this._soundDropdownOpen = false;
        this._areaDropdownOpen = false;
        this.render();
      });
    }

    const areaTrigger = shadow.getElementById("area-trigger");
    if (areaTrigger) {
      areaTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        this._areaDropdownOpen = !this._areaDropdownOpen;
        this._soundDropdownOpen = false;
        this._mpDropdownOpen = false;
        this.render();
      });
    }

    // Custom dropdown option clicks
    shadow.querySelectorAll(".custom-dropdown-option").forEach((opt) => {
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        const val = opt.getAttribute("data-value");
        const parent = opt.parentElement;
        if (parent.classList.contains("sound-options")) {
          this._formState.sound = val;
          this._soundDropdownOpen = false;
        } else if (parent.classList.contains("mp-options")) {
          this._formState.media_player = val || "";
          this._mpDropdownOpen = false;
        } else if (parent.classList.contains("area-options")) {
          this._formState.area_id = val || "";
          this._areaDropdownOpen = false;
        }
        this.render();
      });
    });

    // Close all active dropdowns when clicking anywhere in the card's shadow root
    shadow.addEventListener("click", () => {
      this._soundDropdownOpen = false;
      this._mpDropdownOpen = false;
      this._areaDropdownOpen = false;
      shadow.querySelectorAll(".dropdown-menu").forEach((m) => {
        m.classList.remove("open");
      });
      shadow.querySelectorAll(".custom-dropdown-options").forEach((d) => {
        d.classList.remove("open");
      });
    });

    // Modal Close buttons
    const closeModalBtn = shadow.querySelector(".close-modal-btn");
    if (closeModalBtn) {
      closeModalBtn.addEventListener("click", () => this._closeModal());
    }
    const btnCancel = shadow.querySelector(".btn-cancel");
    if (btnCancel) {
      btnCancel.addEventListener("click", () => this._closeModal());
    }

    // Day multi-selector in Modal
    shadow.querySelectorAll(".day-select-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const dayIdx = parseInt(btn.getAttribute("data-day"), 10);
        this._handleDayToggle(dayIdx);
      });
    });

    // Color swatches in Modal
    shadow.querySelectorAll(".color-swatch").forEach((swatch) => {
      swatch.addEventListener("click", (e) => {
        e.stopPropagation();
        this._formState.color = swatch.getAttribute("data-color");
        this.render();
      });
    });

    // Sound preview button in Modal
    const previewBtn = shadow.querySelector(".preview-btn");
    if (previewBtn) {
      previewBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._previewSound();
      });
    }

    // Bind form inputs to _formState to survive renders
    const nameInput = shadow.getElementById("name");
    if (nameInput) {
      nameInput.addEventListener("input", (e) => {
        this._formState.name = e.target.value;
      });
    }

    const timeInput = shadow.getElementById("time");
    if (timeInput) {
      const updateTime = (e) => {
        this._formState.time = e.target.value;
      };
      timeInput.addEventListener("change", updateTime);
      timeInput.addEventListener("input", updateTime);
    }

    const snoozeInput = shadow.getElementById("snooze_duration");
    if (snoozeInput) {
      snoozeInput.addEventListener("input", (e) => {
        this._formState.snooze_duration = parseInt(e.target.value, 10) || 1;
      });
    }

    // Form submit
    const alarmForm = shadow.getElementById("alarm-form");
    if (alarmForm) {
      alarmForm.addEventListener("submit", (e) => this._saveAlarm(e));
    }
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
