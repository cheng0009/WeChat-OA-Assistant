"""
授权验证核心模块
功能：机器指纹生成、授权验证、签名校验、反调试检测
"""
import os
import sys
import json
import hmac
import hashlib
import base64
import ctypes
import platform
import uuid
import subprocess
import gc
import atexit
from datetime import datetime
from pathlib import Path

LICENSE_FILENAME = "license.dat"
DEFAULT_MAX_DEVICES = 3
DEFAULT_EXPIRE_DAYS = 365


def get_license_path() -> str:
    """获取授权文件路径（exe同目录或当前目录）"""
    # 获取exe所在目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 优先查找exe同目录
    exe_path = os.path.join(exe_dir, LICENSE_FILENAME)
    if os.path.exists(exe_path):
        return exe_path
    
    # 其次查找当前目录
    cur_path = os.path.join(os.getcwd(), LICENSE_FILENAME)
    if os.path.exists(cur_path):
        return cur_path
    
    return LICENSE_FILENAME

try:
    import _winreg as winreg
except ImportError:
    import winreg

class LicenseCheckError(Exception):
    """授权验证错误"""
    pass

class MachineFingerprint:
    """机器指纹生成器"""
    
    @staticmethod
    def _get_cpu_id() -> str:
        """获取CPU ID"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'ProcessorId'],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:
                    cpu_id = line.strip()
                    if cpu_id:
                        return cpu_id
        except:
            pass
        return ""
    
    @staticmethod
    def _get_baseboard_serial() -> str:
        """获取主板序列号"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['wmic', 'baseboard', 'get', 'SerialNumber'],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:
                    serial = line.strip()
                    if serial and serial != "To be filled by O.E.M.":
                        return serial
        except:
            pass
        return ""
    
    @staticmethod
    def _get_disk_serial() -> str:
        """获取磁盘序列号"""
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ['wmic', 'diskdrive', 'get', 'SerialNumber'],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:
                    serial = line.strip()
                    if serial:
                        return serial
        except:
            pass
        return ""
    
    @staticmethod
    def _get_mac_address() -> str:
        """获取MAC地址"""
        mac = uuid.UUID(int=uuid.getnode()).hex[-12:]
        return ':'.join([mac[i:i+2] for i in range(0, 12, 2)])
    
    @classmethod
    def get_fingerprint(cls) -> str:
        """生成机器指纹"""
        identifiers = []
        
        cpu_id = cls._get_cpu_id()
        if cpu_id:
            identifiers.append(cpu_id)
        
        board_serial = cls._get_baseboard_serial()
        if board_serial:
            identifiers.append(board_serial)
        
        disk_serial = cls._get_disk_serial()
        if disk_serial:
            identifiers.append(disk_serial)
        
        mac = cls._get_mac_address()
        identifiers.append(mac)
        
        combined = '|'.join(identifiers)
        fingerprint = hashlib.sha256(combined.encode('utf-8')).hexdigest()
        return fingerprint[:32]
    
    @classmethod
    def get_simple_fingerprint(cls) -> str:
        """简化指纹 (仅MAC)"""
        return cls._get_mac_address().replace(':', '').upper()[:12]


class LicenseSigner:
    """授权签名器"""
    
    def __init__(self, secret_key: bytes = None):
        if secret_key is None:
            secret_key = self._load_or_create_key()
        self.secret_key = secret_key
    
    def _load_or_create_key(self) -> bytes:
        """加载或创建密钥"""
        # 优先使用构建时嵌入的密钥（打包进 exe 内部）
        try:
            from _secret import EMBEDDED_KEY
            if EMBEDDED_KEY:
                return EMBEDDED_KEY
        except (ImportError, AttributeError):
            pass

        key_file = Path("SECURITY_KEY.dat")
        if key_file.exists():
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            key = os.urandom(64)
            with open(key_file, 'wb') as f:
                f.write(key)
            return key
    
    def sign(self, data: dict) -> str:
        """签名"""
        data_copy = {k: v for k, v in data.items() if k != 'signature'}
        json_str = json.dumps(data_copy, sort_keys=True, ensure_ascii=False)
        signature = hmac.new(self.secret_key, json_str.encode('utf-8'), hashlib.sha256).digest()
        return base64.b64encode(signature).decode('utf-8')
    
    def verify(self, data: dict) -> bool:
        """验证签名"""
        if 'signature' not in data:
            return False
        expected_signature = self.sign(data)
        return hmac.compare_digest(expected_signature, data['signature'])


