import json
import os

import matplotlib

matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.ticker import MultipleLocator
from PyQt5.QtCore import QMutex, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from config import (
    DEFAULT_PRINT_FILE_PARAMS,
    DEFAULT_PRINT_PARAMS,
    GUI_CONFIG,
    PDXC2_CONFIG,
    STAGE_POSITION_LIMITS,
    STATE_FILE,
    THREADING_CONFIG,
    VOLTAGE_AMPLITUDES,
    XERYON_CONFIG,
)
from hardware.daq import is_daq_connected
from hardware.joystick import JoystickThread
from hardware.stage.dover_controller import DoverController, shutdown_motion_synergy_api
from hardware.stage.mock_controller import MockController
from hardware.stage.pdxc2_controller import PDXC2Controller
from hardware.stage.xeryon.xeryon_controller import XeryonController
from printing.job_thread import LaserThread, PointscanThread


class IntegratedGUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.movement_lock = QMutex()
        self.is_printing = False
        self.pointscan_thread = None
        self.laser_thread = None
        self.state_file = STATE_FILE
        self.initial_z_pos = 0
        self.daq_connected = is_daq_connected()
        print(
            f"Using DAQ for voltage output."
            if self.daq_connected
            else "No voltage device connected."
        )
        # Use real controllers if connected, otherwise MockController
        # Priority: Xeryon > PDXC2 > Dover > Mock (only need to try Dover during homing)
        xeryon_connected = XeryonController.is_connected("")

        z_serial_pdxc2 = PDXC2_CONFIG["device_serials"]["z_axis"]
        self.z_controller = (
            XeryonController(serial="", home=False, axis="Z")
            if xeryon_connected
            else (
                PDXC2Controller(serial=z_serial_pdxc2, home=False, axis="Z")
                if PDXC2Controller.is_connected(z_serial_pdxc2)
                else MockController(serial=z_serial_pdxc2, home=False, axis="Z")
            )
        )

        x_serial_pdxc2 = PDXC2_CONFIG["device_serials"]["x_axis"]
        self.x_controller = (
            XeryonController(serial="", home=False, axis="X")
            if xeryon_connected
            else (
                PDXC2Controller(serial=x_serial_pdxc2, home=False, axis="X")
                if PDXC2Controller.is_connected(x_serial_pdxc2)
                else MockController(serial=x_serial_pdxc2, home=False, axis="X")
            )
        )

        y_serial_pdxc2 = PDXC2_CONFIG["device_serials"]["y_axis"]
        self.y_controller = (
            XeryonController(serial="", home=False, axis="Y")
            if xeryon_connected
            else (
                PDXC2Controller(serial=y_serial_pdxc2, home=False, axis="Y")
                if PDXC2Controller.is_connected(y_serial_pdxc2)
                else MockController(serial=y_serial_pdxc2, home=False, axis="Y")
            )
        )

        # Find reference for all controllers explicitly (Z first, then X, Y for Xeryon compatibility)
        # If reference finding fails, try Dover for Z axis, then fallback to MockController
        for axis_name, controller_attr in [
            ("Z", "z_controller"),
            ("X", "x_controller"),
            ("Y", "y_controller"),
        ]:
            controller = getattr(self, controller_attr)

            try:
                controller.home()
            except (RuntimeError, Exception) as e:
                # Special handling for Z axis: try Dover as fallback
                if axis_name == "Z" and not isinstance(controller, DoverController):
                    print(
                        f"Z axis: Reference finding failed ({e}), trying Dover as fallback..."
                    )
                    if DoverController.is_connected(""):
                        try:
                            dover_z = DoverController(serial="", home=False, axis="Z")
                            dover_z.home()
                            setattr(self, controller_attr, dover_z)
                            print("Z axis: Successfully fell back to DoverController")
                            continue
                        except Exception as dover_error:
                            print(
                                f"Z axis: Dover homing also failed ({dover_error}), using MockController"
                            )
                    else:
                        print("Z axis: Dover not available, using MockController")

                # Default fallback to MockController
                print(
                    f"{axis_name} axis: Reference finding failed ({e}), replacing with MockController"
                )
                serial = PDXC2_CONFIG["device_serials"][f"{axis_name.lower()}_axis"]
                setattr(
                    self,
                    controller_attr,
                    MockController(serial=serial, home=False, axis=axis_name),
                )

        self.controllers = [self.x_controller, self.y_controller, self.z_controller]
        reference_pos = XERYON_CONFIG["reference_position"]
        self.home_x = reference_pos["X"]
        self.home_y = reference_pos["Y"]
        self.home_z = reference_pos["Z"]

        self.initUI()
        self.loadState()
        self.initJoystickThread()

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.updatePosition)
        self.update_timer.start(THREADING_CONFIG["position_update_interval"])

        self.position_save_timer = QTimer()
        self.position_save_timer.timeout.connect(self.saveState)
        self.position_save_timer.start(THREADING_CONFIG["state_save_interval"])

        self.setFocusPolicy(Qt.StrongFocus)
        self.centralWidget().setFocusPolicy(Qt.StrongFocus)

    def initUI(self) -> None:
        self.setWindowTitle(GUI_CONFIG["window_title"])
        self.setGeometry(*GUI_CONFIG["window_geometry"])
        self.setMinimumWidth(900)
        self.setWindowIcon(QIcon(GUI_CONFIG["window_icon"]))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        file_group = QGroupBox("Print File")
        file_group.setStyleSheet("QGroupBox::title { font-weight: bold; color: red; }")
        file_layout = QFormLayout()

        matrix_type_group = QButtonGroup(self)
        self.dense_radio = QRadioButton("Use Dense Matrix")
        self.npy_radio = QRadioButton("Use NPY")
        matrix_type_group.addButton(self.dense_radio)
        matrix_type_group.addButton(self.npy_radio)
        self.dense_radio.setChecked(True)
        matrix_type_group.buttonClicked.connect(self.onMatrixTypeChanged)
        matrix_type_group.buttonClicked.connect(self.saveState)
        file_layout.addRow(self.dense_radio)

        matrix_layout = QHBoxLayout()
        self.matrix_x_input = QLineEdit(str(DEFAULT_PRINT_FILE_PARAMS["matrix_x"]))
        self.matrix_x_input.textChanged.connect(self.saveState)
        self.matrix_y_input = QLineEdit(str(DEFAULT_PRINT_FILE_PARAMS["matrix_y"]))
        self.matrix_y_input.textChanged.connect(self.saveState)
        self.matrix_z_input = QLineEdit(str(DEFAULT_PRINT_FILE_PARAMS["matrix_z"]))
        self.matrix_z_input.textChanged.connect(self.saveState)
        self.dense_matrix_value_input = QLineEdit(
            str(DEFAULT_PRINT_FILE_PARAMS["dense_matrix_value"])
        )
        self.dense_matrix_value_input.textChanged.connect(self.saveState)
        matrix_layout.addWidget(QLabel("Matrix X (Fast Axis):", self))
        matrix_layout.addWidget(self.matrix_x_input)
        matrix_layout.addWidget(QLabel("Matrix Y (Slow Axis):", self))
        matrix_layout.addWidget(self.matrix_y_input)
        matrix_layout.addWidget(QLabel("Matrix Z:", self))
        matrix_layout.addWidget(self.matrix_z_input)
        matrix_layout.addWidget(QLabel("Value (0-1):", self))
        matrix_layout.addWidget(self.dense_matrix_value_input)
        file_layout.addRow(matrix_layout)

        file_layout.addRow(self.npy_radio)

        npy_layout = QHBoxLayout()
        self.npy_path_input = QLineEdit()
        self.npy_path_input.setEnabled(False)
        self.npy_path_input.textChanged.connect(self.saveState)
        self.load_npy_button = QPushButton("Load NPY")
        self.load_npy_button.clicked.connect(self.loadNPYFile)
        self.load_npy_button.setEnabled(False)
        npy_layout.addWidget(self.npy_path_input)
        npy_layout.addWidget(self.load_npy_button)
        file_layout.addRow("NPY File:", npy_layout)

        # Initialize enabled state based on radio button default (after all widgets are created)
        self.onMatrixTypeChanged()

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        params_group = QGroupBox("Print Parameters")
        params_group.setStyleSheet(
            "QGroupBox::title { font-weight: bold; color: red; }"
        )
        params_layout = QFormLayout()

        self.z_step_input = QLineEdit(str(DEFAULT_PRINT_PARAMS["z_step"]))
        self.z_step_input.textChanged.connect(self.saveState)
        params_layout.addRow("Z Step (µm):", self.z_step_input)

        self.time_per_pixel_input = QLineEdit(
            str(DEFAULT_PRINT_PARAMS["time_per_pixel"])
        )
        self.time_per_pixel_input.textChanged.connect(self.saveState)
        params_layout.addRow("Time per Pixel (µs):", self.time_per_pixel_input)

        self.fov_x_input = QLineEdit(str(DEFAULT_PRINT_PARAMS["fov_x"]))
        self.fov_x_input.textChanged.connect(self.saveState)
        params_layout.addRow("FOV X (µm):", self.fov_x_input)

        self.fov_y_input = QLineEdit(str(DEFAULT_PRINT_PARAMS["fov_y"]))
        self.fov_y_input.textChanged.connect(self.saveState)
        params_layout.addRow("FOV Y (µm):", self.fov_y_input)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        self.pointscan_button = QPushButton("Start Print")
        self.pointscan_button.clicked.connect(self.runPointscan)
        layout.addWidget(self.pointscan_button)

        position_group = QGroupBox("Position Control")
        position_group.setStyleSheet(
            "QGroupBox::title { font-weight: bold; color: red; }"
        )
        position_layout = QVBoxLayout()

        def add_labeled_column(h_layout, label_text, widget, align_widget=False):
            col = QVBoxLayout()
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignCenter)
            col.addWidget(label)
            if align_widget:
                widget.setAlignment(Qt.AlignCenter)
            col.addWidget(widget)
            h_layout.addLayout(col)

        def add_button_column(h_layout, button_text, callback):
            col = QVBoxLayout()
            col.addWidget(QLabel(""))
            btn = QPushButton(button_text)
            btn.clicked.connect(callback)
            col.addWidget(btn)
            h_layout.addLayout(col)
            return btn

        def set_equal_stretch(h_layout, count=4):
            for i in range(count):
                h_layout.setStretch(i, 1)

        # Current position row
        current_pos_layout = QHBoxLayout()
        self.x_pos_label = QLabel("0.000")
        self.y_pos_label = QLabel("0.000")
        self.z_pos_label = QLabel("0.000")
        for label_text, widget in [
            ("Current X (µm):", self.x_pos_label),
            ("Current Y (µm):", self.y_pos_label),
            ("Current Z (µm):", self.z_pos_label),
        ]:
            add_labeled_column(
                current_pos_layout, label_text, widget, align_widget=True
            )
        # Store label references for controller name updates
        self.x_label = current_pos_layout.itemAt(0).layout().itemAt(0).widget()
        self.y_label = current_pos_layout.itemAt(1).layout().itemAt(0).widget()
        self.z_label = current_pos_layout.itemAt(2).layout().itemAt(0).widget()
        self.set_home_button = add_button_column(
            current_pos_layout, "Set as Home", self.setHome
        )
        set_equal_stretch(current_pos_layout)
        position_layout.addLayout(current_pos_layout)

        # Move to row
        move_layout = QHBoxLayout()
        self.x_input = QLineEdit("0")
        self.y_input = QLineEdit("0")
        self.z_input = QLineEdit("0")
        for label_text, widget in [
            ("X (µm):", self.x_input),
            ("Y (µm):", self.y_input),
            ("Z (µm):", self.z_input),
        ]:
            add_labeled_column(move_layout, label_text, widget)
        self.move_to_button = add_button_column(
            move_layout, "Move To", self.moveToPosition
        )
        set_equal_stretch(move_layout)
        position_layout.addLayout(move_layout)

        # Move by row
        move_by_layout = QHBoxLayout()
        self.x_by_input = QLineEdit("0")
        self.y_by_input = QLineEdit("0")
        self.z_by_input = QLineEdit("0")
        for label_text, widget in [
            ("ΔX (µm):", self.x_by_input),
            ("ΔY (µm):", self.y_by_input),
            ("ΔZ (µm):", self.z_by_input),
        ]:
            add_labeled_column(move_by_layout, label_text, widget)
        self.move_by_button = add_button_column(
            move_by_layout, "Move By", self.moveByPosition
        )
        set_equal_stretch(move_by_layout)
        position_layout.addLayout(move_by_layout)

        # Home position row
        home_layout = QHBoxLayout()
        self.home_x_label = QLabel("0.000")
        self.home_y_label = QLabel("0.000")
        self.home_z_label = QLabel("0.000")
        for label_text, widget in [
            ("Home X (µm):", self.home_x_label),
            ("Home Y (µm):", self.home_y_label),
            ("Home Z (µm):", self.home_z_label),
        ]:
            add_labeled_column(home_layout, label_text, widget, align_widget=True)
        self.move_home_button = add_button_column(home_layout, "Go Home", self.moveHome)
        set_equal_stretch(home_layout)
        position_layout.addLayout(home_layout)
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)

        minimap_layout = QHBoxLayout()

        # Simple XY plot with Z colorbar
        self.minimap_figure, self.minimap_ax = plt.subplots()
        self.minimap_figure.patch.set_facecolor("none")
        self.minimap_ax.set_facecolor("none")
        self.minimap_canvas = FigureCanvas(self.minimap_figure)
        self.minimap_canvas.setFixedSize(*GUI_CONFIG["minimap_size"])

        # Set limits from config
        x_limits = STAGE_POSITION_LIMITS["axis_limits"]["X"]
        y_limits = STAGE_POSITION_LIMITS["axis_limits"]["Y"]
        # Use ZAXIS limits for Dover controller, Z limits for others
        z_axis_key = "ZAXIS" if isinstance(self.z_controller, DoverController) else "Z"
        z_limits = STAGE_POSITION_LIMITS["axis_limits"][z_axis_key]
        self.z_min_nm = z_limits["min"]
        self.z_max_nm = z_limits["max"]

        self.minimap_ax.set_xlim(x_limits["min"] / 1e3, x_limits["max"] / 1e3)
        self.minimap_ax.set_ylim(y_limits["min"] / 1e3, y_limits["max"] / 1e3)
        self.minimap_ax.set_aspect("equal", adjustable="box")

        # Set same grid intervals for X and Y
        major_interval = 20000.0  # µm
        minor_interval = 5000.0  # µm
        for axis in [self.minimap_ax.xaxis, self.minimap_ax.yaxis]:
            axis.set_major_locator(MultipleLocator(major_interval))
            axis.set_minor_locator(MultipleLocator(minor_interval))

        self.minimap_ax.grid(True, which="minor", linewidth=1, alpha=0.3, linestyle=":")
        self.minimap_ax.grid(True, which="major", linewidth=1, alpha=0.5)
        self.minimap_ax.axhline(y=0, color="black", linewidth=1.5, zorder=1)
        self.minimap_ax.axvline(x=0, color="black", linewidth=1.5, zorder=1)
        self.minimap_ax.set_xlabel("X (µm)", fontsize=12)
        self.minimap_ax.set_ylabel("Y (µm)", fontsize=12)
        (self.position_point,) = self.minimap_ax.plot(
            0, 0, "r+", markersize=20, markeredgewidth=2, zorder=10
        )

        # Z colorbar: create colormap function (using microns)
        self.z_min_um = self.z_min_nm / 1e3
        self.z_max_um = self.z_max_nm / 1e3

        def create_z_colormap(z_pos_um):
            z_norm = (z_pos_um - self.z_min_um) / (self.z_max_um - self.z_min_um)
            red_width = 0.01
            red_start = max(0, z_norm - red_width)
            red_end = min(1, z_norm + red_width)
            light_gray = (0.85, 0.85, 0.85)
            red_color = (1.0, 0.2, 0.2)

            positions = [0]
            colors = [light_gray]
            if red_start > 0:
                positions.append(red_start)
                colors.append(light_gray)
            positions.extend([red_start, red_end])
            colors.extend([red_color, red_color])
            if red_end < 1:
                positions.extend([red_end, 1])
                colors.extend([light_gray, light_gray])
            return LinearSegmentedColormap.from_list(
                "z_cmap", list(zip(positions, colors))
            )

        self.create_z_colormap = create_z_colormap
        self.z_cmap = create_z_colormap(self.z_min_um)
        self.z_mappable = ScalarMappable(
            cmap=self.z_cmap, norm=Normalize(self.z_min_um, self.z_max_um)
        )
        self.z_mappable.set_array([])
        self.z_cbar = self.minimap_figure.colorbar(
            self.z_mappable, ax=self.minimap_ax, orientation="vertical"
        )
        self.z_cbar.ax.set_title("Z (µm)", fontsize=12)
        self.z_cbar.ax.set_facecolor("none")
        self.minimap_canvas.draw()

        minimap_layout.addWidget(self.minimap_canvas)

        minimap_layout.setSpacing(10)

        layout.addLayout(minimap_layout)

        self.laser_button = QPushButton("Laser: OFF")
        self.laser_button.clicked.connect(self.toggleLaser)
        layout.addWidget(self.laser_button)

    def initJoystickThread(self) -> None:
        self.joystick_thread = JoystickThread(self.controllers, self.movement_lock)
        self.joystick_thread.toggle_laser.connect(self.toggleLaser)
        self.joystick_thread.run_pointscan.connect(self.runPointscan)
        self.joystick_thread.position_update.connect(self.updatePosition)
        self.joystick_thread.start()

    def updatePosition(self) -> None:
        x_pos = self.x_controller.position
        y_pos = self.y_controller.position
        z_pos = self.z_controller.position

        if hasattr(self, "x_label"):
            self.x_label.setText(f"{self.x_controller.__class__.__name__}\nCurrent X (µm):")  # type: ignore
            self.y_label.setText(f"{self.y_controller.__class__.__name__}\nCurrent Y (µm):")  # type: ignore
            self.z_label.setText(f"{self.z_controller.__class__.__name__}\nCurrent Z (µm):")  # type: ignore

        if x_pos is not None and z_pos is not None and y_pos is not None:
            self.x_pos_label.setText(f"{x_pos/1e3:9.3f}")
            self.y_pos_label.setText(f"{y_pos/1e3:9.3f}")
            self.z_pos_label.setText(f"{z_pos/1e3:9.3f}")
            self.home_x_label.setText(f"{self.home_x/1e3:9.3f}")
            self.home_y_label.setText(f"{self.home_y/1e3:9.3f}")
            self.home_z_label.setText(f"{self.home_z/1e3:9.3f}")

            x_um = x_pos / 1e3
            y_um = y_pos / 1e3
            z_um = z_pos / 1e3

            # Update matplotlib plot
            self.position_point.set_data([x_um], [y_um])
            self.z_cmap = self.create_z_colormap(z_um)
            self.z_mappable.set_cmap(self.z_cmap)
            self.z_cbar.update_normal(self.z_mappable)

            self.minimap_canvas.draw_idle()

    def onMatrixTypeChanged(self) -> None:
        use_dense = self.dense_radio.isChecked()
        self.npy_path_input.setEnabled(not use_dense)
        self.load_npy_button.setEnabled(not use_dense)
        self.matrix_x_input.setEnabled(use_dense)
        self.matrix_y_input.setEnabled(use_dense)
        self.matrix_z_input.setEnabled(use_dense)
        self.dense_matrix_value_input.setEnabled(use_dense)

    def loadNPYFile(self) -> None:
        initial_dir = (
            os.path.dirname(self.npy_path_input.text())
            if self.npy_path_input.text()
            else ""
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select NPY File",
            initial_dir,
            "NPY Files (*.npy)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if file_path:
            self.npy_path_input.setText(file_path)

    def runPointscan(self) -> None:
        if not self.is_printing:
            if self.movement_lock.tryLock():
                try:
                    if self.laser_thread and self.laser_thread.isRunning():
                        try:
                            print("Turning off laser before starting print...")
                            self.laser_thread.stop()
                            self.laser_thread.wait(THREADING_CONFIG["wait_timeout"])
                        except Exception as e:
                            print(f"Error turning laser off before printing: {e}")

                    try:
                        z_step = float(self.z_step_input.text())
                        time_per_pixel = float(self.time_per_pixel_input.text()) * 1e-6
                        fov_x = float(self.fov_x_input.text())
                        fov_y = float(self.fov_y_input.text())
                        matrix_x = int(self.matrix_x_input.text())
                        matrix_y = int(self.matrix_y_input.text())
                        matrix_z = int(self.matrix_z_input.text())

                        if self.dense_radio.isChecked():
                            dense_value = float(self.dense_matrix_value_input.text())
                            dense_value = max(
                                0.0, min(1.0, dense_value)
                            )  # Clamp to 0-1
                            matrix_3D = (
                                np.ones((matrix_y, matrix_x, matrix_z)) * dense_value
                            )
                        else:
                            matrix_3D = np.load(self.npy_path_input.text())

                        self.initial_z_pos = self.z_controller.position

                        self.pointscan_thread = PointscanThread(
                            self.z_controller, self.daq_connected, self.movement_lock
                        )
                        self.pointscan_thread.matrix = matrix_3D
                        self.pointscan_thread.params = {
                            "z_step_microns": z_step,
                            "timePerPixel": time_per_pixel,
                            "FOV_X_um": fov_x,
                            "FOV_Y_um": fov_y,
                        }

                        self.pointscan_thread.finished.connect(self.onPointscanFinished)
                        self.pointscan_thread.error.connect(self.onPointscanError)
                        self.pointscan_thread.start()

                        self.is_printing = True
                        self.pointscan_button.setText("Stop Print")
                    except ValueError as e:
                        print(f"Invalid parameter value: {e}")
                    except Exception as e:
                        print(f"Error starting print: {e}")
                finally:
                    self.movement_lock.unlock()
            else:
                print(
                    "[GUI] Could not acquire movement lock to start print. Movement may be in progress."
                )
        else:
            # Stop print - can be called without lock since stop() just sets a flag
            if self.pointscan_thread:
                self.pointscan_thread.stop()
            self.is_printing = False
            self.pointscan_button.setText("Start Print")

    def onPointscanFinished(self) -> None:
        self.is_printing = False
        self.pointscan_button.setText("Start Print")
        if self.movement_lock.tryLock():
            try:
                self.z_controller.move(self.initial_z_pos)
            finally:
                self.movement_lock.unlock()
        else:
            print("[GUI] WARNING: Could not acquire lock for post-print Z movement")

    def onPointscanError(self, error_msg: str) -> None:
        print(f"Error during print: {error_msg}")

    def toggleLaser(self) -> None:
        if self.is_printing:
            print("Cannot toggle laser while printing is in progress")
            return

        try:
            if not self.laser_thread or (
                self.laser_thread and not self.laser_thread.isRunning()
            ):
                # Turn laser ON using maximum aom channel amplitude
                self.laser_thread = LaserThread(
                    daq_connected=self.daq_connected,
                    voltage=VOLTAGE_AMPLITUDES["aom"],
                    channel="aom",
                )
                self.laser_thread.finished.connect(self.onLaserFinished)
                self.laser_thread.error.connect(self.onLaserError)
                self.laser_thread.start()
                self.laser_button.setText("Laser: ON")
            else:
                # Turn laser OFF
                if self.laser_thread and self.laser_thread.isRunning():
                    self.laser_thread.stop()

        except Exception as e:
            print(f"Error toggling laser: {e}")

    def onLaserFinished(self) -> None:
        self.laser_button.setText("Laser: OFF")

    def onLaserError(self, error_msg: str) -> None:
        print(f"Error occurred while running laser: {error_msg}")
        self.laser_button.setText("Laser: OFF")

    def saveState(self) -> None:
        state = {
            "z_step": self.z_step_input.text(),
            "time_per_pixel": self.time_per_pixel_input.text(),
            "fov_x": self.fov_x_input.text(),
            "fov_y": self.fov_y_input.text(),
            "matrix_x": self.matrix_x_input.text(),
            "matrix_y": self.matrix_y_input.text(),
            "matrix_z": self.matrix_z_input.text(),
            "dense_matrix_value": self.dense_matrix_value_input.text(),
            "use_dense": self.dense_radio.isChecked(),
            "npy_path": self.npy_path_input.text(),
            "x_position": self.x_controller.position,
            "y_position": self.y_controller.position,
            "z_position": self.z_controller.position,
            "home_x": self.home_x,
            "home_y": self.home_y,
            "home_z": self.home_z,
        }
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state, f)

    def loadState(self) -> None:
        """Load UI state from file."""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)

            self.z_step_input.setText(
                state.get("z_step", str(DEFAULT_PRINT_PARAMS["z_step"]))
            )
            self.time_per_pixel_input.setText(
                state.get("time_per_pixel", str(DEFAULT_PRINT_PARAMS["time_per_pixel"]))
            )
            self.fov_x_input.setText(
                state.get("fov_x", str(DEFAULT_PRINT_PARAMS["fov_x"]))
            )
            self.fov_y_input.setText(
                state.get("fov_y", str(DEFAULT_PRINT_PARAMS["fov_y"]))
            )
            self.matrix_x_input.setText(
                state.get("matrix_x", str(DEFAULT_PRINT_FILE_PARAMS["matrix_x"]))
            )
            self.matrix_y_input.setText(
                state.get("matrix_y", str(DEFAULT_PRINT_FILE_PARAMS["matrix_y"]))
            )
            self.matrix_z_input.setText(
                state.get("matrix_z", str(DEFAULT_PRINT_FILE_PARAMS["matrix_z"]))
            )
            self.dense_matrix_value_input.setText(
                state.get(
                    "dense_matrix_value",
                    str(DEFAULT_PRINT_FILE_PARAMS["dense_matrix_value"]),
                )
            )
            self.npy_path_input.setText(state.get("npy_path", ""))

            use_dense = state.get("use_dense", True)
            if use_dense:
                self.dense_radio.setChecked(True)
            else:
                self.npy_radio.setChecked(True)
            self.onMatrixTypeChanged()
            reference_pos = XERYON_CONFIG["reference_position"]
            self.home_x = state.get("home_x", reference_pos["X"])
            self.home_y = state.get("home_y", reference_pos["Y"])
            self.home_z = state.get("home_z", reference_pos["Z"])
        except Exception as e:
            print(f"Error loading state: {e}")

    def closeEvent(self, event) -> None:
        self.saveState()
        self.update_timer.stop()
        self.position_save_timer.stop()

        if self.pointscan_thread and self.pointscan_thread.isRunning():
            self.pointscan_thread.stop()
            self.pointscan_thread.wait()

        if self.laser_thread and self.laser_thread.isRunning():
            self.laser_thread.stop()
            self.laser_thread.wait()

        if self.joystick_thread and self.joystick_thread.isRunning():
            self.joystick_thread.stop()
            self.joystick_thread.wait()

        for controller in self.controllers:
            controller.close()

        if isinstance(self.z_controller, DoverController):
            shutdown_motion_synergy_api()

        event.accept()

    def moveToPosition(self) -> None:
        if self.movement_lock.tryLock():
            try:
                try:
                    x_target = int(float(self.x_input.text()) * 1e3)
                    y_target = int(float(self.y_input.text()) * 1e3)
                    z_target = int(float(self.z_input.text()) * 1e3)
                except ValueError:
                    print("Invalid position values. Please enter numeric values.")
                    return

                self.x_controller.move(x_target)
                self.y_controller.move(y_target)
                self.z_controller.move(z_target)
            finally:
                self.movement_lock.unlock()

    def moveByPosition(self) -> None:
        if self.movement_lock.tryLock():
            try:
                try:
                    x_delta = int(float(self.x_by_input.text()) * 1e3)
                    y_delta = int(float(self.y_by_input.text()) * 1e3)
                    z_delta = int(float(self.z_by_input.text()) * 1e3)
                except ValueError:
                    print("Invalid position values. Please enter numeric values.")
                    return

                self.x_controller.move(
                    self.x_controller.get_desired_position() + x_delta
                )
                self.y_controller.move(
                    self.y_controller.get_desired_position() + y_delta
                )
                self.z_controller.move(
                    self.z_controller.get_desired_position() + z_delta
                )

                self.x_by_input.setText("0")
                self.y_by_input.setText("0")
                self.z_by_input.setText("0")
            finally:
                self.movement_lock.unlock()

    def setHome(self) -> None:
        if self.x_controller.position is not None:
            self.home_x = self.x_controller.position
        if self.y_controller.position is not None:
            self.home_y = self.y_controller.position
        if self.z_controller.position is not None:
            self.home_z = self.z_controller.position
        self.saveState()

    def moveHome(self) -> None:
        if self.movement_lock.tryLock():
            try:
                self.x_controller.move(self.home_x)
                self.y_controller.move(self.home_y)
                self.z_controller.move(self.home_z)
            finally:
                self.movement_lock.unlock()
