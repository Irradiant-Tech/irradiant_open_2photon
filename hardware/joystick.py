import os
import time
from typing import Any

# Suppress pygame initialization messages
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
# Disable Raw Input so SDL handles the controller consistently through XInput
os.environ["SDL_JOYSTICK_RAWINPUT"] = "0"
import pygame
from PyQt5.QtCore import QMutex, QThread, pyqtSignal

from config import JOYSTICK_CONFIG, THREADING_CONFIG


class JoystickThread(QThread):
    position_update = pyqtSignal(int)
    toggle_laser = pyqtSignal()
    run_pointscan = pyqtSignal()

    def __init__(self, controllers: list[Any], movement_lock: QMutex) -> None:
        super().__init__()
        self.controllers = controllers
        self.running = True
        self.movement_lock = movement_lock
        self.joystick = None
        self.last_reconnect_attempt = 0.0
        self.error_logged = False

        self.DEADZONE = JOYSTICK_CONFIG["deadzone"]
        self.RECONNECT_INTERVAL = JOYSTICK_CONFIG["reconnect_interval"]
        self.BASE_POSITION_SCALE_XY = JOYSTICK_CONFIG["base_position_scale_xy"]
        self.BASE_POSITION_SCALE_Z = JOYSTICK_CONFIG["base_position_scale_z"]
        self.FINE_CONTROL_MULTIPLIER = JOYSTICK_CONFIG["fine_control_multiplier"]
        self.AXES = JOYSTICK_CONFIG["axes"]
        self.BUTTONS = JOYSTICK_CONFIG["buttons"]

        pygame.init()
        pygame.joystick.init()

        if pygame.joystick.get_count() > 0:
            self._open_joystick(0)
        else:
            print("No joystick found")

    def _open_joystick(self, device_index: int) -> None:
        self.joystick = pygame.joystick.Joystick(device_index)
        self.joystick.init()
        print(f"Joystick connected: {self.joystick.get_name()}")

    def _close_joystick(self) -> None:
        if self.joystick is None:
            return
        try:
            self.joystick.quit()
        except pygame.error:
            pass
        self.joystick = None

    def _try_reconnect(self) -> None:
        # Devices dropped by an error get no JOYDEVICEADDED event. Rate limited
        # so one that fails every open cannot retry each poll.
        now = time.monotonic()
        if now - self.last_reconnect_attempt < self.RECONNECT_INTERVAL:
            return
        self.last_reconnect_attempt = now

        if pygame.joystick.get_count() > 0:
            self._open_joystick(0)

    def run(self) -> None:
        while self.running:
            if not self.running:
                break

            try:
                if self.joystick is None:
                    self._try_reconnect()

                for event in pygame.event.get():
                    if event.type == pygame.JOYDEVICEADDED and self.joystick is None:
                        self._open_joystick(event.device_index)
                    elif event.type == pygame.JOYDEVICEREMOVED:
                        if (
                            self.joystick
                            and event.instance_id == self.joystick.get_instance_id()
                        ):
                            print("Joystick disconnected; waiting to reconnect")
                            self._close_joystick()
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if event.button == self.BUTTONS["laser"]:
                            self.toggle_laser.emit()
                        elif event.button == self.BUTTONS["pointscan"]:
                            self.run_pointscan.emit()

                if self.movement_lock.tryLock():
                    try:
                        if self.joystick and self.running:
                            x_axis = round(self.joystick.get_axis(self.AXES["x"]), 2)
                            y_axis = round(self.joystick.get_axis(self.AXES["y"]), 2)
                            z_axis = round(self.joystick.get_axis(self.AXES["z"]), 2)

                            # Held button 5 engages fine control.
                            multiplier = (
                                self.FINE_CONTROL_MULTIPLIER
                                if self.joystick.get_button(
                                    self.BUTTONS["fine_control"]
                                )
                                else 1
                            )
                            scale_xy = self.BASE_POSITION_SCALE_XY * multiplier
                            scale_z = self.BASE_POSITION_SCALE_Z * multiplier

                            if abs(x_axis) > self.DEADZONE:
                                self.controllers[0].move(
                                    self.controllers[0].get_desired_position()
                                    + int(x_axis * scale_xy)
                                )
                            if abs(y_axis) > self.DEADZONE:
                                self.controllers[1].move(
                                    self.controllers[1].get_desired_position()
                                    + int(y_axis * scale_xy * -1)
                                )
                            if abs(z_axis) > self.DEADZONE:
                                self.controllers[2].move(
                                    self.controllers[2].get_desired_position()
                                    + int(z_axis * scale_z)
                                )
                                self.position_update.emit(self.controllers[2].position)
                    finally:
                        self.movement_lock.unlock()

                self.error_logged = False

            # Device failures drop the joystick and wait for a reconnect. Stage
            # faults are usually transient: log once per episode and keep polling.
            except pygame.error as e:
                if self.running:
                    print(f"Joystick error, dropping device: {e}")
                self._close_joystick()
            except Exception as e:
                if self.running and not self.error_logged:
                    print(f"Joystick error, skipping cycle: {e}")
                    self.error_logged = True

            time.sleep(THREADING_CONFIG["joystick_poll_interval"])

        try:
            if pygame.get_init():
                pygame.quit()
        except:
            pass

    def stop(self) -> None:
        self.running = False
        self.wait(THREADING_CONFIG["wait_timeout"])
