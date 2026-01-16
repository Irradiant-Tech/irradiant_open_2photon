"""
Xeryon Library - Minimal implementation
Extracted from Xeryon Python library, only functions needed for controller wrapper.
"""

import math
import threading
import time
from enum import Enum

import serial
import serial.tools.list_ports

from config import XERYON_CONFIG

AMPLITUDE_MULTIPLIER = XERYON_CONFIG.get("amplitude_multiplier", 1456.0)
PHASE_MULTIPLIER = XERYON_CONFIG.get("phase_multiplier", 182)
DEFAULT_POLI_VALUE = XERYON_CONFIG.get("default_poli_value", 200)

OUTPUT_TO_CONSOLE = XERYON_CONFIG.get("output_to_console", False)
DISABLE_WAITING = XERYON_CONFIG.get("disable_waiting", False)
AUTO_SEND_SETTINGS = XERYON_CONFIG.get("auto_send_settings", True)
DEBUG_MODE = XERYON_CONFIG.get("debug_mode", True)
AUTO_SEND_ENBL = XERYON_CONFIG.get("auto_send_enbl", False)

# Commands that don't get stored as settings
NOT_SETTING_COMMANDS = [
    "DPOS",
    "EPOS",
    "HOME",
    "ZERO",
    "RSET",
    "INDX",
    "STEP",
    "MOVE",
    "STOP",
    "CONT",
    "SAVE",
    "STAT",
    "TIME",
    "SRNO",
    "SOFT",
    "XLA3",
    "XLA1",
    "XRT1",
    "XRT3",
    "XLS1",
    "XLS3",
    "SFRQ",
    "SYNC",
]


class Units(Enum):
    """Unit enumeration for stage operations."""

    mm = (0, "mm")
    mu = (1, "mu")
    nm = (2, "nm")
    inch = (3, "inches")
    minch = (4, "milli inches")
    enc = (5, "encoder units")
    rad = (6, "radians")
    mrad = (7, "mrad")
    deg = (8, "degrees")

    def __init__(self, ID, str_name):
        self.ID = ID
        self.str_name = str_name

    def __str__(self):
        return self.str_name


class Stage(Enum):
    """Stage type enumeration with encoder resolutions."""

    # X or Y axis
    XLS_3_120_5 = (
        True,  # isLinear
        XERYON_CONFIG.get("stages", {})
        .get("XLS_3_120_5", {})
        .get("encoder_resolution_command", "XLS3=5"),  # Encoder Resolution Command
        XERYON_CONFIG.get("stages", {})
        .get("XLS_3_120_5", {})
        .get("encoder_resolution", 5.0),  # Encoder Resolution in nanometer
        XERYON_CONFIG.get("stages", {})
        .get("XLS_3_120_5", {})
        .get("speed_multiplier", 1000),  # Speed multiplier
    )

    # Z axis
    XVP_80_5 = (
        True,  # isLinear
        XERYON_CONFIG.get("stages", {})
        .get("XVP_80_5", {})
        .get("encoder_resolution_command", "XLS1=5"),  # Encoder Resolution Command
        XERYON_CONFIG.get("stages", {})
        .get("XVP_80_5", {})
        .get("encoder_resolution", 5.0),  # Encoder Resolution in nanometer
        XERYON_CONFIG.get("stages", {})
        .get("XVP_80_5", {})
        .get("speed_multiplier", 1000),  # Speed multiplier
    )

    def __init__(
        self, isLineair, encoderResolutionCommand, encoderResolution, speedMultiplier
    ):
        self.isLineair = isLineair
        self.encoderResolutionCommand = encoderResolutionCommand
        self.encoderResolution = encoderResolution  # in nm
        self.speedMultiplier = speedMultiplier
        self.amplitudeMultiplier = AMPLITUDE_MULTIPLIER
        self.phaseMultiplier = PHASE_MULTIPLIER


def is_numeric(value):
    """Check if value is numeric."""
    try:
        int(value)
        return True
    except ValueError:
        return False


