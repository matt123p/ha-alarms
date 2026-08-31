"""LLM tools for the Alarms integration."""

from homeassistant.components import llm
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent
from homeassistant.helpers.llm import LLM_API_ASSIST, IntentTool, LLMContext, Tool

LLM_INTENTS = (
    "AlarmsCreate",
    "AlarmsDelete",
    "AlarmsUpdate",
    "AlarmsSnooze",
    "AlarmsDismiss",
)


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> llm.LLMTools | None:
    """Expose alarm intents to Home Assistant's built-in Assist LLM API."""
    if api_id != LLM_API_ASSIST:
        return None

    tools: list[Tool] = [
        IntentTool(handler.intent_type, handler)
        for handler in intent.async_get(hass)
        if handler.intent_type in LLM_INTENTS
    ]
    if not tools:
        return None

    return llm.LLMTools(
        tools=tools,
        prompt=(
            "Use the Alarms tools for wake-up alarms. If the user does not name "
            "a room, alarm creation, snooze, and dismiss default to the area of "
            "the voice satellite that received the request."
        ),
    )
