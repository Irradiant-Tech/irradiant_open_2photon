import os
import time
from typing import Any

# Suppress pygame initialization messages
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
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

        self.DEADZONE = JOYSTICK_CONFIG["deadzone"]
        self.BASE_POSITION_SCALE_XY = JOYSTICK_CONFIG["base_position_scale_xy"]
        self.BASE_POSITION_SCALE_Z = JOYSTICK_CONFIG["base_position_scale_z"]
        self.POSITION_SCALE_XY = self.BASE_POSITION_SCALE_XY
        self.POSITION_SCALE_Z = self.BASE_POSITION_SCALE_Z

        pygame.init()
        pygame.joystick.init()
        pygame.event.set_allowed(
            [pygame.QUIT, pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP]
        )

        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f"Joystick connected: {self.joystick.get_name()}")
        else:
            print("No joystick found")
            self.joystick = None

    def run(self) -> None:
        while self.running:
            if not self.running:
                break

            try:
                for event in pygame.event.get():
                    if event.type == pygame.JOYBUTTONDOWN:
                        if event.button == 0:
                            self.toggle_laser.emit()
                        elif event.button == 1:
                            self.run_pointscan.emit()
                        elif event.button == 5:
                            self.POSITION_SCALE_XY = (
                                self.BASE_POSITION_SCALE_XY
                                * JOYSTICK_CONFIG["fine_control_multiplier"]
                            )
                            self.POSITION_SCALE_Z = (
                                self.BASE_POSITION_SCALE_Z
                                * JOYSTICK_CONFIG["fine_control_multiplier"]
                            )
                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == 5:
                            self.POSITION_SCALE_XY = self.BASE_POSITION_SCALE_XY
                            self.POSITION_SCALE_Z = self.BASE_POSITION_SCALE_Z

                if self.movement_lock.tryLock():
                    try:
                        if self.joystick and self.running:
                            x_axis = round(self.joystick.get_axis(0), 2)
                            y_axis = round(self.joystick.get_axis(1), 2)
                            z_axis = round(self.joystick.get_axis(3), 2)

                            if abs(x_axis) > self.DEADZONE:
                                self.controllers[0].move(
                                    self.controllers[0].get_desired_position()
                                    + int(x_axis * self.POSITION_SCALE_XY)
                                )
                            if abs(y_axis) > self.DEADZONE:
                                self.controllers[1].move(
                                    self.controllers[1].get_desired_position()
                                    + int(y_axis * self.POSITION_SCALE_XY * -1)
                                )
                            if abs(z_axis) > self.DEADZONE:
                                self.controllers[2].move(
                                    self.controllers[2].get_desired_position()
                                    + int(z_axis * self.POSITION_SCALE_Z)
                                )
                                self.position_update.emit(self.controllers[2].position)
                    finally:
                        self.movement_lock.unlock()

            except Exception as e:
                if self.running:
                    print(f"Joystick error: {e}")
                break

            time.sleep(THREADING_CONFIG["joystick_poll_interval"])

        try:
            if pygame.get_init():
                pygame.quit()
        except:
            pass

    def stop(self) -> None:
        self.running = False
        self.wait()
