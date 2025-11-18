from machine import SPI, Pin
from sdcard import SDCard
import os
import time

def mount_sdcard(spi: SPI, cs: Pin):
    sd = SDCard(spi, cs)
    vfs = os.VfsFat(sd)
    os.mount(vfs, "/sd")
    return sd

def unmount_sdcard(sd: SDCard):
    os.umount("/sd")
    #sd.deinit() #  Warning: error unmounting SD card: 'SDCard' object has no attribute 'deinit'

def check_sdcard():
    try:
        os.stat("/sd")
        return True
    except OSError:
        return False

def get_timestamp():
    # Get the current local time as a tuple (year, month, day, hour, minute, second, weekday, yearday)
    local_time = time.localtime()
    
    # Format the timestamp as 'YYYY-MM-DD HH:MM:SS'
    timestamp = "{:04}-{:02}-{:02} {:02}:{:02}:{:02}".format(
        local_time[0], local_time[1], local_time[2], local_time[3], local_time[4], local_time[5]
    )
    
    return timestamp

# Datalogging function: Logs sensor data with timestamp
def log_sensor_data(data, columns):
    if check_sdcard():
        # Get the current timestamp (formatted as 'YYYY-MM-DD HH:MM:SS')
        timestamp = get_timestamp()
        
        # Prepare the data (timestamp, temperature, humidity)
        data_to_log = [timestamp] + data

        # Convert all values in data_to_log to strings
        data_to_log = [str(value) for value in data_to_log]

        # Open the CSV file in append mode ("a")
        with open("/sd/sensor_data.csv", "a") as file:

            # If the file is empty, write the header
            if file.tell() == 0:  # Check if file is empty
                file.write(",".join(["Timestamp"] + columns) + "\n")
            
            # Write the data
            file.write(",".join(data_to_log) + "\n")
        
        print(f"Logged data: {data_to_log}")
        return True
    else:
        print("SD card not mounted.")
        return False