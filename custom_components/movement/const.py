"""Constants for the Movement integration."""

import datetime as dt
from typing import Final

DOMAIN: Final = "movement"

ATTR_DISTANCE: Final = "distance_traveled"
ATTR_DISTANCE_ADJUSTMENTS: Final = "distance_adjustments"
ATTR_DISTANCE_WALKING: Final = "distance_walking"
ATTR_DISTANCE_BIKING: Final = "distance_biking"
ATTR_DISTANCE_DRIVING: Final = "distance_driving"
ATTR_SPEED: Final = "speed"
ATTR_MODE_OF_TRANSIT: Final = "mode_of_transit"
ATTR_GPS_ACCURACY: Final = "gps_accuracy"
ATTR_UPDATE_COUNT: Final = "distance_updates"

CONF_DEPENDENT_ENTITIES: Final = "dependent_entities"
CONF_TRACKED_ENTITY: Final = "tracked_entity"
CONF_TRIP_ADDITION: Final = "trip_addition"
CONF_MULTIPLIERS: Final = "multipliers"
CONF_NEIGHBORHOOD: Final = "neighborhood"
CONF_LOCAL: Final = "local"
CONF_HIGHWAY: Final = "highway"

UPDATES_STALLED_DELTA: Final = dt.timedelta(minutes=20)
HISTORY_EXPIRATION_DELTA: Final = dt.timedelta(hours=1)
SPEED_USABLE_DELTA: Final = dt.timedelta(seconds=45)
DEBOUNCE_UPDATES_DELTA: Final = dt.timedelta(seconds=5)

MAX_RESTORE_HISTORY: Final = 25
MAX_RESTORE_TRANSITION: Final = 25
