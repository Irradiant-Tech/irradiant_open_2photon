"""
Voltage Test Script

This script provides a simple GUI for testing constant DC voltage output on
connected hardware channels (x_galvo, y_galvo, aom, z_piezo) using the
existing Irradiant-2photon DAQ control modules.

It is intended for hardware testing and validation outside the main
Irradiant-2photon application.

To run:
    python tests/set_voltage_all_channels.py
"""

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import DoubleVar, Label, messagebox
from typing import Dict, List, Optional

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from config import AOM_VOLTAGE_RANGE, CHANNELS, THREADING_CONFIG, VOLTAGE_AMPLITUDES
from hardware.voltage_device.voltage_devices import AnalogDevice, get_voltage_device
from utils.stop_flag import StopFlag


class VoltageController:
    """Controller for multi-channel voltage output"""

    def __init__(self):
        self.voltage_thread: Optional[threading.Thread] = None
        self.stop_flag: Optional[StopFlag] = None
        self.voltage_device: Optional[AnalogDevice]
        self.voltage_device_str: Optional[str]

        self.voltage_device, self.voltage_device_str = get_voltage_device()

    def set_voltages(
        self,
        channel: str | List[str],
        voltage: float | List[float],
    ) -> bool:
        """
        Start constant voltage output on one or more channels.

        Args:
            - channel: Channel name or list of channel names
            - voltage: Voltage or list of voltages corresponding to channels
        """
        if not self.voltage_device:
            messagebox.showerror("Error", "No voltage device connected.")
            return False

        channel_names = [channel] if isinstance(channel, str) else list(channel)
        voltages = [voltage] if isinstance(voltage, (int, float)) else list(voltage)

        if len(channel_names) != len(voltages):
            messagebox.showerror(
                "Invalid Input",
                "Channel and voltage must be the same length.",
            )
            return False

        if len(set(channel_names)) != len(channel_names):
            messagebox.showerror(
                "Invalid Input",
                "All channels must be unique.",
            )
            return False

        for ch in channel_names:
            if ch not in CHANNELS:
                messagebox.showerror(
                    "Invalid Channel",
                    f"Channel '{ch}' is not valid.",
                )
                return False

        # Stop any existing output
        self.stop_voltage_output()
        self.stop_flag = StopFlag()

        self.voltage_thread = threading.Thread(
            target=self.voltage_device.output_constant_voltage,
            kwargs={
                "channel": channel_names,
                "voltage": voltages,
                "stop_flag": self.stop_flag,
            },
            daemon=True,
        )
        self.voltage_thread.start()

        return True

    def stop_voltage_output(self):
        """Stop voltage output safely."""
        if self.stop_flag:
            self.stop_flag.stop = True

        if self.voltage_thread and self.voltage_thread.is_alive():
            self.voltage_thread.join(timeout=THREADING_CONFIG["wait_timeout"])
            if self.voltage_thread.is_alive():
                raise RuntimeError("Voltage thread did not stop in time.")


class MultiChannelVoltageGUI:
    """GUI for setting voltages on all Irradiant-2photon channels"""

    def __init__(self):
        self.controller = VoltageController()

        self.channel_vars: Dict[str, DoubleVar] = {}
        self.last_value_labels: Dict[str, Label] = {}

        self.setup_gui()

    def setup_gui(self):
        """Setup the GUI elements"""
        self.root = tk.Tk()
        self.root.title("Irradiant-2photon Multi-Channel Voltage Control")
        self.root.geometry("520x250")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        device_label = tk.Label(
            self.root,
            text=f"Voltage Output ({self.controller.voltage_device_str or 'No Device'})",
            font=("Arial", 12, "bold"),
        )
        device_label.pack(pady=(10, 8))

        body = tk.Frame(self.root)
        body.pack(padx=10)

        # Voltage input section
        for ch in CHANNELS.keys():
            amp = VOLTAGE_AMPLITUDES[ch]
            min_v = AOM_VOLTAGE_RANGE[0] if ch == "aom" else -amp
            max_v = amp

            row = tk.Frame(body)
            row.pack(fill="x", pady=4)

            # Label: Channel name [-amp -> +amp]:
            label_text = f"{ch} [{min_v} → {max_v}]:"
            tk.Label(row, text=label_text, width=15, anchor="w").pack(side=tk.LEFT)

            # User input
            var = DoubleVar(value=0.0)
            self.channel_vars[ch] = var
            entry = tk.Entry(row, textvariable=var, width=8, justify="center")
            entry.pack(side=tk.LEFT, padx=(4, 4))

            # Label: "Last set voltage: ___"
            tk.Label(row, text="| Last set voltage:", anchor="e").pack(
                side=tk.LEFT, padx=(4, 2)
            )
            last_lbl = tk.Label(row, text="N/A", width=8, anchor="w")
            last_lbl.pack(side=tk.LEFT)
            self.last_value_labels[ch] = last_lbl

        # Buttons
        btn_row = tk.Frame(self.root)
        btn_row.pack(pady=18)

        self.set_button = tk.Button(
            btn_row,
            text="SET ALL",
            command=self.set_voltages,
            bg="lightblue",
            width=16,
            height=2,
        )
        self.set_button.pack(side=tk.LEFT, padx=8)

        self.zero_button = tk.Button(
            btn_row,
            text="ZERO ALL",
            command=self.zero_all,
            width=16,
            height=2,
        )
        self.zero_button.pack(side=tk.LEFT, padx=8)

    def set_voltages(self):
        voltages_dict: Dict[str, float] = {}

        # Validate user input
        try:
            for ch, var in self.channel_vars.items():
                v = float(var.get())

                amp = VOLTAGE_AMPLITUDES[ch]
                min_v = AOM_VOLTAGE_RANGE[0] if ch == "aom" else -amp
                max_v = amp

                if not (min_v <= v <= max_v):
                    messagebox.showerror(
                        "Invalid Voltage",
                        f"{ch}: {v} V is outside [{min_v}, {max_v}]",
                    )
                    return

                voltages_dict[ch] = v
        except tk.TclError:
            messagebox.showerror(
                "Invalid Input", "Please enter valid numeric voltages."
            )
            return

        # Start output
        if self.controller.set_voltages(
            channel=list(voltages_dict.keys()), voltage=list(voltages_dict.values())
        ):
            # Update last set voltage values
            for ch, v in voltages_dict.items():
                self.last_value_labels[ch].config(text=f"{v:.3f} V")

    def zero_all(self):
        """Set all input voltages to 0.0 and apply them."""
        for var in self.channel_vars.values():
            var.set(0.0)

        # Apply zeros
        self.set_voltages()

    def stop_output(self):
        try:
            self.controller.stop_voltage_output()
        except Exception as e:
            messagebox.showerror("Stop Error", str(e))

    def on_close(self):
        try:
            print("Stopping voltage output...")
            self.controller.stop_voltage_output()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = MultiChannelVoltageGUI()
    app.run()


if __name__ == "__main__":
    main()
