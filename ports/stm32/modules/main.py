# ============================================================
# IMPORTS
# ============================================================
# Common Stuff
# from multiprocessing.util import info
import time
import ujson as json
import machine
from machine import I2C, SPI, Pin, deepsleep

# Sensors Stuff
from umodbus.serial import Serial as ModbusRTUMaster
from src.SensorRead import write_single_register, read_holding_registers, modbus_registers_to_float

# Notecard Stuff
from src.NoteConfig import NotecardExceptionInfo, create_notecard_I2C, send_sensor_data, sync_notecard

# SD Card Stuff
from src.DatalogSD import mount_sdcard, unmount_sdcard, check_sdcard, log_sensor_data


# ============================================================
# GLOBAL CONSTANTS
# ============================================================
PRODUCT_UID = "es.uma.mafortes.it:isat2025"

# Deep sleep time in milliseconds
DEEP_SLEEP_TIME = 1000 * 10     # 60 * 60 * 1000  # 1 hour

# Sensor configuration structure (empty placeholders)
CSV_PATH   = "/sd/isat_data.csv"
JSONL_PATH = "/sd/isat_data.jsonl"

# Sensor configuration structure
SENSOR_PROFILES = {
    "C4E": {
    "slave_addr": 30,
    "start_register": 1,
    "start_value": 15,
    "warmup_ms": 400,
    "params": [
        {"name": "temperature",  "addr": 83, "qty": 2},
        {"name": "conductivity", "addr": 85, "qty": 2},
        {"name": "salinity",     "addr": 87, "qty": 2},
        {"name": "tds",          "addr": 89, "qty": 2},
    ]
    },
    "NTU": {
        "slave_addr": 40,
        "start_register": 1,
        "start_value": 15,
        "warmup_ms": 400,
        "params": [
            {"name": "temperature", "addr": 83, "qty": 2},
            {"name": "ntu",         "addr": 85, "qty": 2},
            {"name": "fnu",         "addr": 87, "qty": 2},
            {"name": "mgL",         "addr": 89, "qty": 2},
        ]
    },
    "O2": {
        "slave_addr": 50,
        "start_register": 1,
        "start_value": 15,
        "warmup_ms": 400,
        "params": [
            {"name": "temperature", "addr": 83, "qty": 2},
            {"name": "saturation",  "addr": 85, "qty": 2},
            {"name": "mgL",         "addr": 87, "qty": 2},
            {"name": "ppm",         "addr": 89, "qty": 2},
        ]
    },

    "SENSOR4_KELLER": {"slave_addr": None, "start_register": None, "start_value": None, "warmup_ms": 0, "params": []},
    "SENSOR5_KELLER": {"slave_addr": None, "start_register": None, "start_value": None, "warmup_ms": 0, "params": []},
}

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def iso8601_now():
    """Return current timestamp in ISO-8601 format."""
    t = time.localtime()
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        t[0], t[1], t[2], t[3], t[4], t[5]
    )

# ============================================================
def flatten_sensor_data(sensor_data):
    """Flatten nested sensor data dictionary."""
    flat = {}
    for sensor, params in sensor_data.items():
        for param, value in params.items():
            flat["{}_{}".format(sensor, param)] = value
    return flat

# ============================================================

# CSV
# timestamp,C4E_temperature,C4E_conductivity,NTU_turbidity,PH_value,O2_temp
# 2025-01-01T12:00:00Z,12.3,71.2,6.1,7.55,21.7

def ensure_csv_header(path, flat_dict):
    """Ensure the CSV file has a header row."""
    try:
        with open(path, "r") as f:
            header = f.readline().strip()
            if header.startswith("timestamp"):
                return
    except:
        pass

    keys = sorted(flat_dict.keys())
    with open(path, "w") as f:
        f.write("timestamp," + ",".join(keys) + "\n")


def append_csv_row(path, timestamp, flat_dict):
    keys = sorted(flat_dict.keys())
    values = [str(flat_dict[k]) for k in keys]

    with open(path, "a") as f:
        f.write(timestamp + "," + ",".join(values) + "\n")

