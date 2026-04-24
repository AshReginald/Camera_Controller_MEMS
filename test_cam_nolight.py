# -*- coding: utf-8 -*-
"""
test_cam_nolight.py
-------------------
Kiểm tra "camera có sống không" mà KHÔNG cần đèn / cần nhìn ảnh.

Script sẽ:
    1. Liệt kê camera (USB3 / GigE) đang kết nối.
    2. Mở camera đầu tiên.
    3. In thông số: WxH, PixelType, PayloadSize, ExposureTime, Gain.
    4. Quét thử exposure ở 3 mức (thấp / vừa / cao) -> với mỗi mức lấy
       vài frame và in min / max / mean / std của pixel.
       Nếu camera hoạt động, các giá trị này sẽ THAY ĐỔI khi đổi exposure
       (mean tăng khi exposure tăng) -> bằng chứng sensor đang nhận sáng.
    5. Lưu 1 ảnh raw debug ra file PNG (kể cả khi tối đen).

Cách chạy:
    python test_cam_nolight.py
"""

import os
import sys
import time
import numpy as np
from ctypes import byref, sizeof, memset, cast, POINTER, c_ubyte, c_float

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from camera_utilities.MvCameraControl_class import MvCamera
from camera_utilities.CameraParams_const import (
    MV_GIGE_DEVICE, MV_USB_DEVICE, MV_ACCESS_Exclusive,
)
from camera_utilities.CameraParams_header import (
    MV_CC_DEVICE_INFO_LIST, MV_CC_DEVICE_INFO,
    MVCC_INTVALUE, MVCC_FLOATVALUE,
    MV_FRAME_OUT_INFO_EX, MV_TRIGGER_MODE_OFF,
)
from camera_utilities.MvErrorDefine_const import MV_OK


def hex_err(ret: int) -> str:
    if ret < 0:
        ret += 2 ** 32
    return f"0x{ret:08x}"


def get_int(cam, key):
    v = MVCC_INTVALUE()
    memset(byref(v), 0, sizeof(v))
    ret = cam.MV_CC_GetIntValue(key, v)
    return v.nCurValue if ret == MV_OK else None


def get_float(cam, key):
    v = MVCC_FLOATVALUE()
    memset(byref(v), 0, sizeof(v))
    ret = cam.MV_CC_GetFloatValue(key, v)
    return v.fCurValue if ret == MV_OK else None


def grab_frame(cam, buf, payload_size, timeout_ms=2000):
    info = MV_FRAME_OUT_INFO_EX()
    memset(byref(info), 0, sizeof(info))
    ret = cam.MV_CC_GetOneFrameTimeout(byref(buf), payload_size, info, timeout_ms)
    if ret != MV_OK:
        return None, ret
    n = info.nFrameLen
    arr = np.frombuffer(buf, dtype=np.uint8, count=n)
    return (arr, info), MV_OK


def stats(arr: np.ndarray) -> str:
    return (f"min={arr.min():3d} max={arr.max():3d} "
            f"mean={arr.mean():6.2f} std={arr.std():6.2f}")


