"""Integration tests for sensor.py with coordinator pattern."""

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.esb_smart_meter.const import DOMAIN
from custom_components.esb_smart_meter.models import ESBData
from custom_components.esb_smart_meter.sensor import (
    ApiStatusSensor,
    CircuitBreakerStatusSensor,
    DataAgeSensor,
    LastUpdateSensor,
    TariffUsageSensor,
    async_setup_entry,
)
from tests.conftest import _async_create_task_handler


class TestAsyncSetupEntry:
    """Test async_setup_entry function with coordinator."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = ESBData(
            data=[
                {
                    "Read Date and End Time": "31-12-2024 00:30",
                    "Read Value": "1.5",
                    "Read Type": "Active Import",
                    "MPRN": "12345678901",
                }
            ]
        )
        coordinator.mprn = "12345678901"
        # Mock esb_api and circuit breaker to prevent RuntimeWarnings
        coordinator.esb_api = MagicMock()
        mock_circuit_breaker = MagicMock()
        mock_circuit_breaker._is_open = False
        mock_circuit_breaker._failure_count = 0
        mock_circuit_breaker._daily_attempts = 0
        mock_circuit_breaker._last_failure_time = None
        mock_circuit_breaker.can_attempt.return_value = True
        coordinator.esb_api._circuit_breaker = mock_circuit_breaker
        # Mock hass on esb_api to prevent async task creation
        coordinator.esb_api._hass = MagicMock()
        coordinator.esb_api._hass.async_create_task = MagicMock(side_effect=_async_create_task_handler)
        return coordinator

    @pytest.fixture
    def mock_hass(self, mock_coordinator):
        """Create mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {DOMAIN: {"test_entry_id": {"coordinator": mock_coordinator}}}
        # Mock async_create_task to properly close coroutines and prevent RuntimeWarnings
        hass.async_create_task = MagicMock(side_effect=_async_create_task_handler)
        return hass

    @pytest.fixture
    def mock_config_entry(self):
        """Create mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        return entry

    @pytest.mark.asyncio
    async def test_setup_entry_creates_all_sensors(self, mock_hass, mock_config_entry):
        """Test that setup_entry creates all tariff sensors and diagnostic sensors."""
        async_add_entities = MagicMock()

        await async_setup_entry(mock_hass, mock_config_entry, async_add_entities)

        # Verify 22 sensors were created (18 tariff sensors + 4 diagnostic sensors).
        assert async_add_entities.called
        sensors = async_add_entities.call_args[0][0]
        assert len(sensors) == 22

        # Verify tariff sensors and diagnostics
        assert isinstance(sensors[0], TariffUsageSensor)
        assert isinstance(sensors[17], TariffUsageSensor)
        assert isinstance(sensors[18], LastUpdateSensor)
        assert isinstance(sensors[19], ApiStatusSensor)
        assert isinstance(sensors[20], DataAgeSensor)
        assert isinstance(sensors[21], CircuitBreakerStatusSensor)


class TestBaseSensor:
    """Test BaseSensor class with coordinator."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = ESBData(
            data=[
                {
                    "Read Date and End Time": "31-12-2024 00:30",
                    "Read Value": "1.5",
                    "Read Type": "Active Import",
                    "MPRN": "12345678901",
                }
            ]
        )
        return coordinator

    def test_sensor_reads_from_coordinator(self, mock_coordinator):
        """Test sensor reads data from coordinator."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        value = sensor.native_value

        assert value == mock_coordinator.data.today_tariff["night"]

    def test_sensor_handles_no_data(self):
        """Test sensor handles when coordinator has no data."""
        coordinator = MagicMock(spec=DataUpdateCoordinator)
        coordinator.data = None

        sensor = TariffUsageSensor(
            coordinator=coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        value = sensor.native_value

        assert value is None

    def test_sensor_device_info(self, mock_coordinator):
        """Test sensor device info."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        device_info = sensor.device_info

        assert device_info["identifiers"] == {(DOMAIN, "12345678901")}
        assert "ESB Smart Meter" in device_info["name"]
        assert "12345678901" in device_info["name"]

    def test_sensor_unit_of_measurement(self, mock_coordinator):
        """Test sensor has correct unit of measurement."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        assert sensor._attr_native_unit_of_measurement == UnitOfEnergy.KILO_WATT_HOUR

    def test_sensor_icon(self, mock_coordinator):
        """Test sensor has correct icon."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        assert sensor._attr_icon == "mdi:flash"