# ============================================================

# JSON
# {
#   "timestamp": "2025-01-01T12:00:00Z",
#   "C4E_temperature": 12.3,
#   "C4E_conductivity": 71.2,
#   "NTU_turbidity": 6.1,
#   "PH_value": 7.55,
#   "O2_temp": 21.7
# }

# JSONL
# {"timestamp":"2025-01-01T12:00:00Z","C4E_temperature":12.3,"C4E_conductivity":71.2,"NTU_turbidity":6.1,"PH_value":7.55,"O2_temp":21.7}

def append_jsonl_record(path, timestamp, flat_dict):
    record = {"timestamp": timestamp}
    record.update(flat_dict)

    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")

# ============================================================
# SENSOR HANDLING
# ============================================================
def activate_all_sensors(modbus):
    """
    Activates all sensors by writing their start command.
    """
    if modbus is None:
        print("[SENSORS] No Modbus available, skipping activation.")
        return

    # This time will be used to wait after activating sensors
    max_warmup_ms = 0

    for sensor_id, profile in SENSOR_PROFILES.items():
        slave = profile.get("slave_addr")
        reg   = profile.get("start_register")
        value = profile.get("start_value")
        warmup_ms = profile.get("warmup_ms", 0)

        if warmup_ms > max_warmup_ms:
            max_warmup_ms = warmup_ms

        if slave is None or reg is None or value is None:
            print(f"[WARN] Sensor {sensor_id}: missing activation fields")
            continue

        try:
            write_single_register(modbus, slave, reg, value)

        except Exception as e:
            print("[SENSORS] Warning: start failed for {}: {}".format(sensor_id, e))

    if max_warmup_ms > 0:
        print("[SENSORS] Warmup wait: {} ms".format(max_warmup_ms))
        time.sleep(max_warmup_ms / 1000.0)


def read_sensor(modbus, sensor_id, profile):
    """
    Read all parameters for a single sensor.
    Returns a dict: { "param_name": value or None }
    """
    result = {}
    slave = profile.get("slave_addr")
    params = profile.get("params", [])

    if modbus is None or slave is None or not params:
        print(f"[ERROR] Sensor {sensor_id}: invalid profile or modbus not ready")
        return result

    print(f"[SENSOR] Reading {sensor_id} (slave {slave})")

    for param in params:
        name = param.get("name")
        addr = param.get("addr")
        qty  = param.get("qty", 2)

        if name is None or addr is None:
            print(f"[WARN] Sensor {sensor_id}: invalid param entry → {param}")
            result[name] = None
            continue

        try:
            # Read registers from Modbus
            raw = read_holding_registers(
                modbus,
                slave_addr=slave,
                starting_addr=addr,
                register_qty=qty,
                signed=False
            )

            # Convert Modbus register array to float
            value = modbus_registers_to_float(raw)
            result[name] = value

            print(f"   • {name} = {value}")

        except Exception as e:
            print(f"[ERROR] Sensor {sensor_id}: failed to read '{name}' → {e}")
            result[name] = None

    return result

def read_all_sensors(modbus):
    """
    Read all sensors defined in SENSOR_PROFILES.

    Returns:
        sensor_data = {
            "C4E": {
                "temperature": 12.3,
                "conductivity": 71.2
            },
            "NTU": {
                "turbidity": 6.1
            },
            "PH": {
                "value": 7.55
            },
            "O2": {
                "temp": 21.7
            }
        }
    """
    print("[SENSORS] Collecting data from all sensors...")

    data = {}

    if modbus is None:
        print("[ERROR] Modbus not initialized")
        return data

    for sensor_id, profile in SENSOR_PROFILES.items():
        try:
            values = read_sensor(modbus, sensor_id, profile)
            data[sensor_id] = values

        except Exception as e:
            print(f"[ERROR] Unexpected failure reading {sensor_id}: {e}")
            data[sensor_id] = {}

    return data

