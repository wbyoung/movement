# Movement for Home Assistant

[![HACS](https://img.shields.io/badge/hacs-default-orange)][hacs-repo]
[![Version](https://img.shields.io/github/v/release/wbyoung/movement)][releases]
![Downloads](https://img.shields.io/github/downloads/wbyoung/movement/total)
![Build](https://img.shields.io/github/actions/workflow/status/wbyoung/movement/pytest.yml
)


This integration does its best to try to determine both how far and with what
mode of transit you are traveling throughout the day. It builds off of
[the device tracker integration][device-tracker] and assumes you carry a device
with you as you travel.

Because it is based on the frequency with which your device sends GPS
information back to Home Assistant, all of the gotchas that apply to location
updating from the [Companion Apps][companion-app-location-docs] will affect its
ability to provide accurate data.

_Said another way: do not expect this integration to provide you with perfection._

<img width="698" alt="Distance examples" src="https://github.com/user-attachments/assets/c430f122-2a23-424b-8f27-0b4b1ae565f8" />

There are a few more [example graphs below](#example-graphs).

## Installation

### HACS

Installation through [HACS][hacs] is the preferred installation method.

1. Go to the HACS dashboard.
1. Click the ellipsis menu (three dots) in the top right &rarr; choose _Custom repositories_.
1. Enter the URL of this GitHub repository,
   `https://github.com/wbyoung/movement`, in the _Repository_ field.
1. Select _Integration_ as the category.
1. Click _Add_.
1. Search for "Movement" &rarr; select it &rarr; press _DOWNLOAD_.
1. Select the version (it will auto select the latest) &rarr; press _DOWNLOAD_.
1. Restart Home Assistant then continue to [the setup section](#setup).

### Manual Download

1. Go to the [release page][releases] and download the `movement.zip` attached to the latest
   release.
1. Unpack the file and move the folder it contains called `movement` to the following
   directory of your Home Assistant configuration: `/config/custom_components/`.
1. Restart Home Assistant then continue to [the setup section](#setup).

## Setup

Open your Home Assistant instance and start setting up by following these steps:

1. Navigate to "Settings" &rarr; "Devices & Services"
1. Click "+ Add Integration"
1. Search for and select &rarr; "Movement"

Or you can use the My Home Assistant Button below.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)][config-flow-start]

Follow the instructions to configure the integration.

### Configuration Settings

1. Choose a person or a device to track from the main dropdown.
1. If desired, configure any of the additional options below.

* **Distance to add to the start of each driving trip**  
  Set in kilometers the distance you want added to the start of each driving
  trip. This  will add an adjustment to your total distance traveled each time
  the integration determines you're moving fast enough to be considered driving.
  The reason you may wish to do this is because some devices can take a little
  longer to "wake up" and start reporting data back to Home Assistant when in
  the car. This may change based on your phone type, use of GPS or mapping apps,
  whether or not you have _Android Auto_ or _Apple CarPlay_ that connect
  automatically, or if you charge your phone in the car.

* **Driving multipliers**  
  These settings allow you to scale up or down the distance traveled while
  driving. Driving is not in a straight line, so depending on the types of roads
  you frequent, you may find that these settings can help you tweak the
  integration to get closer to the actual distance you are driving.

* **Advanced options**  
  Advanced options will only appear when re-configuring the integration via the
  _CONFIGURE_ button. These are described in more detail in the
  [dedicated section below](#advanced-configuration-settings).


## Sensors

Each of the sensors that the integration provides are described in detail below.
All sensors are reset at the beginning of a new day.

### `sensor.<name>_distance_traveled`

This represents the total distance the person on device tracker has traveled.

_Note: if this sensor is disabled, state will not be restored for all sensors in the configuration when Home Assistant is restarted._

#### Attributes

* `adjustments` The adjustments that have been added to the distance traveled; mirrors the _[sensor value](#sensorname_distance_adjustments)*_.
* `speed` The speed that the person or device is moving; mirrors the _[sensor value](#sensorname_speed)*_.
* `mode_of_transit` The assumed mode of transit the person is using; mirrors the _[sensor value](#sensorname_mode_of_transit)*_.
* `ignore_count` The number of location changes that have been ignored. Changes are ignored when the GPS accuracy is poor and/or when updates arrive clustered together (a workaround for home-assistant/core#126972).
* `update_rate`: The rate at which distance changes are being calculated per minute.

_* These attributes mirror their respective sensors and are provided as part of the main distance traveled sensor for use by more complex automations. Some automations may require an understanding of the way the state is changing across all of the values simultaneously which cannot be obtained from individual sensors since state change triggers would be delivered to automations for each independently._


### `sensor.<name>_distance_adjustments`

The adjustments to the distance traveled that can be attributed to [the adjustments in the configuration settings](#configuration-settings).

### `sensor.<name>_distance_walking`

The distance that has been determined to be for walking.

_Note: The value calculated by this sensor takes into account the possibility that you may be in transition between two modes of transit. It will do its best to assign values to the distance sensor that is the most logical for the given situation. This means the value is not simply the sum of all distance changes from [`sensor.<name>_distance_traveled`](#sensorname_distance_traveled) while in this mode._

#### Attributes

* `trip_start`: The starting time of the current or last walking trip.
* `trip_distance`: The distance traveled for the current trip.
* `trip_adjustments`: The distance adjustments for the current trip.

### `sensor.<name>_distance_biking`

The distance that has been determined to be for biking.

_See notes in under the [walking sensor](#sensorname_distance_walking) about how this value is calculated._

#### Attributes

* `trip_start`: The starting time of the current or last biking trip.
* `trip_distance`: The distance traveled for the current trip.
* `trip_adjustments`: The distance adjustments for the current trip.

### `sensor.<name>_distance_driving`

The distance that has been determined to be for driving.

_See notes in under the [walking sensor](#sensorname_distance_walking) about how this value is calculated._

#### Attributes

* `trip_start`: The starting time of the current or last driving trip.
* `trip_distance`: The distance traveled for the current trip.
* `trip_adjustments`: The distance adjustments for the current trip.

### `sensor.<name>_speed`

The speed that the person or device is moving based on recent updates.

#### Attributes

* `speed_recent_avg`: The average speed at which you've been traveling recently.
* `speed_recent_max`: The maximum speed at which you've been traveling recently.

### `sensor.<name>_mode_of_transit`

The assumed mode of transit the person is using based on recent updates.

#### Attributes

* `transitioning`: Whether it has been determined that the person or device is
  likely transitioning from one mode of transit to another.

### `sensor.<name>_gps_accuracy`

The GPS accuracy person or device from the most recent update.

### `sensor.<name>_distance_updates`

The number of updates to distance that have been made for the person or device
throughout the day.

## Actions

### `movement.add_distance`

Add a certain distance manually.

This can be used, for instance if you travel on a certain schedule without a
device.

_Note: using this action will result in the [speed](#sensorname_speed) being cleared and may result in the mode of transit needing to be recalculated. It is best to use this action when you know that your device is not moving (much)._

#### Service Data Attributes

* `config_entry`: **required** Config entry to use. Example: `1b4a46c6cba0677bbfb5a8c53e8618b0`.
* `distance`: The distance to add in _kilometers_.
* `adjustments`: The adjustments to add in _kilometers_. This will increment both
  the [distance traveled](#sensorname_distance_traveled) and the
  [distance adjustments](#sensorname_distance_adjustments). So adding a distance
  of `1.2` with adjustments of `0.2` will result in the distance traveled being
* `mode_of_transit`: The mode of transit that should be switched to.


## Events

### `movement.template_entity_should_apply_update`

This event will be fired for
[custom distance tracking template sensors](#custom-distance-tracking-template-sensors).
See the documentation for more details on how to configure this advanced option.

#### Event Data

* `entity_id`: The entity id for which this change applies. This will match the
  [custom distance tracking template sensor](#custom-distance-tracking-template-sensors).
  Example: `sensor.toyota_prius_distance`.
* `config_entry_id`: The config entry id for which this change applies. This can
  be used to get more details in templates, i.e. getting the title via
  [`config_entry_attr(config_entry_id, 'title')`][template-config-entries] or
  even all related entities via
  [`integration_entities(title)`][template-integration-entities].
* `reason`: The reason for the change. Either `update` or `reset`.
* `from_state`: The prior state of the
  [`sensor.<name>_distance_traveled`](#sensorname_distance_traveled).
* `to_state`:  The new state of the
  [`sensor.<name>_distance_traveled`](#sensorname_distance_traveled).
* `updates`: The new state that should be applied to the template sensor. This
  can be applied or ignored based on logic that you choose. It includes both
  the new `state` and `attributes`. See the example for more details.


## Improving Location Reporting Frequency

There are a few things that may help with increasing the frequency with which
your device reports its location back to Home Assistant. Be sure to check out
the [companion app docs as well][companion-app-location-docs].

- Get into the habit of plugging in your phone in the car, connecting it to the
  infotainment system, and ensuring the map app is visible.
- Consider adding zones intersections you walk or drive through frequenly. This
  can be especially helpful if you are turning or if the road turns at a given
  location.
- Request [location updates via an automation](examples/request-location.yaml)
  while driving.

Various factors will affect whether or not these will work for you or not. Try
out different ideas and see what works best. Different devices manage battery
life differently. Most try to strike a good balance, and this is in conflict
with constantly obtaining and reporting GPS location.

_Your mileage will vary with each of these solutions._


## Advanced Configuration Settings

### Custom Distance Tracking Template Sensors

This can be used to build complex scenarios of distance tracking, for instance
combining several drivers for a single vehicle:

- [`examples/template-sensor.yaml` with multiple drivers](examples/template-sensor.yaml)

Using this setting, you can build custom sensors like the
[walking](#sensorname_distance_walking), [biking](#sensorname_distance_biking),
or [driving](#sensorname_distance_biking) sensors. but where you control when
the distance changes applies to the sensor.

This can be used to have multiple configurations update the same (template
entity) sensor which is what the
[multiple driver example](examples/template-sensor.yaml) does. For each driver
in this example, you would press the _CONFIGURE_ button, open the
_Advanced options_ section, and then select the shared template sensor.

For each [trigger template sensor][trigger-template-sensor-docs] entity that you
select, the integration will
[emit an event](#movementtemplate_entity_should_apply_update) that can be
consumed by a trigger, and you can change how it gets applied to the sensor as
you see fit. See the example YAML configuration linked above for more details.

## Example Graphs

<img width="644" alt="Speed example" src="https://github.com/user-attachments/assets/51f72a30-d60b-4d61-ba00-4e468388ac21" />  

<img width="644" alt="Update rate example" src="https://github.com/user-attachments/assets/d60bdfb0-7524-4175-8e13-5813d14d5065" />  

<img width="644" alt="GPS accuracy example" src="https://github.com/user-attachments/assets/71264a45-3043-45bf-ac2e-f7c2ede9a7f9" />  


[config-flow-start]: https://my.home-assistant.io/redirect/config_flow_start/?domain=movement
[hacs]: https://hacs.xyz/
[hacs-repo]: https://github.com/hacs/integration
[releases]: https://github.com/wbyoung/movement/releases
[device-tracker]: https://www.home-assistant.io/integrations/device_tracker/
[companion-app-location-docs]: https://companion.home-assistant.io/docs/core/location/
[trigger-template-sensor-docs]: https://www.home-assistant.io/integrations/template/#trigger-based-template-binary-sensors-images-lights-numbers-selects-sensors-switches-and-weathers
[template-config-entries]: https://www.home-assistant.io/docs/configuration/templating/#config-entries-examples
[template-integration-entities]: https://www.home-assistant.io/docs/configuration/templating/#integrations-examples
