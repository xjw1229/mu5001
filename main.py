import flet as ft
import httpx
import hashlib
import base64
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Set, Callable, Union
from enum import Enum

# ==========================================
# 日志配置
# 1. 输出到控制台
# 2. 日志格式包含进程号、模块名、行号，便于定位
# 3. DEBUG_MODE 开关控制调试日志输出
# 4. 避免重复日志刷屏
# ==========================================
DEBUG_MODE = False # 调试时设为 True 或 False 可开关输出完整调试信息
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO
logger = logging.getLogger("MU5001")
logger.setLevel(LOG_LEVEL)
logger.handlers.clear()
logger.propagate = False

# 控制台输出
console_handler = logging.StreamHandler()
console_handler.setLevel(LOG_LEVEL)
# 日志格式：时间 - 进程 - 日志名 - 级别 - 模块:行号 - 消息
formatter = logging.Formatter(
    "%(asctime)s - %(process)d - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ==========================================
# 全局配置 (可在此处集中自定义颜色)
# ==========================================
class ThemeColors:
    # 页面底色
    DARK_PAGE_BG = "#171920"          # 深色页面主背景
    LIGHT_PAGE_BG = "#F6F8FB"         # 浅色页面主背景

    # 深色主题
    DARK_SCHEME = {
        "surface": "#40425C",                   # 卡片容器背景
        "surface_container_highest": "#36394F", # 输入框、下拉框、设备列表背景
        "on_surface": "#FFFFFF",                # 主要文本颜色
        "on_surface_variant": "#C0C5D8",        # 次要文本、提示文本颜色
        "inverse_primary": "#FFF9F2",           # 开关旁辅助说明文字
        "primary": "#82A5E0",                   # 激活色（勾选框、开关，功能切换）
        "error": "#E08282",                     # 错误状态文本颜色
        "outline_variant": "#2A2C3E",           # 页面分割线颜色
        "secondary_container": "#535773",       # 普通按钮默认背景
        "secondary": "#6A6F91",                 # 普通按钮悬停背景
        "tertiary_container": "#2D4A3E",        # 成功提示背景
        "error_container": "#5C2D2D"            # 失败提示背景
    }

    # 浅色主题
    LIGHT_SCHEME = {
        "surface": "#FFFFFF",                   # 卡片容器背景
        "surface_container_highest": "#EEF3F8", # 输入框、下拉框、设备列表背景
        "on_surface": "#000000",                # 主要文本颜色
        "on_surface_variant": "#5F6B7A",        # 次要文本、提示文本颜色
        "inverse_primary": "#1A1A1A",           # 开关旁辅助说明文字
        "primary": "#D76F88",                   # 激活色（勾选框、开关，功能切换）
        "error": "#D64545",                     # 错误状态文本颜色
        "outline_variant": "#DDE4EC",           # 页面分割线颜色
        "secondary_container": "#D7E2EE",       # 普通按钮默认背景
        "secondary": "#B5C6D8",                 # 普通按钮悬停背景
        "tertiary_container": "#DDF3E9",        # 成功提示背景
        "error_container": "#FFE0DD"            # 失败提示背景
    }

# WiFi 双频状态配置
class WiFiMode(str, Enum):
    MERGED = "merged"
    SEPARATED = "separated"

# 超时与间隔配置（单位：秒、次）
API_TIMEOUT = 5               # 普通 API 请求超时
LOGIN_TIMEOUT = 3             # 登录相关请求超时
AUTO_REFRESH_INTERVAL = 1     # 实时数据自动刷新间隔
OFFLINE_FAIL_THRESHOLD = 3     # 连续3次失败后才显示断网
NET_SWITCH_DELAY = 0.5        # 网络断连/重连等待时间

# 网络模式映射：界面显示名 <-> 设备读写参数
NET_CONFIG = {
    "5G/4G/3G": {"write_val": "WL_AND_5G",     "read_val": "WL_AND_5G"},
    "NSA":      {"write_val": "LTE_AND_5G",    "read_val": "LTE_AND_5G"},
    "SA":       {"write_val": "Only_5G",       "read_val": "ONLY_5G"},
    "4G/3G":    {"write_val": "WCDMA_AND_LTE", "read_val": "WCDMA_AND_LTE"},
    "4G":       {"write_val": "Only_LTE",      "read_val": "ONLY_LTE"},
    "3G":       {"write_val": "Only_WCDMA",    "read_val": "ONLY_WCDMA"}
}

# 设备支持的频段列表
LTE_BANDS = ["1","3","4","5","7","8","12","17","34","39","40","41"]
NR_SA_BANDS = ["1","3","28","41","78"]
NR_NSA_BANDS = ["28","41","78"]

# 设备默认参数
DEFAULT_IP = "192.168.0.1"
API_KEY_WRITE = "BearerPreference"  # 写入网络模式的字段名
API_KEY_READ = "net_select"         # 读取网络模式的字段名

# 运营商 PLMN 常量
CMCC_PLMNS = frozenset({"46000", "46002", "46004", "46007", "46008", "46015"})
CU_CT_PLMNS = frozenset({"46001", "46003", "46006", "46009", "46011"})
CMCC_KEYS = frozenset({"移动", "中国移动", "中移", "MOBILE", "CMCC", "CHINA MOBILE", "广电", "中国广电", "CBN"})

# ==========================================
# 工具函数
# ==========================================

# 计算字符串的 MD5 哈希（小写 32 位）
def get_md5(text: str) -> str:
    result = hashlib.md5(text.encode('utf-8')).hexdigest().lower()
    logger.debug(f"MD5 计算完成，输入长度={len(text)}")
    return result

# 计算字符串的 SHA256 哈希（大写 64 位）
def get_sha256_upper(text: str) -> str:
    result = hashlib.sha256(text.encode('utf-8')).hexdigest().upper()
    logger.debug(f"SHA256 计算完成，输入长度={len(text)}")
    return result

# 计算设备接口鉴权所需的 AD 值，算法：MD5( MD5(rd0 + rd1) + rd_value )
def calculate_ad(rd0: str, rd1: str, rd_value: str) -> str:
    logger.debug("开始计算 AD 鉴权值")
    step1 = get_md5(rd0 + rd1)
    ad = get_md5(step1 + rd_value)
    logger.debug("AD 值计算完成")
    return ad

# 规范化设备管理地址
# 兼容纯IP、http、https 输入，自动去除末尾斜杠
# 注：设备 goform 接口仅支持 HTTP，输入 HTTPS 自动降级为 HTTP 以保证可用性
def normalize_base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        return DEFAULT_IP
    # 统一转为小写，匹配协议
    url_lower = url.lower()
    if url_lower.startswith("https://"):
        # HTTPS 自动降级为 HTTP，设备接口不支持 HTTPS
        url = "http://" + url[8:]
    elif not url_lower.startswith("http://"):
        # 无协议自动补全 HTTP
        url = "http://" + url
    return url

# 网速显示单位（B/KB/MB/GB/TB），保留两位小数
def format_bytes(size: Union[int, float, str]) -> str:
    try:
        size = float(size)
    except (ValueError, TypeError) as e:
        logger.warning(f"字节格式化失败，输入={size}, 错误={e}")
        return "0 B"
    if size <= 0:
        return "0 B"
    labels = ['B', 'KB', 'MB', 'GB', 'TB']
    n = 0
    while size >= 1024 and n < len(labels) - 1:
        size /= 1024
        n += 1
    return f"{size:.2f} {labels[n]}"

# 流量使用情况查询失败返回0值
def safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

# 将 LTE 频段列表转换为设备识别的十六进制掩码
def lte_bands_to_mask(bands: List[str]) -> str:
    mask = 0
    for b in bands:
        try:
            mask |= 1 << (int(b) - 1)
        except ValueError:
            logger.warning(f"忽略无效 LTE 频段: {b}")
    result = f"0x{mask:010x}"
    logger.debug(f"LTE 频段转掩码: {bands} -> {result}")
    return result

# 将十六进制掩码还原为 LTE 频段列表
def mask_to_lte_bands(mask_str: str) -> List[str]:
    try:
        mask = int(mask_str, 16)
    except (ValueError, TypeError) as e:
        logger.error(f"掩码解析失败: {mask_str}, {e}")
        return []
    bands = [str(i + 1) for i in range(64) if mask & (1 << i)]
    logger.debug(f"掩码转 LTE 频段: {mask_str} -> {bands}")
    return bands

# ==========================================
# API 客户端封装
# ==========================================

# 设备连接状态数据类，在 UI 与 API 客户端之间共享
class DeviceState:
    client: Optional[httpx.AsyncClient] = None   # httpx 异步客户端实例
    ip: str = ""                                 # 设备管理地址
    rd0: str = ""                                # 设备内部版本号
    rd1: str = ""                                # 设备固件版本号
    password: str = ""                           # 明文管理员密码
    dev_unlocked: bool = False                   # 开发者模式是否解锁

# 数据模型
@dataclass
class RealtimeStatus:
    network_type: str
    provider: str
    battery_percent: str
    is_charging: bool
    wan_ip: str
    imei: str
    imsi: str
    conn_time_sec: int
    tx_speed: float
    rx_speed: float
    tx_bytes_rt: float
    rx_bytes_rt: float
    tx_bytes_mo: float
    rx_bytes_mo: float
    macs_count: int
    arfcn: str
    pci_5g: str
    pci_4g: str
    rsrp_5g: str
    rsrp_4g: str
    rsrq_5g: str
    rsrq_4g: str
    sinr_5g: str
    sinr_4g: str
    rssi_5g: str
    rssi_4g: str
    cell_id_5g: str
    cell_id_4g: str
    mcc_mnc: str
    temp_bat: str
    temp_mdm: str
    temp_pa: str
    is_data_connected: bool
    active_band_5g: str
    active_band_4g: str
    connected_devices: list
    blacklisted_devices: list

# 封装设备登录、配置读写、状态查询等所有 HTTP 交互，自动维护会话 Cookie 与 AD 鉴权计算。
class MU5001Client:
    # 初始化客户端，state 为外部共享的设备状态实例
    def __init__(self, state: DeviceState):
        self.state = state
        # 异步锁（Async Lock）机制
        self._request_lock = asyncio.Lock()
        logger.debug("MU5001Client 实例已创建")

    # 拼接设备 IP 与接口路径，返回完整 URL
    def _build_url(self, path: str) -> str:
        return f"{self.state.ip}/{path}"

    # 安全关闭 HTTP 客户端，释放连接池资源
    async def close(self):
        if self.state.client:
            logger.debug("关闭 HTTP 客户端连接池")
            await self.state.client.aclose()
            self.state.client = None

    # 异步 GET 查询设备配置，cmd 支持逗号分隔多命令，multi_data 启用多数据返回模式
    async def get_cmd(self, cmd: str, multi_data: bool = False) -> Dict:
        # 移除互斥锁，允许 GET 请求高并发，不再排队等待，大幅提升刷新丝滑度
        return await self._get_cmd_unlocked(cmd, multi_data)

    async def _get_cmd_unlocked(self, cmd: str, multi_data: bool = False) -> Dict:
        if not self.state.client:
            raise RuntimeError("未登录设备，无法执行 GET 请求")
        params = {"isTest": "false", "cmd": cmd}
        if multi_data:
            params["multi_data"] = "1"
        logger.debug(f"GET cmd: {cmd[:80]}...")
        try:
            resp = await self.state.client.get(
                self._build_url("goform/goform_get_cmd_process"),
                params=params,
                timeout=API_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"GET 成功: {cmd[:50]}")
            return data
        except httpx.TimeoutException:
            logger.error(f"GET 超时: {cmd}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"GET HTTP {e.response.status_code}: {cmd}")
            raise
        except Exception as e:
            logger.error(f"GET 异常: {cmd}, {type(e).__name__}: {e}", exc_info=DEBUG_MODE)
            raise

    # 异步 POST 设置设备配置，自动计算 AD 鉴权
    # goform_id 为操作标识，params 为业务参数
    async def post_cmd(self, goform_id: str, params: Dict = None) -> bool:
        async with self._request_lock:
            return await self._post_cmd_unlocked(goform_id, params)

    async def _post_cmd_unlocked(self, goform_id: str, params: Dict = None) -> bool:
        if not self.state.client:
            raise RuntimeError("未登录设备，无法执行 POST 请求")
        params = params or {}
        logger.debug(f"POST goformId={goform_id}, params={params}")
        try:
            # 重新获取 RD 并计算 AD
            rd_res = await self._get_cmd_unlocked("RD")
            rd_val = rd_res.get("RD", "")
            ad = calculate_ad(self.state.rd0, self.state.rd1, rd_val)
            payload = {"isTest": "false", "goformId": goform_id, "AD": ad}
            payload.update(params)
            resp = await self.state.client.post(
                self._build_url("goform/goform_set_cmd_process"),
                data=payload,
                timeout=API_TIMEOUT
            )
            resp.raise_for_status()
            result = str(resp.json().get("result", "")).strip()
            # 消除魔术字符串：将成功状态码统一定义为一个集合
            SUCCESS_CODES = {"0", "success", "4"}
            success = result in SUCCESS_CODES
            if success:
                logger.info(f"POST 成功: {goform_id}")
            else:
                logger.warning(f"POST 返回失败: {goform_id}, result={result}")
            return success
        except Exception as e:
            logger.error(f"POST 异常: {goform_id}, {type(e).__name__}: {e}", exc_info=DEBUG_MODE)
            raise

    # 异步设置 WiFi 覆盖范围
    async def set_wifi_coverage(self, coverage_val: str) -> bool:
        return await self.post_cmd("setWiFiCoverage", {"WiFiCoverage": coverage_val})

    # 设备列表
    async def get_device_access_control_list(self) -> Dict:
        try:
            return await self.get_cmd("queryDeviceAccessControlList")
        except Exception as e:
            logger.error(f"读取设备访问控制列表失败: {e}", exc_info=DEBUG_MODE)
            return {}

    def _split_acl_list(self, value: str) -> List[str]:
        return [item.strip() for item in str(value or "").split(";") if item.strip()]

    async def set_device_blacklist(self, devices: list) -> bool:
        macs = []
        names = []
        seen = set()
        for dev in devices:
            mac = str(dev.get("mac", "")).strip().upper()
            if not mac or mac in seen:
                continue
            seen.add(mac)
            macs.append(mac)
            names.append(str(dev.get("name", "")).strip() or mac)
        return await self.post_cmd("setDeviceAccessControlList", {
            "AclMode": "2",
            "WhiteMacList": "",
            "BlackMacList": ";".join(macs) + (";" if macs else ""),
            "WhiteNameList": "",
            "BlackNameList": ";".join(names) + (";" if names else "")
        })

    async def get_blacklisted_devices(self) -> list:
        acl = await self.get_device_access_control_list()
        macs = self._split_acl_list(acl.get("BlackMacList", ""))
        names = self._split_acl_list(acl.get("BlackNameList", ""))
        return [{"mac": mac.upper(), "name": names[i] if i < len(names) else mac.upper()} for i, mac in enumerate(macs)]

    async def block_device(self, mac: str, name: str) -> bool:
        devices = await self.get_blacklisted_devices()
        mac = str(mac or "").strip().upper()
        if not mac:
            return False
        for dev in devices:
            if dev.get("mac") == mac:
                return True
        devices.append({"mac": mac, "name": str(name or "").strip() or mac})
        return await self.set_device_blacklist(devices)

    async def unblock_device(self, mac: str) -> bool:
        mac = str(mac or "").strip().upper()
        devices = [dev for dev in await self.get_blacklisted_devices() if dev.get("mac") != mac]
        return await self.set_device_blacklist(devices)

    # WiFi 设置：切换双频合一/分离模式
    async def apply_wifi_mode(self, is_merged: bool) -> bool:
        target_lbd = "1" if is_merged else "0"
        switch_payload = {
            "SwitchOption": "1",       
            "wifi_lbd_enable": target_lbd     
        }
        try:
            async with self._request_lock:
                await self._post_cmd_unlocked("switchWiFiModule", switch_payload)
                return True
        except Exception as e:
            logger.warning(f"切换 WiFi 模式时断网 (预期现象): {e}")
            return True

    # WiFi 设置：修改 SSID 广播状态
    async def apply_wifi_broadcast(self, is_merged: bool, broadcast_merged: bool, broadcast_24g: bool, broadcast_5g: bool) -> bool:
        try:
            async with self._request_lock:
                ap_info = await self._get_cmd_unlocked("queryAccessPointInfo")
                chip_payload = {
                    "ChipIndex": "9",
                    "AccessPointIndex": "0",
                    "QrImageShow": "1",
                    "QrImageShow_5G": "1",
                    "wifi_syncparas_flag": "0"
                }
                
                if ap_info and "ResponseList" in ap_info:
                    for ap in ap_info["ResponseList"]:
                        if ap.get("AccessPointIndex") != "0": 
                            continue
                        c_idx = ap.get("ChipIndex")
                        if c_idx == "0": 
                            chip_payload["AccessPointSwitchStatus"] = ap.get("AccessPointSwitchStatus", "1")
                            chip_payload["SSID"] = ap.get("SSID", "")
                            chip_payload["ApIsolate"] = ap.get("ApIsolate", "0")
                            chip_payload["AuthMode"] = ap.get("AuthMode", "")
                            chip_payload["EncrypType"] = ap.get("EncrypType", "")
                        elif c_idx == "1": 
                            chip_payload["AccessPointSwitchStatus_5G"] = ap.get("AccessPointSwitchStatus", "1")
                            chip_payload["SSID_5G"] = ap.get("SSID", "")
                            chip_payload["ApIsolate_5G"] = ap.get("ApIsolate", "0")
                            chip_payload["AuthMode_5G"] = ap.get("AuthMode", "")
                            chip_payload["EncrypType_5G"] = ap.get("EncrypType", "")
                
                if is_merged:
                    val = "0" if broadcast_merged else "1"
                    chip_payload["ApBroadcastDisabled"] = val
                    chip_payload["ApBroadcastDisabled_5G"] = val
                else:
                    chip_payload["ApBroadcastDisabled"] = "0" if broadcast_24g else "1"
                    chip_payload["ApBroadcastDisabled_5G"] = "0" if broadcast_5g else "1"

                await self._post_cmd_unlocked("setAccessPointInfo_24G_5G_ALL", chip_payload)
                return True
        except Exception as e:
            logger.error(f"下发 SSID 广播状态时断网 (预期现象): {e}")
            return True

    async def apply_wifi_detail(self, is_merged: bool, detail_24g: Dict, detail_5g: Dict, sync_to_5g: bool = False) -> bool:
        def enc_pwd(value: str) -> str:
            return base64.b64encode((value or "").encode("utf-8")).decode("ascii")

        if is_merged:
            detail_5g = dict(detail_24g)
        elif sync_to_5g:
            detail_5g = dict(detail_24g, ssid=detail_5g.get("ssid", ""))

        payload = {
            "ChipIndex": "9",
            "AccessPointIndex": "0",
            "QrImageShow": "1",
            "QrImageShow_5G": "1",
            "wifi_syncparas_flag": "1" if sync_to_5g else "0",
            "AccessPointSwitchStatus": "1",
            "SSID": detail_24g.get("ssid", ""),
            "ApIsolate": "1" if detail_24g.get("isolate") else "0",
            "AuthMode": detail_24g.get("auth", "WPA2PSK"),
            "ApBroadcastDisabled": "0" if detail_24g.get("broadcast") else "1",
            "EncrypType": detail_24g.get("encryp", "CCMP"),
            "Password": enc_pwd(detail_24g.get("password", "")),
            "AccessPointSwitchStatus_5G": "1",
            "SSID_5G": detail_5g.get("ssid", ""),
            "ApIsolate_5G": "1" if detail_5g.get("isolate") else "0",
            "AuthMode_5G": detail_5g.get("auth", "WPA2PSK"),
            "ApBroadcastDisabled_5G": "0" if detail_5g.get("broadcast") else "1",
            "EncrypType_5G": detail_5g.get("encryp", "CCMP"),
            "Password_5G": enc_pwd(detail_5g.get("password", "")),
        }
        try:
            await self.post_cmd("setAccessPointInfo_24G_5G_ALL", payload)
            return True
        except Exception as e:
            logger.error(f"下发 WiFi 详细设置时断网 (预期现象): {e}")
            return True

    # 异步设置定时重启规则
    async def set_reboot_schedule(self, enable: bool, mode: str, hr: str, min: str, buffer: str, weeks: list, interval: str) -> bool:
        payload = {
            "reboot_schedule_enable": "1" if enable else "0",
            "reboot_schedule_mode": mode,
            "reboot_hour1": hr.zfill(2),
            "reboot_hour2": hr.zfill(2),
            "reboot_min1": min.zfill(2),
            "reboot_min2": min.zfill(2),
            "reboot_timeframe_hours1": buffer.zfill(2),
            "reboot_timeframe_hours2": buffer.zfill(2),
            "reboot_dow": ",".join(weeks),
            "reboot_dod": interval
        }
        return await self.post_cmd("FIX_TIME_REBOOT_SCHEDULE", payload)

    # 异步设置 WiFi 休眠
    async def set_wifi_sleep(self, sleep_time: str) -> bool:
        return await self.post_cmd("SET_WIFI_SLEEP_INFO", {"sysIdleTimeToSleep": sleep_time})

    # 异步锁定 4G 频段
    async def set_lte_band_lock(self, bands: list) -> bool:
        return await self.post_cmd("BAND_SELECT", {
            "is_gw_band": "0", "gw_band_mask": "0",
            "is_lte_band": "1", "lte_band_mask": lte_bands_to_mask(bands)
        })

    # 异步锁定 5G SA 频段
    async def set_sa_band_lock(self, bands: list) -> bool:
        return await self.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
            "nr5g_band_mask": ",".join(sorted(bands, key=int)), "type": "0"
        })

    # 异步锁定 5G NSA 频段
    async def set_nsa_band_lock(self, bands: list) -> bool:
        return await self.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
            "nr5g_band_mask": ",".join(sorted(bands, key=int)), "type": "1"
        })

    # 异步锁定/解锁小区
    async def set_cell_lock(self, pci: str, earfcn: str, band: str, scs: str) -> bool:
        lock_val = f"{pci},{earfcn},{band},{scs}"
        return await self.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": lock_val})

    async def unlock_cell(self) -> bool:
        return await self.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": "1,1,1,1"})

    # 异步切换网络模式
    async def switch_net_mode(self, mode_val: str, was_connected: bool) -> bool:
        try:
            async with self._request_lock:
                await self._post_cmd_unlocked("DISCONNECT_NETWORK", {"notCallback": "true"})
                await asyncio.sleep(NET_SWITCH_DELAY)
                ok_set = await self._post_cmd_unlocked("SET_BEARER_PREFERENCE", {API_KEY_WRITE: mode_val})
                if was_connected:
                    await asyncio.sleep(NET_SWITCH_DELAY)
                    ok_connect = await self._post_cmd_unlocked("CONNECT_NETWORK", {"notCallback": "true"})
                    return ok_set and ok_connect
                return ok_set
        except Exception as e:
            logger.error(f"切换网络模式异常: {e}")
            return False

    # 获取设备 LD 值（登录密码加密盐），失败返回空串
    async def get_ld(self) -> str:
        try:
            res = await self.get_cmd("LD")
            return res.get("LD", "")
        except Exception:
            return ""

    # 解锁开发者模式（频段锁定、锁小区等高级功能依赖）
    async def unlock_developer(self) -> bool:
        logger.info("尝试解锁开发者模式")
        try:
            ld = await self.get_ld()
            if not ld:
                logger.warning("解锁开发者模式失败：LD 为空")
                return False
            pwd_enc = get_sha256_upper(
                get_sha256_upper(self.state.password) + ld
            )
            ok = await self.post_cmd("DEVELOPER_OPTION_LOGIN", {"password": pwd_enc})
            self.state.dev_unlocked = ok
            if ok:
                logger.info("开发者模式解锁成功")
            else:
                logger.warning("开发者模式解锁失败")
            return ok
        except Exception as e:
            logger.error(f"解锁开发者模式异常: {e}", exc_info=DEBUG_MODE)
            return False

    # 异步获取并清洗实时状态数据
    async def get_realtime_status(self) -> RealtimeStatus:
        cmd = (
            "battery_value,battery_charging,network_type,wan_ipaddr,imei,imsi,sim_imsi,Z5g_rsrp,Z5g_SINR,"
            "nr5g_pci,nr5g_action_channel,pm_sensor_mdm,battery_temp,pm_sensor_pa1,"
            "realtime_tx_thrpt,realtime_rx_thrpt,realtime_tx_bytes,realtime_rx_bytes,"
            "monthly_tx_bytes,monthly_rx_bytes,wan_active_band,nr5g_action_band,"
            "wan_active_channel,lte_pci,lte_rsrp,lte_snr,cell_id,Z5g_Cell_ID,"
            "nr5g_cell_id,network_provider,realtime_time,lte_rsrq,Z5g_rsrq,lte_rssi,"
            "Z5g_rssi,nr5g_rssi,ppp_status,mcc_mnc" 
        )
        res = await self.get_cmd(cmd, multi_data=True)
        
        macs_count = 0
        connected_devices = []
        blacklisted_devices = []
        macs = set()
        try:
            wifi_res = await self.get_cmd("station_list")
            lan_res = await self.get_cmd("lan_station_list")
            for d in wifi_res.get("station_list", []) + lan_res.get("lan_station_list", []):
                mac = d.get("mac_addr", "").strip().upper()
                if mac and mac not in macs:
                    macs.add(mac)
                    name = d.get("hostname", "").strip() or "未知设备"
                    ip = d.get("ip_addr", "").strip() or "未知 IP"
                    connected_devices.append({"name": name, "ip": ip, "mac": mac})
        except Exception:
            pass
        try:
            blacklisted_devices = await self.get_blacklisted_devices()
        except Exception:
            blacklisted_devices = []
        black_macs = {str(dev.get("mac", "")).upper() for dev in blacklisted_devices}
        macs_count = len(macs - black_macs)

        status_str = res.get("ppp_status", "").lower().replace("disconnected", "off")
        
        return RealtimeStatus(
            network_type=res.get('network_type', '?'),
            provider=str(res.get('network_provider', '')).upper(),
            battery_percent=str(res.get('battery_value', '?')),
            is_charging=str(res.get('battery_charging', '')) in ['1', '2'],
            wan_ip=res.get('wan_ipaddr', '未分配'),
            imei=str(res.get('imei', '')).strip(),
            imsi=str(res.get('sim_imsi', '') or res.get('imsi', '')).strip(),
            conn_time_sec=int(res.get("realtime_time", 0)) if str(res.get("realtime_time", 0)).isdigit() else 0,
            tx_speed=safe_float(res.get('realtime_tx_thrpt', 0)),
            rx_speed=safe_float(res.get('realtime_rx_thrpt', 0)),
            tx_bytes_rt=safe_float(res.get("realtime_tx_bytes")),
            rx_bytes_rt=safe_float(res.get("realtime_rx_bytes")),
            tx_bytes_mo=safe_float(res.get("monthly_tx_bytes")),
            rx_bytes_mo=safe_float(res.get("monthly_rx_bytes")),
            macs_count=macs_count,
            arfcn=str(res.get("nr5g_action_channel", "") or res.get("nr5g_arfcn", "") or res.get("Z5g_arfcn", "") or res.get("wan_active_channel", "")).strip(),
            pci_5g=str(res.get("nr5g_pci", "") or res.get("Z5g_pci", "")),
            pci_4g=str(res.get("lte_pci", "")),
            rsrp_5g=str(res.get('Z5g_rsrp', '') or res.get('nr5g_rsrp', '')).strip(),
            rsrp_4g=str(res.get('lte_rsrp', '')).strip(),
            rsrq_5g=str(res.get('Z5g_rsrq', '') or res.get('nr5g_rsrq', '')).strip(),
            rsrq_4g=str(res.get('lte_rsrq', '')).strip(),
            sinr_5g=str(res.get('Z5g_SINR', '') or res.get('Z5g_sinr', '') or res.get('nr5g_sinr', '')).strip(),
            sinr_4g=str(res.get('lte_snr', '') or res.get('lte_sinr', '')).strip(),
            rssi_5g=str(res.get('Z5g_rssi', '') or res.get('nr5g_rssi', '')).strip(),
            rssi_4g=str(res.get('lte_rssi', '')).strip(),
            cell_id_5g=str(res.get("nr5g_cell_id", "") or res.get("Z5g_Cell_ID", "")).strip(),
            cell_id_4g=str(res.get("cell_id", "")).strip(),
            mcc_mnc=str(res.get('mcc_mnc', '')).strip(),
            temp_bat=str(res.get('battery_temp', '--')),
            temp_mdm=str(res.get('pm_sensor_mdm', '--')),
            temp_pa=str(res.get('pm_sensor_pa1', '--')),
            is_data_connected="connected" in status_str,
            active_band_5g=str(res.get('nr5g_action_band', '')).strip(), 
            active_band_4g=str(res.get('wan_active_band', '')).strip(),
            connected_devices=connected_devices,
            blacklisted_devices=blacklisted_devices
        )
    async def login(self, ip: str, password: str) -> bool:
        logger.info(f"开始登录设备: {ip}")
        await self.close()

        # 规范化地址，兼容所有输入格式，HTTPS 自动降级为 HTTP
        base_url = normalize_base_url(ip)

        client = httpx.AsyncClient(
            http2=False,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"{base_url}/index.html"
            }
        )
        try:
            # 访问首页建立会话
            await client.get(f"{base_url}/index.html", timeout=LOGIN_TIMEOUT)
            # 并发获取三个关键参数
            req_ver = client.get(
                f"{base_url}/goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "Language,cr_version,wa_inner_version", "multi_data": "1"},
                timeout=LOGIN_TIMEOUT
            )
            req_ld = client.get(
                f"{base_url}/goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "LD"},
                timeout=LOGIN_TIMEOUT
            )
            req_rd = client.get(
                f"{base_url}/goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "RD"},
                timeout=LOGIN_TIMEOUT
            )
            ver_resp, ld_resp, rd_resp = await asyncio.gather(req_ver, req_ld, req_rd)
            ver = ver_resp.json()
            rd0 = ver.get("wa_inner_version", "")
            rd1 = ver.get("cr_version", "")
            ld = ld_resp.json().get("LD", "")
            rd_val = rd_resp.json()["RD"]
            logger.debug(f"登录参数就绪: rd0={rd0}, rd1={rd1}, ld_len={len(ld)}")
            # 计算密码与 AD 后登录
            pwd_enc = get_sha256_upper(get_sha256_upper(password) + ld)
            login_resp = await client.post(
                f"{base_url}/goform/goform_set_cmd_process",
                data={
                    "isTest": "false",
                    "goformId": "LOGIN",
                    "password": pwd_enc,
                    "AD": calculate_ad(rd0, rd1, rd_val)
                },
                timeout=LOGIN_TIMEOUT
            )
            resp_data = login_resp.json()
            result = str(resp_data.get("result", "")).strip()
            if result in ["0", "4"]:
                self.state.client = client
                self.state.ip = base_url
                self.state.rd0 = rd0
                self.state.rd1 = rd1
                self.state.password = password
                logger.info(f"登录成功: {base_url}")
                return True
            logger.warning(f"登录失败，result={result}")
            await client.aclose()
            return False
        except Exception as e:
            logger.error(f"登录异常: {type(e).__name__}: {e}", exc_info=DEBUG_MODE)
            await client.aclose()
            return False

