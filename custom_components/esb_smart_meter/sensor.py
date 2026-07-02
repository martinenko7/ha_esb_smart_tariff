"""Support for ESB Smart Meter sensors."""

import logging
from abc import abstractmethod
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, TARIFF_DAY, TARIFF_NIGHT, TARIFF_PEAK
from .coordinator import ESBDataUpdateCoordinator
from .models import ESBData

_LOGGER = logging.getLogger(__name__)

PERIODS = [
    ("today", "Today"),
    ("last_24_hours", "Last 24 Hours"),
    ("this_week", "This Week"),
    ("last_7_days", "Last 7 Days"),
    ("this_month", "This Month"),
    ("last_30_days", "Last 30 Days"),
]

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
    """Set up the ESB Smart Meter sensor based on a config entry."""
    coordinator: ESBDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    mprn = coordinator.mprn

    sensors = []
    for period_key, period_label in PERIODS:
        for tariff_key, tariff_label in TARIFFS:
            sensors.append(
                TariffUsageSensor(
                    coordinator=coordinator,
                    mprn=mprn,
                    period_key=period_key,
                    period_label=period_label,
                    tariff_key=tariff_key,
                    tariff_label=tariff_label,
                )
            )

    sensors.extend([
        LastUpdateSensor(coordinator=coordinator, mprn=mprn),
        ApiStatusSensor(coordinator=coordinator, mprn=mprn),
        DataAgeSensor(coordinator=coordinator, mprn=mprn),
        CircuitBreakerStatusSensor(coordinator=coordinator, mprn=mprn),
    ])

    async_add_entities(sensors)


class BaseSensor(CoordinatorEntity[ESBDataUpdateCoordinator], SensorEntity):
    """Base sensor class for ESB Smart Meter sensors using coordinator."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    # Use TOTAL (not TOTAL_INCREASING) since values are recalculated from ESB CSV
    # which may have varying historical data availability
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        *,
        coordinator: ESBDataUpdateCoordinator,
        mprn: str,
        name: str,
        unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._mprn = mprn
        self._attr_name = name
        self._attr_unique_id = unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._mprn)},
            name=f"ESB Smart Meter ({self._mprn})",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @abstractmethod
    def _get_data(self, *, esb_data: ESBData) -> float:
        """Get the data for this sensor from coordinator data."""

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self._get_data(esb_data=self.coordinator.data)


class TariffUsageSensor(BaseSensor):
    """Sensor for tariff-specific electricity usage."""

    def __init__(
        self,
        *,
        coordinator: ESBDataUpdateCoordinator,
        mprn: str,
        period_key: str,
        period_label: str,
        tariff_key: str,
        tariff_label: str,
    ) -> None:
        """Initialize the tariff sensor."""
        name = f"ESB Electricity Usage: {period_label} {tariff_label}"
        unique_id = f"{mprn}_{period_key}_{tariff_key}"
        super().__init__(
            coordinator=coordinator,
            mprn=mprn,
            name=name,
            unique_id=unique_id,
        )
        self._period_key = period_key
        self._tariff_key = tariff_key

    def _get_data(self, *, esb_data: ESBData) -> float:
        """Get the requested tariff usage from coordinator data."""
        period_attr = f"{self._period_key}_tariff"
        period_data = getattr(esb_data, period_attr, None)
        if period_data is None:
            return 0.0
        return float(period_data.get(self._tariff_key, 0.0))


class LastUpdateSensor(SensorEntity):
    """Sensor for last update timestamp."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_state_class = None  # Timestamps don't use state class
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:clock-outline"

    def __init__(self, *, coordinator: ESBDataUpdateCoordinator, mprn: str) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._mprn = mprn
        self._attr_name = "ESB Smart Meter: Last Update"
        self._attr_unique_id = f"{mprn}_last_update"

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
        """When entity is added to hass."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return the timestamp of the last successful update as a datetime.

        Home Assistant expects a datetime object for sensors with
        device_class=timestamp so return the actual datetime rather than an
        ISO-formatted string.
        """
        if self.coordinator.last_successful_update_time is None:
            return None
        return self.coordinator.last_successful_update_time


class ApiStatusSensor(SensorEntity):
    """Sensor for API status."""

    _attr_device_class = None
    _attr_state_class = None
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:api"

    def __init__(self, *, coordinator: ESBDataUpdateCoordinator, mprn: str) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._mprn = mprn
        self._attr_name = "ESB Smart Meter: API Status"
        self._attr_unique_id = f"{mprn}_api_status"

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
        """When entity is added to hass."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the API status."""
        if self.coordinator.last_update_success is None:
            return "unknown"
        if self.coordinator.data is None:
            return "error"
        return "online"


