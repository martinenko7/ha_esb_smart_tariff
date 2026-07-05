"""Data models for ESB Smart Meter integration."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from .const import (
    CSV_COLUMN_DATE,
    CSV_COLUMN_VALUE,
    CSV_DATE_FORMAT,
    MAX_DATA_AGE_DAYS,
    TARIFF_DAY,
    TARIFF_NIGHT,
    TARIFF_PEAK,
)

_LOGGER = logging.getLogger(__name__)


class ESBData:
    """Class to manipulate data retrieved from ESB with memory optimization."""

    def __init__(self, *, data: List[Dict[str, Any]]) -> None:
        """Initialize with raw CSV data, filtering old data to prevent memory leaks."""
        if data:
            if not self._validate_csv_structure(data[0]):
                _LOGGER.error("CSV validation failed. First row keys: %s", list(data[0].keys()))
                raise ValueError(f"Invalid CSV structure. Expected columns: {CSV_COLUMN_DATE}, {CSV_COLUMN_VALUE}")

        cutoff_date = datetime.now() - timedelta(days=MAX_DATA_AGE_DAYS)
        self._data: List[Tuple[datetime, float, str]] = self._filter_and_parse_data(data, cutoff_date)
        _LOGGER.debug(
            "Loaded %d rows of historical intervals (filtered data older than %d days)",
            len(self._data),
            MAX_DATA_AGE_DAYS,
        )

    @staticmethod
    def _validate_csv_structure(row: dict[str, Any]) -> bool:
        """Validate that required CSV columns exist."""
        return CSV_COLUMN_DATE in row and CSV_COLUMN_VALUE in row

    def _filter_and_parse_data(self, data: list[dict[str, Any]], cutoff_date: datetime) -> list[tuple[datetime, float, str]]:
        """Filter old data and pre-parse directly into typed intervals with tariff sorting."""
        parsed_data = []
        for row in data:
            try:
                timestamp = datetime.strptime(row[CSV_COLUMN_DATE], CSV_DATE_FORMAT)
                if timestamp >= cutoff_date:
                    value = float(row[CSV_COLUMN_VALUE])
                    tariff_type = self._get_tariff_type(timestamp)
                    parsed_data.append((timestamp, value, tariff_type))
            except (ValueError, KeyError) as err:
                _LOGGER.warning("Skipping invalid row: %s", err)
                continue
        return parsed_data

    @staticmethod
    def _get_tariff_type(timestamp: datetime) -> str:
        """Return the tariff bucket for the given timestamp."""
        hour = timestamp.hour
        if 23 <= hour or hour < 8:
            return TARIFF_NIGHT
        if 17 <= hour < 19:
            return TARIFF_PEAK
        return TARIFF_DAY

    @property
    def intervals(self) -> List[Tuple[datetime, float, str]]:
        """Return the parsed list of chronological half-hourly intervals."""
        return self._data
