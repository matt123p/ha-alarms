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
      area_id: "",
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
    this.render();
  }

  // Home Assistant custom sidebar panels receive panel/narrow props instead
  // of Lovelace card config. Keep them so the layout can adapt by context.
  set panel(panel) {
    this._panel = panel;
    this.render();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this.render();
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
      btn.textContent = "Preview";
      return;
    }

    const soundUrl = `/alarms_static/sounds/${sound}`;
    this._previewAudio = new Audio(soundUrl);
    this._previewAudio.play().catch(e => console.warn(e));
    btn.textContent = "Stop";

    this._previewAudio.onended = () => {
      this._previewAudio = null;
      btn.textContent = "Preview";
    };
  }

  async _saveAlarm(e) {
    e.preventDefault();
    const shadow = this.shadowRoot;

    const name = shadow.getElementById("name").value.trim() || "Alarm";
    const time = shadow.getElementById("time").value;
    const color = this._safeColor(this._formState.color, "#3498db");
    const sound = shadow.getElementById("sound").value;
    const snooze_duration = parseInt(shadow.getElementById("snooze_duration").value, 10);
    const media_player = shadow.getElementById("media_player").value || null;
    const area_id = shadow.getElementById("area_id").value || null;
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

  _escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
  }

  _safeColor(value, fallback = "#e2b46c") {
    return /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : fallback;
  }

  _formatNextTrigger(value) {
    if (!value) return "Not scheduled";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Scheduled";
    return date.toLocaleString([], {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      day: "numeric",
      month: "short",
    });
  }

  _formatSchedule(days) {
    if (!days || days.length === 0) return "One-off";
    const sorted = [...days].sort();
    const sameDays = (values) => sorted.length === values.length && values.every((day, idx) => sorted[idx] === day);
    if (sameDays([0, 1, 2, 3, 4, 5, 6])) return "Daily";
    if (sameDays([0, 1, 2, 3, 4])) return "Weekdays";
    if (sameDays([5, 6])) return "Weekends";
    const names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    return sorted.map((idx) => names[idx]).join(", ");
  }

  // Render HTML Templates
  render() {
    if (!this._hass) return;

    const statusOrder = {
      ringing: 0,
      snoozed: 1,
      silenced: 2,
      idle: 3,
      disabled: 4,
    };
    const alarmsList = Object.values(this._alarms).sort((a, b) => {
      const statusDiff = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3);
      if (statusDiff !== 0) return statusDiff;
      return String(a.time || "").localeCompare(String(b.time || ""));
    });
    const enabledCount = alarmsList.filter((alarm) => alarm.enabled).length;
    const isPanelPage = Boolean(this._panel) || !this._config;
    this.toggleAttribute("panel-page", isPanelPage);
    const daysShort = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const ringingCount = alarmsList.filter((alarm) => alarm.status === "ringing").length;
    const snoozedCount = alarmsList.filter((alarm) => alarm.status === "snoozed").length;
    const skippedCount = alarmsList.filter((alarm) => alarm.status === "silenced").length;
    const upcomingAlarms = alarmsList
      .map((alarm) => ({ alarm, triggerMs: Date.parse(alarm.next_trigger || "") }))
      .filter((item) => item.alarm.enabled && Number.isFinite(item.triggerMs))
      .sort((a, b) => a.triggerMs - b.triggerMs);
    const nextAlarm = upcomingAlarms[0]?.alarm;
    const nextAlarmName = nextAlarm ? this._escapeHtml(nextAlarm.name || "Alarm") : "No upcoming alarm";
    const nextAlarmTime = nextAlarm ? this._formatNextTrigger(nextAlarm.next_trigger) : "Enable or create an alarm";

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

    const areas = Object.values(this._hass.areas || {});

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
          display: block;
          font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          color: var(--primary-text-color, #2d3748);
          width: 100%;
          max-width: 100%;
          min-width: 0;
          box-sizing: border-box;
        }

        :host([panel-page]) {
          min-height: calc(100dvh - 64px);
          padding: clamp(12px, 2vw, 24px);
          background: var(--primary-background-color, #f5f7fa);
        }

        *, *::before, *::after {
          box-sizing: border-box;
        }

        .container {
          background: var(--card-background-color, #ffffff);
          border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
          border-radius: var(--ha-card-border-radius, 12px);
          padding: clamp(16px, 3vw, 28px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.08));
          position: relative;
          overflow: visible;
          display: flex;
          flex-direction: column;
          gap: 18px;
          min-width: 0;
        }

        .container.panel-page {
          width: min(1240px, 100%);
          min-height: calc(100dvh - 112px);
          margin: 0 auto;
          padding: 0;
          background: transparent;
          border: 0;
          border-radius: 0;
          box-shadow: none;
          gap: 22px;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          flex-wrap: wrap;
          gap: 12px 18px;
        }

        .panel-page .header {
          padding: 4px 0 0;
          gap: 16px 24px;
        }

        .title-area h2 {
          margin: 0;
          font-size: clamp(24px, 4vw, 32px);
          font-weight: 700;
          color: var(--primary-text-color, #1a202c);
          letter-spacing: 0;
        }

        .panel-page .title-area h2 {
          font-size: clamp(32px, 5vw, 44px);
        }

        .clock-area {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 4px;
          color: var(--secondary-text-color, #4a5568);
          flex-wrap: wrap;
        }

        .clock-icon {
          width: 24px;
          height: 24px;
          stroke: #2d3748;
        }

        .digital-clock {
          font-size: clamp(18px, 3vw, 24px);
          font-weight: 500;
          letter-spacing: 0;
          color: var(--primary-text-color, #1a202c);
        }

        .summary-text {
          font-size: 13px;
          font-weight: 600;
          color: var(--secondary-text-color, #718096);
        }

        .page-summary {
          display: grid;
          grid-template-columns: minmax(260px, 1.4fr) repeat(3, minmax(150px, 1fr));
          gap: 12px;
        }

        .summary-card {
          background: var(--card-background-color, #ffffff);
          border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
          border-radius: 12px;
          padding: 14px 16px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.06));
          min-width: 0;
        }

        .summary-card.primary {
          border-left: 5px solid var(--primary-color, #2b7a94);
        }

        .summary-label {
          color: var(--secondary-text-color, #718096);
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0;
          margin-bottom: 6px;
        }

        .summary-value {
          color: var(--primary-text-color, #1a202c);
          font-size: 22px;
          font-weight: 750;
          line-height: 1.15;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .summary-subvalue {
          color: var(--secondary-text-color, #718096);
          font-size: 13px;
          font-weight: 600;
          margin-top: 4px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .btn-add {
          background: var(--primary-color, #2b7a94);
          color: white;
          border: none;
          padding: 10px 16px;
          border-radius: 10px;
          font-weight: 600;
          font-size: 15px;
          cursor: pointer;
          transition: filter 0.2s, transform 0.2s;
          display: flex;
          align-items: center;
          gap: 8px;
          min-height: 40px;
        }

        .btn-add:hover {
          filter: brightness(1.08);
          transform: translateY(-1px);
        }

        /* Alarms List */
        .alarms-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
          min-width: 0;
        }

        .panel-page .alarms-list {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 390px), 1fr));
          gap: 14px;
          align-items: start;
        }

        .empty-state {
          text-align: center;
          padding: 44px 20px;
          background: var(--secondary-background-color, #f7fafc);
          border-radius: 12px;
          border: 1px dashed var(--divider-color, rgba(0,0,0,0.12));
        }

        .panel-page .empty-state {
          background: var(--card-background-color, #ffffff);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.06));
        }

        .empty-state p {
          color: #718096;
          font-size: 16px;
          margin-top: 12px;
          font-weight: 500;
        }

        /* Alarm Row */
        .alarm-row {
          background: var(--secondary-background-color, #f8fafc);
          border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
          border-left: 5px solid var(--alarm-color);
          border-radius: 12px;
          padding: 14px 16px;
          transition: background 0.2s, box-shadow 0.2s;
          display: grid;
          grid-template-columns: minmax(92px, 0.7fr) minmax(140px, 1.2fr) minmax(210px, 1fr) auto auto;
          align-items: center;
          gap: 12px 16px;
          position: relative;
          min-width: 0;
        }

        .panel-page .alarm-row {
          grid-template-columns: minmax(96px, auto) minmax(0, 1fr) auto;
          grid-template-areas:
            "time details menu"
            "time details actions"
            "days days days";
          align-items: start;
          min-height: 164px;
          padding: 18px;
          background: var(--card-background-color, #ffffff);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.08));
        }

        .panel-page .time-display {
          grid-area: time;
        }

        .panel-page .alarm-details {
          grid-area: details;
        }

        .panel-page .days-row {
          grid-area: days;
          grid-column: 1 / -1;
          width: min(100%, 356px);
          grid-template-columns: repeat(7, 44px);
          justify-content: start;
        }

        .panel-page .day-dot {
          height: 32px;
        }

        .panel-page .switch-container {
          grid-area: actions;
          justify-self: end;
          align-items: flex-end;
        }

        .panel-page .options-container {
          grid-area: menu;
          justify-self: end;
        }

        .alarm-row:hover {
          background: var(--card-background-color, #ffffff);
          box-shadow: 0 4px 14px rgba(0,0,0,0.06);
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
          font-size: clamp(34px, 5vw, 46px);
          font-weight: 700;
          color: var(--primary-text-color, #1a202c);
          letter-spacing: 0;
          line-height: 1;
          min-width: 0;
        }

        .alarm-details {
          display: flex;
          flex-direction: column;
          gap: 4px;
          min-width: 0;
        }

        .alarm-name {
          font-size: 20px;
          font-weight: 600;
          color: var(--primary-text-color, #1a202c);
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
          color: var(--secondary-text-color, #718096);
          text-transform: uppercase;
          letter-spacing: 0;
          min-width: 0;
        }

        .status-area span:last-child {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .alarm-meta-row {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 8px;
          min-width: 0;
        }

        .meta-chip {
          background: var(--secondary-background-color, #f7fafc);
          border: 1px solid var(--divider-color, #e2e8f0);
          border-radius: 8px;
          color: var(--secondary-text-color, #4a5568);
          font-size: 12px;
          font-weight: 650;
          line-height: 1.2;
          min-width: 0;
          max-width: 100%;
          padding: 6px 8px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .meta-chip.next {
          color: var(--primary-text-color, #1a202c);
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
          min-width: 84px;
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
          color: var(--primary-color, #488a99);
          cursor: pointer;
          text-decoration: underline;
          transition: color 0.2s;
        }

        .skip-next-text:hover {
          color: #1c566a;
        }

        /* Badges */
        .days-row {
          display: grid;
          grid-template-columns: repeat(7, minmax(36px, 1fr));
          gap: 6px;
          width: min(100%, 336px);
          min-width: 0;
        }

        .day-dot {
          width: 100%;
          min-width: 0;
          height: 30px;
          border-radius: 999px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
          font-weight: 700;
          background: var(--secondary-background-color, #f7fafc);
          color: var(--secondary-text-color, #718096);
          border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
        }

        .day-dot.active {
          color: white;
          border-color: transparent;
          box-shadow: none;
        }

        .one-off-badge {
          grid-column: 1 / -1;
          justify-self: start;
          font-size: 13px;
          font-weight: 600;
          color: var(--secondary-text-color, #718096);
          background: var(--divider-color, #e2e8f0);
          padding: 6px 10px;
          border-radius: 8px;
          white-space: nowrap;
        }

        /* Action buttons */
        .btn-action {
          padding: 8px 12px;
          font-size: 13px;
          font-weight: 700;
          border-radius: 10px;
          border: none;
          cursor: pointer;
          transition: all 0.2s;
        }

        .active-actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          justify-content: center;
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
          color: var(--secondary-text-color, #718096);
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
          padding: 16px;
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
          background: var(--card-background-color, #ffffff);
          border: 1px solid var(--divider-color, rgba(0,0,0,0.08));
          border-radius: var(--ha-card-border-radius, 12px);
          width: min(720px, 100%);
          max-height: calc(100dvh - 32px);
          overflow-y: auto;
          padding: clamp(18px, 3vw, 28px);
          box-shadow: 0 25px 60px rgba(0,0,0,0.15);
          transform: translateY(20px);
          transition: transform 0.3s;
          color: var(--primary-text-color, #2d3748);
        }

        .modal-overlay.open .modal-content {
          transform: translateY(0);
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          margin-bottom: 20px;
        }

        .modal-header h3 {
          margin: 0;
          font-size: 24px;
          font-weight: 700;
          color: var(--primary-text-color, #1a202c);
        }

        .close-modal-btn {
          background: transparent;
          border: none;
          color: #718096;
          font-size: 24px;
          cursor: pointer;
        }

        #alarm-form {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 16px;
        }

        .form-group {
          margin-bottom: 0;
          min-width: 0;
        }

        .form-group.full-width,
        .modal-footer {
          grid-column: 1 / -1;
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
          background: var(--secondary-background-color, #f7fafc);
          border: 1px solid var(--divider-color, #e2e8f0);
          border-radius: 10px;
          color: var(--primary-text-color, #2d3748);
          font-size: 15px;
          outline: none;
          transition: all 0.2s;
          min-height: 44px;
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
          align-items: center;
          width: 100%;
          min-width: 0;
        }

        .sound-row .select-input {
          min-width: 0;
        }

        .preview-btn {
          background: var(--secondary-background-color, #f7fafc);
          color: var(--primary-text-color, #2d3748);
          border: 1px solid var(--divider-color, #e2e8f0);
          border-radius: 10px;
          padding: 0 14px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 600;
          transition: 0.2s;
          white-space: nowrap;
          min-height: 44px;
        }

        .preview-btn:hover {
          background: #edf2f7;
        }

        /* Custom Day Selector in Form */
        .day-select-row {
          display: grid;
          grid-template-columns: repeat(7, minmax(32px, 1fr));
          gap: 8px;
          margin-top: 4px;
        }

        .day-select-btn {
          width: 100%;
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
          flex-wrap: wrap;
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
          margin-top: 8px;
          flex-wrap: wrap;
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
          border-radius: 12px;
          padding: 14px 16px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
          color: #9b2c2c;
          box-shadow: 0 10px 20px rgba(155, 44, 44, 0.05);
          animation: banner-glow 1.5s infinite alternate;
        }

        .audio-prompt-title {
          font-weight: 700;
          display: flex;
          align-items: center;
          gap: 8px;
          min-width: 0;
        }

        .audio-prompt-actions {
          display: flex;
          gap: 8px;
          align-items: center;
          flex-wrap: wrap;
        }

        @keyframes banner-glow {
          0% { box-shadow: 0 0 5px rgba(229, 62, 62, 0.1); }
          100% { box-shadow: 0 0 20px rgba(229, 62, 62, 0.3); }
        }

        @media (max-width: 900px) {
          .page-summary {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }

          .alarm-row {
            grid-template-columns: minmax(92px, auto) minmax(0, 1fr) auto;
          }

          .card-page .days-row {
            grid-column: 1 / -1;
            width: 100%;
          }
        }

        @media (max-width: 620px) {
          .container {
            padding: 14px;
            gap: 14px;
          }

          .header {
            align-items: stretch;
          }

          .btn-add {
            width: 100%;
            justify-content: center;
          }

          .page-summary {
            grid-template-columns: 1fr;
          }

          .summary-value,
          .summary-subvalue {
            white-space: normal;
          }

          .alarm-row {
            grid-template-columns: minmax(0, 1fr) auto;
            grid-template-areas:
              "time menu"
              "details details"
              "days days"
              "actions actions";
          }

          .time-display { grid-area: time; }
          .alarm-details { grid-area: details; }
          .days-row { grid-area: days; }
          .switch-container {
            grid-area: actions;
            justify-self: stretch;
            align-items: flex-start;
          }
          .options-container {
            grid-area: menu;
            justify-self: end;
          }

          .alarm-name {
            white-space: normal;
          }

          #alarm-form {
            grid-template-columns: 1fr;
          }

          .form-group.full-width,
          .modal-footer {
            grid-column: auto;
          }

          .sound-row {
            flex-direction: column;
            align-items: stretch;
          }

          .modal-footer {
            justify-content: stretch;
          }

          .modal-footer button {
            flex: 1 1 140px;
          }
        }
      </style>

      <div class="container ${isPanelPage ? "panel-page" : "card-page"}">
        <!-- Ringing Alarm Banner -->
        ${ringingAlarm
        ? `
          <div class="audio-prompt">
            <span class="audio-prompt-title">
              Alarm "${this._escapeHtml(ringingAlarm.name || 'Alarm')}" is ringing
            </span>
            <div class="audio-prompt-actions">
              <button class="btn-action btn-snooze" data-id="${this._escapeHtml(ringingAlarm.id)}">Snooze</button>
              <button class="btn-action btn-stop" data-id="${this._escapeHtml(ringingAlarm.id)}">Stop</button>
            </div>
          </div>
        `
        : ""
      }

        <div class="header">
          <div class="title-area">
            <h2>Alarms</h2>
            <div class="clock-area">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="clock-icon"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
              <div class="digital-clock">00:00:00</div>
              <div class="summary-text">${alarmsList.length} ${alarmsList.length === 1 ? "alarm" : "alarms"} | ${enabledCount} enabled</div>
            </div>
          </div>
          <button class="btn-add">+ Add Alarm</button>
        </div>

        ${isPanelPage
        ? `
          <div class="page-summary">
            <div class="summary-card primary">
              <div class="summary-label">Next</div>
              <div class="summary-value">${nextAlarmName}</div>
              <div class="summary-subvalue">${this._escapeHtml(nextAlarmTime)}</div>
            </div>
            <div class="summary-card">
              <div class="summary-label">Enabled</div>
              <div class="summary-value">${enabledCount}/${alarmsList.length}</div>
              <div class="summary-subvalue">Ready to ring</div>
            </div>
            <div class="summary-card">
              <div class="summary-label">Active</div>
              <div class="summary-value">${ringingCount + snoozedCount}</div>
              <div class="summary-subvalue">${ringingCount} ringing, ${snoozedCount} snoozed</div>
            </div>
            <div class="summary-card">
              <div class="summary-label">Skipped</div>
              <div class="summary-value">${skippedCount}</div>
              <div class="summary-subvalue">Next occurrence</div>
            </div>
          </div>
        `
        : ""
      }

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
            const alarmStatus = String(alarm.status || "idle").replace(/[^a-z0-9_-]/gi, "") || "idle";
            const isRinging = alarmStatus === "ringing";
            const isSnoozed = alarmStatus === "snoozed";
            const isSilenced = alarmStatus === "silenced";

            let statusText = alarmStatus;
            if (alarmStatus === "silenced") statusText = "Skipped Next";
            const alarmColor = this._safeColor(alarm.color);
            const alarmArea = alarm.area_id ? (areas.find(a => a.area_id === alarm.area_id)?.name || alarm.area_id) : "";
            const alarmId = this._escapeHtml(alarm.id);
            const scheduleText = this._formatSchedule(alarm.days);
            const nextText = alarm.enabled ? this._formatNextTrigger(alarm.next_trigger) : "Disabled";

            return `
              <div class="alarm-row status-${alarmStatus}" style="--alarm-color: ${alarmColor}">
                <div class="time-display">${this._escapeHtml(String(alarm.time || "").substring(0, 5))}</div>
                
                <div class="alarm-details">
                  <div class="alarm-name">${this._escapeHtml(alarm.name || 'Alarm')}</div>
                  <div class="status-area">
                    <span class="status-dot ${alarmStatus}"></span>
                    <span>${this._escapeHtml(statusText)}${alarmArea ? ` | ${this._escapeHtml(alarmArea)}` : ""}</span>
                  </div>
                  <div class="alarm-meta-row">
                    <span class="meta-chip">${this._escapeHtml(scheduleText)}</span>
                    <span class="meta-chip next">${this._escapeHtml(nextText)}</span>
                  </div>
                </div>

                ${alarm.days && alarm.days.length > 0
                ? `
                  <div class="days-row">
                    ${daysShort
                  .map((day, idx) => {
                    const active = alarm.days.includes(idx);
                    return `<div class="day-dot ${active ? "active" : ""}" style="${active ? `background: ${alarmColor};` : ""}">${day}</div>`;
                  })
                  .join("")}
                  </div>
                `
                : `<div class="days-row"><div class="one-off-badge">One-off Alarm</div></div>`
              }

                <div class="switch-container">
                  ${isRinging || isSnoozed
                  ? `
                    <div class="active-actions">
                      ${isRinging ? `<button class="btn-action btn-snooze" data-id="${alarmId}">Snooze</button>` : ""}
                      <button class="btn-action btn-stop" data-id="${alarmId}">Stop</button>
                    </div>
                  `
                  : `
                    <label class="switch">
                      <input type="checkbox" class="toggle-enabled" data-id="${alarmId}" ${alarm.enabled ? "checked" : ""}>
                      <span class="slider"></span>
                    </label>
                    ${alarm.enabled && alarm.days && alarm.days.length > 0
                    ? `<span class="skip-next-text btn-skip ${isSilenced ? 'silenced' : ''}" data-id="${alarmId}">${isSilenced ? 'Unskip' : 'Skip Next'}</span>`
                    : ""
                    }
                  `
                  }
                </div>

                <div class="options-container">
                  <button class="btn-options" title="Options">...</button>
                  <div class="dropdown-menu">
                    <button class="dropdown-item icon-btn-edit" data-id="${alarmId}">Edit</button>
                    <button class="dropdown-item dropdown-item-delete icon-btn-delete" data-id="${alarmId}">Delete</button>
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
          <div class="modal-content" style="--form-color: ${this._safeColor(this._formState.color, "#3498db")}">
            <div class="modal-header">
              <h3>${this._editingId ? "Edit Alarm" : "Add Alarm"}</h3>
              <button class="close-modal-btn" aria-label="Close">&times;</button>
            </div>
            
            <form id="alarm-form">
              <div class="form-group full-width">
                <label for="name">Alarm Name / Label</label>
                <input type="text" id="name" class="input-text" placeholder="Alarm name..." value="${this._escapeHtml(this._formState.name)
      }">
              </div>

              <div class="form-group">
                <label for="time">Time</label>
                <input type="time" id="time" class="input-text" required value="${this._escapeHtml(this._formState.time)
      }">
              </div>

              <div class="form-group">
                <label for="snooze_duration">Snooze Duration (minutes)</label>
                <input type="number" id="snooze_duration" class="input-text" min="1" max="60" required value="${this._escapeHtml(this._formState.snooze_duration)
      }">
              </div>

              <div class="form-group full-width">
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

              <div class="form-group full-width">
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

              <div class="form-group full-width">
                <label>Alarm Sound</label>
                <div class="sound-row">
                  <select id="sound" class="select-input">
                    ${sounds
                      .map((s) => `
                        <option value="${this._escapeHtml(s.file)}" ${this._formState.sound === s.file ? "selected" : ""}>
                          ${this._escapeHtml(s.name)}
                        </option>
                      `)
                      .join("")}
                  </select>
                  <button type="button" class="preview-btn">Preview</button>
                </div>
              </div>

              <div class="form-group">
                <label for="media_player">Output Speaker (Optional)</label>
                <select id="media_player" class="select-input">
                  <option value="" ${this._formState.media_player === "" ? "selected" : ""}>Browser Only</option>
                  ${this._mediaPlayers
                    .map((mp) => `
                      <option value="${this._escapeHtml(mp.entity_id)}" ${this._formState.media_player === mp.entity_id ? "selected" : ""}>
                        ${this._escapeHtml(mp.name)}
                      </option>
                    `)
                    .join("")}
                </select>
              </div>

              <div class="form-group">
                <label for="area_id">Area (Optional)</label>
                <select id="area_id" class="select-input">
                  <option value="" ${this._formState.area_id === "" ? "selected" : ""}>No Area</option>
                  ${areas
                    .map((area) => `
                      <option value="${this._escapeHtml(area.area_id)}" ${this._formState.area_id === area.area_id ? "selected" : ""}>
                        ${this._escapeHtml(area.name)}
                      </option>
                    `)
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

    // Close row option menus when clicking anywhere in the card's shadow root
    shadow.onclick = () => {
      shadow.querySelectorAll(".dropdown-menu").forEach((m) => {
        m.classList.remove("open");
      });
    };

    // Modal Close buttons
    const closeModalBtn = shadow.querySelector(".close-modal-btn");
    if (closeModalBtn) {
      closeModalBtn.addEventListener("click", () => this._closeModal());
    }
    const btnCancel = shadow.querySelector(".btn-cancel");
    if (btnCancel) {
      btnCancel.addEventListener("click", () => this._closeModal());
    }

    const modalOverlay = shadow.querySelector(".modal-overlay");
    if (modalOverlay) {
      modalOverlay.addEventListener("click", (e) => {
        if (e.target === modalOverlay) {
          this._closeModal();
        }
      });
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

    const soundSelect = shadow.getElementById("sound");
    if (soundSelect) {
      soundSelect.addEventListener("change", (e) => {
        this._formState.sound = e.target.value;
      });
    }

    const mediaPlayerSelect = shadow.getElementById("media_player");
    if (mediaPlayerSelect) {
      mediaPlayerSelect.addEventListener("change", (e) => {
        this._formState.media_player = e.target.value || "";
      });
    }

    const areaSelect = shadow.getElementById("area_id");
    if (areaSelect) {
      areaSelect.addEventListener("change", (e) => {
        this._formState.area_id = e.target.value || "";
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