def main() -> int:
    cam = MvCamera()
    dev_list = MV_CC_DEVICE_INFO_LIST()

    print("=" * 60)
    print("  HIKROBOT CAMERA SANITY CHECK (no light required)")
    print("=" * 60)

    ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, dev_list)
    if ret != MV_OK:
        print(f"[FAIL] EnumDevices: {hex_err(ret)}")
        return 1
    if dev_list.nDeviceNum == 0:
        print("[FAIL] Không thấy camera nào. Kiểm tra cáp / nguồn / driver MVS.")
        return 1
    print(f"[OK] Tìm thấy {dev_list.nDeviceNum} camera.")

    info = cast(dev_list.pDeviceInfo[0], POINTER(MV_CC_DEVICE_INFO)).contents
    if cam.MV_CC_CreateHandle(info) != MV_OK:
        print("[FAIL] CreateHandle")
        cam.MV_CC_DestroyHandle()
        return 1
    if cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0) != MV_OK:
        print("[FAIL] OpenDevice (có thể MVS Viewer đang giữ camera).")
        cam.MV_CC_DestroyHandle()
        return 1
    print("[OK] Open device.")

    if info.nTLayerType == MV_GIGE_DEVICE:
        ps = cam.MV_CC_GetOptimalPacketSize()
        if ps > 0:
            cam.MV_CC_SetIntValue("GevSCPSPacketSize", ps)

    # Tắt trigger -> free run
    cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
    # Tắt auto để mình tự đặt exposure
    cam.MV_CC_SetEnumValue("ExposureAuto", 0)
    cam.MV_CC_SetEnumValue("GainAuto", 0)

    payload_size = get_int(cam, "PayloadSize")
    width = get_int(cam, "Width")
    height = get_int(cam, "Height")
    exposure = get_float(cam, "ExposureTime")
    gain = get_float(cam, "Gain")

    print(f"  Resolution    : {width} x {height}")
    print(f"  PayloadSize   : {payload_size} bytes")
    print(f"  ExposureTime  : {exposure} us")
    print(f"  Gain          : {gain} dB")

    if not payload_size:
        print("[FAIL] Không đọc được PayloadSize.")
        cam.MV_CC_CloseDevice(); cam.MV_CC_DestroyHandle()
        return 1

    buf = (c_ubyte * payload_size)()

    if cam.MV_CC_StartGrabbing() != MV_OK:
        print("[FAIL] StartGrabbing")
        cam.MV_CC_CloseDevice(); cam.MV_CC_DestroyHandle()
        return 1
    print("[OK] Start grabbing.\n")

    # Quét thử 3 mức exposure (us). Một số model dùng đơn vị us, range
    # khác nhau; nếu set lỗi sẽ bỏ qua mức đó.
    test_exposures = [1000.0, 10000.0, 50000.0]
    last_arr = None

    for exp in test_exposures:
        ret_set = cam.MV_CC_SetFloatValue("ExposureTime", exp)
        if ret_set != MV_OK:
            print(f"[skip] Không set được ExposureTime={exp} us ({hex_err(ret_set)})")
            continue
        time.sleep(0.2)  # cho camera ổn định

        # Bỏ 1-2 frame đầu (đang trong queue cũ), lấy frame thứ 3
        ok_count = 0
        last = None
        for _ in range(4):
            res, rc = grab_frame(cam, buf, payload_size)
            if rc == MV_OK:
                ok_count += 1
                last = res

        actual_exp = get_float(cam, "ExposureTime")
        if last is None:
            print(f"  Exposure={exp:>7.0f} us -> [FAIL] Không lấy được frame.")
            continue

        arr, fi = last
        last_arr = (arr, fi)
        print(f"  Exposure set={exp:>7.0f} us  actual={actual_exp:>7.1f} us  "
              f"frames_ok={ok_count}/4")
        print(f"     frame: W={fi.nWidth} H={fi.nHeight} len={fi.nFrameLen} "
              f"pix=0x{fi.enPixelType:08x} fnum={fi.nFrameNum}")
        print(f"     pixel stats: {stats(arr)}")

    # Lưu raw + (nếu có thể) decode đơn giản 8-bit grayscale ra PNG để xem
    if last_arr is not None:
        arr, fi = last_arr
        raw_path = os.path.join(THIS_DIR, "debug_raw.bin")
        with open(raw_path, "wb") as f:
            f.write(bytes(arr))
        print(f"\n[OK] Đã ghi raw buffer: {raw_path} ({len(arr)} bytes)")

        # Cố gắng dump PNG nếu pixel format có vẻ là 8-bit/pixel mono/bayer
        try:
            import cv2
            n_pixels = fi.nWidth * fi.nHeight
            if len(arr) >= n_pixels:
                gray = arr[:n_pixels].reshape((fi.nHeight, fi.nWidth))
                png_path = os.path.join(THIS_DIR, "debug_frame.png")
                cv2.imwrite(png_path, gray)
                print(f"[OK] Đã lưu ảnh debug (xem dạng grayscale): {png_path}")
        except Exception as e:
            print(f"[warn] Không lưu được PNG: {e}")

    print("\n--- Kết luận ---")
    print(" * Nếu các dòng exposure trên đều có frames_ok > 0  -> Camera hoạt động.")
    print(" * Nếu mean pixel TĂNG khi exposure TĂNG            -> Sensor nhận sáng OK.")
    print(" * Nếu mean ~ 0 ở mọi exposure: che kín hoàn toàn  -> bình thường;")
    print("   thử rọi đèn điện thoại sát ống kính, mean phải bật lên.")

    cam.MV_CC_StopGrabbing()
    cam.MV_CC_CloseDevice()
    cam.MV_CC_DestroyHandle()
    print("[OK] Đã giải phóng camera.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
