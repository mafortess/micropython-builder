# main.py -- put your code here!
from machine import UART, Pin, I2C
# import notecard
from struct import pack, unpack

from time import sleep

def write_single_register(rs485, slave_addr, register_addr, register_value):
    """
    Writes a single register to the given slave address.
    Parameters
    ----------
    rs485 : ModbusRTUMaster
        Instance of the Modbus master interface used to communicate 
        over the RS-485 bus.
    
    slave_addr : int
        Modbus address of the slave device (1–247). 
        Each sensor (C4E, NTU, O2, Keller…) has its own slave address.
    
    register_addr : int
        Address of the holding register to write. 
        For Aqualabo sensors, register 1 is typically the measurement-order 
        bitfield (MT, M1, M2, M3, M4).
    
    register_value : int
        Value to write to the register. For example:
        - 1   → request only temperature
        - 3   → temperature + parameter 1 
        - 15  → temperature + parameters 1,2,3 (Aqualabo universal)
        - Other values depending on device configuration.

    Returns
    -------
    response : bytes or list
        Raw response from the slave device. 
        If communication succeeds, the device echoes the register and value written.
        If communication fails, the driver raises an exception.
    """
    response = rs485.write_single_register(slave_addr=slave_addr, register_address=register_addr, register_value=register_value)
    return response

def read_holding_registers(rs485, slave_addr, starting_addr, register_qty, signed):
    """
    Reads holding registers from the given slave address.
    Parameters
    ----------
    rs485 : ModbusRTUMaster
        Instance of the Modbus master interface used for RS-485 communication.
    
    slave_addr : int
        Modbus slave address of the sensor to read from.
        Example: 30 (C4E), 40 (NTU), 50 (Oxygen), etc.
    
    starting_addr : int
        The first register address to read.
        For Aqualabo sensors:
            83 → Temperature (float, 2 registers)
            85 → Parameter 1 (float)
            87 → Parameter 2 (float)
            89 → Parameter 3 (float)
            91 → Parameter 4 (float)
    
    register_qty : int
        Number of consecutive registers to read.
        Aqualabo parameters are float32, so always use 2 registers.
    
    signed : bool
        Whether the returned 16-bit words should be interpreted as signed integers.
        For Aqualabo float32 values, typically set to False.

    Returns
    -------
    response : list[int]
        Raw 16-bit register values read from the device. 
        The list length equals `register_qty`.
        Example for a float32 → [register_high, register_low]

        These values must be converted using your function:
        modbus_registers_to_float(response)
    """
    response = rs485.read_holding_registers(slave_addr=slave_addr, starting_addr=starting_addr, register_qty=register_qty, signed=signed)
    return response

def modbus_registers_to_float(registers):
    """
    Convert two Modbus RTU registers to a float (IEEE 754).
    Parameters
    ----------
    registers : list[int]
        A list containing exactly two 16-bit Modbus registers.
        These two registers represent a single 32-bit float value.
        
        Convention used:
        - registers[0] = High Word (most significant 16 bits)
        - registers[1] = Low  Word (least significant 16 bits)
        
        This is the standard "Big-Endian register order" used by 
        Aqualabo, Keller, and most Modbus devices for float32 values.

        Example:
            registers = [0x4228, 0x0000]
            → represents a float (e.g., 42.0)

    Returns
    -------
    float
        The decoded IEEE-754 floating-point value represented by the 
        two input registers.

    Raises
    ------
    ValueError
        If `registers` does not contain exactly two elements.
    
    Notes
    -----
    Modbus registers are 16 bits. A 32-bit float is split across two registers.
    
    This function reconstructs the original 32-bit value by:
        1. Shifting the high register 16 bits to the left
        2. OR-ing the low register
        3. Packing the 32-bit integer in Big-Endian format
        4. Unpacking it as a Big-Endian IEEE-754 float

    Binary reconstruction:
        raw_value = (reg_high << 16) | reg_low

    Endianness:
        - Big-Endian word order:   [HighWord][LowWord]
        - Byte order inside words is preserved

    This matches the memory format expected by most sensors that 
    return float values over Modbus RTU.
    """
    if len(registers) != 2:
        raise ValueError("Expected 2 registers")    
    raw_value = (registers[0] << 16) | registers[1]
    return unpack(">f", pack(">I", raw_value))[0]