"""light trigger component."""
import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change,
)
from homeassistant.util import dt as dt_util

DOMAIN = "peak_control"
STOPPED_DEVICES = "stopped_devices"

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: {
            vol.Required("estimated_hourly_consumtion_sensor"): cv.entity_id,
            vol.Required("max_hourly_consumption"): cv.entity_id,
            vol.Required("devices"): cv.entity_ids,
        }
    },
    extra=vol.ALLOW_EXTRA,
)

print(CONFIG_SCHEMA)


def setup(hass, config):
    """Sets up the effect control."""
    print(config)
    print(config[DOMAIN])
    print(config[DOMAIN].keys())
    devices = config[DOMAIN]["devices"]
    hass.data[STOPPED_DEVICES] = {}
    last_update = dt_util.now() - timedelta(hours=1)
    store = None

    async def _async_initialize(_=None):
        """Get the cache data."""
        store = hass.helpers.storage.Store(1, DOMAIN)
        hass.data[STOPPED_DEVICES] = await store.async_load()

    @callback
    def _data_to_save():
        """Return data of entity map to store in a file."""
        return hass.data[STOPPED_DEVICES]

    async def _activate(_, _, new_state):

        now = dt_util.now()
        if now.minute < 10:
            return

        nonlocal last_update
        if (now - last_update) < timedelta(minutes=1):
            return

        est_total_cons = float(new_state.state)

        max_cons = hass.states.get(config[DOMAIN]["max_hourly_consumption"]).state
        _LOGGER.debug("%s %s %s", float(new_state.state), est_total_cons, max_cons)

        last_update = now

        if now.minute > 45:
            sec_left = 3600 - now.minute * 60 - now.second
            factor = 0.99 - sec_left / (15 * 60) * 0.09
        else:
            factor = 0.90

        # Restore
        if est_total_cons < factor * max_cons and hass.data[STOPPED_DEVICES]:
            for entity_id in devices:
                if entity_id not in hass.data[STOPPED_DEVICES]:
                    continue
                state = hass.data[STOPPED_DEVICES].pop(entity_id)

                _LOGGER.debug("Restore %s", entity_id)
                if "climate" in entity_id:
                    _data = {
                        "entity_id": entity_id,
                        "temperature": int(float(state.attributes.get("temperature"))),
                    }
                    await hass.services.async_call(
                        "climate", "set_temperature", _data, blocking=False
                    )

                elif "switch" in entity_id or "input_boolean" in entity_id:
                    _data = {"entity_id": entity_id}
                    service = (
                        SERVICE_TURN_ON if state.state == "on" else SERVICE_TURN_OFF
                    )
                    await hass.services.async_call(
                        "switch", service, _data, blocking=False
                    )

                store.async_delay_save(_data_to_save, 10)
                return

        if est_total_cons < max_cons:
            return

        # turn down
        for entity_id in devices:
            if entity_id in hass.data[STOPPED_DEVICES]:
                continue

            _LOGGER.debug("Turn down %s", entity_id)
            if "climate" in entity_id:
                _data = {"entity_id": entity_id, "temperature": 10}
                hass.data[STOPPED_DEVICES][entity_id] = hass.states.get(entity_id)
                await hass.services.async_call(
                    "climate", "set_temperature", _data, blocking=False
                )
                hass.data[STOPPED_DEVICES][entity_id] = hass.states.get(entity_id)

            elif "switch" in entity_id or "input_boolean" in entity_id:
                _data = {"entity_id": entity_id}
                hass.data[STOPPED_DEVICES][entity_id] = hass.states.get(entity_id)
                await hass.services.async_call(
                    "switch", SERVICE_TURN_OFF, _data, blocking=False
                )

            store.async_delay_save(_data_to_save, 10)
            return

    async_track_state_change(
        hass, config[DOMAIN]["estimated_hourly_consumtion_sensor"], _activate
    )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_initialize)

    return True
