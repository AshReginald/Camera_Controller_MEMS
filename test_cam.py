# -*- coding: utf-8 -*-
"""
test_cam.py
-----------
Chương trình test nhanh camera công nghiệp Hikrobot (MVS SDK).

Các bước:
    1. Liệt kê các camera (GigE / USB3 Vision) đang kết nối.
    2. Mở camera đầu tiên tìm được.
    3. Cấu hình tự động Exposure / Gain / White Balance.
    4. Bắt đầu streaming, hiển thị bằng OpenCV.
    5. Nhấn 's' để lưu một khung hình ra file PNG.
       Nhấn 'q' hoặc ESC để thoát.

Yêu cầu:
    - Đã cài MVS Runtime của Hikrobot (chứa các DLL MvCameraControl).
    - pip install opencv-python numpy
"""

import os
import sys
import time
import cv2
import numpy as np
from ctypes import (
    byref, sizeof, memset, cast, POINTER, c_ubyte,
)

# Đảm bảo Python tìm thấy thư mục camera_utilities (workspace root)
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from camera_utilities.MvCameraControl_class import MvCamera
from camera_utilities.CameraParams_const import (
    MV_GIGE_DEVICE, MV_USB_DEVICE, MV_ACCESS_Exclusive,
)
from camera_utilities.CameraParams_header import (
    MV_CC_DEVICE_INFO_LIST, MV_CC_DEVICE_INFO, MVCC_INTVALUE,
    MV_FRAME_OUT_INFO_EX, MV_CC_PIXEL_CONVERT_PARAM, MV_TRIGGER_MODE_OFF,
)
from camera_utilities.PixelType_header import PixelType_Gvsp_RGB8_Packed
from camera_utilities.MvErrorDefine_const import MV_OK


def hex_err(ret: int) -> str:
    """Format mã lỗi của SDK sang chuỗi hex."""
    if ret < 0:
        ret += 2 ** 32
    return f"0x{ret:08x}"


def get_device_name(dev_info: MV_CC_DEVICE_INFO) -> str:
    """Lấy tên model + serial từ thông tin thiết bị."""
    if dev_info.nTLayerType == MV_USB_DEVICE:
        usb = dev_info.SpecialInfo.stUsb3VInfo
        model = bytes(usb.chModelName).split(b'\x00', 1)[0].decode(errors='ignore')
        serial = bytes(usb.chSerialNumber).split(b'\x00', 1)[0].decode(errors='ignore')
        return f"[USB3] {model} (SN: {serial})"
    elif dev_info.nTLayerType == MV_GIGE_DEVICE:
        gige = dev_info.SpecialInfo.stGigEInfo
        model = bytes(gige.chModelName).split(b'\x00', 1)[0].decode(errors='ignore')
        ip_int = gige.nCurrentIp
        ip = ".".join(str((ip_int >> (8 * i)) & 0xFF) for i in (3, 2, 1, 0))
        return f"[GigE] {model} (IP: {ip})"
    return "[Unknown device]"


