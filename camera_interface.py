# OOCYTE_TIMELAPSE_TRACKER/hardware/camera/camera_interface.py
import sys
import os
import cv2 # Cần thêm thư viện opencv-python
import numpy as np
from ctypes import byref, sizeof, memset, cast, POINTER, c_bool, c_ubyte

# === PHẦN SỬA ĐỔI BẮT ĐẦU TẠI ĐÂY ===
# Thay thế ".sdk_files" bằng ".camera_utilities"
from .camera_utilities.MvCameraControl_class import MvCamera
from .camera_utilities.CameraParams_const import (MV_GIGE_DEVICE, MV_USB_DEVICE, MV_ACCESS_Exclusive)
from .camera_utilities.CameraParams_header import (MV_CC_DEVICE_INFO_LIST, MV_CC_DEVICE_INFO, MVCC_INTVALUE,
                                              MV_FRAME_OUT_INFO_EX, MV_CC_PIXEL_CONVERT_PARAM, MV_TRIGGER_MODE_OFF)
from .camera_utilities.PixelType_header import PixelType_Gvsp_RGB8_Packed
from .camera_utilities.MvErrorDefine_const import MV_OK

class CameraController:
    """
    Lớp giao diện cấp cao để điều khiển camera công nghiệp Hikrobot.
    Cung cấp các phương thức đơn giản để kết nối, lấy ảnh và ngắt kết nối.
    """
    def __init__(self):
        self.cam = MvCamera()
        self.device_list = MV_CC_DEVICE_INFO_LIST()
        self.is_connected = False
        self.payload_size = 0
        self.image_buffer = None

    def _check_error(self, ret, message):
        """Hàm nội bộ để kiểm tra mã trả về và ném ra exception nếu có lỗi."""
        if ret != MV_OK:
            # Bạn có thể xây dựng một bộ chuyển đổi mã lỗi chi tiết hơn ở đây
            error_msg = f"{message} | Mã lỗi: {ret:#010x}"
            raise RuntimeError(error_msg)

    def connect(self, device_index: int = 0):
        """
        Quét tìm, kết nối và khởi động camera.
        
        Args:
            device_index (int): Chỉ số của camera cần kết nối trong danh sách tìm thấy.
        
        Raises:
            RuntimeError: Nếu không tìm thấy camera hoặc không thể kết nối/khởi động.
        """
        if self.is_connected:
            print("Camera đã được kết nối.")
            return

        # 1. Liệt kê thiết bị
        tlayer_type = MV_GIGE_DEVICE | MV_USB_DEVICE
        ret = MvCamera.MV_CC_EnumDevices(tlayer_type, byref(self.device_list))
        self._check_error(ret, "Liệt kê thiết bị thất bại")

        if self.device_list.nDeviceNum == 0:
            raise RuntimeError("Không tìm thấy camera nào.")
        
        if device_index >= self.device_list.nDeviceNum:
            raise ValueError(f"Chỉ số camera ({device_index}) vượt quá số lượng camera tìm thấy ({self.device_list.nDeviceNum}).")

        print(f"Tìm thấy {self.device_list.nDeviceNum} camera. Đang kết nối tới camera số {device_index}.")

        # 2. Tạo handle cho thiết bị được chọn
        st_device_info = cast(self.device_list.pDeviceInfo[device_index], POINTER(MV_CC_DEVICE_INFO)).contents
        ret = self.cam.MV_CC_CreateHandle(st_device_info)
        self._check_error(ret, "Tạo handle thất bại")

        # 3. Mở thiết bị
        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        self._check_error(ret, "Mở camera thất bại")

        # 4. Tối ưu hóa kích thước gói tin (cho camera GigE)
        if st_device_info.nTLayerType == MV_GIGE_DEVICE:
            packet_size = self.cam.MV_CC_GetOptimalPacketSize()
            if packet_size > 0:
                self.cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet_size)

        # 5. Lấy payload size và cấp phát bộ đệm
        st_param = MVCC_INTVALUE()
        memset(byref(st_param), 0, sizeof(MVCC_INTVALUE))
        ret = self.cam.MV_CC_GetIntValue("PayloadSize", st_param)
        self._check_error(ret, "Lấy PayloadSize thất bại")
        self.payload_size = st_param.nCurValue
        self.image_buffer = (c_ubyte * self.payload_size)()

        # 6. Cấu hình các thông số tự động (quan trọng)
        self.cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
        self.cam.MV_CC_SetEnumValue("ExposureAuto", 2)  # Continuous
        self.cam.MV_CC_SetEnumValue("GainAuto", 2)      # Continuous
        self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 1) # Continuous

        # 7. Bắt đầu lấy ảnh (start grabbing)
        ret = self.cam.MV_CC_StartGrabbing()
        self._check_error(ret, "Bắt đầu grabbing thất bại")

        self.is_connected = True
        print("Kết nối và khởi động camera thành công.")

    def get_frame(self) -> np.ndarray | None:
        """
        Lấy một khung hình từ camera và trả về dưới dạng mảng NumPy (BGR).
        
        Returns:
            np.ndarray: Khung hình dạng BGR.
            None: Nếu lấy ảnh thất bại (ví dụ: timeout).
        """
        if not self.is_connected:
            raise RuntimeError("Camera chưa được kết nối. Vui lòng gọi connect() trước.")

        st_frame_info = MV_FRAME_OUT_INFO_EX()
        memset(byref(st_frame_info), 0, sizeof(st_frame_info))
        
        ret = self.cam.MV_CC_GetOneFrameTimeout(byref(self.image_buffer), self.payload_size, st_frame_info, 1000)
        if ret != MV_OK:
            # Đây có thể không phải là lỗi nghiêm trọng, chỉ là timeout, nên trả về None
            print(f"Cảnh báo: Lấy khung hình thất bại. Mã lỗi: {ret:#010x}")
            return None

        # Chuyển đổi pixel format sang BGR để OpenCV xử lý
        # Lưu ý: Các file SDK gốc đã có logic chuyển sang RGB, tôi chỉnh lại sang BGR cho phù hợp với OpenCV
        w, h = st_frame_info.nWidth, st_frame_info.nHeight
        
        convert_param = MV_CC_PIXEL_CONVERT_PARAM()
        memset(byref(convert_param), 0, sizeof(convert_param))
        convert_param.nWidth = w
        convert_param.nHeight = h
        convert_param.pSrcData = self.image_buffer
        convert_param.nSrcDataLen = st_frame_info.nFrameLen
        convert_param.enSrcPixelType = st_frame_info.enPixelType
        
        # Chuyển đổi sang BGR 8-bit
        n_convert_size = w * h * 3
        convert_param.enDstPixelType = PixelType_Gvsp_RGB8_Packed # SDK thường chuyển sang RGB
        convert_param.pDstBuffer = (c_ubyte * n_convert_size)()
        convert_param.nDstBufferSize = n_convert_size
        
        ret = self.cam.MV_CC_ConvertPixelType(convert_param)
        self._check_error(ret, "Chuyển đổi định dạng pixel thất bại")
        
        # Tạo mảng NumPy từ buffer đã chuyển đổi
        image_data = np.frombuffer(convert_param.pDstBuffer, dtype=np.uint8)
        image_rgb = image_data.reshape((h, w, 3))
        
        # Chuyển từ RGB sang BGR cho OpenCV
        image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        
        return image_bgr

    def disconnect(self):
        """
        Dừng lấy ảnh, đóng và giải phóng tài nguyên camera.
        """
        if not self.is_connected:
            return

        print("Đang ngắt kết nối camera...")
        try:
            ret = self.cam.MV_CC_StopGrabbing()
            self._check_error(ret, "Dừng grabbing thất bại")
        except RuntimeError as e:
            print(e) # In lỗi nhưng vẫn tiếp tục các bước dọn dẹp khác

        try:
            ret = self.cam.MV_CC_CloseDevice()
            self._check_error(ret, "Đóng thiết bị thất bại")
        except RuntimeError as e:
            print(e)

        try:
            ret = self.cam.MV_CC_DestroyHandle()
            self._check_error(ret, "Hủy handle thất bại")
        except RuntimeError as e:
            print(e)
            
        self.is_connected = False
        self.image_buffer = None
        print("Đã ngắt kết nối và giải phóng tài nguyên.")