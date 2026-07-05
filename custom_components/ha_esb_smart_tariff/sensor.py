"""Support for ESB Smart Meter historical time-of-use sensors."""

import asyncio
import itertools
import logging
import statistics
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant_historical_sensor import HistoricalSensor, HistoricalState
from homeassistant.components.recorder.models import (
    StatisticData, 
    StatisticMetaData, 
    StatisticMeanType
)

from .const import DOMAIN, MANUFACTURER, MODEL, TARIFF_DAY, TARIFF_NIGHT, TARIFF_PEAK
from .coordinator import ESBDataUpdateCoordinator

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


class ESBHistoricalTariffSensor(CoordinatorEntity[ESBDataUpdateCoordinator], HistoricalSensor, SensorEntity):
    """Historical sensor for backfilling tariff-specific electricity usage."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = None
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
        super().__init__(coordinator)
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

    @callback
    def _handle_coordinator_update(self) -> None:
        """Process data when the coordinator fetches a new CSV."""
        if self.coordinator.data is None:
            return

        hist_states = []
        for timestamp, value, tariff_type in self.coordinator.data.intervals:
            if tariff_type == self._tariff_key:
                dt_utc = timestamp.replace(tzinfo=timezone.utc)
                hist_states.append(HistoricalState(state=value, dt=dt_utc))

        hist_states.sort(key=lambda x: x.dt)
        
        if hist_states:
            self._attr_historical_states = hist_states
            self._attr_native_value = sum(x.state for x in hist_states)
        else:
            self._attr_native_value = 0.0

        # This triggers the state write to Home Assistant
        super()._handle_coordinator_update()

    @property
    def statistic_id(self) -> str:
        return self.entity_id

    def get_statistic_metadata(self) -> StatisticMetaData:
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["mean_type"] = StatisticMeanType.ARITHMETIC
        meta["unit_class"] = "energy"
        return meta

    async def async_calculate_statistic_data(
        self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        accumulated = latest["sum"] if latest else 0.0

        def hourly_group_key(state: HistoricalState) -> datetime:
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
