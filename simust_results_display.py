"""
simust_results_display.py - Displays recognition results on Screen 2
Shows results in the same 3712x512 format as the video player
"""

import sys
import os
import time
import json
import subprocess
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt

# Hide console on Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


class ResultsDisplayWindow(QtWidgets.QMainWindow):
    def __init__(self, report_path, screen_index=1, auto_close_delay=20000):
        super().__init__()
        self.report_path = report_path
        self.screen_index = screen_index
        self.auto_close_delay = auto_close_delay
        self.video_width = 3712
        self.video_height = 512
        
        # Check if we have a valid report
        self.has_report = os.path.exists(report_path) and report_path != "NO_REPORT"
        if self.has_report:
            self.report_data = self._load_report(report_path)
        else:
            self.report_data = None
        
        # Main window setup - transparent background
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | 
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        
        # Central widget with dark background
        self.central_widget = QtWidgets.QWidget(self)
        self.central_widget.setStyleSheet("background-color: rgba(0,0,0,0.92); border-radius: 0px;")
        self.setCentralWidget(self.central_widget)
        
        # Main layout
        layout = QtWidgets.QVBoxLayout(self.central_widget)
        layout.setContentsMargins(50, 30, 50, 30)
        layout.setSpacing(15)
        
        if self.has_report and self.report_data:
            self._build_results_layout(layout)
        else:
            self._build_no_report_layout(layout)
        
        # Auto-close timer
        self.close_timer = QtCore.QTimer()
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.close)
        
        # Position on Screen 2
        self._position_on_screen()
        
        # Show full screen
        self.showFullScreen()
        
        # Bring to front
        self.raise_()
        self.activateWindow()
        
        # Start auto-close timer
        self.close_timer.start(auto_close_delay)
        
        # Keyboard shortcuts
        self.setFocusPolicy(Qt.StrongFocus)
    
    def _build_results_layout(self, layout):
        """Build the results display layout"""
        # Title
        title = QtWidgets.QLabel("🏆 SIMUST RESULTS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 36px;
            font-weight: bold;
            color: #ffc107;
            font-family: 'Inter', 'Segoe UI', system-ui;
            padding: 5px;
        """)
        layout.addWidget(title)
        
        # Subtitle with player info
        player_info = self._get_player_info()
        if player_info:
            subtitle = QtWidgets.QLabel(f"👤 {player_info}")
            subtitle.setAlignment(Qt.AlignCenter)
            subtitle.setStyleSheet("color: #9ca3af; font-size: 16px; padding: 0px 0px 10px 0px;")
            layout.addWidget(subtitle)
        
        # Stats grid
        stats_widget = QtWidgets.QWidget()
        stats_layout = QtWidgets.QGridLayout(stats_widget)
        stats_layout.setSpacing(15)
        stats_layout.setContentsMargins(10, 10, 10, 10)
        
        stats = self.report_data.get('statistics', {})
        total_actions = self.report_data.get('total_actions', 0)
        correct = stats.get('correct', 0)
        late = stats.get('late', 0)
        wrong = stats.get('wrong', 0) + stats.get('no_goal', 0)
        
        # Calculate percentages
        correct_pct = (correct / total_actions * 100) if total_actions > 0 else 0
        late_pct = (late / total_actions * 100) if total_actions > 0 else 0
        wrong_pct = (wrong / total_actions * 100) if total_actions > 0 else 0
        simust_score = correct_pct
        
        # Stats cards
        stats_data = [
            ("🎯 SIMUST SCORE", f"{simust_score:.1f}%", "#ffc107" if simust_score >= 70 else "#f97316" if simust_score >= 50 else "#ef4444"),
            ("📊 TOTAL ACTIONS", str(total_actions), "#60a5fa"),
            ("✅ CORRECT", f"{correct} ({correct_pct:.1f}%)", "#4ade80"),
            ("⚠️ LATE", f"{late} ({late_pct:.1f}%)", "#fbbf24"),
            ("❌ WRONG", f"{wrong} ({wrong_pct:.1f}%)", "#f87171"),
        ]
        
        for i, (label, value, color) in enumerate(stats_data):
            card = QtWidgets.QWidget()
            card.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(255,255,255,0.06);
                    border-radius: 14px;
                    border: 1px solid rgba(255,255,255,0.08);
                    padding: 8px;
                }}
                QWidget:hover {{
                    background-color: rgba(255,255,255,0.10);
                }}
            """)
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setSpacing(2)
            
            label_widget = QtWidgets.QLabel(label)
            label_widget.setAlignment(Qt.AlignCenter)
            label_widget.setStyleSheet("color: #9ca3af; font-size: 13px; font-weight: 400;")
            
            value_widget = QtWidgets.QLabel(value)
            value_widget.setAlignment(Qt.AlignCenter)
            value_widget.setStyleSheet(f"""
                color: {color};
                font-size: 26px;
                font-weight: bold;
                font-family: monospace;
            """)
            
            card_layout.addWidget(label_widget)
            card_layout.addWidget(value_widget)
            stats_layout.addWidget(card, i // 3, i % 3)
        
        layout.addWidget(stats_widget)
        
        # Goals by screen section
        goals_by_screen = self.report_data.get('goals_by_screen', {})
        if goals_by_screen and any(count > 0 for count in goals_by_screen.values()):
            goals_label = QtWidgets.QLabel("🎯 GOALS BY SCREEN")
            goals_label.setAlignment(Qt.AlignCenter)
            goals_label.setStyleSheet("color: #ffc107; font-size: 18px; font-weight: bold; padding-top: 8px;")
            layout.addWidget(goals_label)
            
            goals_widget = QtWidgets.QWidget()
            goals_layout = QtWidgets.QHBoxLayout(goals_widget)
            goals_layout.setSpacing(20)
            goals_layout.setAlignment(Qt.AlignCenter)
            
            sorted_goals = sorted(goals_by_screen.items(), key=lambda x: x[1], reverse=True)
            for screen, count in sorted_goals[:6]:
                if count > 0:
                    screen_label = QtWidgets.QLabel(f"Screen {screen}: {count}")
                    screen_label.setStyleSheet("""
                        color: #e2e8f0;
                        font-size: 16px;
                        font-weight: 600;
                        background-color: rgba(255,193,7,0.15);
                        padding: 6px 18px;
                        border-radius: 8px;
                        border: 1px solid rgba(255,193,7,0.3);
                    """)
                    goals_layout.addWidget(screen_label)
            
            layout.addWidget(goals_widget)
        
        layout.addStretch()
        
        # Footer
        footer = QtWidgets.QLabel("📊 Analysis Complete • Press ESC or click to close")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #6b7280; font-size: 13px; padding: 8px;")
        layout.addWidget(footer)
    
    def _build_no_report_layout(self, layout):
        """Build layout when no report is found"""
        # Title
        title = QtWidgets.QLabel("📊 SIMUST RESULTS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 36px;
            font-weight: bold;
            color: #ffc107;
            font-family: 'Inter', 'Segoe UI', system-ui;
            padding: 20px;
        """)
        layout.addWidget(title)
        
        # Message
        message = QtWidgets.QLabel("⏳ Results are being processed...\n\nPlease wait a moment and try again.")
        message.setAlignment(Qt.AlignCenter)
        message.setStyleSheet("""
            color: #e2e8f0;
            font-size: 20px;
            padding: 30px;
            background-color: rgba(255,255,255,0.05);
            border-radius: 12px;
        """)
        layout.addWidget(message)
        
        layout.addStretch()
        
        footer = QtWidgets.QLabel("Press ESC or click to close")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet("color: #6b7280; font-size: 13px; padding: 8px;")
        layout.addWidget(footer)
    
    def _load_report(self, report_path):
        """Load and parse the recognition report"""
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading report: {e}")
            return None
    
    def _get_player_info(self):
        """Extract player info from report"""
        if not self.report_data:
            return None
        try:
            if 'player' in self.report_data:
                p = self.report_data['player']
                name = p.get('name', '')
                surname = p.get('surname', '')
                pid = p.get('playerId', 'N/A')
                return f"{name} {surname} (ID: {pid})"
            
            if 'session' in self.report_data:
                session = self.report_data['session']
                level = session.get('level', 'Unknown')
                timestamp = session.get('timestamp', '')
                if timestamp:
                    date = timestamp.split('T')[0] if 'T' in timestamp else timestamp[:10]
                    return f"{level} • {date}"
            
            return None
        except:
            return None
    
    def _position_on_screen(self):
        """Position window on the specified screen"""
        app = QtWidgets.QApplication.instance()
        screens = app.screens()
        
        if screens and self.screen_index < len(screens):
            screen = screens[self.screen_index]
            geometry = screen.geometry()
            
            # Set the window to cover the entire screen
            self.setGeometry(geometry)
            self.move(geometry.topLeft())
            
            print(f"📺 Positioned on Screen {self.screen_index}: {geometry.width()}x{geometry.height()}")
            
            # Make sure the window is on top
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint | 
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.Tool
            )
            self.show()
        else:
            # Fallback to primary screen
            if screens:
                screen = screens[0]
                geometry = screen.geometry()
                self.setGeometry(geometry)
                self.move(geometry.topLeft())
                print(f"📺 Positioned on primary screen: {geometry.width()}x{geometry.height()}")
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        key = event.key()
        if key == Qt.Key_Escape or key == Qt.Key_Space:
            self.close()
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self.close()
        else:
            super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """Click to close"""
        self.close()
    
    def closeEvent(self, event):
        """Clean up on close"""
        self.close_timer.stop()
        event.accept()


def main():
    if len(sys.argv) < 2:
        print("Usage: python simust_results_display.py <report_path> [screen_index] [auto_close_delay_ms]")
        print("Example: python simust_results_display.py C:/path/to/recognition_report.json 1 20000")
        sys.exit(1)
    
    report_path = sys.argv[1]
    
    screen_index = 1  # Default to Screen 2
    if len(sys.argv) >= 3:
        try:
            screen_index = int(sys.argv[2])
        except:
            pass
    
    auto_close_delay = 20000  # 20 seconds default
    if len(sys.argv) >= 4:
        try:
            auto_close_delay = int(sys.argv[3])
        except:
            pass
    
    print(f"📊 SIMUST Results Display")
    print(f"   Report: {report_path}")
    print(f"   Screen: {screen_index}")
    print(f"   Auto-close: {auto_close_delay}ms")
    
    # Create application
    app = QtWidgets.QApplication(sys.argv)
    
    # Create and show window
    window = ResultsDisplayWindow(report_path, screen_index, auto_close_delay)
    
    # Ensure window is visible
    window.show()
    window.raise_()
    window.activateWindow()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()