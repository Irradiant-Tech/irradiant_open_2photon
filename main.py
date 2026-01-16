import sys

# CRITICAL: Initialize MotionSynergyAPI BEFORE any PyQt/matplotlib imports
# This must happen first to avoid AccessViolationException from Qt DLL conflicts
from hardware.stage.dover_controller import initialize_motion_synergy_api

try:
    initialize_motion_synergy_api()
except Exception:
    pass

from PyQt5.QtCore import QtMsgType, qInstallMessageHandler
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QMessageBox

# Suppress QWindowsContext COM warning
qInstallMessageHandler(
    lambda t, c, m: (
        None if t == QtMsgType.QtWarningMsg and "QWindowsContext" in m else print(m)
    )
)

from config import GUI_CONFIG
from gui.main_window import IntegratedGUI


def main() -> None:
    app = QApplication(sys.argv)
    font = QFont()
    font.setPointSize(GUI_CONFIG["font_size"])
    app.setFont(font)
    
    msg = QMessageBox()
    msg.setWindowTitle("Safety Warning")
    msg.setText("Stages move to their hardware limits during initialization.\nIt is safer to remove the sample holder.\n\nHas the sample holder been removed?")
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.Yes)
    if msg.exec_() != QMessageBox.Yes:
        sys.exit(0)
    
    gui = IntegratedGUI()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
