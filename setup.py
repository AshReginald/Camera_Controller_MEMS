from setuptools import setup, find_packages

setup(
    name="camera_controller",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "opencv-python",
        "numpy"
    ],
    author="Your Name",
    description="Simple wrapper for controlling industrial camera",
)