# ============================================================
# SD CARD HANDLING
# ============================================================
def setup_sd_card():
    """Mount the SD card and return the SD card object."""
    print("[SD] Mounting SD card (SPI)...")
    print("[SPI] Initializing SPI bus...")
    spi = SPI(1)
    cs = Pin("PA4", Pin.OUT)

    try:
        sd = mount_sdcard(spi, cs)
        print("[SD] SD card mounted successfully.")
        return sd
    except Exception as e:
        print("[SD] Warning: could not mount SD card:", e)
        return None

def shutdown_sd_card(sd):
    """Properly unmount the SD card before deep sleep."""
    print("[SD] Unmounting SD card...")
    if sd is None:
        print("[SD] Warning: SD card object is None, cannot unmount.")
        return
    try:
        unmount_sdcard(sd)
        print("[SD] SD card unmounted successfully.")
    except Exception as e:
        print("[SD] Warning: error unmounting SD card:", e)

def save_to_sd(sd, csv_path, jsonl_path, timestamp, flat_data):
    """
    Writes sensor data to the SD card in CSV and JSONL formats.
    Handles header creation, row append, and JSONL append.
    """
    if sd is None:
        print("[SD] Warning: SD card not mounted, cannot save data.")
        return False

    try:
        # Ensure header exists only once
        ensure_csv_header(csv_path, flat_data)

        # Save CSV row
        append_csv_row(csv_path, timestamp, flat_data)

        # Save JSONL record
        append_jsonl_record(jsonl_path, timestamp, flat_data)

        print("[SD] Data correctly written to SD card.")
        return True

    except Exception as e:
        print("[SD] ERROR writing to SD:", e)
        return False

# ============================================================
# MODBUS SENSOR HANDLING
# ============================================================
def setup_modbus():
    """Initialize Modbus RTU master over RS485 and return the master instance."""
    print("[MODBUS] Initializing Modbus RTU over RS485...")
    try:
        modbus = ModbusRTUMaster(uart_id=1)
        print("[MODBUS] Modbus RTU ready.")
        return modbus
    except Exception as e:
        print("[UART] Error initializing Modbus RTU:", e)
        return None

# ============================================================
# NOTECARD HANDLING
# ============================================================
def setup_notecard():
    """Initialize Notecard on I2C and return the card instance."""
    print("[I2C] Initializing I2C bus for Notecard...")
    try:
        port = I2C(1)
    except Exception as exception:
        raise Exception("Error opening I2C port: " +
                        NotecardExceptionInfo(exception))

    print("[I2C] Creating Notecard instance...")
    card = create_notecard_I2C(port, PRODUCT_UID)
    return card

def send_data_to_notecard(card, timestamp, flat_dict):
    """Send the JSON payload to Notehub."""
    payload = {
        "timestamp": timestamp,
        "data": flat_dict
    }
    try:
        send_sensor_data(card, payload)
    except Exception as e:
        print("[NOTECARD] Warning: error sending data:", e)

def sync_notecard_now(card):
    """Force Notehub synchronization."""
    try:
        sync_notecard(card)
    except Exception as e:
        print("[NOTECARD] Warning: error syncing:", e)

# ============================================================
# OTA UPDATE HANDLING (FULL IMPLEMENTATION)
# ============================================================

def check_ota_update(card):
    print("[OTA] Checking via hub.firmware...")

    # Tell Notecard we support OTA
    card.Transaction(
        {"req":"card.dfu",
        "name":"stm32",
        "on":True}
    )

    # Check if there is pending firmware
    rsp = card.Transaction({"req": "hub.firmware"})

    if not rsp.get("pending"):
        print("[OTA] No update available.")
        return False

    print("[OTA] Update detected:", rsp)

    # Request the update
    update = card.Transaction({"req": "hub.firmware.get"})

    code = update.get("body")
    if not code:
        print("[OTA] Update body missing.")
        return False

    print("[OTA] Writing new main.py...")

    with open("/main.py", "w") as f:
        f.write(code)

     # 5. Reboot MCU
    print("[OTA] Firmware installed.")
    print("[OTA] Rebooting...")

    time.sleep(2)
    machine.reset()  

    return True