class TestTariffUsageSensor:
    """Test tariff usage sensors."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        return MagicMock(spec=DataUpdateCoordinator)

    def test_unique_id(self, mock_coordinator):
        """Test tariff sensor unique ID."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        assert sensor._attr_unique_id == "12345678901_today_night"

    def test_get_data(self, mock_coordinator):
        """Test tariff sensor gets correct data from ESBData."""
        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        esb_data = MagicMock()
        esb_data.today_tariff = {"day": 0.0, "night": 1.5, "peak": 0.0}

        result = sensor._get_data(esb_data=esb_data)
        assert result == 1.5

    def test_native_value_uses_coordinator_data(self, mock_coordinator):
        """Test tariff sensor native_value returns coordinator data."""
        esb_data = ESBData(
            data=[
                {
                    "Read Date and End Time": "31-12-2024 00:30",
                    "Read Value": "1.5",
                }
            ]
        )
        mock_coordinator.data = esb_data

        sensor = TariffUsageSensor(
            coordinator=mock_coordinator,
            mprn="12345678901",
            period_key="today",
            period_label="Today",
            tariff_key="night",
            tariff_label="Night",
        )

        assert sensor.native_value == 1.5


class TestLastUpdateSensor:
    """Test LastUpdateSensor class."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        return MagicMock(spec=DataUpdateCoordinator)

    def test_unique_id(self, mock_coordinator):
        """Test Last Update sensor unique ID."""
        sensor = LastUpdateSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor._attr_unique_id == "12345678901_last_update"

    def test_native_value_none(self, mock_coordinator):
        """Test Last Update sensor returns None when last_successful_update_time is None."""
        mock_coordinator.last_successful_update_time = None
        sensor = LastUpdateSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value is None

    def test_native_value_datetime(self, mock_coordinator):
        """Test Last Update sensor returns a datetime when last_successful_update_time is set."""
        from datetime import datetime, timezone

        test_time = datetime(2024, 12, 31, 12, 30, 0, tzinfo=timezone.utc)
        mock_coordinator.last_successful_update_time = test_time
        sensor = LastUpdateSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value == test_time


class TestApiStatusSensor:
    """Test ApiStatusSensor class."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        return MagicMock(spec=DataUpdateCoordinator)

    def test_unique_id(self, mock_coordinator):
        """Test API Status sensor unique ID."""
        sensor = ApiStatusSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor._attr_unique_id == "12345678901_api_status"

    def test_native_value_unknown_when_none(self, mock_coordinator):
        """Test API Status sensor returns unknown when last_update_success is None."""
        mock_coordinator.last_update_success = None
        sensor = ApiStatusSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value == "unknown"

    def test_native_value_error_when_no_data(self, mock_coordinator):
        """Test API Status sensor returns error when coordinator has no data."""
        from datetime import datetime, timezone

        mock_coordinator.last_update_success = datetime.now(timezone.utc)
        mock_coordinator.data = None
        sensor = ApiStatusSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value == "error"

    def test_native_value_online_when_has_data(self, mock_coordinator):
        """Test API Status sensor returns online when coordinator has data."""
        from datetime import datetime, timezone

        mock_coordinator.last_update_success = datetime.now(timezone.utc)
        mock_coordinator.data = MagicMock()
        sensor = ApiStatusSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value == "online"


class TestDataAgeSensor:
    """Test DataAgeSensor class."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create mock coordinator."""
        return MagicMock(spec=DataUpdateCoordinator)

    def test_unique_id(self, mock_coordinator):
        """Test Data Age sensor unique ID."""
        sensor = DataAgeSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor._attr_unique_id == "12345678901_data_age"

    def test_native_value_none(self, mock_coordinator):
        """Test Data Age sensor returns None when last_successful_update_time is None."""
        mock_coordinator.last_successful_update_time = None
        sensor = DataAgeSensor(coordinator=mock_coordinator, mprn="12345678901")

        assert sensor.native_value is None

    def test_native_value_calculates_age(self, mock_coordinator):
        """Test Data Age sensor calculates age correctly."""
        from datetime import datetime, timedelta, timezone

        # Set last update to 2 hours ago
        test_time = datetime.now(timezone.utc) - timedelta(hours=2)
        mock_coordinator.last_successful_update_time = test_time
        sensor = DataAgeSensor(coordinator=mock_coordinator, mprn="12345678901")

        age = sensor.native_value
        assert age is not None
        # Should be approximately 2 hours
        assert 1.9 < age < 2.1

    def test_native_unit_of_measurement(self, mock_coordinator):
        """Test Data Age sensor has correct unit."""
        sensor = DataAgeSensor(coordinator=mock_coordinator, mprn="12345678901")

        from homeassistant.const import UnitOfTime

        assert sensor._attr_native_unit_of_measurement == UnitOfTime.HOURS