class AntiDebug:
    """反调试/反破解"""
    
    @staticmethod
    def check_debugger() -> bool:
        """检测调试器"""
        if platform.system() == "Windows":
            kernel32 = ctypes.windll.kernel32
            if kernel32.IsDebuggerPresent():
                return True
            is_debugged = ctypes.c_bool(False)
            kernel32.CheckRemoteDebuggerPresent(ctypes.c_void_p(-1), ctypes.byref(is_debugged))
            if is_debugged.value:
                return True
        return False
    
    @staticmethod
    def check_vm() -> bool:
        """检测虚拟机"""
        indicators = ['vmware', 'virtualbox', 'qemu', 'kvm', 'xen', 'parallels']
        try:
            result = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=5)
            for indicator in indicators:
                if indicator in result.stdout.lower():
                    return True
        except:
            pass
        
        mac = uuid.UUID(int=uuid.getnode()).hex[-12:]
        vm_macs = ['000569', '080027', '000C29', '001C42', '001DD8']
        mac_prefix = mac[:6].upper()
        if mac_prefix in vm_macs:
            return True
        
        return False
    
    @staticmethod
    def check_dumper() -> bool:
        """检测内存 dump 工具"""
        indicators = ['processhacker', 'procmon', 'filemon', 'regmon', 'ollydbg', 'x64dbg', 'ida']
        try:
            result = subprocess.run(['tasklist'], capture_output=True, text=True, timeout=5)
            for indicator in indicators:
                if indicator.lower() in result.stdout.lower():
                    return True
        except:
            pass
        return False


