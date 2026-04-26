# Battery Negative Price Setup

This add-on can now drive a battery `negative-price override` through Home Assistant entities.
The add-on itself writes helper entities only. Home Assistant then forwards those helper values to your inverter or Modbus registers.

## 1. Copy the Home Assistant package

Copy:

`docs/examples/battery_negative_price_package.yaml`

to your Home Assistant config as:

`/config/packages/battery_negative_price_package.yaml`

If you do not use packages yet, add this to your Home Assistant `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

## 2. Edit the Modbus bridge scripts

Inside `battery_negative_price_package.yaml`, replace the placeholders in these scripts:

- `scr_fronius_battery_push_discharge_limit_from_helper`
- `scr_fronius_battery_push_charge_allowed_from_helper`
- `scr_fronius_battery_push_charge_power_from_helper`
- `scr_fronius_battery_push_target_soc_from_helper`

Replace:

- `modbus_hub`
- `modbus_slave`
- `register_address`

with your real Fronius/Modbus values.

If `charge allowed` on your inverter is a coil instead of a holding register, change that script from `modbus.write_register` to `modbus.write_coil`.

## 3. Use these entities in the add-on Battery page

Recommended mapping:

- `Discharge limit entity` -> `input_number.battery_discharge_limit_watt`
- `Charge allowed entity` -> `input_boolean.battery_charge_allowed`
- `Charge power entity` -> `input_number.battery_charge_power_watt`
- `Target SoC entity` -> `input_number.battery_target_soc_pct`

Recommended negative-price values:

- `Discharge limit negative` -> `0`
- `Charge allowed` -> enabled by the add-on automatically
- `Charge power negative` -> your desired charge power in watts
- `Target SoC negative` -> `100`

Recommended normal values:

- `Discharge limit normal` -> your standard inverter value
- `Charge power normal` -> your standard inverter value
- `Target SoC normal` -> your standard target, e.g. `90`

For `Charge allowed`, the add-on will restore the previous helper state automatically.

## 4. Behavior

When effective grid price is `<= 0`, the add-on will:

- set discharge limit to the configured negative-price value
- enable charge allowed
- optionally raise charge power
- optionally set target SoC to 100%

When the price becomes `> 0`, or if the feature is disabled, the add-on restores normal values.

## 5. Safety notes

- Adjust helper min/max ranges to your inverter limits.
- Do not keep the example register addresses at `0`.
- Test each helper manually first from Home Assistant before enabling the add-on feature.
- Watch the Battery page `Control status` field to confirm `active`, `idle`, or failure states.