class DataAgeSensor(SensorEntity):
    """Sensor for data age in hours."""

    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "h"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, *, coordinator: ESBDataUpdateCoordinator, mprn: str) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._mprn = mprn
        self._attr_name = "ESB Smart Meter: Data Age"
        self._attr_unique_id = f"{mprn}_data_age"

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
        """When entity is added to hass."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the age of the data in hours."""
        if self.coordinator.last_successful_update_time is None:
            return None

        age = datetime.now(timezone.utc) - self.coordinator.last_successful_update_time
        return round(age.total_seconds() / 3600, 1)  # Hours with 1 decimal place


class CircuitBreakerStatusSensor(SensorEntity):
    """Sensor showing circuit breaker state and health."""

    _attr_device_class = None
    _attr_state_class = None
    _attr_native_unit_of_measurement = None
    _attr_icon = "mdi:electric-switch"

    def __init__(self, *, coordinator: ESBDataUpdateCoordinator, mprn: str) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._mprn = mprn
        self._attr_name = "ESB Smart Meter: Circuit Breaker Status"
        self._attr_unique_id = f"{mprn}_circuit_breaker_status"

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
        """When entity is added to hass."""
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return circuit breaker state."""
        cb = self.coordinator.esb_api._circuit_breaker
        
        if not hasattr(cb, '_is_open'):
            return "unknown"
        
        now = datetime.now()
        
        # Check if circuit is open
        if cb._is_open and cb._last_failure_time:
            # Calculate backoff time
            from .const import CIRCUIT_BREAKER_TIMEOUT, CIRCUIT_BREAKER_MAX_TIMEOUT
            backoff_time = min(
                CIRCUIT_BREAKER_TIMEOUT * (2 ** (cb._failure_count - 1)),
                CIRCUIT_BREAKER_MAX_TIMEOUT,
            )
            elapsed = (now - cb._last_failure_time).total_seconds()
            
            if elapsed < backoff_time:
                return "open"
            return "half_open"
        
        return "closed"

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        cb = self.coordinator.esb_api._circuit_breaker
        
        if not hasattr(cb, '_failure_count'):
            return {}
        
        attrs = {
            "failure_count": cb._failure_count,
            "daily_attempts": cb._daily_attempts,
        }
        
        # Add constants for reference
        from .const import (
            CIRCUIT_BREAKER_FAILURES,
            CIRCUIT_BREAKER_MAX_TIMEOUT,
            MAX_AUTH_ATTEMPTS_PER_DAY,
        )
        attrs["failure_threshold"] = CIRCUIT_BREAKER_FAILURES
        attrs["daily_limit"] = MAX_AUTH_ATTEMPTS_PER_DAY
        
        # Add backoff information if circuit is open
        if cb._is_open and cb._last_failure_time:
            now = datetime.now()
            from .const import CIRCUIT_BREAKER_TIMEOUT
            backoff_time = min(
                CIRCUIT_BREAKER_TIMEOUT * (2 ** (cb._failure_count - 1)),
                CIRCUIT_BREAKER_MAX_TIMEOUT,
            )
            elapsed = (now - cb._last_failure_time).total_seconds()
            remaining = max(0, backoff_time - elapsed)
            
            attrs["backoff_seconds"] = int(backoff_time)
            attrs["time_remaining_seconds"] = int(remaining)
            attrs["time_remaining_minutes"] = round(remaining / 60, 1)
            
            if remaining > 0:
                blocked_until = cb._last_failure_time
                from datetime import timedelta
                blocked_until = blocked_until + timedelta(seconds=backoff_time)
                attrs["blocked_until"] = blocked_until.isoformat()
        
        if cb._last_failure_time:
            attrs["last_failure"] = cb._last_failure_time.isoformat()
        
        if cb._daily_attempts_reset_time:
            attrs["daily_counter_resets"] = cb._daily_attempts_reset_time.date().isoformat()
        
        return attrs

    @property
    def icon(self) -> str:
        """Return icon based on circuit breaker state."""
        state = self.native_value
        return {
            "closed": "mdi:check-circle",
            "open": "mdi:alert-circle",
            "half_open": "mdi:refresh-circle",
            "unknown": "mdi:help-circle",
        }.get(state, "mdi:help-circle")