class LicenseValidator:
    """授权验证器"""
    
    def __init__(self, secret_key: bytes = None):
        self.signer = LicenseSigner(secret_key)
        self.fingerprint = MachineFingerprint.get_fingerprint()
        self.simple_fingerprint = MachineFingerprint.get_simple_fingerprint()
    
    def load_license(self, custom_path: str = None) -> dict:
        """加载授权文件"""
        path = custom_path or LICENSE_FILENAME
        if not os.path.exists(path):
            raise LicenseCheckError("授权文件不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                raise LicenseCheckError("授权文件格式错误")
        
        return data
    
    def validate(self, data: dict) -> tuple:
        """
        验证授权
        Returns: (is_valid, message)
        """
        if not self.signer.verify(data):
            return False, "签名验证失败，授权可能被篡改"
        
        expires_at = data.get('expires_at', '')
        if expires_at:
            try:
                expire_date = datetime.strptime(expires_at, '%Y-%m-%d')
                if expire_date < datetime.now():
                    return False, f"授权已过期 (过期时间: {expires_at})"
            except ValueError:
                pass
        
        machine_code = data.get('machine_code', '')
        registered_devices = data.get('registered_devices', [])
        max_devices = data.get('max_devices', DEFAULT_MAX_DEVICES)
        
        current_machine = self.fingerprint
        
        if machine_code and machine_code == current_machine:
            return True, "授权验证成功"
        
        if current_machine in registered_devices:
            return True, "授权验证成功"
        
        if not registered_devices:
            if not machine_code:
                return True, "首次注册，授权已激活"
            return False, "机器未授权"
        
        if len(registered_devices) >= max_devices:
            return False, f"已达最大设备数量 ({max_devices}台)"
        
        registered_devices.append(current_machine)
        data['registered_devices'] = registered_devices
        data['signature'] = self.signer.sign(data)
        
        with open(LICENSE_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return True, f"新设备已注册 ({len(registered_devices)}/{max_devices})"
    
    def register_new_machine(self, data: dict) -> dict:
        """注册新机器"""
        current_machine = self.fingerprint
        registered_devices = data.get('registered_devices', [])
        max_devices = data.get('max_devices', DEFAULT_MAX_DEVICES)
        
        if current_machine in registered_devices:
            return data
        
        if len(registered_devices) >= max_devices:
            raise LicenseCheckError(f"已达最大设备数量 ({max_devices}台)")
        
        registered_devices.append(current_machine)
        data['registered_devices'] = registered_devices
        data['signature'] = self.signer.sign(data)
        
        return data


class LicenseManager:
    """授权管理器"""
    
    def __init__(self, secret_key: bytes = None):
        self.signer = LicenseSigner(secret_key)
    
    def generate_license(
        self,
        user_name: str,
        user_contact: str = "",
        machine_code: str = "",
        expire_days: int = DEFAULT_EXPIRE_DAYS,
        max_devices: int = DEFAULT_MAX_DEVICES,
        features: list = None
    ) -> dict:
        """生成授权文件"""
        issued_at = datetime.now().strftime('%Y-%m-%d')
        expires_at = (datetime.now() + timedelta(days=expire_days)).strftime('%Y-%m-%d')
        
        license_id = f"LIC-{user_name.upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        data = {
            "license_id": license_id,
            "user_name": user_name,
            "user_contact": user_contact,
            "machine_code": machine_code,
            "registered_devices": [machine_code] if machine_code else [],
            "expires_at": expires_at,
            "issued_at": issued_at,
            "max_devices": max_devices,
            "features": features or ["all"],
            "version": "1.0"
        }
        
        data['signature'] = self.signer.sign(data)
        
        return data
    
    def save_license(self, data: dict, filepath: str = None) -> str:
        """保存授权文件"""
        filename = filepath or f"license_{data.get('user_name', 'user')}.dat"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return filename
    
    def load_license(self, filepath: str) -> dict:
        """加载授权文件"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)


from datetime import timedelta


def get_current_machine_code() -> str:
    """获取当前机器的机器码"""
    return MachineFingerprint.get_fingerprint()


def verify_license(license_path: str = None) -> tuple:
    """
    验证授权 (简化接口)
    Returns: (is_valid, message)
    """
    if license_path is None:
        license_path = get_license_path()
    validator = LicenseValidator()
    data = validator.load_license(license_path)
    return validator.validate(data)


def check_license_with_exit(license_path: str = None) -> bool:
    """验证授权，失败则退出"""
    try:
        is_valid, message = verify_license(license_path)
        if not is_valid:
            print(f"授权验证失败: {message}")
            print("请获取有效授权后重新运行程序")
            input("\n按回车键退出...")
            sys.exit(1)
    except LicenseCheckError as e:
        _show_license_prompt(e)
        sys.exit(1)
    return True


def _show_license_prompt(error: LicenseCheckError):
    """显示授权缺失提示（控制台 + 弹窗），内含机器码供用户复制"""
    machine_code = MachineFingerprint.get_fingerprint()
    simple_code = MachineFingerprint.get_simple_fingerprint()

    print()
    print("=" * 56)
    print("   授权文件未找到 — 请获取授权后重试")
    print("=" * 56)
    print(f"\n错误: {error}")
    print(f"\n■ 机器指纹（完整码）:")
    print(f"  {machine_code}")
    print(f"\n■ 简化机器码:")
    print(f"  {simple_code}")
    print()
    print("请将以上机器码发送给开发者，")
    print("将收到的 license.dat 放到本程序同目录后重新运行。")
    print()

    # 同时将机器码写入同目录文件，方便用户复制
    try:
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
        info_path = os.path.join(exe_dir, "machine_code.txt")
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(f"机器指纹: {machine_code}\n")
            f.write(f"简化机器码: {simple_code}\n")
        print(f"机器码已保存到同目录: {info_path}")
    except Exception:
        pass

    # Windows 弹窗提示
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"授权文件 (license.dat) 未找到。\n\n"
            f"机器指纹:\n{machine_code}\n\n"
            f"简化码: {simple_code}\n\n"
            f"请将此机器码发给开发者获取授权。\n"
            f"（机器码已保存到同目录 machine_code.txt）",
            "授权验证",
            0,
        )
    except Exception:
        pass

    input("\n按回车键退出...")


def secure_start(license_path: str = None, enable_anti_debug: bool = True):
    """安全启动"""
    if enable_anti_debug:
        if AntiDebug.check_debugger():
            sys.exit("检测到调试器，程序终止")
        if AntiDebug.check_vm():
            sys.exit("检测到虚拟机，程序终止")
        if AntiDebug.check_dumper():
            sys.exit("检测到分析工具，程序终止")
    
    atexit.register(lambda: gc.collect())
    
    if license_path or os.path.exists(LICENSE_FILENAME):
        check_license_with_exit(license_path)


if __name__ == "__main__":
    print("=" * 50)
    print("授权验证系统 - 工具")
    print("=" * 50)
    print()
    
    choice = input("选择操作:\n1. 查看当前机器码\n2. 验证授权文件\n3. 生成授权文件\n\n请输入 (1/2/3): ").strip()
    
    if choice == "1":
        print(f"\n机器指纹: {MachineFingerprint.get_fingerprint()}")
        print(f"简化码: {MachineFingerprint.get_simple_fingerprint()}")
    
    elif choice == "2":
        path = input("\n授权文件路径 (直接回车使用默认): ").strip()
        if not path:
            path = None
        try:
            is_valid, msg = verify_license(path)
            print(f"\n验证结果: {'通过' if is_valid else '失败'}")
            print(f"详细信息: {msg}")
        except LicenseCheckError as e:
            print(f"\n错误: {e}")
    
    elif choice == "3":
        from license_manager import create_gui
        create_gui()
    
    input("\n按回车键退出...")