"""
A integration that allows you to get information about next departure from specified stop.
For more details about this component, please refer to the documentation at
https://github.com/tofuSCHNITZEL/home-assistant-wienerlinien
"""
import logging
from datetime import timedelta

import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import Entity

from custom_components.wienerlinien_msd.const import BASE_URL, DEPARTURES

CONF_STOPS = "stops"
CONF_APIKEY = "apikey"
CONF_FIRST_NEXT = "firstnext"

SCAN_INTERVAL = timedelta(seconds=30)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_APIKEY): cv.string,
        vol.Optional(CONF_STOPS, default=None): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_FIRST_NEXT, default="first"): cv.string,
    }
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """Setup."""
    stops = config.get(CONF_STOPS)
    firstnext = config.get(CONF_FIRST_NEXT)
    dev = []
    for stopid in stops:
        api = WienerlinienAPI(async_create_clientsession(hass), hass.loop, stopid)
        data = await api.get_json()
        try:
            name = data["data"]["monitors"][0]["locationStop"]["properties"]["title"]
        except Exception:
            raise PlatformNotReady()
        dev.append(WienerlinienSensor(api, name, firstnext))
    add_devices_callback(dev, True)


class WienerlinienSensor(Entity):
    """WienerlinienSensor."""

    def __init__(self, api, name, firstnext):
        """Initialize."""
        self.api = api
        self.firstnext = firstnext
        self._name = name
        self._state = None
        self.attributes = {}

    def get_time_from_departure(self, departure):
        if "timeReal" in departure["departureTime"]:
            res = departure["departureTime"]["timeReal"]
        elif "timePlanned" in departure["departureTime"]:
            res = departure["departureTime"]["timePlanned"]
        else:
            res = None
        return res

    def sort_lines_and_departures(self, lines):
        """Return sorted list of lines and departures."""
        res = []
        for l in lines:
            # we need both the first and the second departure, because
            # the next two departures might be from different lines
            for i in [0, 1]:
                d = l["departures"]["departure"][i]
                t = self.get_time_from_departure(d)
                if t is not None:
                    res.append({
                        "name": l["name"],
                        "time": t,
                        "countdown": d["departureTime"]["countdown"],
                        "destination": l["towards"],
                        "platform": l["platform"],
                        "direction": l["direction"],
                    })
         # sort departures by countdown value
        d.sort(key=lambda x: x.get('countdown'))
        return d

    async def async_update(self):
        """Update data."""
        try:
            data = await self.api.get_json()
            _LOGGER.debug(data)
            if data is None:
                return
            data = data.get("data", {})
        except:
            _LOGGER.debug("Could not get new state")
            return

        if data is None:
            return
        try:
            # it cannot be assumed that the first line listed is also arriving sooner than the other,
            # we have to make a list of lines and times, order it and get the requested arrival time
            l = data["monitors"][0]["lines"]
            d = self.sort_lines_and_departures(l)
            departure = d[DEPARTURES[self.firstnext]["key"]]
            self._state = departure["time"]

            self.attributes = {
                "destination": departure["destination"],
                "platform": departure["platform"],
                "direction": departure["direction"],
                "name": departure["name"],
                "countdown": departure["countdown"],
            }
        except Exception:
            pass

    @property
    def name(self):
        """Return name."""
        return DEPARTURES[self.firstnext]["name"].format(self._name)

    @property
    def state(self):
        """Return state."""
        if self._state is None:
            return self._state
        else:
            return f"{self._state[:-2]}:{self._state[26:]}"

    @property
    def icon(self):
        """Return icon."""
        return "mdi:bus"

    @property
    def extra_state_attributes(self):
        """Return attributes."""
        return self.attributes

    @property
    def device_class(self):
        """Return device_class."""
        return "timestamp"


class WienerlinienAPI:
    """Call API."""

    def __init__(self, session, loop, stopid):
        """Initialize."""
        self.session = session
        self.loop = loop
        self.stopid = stopid

    async def get_json(self):
        """Get json from API endpoint."""
        value = None
        url = BASE_URL.format(self.stopid)
        try:
            async with async_timeout.timeout(10):
                response = await self.session.get(url)
                value = await response.json()
        except Exception:
            pass

        return value