def main() -> int:
    cam = MvCamera()
    device_list = MV_CC_DEVICE_INFO_LIST()

    # 1. Liệt kê thiết bị
    ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
    if ret != MV_OK:
        print(f"[LỖI] EnumDevices thất bại: {hex_err(ret)}")
        return 1
    if device_list.nDeviceNum == 0:
        print("[LỖI] Không tìm thấy camera nào. Hãy kiểm tra cáp/nguồn và driver MVS.")
        return 1

    print(f"[OK] Tìm thấy {device_list.nDeviceNum} camera:")
    for i in range(device_list.nDeviceNum):
        info = cast(device_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
        print(f"    {i}: {get_device_name(info)}")

    # 2. Lấy camera index 0
    selected = cast(device_list.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
    ret = cam.MV_CC_CreateHandle(selected)
    if ret != MV_OK:
        print(f"[LỖI] CreateHandle: {hex_err(ret)}")
        return 1

    ret = cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
    if ret != MV_OK:
        print(f"[LỖI] OpenDevice: {hex_err(ret)}")
        cam.MV_CC_DestroyHandle()
        return 1
    print("[OK] Đã mở thiết bị.")

    # 3. Tối ưu packet size cho GigE
    if selected.nTLayerType == MV_GIGE_DEVICE:
        packet = cam.MV_CC_GetOptimalPacketSize()
        if packet > 0:
            cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet)
            print(f"[OK] Optimal packet size = {packet}")

    # 4. Lấy payload size, cấp phát buffer
    int_val = MVCC_INTVALUE()
    memset(byref(int_val), 0, sizeof(MVCC_INTVALUE))
    ret = cam.MV_CC_GetIntValue("PayloadSize", int_val)
    if ret != MV_OK:
        print(f"[LỖI] PayloadSize: {hex_err(ret)}")
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        return 1
    payload_size = int_val.nCurValue
    image_buffer = (c_ubyte * payload_size)()
    print(f"[OK] PayloadSize = {payload_size} bytes")

    # 5. Tắt trigger, bật auto exposure / gain / white balance
    cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
    cam.MV_CC_SetEnumValue("ExposureAuto", 2)       # Continuous
    cam.MV_CC_SetEnumValue("GainAuto", 2)           # Continuous
    cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 1)   # Continuous

    # 6. Bắt đầu grab
    ret = cam.MV_CC_StartGrabbing()
    if ret != MV_OK:
        print(f"[LỖI] StartGrabbing: {hex_err(ret)}")
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        return 1
    print("[OK] Bắt đầu streaming. Nhấn 's' để chụp, 'q'/ESC để thoát.")

    frame_info = MV_FRAME_OUT_INFO_EX()
    convert_buf = None
    convert_buf_size = 0
    last_t = time.time()
    fps = 0.0

    try:
        while True:
            memset(byref(frame_info), 0, sizeof(frame_info))
            ret = cam.MV_CC_GetOneFrameTimeout(
                byref(image_buffer), payload_size, frame_info, 1000
            )
            if ret != MV_OK:
                print(f"[CẢNH BÁO] GetOneFrameTimeout: {hex_err(ret)}")
                continue

            w, h = frame_info.nWidth, frame_info.nHeight
            need = w * h * 3
            if convert_buf is None or convert_buf_size < need:
                convert_buf = (c_ubyte * need)()
                convert_buf_size = need

            cvt = MV_CC_PIXEL_CONVERT_PARAM()
            memset(byref(cvt), 0, sizeof(cvt))
            cvt.nWidth = w
            cvt.nHeight = h
            cvt.pSrcData = image_buffer
            cvt.nSrcDataLen = frame_info.nFrameLen
            cvt.enSrcPixelType = frame_info.enPixelType
            cvt.enDstPixelType = PixelType_Gvsp_RGB8_Packed
            cvt.pDstBuffer = convert_buf
            cvt.nDstBufferSize = need

            ret = cam.MV_CC_ConvertPixelType(cvt)
            if ret != MV_OK:
                print(f"[CẢNH BÁO] ConvertPixelType: {hex_err(ret)}")
                continue

            arr = np.frombuffer(convert_buf, dtype=np.uint8, count=need).reshape((h, w, 3))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

            # Tính FPS đơn giản
            now = time.time()
            dt = now - last_t
            last_t = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)
            cv2.putText(
                bgr, f"{w}x{h}  {fps:5.1f} FPS",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
            )

            # Resize cho dễ xem nếu ảnh quá lớn
            disp = bgr
            if w > 1280:
                scale = 1280.0 / w
                disp = cv2.resize(bgr, (int(w * scale), int(h * scale)))

            cv2.imshow("Hikrobot Camera Test", disp)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):  # q hoặc ESC
                break
            if key == ord('s'):
                fname = time.strftime("capture_%Y%m%d_%H%M%S.png")
                cv2.imwrite(fname, bgr)
                print(f"[OK] Đã lưu ảnh: {fname}")

    except KeyboardInterrupt:
        print("\n[INFO] Người dùng dừng chương trình.")
    finally:
        print("[INFO] Đang dọn dẹp...")
        cam.MV_CC_StopGrabbing()
        cam.MV_CC_CloseDevice()
        cam.MV_CC_DestroyHandle()
        cv2.destroyAllWindows()
        print("[OK] Đã giải phóng camera.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
