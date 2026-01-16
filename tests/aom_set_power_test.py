"""
Standalone AOM Test Script

This script provides a simple interface to test AOM voltage control with intensity
values from 0 to +Amp on the AOM channel.

The channel and voltage limits used in this script are defined using values
imported from config.py:
- CHANNEL is set from DAQ_CHANNELS["aom"]
- MIN_VOLTAGE is fixed at 0.0 V
- MAX_VOLTAGE is set from VOLTAGE_AMPLITUDES["aom"]

To run:
    python -m tests.aom_set_power_test

Requirements:
    - NI-DAQmx installed
    - DAQ device connected
"""

import tkinter as tk
from tkinter import DoubleVar, Label, messagebox
from typing import Optional

import nidaqmx

from config import DAQ_CHANNELS, VOLTAGE_AMPLITUDES

# AOM channel definitions taken from config.py
CHANNEL = DAQ_CHANNELS["aom"]
MIN_VOLTAGE = 0.0
MAX_VOLTAGE = VOLTAGE_AMPLITUDES["aom"]


def set_aom_voltage(voltage: float) -> bool:
    """Set AOM voltage using simple single value output"""
    try:
        with nidaqmx.Task() as task:
            # Create AOM channel with specified voltage range
            task.ao_channels.add_ao_voltage_chan(
                CHANNEL, min_val=MIN_VOLTAGE, max_val=MAX_VOLTAGE
            )

            # Write single voltage value
            task.write([voltage], auto_start=True)  # type: ignore

            return True

    except Exception as e:
        print(f"Error setting AOM voltage: {str(e)}")
        return False


class AOMController:
    """Main controller for AOM voltage output"""

    def __init__(self):
        self.last_voltage_label: Optional[Label] = None

    def set_voltage(self, voltage):
        """Set voltage with proper error handling"""
        # Validate voltage range
        if not MIN_VOLTAGE <= voltage <= MAX_VOLTAGE:
            messagebox.showerror(
                "Invalid Voltage",
                f"Voltage must be between {MIN_VOLTAGE} and {MAX_VOLTAGE} V",
            )
            return False

        try:
            # Set the voltage
            success = set_aom_voltage(voltage)

            if success:
                print(f"Successfully set AOM voltage to {voltage}V on {CHANNEL}")
                return True
            else:
                messagebox.showerror("Error", "Failed to set voltage")
                return False

        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            print(error_msg)
            messagebox.showerror("Error", error_msg)
            return False

    def update_display(self, voltage):
        """Update the display label"""
        if self.last_voltage_label is not None:
            self.last_voltage_label.config(text=f"Last set voltage: {voltage:.3f} V")


class AOMGUI:
    """Clean GUI for AOM voltage control"""

    def __init__(self):
        self.controller = AOMController()
        self.setup_gui()

    def setup_gui(self):
        """Setup the GUI elements"""
        self.root = tk.Tk()
        self.root.title("Irradiant-2photon AOM Voltage Control")
        self.root.geometry("300x200")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Voltage input section
        voltage_label = tk.Label(
            self.root, text=f"Set AOM Voltage ({MIN_VOLTAGE} to {MAX_VOLTAGE} V):"
        )
        voltage_label.pack(pady=10)

        # Voltage entry with validation
        self.voltage_var = DoubleVar(value=0.0)
        self.voltage_entry = tk.Entry(
            self.root, textvariable=self.voltage_var, width=10, justify="center"
        )
        self.voltage_entry.pack(pady=5)

        # Set button
        self.set_button = tk.Button(
            self.root,
            text="SET",
            command=self.set_voltage,
            width=15,
            height=2,
            bg="lightblue",
        )
        self.set_button.pack(pady=15)

        # Status display
        self.last_voltage_label = tk.Label(
            self.root, text="Last set voltage: N/A", font=("Arial", 10)
        )
        self.last_voltage_label.pack(pady=10)

        # Bind enter key to set button
        self.voltage_entry.bind("<Return>", lambda event: self.set_voltage())

        # Store reference in controller for display updates
        self.controller.last_voltage_label = self.last_voltage_label

    def set_voltage(self):
        """Handle set voltage button click"""
        try:
            voltage = self.voltage_var.get()
            if self.controller.set_voltage(voltage):
                self.controller.update_display(voltage)
        except tk.TclError:
            messagebox.showerror(
                "Invalid Input",
                f"Please enter a valid number between {MIN_VOLTAGE} and {MAX_VOLTAGE}",
            )

    def run(self):
        """Start the GUI"""
        self.root.mainloop()

    def on_close(self):
        """Set AOM to 0V before closing"""
        try:
            print("Closing GUI: setting AOM voltage to 0.0 V")
            set_aom_voltage(0.0)
        except Exception as e:
            print(f"Failed to set AOM to 0V on close: {e}")
        finally:
            self.root.destroy()


def main():
    """Main entry point"""
    try:
        app = AOMGUI()
        app.run()
    except Exception as e:
        print(f"Failed to start application: {e}")
        messagebox.showerror("Startup Error", f"Failed to start application: {e}")


if __name__ == "__main__":
    main()
