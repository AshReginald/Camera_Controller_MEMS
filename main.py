import sys
import cv2
import numpy as np

from camera_utilities.MvCameraControl_class import MvCamera
from camera_utilities.CameraConnectStream_Class import CameraOperation
from camera_utilities.CameraParams_const import MV_GIGE_DEVICE, MV_USB_DEVICE
from camera_utilities.CameraParams_header import MV_CC_DEVICE_INFO_LIST

def main():
    print("Tìm thiết bị...")
    device_list = MV_CC_DEVICE_INFO_LIST()
    cam = MvCamera()

    # Tìm camera
    ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
    if ret != 0 or device_list.nDeviceNum == 0:
        print("Không tìm thấy camera.")
        return
    print("Tìm thấy camera.")

    # Kết nối
    cam_op = CameraOperation(cam, device_list, n_connect_num=0)
    if cam_op.Open_device() != 0:
        print("Không mở được camera.")
        return

    # Bật các chế độ tự động (gain, exposure, white balance)
    cam_op.obj_cam.MV_CC_SetEnumValue("ExposureAuto", 2)          # Continuous
    cam_op.obj_cam.MV_CC_SetEnumValue("GainAuto", 2)              # Continuous
    cam_op.obj_cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 1)      # Continuous

    cam_op.Start_grabbing()
    print("Đang hiển thị video... Nhấn 'q' để thoát.")

    # Tạo cửa sổ OpenCV
    cv2.namedWindow("Live Camera", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Live Camera", 864, 648)

    # Vòng lặp hiển thị
    while True:
        frame = cam_op.Export_image()
        if frame is not None:
            cv2.imshow("Live Camera", frame)
        else:
            print("[WARNING] Không lấy được frame!")

        key = cv2.waitKey(1)
        if key == ord('q'):
            print("Đã nhận tín hiệu thoát.")
            break

    # Giải phóng tài nguyên
    cam_op.Stop_grabbing()
    cam_op.Close_device()
    cv2.destroyAllWindows()
    print("Đã đóng chương trình.")

if __name__ == "__main__":
    main()
