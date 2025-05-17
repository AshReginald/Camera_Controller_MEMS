# -- coding: utf-8 --
import sys
import tkinter as tk
from PIL import Image, ImageTk
import cv2
import numpy as np
from ctypes import *

# Thêm đường dẫn đến thư mục chứa SDK (nếu cần)
# sys.path.append("C:/Hikvision/MVS/Python")  # Thay đổi đường dẫn nếu cần

from CameraParams_const import MV_GIGE_DEVICE, MV_USB_DEVICE, MV_ACCESS_Exclusive
from CameraParams_header import MV_CC_DEVICE_INFO_LIST, MV_FRAME_OUT_INFO_EX, MV_CC_PIXEL_CONVERT_PARAM, MV_TRIGGER_MODE_OFF
from CameraConnectStream_Class import CameraOperation
from MvCameraControl_class import MvCamera

class CameraDisplay:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera Display")
        
        # Biến quản lý camera
        self.device_list = MV_CC_DEVICE_INFO_LIST()
        self.cam = MvCamera()
        self.obj_cam_operation = None
        self.is_running = False
        
        # Nhãn để hiển thị hình ảnh
        self.label_image = tk.Label(root)
        self.label_image.pack(padx=10, pady=10)
        
        # Khởi động camera
        self.start_camera()
        
        # Bắt đầu vòng lặp hiển thị
        self.display_loop()

    def start_camera(self):
        # Liệt kê thiết bị
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, byref(self.device_list))
        if ret != 0:
            tk.messagebox.showerror("Error", f"Enumerate devices failed! ret = {ret:08x}")
            self.root.quit()
            return
        
        if self.device_list.nDeviceNum == 0:
            tk.messagebox.showerror("Error", "No devices found!")
            self.root.quit()
            return
        
        # Chọn thiết bị đầu tiên
        self.obj_cam_operation = CameraOperation(
            obj_cam=self.cam,
            st_device_list=self.device_list,
            n_connect_num=0
        )
        
        # Mở thiết bị
        ret = self.obj_cam_operation.Open_device()
        if ret != 0:
            tk.messagebox.showerror("Error", f"Open device failed! ret = {ret:08x}")
            self.root.quit()
            return
        
        # Bắt đầu thu thập
        ret = self.obj_cam_operation.Start_grabbing()
        if ret != 0:
            tk.messagebox.showerror("Error", f"Start grabbing failed! ret = {ret:08x}")
            self.root.quit()
            return
        
        self.is_running = True

    def display_loop(self):
        if not self.is_running:
            return
        
        # Lấy hình ảnh từ camera
        image = self.obj_cam_operation.Export_image()
        if image is not None:
            # Chuyển đổi hình ảnh OpenCV sang định dạng PIL
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)  # Chuyển BGR sang RGB
            image = Image.fromarray(image)
            # Thay đổi kích thước nếu cần (tùy chọn)
            image = image.resize((640, 480), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            
            # Cập nhật nhãn hiển thị
            self.label_image.configure(image=photo)
            self.label_image.image = photo  # Giữ tham chiếu để tránh garbage collection
        
        # Lên lịch cho khung hình tiếp theo
        self.root.after(10, self.display_loop)

    def on_closing(self):
        if self.is_running:
            self.obj_cam_operation.Stop_grabbing()
            self.obj_cam_operation.Close_device()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = CameraDisplay(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()