def outputConsole(message, error=False, force=True):
    """Output to console (disabled by default)."""
    if OUTPUT_TO_CONSOLE is True:
        if error is True:
            print("\033[91m" + "ERROR: " + message + "\033[0m")
        else:
            print(message)


def getDposEposString(DPOS, EPOS, Unit):
    """Get DPOS and EPOS string."""
    return str(
        "DPOS: "
        + str(DPOS)
        + " "
        + str(Unit)
        + " and EPOS: "
        + str(EPOS)
        + " "
        + str(Unit)
    )


class Communication:
    """Serial communication handler."""

    def __init__(self, xeryon_object, COM_port, baud):
        self.xeryon_object = xeryon_object
        self.COM_port = COM_port
        self.baud = baud
        self.readyToSend = []
        self.stop_thread = False
        self.thread = None
        self.ser = None

    def start(self, external_communication_thread=False):
        """Start serial communication."""
        if self.COM_port is None:
            self.xeryon_object.findCOMPort()
        if self.COM_port is None:
            raise Exception(
                "No COM_port could automatically be found. You should provide it manually."
            )

        try:
            serial_timeout = XERYON_CONFIG.get("serial_timeout", 0.01)
            self.ser = serial.Serial(self.COM_port, self.baud, timeout=serial_timeout)
            self.ser.flush()
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            if external_communication_thread is False:
                self.stop_thread = False
                self.thread = threading.Thread(target=self.__processData)
                self.thread.daemon = True
                self.thread.start()
            else:
                return self.__processData
        except Exception as e:
            outputConsole(
                "An error occurred while trying to connect to COM: "
                + str(self.COM_port),
                True,
                True,
            )
            outputConsole(str(e), True, True)
            raise Exception("Could not connect to COM " + str(self.COM_port))

    def sendCommand(self, command):
        """Add command to send queue."""
        self.readyToSend.append(command)

    def setCOMPort(self, com_port):
        """Set COM port."""
        self.COM_port = com_port

    def __processData(self, external_while_loop=False):
        """Process serial communication in background thread."""
        try:
            if self.ser is None:
                return
            while self.stop_thread is False and self.ser.is_open:
                # Send commands
                dataToSend = list(self.readyToSend[0:10])
                self.readyToSend = self.readyToSend[10:]

                for command in dataToSend:
                    self.ser.write(str.encode(command.rstrip("\n\r") + "\n"))

                # Read data
                max_to_read = 10
                try:
                    while self.ser.in_waiting > 0 and max_to_read > 0:
                        reading = self.ser.readline().decode()
                        if "=" in reading:
                            if len(reading.split(":")) == 2:  # Multi-axis format
                                axis = self.xeryon_object.getAxis(reading.split(":")[0])
                                reading = reading.split(":")[1]
                                if axis is None:
                                    axis = self.xeryon_object.axis_list[0]
                                axis.receiveData(reading)
                            else:
                                # Single axis system
                                axis = self.xeryon_object.axis_list[0]
                                axis.receiveData(reading)
                        max_to_read -= 1
                except Exception as e:
                    print(str(e))

                if external_while_loop is True:
                    return None
            # Close serial communication
            if self.ser is not None:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
                self.ser.close()
            print("Communication has stopped.")
        except Exception as e:
            print("An error has occurred that crashed the communication thread.")
            print(str(e))
            raise OSError(
                "An error has occurred that crashed the communication thread. \n"
                + str(e)
            )

    def closeCommunication(self):
        """Close communication."""
        self.stop_thread = True


