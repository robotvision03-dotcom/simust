"""
create_results_video.py - Creates a results video from recognition report
"""

import sys
import os
import json
import cv2
import numpy as np
from datetime import datetime

def create_results_video(report_path, output_path):
    """Create a video from the recognition report"""
    try:
        # Load the report
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        
        # Video dimensions (same as smart player)
        width = 3712
        height = 512
        fps = 5  # 5 frames per second, show for 5 seconds = 25 frames
        
        # Create video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        # Get stats
        stats = report.get('statistics', {})
        total_actions = report.get('total_actions', 0)
        correct = stats.get('correct', 0)
        late = stats.get('late', 0)
        wrong = stats.get('wrong', 0) + stats.get('no_goal', 0)
        
        correct_pct = (correct / total_actions * 100) if total_actions > 0 else 0
        late_pct = (late / total_actions * 100) if total_actions > 0 else 0
        wrong_pct = (wrong / total_actions * 100) if total_actions > 0 else 0
        simust_score = correct_pct
        
        # Goals by screen
        goals_by_screen = report.get('goals_by_screen', {})
        sorted_goals = sorted(goals_by_screen.items(), key=lambda x: x[1], reverse=True)
        
        # Create frames
        for frame_num in range(25):  # 5 seconds at 5 fps
            # Create blank image with dark background
            img = np.zeros((height, width, 3), dtype=np.uint8)
            img[:] = (20, 20, 35)  # Dark background
            
            # Title - SIMUST RESULTS
            cv2.putText(img, "SIMUST RESULTS", (width//2 - 200, 70), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 193, 7), 3)
            
            # Player info
            player_info = ""
            if 'player' in report:
                p = report['player']
                player_info = f"{p.get('name', '')} {p.get('surname', '')} (ID: {p.get('playerId', 'N/A')})"
            elif 'session' in report:
                session = report['session']
                player_info = f"Level: {session.get('level', 'Unknown')}"
            
            if player_info:
                cv2.putText(img, player_info, (width//2 - 200, 110), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 180, 220), 2)
            
            # Draw a line separator
            cv2.line(img, (100, 130), (width-100, 130), (255, 193, 7, 100), 1)
            
            # Stats cards
            stats_data = [
                (f"SIMUST SCORE: {simust_score:.1f}%", width//2 - 300, 180, 
                 (255, 193, 7) if simust_score >= 70 else (255, 150, 0) if simust_score >= 50 else (200, 50, 50)),
                (f"TOTAL ACTIONS: {total_actions}", width//2 - 300, 230, (100, 200, 255)),
                (f"CORRECT: {correct} ({correct_pct:.1f}%)", width//2 - 300, 280, (80, 220, 140)),
                (f"LATE: {late} ({late_pct:.1f}%)", width//2 + 100, 280, (255, 200, 80)),
                (f"WRONG: {wrong} ({wrong_pct:.1f}%)", width//2 + 500, 280, (255, 80, 80)),
            ]
            
            for text, x, y, color in stats_data:
                cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            # Goals by screen
            if sorted_goals:
                y_pos = 360
                cv2.putText(img, "GOALS BY SCREEN:", (100, y_pos), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 193, 7), 2)
                
                x_pos = 400
                for screen, count in sorted_goals[:6]:
                    if count > 0:
                        text = f"Screen {screen}: {count}"
                        cv2.putText(img, text, (x_pos, y_pos), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 2)
                        x_pos += 200
            
            # Footer
            cv2.putText(img, f"Analysis Complete - {datetime.now().strftime('%Y-%m-%d %H:%M')}", 
                       (width//2 - 250, height - 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
            
            out.write(img)
        
        out.release()
        print(f"✅ Results video created: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to create results video: {e}")
        return False


def main():
    if len(sys.argv) < 3:
        print("Usage: python create_results_video.py <report_path> <output_path>")
        print("Example: python create_results_video.py C:/path/to/recognition_report.json C:/path/to/results_video.mp4")
        sys.exit(1)
    
    report_path = sys.argv[1]
    output_path = sys.argv[2]
    
    if not os.path.exists(report_path):
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)
    
    create_results_video(report_path, output_path)


if __name__ == "__main__":
    main()