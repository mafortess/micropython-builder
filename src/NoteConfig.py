import sys
from machine import I2C
from time import sleep
from notecard import OpenI2C


def NotecardExceptionInfo(exception):
    """Construct a formatted Exception string.
    Args:
        exception (Exception): An exception object.
    Returns:
        string: a summary of the exception with line number and details.
    """
    s1 = "{}".format(sys.exc_info()[-1].tb_lineno)
    s2 = exception.__class__.__name__
    return "line " + s1 + ": " + s2 + ": " + " ".join(map(str, exception.args))

def sync_notecard(notecard: OpenI2C):
    """Sync the Notecard.
    Args:
        notecard (object): A Notecard object.
    """
    try:
        req = {"req": "hub.sync"}
        notecard.Transaction(req)
    except Exception as exception:
        print("Error syncing Notecard: " + NotecardExceptionInfo(exception))
        sleep(5)


def create_notecard_I2C(port: I2C, product_uid: str) -> OpenI2C:
    """Create a Notecard object using I2C.
    Args:
        port (object): A port object.
        product_uid (string): The product UID.
    Returns:
        card: A Notecard object.
    """
    print("Opening Notecard...")
    try:
        card = OpenI2C(port, 0, 0, debug=True)
    except Exception as exception:
        raise Exception("error opening notecard: " + NotecardExceptionInfo(exception))

    req = {"req": "hub.set", "product": product_uid, "mode": "minimum"}

    try:
        card.Transaction(req)
    except Exception as exception:
        print("Transaction error: " + NotecardExceptionInfo(exception))
        sleep(5)

    return card


def send_sensor_data(notecard: OpenI2C, data: dict):
    """Send sensor data to Notecard.
    Args:
        notecard (object): A Notecard object.
        data (dict): A dictionary of sensor data.
    """
    req = {
        "req": "note.add",
        "sync": True,
        "file": "data.qo",
        "body": data,
    }
    try:
        notecard.Transaction(req)
    except Exception as exception:
        print("Transaction error: " + NotecardExceptionInfo(exception))
        sleep(5)