def send_test_message(card):
    """Send a simple test note to Notehub."""
    body = {
        "type": "test",
        "msg":  "Hello from iSAT STM32!",
        "ts":   iso8601_now(),
    }

    print("[TEST] Sending test note to Notehub:", body)
    try:
        # Usa tu wrapper existente
        send_sensor_data(card, body)
    except Exception as e:
        print("[TEST] Error sending test note:", e)
        return False

    # Pequeña espera antes de sync
    time.sleep(2)
    try:
        sync_notecard_now(card)
    except Exception as e:
        print("[TEST] Error syncing after test note:", e)
        return False

    print("[TEST] Test note sent and sync requested.")
    return True


# ============================================================
# MAIN LOOP FUNCTION (DEFINED SEPARATELY)
# ===========================================================
def main():
    # -------------------------------------------------------
    #                           SETUP
    # -------------------------------------------------------

    # Print system start
    print("[BOOT] System starting...")


    # --------------------------------------------
    # 1 Notecard
    print("\n[SETUP] Setting up Notecard...")
    card = setup_notecard()
    
    print("\n[NOTECARD] Notecard version info:")
    info = card.Transaction({"req": "card.version"})
    
    # -------------------------------------------------------
    # OTA CHECK
    # -------------------------------------------------------
    print("\n[OTA] Checking for updates...")
    check_ota_update(card)

    # print("[TEST] Sending one test message to Notehub...")
    # send_test_message(card)

    # --------------------------------------------
    # 2. SD card
    print("\n[SETUP] Setting up SD card...")
    sd = setup_sd_card()

    # --------------------------------------------
    # 3. Modbus over RS485
    print("\n[SETUP] Setting up Modbus RTU over RS485...")
    modbus = setup_modbus()

    # -------------------------------------------------------
    #                   SENSORS
    # -------------------------------------------------------

    # 4. Activate and configure sensors
    print("\n[SENSORS] Activating sensors...")
    activate_all_sensors(modbus)

    # --------------------------------------------
    # 5. Read all sensors
    print("\n[SENSORS] Reading all sensors...")
    sensors_data = read_all_sensors(modbus)

    # 6. Get current timestamp
    print("\n[DATA] Getting current timestamp...")
    ts = iso8601_now()

    # 7. Flatten sensor data for easier processing
    print("\n[DATA] Flattening sensor data...")
    sensors_data_flat = flatten_sensor_data(sensors_data)

    # -------------------------------------------------------
    # FORMAT CSV / JSON AND SD CARD LOGGING
    # -------------------------------------------------------
    # 8. Save data to SD card
    print("\n[SD] Preparing CSV/JSONL structures and saving data to SD card...")
    save_to_sd(sd, CSV_PATH, JSONL_PATH, ts, sensors_data_flat)

    # -------------------------------------------------------
    # NOTECARD SEND
    # -------------------------------------------------------
    print("\n[NOTECARD] Sending data...")
    send_data_to_notecard(card, ts, sensors_data_flat)
    # send_sensor_data(card, {"C4E_temperature": C4E_temperature, "NTU_temperature": NTU_temperature})

    print("\n[NOTECARD] Waiting before sync...")
    time.sleep(2)

    print("\n[NOTECARD] Syncing...")
    sync_notecard_now(card)

    # -------------------------------------------------------
    # SHUTDOWN SD (optional before deep sleep)
    # -------------------------------------------------------
    if sd is not None:
        shutdown_sd_card(sd)

    # -------------------------------------------------------
    # DEEP SLEEP
    # -------------------------------------------------------
    print("\n[POWER] Entering deep sleep for {} ms...".format(DEEP_SLEEP_TIME))
    # NO PROBAR HASTA ENTRAR EN PRODUCCION
    # SE PIERDE EL ACCESO A LA PLACA HASTA REINICIO DEL FIRMWARE
    # deepsleep(DEEP_SLEEP_TIME)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    main()