class Axis:
    """Axis class for individual stage axis."""

    def __init__(self, xeryon_object, axis_letter, stage):
        self.axis_letter = axis_letter
        self.xeryon_object = xeryon_object
        self.stage = stage
        self.axis_data = dict({"EPOS": 0, "DPOS": 0, "STAT": 0, "SSPD": 0.0, "TIME": 0})
        self.settings = dict({})
        if self.stage.isLineair:
            self.units = Units.mm
        else:
            self.units = Units.deg
        self.update_nb = 0
        self.was_valid_DPOS = False
        self.def_poli_value = str(DEFAULT_POLI_VALUE)
        self.isLogging = False
        self.logs = {}
        self.previous_epos = [0, 0]
        self.previous_time = [0, 0]

    def findIndex(self, forceWaiting=False, direction=0):
        """Find index (homing) with travel limit safety checks."""
        self.__sendCommand("INDX=" + str(direction))
        self.was_valid_DPOS = False

        if DISABLE_WAITING is False or forceWaiting is True:
            self.__waitForUpdate()
            self.__waitForUpdate()
            self.__waitForUpdate()

            outputConsole("Searching index for axis " + str(self) + ".")

            # Get travel limits (stored in encoder units after conversion from mm in settings file)
            # EPOS from getData() is also in encoder units, so direct comparison is valid
            llim_str = self.getSetting("LLIM")
            hlim_str = self.getSetting("HLIM")
            llim = int(llim_str) if llim_str else None
            hlim = int(hlim_str) if hlim_str else None

            # If encoder is already valid, we can skip the search
            if self.isEncoderValid():
                return True

            iteration = 0
            max_iterations = 100  # 10 seconds max (100 * 0.2s)

            while not self.isEncoderValid():
                iteration += 1
                if iteration > max_iterations:
                    return False

                if not self.isSearchingIndex():
                    outputConsole(
                        "Index is not found, but stopped searching for index.", True
                    )
                    return False

                # Safety check: monitor position and limits
                current_pos = self.getData("EPOS")
                if current_pos is not None:
                    try:
                        pos = int(current_pos)
                        # Check software limits
                        if llim is not None and pos < llim:
                            outputConsole(
                                f"Travel limit reached: position {pos} < LLIM {llim}. Stopping homing.",
                                True,
                            )
                            self.__sendCommand("STOP=0")
                            return False
                        if hlim is not None and pos > hlim:
                            outputConsole(
                                f"Travel limit reached: position {pos} > HLIM {hlim}. Stopping homing.",
                                True,
                            )
                            self.__sendCommand("STOP=0")
                            return False

                        # Check hardware limit switches (additional safety)
                        if self.isAtLeftEnd() or self.isAtRightEnd():
                            outputConsole(
                                "Hardware limit switch triggered during homing. Stopping.",
                                True,
                            )
                            self.__sendCommand("STOP=0")
                            return False
                    except (ValueError, TypeError):
                        pass  # Skip if position can't be parsed

                time.sleep(0.2)

        if self.isEncoderValid():
            outputConsole("Index of axis " + str(self) + " found.")
            return True
        return False

    def setDPOS(
        self, value, differentUnits=None, outputToConsole=True, forceWaiting=False
    ):
        """Set desired position."""
        unit = self.units
        if differentUnits is not None:
            unit = differentUnits

        DPOS = int(self.convertUnitsToEncoder(value, unit))
        error = False

        self.__sendCommand("DPOS=" + str(DPOS))
        self.was_valid_DPOS = True

        # Wait until position is reached
        if DEBUG_MODE is False and DISABLE_WAITING is False or forceWaiting is True:
            max_iterations = 10000  # 100 seconds max
            iteration = 0
            while True:
                iteration += 1
                if iteration > max_iterations:
                    break

                # Check exit condition
                if self.__isWithinTol(DPOS) and self.isPositionReached():
                    break

                if self.isAtLeftEnd() or self.isAtRightEnd():
                    outputConsole(
                        "DPOS is out or range. (1) "
                        + getDposEposString(value, self.getEPOS(), unit),
                        True,
                    )
                    error = True
                    return False

                if self.isErrorLimit():
                    outputConsole("Position not reached. (5) ELIM Triggered.", True)
                    error = True
                    return False

                if self.isSafetyTimeoutTriggered():
                    outputConsole(
                        "Position not reached. (6) TOU2 (Timeout 2) triggered.", True
                    )
                    error = True
                    return False

                if self.isPositionFailTriggered():
                    outputConsole(
                        "Position not reached. (8) TOU3 (Timeout 3) triggered, 'position fail' status bit 21 went high. ",
                        True,
                    )
                    error = True
                    return False

                if self.isThermalProtection1() or self.isThermalProtection2():
                    outputConsole("Position not reached. (7) amplifier error.", True)
                    error = True
                    return False

                time.sleep(0.01)

        if outputToConsole and error is False and DISABLE_WAITING is False:
            outputConsole(getDposEposString(value, self.getEPOS(), unit))

        return not error

    def getDPOS(self):
        """Get desired position in current units."""
        return self.convertEncoderUnitsToUnits(self.getData("DPOS"), self.units)

    def getEPOS(self):
        """Get encoder position in current units."""
        return self.convertEncoderUnitsToUnits(self.getData("EPOS"), self.units)

    def setUnits(self, units):
        """Set units."""
        self.units = units

    def getData(self, TAG):
        """Get data value."""
        return self.axis_data.get(TAG)

    def sendCommand(self, command):
        """Send command."""
        tag = command.split("=")[0]
        value = str(command.split("=")[1])

        if tag in NOT_SETTING_COMMANDS:
            self.__sendCommand(command)
        else:
            self.setSetting(tag, value)

    def reset(self):
        """Reset axis."""
        self.sendCommand("RSET=0")
        self.was_valid_DPOS = False

    def setSetting(self, tag, value, fromSettingsFile=False, doNotSendThrough=False):
        """Set setting."""
        if fromSettingsFile:
            value = self.applySettingMultipliers(tag, value)
            if "MASS" in tag:
                tag = "CFRQ"
        if "?" not in str(value):
            self.settings.update({tag: value})
        if not doNotSendThrough:
            self.__sendCommand(str(tag) + "=" + str(value))

    def getSetting(self, tag):
        """Get setting value."""
        return self.settings.get(tag)

    def sendSettings(self):
        """Send all settings to controller."""
        self.__sendCommand(str(self.stage.encoderResolutionCommand))
        for tag in self.settings:
            self.__sendCommand(str(tag) + "=" + str(self.getSetting(tag)))

    def applySettingMultipliers(self, tag, value):
        """Apply multipliers for settings."""
        if (
            "MAMP" in tag
            or "MIMP" in tag
            or "OFSA" in tag
            or "OFSB" in tag
            or "AMPL" in tag
            or "MAM2" in tag
        ):
            value = str(int(int(value) * self.stage.amplitudeMultiplier))
        elif "PHAC" in tag or "PHAS" in tag:
            value = str(int(int(value) * self.stage.phaseMultiplier))
        elif "SSPD" in tag or "MSPD" in tag or "ISPD" in tag:
            value = str(int(float(value) * self.stage.speedMultiplier))
        elif "LLIM" in tag or "RLIM" in tag or "HLIM" in tag:
            if self.stage.isLineair:
                value = str(self.convertUnitsToEncoder(value, Units.mm))
            else:
                value = str(self.convertUnitsToEncoder(value, Units.deg))
        elif "POLI" in tag:
            self.def_poli_value = value
        elif "MASS" in tag:
            value = str(self.__massToCFREQ(value))
        elif "ZON1" in tag or "ZON2" in tag:
            if self.stage.isLineair:
                value = str(self.convertUnitsToEncoder(value, Units.mm))
            else:
                value = str(self.convertUnitsToEncoder(value, Units.deg))
        return str(value)

    def __massToCFREQ(self, mass):
        """Convert MASS to CFRQ."""
        mass = int(mass)
        if mass <= 50:
            return 100000
        if mass <= 100:
            return 60000
        if mass <= 250:
            return 30000
        if mass <= 500:
            return 10000
        if mass <= 1000:
            return 5000
        return 3000

    def convertUnitsToEncoder(self, value, units=None):
        """Convert units to encoder units."""
        if units is None:
            units = self.units
        value = float(value)
        if units == Units.mm:
            return round(value * 10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.mu:
            return round(value * 10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.nm:
            return round(value * 1 / self.stage.encoderResolution)
        elif units == Units.inch:
            return round(value * 25.4 * 10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.minch:
            return round(value * 25.4 * 10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.enc:
            return round(value)
        elif units == Units.mrad:
            return round(value * 10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.rad:
            return round(value * 10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.deg:
            return round(
                value * (2 * math.pi) / 360 * 10**6 / self.stage.encoderResolution
            )
        else:
            self.xeryon_object.stop()
            raise Exception("Unexpected unit")

    def convertEncoderUnitsToUnits(self, value, units=None):
        """Convert encoder units to units."""
        if units is None:
            units = self.units
        value = float(value)
        if units == Units.mm:
            return value / (10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.mu:
            return value / (10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.nm:
            return value / (1 / self.stage.encoderResolution)
        elif units == Units.inch:
            return value / (25.4 * 10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.minch:
            return value / (25.4 * 10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.enc:
            return value
        elif units == Units.mrad:
            return value / (10**3 * 1 / self.stage.encoderResolution)
        elif units == Units.rad:
            return value / (10**6 * 1 / self.stage.encoderResolution)
        elif units == Units.deg:
            return value / ((2 * math.pi) / 360 * 10**6 / self.stage.encoderResolution)
        else:
            self.xeryon_object.stop()
            raise Exception("Unexpected unit")

    def receiveData(self, data):
        """Process received data."""
        if "=" in data:
            tag = data.split("=")[0]
            val = data.split("=")[1].rstrip("\n\r").replace(" ", "")

            if is_numeric(val):
                if (
                    tag not in NOT_SETTING_COMMANDS
                    and "EPOS" not in tag
                    and "DPOS" not in tag
                ):
                    self.setSetting(tag, val, doNotSendThrough=True)
                else:
                    self.axis_data[tag] = val

                if "STAT" in tag:
                    if self.isSafetyTimeoutTriggered():
                        outputConsole(
                            "The safety timeout was triggered (TOU2 command). "
                            "This means that the stage kept moving and oscillating around the desired position. "
                            "A reset is required now OR 'ENBL=1' should be send.",
                            True,
                        )

                    if self.isPositionFailTriggered():
                        outputConsole(
                            "Safety timeout TOU3 went off, the 'position fail' status bit went high."
                        )

                    if (
                        self.isThermalProtection1()
                        or self.isThermalProtection2()
                        or self.isErrorLimit()
                        or self.isSafetyTimeoutTriggered()
                    ):
                        if self.isErrorLimit():
                            outputConsole(
                                "Error limit is reached (status bit 16). A reset is required now OR 'ENBL=1' should be send.",
                                True,
                            )

                        if self.isThermalProtection2() or self.isThermalProtection1():
                            outputConsole(
                                "Thermal protection 1 or 2 is raised (status bit 2 or 3). A reset is required now OR 'ENBL=1' should be send.",
                                True,
                            )

                        if self.isSafetyTimeoutTriggered():
                            outputConsole(
                                "Saftety timeout (TOU2 timeout reached) triggered. A reset is required now OR 'ENBL=1' should be send.",
                                True,
                            )

                        if AUTO_SEND_ENBL:
                            self.xeryon_object.setMasterSetting("ENBL", "1")
                            outputConsole("'ENBL=1' is automatically send.")

                if "EPOS" in tag:
                    self.previous_epos = [self.previous_epos[-1], int(val)]
                    self.update_nb += 1

                if self.isLogging:
                    if tag not in [
                        "SRNO",
                        "XLS ",
                        "XRTU",
                        "XLA ",
                        "XTRA",
                        "SOFT",
                        "SYNC",
                    ]:
                        if self.logs.get(tag) is None:
                            self.logs[tag] = []
                        self.logs[tag].append(int(val))

                if "TIME" in tag:
                    self.previous_time = [self.previous_time[-1], int(val)]
                    t1 = self.previous_time[0]
                    t2 = int(val)
                    if t2 < t1:
                        t2 += 2**16

                    if len(self.previous_epos) >= 2:
                        if t2 - t1 > 0:
                            self.axis_data["SSPD"] = (
                                self.previous_epos[1] - self.previous_epos[0]
                            ) / ((t2 - t1) * 10)

                            if self.isLogging:
                                if self.logs.get("SSPD") is None:
                                    self.logs["SSPD"] = []
                                self.logs["SSPD"].append(self.axis_data["SSPD"])

    def __sendCommand(self, command):
        """Send command to controller."""
        tag = command.split("=")[0]
        value = str(command.split("=")[1])

        prefix = ""
        if not self.xeryon_object.isSingleAxisSystem():
            prefix = self.axis_letter + ":"

        command = tag + "=" + str(value)
        self.xeryon_object.getCommunication().sendCommand(prefix + command)

    def __waitForUpdate(self):
        """Wait for update."""
        wait_nb = 3
        poli_setting = self.getSetting("POLI")
        if poli_setting is not None:
            try:
                wait_nb = wait_nb / int(self.def_poli_value) * int(poli_setting)
            except (ValueError, TypeError):
                pass

        start_nb = int(self.update_nb)
        while (int(self.update_nb) - start_nb) < wait_nb:
            time.sleep(0.01)

    def __isWithinTol(self, DPOS):
        """Check if within tolerance."""
        DPOS = abs(int(DPOS))
        pto2_setting = self.getSetting("PTO2")
        if pto2_setting is not None:
            try:
                PTO2 = int(pto2_setting)
            except (ValueError, TypeError):
                PTO2 = 10
        else:
            ptol_setting = self.getSetting("PTOL")
            if ptol_setting is not None:
                try:
                    PTO2 = int(ptol_setting)
                except (ValueError, TypeError):
                    PTO2 = 10
            else:
                PTO2 = 10
        epos_data = self.getData("EPOS")
        if epos_data is None:
            return False
        try:
            EPOS = abs(int(epos_data))
        except (ValueError, TypeError):
            return False

        if DPOS - PTO2 <= EPOS <= DPOS + PTO2:
            return True
        return False

    def __getStatBitAtIndex(self, bit_index, external_stat=None):
        """Get status bit at index."""
        stat = self.getData("STAT")
        if external_stat is not None:
            stat = external_stat

        if stat is not None:
            bits = bin(int(stat)).replace("0b", "")[::-1]
            if len(bits) >= bit_index + 1:
                return bits[bit_index]
        return "0"

    # Status bit checks
    def isThermalProtection1(self, external_stat=None):
        return self.__getStatBitAtIndex(2, external_stat) == "1"

    def isThermalProtection2(self, external_stat=None):
        return self.__getStatBitAtIndex(3, external_stat) == "1"

    def isPositionReached(self, external_stat=None):
        return self.__getStatBitAtIndex(10, external_stat) == "1"

    def isEncoderValid(self, external_stat=None):
        return self.__getStatBitAtIndex(8, external_stat) == "1"

    def isSearchingIndex(self, external_stat=None):
        return self.__getStatBitAtIndex(9, external_stat) == "1"

    def isAtLeftEnd(self, external_stat=None):
        return self.__getStatBitAtIndex(14, external_stat) == "1"

    def isAtRightEnd(self, external_stat=None):
        return self.__getStatBitAtIndex(15, external_stat) == "1"

    def isErrorLimit(self, external_stat=None):
        return self.__getStatBitAtIndex(16, external_stat) == "1"

    def isSafetyTimeoutTriggered(self, external_stat=None):
        return self.__getStatBitAtIndex(18, external_stat) == "1"

    def isPositionFailTriggered(self, external_stat=None):
        return self.__getStatBitAtIndex(21, external_stat) == "1"

    def getLetter(self):
        """Get axis letter."""
        return self.axis_letter

    def __str__(self):
        return str(self.axis_letter)


class Xeryon:
    """Main Xeryon controller class."""

    def __init__(self, COM_port=None, baudrate=None):
        if baudrate is None:
            baudrate = XERYON_CONFIG.get("baudrate", 115200)
        self.comm = Communication(self, COM_port, baudrate)
        self.axis_list = []
        self.axis_letter_list = []
        self.master_settings = {}

    def isSingleAxisSystem(self):
        """Check if single axis system."""
        return len(self.getAllAxis()) <= 1

    def start(
        self, external_communication_thread=False, external_settings_default=None
    ):
        """Start controller and send settings."""
        if len(self.getAllAxis()) <= 0:
            raise Exception("Cannot start the system without stages.")

        comm = self.getCommunication().start(external_communication_thread)

        for axis in self.getAllAxis():
            axis.reset()

        time.sleep(0.2)

        self.readSettings(external_settings_default)
        if AUTO_SEND_SETTINGS:
            self.sendMasterSettings()
            for axis in self.getAllAxis():
                axis.sendSettings()

        # Enable all axes
        for axis in self.getAllAxis():
            axis.sendCommand("ENBL=1")

        # Ask for limit values
        for axis in self.getAllAxis():
            axis.sendCommand("HLIM=?")
            axis.sendCommand("LLIM=?")
            axis.sendCommand("SSPD=?")
            axis.sendCommand("PTO2=?")
            axis.sendCommand("PTOL=?")
            if "XRTA" in str(axis.stage):
                axis.sendCommand("ENBL=3")

        if external_communication_thread:
            return comm

    def stop(self):
        """Stop controller."""
        for axis in self.getAllAxis():
            axis.sendCommand("ZERO=0")
            axis.sendCommand("STOP=0")
            axis.was_valid_DPOS = False
        self.getCommunication().closeCommunication()
        outputConsole("Program stopped running.")

    def getAllAxis(self):
        """Get all axes."""
        return self.axis_list

    def addAxis(self, stage, axis_letter):
        """Add axis."""
        newAxis = Axis(self, axis_letter, stage)
        self.axis_list.append(newAxis)
        self.axis_letter_list.append(axis_letter)
        return newAxis

    def getCommunication(self):
        """Get communication object."""
        return self.comm

    def getAxis(self, letter):
        """Get axis by letter."""
        if self.axis_letter_list.count(letter) == 1:
            indx = self.axis_letter_list.index(letter)
            if len(self.getAllAxis()) > indx:
                return self.getAllAxis()[indx]
        return None

    def readSettings(self, external_settings_default=None):
        """Read settings file."""
        try:
            if external_settings_default is None:
                settings_file = XERYON_CONFIG.get(
                    "settings_file", "hardware/stage/xeryon/settings_Xeryon.txt"
                )
                file = open(settings_file, "r")
            else:
                file = open(external_settings_default, "r")

            for line in file.readlines():
                if "=" in line and line.find("%") != 0:
                    line = line.strip("\n\r").replace(" ", "")
                    axis = self.getAllAxis()[0]  # Default
                    if ":" in line:
                        axis = self.getAxis(line.split(":")[0])
                        if axis is None:
                            continue
                        line = line.split(":")[1]
                    elif not self.isSingleAxisSystem():
                        if "%" in line:
                            line = line.split("%")[0]
                        self.setMasterSetting(
                            line.split("=")[0], line.split("=")[1], True
                        )
                        continue

                    if "%" in line:
                        line = line.split("%")[0]

                    tag = line.split("=")[0]
                    value = line.split("=")[1]

                    axis.setSetting(tag, value, True, doNotSendThrough=True)

            file.close()
        except FileNotFoundError as e:
            if external_settings_default is None:
                outputConsole("No settings file found.")
            else:
                raise e
        except Exception as e:
            raise e

    def setMasterSetting(self, tag, value, fromSettingsFile=False):
        """Set master setting."""
        self.master_settings.update({tag: value})
        if not fromSettingsFile:
            self.comm.sendCommand(str(tag) + "=" + str(value))
        if "COM" in tag:
            self.setCOMPort(str(value))

    def sendMasterSettings(self, axis=False):
        """Send master settings."""
        prefix = ""
        if axis is not False:
            prefix = str(self.getAllAxis()[0].getLetter()) + ":"

        for tag, value in self.master_settings.items():
            self.comm.sendCommand(str(prefix) + str(tag) + "=" + str(value))

    def setCOMPort(self, com_port):
        """Set COM port."""
        self.getCommunication().setCOMPort(com_port)

    def findCOMPort(self):
        """Find COM port automatically."""
        if OUTPUT_TO_CONSOLE:
            print("Automatically searching for COM-Port.")
        ports = list(serial.tools.list_ports.comports())
        hardware_id = XERYON_CONFIG.get("hardware_id", "04D8")
        for port in ports:
            if hardware_id in str(port.hwid):
                self.setCOMPort(str(port.device))
                break
