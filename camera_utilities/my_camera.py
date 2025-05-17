# camera_controller/my_camera.py

from .CameraConnectStream_Class import CameraOperation
from .MvCameraControl_class import MvCamera
from .CameraParams_const import MV_GIGE_DEVICE, MV_USB_DEVICE
from .CameraParams_header import MV_CC_DEVICE_INFO_LIST

class MyCamera:
    def __init__(self):
        self.device_list = MV_CC_DEVICE_INFO_LIST()
        self.cam = MvCamera()
        self.cam_op = None

    def connect(self, index=0):
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0 or self.device_list.nDeviceNum == 0:
            raise RuntimeError("Không tìm thấy camera.")
        self.cam_op = CameraOperation(self.cam, self.device_list, n_connect_num=index)
        if self.cam_op.Open_device() != 0:
            raise RuntimeError("Không mở được camera.")

        # Auto settings
        self.cam_op.obj_cam.MV_CC_SetEnumValue("ExposureAuto", 2)
        self.cam_op.obj_cam.MV_CC_SetEnumValue("GainAuto", 2)
        self.cam_op.obj_cam.MV_CC_SetEnumValue("BalanceWhiteAuto", 1)

        self.cam_op.Start_grabbing()

    def get_frame(self):
        return self.cam_op.Export_image()

    def release(self):
        self.cam_op.Stop_grabbing()
        self.cam_op.Close_device()
