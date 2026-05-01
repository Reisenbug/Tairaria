import pyautogui
import time

print("移动鼠标到目标位置，每秒打印坐标，ctrl+c退出")
while True:
    x, y = pyautogui.position()
    print(f"mouse=({x},{y})", end="\r")
    time.sleep(0.5)
