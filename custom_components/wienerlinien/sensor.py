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

from custom_components.wienerlinien.const import BASE_URL

CONF_STOPS = "stops"
CONF_APIKEY = "apikey"

SCAN_INTERVAL = timedelta(seconds=30)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_APIKEY): cv.string,
        vol.Optional(CONF_STOPS, default=None): vol.All(cv.ensure_list, [cv.string]),
    }
)


_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_devices_callback, discovery_info=None):
    """Setup."""
    stops = config.get(CONF_STOPS)
    dev = []
    for stopid in stops:
        api = WienerlinienAPI(async_create_clientsession(hass), hass.loop, stopid)
        data = await api.get_json()
        try:
            name = data["data"]["monitors"][0]["locationStop"]["properties"]["title"]
        except Exception:
            raise PlatformNotReady()
        dev.append(WienerlinienSensor(api, name))
    add_devices_callback(dev, True)


class WienerlinienSensor(Entity):
    """WienerlinienSensor."""

    def __init__(self, api, name):
        """Initialize."""
        self.api = api
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
        wheelchair = " \u267F"
        oldtram = " \U0001F68B"
        for theline in lines:
            # we need both the first and the second departure, because
            # the next two departures might be from different lines
            l = theline["lines"][0]
            barrierFree = l["barrierFree"]
            if barrierFree is True:
                suffix = wheelchair
            else:
                suffix = oldtram
            for i in [0, 1]:
                d = l["departures"]["departure"][i]
                t = self.get_time_from_departure(d)
                if "vehicle" in d:
                    if d["vehicle"]["barrierFree"] is True:
                        s = wheelchair
                    else:
                        s = oldtram
                else:
                    s = suffix
                if t is not None:
                    n = str(l["name"])+s
                    res.append({
                        "name": n,
                        "time": t,
                        "countdown": d["departureTime"]["countdown"],
                        "destination": l["towards"],
                        "platform": l["platform"],
                        "direction": l["direction"],
                    })
            # sort departures by countdown value
        res.sort(key=lambda x: x.get('countdown'))
        return res

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
            l = data["monitors"]
            d = self.sort_lines_and_departures(l)
            departure = d[0]
            next_departure = d[1]
            self._state = departure["time"]

            self.attributes = {
                "destination": departure["destination"],
                "platform": departure["platform"],
                "direction": departure["direction"],
                "name": departure["name"],
                "countdown": departure["countdown"],
                "next_time": next_departure["time"],
                "next_destination": next_departure["destination"],
                "next_platform": next_departure["platform"],
                "next_direction": next_departure["direction"],
                "next_name": next_departure["name"],
                "next_countdown": next_departure["countdown"],
            }
        except Exception:
            pass

    @property
    def name(self):
        """Return name."""
        return self._name

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
