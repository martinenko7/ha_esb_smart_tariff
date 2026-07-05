"""Support for ESB Smart Meter historical time-of-use sensors."""

import asyncio
import itertools
import logging
import statistics
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
)
from homeassistant.components.recorder.models import (
    StatisticData, 
    StatisticMetaData, 
    StatisticMeanType
)

from .const import DOMAIN, MANUFACTURER, MODEL, TARIFF_DAY, TARIFF_NIGHT, TARIFF_PEAK
from .coordinator import ESBDataUpdateCoordinator
from .models import ESBData

_LOGGER = logging.getLogger(__name__)

TARIFFS = [
    (TARIFF_DAY, "Day"),
    (TARIFF_NIGHT, "Night"),
    (TARIFF_PEAK, "Peak"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ESB Smart Meter historical sensors based on a config entry."""
    coordinator: ESBDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    mprn = coordinator.mprn

    # Spawn only the 3 Time-of-Use statistical sensors
    sensors = []
    for tariff_key, tariff_label in TARIFFS:
        sensors.append(
            ESBHistoricalTariffSensor(
                coordinator=coordinator,
                mprn=mprn,
                tariff_key=tariff_key,
                tariff_label=tariff_label,
            )
        )

    async_add_entities(sensors)


class ESBHistoricalTariffSensor(PollUpdateMixin, HistoricalSensor, CoordinatorEntity[ESBDataUpdateCoordinator], SensorEntity):
    """Historical sensor for backfilling tariff-specific electricity usage."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = None  # HistoricalSensor controls statistical metadata natively
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        *,
        coordinator: ESBDataUpdateCoordinator,
        mprn: str,
        tariff_key: str,
        tariff_label: str,
    ) -> None:
        """Initialize the historical sensor."""
        CoordinatorEntity.__init__(self, coordinator)
        HistoricalSensor.__init__(self)
        
        self._mprn = mprn
        self._tariff_key = tariff_key
        self._attr_name = f"ESB Electricity Usage: Cumulative {tariff_label}"
        self._attr_unique_id = f"{mprn}_cumulative_{tariff_key}"
        self._attr_native_value = 0.0

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._mprn)},
            name=f"ESB Smart Meter ({self._mprn})",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        """Handle coordination hooks when added to HA."""
        await super().async_added_to_hass()

    async def async_update_historical(self):
        """Re-map coordinator dataset into historical state intervals."""
        if self.coordinator.data is None:
            return

        hist_states = []
        # Filter raw arrays matching this sensor's specific tariff bucket
        for timestamp, value, tariff_type in self.coordinator.data.intervals:
            if tariff_type == self._tariff_key:
                # Force UTC context safety for database persistence boundaries
                dt_utc = timestamp.replace(tzinfo=timezone.utc)
                hist_states.append(HistoricalState(state=value, dt=dt_utc))

        # Chronological sort required by the long-term statistics compiler
        hist_states.sort(key=lambda x: x.dt)
        
        if hist_states:
            self._attr_historical_states = hist_states
            # Cumulative native value maps to the last historical element computed
            self._attr_native_value = sum(x.state for x in hist_states)
        else:
            self._attr_native_value = 0.0

        self.async_write_ha_state()

    @property
    def statistic_id(self) -> str:
        """Set statistics entity tracker ID."""
        return self.entity_id

    def get_statistic_metadata(self) -> StatisticMetaData:
        """Define long-term database tracking requirements."""
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["mean_type"] = StatisticMeanType.ARITHMETIC
        meta["unit_class"] = "energy"
        return meta

    async def async_calculate_statistic_data(
        self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        """Aggregate 30-minute intervals into explicit 1-hour statistics blocks."""
        accumulated = latest["sum"] if latest else 0.0

        def hourly_group_key(state: HistoricalState) -> datetime:
            """Group half-hourly CSV entries into flat 1-hour boundaries."""
            if state.dt.minute == 0 and state.dt.second == 0:
                dt = state.dt - timedelta(hours=1)
                return dt.replace(minute=0, second=0, microsecond=0)
            return state.dt.replace(minute=0, second=0, microsecond=0)

        calculated_records = []
        for hourly_boundary, collection_iter in itertools.groupby(hist_states, key=hourly_group_key):
            intervals_list = list(collection_iter)
            
            mean_value = statistics.mean([x.state for x in intervals_list])
            sum_value = sum([x.state for x in intervals_list])
            accumulated += sum_value
            
            calculated_records.append(
                StatisticData(
                    start=hourly_boundary,
                    state=sum_value,
                    mean=mean_value,
                    sum=accumulated
                )
            )
            
        return calculated_records
