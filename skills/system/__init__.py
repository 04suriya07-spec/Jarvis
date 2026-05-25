"""Ubuntu/Linux system skills — WiFi, Bluetooth, Audio, Notifications, Brightness."""

from skills.system.wifi import WiFiSkill
from skills.system.bluetooth import BluetoothSkill
from skills.system.audio import AudioSkill
from skills.system.notify import NotifySkill
from skills.system.brightness import BrightnessSkill

__all__ = ["WiFiSkill", "BluetoothSkill", "AudioSkill", "NotifySkill", "BrightnessSkill"]