# ==========================================
# UI 工具函数
# ==========================================

def create_text_field(label: str, value: str = "", **kwargs) -> ft.TextField:
    sec_style = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)
    return ft.TextField(
        label=label, value=value,
        color=ft.Colors.ON_SURFACE, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_color=ft.Colors.ON_SURFACE_VARIANT, focused_border_color=ft.Colors.PRIMARY,
        label_style=sec_style, hint_style=sec_style,
        **kwargs
    )

def create_checkbox(label: str, value: bool = False, on_change=None, **kwargs) -> ft.Checkbox:
    return ft.Checkbox(
        label=label, value=value, on_change=on_change,
        label_style=ft.TextStyle(color=ft.Colors.ON_SURFACE),
        fill_color={"selected": ft.Colors.PRIMARY, "": ft.Colors.SURFACE}, check_color=ft.Colors.SURFACE,
        **kwargs
    )

def create_dropdown(label: str, options: list, value: str, **kwargs) -> ft.Dropdown:
    sec_style = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)
    return ft.Dropdown(
        label=label, options=options, value=value,
        color=ft.Colors.ON_SURFACE, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_color=ft.Colors.ON_SURFACE_VARIANT, focused_border_color=ft.Colors.PRIMARY,
        label_style=sec_style, text_size=15, content_padding=ft.Padding(12, 10, 12, 10),
        **kwargs
    )

# 创建统一样式的主题按钮
def create_button(text: str, on_click: Callable, height: int = 48, expand: bool = False) -> ft.Control:
    BtnClass = getattr(ft, "Button", ft.ElevatedButton)
    btn = BtnClass(
        text, on_click=on_click, height=height,
        style=ft.ButtonStyle(
            color=ft.Colors.ON_SURFACE,
            bgcolor={"hovered": ft.Colors.SECONDARY, "": ft.Colors.SECONDARY_CONTAINER},
            elevation=0, text_style=ft.TextStyle(weight=ft.FontWeight.W_600)
        )
    )
    if expand: btn.expand = True
    return btn

# 在页面底部弹出浮动提示条
def show_toast(page: ft.Page, msg: str, success: bool = True) -> None:
    # 成功时调用 tertiary_container，失败时调用 error_container
    bg = ft.Colors.TERTIARY_CONTAINER if success else ft.Colors.ERROR_CONTAINER
    for c in list(page.overlay):
        if isinstance(c, ft.SnackBar):
            page.overlay.remove(c)
            
    snack = ft.SnackBar(
        content=ft.Text(msg, color=ft.Colors.ON_SURFACE, weight=ft.FontWeight.BOLD),
        bgcolor=bg,
        duration=3000, 
        behavior=ft.SnackBarBehavior.FLOATING
    )
    page.overlay.append(snack)
    snack.open = True
    page.update()

# ==========================================
# eCellID 工具函数
# ==========================================
def parse_cell_id(raw_val: str) -> int:
    # 安全解析基带返回的十六进制或十进制 ID
    raw_val = raw_val.strip().lower()
    if not raw_val:
        return 0  # 空串返回 0
    try:
        if raw_val.startswith("0x") or any(c in raw_val for c in "abcdef"):
            return int(raw_val, 16)
        return int(raw_val, 10)
    except ValueError:
        return -1  # 非法值返回 -1

