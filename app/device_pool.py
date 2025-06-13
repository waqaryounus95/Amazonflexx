# import threading

# class DevicePool:
#     def __init__(self):
#         self.lock = threading.Lock()
#         self.devices = [
#             {
#                 'device_name': 'Techno', 
#                 'udid' : '097875438E100893',
#                 # 'udid': '192.168.18.31:5555',
#                 'platform_version': '13', 
#                 'appium_server_url': 'http://127.0.0.1:4723/wd/hub',
#                 'in_use': False
#             }
#             # {
#             #     'device_name': 'Pixel',
#             #     'udid': '192.168.18.86:5556', 
#             #     'platform_version': '14',
#             #     'appium_server_url': 'http://127.0.0.1:4724/wd/hub',
#             #     'in_use': False
#             # }
#         ]

#     def assign_device(self):
#         """Assign an available device from the pool with thread safety."""
#         with self.lock:
#             for device in self.devices:
#                 if not device['in_use']:
#                     device['in_use'] = True
#                     return device.copy() 
#             return None

#     def release_device(self, device_name):
#         """Release a device back to the pool with thread safety."""
#         with self.lock:
#             for device in self.devices:
#                 if device['device_name'] == device_name:
#                     device['in_use'] = False
#                     break

# # Create a global instance
# device_pool = DevicePool()
# assign_device = device_pool.assign_device
# release_device = device_pool.release_device


import threading
import os

class DevicePool:
    def __init__(self):
        self.lock = threading.Lock()
        self.devices = []

        # Read number of devices from .env (default to 1)
        num_devices = int(os.getenv('NUM_DEVICES', '1'))

        for i in range(1, num_devices + 1):
            device_name = os.getenv(f'DEVICE_{i}_NAME')
            udid = os.getenv(f'DEVICE_{i}_UDID')
            platform_version = os.getenv(f'DEVICE_{i}_PLATFORM_VERSION')

            # Appium server URL pattern:
            appium_server_url = f'http://appium{i}:4723/wd/hub'

            if device_name and udid and platform_version:
                device = {
                    'device_name': device_name,
                    'udid': udid,
                    'platform_version': platform_version,
                    'appium_server_url': appium_server_url,
                    'in_use': False
                }
                self.devices.append(device)

    def assign_device(self):
        """Assign an available device from the pool with thread safety."""
        with self.lock:
            for device in self.devices:
                if not device['in_use']:
                    device['in_use'] = True
                    return device.copy()
            return None

    def release_device(self, device_name):
        """Release a device back to the pool with thread safety."""
        with self.lock:
            for device in self.devices:
                if device['device_name'] == device_name:
                    device['in_use'] = False
                    break

# Global instance
device_pool = DevicePool()
assign_device = device_pool.assign_device
release_device = device_pool.release_device