def normalize_plmn(raw_plmn: str) -> str:
    #标准化PLMN，去除横杠、下划线等分隔符，返回纯数字字符串
    return raw_plmn.strip().replace("-", "").replace("_", "")
# 十六进制转十进制 (安全解析)
def parse_hex_safe(raw):
    raw = str(raw).strip()
    if not raw:
        return ""
    try:
        return str(int(raw, 16))
    except ValueError:     
        try:
            return str(int(raw))
        except ValueError:
            return raw

# ==========================================
# UI 组件拆分 - 登录视图
# ==========================================
class LoginView(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, prefs, on_login_success: Callable):
        super().__init__(padding=15, expand=True)
        self.app_page = page
        self.api_client = client
        self.prefs = prefs
        self.on_login_success = on_login_success
        self.sec_style = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT, size=14)
        
        default_pad = ft.Padding(left=12, top=12, right=12, bottom=12)
        
        self.ip_input = create_text_field(label="管理地址", value=DEFAULT_IP)
        self.pwd_input = create_text_field(label="管理员密码", password=True, can_reveal_password=True, multiline=True, max_lines=3)
        self.remember_cb = create_checkbox(label="记住密码", value=False)
        self.login_status = ft.Text("输入账号密码登录", color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
        self.login_btn = create_button("登录", on_click=self.do_login, height=45)
        
        self.title_text = ft.Text("MU5001", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, text_align=ft.TextAlign.CENTER, max_lines=1)
        
        self.content = ft.Column(
            [
                ft.Container(height=40),
                self.title_text,  
                ft.Container(height=20),
                self.ip_input, self.pwd_input, self.remember_cb,
                ft.Container(height=8),
                self.login_status, self.login_btn
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
        )

    def update_size(self, is_small: bool):
        self.padding = ft.Padding(left=5, top=15, right=5, bottom=15) if is_small else 15
        self.sec_style.size = 11 if is_small else 14
        
        # 小屏标题字号
        self.title_text.size = 18 if is_small else 32
        
        t_size = 12 if is_small else 15
        
        if is_small:
            pad = ft.Padding(left=2, top=8, right=2, bottom=8)
        else:
            pad = ft.Padding(left=12, top=12, right=12, bottom=12)
            
        self.ip_input.text_size = t_size
        self.ip_input.content_padding = pad
        
        self.pwd_input.text_size = t_size
        self.pwd_input.content_padding = pad
        
        try:
            self.update()
        except Exception:
            pass

    async def init_from_storage(self):
        saved_ip = DEFAULT_IP
        saved_pwd = ""
        
        try:
            if self.prefs:
                if hasattr(self.prefs, "get_async"):
                    saved_ip = await self.prefs.get_async("saved_ip") or DEFAULT_IP
                    saved_pwd = await self.prefs.get_async("saved_pwd") or ""
                else:
                    saved_ip = await self.prefs.get("saved_ip") or DEFAULT_IP
                    saved_pwd = await self.prefs.get("saved_pwd") or ""
        except Exception:
            pass
            
        if saved_ip:
            self.ip_input.value = saved_ip
        if saved_pwd:
            self.pwd_input.value = saved_pwd
            self.remember_cb.value = True
            await self.do_login(None)
            
        self.update()

    async def do_login(self, e=None):
        ip = self.ip_input.value
        pwd = self.pwd_input.value
        if not pwd:
            self.login_status.value = "请输入密码"
            self.login_status.color = ft.Colors.ERROR
            self.update()
            return
        self.login_btn.disabled = True
        self.login_status.value = "正在验证登录..."
        self.login_status.color = ft.Colors.ON_SURFACE_VARIANT
        self.update()
        await asyncio.sleep(0.05)
        try:
            success = await self.api_client.login(ip, pwd)
            if success:
                if self.remember_cb.value and self.prefs:
                    try:
                        if hasattr(self.prefs, "set_async"):
                            await self.prefs.set_async("saved_ip", ip)
                            await self.prefs.set_async("saved_pwd", pwd)
                        else:
                            await self.prefs.set("saved_ip", ip)
                            await self.prefs.set("saved_pwd", pwd)
                    except Exception:
                        pass
                        
                self.login_status.value = "解锁开发者模式..."
                self.update()
                # 获取返回值并进行判断
                dev_ok = await self.api_client.unlock_developer()
                if dev_ok:
                    show_toast(self.app_page, "登录成功，开发者模式已解锁", True)
                else:
                    # 使用 False 触发 error_container 的底色，给用户明显的警示
                    show_toast(self.app_page, "登录成功，开发者模式解锁失败", False)  
                await self.on_login_success()
            else:
                await self.clear_credentials_and_reset(is_error=True)
                self.login_status.value = "密码错误或账号锁定"
                self.login_status.color = ft.Colors.ERROR
                show_toast(self.app_page, "密码错误或账号锁定", False)
        except Exception as e:
            logger.error(f"登录异常，请检查地址和网络: {e}", exc_info=DEBUG_MODE)
            await self.clear_credentials_and_reset(is_error=True)
            self.login_status.value = "连接失败，请检查地址和网络"
            self.login_status.color = ft.Colors.ERROR
            show_toast(self.app_page, "连接失败，请检查地址和网络", False)
        self.login_btn.disabled = False
        self.update()

    async def clear_credentials_and_reset(self, is_error=False):
        if self.prefs:
            try:
                if hasattr(self.prefs, "remove_async"):
                    await self.prefs.remove_async("saved_ip")
                    await self.prefs.remove_async("saved_pwd")
                else:
                    await self.prefs.remove("saved_ip")
                    await self.prefs.remove("saved_pwd")
            except Exception:
                pass
                
        self.remember_cb.value = False
        self.pwd_input.value = ""
        # 所有场景均重置为默认IP地址
        self.ip_input.value = DEFAULT_IP
        if not is_error:
            self.login_status.value = "已退出登录，请重新验证"
            self.login_status.color = ft.Colors.ON_SURFACE_VARIANT
        self.update()

# ==========================================
# UI 组件拆分 - 状态卡片 (Diff 渲染优化)
# ==========================================
class StatusCard(ft.Container):
    def __init__(self):
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12)
        self.is_small = False
        self._last_data_hash = {}

        def c_txt(val): return ft.Text(val, color=ft.Colors.ON_SURFACE)
        self.txt_provider, self.txt_battery, self.txt_network, self.txt_conn_time = c_txt("运营商: --"), c_txt("电量: --"), c_txt("网络: --"), c_txt("连接时长: --")
        self.txt_wan_ip, self.txt_imei, self.txt_imsi = c_txt("WAN IP: --"), c_txt("IMEI: --"), c_txt("IMSI: --")
        self.txt_tx_speed, self.txt_rx_speed = c_txt("上传速度: --"), c_txt("下载速度: --")
        self.txt_traffic_rt, self.txt_traffic_mo = c_txt("本次流量: --"), c_txt("当月流量: --")
        self.txt_freq, self.txt_pci, self.txt_ecellid = c_txt("ARFCN (小区频点): --"), c_txt("PCI (物理小区标识): --"), c_txt("eCellID (小区编号): --")
        self.txt_rsrp, self.txt_rsrq, self.txt_sinr, self.txt_rssi = c_txt("RSRP (信号强度): --"), c_txt("RSRQ (信号质量): --"), c_txt("SINR (信噪比): --"), c_txt("RSSI (接收总功率): --")
        self.txt_temp_bat, self.txt_temp_mdm, self.txt_temp_pa = c_txt("电池温度: --℃"), c_txt("4G Modem: --℃"), c_txt("PA: --℃")
        self.status_text = ft.Text("", color=ft.Colors.ON_SURFACE)
        
        block1 = ft.ResponsiveRow([
            ft.Container(ft.Column([self.txt_provider, self.txt_battery, self.txt_network, self.txt_conn_time], spacing=6), col={"sm": 12, "md": 6}),
            ft.Container(ft.Column([self.txt_wan_ip, self.txt_imei, self.txt_imsi], spacing=6), col={"sm": 12, "md": 6})
        ])
        
        # 温度列表
        block2 = ft.ResponsiveRow([
            ft.Container(ft.Column([self.txt_tx_speed, self.txt_rx_speed, self.txt_traffic_rt, self.txt_traffic_mo], spacing=6), col={"sm": 12, "md": 6}),
            ft.Container(ft.Column([self.txt_temp_bat, self.txt_temp_mdm, self.txt_temp_pa], spacing=6), col={"sm": 12, "md": 6})
        ])
        
        block3 = ft.ResponsiveRow([
            ft.Container(ft.Column([self.txt_freq, self.txt_pci, self.txt_ecellid], spacing=6), col={"sm": 12, "md": 6}),
            ft.Container(ft.Column([self.txt_rsrp, self.txt_rsrq, self.txt_sinr, self.txt_rssi], spacing=6), col={"sm": 12, "md": 6})
        ])

        self.content = ft.Column([
            block1,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            block2,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            block3,
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.status_text
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        self.is_small = is_small
        size = 11 if is_ultra_small else (13 if is_small else 14)
        spacing = 2 if is_ultra_small else (4 if is_small else 6)
        for txt in [
            self.txt_provider, self.txt_battery, self.txt_network, self.txt_conn_time,
            self.txt_wan_ip, self.txt_imei, self.txt_imsi, self.txt_tx_speed,
            self.txt_rx_speed, self.txt_traffic_rt, self.txt_traffic_mo,
            self.txt_freq, self.txt_pci, self.txt_ecellid, self.txt_rsrp,
            self.txt_rsrq, self.txt_sinr, self.txt_rssi, self.txt_temp_bat,
            self.txt_temp_mdm, self.txt_temp_pa, self.status_text
        ]:
            txt.size = size
        for ctrl in self.content.controls:
            if isinstance(ctrl, ft.ResponsiveRow):
                for item in ctrl.controls:
                    col = getattr(item, "content", None)
                    if isinstance(col, ft.Column):
                        col.spacing = spacing
        self.padding = 8 if is_ultra_small else (12 if is_small else 15)
        self.border_radius = 8 if is_ultra_small else (10 if is_small else 12)
        self.content.spacing = 6 if is_ultra_small else (8 if is_small else 10)

    def set_global_status(self, text: str, color: str):
        if self.status_text.value != text or self.status_text.color != color:
            self.status_text.value = text
            self.status_text.color = color
            self.update()

    def _update_field(self, ctrl: ft.Text, new_val: str) -> bool:
        ctrl_id = id(ctrl)
        if self._last_data_hash.get(ctrl_id) != new_val:
            ctrl.value = new_val
            self._last_data_hash[ctrl_id] = new_val
            return True
        return False

    def update_realtime(self, status: 'RealtimeStatus'):
        sep = " "
        has_changes = False

        if self._update_field(self.txt_provider, f"运营商:{sep}{status.provider or '--'}"): has_changes = True
        
        charge = "充电中" if status.is_charging else "未充电"
        if self._update_field(self.txt_battery, f"电量:{sep}{status.battery_percent}% ({charge})"): has_changes = True
        
        lte_bands = []
        if status.active_band_4g:
            for b in status.active_band_4g.split(','):
                num = ''.join(filter(str.isdigit, b))
                if num: lte_bands.append(f"B{num}")
                elif b.strip(): lte_bands.append(b.strip())
            
        nr_bands = []
        if status.active_band_5g:
            for b in status.active_band_5g.split(','):
                num = ''.join(filter(str.isdigit, b))
                if num: nr_bands.append(f"n{num}")
                elif b.strip(): nr_bands.append(b.strip())

        net_type_upper = status.network_type.upper()
        is_sa = "SA" in net_type_upper and "NSA" not in net_type_upper
        is_nsa = "NSA" in net_type_upper

        display_bands = nr_bands if is_sa else (lte_bands + nr_bands if is_nsa else lte_bands)
        valid_bands = []
        for b in display_bands:
            if b and b not in valid_bands:
                valid_bands.append(b)

        band_display = f" ({' + '.join(valid_bands)})" if valid_bands else ""

        net_str = f"网络:{sep}{status.network_type}{band_display}"
        if self._update_field(self.txt_network, net_str): has_changes = True
        if self._update_field(self.txt_wan_ip, f"WAN IP:{sep}{status.wan_ip}"): has_changes = True
        if self._update_field(self.txt_imei, f"IMEI:{sep}{status.imei or '--'}"): has_changes = True
        if self._update_field(self.txt_imsi, f"IMSI:{sep}{status.imsi or '--'}"): has_changes = True
        
        hours, rem = divmod(status.conn_time_sec, 3600)
        minutes, seconds = divmod(rem, 60)
        time_str = f"连接时长:{sep}{hours:02d}:{minutes:02d}:{seconds:02d}" if status.conn_time_sec > 0 else f"连接时长:{sep}--"
        if self._update_field(self.txt_conn_time, time_str): has_changes = True

        if self._update_field(self.txt_tx_speed, f"上传速度:{sep}{format_bytes(status.tx_speed)}/s"): has_changes = True
        if self._update_field(self.txt_rx_speed, f"下载速度:{sep}{format_bytes(status.rx_speed)}/s"): has_changes = True
        
        rt_total = status.tx_bytes_rt + status.rx_bytes_rt
        mo_total = status.tx_bytes_mo + status.rx_bytes_mo
        if self._update_field(self.txt_traffic_rt, f"本次流量:{sep}{format_bytes(rt_total)}"): has_changes = True
        if self._update_field(self.txt_traffic_mo, f"当月流量:{sep}{format_bytes(mo_total)}"): has_changes = True

        if self._update_field(self.txt_freq, f"ARFCN (小区频点):{sep}{status.arfcn or '--'}"): has_changes = True
        
        display_pci_5g = parse_hex_safe(status.pci_5g)
        display_pci_4g = parse_hex_safe(status.pci_4g)
        if self._update_field(self.txt_pci, f"PCI (物理小区标识):{sep}{display_pci_5g or display_pci_4g or '--'}"): has_changes = True

        if self._update_field(self.txt_rsrp, f"RSRP (信号强度):{sep}{status.rsrp_5g or status.rsrp_4g or '--'} dBm"): has_changes = True
        if self._update_field(self.txt_rsrq, f"RSRQ (信号质量):{sep}{status.rsrq_5g or status.rsrq_4g or '--'} dB"): has_changes = True
        if self._update_field(self.txt_sinr, f"SINR (信噪比):{sep}{status.sinr_5g or status.sinr_4g or '--'} dB"): has_changes = True
        if self._update_field(self.txt_rssi, f"RSSI (接收总功率):{sep}{status.rssi_5g or status.rssi_4g or '--'} dBm"): has_changes = True

        mcc_mnc = normalize_plmn(status.mcc_mnc)
        if mcc_mnc in CMCC_PLMNS: is_14bit_provider = True
        elif mcc_mnc in CU_CT_PLMNS: is_14bit_provider = False
        else: is_14bit_provider = any(k in status.provider for k in CMCC_KEYS)

        nr_cell_bits = 14 if is_14bit_provider else 12
        ecellid_str = f"eCellID (小区编号):{sep}--"
        is_5g = bool({"5G", "SA", "NSA"} & set(status.network_type.upper().split()))

        if is_5g and status.cell_id_5g and status.cell_id_5g != "0":
            dec_val = parse_cell_id(status.cell_id_5g)
            if dec_val > 0:
                MAX_NCI = (1 << 36) - 1
                nci_val = dec_val & MAX_NCI 
                gnb_id = nci_val >> nr_cell_bits
                cell_id = nci_val & ((1 << nr_cell_bits) - 1)
                ecellid_str = f"eCellID (小区编号):{sep}{gnb_id}-{cell_id}"
            else:
                ecellid_str = f"eCellID (小区编号):{sep}{status.cell_id_5g}"
        else:
            if status.cell_id_4g and status.cell_id_4g != "0":
                ecell_dec = parse_cell_id(status.cell_id_4g)
                if ecell_dec > 0:
                    MAX_ECI = (1 << 28) - 1
                    eci_val = ecell_dec & MAX_ECI
                    enb_id = eci_val >> 8
                    local_cell = eci_val & 0xFF
                    ecellid_str = f"eCellID (小区编号):{sep}{enb_id}-{local_cell}"
                else:
                    ecellid_str = f"eCellID (小区编号):{sep}{status.cell_id_4g}"
        
        if self._update_field(self.txt_ecellid, ecellid_str): has_changes = True
        
        # 更新温度信息
        if self._update_field(self.txt_temp_bat, f"电池温度:{sep}{status.temp_bat}℃"): has_changes = True
        if self._update_field(self.txt_temp_mdm, f"4G Modem:{sep}{status.temp_mdm}℃"): has_changes = True
        if self._update_field(self.txt_temp_pa, f"PA:{sep}{status.temp_pa}℃"): has_changes = True
        
        if has_changes:
            self.update()

# ==========================================
# UI 组件拆分 - 定时重启卡片
# ==========================================
class RebootCard(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable):
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12)
        self.app_page = page
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.sec_style = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)

        self.txt_local_time = ft.Text("设备当前时间: --", size=12, color=ft.Colors.ON_SURFACE_VARIANT)    
        # 定时重启功能绑定 on_change 事件
        self.reboot_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY, inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_reboot_switch_change
        )

        self.reboot_hint = ft.Text("提示：时:0~23 | 分:0~59 | 缓冲时间:1~6", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.reboot_mode = create_dropdown("重启模式", [ft.dropdown.Option("1", "1 - 按周自动重启"), ft.dropdown.Option("2", "2 - 按间隔天数")], "1", width=220)
        
        # 不再使用 expand，依赖 ResponsiveRow 的栅格系统来控制宽度
        self.rb_time_hr = create_text_field(label="时", value="02", input_filter=ft.NumbersOnlyInputFilter())
        self.rb_time_min = create_text_field(label="分", value="00", input_filter=ft.NumbersOnlyInputFilter())
        self.rb_buffer = create_text_field(label="缓冲时间", value="02", input_filter=ft.NumbersOnlyInputFilter())
        
        # 采用 ResponsiveRow，小屏(sm)占据12格(独占一行)，中屏(md)占据4格(三分之一宽)
        self.time_container = ft.ResponsiveRow(
            controls=[
                ft.Container(self.rb_time_hr, col={"sm": 12, "md": 4}),
                ft.Container(self.rb_time_min, col={"sm": 12, "md": 4}),
                ft.Container(self.rb_buffer, col={"sm": 12, "md": 4}),
            ],
            spacing=5,
            run_spacing=5
        )

        self.week_cbs = [
            create_checkbox(label=w, value=False, data=str(i+1), on_change=self.on_week_change)
            for i, w in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
        ]
        self.rb_interval = create_dropdown("间隔天数", [ft.dropdown.Option(str(i), str(i)) for i in range(1, 31)], "1", menu_height=300)
        self.btn_save_reboot = create_button("保存重启规则", on_click=self.on_save_reboot)
        
        self.week_items = [ft.Container(content=cb, width=86, padding=0, margin=0) for cb in self.week_cbs]
        row_weeks = ft.Row(controls=self.week_items, wrap=True, spacing=4, run_spacing=4)

        self.txt_reboot_title = ft.Text("定时重启规则", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        # 抽离选项为变量
        self.txt_opt1 = ft.Text("选项1: 按周触发（仅选 1 生效）", size=13, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.BOLD)
        self.txt_opt2 = ft.Text("选项2: 间隔触发（仅选 2 生效）", size=13, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.BOLD)

        self.content = ft.Column([
            self.txt_reboot_title,
            self.txt_local_time, ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            ft.Row([self.reboot_enable, ft.Text("定时重启", color=ft.Colors.INVERSE_PRIMARY)], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True), 
            self.reboot_hint,
            
            self.time_container,  # 响应式容器
            
            self.reboot_mode,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            self.txt_opt1,  # 使用变量
            row_weeks, ft.Container(height=5),
            self.txt_opt2,  # 使用变量
            self.rb_interval, ft.Container(height=10), self.btn_save_reboot
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        self.is_small_layout = is_small
        if hasattr(self, 'txt_reboot_title'): self.txt_reboot_title.size = 13 if is_ultra_small else (16 if is_small else 18)
        
        # 统一提示文本字号
        hint_size = 10 if is_ultra_small else (11 if is_small else 12)
        if hasattr(self, 'txt_local_time'): self.txt_local_time.size = hint_size
        if hasattr(self, 'reboot_hint'): self.reboot_hint.size = hint_size
        
        text_size = 11 if is_ultra_small else (13 if is_small else 15)
        label_size = 10 if is_ultra_small else (12 if is_small else 14)
        pad = ft.Padding(left=6, top=6, right=6, bottom=6) if is_ultra_small else (ft.Padding(left=10, top=8, right=10, bottom=8) if is_small else ft.Padding(left=12, top=10, right=12, bottom=10))
        for control in [self.reboot_mode, self.rb_time_hr, self.rb_time_min, self.rb_buffer, self.rb_interval]:
            if hasattr(control, "text_size"):
                control.text_size = text_size
            if hasattr(control, "content_padding"):
                if not (is_small and isinstance(getattr(control, "data", None), dict) and "small_options" in control.data):
                    control.content_padding = pad
            if hasattr(control, "label_style"):
                control.label_style.size = label_size
        for cb in self.week_cbs:
            if cb.label_style:
                cb.label_style.size = label_size
        for item in getattr(self, "week_items", []):
            item.width = 74 if is_ultra_small else (86 if is_small else 75)
            
        # 处理选项文本和按钮排版
        if hasattr(self, 'txt_opt1'): self.txt_opt1.size = 11 if is_ultra_small else 13
        if hasattr(self, 'txt_opt2'): self.txt_opt2.size = 11 if is_ultra_small else 13
        
        self.btn_save_reboot.height = 42 if is_ultra_small else 48
        if self.btn_save_reboot.style:
            # 单独把这个按钮的文字设小，并极大压缩左右内边距(Padding)，防止文字换行
            self.btn_save_reboot.style.text_style.size = 11 if is_ultra_small else (13 if is_small else 14)
            self.btn_save_reboot.style.padding = ft.Padding.symmetric(horizontal=4) if is_ultra_small else None

        if is_ultra_small:
            self.padding = 8
            self.border_radius = 8
            self.content.spacing = 8
        try:
            self.update()
        except Exception:
            pass

    def on_week_change(self, e):
        # 星期单选：保证仅选中一天
        for cb in self.week_cbs:
            cb.value = (cb is e.control)
        self.update()

    def update_time_display(self):
        self.txt_local_time.value = f"设备当前时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        self.update()

    def update_config(self, res: dict):
        self.reboot_enable.value = res.get("reboot_schedule_enable", "0") == "1"
        rb_mode = res.get("reboot_schedule_mode", "1")
        if rb_mode in ["1", "2"]:
            self.reboot_mode.value = rb_mode
        self.rb_time_hr.value = res.get("reboot_hour1", "02").zfill(2)
        self.rb_time_min.value = res.get("reboot_min1", "00").zfill(2)
        self.rb_buffer.value = res.get("reboot_timeframe_hours1", "02").zfill(2)
        weeks = [w.strip() for w in res.get("reboot_dow", "").split(",") if w.strip()]
        for cb in self.week_cbs:
            cb.value = cb.data in weeks
        dod = res.get("reboot_dod", "1")
        if any(o.key == dod for o in self.rb_interval.options):
            self.rb_interval.value = dod
        self.update()

    # 拨动定时重启开关直接生效
    async def on_reboot_switch_change(self, e):
        is_on = self.reboot_enable.value
        show_toast(self.app_page, f"正在{'开启' if is_on else '关闭'}定时重启...", True)
        selected_weeks = [cb.data for cb in self.week_cbs if cb.value]
        try:
            ok = await self.api_client.set_reboot_schedule(
                enable=is_on, mode=self.reboot_mode.value, hr=self.rb_time_hr.value,
                min=self.rb_time_min.value, buffer=self.rb_buffer.value,
                weeks=selected_weeks, interval=self.rb_interval.value
            )
            if ok:
                self.set_global_status(f"定时重启已{'开启' if is_on else '关闭'}", ft.Colors.PRIMARY)
                show_toast(self.app_page, f"定时重启已{'开启' if is_on else '关闭'}", True)
            else:
                self.set_global_status("定时重启状态切换失败", ft.Colors.ERROR)
                show_toast(self.app_page, "状态切换失败", False)
                self.reboot_enable.value = not is_on
        except Exception as e:
            logger.error(f"定时重启开关异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("定时重启状态切换异常", ft.Colors.ERROR)
            show_toast(self.app_page, "状态切换异常", False)
            self.reboot_enable.value = not is_on
        self.update()

    # 保存重启规则
    async def on_save_reboot(self, e):
        selected_weeks = [cb.data for cb in self.week_cbs if cb.value]
        try:
            ok = await self.api_client.set_reboot_schedule(
                enable=self.reboot_enable.value, mode=self.reboot_mode.value, hr=self.rb_time_hr.value,
                min=self.rb_time_min.value, buffer=self.rb_buffer.value,
                weeks=selected_weeks, interval=self.rb_interval.value
            )
            if ok:
                self.set_global_status("定时重启配置已保存", ft.Colors.PRIMARY)
                show_toast(self.app_page, "定时重启配置保存成功", True)
            else:
                self.set_global_status("保存失败，请检查连接状态", ft.Colors.ERROR)
                show_toast(self.app_page, "定时重启配置保存失败", False)
        except Exception as e:
            logger.error(f"保存重启规则异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("保存失败", ft.Colors.ERROR)
        self.update()

# ==========================================
# UI 组件拆分 - 高级设置卡片
# ==========================================
class SettingsCard(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable, on_reboot_cb: Callable):
        super().__init__()
        self.app_page = page 
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.on_reboot_device = on_reboot_cb
        self.sec_style = ft.TextStyle(color=ft.Colors.ON_SURFACE_VARIANT)
        self.lte_selected: Set[str] = set(LTE_BANDS)
        self.nr_sa_selected: Set[str] = set(NR_SA_BANDS)
        self.nr_nsa_selected: Set[str] = set(NR_NSA_BANDS)
        self.lte_cbs: Dict[str, ft.Checkbox] = {}
        self.sa_cbs: Dict[str, ft.Checkbox] = {}
        self.nsa_cbs: Dict[str, ft.Checkbox] = {}
        self.net_mode_cbs: Dict[str, ft.Checkbox] = {}
        self.net_mode_items: List[ft.Container] = []
        self.wifi_mode_cbs: Dict[str, ft.Checkbox] = {}
        self.is_switching_data = False
        self.actual_wifi_mode = "merged"
        self.compact_labels: List[ft.TextStyle] = []
        self.compact_inputs: List[ft.Control] = []
        self.compact_buttons: List[ft.Control] = []
        self.compact_texts: List[ft.Text] = []
        self.build_ui()

    def _create_checkbox_grid(self, bands: List[str], prefix: str, selected: Set[str], cb_map: Dict[str, ft.Checkbox], on_change: Callable) -> ft.Row:
        controls = []
        for b in bands:
            cb = create_checkbox(label=f"{prefix}{b}", value=b in selected, data=b, on_change=on_change)
            cb_map[b] = cb
            controls.append(ft.Container(content=cb, width=76, padding=0, margin=0))
        row = ft.Row(controls, wrap=True, spacing=6, run_spacing=4)
        row.data = {"item_width_ultra": 58, "item_width_small": 74, "item_width_base": 76}
        return row

    def on_lte_change(self, e):
        b = e.control.data
        if e.control.value: self.lte_selected.add(b)
        elif b in self.lte_selected: self.lte_selected.remove(b)

    def on_sa_change(self, e):
        b = e.control.data
        if e.control.value: self.nr_sa_selected.add(b)
        elif b in self.nr_sa_selected: self.nr_sa_selected.remove(b)

    def on_nsa_change(self, e):
        b = e.control.data
        if e.control.value: self.nr_nsa_selected.add(b)
        elif b in self.nr_nsa_selected: self.nr_nsa_selected.remove(b)

    def on_net_mode_change(self, e):
        if e.control.value:
            for cb in self.net_mode_cbs.values():
                if cb is not e.control:
                    cb.value = False
        else:
            e.control.value = True
        self.update()

    def on_wifi_mode_change(self, e):
        self.update()

    def _infer_wifi_sync_to_5g(self, res: dict) -> bool:
        if self.actual_wifi_mode != "separated":
            return False
        flag = str(res.get("wifi_syncparas_flag", "")).strip().lower()
        if flag in ["1", "true", "on", "yes"]:
            return True
        if flag in ["0", "false", "off", "no"]:
            return False
        return False

    def update_broadcast_controls(self):
        # 使用实际生效的广播模式
        mode = self.actual_wifi_mode 
        if hasattr(self, "wifi_detail_5g_section"):
            self.wifi_detail_5g_section.visible = (mode == "separated")
        if hasattr(self, "wifi_sync_to_5g"):
            self.wifi_sync_to_5g.visible = (mode == "separated")
        if hasattr(self, "wifi_sync_to_5g_row"):
            self.wifi_sync_to_5g_row.visible = (mode == "separated")
            self.update_wifi_sync_state()
        if hasattr(self, "wifi_detail_24g_title"):
            self.wifi_detail_24g_title.value = "2.4/5GHz" if mode == "merged" else "2.4GHz"

    def build_ui(self):
        # WiFi 休眠
        sleep_opts = [("0", "永不休眠"), ("5", "5分钟"), ("10", "10分钟"), ("20", "20分钟"), ("30", "30分钟"), ("60", "1小时"), ("120", "2小时")]
        self.wifi_sleep = create_dropdown("", [ft.dropdown.Option(k, v) for k, v in sleep_opts], "10")
        btn_wifi_sleep = create_button("保存休眠", on_click=self.on_wifi_sleep_save)

        # WiFi 设置 UI (合一/分离单选 + 动态广播复选框)
        # 提取公共的文字样式，跟随主题的 ON_SURFACE 颜色变化
        lbl_style = ft.TextStyle(color=ft.Colors.ON_SURFACE)
        self.compact_labels = [self.sec_style, lbl_style]
        self.wifi_checkbox_label_texts: List[ft.Text] = []

        def make_checkbox_line(cb: ft.Checkbox, label: str) -> ft.Row:
            cb.label = ""
            txt = ft.Text(label, color=ft.Colors.ON_SURFACE)
            txt.data = {"base_label": label, "small_label": label}
            self.wifi_checkbox_label_texts.append(txt)
            return ft.Row(
                [cb, txt],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=False
            )

        # 横向自动折行排列
        self.wifi_mode = ft.RadioGroup(
            value=WiFiMode.MERGED,
            content=ft.ResponsiveRow([
                ft.Container(content=ft.Radio(value=WiFiMode.MERGED, label="双频合一", fill_color=ft.Colors.PRIMARY, label_style=ft.TextStyle(color=ft.Colors.ON_SURFACE)), col={"xs": 12, "sm": 6, "md": 3}, padding=0, margin=0),
                ft.Container(content=ft.Radio(value=WiFiMode.SEPARATED, label="双频分离", fill_color=ft.Colors.PRIMARY, label_style=ft.TextStyle(color=ft.Colors.ON_SURFACE)), col={"xs": 12, "sm": 6, "md": 3}, padding=0, margin=0)
            ], spacing=10, run_spacing=5),
            on_change=self.on_wifi_mode_change
        )
        
        # WiFi 广播复选框
        self.cb_broadcast_merged = create_checkbox(label="WiFi 广播", value=True)
        self.cb_broadcast_24g = create_checkbox(label="2.4GHz", value=True)
        self.cb_broadcast_5g = create_checkbox(label="5GHz", value=True)
        
        # 赋默认容器内容，避免首次加载数据前出现 UI 空白和页面跳动
        btn_apply_mode = create_button("保存双频", on_click=self.on_apply_wifi_mode)

        wifi_mode_container = ft.Column([
            self.wifi_mode,
            btn_apply_mode,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT)
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        
        # 设为隐藏的占位符，防止页面下方的排版代码报错
        def create_detail_controls(prefix: str, title: str):
            title_text = ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
            ssid = create_text_field(label="", multiline=True, max_lines=3)
            broadcast = create_checkbox(label="", value=True)
            isolate = create_checkbox(label="", value=False)
            auth_opts = [("OPEN", "OPEN"), ("WPA2PSK", "WPA2-PSK"), ("WPAPSKWPA2PSK", "WPA/WPA2-PSK"), ("WPA3PSK", "WPA3-PSK"), ("WPA2PSKWPA3PSK", "WPA2/WPA3-PSK")]
            auth = create_dropdown("安全模式", [ft.dropdown.Option(k, v) for k, v in auth_opts], "WPA2PSK")
            auth.data = {"base_options": auth_opts, "small_options": [("OPEN", "OPEN"), ("WPA2PSK", "WPA2"), ("WPAPSKWPA2PSK", "WPA/2"), ("WPA3PSK", "WPA3"), ("WPA2PSKWPA3PSK", "WPA2/3")]}
            password = create_text_field(label="密码", password=True, can_reveal_password=True, multiline=True, max_lines=3)
            broadcast.data = {"base_label": "广播SSID", "small_label": "广播SSID"}
            isolate.data = {"base_label": "客户端隔离", "small_label": "客户端隔离"}
            controls = {"title": title_text, "ssid": ssid, "broadcast": broadcast, "isolate": isolate, "auth": auth, "password": password}
            setattr(self, f"wifi_detail_{prefix}", controls)
            return ft.Column([
                title_text,
                ssid,
                make_checkbox_line(broadcast, "广播SSID"),
                make_checkbox_line(isolate, "客户端隔离"),
                auth,
                password
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        wifi_detail_24g_section = create_detail_controls("24g", "2.4GHz")
        self.wifi_detail_24g_title = self.wifi_detail_24g["title"]
        self.wifi_detail_5g_section = create_detail_controls("5g", "5GHz")
        self.wifi_detail_5g_section.visible = False
        btn_apply_wifi_detail = create_button("应用WiFi设置", on_click=self.on_apply_wifi_detail, expand=True)
        self.wifi_sync_to_5g = create_checkbox(label="", value=False, on_change=lambda e: self.update_wifi_sync_state())
        self.wifi_sync_to_5g_row = make_checkbox_line(self.wifi_sync_to_5g, "同步到5GHz")
        self.wifi_sync_to_5g_row.visible = False
        wifi_detail_container = ft.Column([
            ft.Text("WiFi 详细设置", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
            wifi_detail_24g_section,
            self.wifi_sync_to_5g_row,
            self.wifi_detail_5g_section,
            btn_apply_wifi_detail
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        btn_wifi_radio_apply = ft.Container(height=0)
        
        # WiFi 覆盖范围
        self.wifi_coverage_cbs = {}
        
        def on_coverage_change(e):
            if e.control.value:
                # 勾选其中一个时，取消其他勾选
                for cb in self.wifi_coverage_cbs.values():
                    if cb is not e.control:
                        cb.value = False
            else:
                # 防止全部取消，必须保留一个勾
                e.control.value = True 
            self.update()

        coverage_options = {"short_mode": "近距离", "medium_mode": "中距离", "long_mode": "远距离"}
        cov_controls = []
        for val, label in coverage_options.items():
            cb = create_checkbox(label="", value=(val == "short_mode"), on_change=on_coverage_change)
            self.wifi_coverage_cbs[val] = cb
            cov_controls.append(ft.Container(content=make_checkbox_line(cb, label), col={"xs": 12, "sm": 6, "md": 3}, padding=0, margin=0))
            
        self.wifi_coverage_row = ft.ResponsiveRow(controls=cov_controls, spacing=10, run_spacing=5)
        btn_wifi_coverage_apply = create_button("应用覆盖范围", on_click=self.on_apply_wifi_coverage, expand=True)
        
        # 数据连接开关
        self.data_switch = ft.Switch(
            value=True,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_data_switch_change
        )
        
        # 网络模式
        net_mode_controls = []
        for name in NET_CONFIG.keys():
            cb = create_checkbox(label=name, value=(name == "5G/4G/3G"), on_change=self.on_net_mode_change)
            self.net_mode_cbs[name] = cb
            item = ft.Container(content=cb, width=120, padding=0, margin=0)
            self.net_mode_items.append(item)
            net_mode_controls.append(item)
        net_mode_grid = ft.Row(controls=net_mode_controls, wrap=True, spacing=0, run_spacing=5)
        self.btn_net_mode_apply = create_button("网络锁定", on_click=self.on_apply_net_mode, expand=True)
        
        # 频段选择
        lte_grid = self._create_checkbox_grid(LTE_BANDS, "B", self.lte_selected, self.lte_cbs, self.on_lte_change)
        sa_grid = self._create_checkbox_grid(NR_SA_BANDS, "N", self.nr_sa_selected, self.sa_cbs, self.on_sa_change)
        nsa_grid = self._create_checkbox_grid(NR_NSA_BANDS, "N", self.nr_nsa_selected, self.nsa_cbs, self.on_nsa_change)
        self.band_grids = [lte_grid, sa_grid, nsa_grid]
        btn_lte_apply = create_button("应用4G", on_click=self.on_apply_lte, expand=True)
        btn_sa_apply = create_button("应用SA", on_click=self.on_apply_sa, expand=True)
        btn_nsa_apply = create_button("应用NSA", on_click=self.on_apply_nsa, expand=True)
        
        # 锁小区表单
        # 统一加上 expand=True，强制它们撑满容器宽度以保证右侧对齐
        self.cell_pci = create_text_field(label="", expand=True, input_filter=ft.NumbersOnlyInputFilter())
        self.cell_earfcn = create_text_field(label="", expand=True, input_filter=ft.NumbersOnlyInputFilter())
        self.cell_band = create_dropdown("", [ft.dropdown.Option(b, b) for b in ["1", "3", "28", "41", "78"]], "1", expand=True)
        self.cell_scs = create_dropdown("", [ft.dropdown.Option(s, f"{s}KHz") for s in ["15", "30", "60"]], "15", expand=True)
        self.compact_inputs = [
            self.wifi_sleep, self.cell_pci, self.cell_earfcn, self.cell_band, self.cell_scs,
            self.wifi_detail_24g["ssid"], self.wifi_detail_24g["auth"], self.wifi_detail_24g["password"],
            self.wifi_detail_5g["ssid"], self.wifi_detail_5g["auth"], self.wifi_detail_5g["password"]
        ]
       
        # 采用 ResponsiveRow 自动处理排版
        def create_responsive_field(label_text: str, control: ft.Control) -> ft.ResponsiveRow:
            return ft.ResponsiveRow(
                controls=[
                    ft.Container(
                        ft.Text(label_text, color=ft.Colors.ON_SURFACE), 
                        col={"xs": 12, "sm": 12, "md": 3},
                        alignment=ft.Alignment.CENTER_LEFT,
                    ),
                    ft.Container(control, col={"xs": 12, "sm": 12, "md": 9})
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=5, run_spacing=2
            )

        row_pci = create_responsive_field("PCI", self.cell_pci)
        row_earfcn = create_responsive_field("ARFCN", self.cell_earfcn)
        row_band = create_responsive_field("BAND", self.cell_band)
        row_scs = create_responsive_field("SCS", self.cell_scs)
        
        cell_tip = ft.Text("设备重启后生效", size=13, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
        self.compact_texts = [cell_tip]
        
        btn_cell_apply = create_button("锁定小区", on_click=self.on_cell_lock, expand=True)
        btn_cell_unlock = create_button("清除锁定", on_click=self.on_cell_unlock, expand=True)
        btn_cell_reboot = create_button("重启设备", on_click=self.on_reboot_device, expand=True)
        self.compact_buttons = [
            btn_wifi_sleep, btn_apply_mode, btn_apply_wifi_detail, btn_wifi_coverage_apply,
            self.btn_net_mode_apply, btn_lte_apply, btn_sa_apply, btn_nsa_apply,
            btn_cell_apply, btn_cell_unlock, btn_cell_reboot
        ]
        self.wifi_reconnect_hint = ft.Text("应用后需重新连接 WiFi", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.band_hint = ft.Text("每项至少保留一个频段", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        # WiFi 设置专属卡片
        self.txt_wifi_title = ft.Text("WiFi 设置", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        wifi_section = ft.Container(
            padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12,
            content=ft.Column([
                self.txt_wifi_title,
                ft.Divider(height=10, color=ft.Colors.OUTLINE_VARIANT),
                ft.Text("WiFi 休眠", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                self.wifi_sleep, btn_wifi_sleep, ft.Container(height=15),

                ft.Column([
                    ft.Text("WiFi 频段设置", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                    self.wifi_reconnect_hint
                ], spacing=2),
                wifi_mode_container, btn_wifi_radio_apply, ft.Container(height=15),
                wifi_detail_container, ft.Container(height=15),

                ft.Text("WiFi 覆盖范围", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                self.wifi_coverage_row, btn_wifi_coverage_apply
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        )

        # 高级网络设置专属卡片
        self.txt_adv_net_title = ft.Text("高级网络设置", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        adv_network_section = ft.Container(
            padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12,
            content=ft.Column([
                self.txt_adv_net_title,
                ft.Divider(height=10, color=ft.Colors.OUTLINE_VARIANT),
                
                ft.Text("网络模式锁定", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                ft.Row([self.data_switch, ft.Text("数据连接", color=ft.Colors.INVERSE_PRIMARY)], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                net_mode_grid, self.btn_net_mode_apply, ft.Container(height=15),
                
                ft.Column([
                    ft.Text("网络频段锁定", weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                    self.band_hint 
                ], spacing=2),
                ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
                ft.Text("4G LTE 频段", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE),
                lte_grid, btn_lte_apply, ft.Container(height=10),
                ft.Text("5G SA 频段", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE),
                sa_grid, btn_sa_apply, ft.Container(height=10),
                ft.Text("5G NSA 频段", size=13, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE),
                nsa_grid, btn_nsa_apply, ft.Container(height=10),
                ft.Text("锁定小区", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
                row_pci, row_earfcn, row_band, row_scs, cell_tip, btn_cell_apply,
                
                ft.ResponsiveRow([
                    ft.Container(btn_cell_unlock, col={"xs": 12, "sm": 6}),
                    ft.Container(btn_cell_reboot, col={"xs": 12, "sm": 6})
                ], spacing=10, run_spacing=10)
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        )

        # 将 WiFi 设置单独提出来，作为类属性供外部调用
        self.wifi_section = wifi_section
        
        # 高级网络设置卡片
        self.content = adv_network_section

    # 重写 update 方法，确保被分离到工具箱的 wifi_section 也能同步刷新数据
    def update_size(self, is_small: bool, is_ultra_small: bool = False):

        if hasattr(self, 'txt_wifi_title'): self.txt_wifi_title.size = 13 if is_ultra_small else (16 if is_small else 18)
        if hasattr(self, 'txt_adv_net_title'): self.txt_adv_net_title.size = 13 if is_ultra_small else (16 if is_small else 18)
        text_size = 11 if is_ultra_small else (13 if is_small else 15)
        label_size = 10 if is_ultra_small else (12 if is_small else 14)
        button_text_size = 11 if is_ultra_small else (13 if is_small else 14)
        button_height = 42 if is_ultra_small else 48
        pad = ft.Padding(left=6, top=6, right=6, bottom=6) if is_ultra_small else (ft.Padding(left=10, top=8, right=10, bottom=8) if is_small else ft.Padding(left=12, top=10, right=12, bottom=10))

        for section in [getattr(self, "wifi_section", None), getattr(self, "content", None)]:
            if section:
                section.padding = 8 if is_ultra_small else (12 if is_small else 15)
                section.border_radius = 8 if is_ultra_small else (10 if is_small else 12)
                if isinstance(getattr(section, "content", None), ft.Column):
                    section.content.spacing = 8 if is_ultra_small else (10 if is_small else 12)

        for style in self.compact_labels:
            style.size = label_size
        option_label_style = ft.TextStyle(color=ft.Colors.ON_SURFACE, size=label_size)

        for cb in list(self.net_mode_cbs.values()) + list(self.lte_cbs.values()) + list(self.sa_cbs.values()) + list(self.nsa_cbs.values()) + list(getattr(self, "wifi_coverage_cbs", {}).values()):
            cb.label_style = option_label_style
            if cb in getattr(self, "wifi_coverage_cbs", {}).values() and isinstance(cb.data, dict):
                cb.label = ""

        net_item_width = 86 if is_ultra_small else (105 if is_small else 120)
        for item in self.net_mode_items:
            item.width = net_item_width
        for grid in getattr(self, "band_grids", []):
            if isinstance(grid.data, dict):
                key = "item_width_ultra" if is_ultra_small else ("item_width_small" if is_small else "item_width_base")
                item_width = grid.data.get(key, 76)
            else:
                item_width = 76
            grid.spacing = 2 if is_ultra_small else (4 if is_small else 6)
            grid.run_spacing = 2 if is_ultra_small else 4
            for item in grid.controls:
                item.width = item_width

        for cb in [getattr(self, "cb_broadcast_merged", None), getattr(self, "cb_broadcast_24g", None), getattr(self, "cb_broadcast_5g", None)]:
            if cb:
                cb.label_style = option_label_style

        radio_content = getattr(self.wifi_mode, "content", None)
        if radio_content:
            for item in getattr(radio_content, "controls", []):
                radio = getattr(item, "content", None)
                if radio:
                    radio.label_style = option_label_style
                    if radio.value == "merged":
                        radio.label = "双频合一"
                    elif radio.value == "separated":
                        radio.label = "双频分离"

        for controls in [self.wifi_detail_24g, self.wifi_detail_5g]:
            for key in ["broadcast", "isolate"]:
                cb = controls[key]
                cb.label_style = option_label_style
                cb.label = ""
                if isinstance(cb.data, dict):
                    cb.data["current_label"] = cb.data.get("small_label" if is_small else "base_label", "")
        self.wifi_sync_to_5g.label_style = option_label_style
        self.wifi_sync_to_5g.label = ""
        if isinstance(self.wifi_sync_to_5g.data, dict):
            self.wifi_sync_to_5g.data["current_label"] = self.wifi_sync_to_5g.data.get("small_label" if is_small else "base_label", "同步到5GHz")

        for text in getattr(self, "wifi_checkbox_label_texts", []):
            text.size = label_size
            text.color = ft.Colors.ON_SURFACE
            if isinstance(text.data, dict):
                text.value = text.data.get("small_label" if is_small else "base_label", text.value)

        for control in self.compact_inputs:
            if hasattr(control, "text_size"):
                control.text_size = text_size
            if isinstance(getattr(control, "data", None), dict) and "small_options" in control.data:
                option_key = "small_options" if is_small else "base_options"
                control.options = [ft.dropdown.Option(key, text) for key, text in control.data[option_key]]
                if is_small:
                    control.text_size = text_size
                    control.content_padding = pad
                    control.height = 44 if is_ultra_small else 56
            if control in [self.wifi_detail_24g["auth"], self.wifi_detail_5g["auth"], self.wifi_detail_24g["password"], self.wifi_detail_5g["password"]]:
                control.width = None if is_small else 360
            if hasattr(control, "height"):
                if not (is_small and isinstance(getattr(control, "data", None), dict) and "small_options" in control.data):
                    control.height = None
            if hasattr(control, "content_padding"):
                if not (is_small and isinstance(getattr(control, "data", None), dict) and "small_options" in control.data):
                    control.content_padding = pad
            if hasattr(control, "label_style"):
                control.label_style = self.sec_style
            if hasattr(control, "hint_style"):
                control.hint_style = self.sec_style

        for btn in self.compact_buttons:
            btn.height = btn.data.get("small_height", button_height) if is_small and isinstance(btn.data, dict) else button_height
            if isinstance(btn.data, dict) and "small_text" in btn.data:
                if hasattr(btn, "text"):
                    current_text = getattr(btn, "text", "")
                    btn.text = btn.data.get("small_text" if is_small else "base_text", current_text)
                elif hasattr(btn, "content"):
                    current_text = getattr(btn, "content", "")
                    btn.content = btn.data.get("small_text" if is_small else "base_text", current_text)
            if btn.style and getattr(btn.style, "text_style", None):
                if is_small and isinstance(btn.data, dict):
                    btn.style.text_style.size = btn.data.get("small_text_size", button_text_size)
                else:
                    btn.style.text_style.size = button_text_size

        # 统一处理底部提示文字缩放
        hint_size = 10 if is_ultra_small else (11 if is_small else 12)
        
        if hasattr(self, "wifi_reconnect_hint"):
            self.wifi_reconnect_hint.size = hint_size
            
        if hasattr(self, "band_hint"):
            self.band_hint.size = hint_size

        for text in self.compact_texts:
            text.size = hint_size

        try:
            self.update()
        except Exception:
            pass

    def update(self):
        super().update()
        if hasattr(self, 'wifi_section') and self.wifi_section.page:
            try:
                self.wifi_section.update()
            except Exception:
                pass

    def update_config(self, res: dict, sa_raw: str, nsa_raw: str, current_net_mode: str):
        # WiFi 休眠
        sleep_val = res.get("sysIdleTimeToSleep", "10")
        if any(o.key == sleep_val for o in self.wifi_sleep.options):
            self.wifi_sleep.value = sleep_val
        # LTE 频段
        mask = res.get("lte_band_lock", "")
        if mask:
            self.lte_selected.clear()
            self.lte_selected.update(mask_to_lte_bands(mask))
        for b, cb in self.lte_cbs.items():
            cb.value = b in self.lte_selected
        # 5G SA 频段
        if sa_raw:
            self.nr_sa_selected.clear()
            self.nr_sa_selected.update([b.strip() for b in sa_raw.split(",") if b.strip()])
        for b, cb in self.sa_cbs.items():
            cb.value = b in self.nr_sa_selected
        # 5G NSA 频段
        if nsa_raw:
            self.nr_nsa_selected.clear()
            self.nr_nsa_selected.update([b.strip() for b in nsa_raw.split(",") if b.strip()])
        for b, cb in self.nsa_cbs.items():
            cb.value = b in self.nr_nsa_selected
        # 锁小区配置
        cell_val = res.get("nr5g_cell_lock", "")
        if cell_val and cell_val != "1,1,1,1":
            parts = cell_val.split(",")
            parts = (parts + ["", "", "1", "15"])[:4]  # 安全补全缺失数据，防止越界崩溃
            self.cell_pci.value = parts[0].strip()
            self.cell_earfcn.value = parts[1].strip()
            if any(o.key == parts[2].strip() for o in self.cell_band.options): self.cell_band.value = parts[2].strip()
            if any(o.key == parts[3].strip() for o in self.cell_scs.options): self.cell_scs.value = parts[3].strip()
        else:
            self.cell_pci.value = ""
            self.cell_earfcn.value = ""
            self.cell_band.value = "1"
            self.cell_scs.value = "15"

        # WiFi 覆盖范围回显
        cov_val = str(res.get("WiFiCoverage", "")).strip()
        if cov_val in ["short_mode", "medium_mode", "long_mode"]:
            for val, cb in self.wifi_coverage_cbs.items():
                cb.value = (val == cov_val)

        # WiFi 频段及广播状态回显
        wifi_lbd = str(res.get("wifi_lbd_enable", "")).strip()
        b_24 = str(res.get("ap_broadcast_24g", "0")).strip()
        b_5g = str(res.get("ap_broadcast_5g", "0")).strip()

        # ApBroadcastDisabled: 0 代表广播(开启), 1 代表隐藏(关闭)
        if wifi_lbd == "1":
            self.wifi_mode.value = WiFiMode.MERGED
            self.actual_wifi_mode = WiFiMode.MERGED  # 记录真实状态
            self.cb_broadcast_merged.value = (b_24 == "0") 
        else:
            self.wifi_mode.value = WiFiMode.SEPARATED
            self.actual_wifi_mode = WiFiMode.SEPARATED  # 记录真实状态
            self.cb_broadcast_24g.value = (b_24 == "0")
            self.cb_broadcast_5g.value = (b_5g == "0")
            
        # 刷新显示状态
        self.update_broadcast_controls()

        def decode_wifi_pwd(value: str) -> str:
            try:
                return base64.b64decode((value or "").encode("ascii")).decode("utf-8")
            except Exception:
                return value or ""

        def fill_wifi_detail(controls: Dict, data: Dict):
            controls["ssid"].value = data.get("SSID", "")
            controls["broadcast"].value = data.get("ApBroadcastDisabled", "0") == "0"
            controls["isolate"].value = data.get("ApIsolate", "0") == "1"
            auth = data.get("AuthMode", "WPA2PSK") or "WPA2PSK"
            controls["auth"].value = auth if any(o.key == auth for o in controls["auth"].options) else "WPA2PSK"
            controls["password"].value = decode_wifi_pwd(data.get("Password", ""))

        fill_wifi_detail(self.wifi_detail_24g, res.get("wifi_detail_24g", {}))
        fill_wifi_detail(self.wifi_detail_5g, res.get("wifi_detail_5g", {}))
        if hasattr(self, "wifi_sync_to_5g"):
            self.wifi_sync_to_5g.value = self._infer_wifi_sync_to_5g(res)
        self.update_broadcast_controls()

        # 网络模式配置
        matched = False
        for name, cfg in NET_CONFIG.items():
            if current_net_mode == cfg["read_val"].upper():
                for cb in self.net_mode_cbs.values(): cb.value = False
                self.net_mode_cbs[name].value = True
                matched = True
                break
        if not matched:
            for cb in self.net_mode_cbs.values(): cb.value = False
            self.net_mode_cbs["5G/4G/3G"].value = True
        self.update()
        
    def update_realtime(self, res: dict):
        # 同步设备实际的数据连接状态到 UI 开关
        # 兼容 ipv4_ipv6_connected 等双栈状态
        status = res.get("ppp_status", "").lower()
        status_clean = status.replace("disconnected", "off")
        is_connected = "connected" in status_clean
        is_disconnected = "off" in status_clean and not is_connected

        # 只在状态明确连上或断开时，且用户没有在手动切换时更新，防止正在连接中(connecting)发生界面跳动
        if not self.is_switching_data:
            if is_connected and not self.data_switch.value:
                self.data_switch.value = True
                self.update()
            elif is_disconnected and self.data_switch.value:
                self.data_switch.value = False
                self.update()
    
    # 按钮锁死助手函数
    def _toggle_network_lock(self, disabled: bool):
        # 同时禁用/启用：数据开关、应用按钮、6个网络模式勾选框
        self.data_switch.disabled = disabled
        self.btn_net_mode_apply.disabled = disabled
        for cb in self.net_mode_cbs.values():
            cb.disabled = disabled
            
        # 跨区域联动：同时物理变灰锁死顶部的“刷新”和卡片内的“刷新数据”按钮
        if hasattr(self, 'top_refresh_btn'):
            self.top_refresh_btn.disabled = disabled
            self.top_refresh_btn.update()
        
        # 强制瞬间刷新控件
        self.data_switch.update()
        self.btn_net_mode_apply.update()
        for cb in self.net_mode_cbs.values():
            cb.update()

    # 界面交互代码
    async def on_data_switch_change(self, e):
        if self.is_switching_data:
            self.data_switch.value = not self.data_switch.value
            self.data_switch.update()
            return

        self.is_switching_data = True
        self._toggle_network_lock(True)  # 一键锁死整个网络模式区域

        is_on = self.data_switch.value
        show_toast(self.app_page, f"正在下发{'开启' if is_on else '关闭'}指令...", True)
        try:
            cmd = "CONNECT_NETWORK" if is_on else "DISCONNECT_NETWORK"
            ok = await self.api_client.post_cmd(cmd, {"notCallback": "true"})
            if ok:
                self.set_global_status(f"正在{'开启' if is_on else '关闭'}数据，请等待生效...", ft.Colors.PRIMARY)
            else:
                self.set_global_status("数据状态切换失败", ft.Colors.ERROR)
                show_toast(self.app_page, "数据状态切换失败", False)
                self.data_switch.value = not is_on
        except Exception as e:
            logger.error(f"数据状态切换异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("数据状态切换异常", ft.Colors.ERROR)
            show_toast(self.app_page, "数据状态切换异常", False)
            self.data_switch.value = not is_on
        finally:
            await asyncio.sleep(5)  # 物理死锁5秒
            self.is_switching_data = False
            self._toggle_network_lock(False)  # 5秒后解禁
            self.update()

    async def on_wifi_sleep_save(self, e):
        try:
            if await self.api_client.set_wifi_sleep(self.wifi_sleep.value):
                self.set_global_status("WiFi 休眠设置已保存", ft.Colors.PRIMARY)
                show_toast(self.app_page, "WiFi 休眠设置保存成功", True)
            else:
                self.set_global_status("保存失败", ft.Colors.ERROR)
                show_toast(self.app_page, "WiFi 休眠设置保存失败", False)
        except Exception as e:
            logger.error(f"保存WiFi休眠异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("保存失败", ft.Colors.ERROR)
        self.update()

    async def on_apply_lte(self, e):
        if not self.lte_selected:
            show_toast(self.app_page, "请至少勾选一个 4G 频段", False)
            return
        try:
            if await self.api_client.set_lte_band_lock(list(self.lte_selected)):
                self.set_global_status("4G 频段设置完成", ft.Colors.PRIMARY)
                show_toast(self.app_page, "4G 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者模式已解锁", ft.Colors.ERROR)
                show_toast(self.app_page, "4G 频段设置失败，请确认开发者模式已解锁", False)
        except Exception as e:
            logger.error(f"4G 频段设置异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("设置失败", ft.Colors.ERROR)
        self.update()

    async def on_apply_sa(self, e):
        if not self.nr_sa_selected:
            show_toast(self.app_page, "请至少勾选一个 5G SA 频段", False)
            return
        try:
            if await self.api_client.set_sa_band_lock(list(self.nr_sa_selected)):
                self.set_global_status("5G SA 频段设置完成", ft.Colors.PRIMARY)
                show_toast(self.app_page, "5G SA 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者模式已解锁", ft.Colors.ERROR)
                show_toast(self.app_page, "5G SA 频段设置失败，请确认开发者模式已解锁", False)
        except Exception as e:
            logger.error(f"5G SA 设置异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("设置失败", ft.Colors.ERROR)
        self.update()

    async def on_apply_nsa(self, e):
        if not self.nr_nsa_selected:
            show_toast(self.app_page, "请至少勾选一个 5G NSA 频段", False)
            return
        try:
            if await self.api_client.set_nsa_band_lock(list(self.nr_nsa_selected)):
                self.set_global_status("5G NSA 频段设置完成", ft.Colors.PRIMARY)
                show_toast(self.app_page, "5G NSA 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者模式已解锁", ft.Colors.ERROR)
                show_toast(self.app_page, "5G NSA 频段设置失败，请确认开发者模式已解锁", False)
        except Exception as e:
            logger.error(f"5G NSA 设置异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("设置失败", ft.Colors.ERROR)
        self.update()

    async def on_cell_lock(self, e):
        if not self.cell_pci.value or not self.cell_earfcn.value:
            show_toast(self.app_page, "请填写 PCI 与 ARFCN", False)
            return
        try:
            if await self.api_client.set_cell_lock(
                self.cell_pci.value.strip(), self.cell_earfcn.value.strip(),
                self.cell_band.value, self.cell_scs.value
            ):
                self.set_global_status("锁小区配置下发完成", ft.Colors.PRIMARY)
                show_toast(self.app_page, "锁小区成功", True)
            else:
                self.set_global_status("锁小区失败，请确认开发者模式已解锁", ft.Colors.ERROR)
                show_toast(self.app_page, "锁小区失败，请确认开发者模式已解锁", False)
        except Exception as e:
            logger.error(f"锁小区异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("锁小区失败", ft.Colors.ERROR)
        self.update()

    async def on_cell_unlock(self, e):
        try:
            if await self.api_client.unlock_cell():
                self.cell_pci.value = ""
                self.cell_earfcn.value = ""
                self.cell_band.value = "1"
                self.cell_scs.value = "15"
                self.set_global_status("小区锁定已解除", ft.Colors.PRIMARY)
                show_toast(self.app_page, "小区锁定已解除", True)
            else:
                self.set_global_status("解除失败，请确认开发者模式已解锁", ft.Colors.ERROR)
                show_toast(self.app_page, "解除锁定失败", False)
        except Exception as e:
            logger.error(f"解锁小区异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("解除失败", ft.Colors.ERROR)
        self.update()

    async def on_apply_net_mode(self, e):
        if self.is_switching_data:
            show_toast(self.app_page, "操作中，请勿频繁点击", False)
            return

        selected_val = "WL_AND_5G"
        for name, cb in self.net_mode_cbs.items():
            if cb.value:
                selected_val = NET_CONFIG[name]["write_val"]
                break
        
        self.is_switching_data = True
        self._toggle_network_lock(True)  # 一键锁死整个网络模式区域
        
        show_toast(self.app_page, "正在切换网络锁定，请稍候...", True)
        try:
            was_connected = self.data_switch.value
            ok = await self.api_client.switch_net_mode(selected_val, was_connected)
            if ok:
                self.set_global_status("网络配置已下发，等待生效...", ft.Colors.PRIMARY)
                show_toast(self.app_page, "网络切换指令已成功下发", True)
            else:
                self.set_global_status("设置失败或网络连接异常", ft.Colors.ERROR)
                show_toast(self.app_page, "网络切换失败", False)
        finally:
            await asyncio.sleep(5)  # 物理死锁5秒
            self.is_switching_data = False
            self._toggle_network_lock(False)  # 5秒后解禁
            self.update()

    # 应用 WiFi 覆盖范围
    async def on_apply_wifi_coverage(self, e):
        selected_val = "short_mode"
        for val, cb in self.wifi_coverage_cbs.items():
            if cb.value:
                selected_val = val
                break
                
        show_toast(self.app_page, "正在应用 WiFi 覆盖范围...", True)
        try:
            if await self.api_client.set_wifi_coverage(selected_val):
                self.set_global_status("WiFi 范围设置成功", ft.Colors.PRIMARY)
                show_toast(self.app_page, "WiFi 范围设置成功", True)
            else:
                self.set_global_status("WiFi 范围设置失败", ft.Colors.ERROR)
                show_toast(self.app_page, "WiFi 范围设置失败", False)
        except Exception as e:
            logger.error(f"WiFi覆盖设置异常: {e}", exc_info=DEBUG_MODE)
            self.set_global_status("设置异常", ft.Colors.ERROR)
        self.update()

    # 执行 WiFi 设置的实际逻辑
    async def _execute_apply_wifi_mode(self):
        mode = self.wifi_mode.value
        if not mode: return
        show_toast(self.app_page, "正在切换双频模式...", True)
        self.update()
        success = await self.api_client.apply_wifi_mode(is_merged=(mode == "merged"))
        if success:
            self.set_global_status("模式已切换，WiFi 将重启，请等待重连", ft.Colors.PRIMARY)
            show_toast(self.app_page, "模式切换成功，等待断网重连", True)
        else:
            show_toast(self.app_page, "执行失败，请检查网络", False)
        self.update()

    async def on_apply_wifi_mode(self, e):
        async def close_dlg(e):
            dlg.open = False
            if dlg in self.app_page.overlay:
                self.app_page.overlay.remove(dlg) # 彻底销毁弹窗，释放内存
            self.app_page.update()
        async def confirm_dlg(e):
            dlg.open = False
            if dlg in self.app_page.overlay:
                self.app_page.overlay.remove(dlg) # 彻底销毁弹窗，释放内存
            self.app_page.update()
            await self._execute_apply_wifi_mode()
            
        dlg = ft.AlertDialog(
            bgcolor=ft.Colors.SURFACE, title_padding=ft.Padding(0,0,0,0), content_padding=ft.Padding(0,0,0,0), actions_padding=ft.Padding(0,0,0,0), inset_padding=ft.Padding(10, 24, 10, 24),
            content=ft.Container(
                height=70, alignment=ft.Alignment(0, 0), padding=ft.Padding(10, 0, 10, 0),
                content=ft.Row(
                    controls=[
                        ft.Container(content=ft.TextButton("取消", on_click=close_dlg, style=ft.ButtonStyle(color=ft.Colors.ON_SURFACE_VARIANT)), expand=True, alignment=ft.Alignment(0, 0)),
                        ft.Container(content=ft.TextButton("确认", on_click=confirm_dlg, style=ft.ButtonStyle(color=ft.Colors.PRIMARY)), expand=True, alignment=ft.Alignment(0, 0)),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=5
                )
            )
        )
        self.app_page.overlay.append(dlg)
        dlg.open = True
        self.app_page.update()

    def update_wifi_sync_state(self):
        sync = bool(getattr(self, "wifi_sync_to_5g", None) and self.wifi_sync_to_5g.value and self.actual_wifi_mode == "separated")
        controls = getattr(self, "wifi_detail_5g", {})
        for key in ["broadcast", "isolate", "auth", "password"]:
            if key in controls:
                controls[key].disabled = sync
        if sync and hasattr(self, "wifi_detail_24g"):
            controls["broadcast"].value = self.wifi_detail_24g["broadcast"].value
            controls["isolate"].value = self.wifi_detail_24g["isolate"].value
            controls["auth"].value = self.wifi_detail_24g["auth"].value
            controls["password"].value = self.wifi_detail_24g["password"].value

    def _read_wifi_detail_controls(self, controls: Dict) -> Dict:
        auth = controls["auth"].value or "WPA2PSK"
        encryp_map = {
            "OPEN": "NONE",
            "WPA2PSK": "CCMP",
            "WPAPSKWPA2PSK": "TKIPCCMP",
            "WPA3PSK": "CCMP",
            "WPA2PSKWPA3PSK": "CCMP",
        }
        return {
            "ssid": controls["ssid"].value or "",
            "broadcast": bool(controls["broadcast"].value),
            "isolate": bool(controls["isolate"].value),
            "auth": auth,
            "encryp": encryp_map.get(auth, "CCMP"),
            "password": controls["password"].value or "",
        }

    async def _execute_apply_wifi_detail(self):
        mode = self.actual_wifi_mode
        if not mode:
            return
        self.update_wifi_sync_state()
        detail_24g = self._read_wifi_detail_controls(self.wifi_detail_24g)
        detail_5g = self._read_wifi_detail_controls(self.wifi_detail_5g)
        sync_to_5g = bool(getattr(self, "wifi_sync_to_5g", None) and self.wifi_sync_to_5g.value and mode == "separated")
        show_toast(self.app_page, "正在应用 WiFi 详细设置...", True)
        self.update()
        success = await self.api_client.apply_wifi_detail(mode == "merged", detail_24g, detail_5g, sync_to_5g)
        if success:
            self.set_global_status("WiFi 详细设置已保存，WiFi 将重启", ft.Colors.PRIMARY)
            show_toast(self.app_page, "WiFi 详细设置保存成功", True)
        else:
            show_toast(self.app_page, "WiFi 详细设置保存失败", False)
        self.update()

    async def on_apply_wifi_detail(self, e):
        await self._execute_apply_wifi_detail()

# ==========================================
# UI 组件拆分 - 设备列表卡片
# ==========================================
class DeviceListCard(ft.Container):
    def __init__(self, page: ft.Page, on_block_device: Callable = None, on_unblock_device: Callable = None):  
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12)
        self.app_page = page 
        self.on_block_device = on_block_device
        self.on_unblock_device = on_unblock_device
        self.is_small_layout = False
        self.is_ultra_small_layout = False
        self._last_data_hash = {}
        
        # 接入设备
        self.txt_device_label = ft.Text("接入设备", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.txt_device_count = ft.Text("0 台", size=14, color=ft.Colors.ON_SURFACE)
        
        # 卡片横向撑满
        self.device_list_col = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        
        self.content = ft.Column([
            ft.Column([self.txt_device_label, self.txt_device_count], spacing=2),
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            self.device_list_col
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def update_realtime(self, status: 'RealtimeStatus'):
        # 动态计算显示数量
        available_height = self.app_page.height - 250
        display_limit = max(4, int(available_height / 65)) 
        
        blacklisted_devices = getattr(status, "blacklisted_devices", [])
        black_macs = {str(dev.get("mac", "")).upper() for dev in blacklisted_devices}
        dev_hash = f"{display_limit}_{self.is_small_layout}_{self.is_ultra_small_layout}_{str(status.connected_devices)}_{str(blacklisted_devices)}"
        
        if self._last_data_hash.get('device_list') != dev_hash:
            name_size = 10 if self.is_ultra_small_layout else (12 if self.is_small_layout else 15)
            detail_size = 9 if self.is_ultra_small_layout else (10 if self.is_small_layout else 13)
            item_padding = 6 if self.is_ultra_small_layout else (8 if self.is_small_layout else 10)
            item_spacing = 3 if self.is_ultra_small_layout else (5 if self.is_small_layout else 8)
            button_height = 30 if self.is_ultra_small_layout else (34 if self.is_small_layout else 36)
            button_width = max(120, int(self.app_page.width - 70)) if self.is_small_layout else None
            button_text_size = 11 if self.is_ultra_small_layout else (13 if self.is_small_layout else 14)
            self.txt_device_count.value = f"{status.macs_count} 台"
            self.device_list_col.controls.clear()
            if not status.connected_devices:
                self.device_list_col.controls.append(
                    ft.Text("暂无设备连接", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
                )
            else:
                for i, dev in enumerate(status.connected_devices[:display_limit]):
                    is_blocked = str(dev.get("mac", "")).upper() in black_macs
                    action_btn = create_button(
                        "已拉黑" if is_blocked else "拉黑",
                        on_click=((lambda e, d=dev: self.on_unblock_device and self.on_unblock_device(d)) if is_blocked else (lambda e, d=dev: self.on_block_device and self.on_block_device(d))),
                        height=button_height,
                        expand=False
                    )
                    if button_width:
                        action_btn.width = button_width
                    if action_btn.style and getattr(action_btn.style, "text_style", None):
                        action_btn.style.text_style.size = button_text_size
                    text_col = ft.Column([
                        ft.Text(f"{dev['name']}", size=name_size, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE),
                        ft.Text(f"IP: {dev['ip']}", size=detail_size, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"MAC: {dev.get('mac', '未知')}", size=detail_size, color=ft.Colors.ON_SURFACE_VARIANT)
                    ], spacing=1 if self.is_ultra_small_layout else 2, expand=not self.is_small_layout)
                    item_content = ft.Column([
                        text_col,
                        ft.Container(action_btn, alignment=ft.Alignment(0, 0))
                    ], spacing=item_spacing) if self.is_small_layout else ft.Row([
                        text_col,
                        action_btn
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    self.device_list_col.controls.append(
                        ft.Container(
                            content=item_content,
                            padding=item_padding,
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            border_radius=8
                        )
                    )
            self._last_data_hash['device_list'] = dev_hash
            self.update()

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        layout_changed = self.is_small_layout != is_small or self.is_ultra_small_layout != is_ultra_small
        self.is_small_layout = is_small
        self.is_ultra_small_layout = is_ultra_small
        self.padding = 8 if is_ultra_small else (12 if is_small else 15)
        self.border_radius = 8 if is_ultra_small else 12
        self.content.spacing = 6 if is_ultra_small else (8 if is_small else 10)
        self.device_list_col.spacing = 5 if is_ultra_small else (7 if is_small else 10)
        self.txt_device_label.size = 12 if is_ultra_small else (18 if not is_small else 16)
        self.txt_device_count.size = 11 if is_ultra_small else 14
        if layout_changed:
            self._last_data_hash.clear()
        try:
            self.update()
        except Exception:
            pass

# ==========================================
# 主程序：应用类封装
# ==========================================
class MU5001:
    def __init__(self, page: ft.Page):
        self.page = page
        logger.info("应用启动，初始化主页面")
        
        # 1. 页面基础设置
        self.page.title = "MU5001"
        self.page.padding = 0
        
        # 挂载深色主题配色字典 (直接原封不动传给引擎)
        self.page.dark_theme = ft.Theme(
            font_family="Source Han Sans SC, Noto Sans SC, Microsoft YaHei, sans-serif",
            color_scheme=ft.ColorScheme(**ThemeColors.DARK_SCHEME)
        )
        
        # 挂载浅色主题配色字典 (直接原封不动传给引擎)
        self.page.theme = ft.Theme(
            font_family="Source Han Sans SC, Noto Sans SC, Microsoft YaHei, sans-serif",
            color_scheme=ft.ColorScheme(**ThemeColors.LIGHT_SCHEME)
        )
        self.apply_responsive_text_theme(14)
        
        # 设定初始状态为深色模式，并赋予独立的页面背景色
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = ThemeColors.DARK_PAGE_BG
        
        # 2. 全局状态初始化
        self.device_state = DeviceState()
        self.client = MU5001Client(self.device_state)
        self.auto_refresh_task: Optional[asyncio.Task] = None
        self.is_refreshing = False
        self.current_is_small = None
        self.tool_item_texts: List[ft.Text] = []
        self.prefs = None
        self._resize_task = None
        
        # 网络连接状态变量
        self.offline_count = 0
        self.is_connected = True

    def apply_responsive_text_theme(self, font_size: int):
        title_size = font_size + 4  # 标题永远比正文大4号，跟随正文一起自动缩放
        text_theme = ft.TextTheme(
            body_medium=ft.TextStyle(size=font_size),
            body_large=ft.TextStyle(size=font_size),
            label_medium=ft.TextStyle(size=font_size),
            label_large=ft.TextStyle(size=font_size),
            title_small=ft.TextStyle(size=title_size),
            title_medium=ft.TextStyle(size=title_size),
        )
        if self.page.theme:
            self.page.theme.text_theme = text_theme
        if self.page.dark_theme:
            self.page.dark_theme.text_theme = text_theme

    def is_control_mounted(self, control) -> bool:
        try:
            return bool(control and control.page)
        except RuntimeError:
            return False

    async def start(self):
        # 尝试初始化本地存储
        try:
            self.prefs = ft.SharedPreferences()
        except Exception as e:
            logger.warning(f"SharedPreferences 初始化失败: {e}")

        # 绑定系统亮度变化事件
        self.page.on_platform_brightness_change = self.on_platform_brightness_change

        # 读取并应用保存的主题 (默认改为 SYSTEM)
        saved_theme = "SYSTEM"
        if self.prefs:
            try:
                if hasattr(self.prefs, "get_async"):
                    saved_theme = await self.prefs.get_async("saved_theme") or "SYSTEM"
                else:
                    saved_theme = await self.prefs.get("saved_theme") or "SYSTEM"
            except Exception:
                pass

        # 实例化各个 UI 业务组件
        self.login_view = LoginView(self.page, self.client, self.prefs, on_login_success=self.on_login_success)
        self.status_card = StatusCard()
        self.reboot_card = RebootCard(self.page, self.client, set_global_status_cb=self.status_card.set_global_status)
        self.settings_card = SettingsCard(self.page, self.client, set_global_status_cb=self.status_card.set_global_status, on_reboot_cb=self.on_reboot_device)
        self.device_list_card = DeviceListCard(self.page, on_block_device=self.on_block_device, on_unblock_device=self.on_unblock_device)

        # 构建主视图布局 (这一步会创建 self.theme_btn)
        self.build_main_view()

        # 统一调用主题应用方法
        self.current_theme_str = saved_theme
        await self.apply_theme(saved_theme)

        # 绑定页面全局事件
        self.page.on_resize = self.on_page_resize
        self.page.on_disconnect = self.on_disconnect

        # 挂载到页面并初始化排版
        self.page.add(self.login_view, self.main_view)
        if self.page.width > 0:
            self.on_page_resize(None)
        self.page.update()

        # 读取存储并尝试自动登录
        await self.login_view.init_from_storage()

    def _create_tool_item(self, icon, text, on_click):
        btn = create_button(text, on_click=on_click, height=48, expand=True)
        if hasattr(self, 'network_action_buttons'):
            self.network_action_buttons.append(btn)
        return btn

    def show_toolbox_menu(self, e):
        self.toolbox_menu.visible = True
        self.toolbox_content.visible = False
        self.view_toolbox.update()

    def show_wifi_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        # 显示WiFi，隐藏重启
        self.settings_card.wifi_section.visible = True
        self.reboot_card.visible = False
        self.view_toolbox.update()

    def show_reboot_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        # 隐藏WiFi，显示重启
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = True
        self.view_toolbox.update()

    # 显示/隐藏断网界面的方法
    def show_disconnected_ui(self):
        self.content_area.visible = False
        self.disconnected_view.visible = True
        self.page.update()

    def show_connected_ui(self):
        self.content_area.visible = True
        self.disconnected_view.visible = False
        self.page.update()

    def build_main_view(self):
        # 全新设计的顶部统一导航栏 (完美对齐、防遮挡、自适应)
        self.current_nav_index = 0  # 记录当前所在的页面索引

        def handle_nav_click(idx):
            self.current_nav_index = idx  # 每次切换时更新索引
            self.view_network_info.visible = (idx == 0)
            self.view_network_settings.visible = (idx == 1)
            self.view_device_list.visible = (idx == 2)
            self.view_toolbox.visible = (idx == 3)
            # 点击后更新文字和图标颜色
            for i, btn in enumerate(self.nav_btns):
                color = ft.Colors.PRIMARY if i == idx else ft.Colors.ON_SURFACE_VARIANT
                btn.content.controls[0].color = color
                btn.content.controls[1].color = color
            self.page.update()

        # 滑动手势
        self.swipe_accum = 0
        self.swipe_locked = False

        def on_drag_start(e):
            self.swipe_accum = 0
            self.swipe_locked = False

        def on_drag_update(e: ft.DragUpdateEvent):
            if self.swipe_locked:
                return
            
            self.swipe_accum += e.primary_delta
            
            # 滑动距离超过 40 像素就触发切换页面
            if self.swipe_accum < -40:
                if self.current_nav_index == 3 and self.toolbox_content.visible:
                    self.show_toolbox_menu(None)
                    self.swipe_locked = True
                    return
                if self.current_nav_index < 3:
                    handle_nav_click(self.current_nav_index + 1)
                self.swipe_locked = True
            elif self.swipe_accum > 40:
                if self.current_nav_index == 3 and self.toolbox_content.visible:
                    self.show_toolbox_menu(None)
                    self.swipe_locked = True
                    return
                if self.current_nav_index > 0:
                    handle_nav_click(self.current_nav_index - 1)
                self.swipe_locked = True

        # 核心：所有 7 个按钮（导航+操作）使用完全相同的底层结构，保证 100% 绝对对齐
        def create_nav_btn(icon, text, on_click_handler, is_active=False):
            color = ft.Colors.PRIMARY if is_active else ft.Colors.ON_SURFACE_VARIANT
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(icon, size=22, color=color),
                        ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=color, max_lines=1)
                    ],
                    alignment=ft.MainAxisAlignment.END, # 【修改】垂直方向强制底部对齐
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4 
                ),
                padding=ft.Padding(left=0, top=6, right=0, bottom=6), 
                alignment=ft.Alignment(0, 1), # 【修改】容器内整体靠下放置
                on_click=on_click_handler
            )

        # 1. 左侧导航按钮
        self.nav_btns = [
            create_nav_btn(ft.Icons.LANGUAGE, "信息", lambda e: handle_nav_click(0), True),
            create_nav_btn(ft.Icons.LOCK_OUTLINE, "锁频", lambda e: handle_nav_click(1)),
            create_nav_btn(ft.Icons.DEVICES, "设备", lambda e: handle_nav_click(2)),
            create_nav_btn(ft.Icons.APPS, "工具", lambda e: handle_nav_click(3))
        ]

        # 2. 右侧操作按钮
        self.logout_btn = create_nav_btn(ft.Icons.LOGOUT, "退出", self.do_logout)
        self.theme_btn_container = create_nav_btn(ft.Icons.DARK_MODE, "主题", self.toggle_theme)
        self.top_refresh_btn = create_nav_btn(ft.Icons.REFRESH, "刷新", self.refresh_all)
        self.action_btns = [self.logout_btn, self.theme_btn_container, self.top_refresh_btn]

        # 将 theme_btn 指向内部的 Icon，兼容后续的主题切换逻辑
        self.theme_btn = self.theme_btn_container.content.controls[0]

        # 顶部导航栏容器
        self.top_header_bar = ft.Container(padding=0, margin=0)

        # 视图关联按钮 (兼容原有逻辑)
        btn_refresh = create_button("刷新数据", on_click=self.refresh_all, expand=True)
        btn_reboot_top = create_button("重启设备", on_click=self.on_reboot_device, expand=True)
        self.network_action_buttons = [btn_refresh, btn_reboot_top]
        self.settings_card.top_refresh_btn = self.top_refresh_btn
        self.settings_card.refresh_btn = btn_refresh

        # 视图 1：网络信息
        self.view_network_info = ft.Column(
            [
                self.status_card, 
                ft.Container(height=5), 
                ft.ResponsiveRow([
                    ft.Container(btn_refresh, col={"xs": 12, "sm": 6}),
                    ft.Container(btn_reboot_top, col={"xs": 12, "sm": 6})
                ], spacing=10, run_spacing=10)
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, 
            alignment=ft.MainAxisAlignment.CENTER,
            scroll=ft.ScrollMode.AUTO, 
            expand=True
        )

        # 视图 2：网络设置
        self.view_network_settings = ft.Column(
            [self.settings_card],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, scroll=ft.ScrollMode.AUTO, expand=True, visible=False
        )

        # 视图 3：设备列表
        self.view_device_list = ft.Column(
            [self.device_list_card],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, scroll=ft.ScrollMode.AUTO, expand=True, visible=False
        )

        # 视图 4：工具箱
        self.toolbox_items = [
            ft.Container(self._create_tool_item(ft.Icons.WIFI, "WiFi 设置", self.show_wifi_settings), col={"xs": 12, "sm": 6}),
            ft.Container(self._create_tool_item(ft.Icons.RESTART_ALT, "定时重启", self.show_reboot_settings), col={"xs": 12, "sm": 6}),
        ]
        self.toolbox_menu = ft.ResponsiveRow(controls=self.toolbox_items, spacing=14, run_spacing=14)
        
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = False
        
        # 独立出来的返回按钮（不参与滚动）
        self.toolbox_back_btn = ft.Container(
            content=ft.IconButton(ft.Icons.ARROW_BACK, on_click=self.show_toolbox_menu, icon_color=ft.Colors.ON_SURFACE),
            visible=False,
            padding=ft.Padding(0, 0, 0, 0)
        )

        # 移除了返回按钮的纯内容区
        self.toolbox_content = ft.Column([
            self.settings_card.wifi_section,
            self.reboot_card
        ], visible=False)

        # 内部滚动容器
        self.view_toolbox_scroll = ft.Column(
            [self.toolbox_menu, self.toolbox_content],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, scroll=ft.ScrollMode.AUTO, expand=True
        )

        # 最外层容器：固定返回键 + 滚动内容，外层自身禁止滚动
        self.view_toolbox = ft.Column(
            [self.view_toolbox_scroll],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, expand=True, visible=False
        )

        self.content_area = ft.Column(
            [self.view_network_info, self.view_network_settings, self.view_device_list, self.view_toolbox],
            expand=True
        )

        # 未连接路由器的提示界面
        # 1. 提取出图标、文字和按钮，方便后续根据屏幕大小自动缩放
        self.disconnect_icon = ft.Icon(ft.Icons.ROUTER_OUTLINED, size=80, color=ft.Colors.PRIMARY)
        # 强制文字居中对齐，防止在极窄屏幕下换行时偏向左侧
        self.disconnect_text = ft.Text("未连接 WiFi", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, text_align=ft.TextAlign.CENTER)
        self.disconnect_btn = create_button("重新登录", on_click=self.do_relogin, expand=False)
        
        self.disconnected_view = ft.Container(
            content=ft.Column(
                [
                    self.disconnect_icon,
                    self.disconnect_text,
                    ft.Container(height=10), # 稍微缩小一点按钮和文字的间距
                    self.disconnect_btn
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=5
            ),
            expand=True,
            visible=False,
            alignment=ft.Alignment(0, 0)
        )
        # 用 Stack 将主页面和提示界面叠放
        self.main_content_wrapper = ft.Stack(
            controls=[self.content_area, self.disconnected_view],
            expand=True
        )

        # 手势检测器
        self.gesture_area = ft.GestureDetector(
            content=self.content_area,
            on_horizontal_drag_start=on_drag_start,
            on_horizontal_drag_update=on_drag_update,
            expand=True
        )
        
        # 使用 ft.SafeArea 实现状态栏自适应
        self.main_view = ft.Container(
            padding=15, expand=True, visible=False,
            content=ft.GestureDetector(
                content=ft.SafeArea(
                    content=ft.Column(
                        [
                            self.top_header_bar,
                            ft.Divider(height=10, thickness=2, color=ft.Colors.OUTLINE_VARIANT),
                            self.main_content_wrapper  # 用 wrapper 实现了界面层叠
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH, spacing=0, expand=True
                    )
                ),
                on_horizontal_drag_start=on_drag_start,
                on_horizontal_drag_update=on_drag_update,
                expand=True
            )
        )

    # 业务交互与任务调度
    async def on_reboot_device(self, e=None):
        show_toast(self.page, "正在发送重启指令...", True)
        try:
            if await self.client.post_cmd("REBOOT_DEVICE"):
                self.status_card.set_global_status("重启指令已发送，设备即将重启", ft.Colors.PRIMARY)
                show_toast(self.page, "设备即将重启", True)
            else:
                self.status_card.set_global_status("重启失败", ft.Colors.ERROR)
                show_toast(self.page, "设备重启失败", False)
        except Exception as e:
            logger.error(f"重启设备异常: {e}", exc_info=DEBUG_MODE)
            self.status_card.set_global_status("重启失败", ft.Colors.ERROR)
            show_toast(self.page, "设备重启失败", False)

    def on_block_device(self, dev: dict):
        asyncio.create_task(self._block_device(dev))

    def on_unblock_device(self, dev: dict):
        asyncio.create_task(self._unblock_device(dev))

    async def _block_device(self, dev: dict):
        mac = str(dev.get("mac", "")).strip().upper()
        name = str(dev.get("name", "")).strip() or mac
        if not mac:
            show_toast(self.page, "设备 MAC 为空", False)
            return
        show_toast(self.page, "正在拉黑设备...", True)
        try:
            ok = await self.client.block_device(mac, name)
            if ok:
                self.device_list_card._last_data_hash.clear()
                await self.fetch_realtime()
                show_toast(self.page, "设备已拉黑", True)
            else:
                show_toast(self.page, "拉黑失败", False)
        except Exception as e:
            logger.error(f"拉黑设备异常: {e}", exc_info=DEBUG_MODE)
            show_toast(self.page, "拉黑失败", False)

    async def _unblock_device(self, dev: dict):
        mac = str(dev.get("mac", "")).strip().upper()
        if not mac:
            show_toast(self.page, "设备 MAC 为空", False)
            return
        show_toast(self.page, "正在解除拉黑...", True)
        try:
            ok = await self.client.unblock_device(mac)
            if ok:
                self.device_list_card._last_data_hash.clear()
                await self.fetch_realtime()
                show_toast(self.page, "已解除拉黑", True)
            else:
                show_toast(self.page, "解除失败", False)
        except Exception as e:
            logger.error(f"解除拉黑异常: {e}", exc_info=DEBUG_MODE)
            show_toast(self.page, "解除失败", False)

    # 动态切换主题函数
    async def apply_theme(self, theme_str: str):
        self.current_theme_str = theme_str
        
        if theme_str == "LIGHT":
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.page.bgcolor = ThemeColors.LIGHT_PAGE_BG
            self.theme_btn.icon = ft.Icons.LIGHT_MODE
            self.theme_btn.tooltip = None
        elif theme_str == "DARK":
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.bgcolor = ThemeColors.DARK_PAGE_BG
            self.theme_btn.icon = ft.Icons.DARK_MODE
            self.theme_btn.tooltip = None
        else: 
            # SYSTEM (跟随系统)
            self.page.theme_mode = ft.ThemeMode.SYSTEM
            # 获取当前系统的真实亮度来决定你的自定义背景色
            is_dark = self.page.platform_brightness == ft.Brightness.DARK
            self.page.bgcolor = ThemeColors.DARK_PAGE_BG if is_dark else ThemeColors.LIGHT_PAGE_BG
            # 使用一个代表“自动”的图标
            self.theme_btn.icon = ft.Icons.BRIGHTNESS_AUTO
            self.theme_btn.tooltip = None

        if self.page.width > 0 and self.is_control_mounted(self.main_view):
            self.current_layout_key = None
            self.on_page_resize(None)
            
        # 保存主题选择到本地
        if self.prefs:
            try:
                if hasattr(self.prefs, "set_async"):
                    await self.prefs.set_async("saved_theme", theme_str)
                else:
                    await self.prefs.set("saved_theme", theme_str)
            except Exception as ex:
                logger.warning(f"保存主题偏好失败: {ex}")
                
        self.page.update()

    # 点击按钮时循环切换主题: 跟随系统 -> 深色 -> 浅色
    async def toggle_theme(self, e):

        if getattr(self, "current_theme_str", "SYSTEM") == "SYSTEM":
            target = "DARK"
        elif self.current_theme_str == "DARK":
            target = "LIGHT"
        else:
            target = "SYSTEM"
            
        await self.apply_theme(target)

    def on_platform_brightness_change(self, e):

        # 只有在“跟随系统”模式下，才去动态更新自定义背景色
        if self.page.theme_mode == ft.ThemeMode.SYSTEM:
            is_dark = self.page.platform_brightness == ft.Brightness.DARK
            self.page.bgcolor = ThemeColors.DARK_PAGE_BG if is_dark else ThemeColors.LIGHT_PAGE_BG
            if self.page.width > 0 and self.is_control_mounted(self.main_view):
                self.current_layout_key = None
                self.on_page_resize(None)
            self.page.update()

    def start_auto_refresh(self):
        if self.auto_refresh_task and not self.auto_refresh_task.done():
            self.auto_refresh_task.cancel()
        self.is_refreshing = False
        self.auto_refresh_task = asyncio.create_task(self._refresh_worker())
        logger.info("自动刷新任务已启动")

    async def _refresh_worker(self):
        try:
            while True:
                await asyncio.sleep(AUTO_REFRESH_INTERVAL)
                # 只有客户端在线且主界面显示时才刷新
                if not (self.device_state.client and self.main_view.visible):
                    continue
                if self.is_refreshing:
                    continue
                self.is_refreshing = True
                try:
                    await self.fetch_realtime()
                except Exception as e:
                    logger.debug(f"后台刷新异常: {e}")
                finally:
                    self.is_refreshing = False
        except asyncio.CancelledError:
            logger.info("自动刷新任务已停止")

    async def fetch_realtime(self):
        if not self.device_state.client:
            return
        try:
            # 拿到强类型数据对象
            status = await self.client.get_realtime_status()
            
            # 精准识别“掉线”
            # 如果核心字段（IMSI、主板温度）同时为空，说明凭证已失效
            is_kicked_out = (
                not status.imsi and 
                status.temp_mdm in ("", "--")
            )
            if is_kicked_out:
                self.offline_count += 1
                if self.offline_count < OFFLINE_FAIL_THRESHOLD:
                    logger.debug(f"疑似凭证失效，等待复核: {self.offline_count}/{OFFLINE_FAIL_THRESHOLD}")
                    return
                raise RuntimeError("凭证已失效，设备已掉线")
            
            # 恢复连接时的处理
            if not self.is_connected:
                self.is_connected = True
                self.show_connected_ui()
            self.offline_count = 0  # 成功拿到数据，重置断网计数
            
            self.reboot_card.update_time_display()
            # 直接把对象丢给卡片
            self.status_card.update_realtime(status)
            self.device_list_card.update_realtime(status)
            
            # 原本的 settings_card 只需要判断数据连接开关，这里做个兼容包装
            self.settings_card.update_realtime({"ppp_status": "connected" if status.is_data_connected else "disconnected"})
        except Exception as e:
            logger.debug(f"实时刷新异常: {e}")
            
            # 断网判定处理
            self.offline_count += 1
            if self.offline_count >= OFFLINE_FAIL_THRESHOLD and self.is_connected:
                self.is_connected = False
                self.show_disconnected_ui()

    async def refresh_all(self, e=None):
        if not self.device_state.client:
            return
        self.status_card.set_global_status("正在读取设备信息...", ft.Colors.ON_SURFACE)
        try:
            cmd = (
                "sysIdleTimeToSleep,lte_band_lock,nr5g_sa_band_lock,nr5g_nsa_band_lock,"
                "nr5g_cell_lock,reboot_schedule_enable,reboot_schedule_mode,reboot_hour1,"
                "reboot_min1,reboot_timeframe_hours1,reboot_dow,reboot_dod,"
                "wifi_lbd_enable,wifi_syncparas_flag" 
            )
            res = await self.client.get_cmd(cmd, multi_data=True)
            try:
                sync_res = await self.client.get_cmd("wifi_syncparas_flag")
                if "wifi_syncparas_flag" in sync_res:
                    res["wifi_syncparas_flag"] = sync_res.get("wifi_syncparas_flag", "0")
            except Exception as sync_ex:
                logger.warning(f"读取 WiFi 同步状态失败: {sync_ex}")
            
            # 向隐藏接口索要 2.4G 和 5G 的真实物理开关状态及广播状态
            try:
                ap_info = await self.client.get_cmd("queryAccessPointInfo")
                if ap_info and "ResponseList" in ap_info:
                    for ap in ap_info["ResponseList"]:
                        # 抓取 2.4G 主网络
                        if ap.get("ChipIndex") == "0" and ap.get("AccessPointIndex") == "0":
                            res["real_24g_status"] = ap.get("AccessPointSwitchStatus")
                            # 抓取广播状态 (0为开启广播，1为隐藏)
                            res["ap_broadcast_24g"] = ap.get("ApBroadcastDisabled", "0") 
                            res["wifi_detail_24g"] = ap
                        # 抓取 5G 主网络
                        elif ap.get("ChipIndex") == "1" and ap.get("AccessPointIndex") == "0":
                            res["real_5g_status"] = ap.get("AccessPointSwitchStatus")
                            res["ap_broadcast_5g"] = ap.get("ApBroadcastDisabled", "0")
                            res["wifi_detail_5g"] = ap
            except Exception as ap_ex:
                logger.warning(f"获取底层AP状态失败: {ap_ex}")

            sa_res = await self.client.get_cmd("nr5g_sa_band_lock")
            nsa_res = await self.client.get_cmd("nr5g_nsa_band_lock")
            net_res = await self.client.get_cmd(API_KEY_READ)
            
            # 单独发一次不带 multi_data 的请求
            try:
                cov_res = await self.client.get_cmd("queryWiFiCoverage")
                res["WiFiCoverage"] = cov_res.get("WiFiCoverage", "")
            except Exception as e:
                logger.error(f"读取 WiFi 覆盖范围失败: {e}")

            current_net_mode = str(net_res.get(API_KEY_READ, "")).strip().upper()
            
            self.reboot_card.update_config(res)
            self.settings_card.update_config(
                res, 
                sa_res.get("nr5g_sa_band_lock", ""), 
                nsa_res.get("nr5g_nsa_band_lock", ""), 
                current_net_mode
            )

            dev_status = " | 开发者模式已解锁" if self.device_state.dev_unlocked else " | 开发者模式未解锁"
            self.status_card.set_global_status("数据读取成功" + dev_status, ft.Colors.PRIMARY if self.device_state.dev_unlocked else ft.Colors.ERROR)
            
            await self.fetch_realtime()
            if e:
                show_toast(self.page, "数据刷新成功", True)
            logger.info("全量配置刷新完成")
        except Exception as ex: # 注意这里用了 ex 防止和参数 e 冲突
            logger.error(f"全量刷新异常: {ex}", exc_info=DEBUG_MODE)
            self.status_card.set_global_status("读取失败，请检查连接", ft.Colors.ERROR)
            if e:
                show_toast(self.page, "数据读取失败，请检查连接", False)

    async def on_login_success(self):
        self.login_view.visible = False
        self.main_view.visible = True
        self.page.update()
        await self.refresh_all()
        self.start_auto_refresh()

    async def do_relogin(self, e=None):
        # 拦截：网络模块正在5秒死锁期，严禁执行重登
        if self.settings_card.is_switching_data:
            show_toast(self.page, "网络操作中，请稍后再重登", False)
            return

        if not self.device_state.ip or not self.device_state.password:
            show_toast(self.page, "本地无缓存密码，请重启 APP", False)
            return

        # 重登前先强制取消后台自动刷新任务，防止并发请求时底层客户端被销毁导致报错
        if self.auto_refresh_task and not self.auto_refresh_task.done():
            self.auto_refresh_task.cancel()
            self.auto_refresh_task = None

        show_toast(self.page, "正在重登...", True)
        try:
            success = await self.client.login(self.device_state.ip, self.device_state.password)
            if success:
                dev_ok = await self.client.unlock_developer()
                try:
                    await self.client.post_cmd("CONNECT_NETWORK", {"notCallback": "true"})
                    self.settings_card.data_switch.value = True
                    self.settings_card.update()
                except Exception as conn_err:
                    logger.warning(f"重登成功，开启数据连接失败: {conn_err}")

                if dev_ok:
                    self.status_card.set_global_status("重登成功，开发者模式解锁成功，正在开启数据连接", ft.Colors.PRIMARY)
                    show_toast(self.page, "重登成功，开发者模式解锁成功，正在开启数据连接", True)
                else:
                    self.status_card.set_global_status("重登成功，开发者模式解锁失败", ft.Colors.ERROR)
                    show_toast(self.page, "重登成功，开发者模式解锁失败", False)
                
                await self.refresh_all()
                
                # 重登和全量刷新顺利完成后，重新启动后台刷新任务
                self.start_auto_refresh()
            else:
                self.status_card.set_global_status("重新登录失败，可能密码已修改或被锁定", ft.Colors.ERROR)
                show_toast(self.page, "重登失败", False)
        except Exception as ex: # 注意这里用了 ex 防止和参数 e 冲突
            logger.error(f"重新登录异常: {ex}", exc_info=DEBUG_MODE)
            self.status_card.set_global_status("重登失败，请检查网络", ft.Colors.ERROR)
            show_toast(self.page, "重登失败，请检查网络", False)
    async def do_logout(self, e=None):
        await self.client.close()
        if self.auto_refresh_task and not self.auto_refresh_task.done():
            self.auto_refresh_task.cancel()
            self.auto_refresh_task = None
        self.device_state.dev_unlocked = False
        await self.login_view.clear_credentials_and_reset()
        self.main_view.visible = False
        self.login_view.visible = True
        show_toast(self.page, "已安全退出登录", True)
        self.page.update()

    def on_page_resize(self, e=None):
        if getattr(self, '_resize_task', None):
            self._resize_task.cancel()
        self._resize_task = asyncio.create_task(self._debounced_resize(e))

    async def _debounced_resize(self, e=None):
        try:
            await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            return
        if self.page.width <= 0: 
            return

        # 提高判定阈值至 435，超小屏阈值设置为 300
        is_small = self.page.width < 435
        is_ultra_small = self.page.width < 300
        layout_key = "ultra" if is_ultra_small else ("small" if is_small else "regular")
        if getattr(self, "current_layout_key", None) == layout_key:
            return
            
        self.current_is_small = is_small
        self.current_layout_key = layout_key
        self.status_card.is_small = is_small
        if hasattr(self, 'status_card'):
            self.status_card.update_size(is_small, is_ultra_small)
            
        # 断网界面的自适应缩放
        if hasattr(self, 'disconnect_icon'):
            # 图标：超小屏30，小屏70，大屏90
            self.disconnect_icon.size = 30 if is_ultra_small else (70 if is_small else 90)
        if hasattr(self, 'disconnect_text'):
            # 标题：超小屏11号，小屏16号，大屏18号
            self.disconnect_text.size = 11 if is_ultra_small else (16 if is_small else 18)
        if hasattr(self, 'disconnect_btn'):
            # 按钮高度和字号同步缩小
            self.disconnect_btn.height = 36 if is_ultra_small else (42 if is_small else 48)
            if self.disconnect_btn.style and getattr(self.disconnect_btn.style, "text_style", None):
                self.disconnect_btn.style.text_style.size = 11 if is_ultra_small else (13 if is_small else 14)
        
        if hasattr(self, 'login_view'):
            self.login_view.update_size(is_small)
        if hasattr(self, 'settings_card'):
            self.settings_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'reboot_card'):
            self.reboot_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'device_list_card'):
            self.device_list_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'toolbox_menu'):
            self.toolbox_menu.spacing = 6 if is_ultra_small else (10 if is_small else 14)
            self.toolbox_menu.run_spacing = 6 if is_ultra_small else (10 if is_small else 14)
        for item in getattr(self, 'toolbox_items', []):
            item.col = {"xs": 12, "sm": 12} if is_small else {"xs": 12, "sm": 6}
        for text in getattr(self, 'tool_item_texts', []):
            text.size = 11 if is_ultra_small else (13 if is_small else 15)
        for btn in getattr(self, 'network_action_buttons', []):
            btn.height = 42 if is_ultra_small else 48
            if btn.style and getattr(btn.style, "text_style", None):
                btn.style.text_style.size = 11 if is_ultra_small else (13 if is_small else 14)
            
        font_size = 10 if is_ultra_small else (12 if is_small else 14)
        self.apply_responsive_text_theme(font_size)

        self.main_view.padding = 4 if is_ultra_small else (8 if is_small else 15)

        # ---------------------------------------------------------
        # 核心排版：完全统一的自适应缩放与折行逻辑
        # ---------------------------------------------------------
        if hasattr(self, 'top_header_bar'):
            # 适当放大字号和图标
            icon_sz = 17 if is_ultra_small else (22 if is_small else 22)
            txt_sz = 9 if is_ultra_small else (11 if is_small else 12)
            
            for btn in self.nav_btns + self.action_btns:
                btn.content.controls[0].size = icon_sz
                btn.content.controls[1].size = txt_sz
                btn.content.spacing = 1 if is_ultra_small else 4
                btn.padding = ft.Padding(left=0, top=2, right=0, bottom=2) if is_ultra_small else ft.Padding(left=0, top=6, right=0, bottom=6)
                
                # 小屏则隐藏文字
                btn.content.controls[1].visible = not is_small 
                
                if is_small:
                    # 小屏“绝对均分”：开启 expand = True
                    # 强迫这一行的所有按钮宽度 100% 一模一样！彻底解决图标中心错位
                    btn.width = None
                    btn.expand = True
                else:
                    # 大屏恢复固定宽度，防止被无限拉成一长条
                    btn.expand = False
                    btn.width = 50

            if is_small:
                # 小屏合并为一行图标导航，减少首屏挤占
                self.top_header_bar.content = ft.Row(
                    [
                        *self.nav_btns,
                        *self.action_btns
                    ],
                    spacing=0,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER
                )
            else:
                self.top_header_bar.content = ft.Row(
                    [
                        ft.Row(self.nav_btns, spacing=15, alignment=ft.MainAxisAlignment.START),
                        ft.Row(self.action_btns, spacing=5, alignment=ft.MainAxisAlignment.END)
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER
                )

            self.top_header_bar.update()

        self.status_card.update()
        self.page.update()
    async def on_disconnect(self, e=None):
        if self.auto_refresh_task and not self.auto_refresh_task.done():
            self.auto_refresh_task.cancel()
            
        # 释放 HTTP 客户端底层的连接池资源
        await self.client.close()

# ==========================================
# 应用运行入口
# ==========================================
async def main(page: ft.Page):
    app = MU5001(page)
    await app.start()

if __name__ == "__main__":
    ft.run(main)
