import flet as ft
import httpx
import hashlib
import base64
import logging
import asyncio
import time
import re
import ipaddress
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

# 登录失败：clear_credentials=True 时才允许清除本地保存的密码
class LoginError(Exception):
    def __init__(self, message: str, *, clear_credentials: bool = False):
        super().__init__(message)
        self.clear_credentials = clear_credentials

# 设备明确拒绝登录（密码错误 / 账号锁定等）
class LoginAuthError(LoginError):
    def __init__(self, message: str = "密码错误或账号锁定"):
        super().__init__(message, clear_credentials=True)

# 网络不可达、超时等临时故障，不应清除本地凭证
class LoginNetworkError(LoginError):
    def __init__(self, message: str = "连接失败，请检查地址和网络"):
        super().__init__(message, clear_credentials=False)

# 超时与间隔配置（单位：秒、次）
API_TIMEOUT = 5               # 普通 API 请求超时
LOGIN_TIMEOUT = 3             # 登录相关请求超时
AUTO_REFRESH_INTERVAL = 1                 # 实时状态自动刷新间隔
STATION_LIST_REFRESH_INTERVAL = 3         # WiFi 设备列表刷新间隔
LAN_STATION_LIST_REFRESH_INTERVAL = 5     # 有线设备列表刷新间隔
BLACKLIST_REFRESH_INTERVAL = 5            # 黑名单刷新间隔
OFFLINE_FAIL_THRESHOLD = 2    # 连续2次失败后显示断网
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

# 规范化 MAC：支持 00:11:.. / 00-11-.. / 0011..；空串保持空，非法返回 None
def normalize_mac(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        return ""
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", raw).upper()
    if len(hex_only) != 12:
        return None
    return ":".join(hex_only[i:i+2] for i in range(0, 12, 2))

# 校验是否为合法 MAC（非空且格式正确）
def is_valid_mac(value: str) -> bool:
    return normalize_mac(value) not in (None, "")

# 校验 IPv4 地址
def is_valid_ipv4(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    try:
        ipaddress.IPv4Address(raw)
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False

# 校验 IPv6 地址（端口过滤可选 IPv6 时使用）
def is_valid_ipv6(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    try:
        ipaddress.IPv6Address(raw)
        return True
    except (ValueError, ipaddress.AddressValueError):
        return False

# 按版本校验 IP（ipv4 / ipv6）
def is_valid_ip(value: str, version: str = "ipv4") -> bool:
    v = (version or "ipv4").strip().lower()
    if v == "ipv6":
        return is_valid_ipv6(value)
    return is_valid_ipv4(value)


# 解析端口号：合法返回 int，空串返回 None（表示未填），非法返回 -1
def parse_port(value: str, allow_empty: bool = False):
    raw = (value or "").strip()
    if not raw:
        return None if allow_empty else -1
    if not raw.isdigit():
        return -1
    n = int(raw)
    if n < 0 or n > 65535:
        return -1
    return n

# 校验端口范围：start/end 均合法且 start <= end
def is_valid_port_range(start_val: str, end_val: str, min_port: int = 1, max_port: int = 65535, allow_zero: bool = False) -> tuple:
    s = parse_port(start_val, allow_empty=False)
    e = parse_port(end_val, allow_empty=False)
    if s == -1 or e == -1 or s is None or e is None:
        return False, "端口格式不正确"
    lo = 0 if allow_zero else min_port
    if s < lo or s > max_port or e < lo or e > max_port:
        return False, f"端口需在 {lo}~{max_port} 之间"
    if s > e:
        return False, "起始端口不能大于结束端口"
    return True, ""


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

# 极速探活工具：绕过 HTTP，直接使用底层 TCP 敲门，0.5秒连不上直接判死
async def check_router_alive(ip: str = "192.168.0.1", port: int = 80) -> bool:
    # 去掉协议和路径，只保留主机部分
    pure_ip = ip.replace("http://", "").replace("https://", "").split("/")[0]
    try:
        # 0.5 秒内 TCP 握手成功即视为在线
        reader, writer = await asyncio.wait_for(asyncio.open_connection(pure_ip, port), timeout=0.5)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        # 超时或连不上：统一按离线处理
        return False


# 后台任务启动器：把 Task 存进 owner.background_tasks，防止 GC 中途回收
def spawn_background_task(owner, coro) -> asyncio.Task:
    tasks = getattr(owner, "background_tasks", None)
    if tasks is None:
        # 兼容未初始化集合的调用方
        tasks = set()
        owner.background_tasks = tasks
    task = asyncio.create_task(coro)
    tasks.add(task)  # 强引用，避免任务被垃圾回收

    def _on_done(t: asyncio.Task):
        # 结束后自动移除，防止集合无限增长
        tasks.discard(t)
        if t.cancelled():
            return
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            # 后台任务异常日志，避免静默失败
            logger.error(f"后台任务异常: {type(exc).__name__}: {exc}", exc_info=exc)

    task.add_done_callback(_on_done)
    return task

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
        # 设备列表/黑名单本地缓存
        self._station_cache: list = []
        self._lan_cache: list = []
        self._blacklist_cache: list = []
        self._last_station_fetch: float = 0.0
        self._last_lan_fetch: float = 0.0
        self._last_blacklist_fetch: float = 0.0
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
        # 会话结束时清空设备列表缓存，避免下次登录用到旧数据
        self._station_cache = []
        self._lan_cache = []
        self._blacklist_cache = []
        self._last_station_fetch = 0.0
        self._last_lan_fetch = 0.0
        self._last_blacklist_fetch = 0.0

    # 异步 GET 查询设备配置，cmd 支持逗号分隔多命令，multi_data 启用多数据返回模式
    async def get_cmd(self, cmd: str, multi_data: bool = False) -> Dict:
        # 恢复互斥锁：保护脆弱的路由器 Web 服务，强制所有 GET 请求排队执行
        async with self._request_lock:
            return await self._get_cmd_unlocked(cmd, multi_data)

    async def _get_cmd_unlocked(self, cmd: str, multi_data: bool = False) -> Dict:
        if not self.state.client:
            raise RuntimeError("未登录设备，无法执行 GET 请求")
        params = {"isTest": "false", "cmd": cmd}
        if multi_data or "," in cmd:
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
            logger.error(f"GET 请求超时 (路由器可能处于高负载状态): {cmd}")
            raise
        except httpx.ConnectError:
            logger.error(f"GET 拒绝连接 (路由器可能已断开或正在重启): {cmd}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"GET HTTP 状态码错误 {e.response.status_code}: {cmd}")
            raise
        except Exception as e:
            # 这里的 exc_info=True 是排错神器，能精准打印出代码里比如 None.strip() 导致的崩溃行号
            logger.error(f"GET 执行时发生代码内部异常: {cmd}, {type(e).__name__}: {e}", exc_info=True)
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
    async def _wait_data_connection_unlocked(self, target_on: bool, timeout: float = 10.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            status_res = await self._get_cmd_unlocked("ppp_status")
            status = str(status_res.get("ppp_status", "")).strip().lower()
            status_clean = status.replace("disconnected", "off")
            is_connected = "connected" in status_clean
            is_disconnected = "off" in status_clean and not is_connected
            if (target_on and is_connected) or (not target_on and is_disconnected):
                return True
            await asyncio.sleep(0.5)
        return False

    async def set_data_connection(self, target_on: bool, timeout: float = 10.0) -> bool:
        try:
            async with self._request_lock:
                status_res = await self._get_cmd_unlocked("ppp_status")
                status = str(status_res.get("ppp_status", "")).strip().lower()
                status_clean = status.replace("disconnected", "off")
                is_connected = "connected" in status_clean
                is_disconnected = "off" in status_clean and not is_connected
                if (target_on and is_connected) or (not target_on and is_disconnected):
                    return True
                goform_id = "CONNECT_NETWORK" if target_on else "DISCONNECT_NETWORK"
                if not await self._post_cmd_unlocked(goform_id, {"notCallback": "true"}):
                    return False
                return await self._wait_data_connection_unlocked(target_on, timeout)
        except Exception as e:
            logger.error(f"数据连接切换异常: {e}", exc_info=DEBUG_MODE)
            return False

    # 异步切换网络模式。官方页面仅允许在数据断开后修改，完成后恢复原连接状态。
    async def switch_net_mode(self, mode_val: str, was_connected: bool) -> bool:
        try:
            async with self._request_lock:
                if not await self._post_cmd_unlocked("DISCONNECT_NETWORK", {"notCallback": "true"}):
                    return False
                if not await self._wait_data_connection_unlocked(False):
                    logger.warning("切换网络模式失败：等待数据连接断开超时")
                    return False
                ok_set = await self._post_cmd_unlocked("SET_BEARER_PREFERENCE", {API_KEY_WRITE: mode_val})
                if not ok_set:
                    return False
                if was_connected:
                    await asyncio.sleep(NET_SWITCH_DELAY)
                    if not await self._post_cmd_unlocked("CONNECT_NETWORK", {"notCallback": "true"}):
                        return False
                    if not await self._wait_data_connection_unlocked(True):
                        logger.warning("网络模式已设置，但等待数据连接恢复超时")
                        return False
                return True
        except Exception as e:
            logger.error(f"切换网络模式异常: {e}", exc_info=DEBUG_MODE)
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
    def invalidate_device_list_cache(self):
        # 强制下次实时刷新重新拉取设备列表/黑名单（拉黑、手动刷新等场景）
        self._last_station_fetch = 0.0
        self._last_lan_fetch = 0.0
        self._last_blacklist_fetch = 0.0

    async def get_realtime_status(self, force_device_lists: bool = False) -> RealtimeStatus:
        # force_device_lists=True：忽略降频缓存，立刻拉 station/lan/黑名单（手动刷新、拉黑后）
        cmd = (
            "battery_value,battery_charging,network_type,wan_ipaddr,imei,imsi,sim_imsi,Z5g_rsrp,Z5g_SINR,"
            "nr5g_pci,nr5g_action_channel,pm_sensor_mdm,battery_temp,pm_sensor_pa1,"
            "realtime_tx_thrpt,realtime_rx_thrpt,realtime_tx_bytes,realtime_rx_bytes,"
            "monthly_tx_bytes,monthly_rx_bytes,wan_active_band,nr5g_action_band,"
            "wan_active_channel,lte_pci,lte_rsrp,lte_snr,cell_id,Z5g_Cell_ID,"
            "nr5g_cell_id,network_provider,realtime_time,lte_rsrq,Z5g_rsrq,lte_rssi,"
            "Z5g_rssi,nr5g_rssi,ppp_status,mcc_mnc" 
        )
        # 状态字段始终按 AUTO_REFRESH_INTERVAL 拉取（约 1s）
        res = await self.get_cmd(cmd, multi_data=True)
        
        now = time.monotonic()
        # WiFi 设备列表：约 3 秒一次
        if force_device_lists or (now - self._last_station_fetch) >= STATION_LIST_REFRESH_INTERVAL:
            try:
                wifi_res = await self.get_cmd("station_list")
                raw = wifi_res.get("station_list", [])
                self._station_cache = raw if isinstance(raw, list) else []
                self._last_station_fetch = now
            except Exception as ex:
                logger.debug(f"拉取 station_list 失败，沿用缓存: {ex}")
        # 有线设备列表：约 5 秒一次
        if force_device_lists or (now - self._last_lan_fetch) >= LAN_STATION_LIST_REFRESH_INTERVAL:
            try:
                lan_res = await self.get_cmd("lan_station_list")
                raw = lan_res.get("lan_station_list", [])
                self._lan_cache = raw if isinstance(raw, list) else []
                self._last_lan_fetch = now
            except Exception as ex:
                logger.debug(f"拉取 lan_station_list 失败，沿用缓存: {ex}")

        macs_count = 0
        connected_devices = []
        blacklisted_devices = []
        macs = set()
        try:
            for d in list(self._station_cache) + list(self._lan_cache):
                if not isinstance(d, dict):
                    continue
                mac = d.get("mac_addr", "").strip().upper()
                if mac and mac not in macs:
                    macs.add(mac)
                    name = d.get("hostname", "").strip() or "未知设备"
                    ip = d.get("ip_addr", "").strip() or "未知 IP"
                    connected_devices.append({"name": name, "ip": ip, "mac": mac})
        except Exception:
            pass
        # 黑名单：约 5 秒一次；强制刷新时立刻更新
        if force_device_lists or (now - self._last_blacklist_fetch) >= BLACKLIST_REFRESH_INTERVAL:
            try:
                self._blacklist_cache = await self.get_blacklisted_devices()
                self._last_blacklist_fetch = now
            except Exception as ex:
                logger.debug(f"拉取黑名单失败，沿用缓存: {ex}")
                if force_device_lists:
                    self._blacklist_cache = []
        blacklisted_devices = list(self._blacklist_cache)
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
            trust_env=False,  # 无视系统VPN和代理
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
            #  统一成功状态码判断，并单独提取常见网络错误
            if result in {"0", "4", "success"}:
                self.state.client = client
                self.state.ip = base_url
                self.state.rd0 = rd0
                self.state.rd1 = rd1
                self.state.password = password
                logger.info(f"登录成功: {base_url}")
                return True
            # 设备明确拒绝：按鉴权失败处理（可清本地密码）
            logger.warning(f"登录被拒，接口返回结果: result={result}")
            await client.aclose()
            raise LoginAuthError("密码错误或账号锁定")
        except LoginError:
            # 已分类的登录异常直接上抛，交给 UI 决定是否清凭证
            raise
        except httpx.TimeoutException:
            # 超时属于网络问题，不应清本地密码
            logger.error(f"登录超时：无法在 {LOGIN_TIMEOUT} 秒内收到设备响应，请检查信号或设备负载")
            await client.aclose()
            raise LoginNetworkError(f"登录超时（{LOGIN_TIMEOUT}s），请检查设备是否在线")
        except httpx.ConnectError:
            # 连不上设备同样按网络失败处理
            logger.error(f"登录断开：无法建立到底层地址 {ip} 的连接，设备可能未开机或 IP 错误")
            await client.aclose()
            raise LoginNetworkError("无法连接设备，请检查地址和网络")
        except Exception as e:
            # 对于真正的内部逻辑错误，强制打印完整堆栈，无视 DEBUG_MODE 开关
            logger.error(f"登录发生不可预期的内部逻辑错误: {type(e).__name__}: {e}", exc_info=True)
            await client.aclose()
            # 未知异常按网络/临时故障处理，避免误删本地密码
            raise LoginNetworkError("登录失败，请稍后重试") from e

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

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        # 仅在超小屏时内边距为5(拉满左右)，其他小屏和大屏都保持正常内边距15
        self.padding = ft.Padding(left=5, top=15, right=5, bottom=15) if is_ultra_small else 15
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
        except LoginAuthError as auth_ex:
            # 仅设备明确拒绝登录时，才清除本地保存的密码
            await self.clear_credentials_and_reset(is_error=True)
            self.login_status.value = str(auth_ex)
            self.login_status.color = ft.Colors.ERROR
            show_toast(self.app_page, str(auth_ex), False)
        except LoginNetworkError as net_ex:
            # 网络波动/设备未就绪：保留本地密码，避免用户反复输入
            logger.error(f"登录网络失败: {net_ex}", exc_info=DEBUG_MODE)
            self.login_status.value = str(net_ex)
            self.login_status.color = ft.Colors.ERROR
            show_toast(self.app_page, str(net_ex), False)
        except Exception as e:
            logger.error(f"登录异常，请检查地址和网络: {e}", exc_info=DEBUG_MODE)
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
         # 取消单独控件的局部刷新，统一交由卡片末尾的 self.update() 打包处理
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
     try:
         self.txt_local_time.update()  # 局部刷新
     except Exception:
         pass

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
        # 按实际生效的双频模式，刷新详细设置区可见性/标题
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

        # WiFi 设置 UI (合一/分离单选；广播在下方详细设置中)
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
        # 同步到5GHz 开启时：2.4G 的广播/隔离/加密/密码变更实时推到 5G
        for _key in ["broadcast", "isolate", "auth", "password"]:
            self.wifi_detail_24g[_key].on_change = lambda e: self.update_wifi_sync_state()
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

        # WiFi 频段模式回显（广播状态由下方详细设置控件回显）
        wifi_lbd = str(res.get("wifi_lbd_enable", "")).strip()
        if wifi_lbd == "1":
            self.wifi_mode.value = WiFiMode.MERGED
            self.actual_wifi_mode = WiFiMode.MERGED  # 记录真实状态
        else:
            self.wifi_mode.value = WiFiMode.SEPARATED
            self.actual_wifi_mode = WiFiMode.SEPARATED  # 记录真实状态

        # 刷新双频相关 UI 显示状态
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
             try:
                 self.data_switch.update()  # 局部刷新：只更新小开关动画
             except Exception:
                 pass
         elif is_disconnected and self.data_switch.value:
             self.data_switch.value = False
             try:
                 self.data_switch.update()  # 局部刷新：只更新小开关动画
             except Exception:
                 pass
    
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
        
        # 统一交给外层卡片进行一次性批量提交
        try:
            self.update()
        except Exception:
            pass

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
            ok = await self.api_client.set_data_connection(is_on)
            if ok:
                self.set_global_status(f"数据连接已{'开启' if is_on else '关闭'}", ft.Colors.PRIMARY)
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
            self.is_switching_data = False
            self._toggle_network_lock(False)
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
            self.is_switching_data = False
            self._toggle_network_lock(False)
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
            ),
            on_dismiss=close_dlg  # 点击遮罩等关闭时也从 overlay 移除，避免泄漏
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
            # 把 2.4G 当前值同步到 5G
            controls["broadcast"].value = self.wifi_detail_24g["broadcast"].value
            controls["isolate"].value = self.wifi_detail_24g["isolate"].value
            controls["auth"].value = self.wifi_detail_24g["auth"].value
            controls["password"].value = self.wifi_detail_24g["password"].value
        # 立即刷新界面：禁用/同步勾选态、安全模式与密码
        try:
            self.update()
        except Exception:
            pass

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
        # 提取轻量的特征值（MAC+IP）拼接作为哈希，避免对字典列表执行极其耗时的 str() 强转
        conn_info = "".join([str(d.get("mac", "")) + str(d.get("ip", "")) for d in status.connected_devices])
        blk_info = "".join([str(d.get("mac", "")) for d in blacklisted_devices])
        dev_hash = f"{display_limit}_{self.is_small_layout}_{self.is_ultra_small_layout}_{conn_info}_{blk_info}"
        
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
            all_devices = []
            seen_macs = set()

            for dev in status.connected_devices:
                mac = str(dev.get("mac", "")).upper()
                seen_macs.add(mac)
                all_devices.append(dev)

            for dev in blacklisted_devices:
                mac = str(dev.get("mac", "")).upper()
                if mac not in seen_macs:
                    all_devices.append({
                        "name": dev.get("name", "未知设备"),
                        "ip": "已断开 (黑名单)",
                        "mac": mac
                    })

            if not all_devices:
                self.device_list_col.controls.append(
                    ft.Text("暂无设备连接或拉黑", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
                )
            else:
                for i, dev in enumerate(all_devices[:display_limit]):
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
# UI 组件拆分 - APN 设置卡片
# ==========================================
class APNCard(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable, refresh_config_cb: Callable = None):
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12)
        self.app_page = page
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.refresh_config = refresh_config_cb
        self.is_data_connected = True
        self.is_switching_data = False
        self.is_adding_profile = False
        self.auto_data = {"name": "", "apn": "", "pdp": "IPv4v6", "auth": "NONE", "user": "", "pwd": ""}
        self.manual_profiles: List[Dict[str, str]] = []
        self.raw_manual_profile_count = 0
        self.selected_profile_name = ""
        self.loaded_profile_name = ""
        self.pending_new_profile_index = ""
        self.just_saved_manual_profile = False
        self.current_apn_name = ""
        self.build_ui()

    def build_ui(self):
        self.txt_title = ft.Text("APN 设置", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.txt_current_apn = ft.Text("--", color=ft.Colors.ON_SURFACE)
        self.data_switch = ft.Switch(
            value=True,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_data_switch_change
        )

        self.radio_mode = ft.RadioGroup(
            value="auto",
            content=ft.Row([
                ft.Radio(value="auto", label="自动", fill_color=ft.Colors.PRIMARY, label_style=ft.TextStyle(color=ft.Colors.ON_SURFACE)),
                ft.Radio(value="manual", label="手动", fill_color=ft.Colors.PRIMARY, label_style=ft.TextStyle(color=ft.Colors.ON_SURFACE))
            ], wrap=True),
            on_change=self.on_mode_change
        )

        self.dropdown_profile = create_dropdown("", [], None, expand=True)
        self.dropdown_profile.on_change = self.on_profile_change
        self.btn_add_profile = create_button("新增", on_click=self.on_add_profile)
        
        self.dropdown_pdp_type = create_dropdown("", [ft.dropdown.Option("IPv4"), ft.dropdown.Option("IPv6"), ft.dropdown.Option("IPv4v6")], "IPv4v6", expand=True)
        self.input_profile_name = create_text_field(label="", expand=True)
        self.input_apn = create_text_field(label="", expand=True)
        self.dropdown_auth = create_dropdown("", [ft.dropdown.Option("NONE"), ft.dropdown.Option("CHAP"), ft.dropdown.Option("PAP")], "NONE", expand=True)
        self.input_user = create_text_field(label="", expand=True)
        self.input_pwd = create_text_field(label="", expand=True)
        self.txt_warning = ft.Text("该设置只能在断网的条件下修改", size=12, color=ft.Colors.ON_SURFACE_VARIANT)


        self.btn_set_default = create_button("默认APN", on_click=self.on_set_default, expand=True)
        self.btn_apply = create_button("保存APN", on_click=self.on_apply, expand=True)
        self.btn_delete = create_button("删除APN", on_click=self.on_delete, expand=True)

        # 提取 Container 为实例变量，方便后续动态修改栅格宽度和可见性
        self.cont_set_default = ft.Container(self.btn_set_default, col={"xs": 12, "sm": 4})
        self.cont_apply = ft.Container(self.btn_apply, col={"xs": 12, "sm": 4}, visible=False)
        self.cont_delete = ft.Container(self.btn_delete, col={"xs": 12, "sm": 4}, visible=False)

        self.action_row = ft.ResponsiveRow(
            [
                self.cont_set_default,
                self.cont_apply,
                self.cont_delete,
            ],
            alignment=ft.MainAxisAlignment.END,
            spacing=10,
            run_spacing=8
        )

        def create_row(label, ctrl, extra=None):
            cols = [ft.Container(ft.Text(label, color=ft.Colors.ON_SURFACE), col={"xs": 12, "sm": 4, "md": 3})]
            if extra:
                ctrl.expand = False
                cols.append(ft.Container(ctrl, col={"xs": 12, "sm": 6, "md": 7}))
                cols.append(ft.Container(extra, col={"xs": 12, "sm": 2, "md": 2}))
            else:
                cols.append(ft.Container(ctrl, col={"xs": 12, "sm": 8, "md": 9}))
            return ft.ResponsiveRow(controls=cols, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.content = ft.Column([
            self.txt_title,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            ft.ResponsiveRow([
                ft.Container(ft.Text("当前配置", color=ft.Colors.ON_SURFACE), col={"xs": 12, "sm": 4, "md": 3}),
                ft.Container(self.txt_current_apn, col={"xs": 12, "sm": 8, "md": 9})
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.ResponsiveRow([
                ft.Container(ft.Text("数据连接", color=ft.Colors.ON_SURFACE), col={"xs": 12, "sm": 4, "md": 3}),
                ft.Container(
                # 只保留 self.data_switch
                    ft.Row([self.data_switch], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                    col={"xs": 12, "sm": 8, "md": 9}
                )
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            create_row("模式", ft.ResponsiveRow([ft.Container(self.radio_mode, col={"xs": 12, "sm": 6}), ft.Container(self.btn_add_profile, col={"xs": 12, "sm": 6})], vertical_alignment=ft.CrossAxisAlignment.CENTER)),
            create_row("配置文件", self.dropdown_profile),
            create_row("PDP 类型", self.dropdown_pdp_type),
            create_row("配置文件名称 *", self.input_profile_name),
            create_row("APN *", self.input_apn),
            create_row("鉴权方式", self.dropdown_auth),
            create_row("用户名", self.input_user),
            create_row("密码", self.input_pwd),
            ft.Container(self.txt_warning, margin=ft.Margin(left=0, top=10, right=0, bottom=0)),
            self.action_row
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def on_mode_change(self, e):
        is_manual = self.radio_mode.value == "manual"
        
        self.btn_add_profile.visible = is_manual

        if is_manual:
            self._refresh_profile_dropdown()
            if self.is_adding_profile:
                data = self._empty_profile(pdp="IPv4")
            elif self.selected_profile_name:
                data = self._find_manual_profile(self.selected_profile_name) or self._empty_profile()
            elif self.manual_profiles:
                data = self.manual_profiles[0]
                self.selected_profile_name = data.get("name", "")
                self._refresh_profile_dropdown()
            else:
                data = self._empty_profile()
                self.selected_profile_name = ""
                self.loaded_profile_name = ""
                self.dropdown_profile.options = []
                self.dropdown_profile.value = None
        else:
            self.is_adding_profile = False
            data = getattr(self, "auto_data", {})
            auto_name = str(data.get("name", "") or "").strip()
            if auto_name:
                self.dropdown_profile.options = [ft.dropdown.Option(auto_name, auto_name)]
                self.dropdown_profile.value = auto_name
            else:
                self.dropdown_profile.options = []
                self.dropdown_profile.value = None

        self._fill_profile_form(data)
        self.loaded_profile_name = self.selected_profile_name if is_manual and not self.is_adding_profile else ""

        self._sync_apn_editable_controls()

        self.btn_apply.visible = is_manual
        self.btn_delete.visible = is_manual
        self.btn_set_default.visible = True
        
        # 动态控制外层 Container 的可见性与栅格宽度
        self.cont_apply.visible = is_manual
        self.cont_delete.visible = is_manual
        
        if is_manual:
            self.cont_set_default.col = {"xs": 12, "sm": 4}
            self.cont_apply.col = {"xs": 12, "sm": 4}
            self.cont_delete.col = {"xs": 12, "sm": 4}
        else:
            self.cont_set_default.col = {"xs": 12}
        self._sync_data_ui()

        self.update()

    def _empty_profile(self, pdp: str = "IPv4v6") -> Dict[str, str]:
        return {"name": "", "apn": "", "pdp": pdp, "auth": "NONE", "user": "", "pwd": "", "index": self._next_profile_index()}

    def _find_manual_profile(self, name: str) -> Optional[Dict[str, str]]:
        for profile in self.manual_profiles:
            if profile.get("name") == name:
                return profile
        return None

    def _next_profile_index(self) -> str:
        used = set()
        for profile in self.manual_profiles:
            try:
                used.add(int(profile.get("index", "")))
            except (TypeError, ValueError):
                continue
        for i in range(20):
            if i not in used:
                return str(i)
        return str(len(self.manual_profiles))

    def _load_manual_profile_form(self, name: str) -> bool:
        name = str(name or "").strip()
        self.selected_profile_name = name
        self.dropdown_profile.value = name or None
        profile = self._find_manual_profile(name)
        if profile:
            self._fill_profile_form(profile)
            self.loaded_profile_name = name
            return True
        logger.warning(f"未找到 APN 配置文件: {name}")
        self._fill_profile_form(self._empty_profile())
        self.loaded_profile_name = ""
        return False

    def _refresh_profile_dropdown(self):
        self.dropdown_profile.options = [ft.dropdown.Option(p["name"], p["name"]) for p in self.manual_profiles if p.get("name")]
        names = [p.get("name") for p in self.manual_profiles]
        if self.is_adding_profile:
            self.dropdown_profile.value = None
        elif self.selected_profile_name in names:
            self.dropdown_profile.value = self.selected_profile_name
        else:
            self.selected_profile_name = names[0] if names else ""
            self.dropdown_profile.value = self.selected_profile_name or None

    def _match_option(self, dropdown, value: str, fallback: str) -> str:
        value_upper = self._ui_pdp_type(value).upper() if dropdown is self.dropdown_pdp_type else str(value or "").upper()
        for opt in dropdown.options:
            if str(opt.key).upper() == value_upper:
                return opt.key
        return fallback

    def _ui_pdp_type(self, value: str) -> str:
        val = str(value or "").strip()
        return "IPv4" if val.upper() == "IP" else val

    def _api_pdp_type(self, value: str) -> str:
        val = str(value or "").strip()
        return "IP" if val.upper() == "IPV4" else val

    def _fill_profile_form(self, data: Dict[str, str]):
        self.input_profile_name.value = data.get("name", "")
        self.input_apn.value = data.get("apn", "")
        self.input_user.value = data.get("user", "")
        self.input_pwd.value = data.get("pwd", "")
        self.dropdown_pdp_type.value = self._match_option(self.dropdown_pdp_type, data.get("pdp", ""), "IPv4v6")
        self.dropdown_auth.value = self._match_option(self.dropdown_auth, data.get("auth", ""), "NONE")

    def _parse_auto_profile(self, res: dict) -> Dict[str, str]:
        data = {"name": "", "apn": "", "pdp": "IPv4v6", "auth": "NONE", "user": "", "pwd": ""}
        auto_cfg = str(res.get("apn_auto_config", "") or res.get("ipv6_apn_auto_config", "") or "").strip()
        if auto_cfg:
            parts = auto_cfg.split("($)")
            if len(parts) > 0:
                data["name"] = parts[0].strip()
            if len(parts) > 1:
                data["apn"] = parts[1].strip()
            if len(parts) > 4 and parts[4].strip():
                data["auth"] = parts[4].strip()
            if len(parts) > 5:
                data["user"] = parts[5].strip()
            if len(parts) > 6:
                data["pwd"] = parts[6].strip()
            if len(parts) > 7 and parts[7].strip():
                data["pdp"] = self._ui_pdp_type(parts[7].strip())

        if not data["name"] and not data["apn"]:
            data.update({
                "name": str(res.get("profile_name_ui", "")).strip(),
                "apn": str(res.get("wan_apn_ui", "")).strip(),
                "pdp": self._ui_pdp_type(str(res.get("pdp_type_ui", "IPv4v6")).strip()),
                "auth": str(res.get("ppp_auth_mode_ui", "NONE")).strip() or "NONE",
                "user": str(res.get("ppp_username_ui", "")).strip(),
                "pwd": str(res.get("ppp_passwd_ui", "")).strip()
            })
        return data

    def _sync_data_ui(self):
        self.data_switch.value = self.is_data_connected
        self.btn_set_default.visible = True
        self.btn_set_default.disabled = self.is_switching_data
        self.btn_add_profile.disabled = self.is_switching_data
        self.btn_apply.disabled = self.is_switching_data
        self.btn_delete.disabled = self.is_switching_data
        self._sync_apn_editable_controls()

    def _sync_apn_editable_controls(self):
        is_manual = getattr(self, "radio_mode", None) and self.radio_mode.value == "manual"
        can_edit = bool(is_manual and not self.is_data_connected and not self.is_switching_data)
        self.dropdown_profile.disabled = not can_edit or self.is_adding_profile
        for ctrl in [self.dropdown_profile, self.dropdown_pdp_type,
                     self.input_profile_name, self.input_apn, self.dropdown_auth,
                     self.input_user, self.input_pwd]:
            ctrl.disabled = not can_edit
        self.dropdown_profile.disabled = not can_edit or self.is_adding_profile

    def update_realtime(self, status: 'RealtimeStatus'):
        if self.is_switching_data:
            return
        self.is_data_connected = bool(getattr(status, "is_data_connected", False))
        self._sync_data_ui()
        if self.radio_mode.value == "manual" and not self.is_adding_profile:
            selected = str(self.dropdown_profile.value or "").strip()
            if selected and selected != self.loaded_profile_name:
                self._load_manual_profile_form(selected)
        try:
            self.update()
        except Exception:
            pass

    def on_profile_change(self, e):
        if self.radio_mode.value != "manual" or self.is_adding_profile:
            return
        selected = getattr(e, "data", None) or getattr(getattr(e, "control", None), "value", None) or self.dropdown_profile.value or ""
        self._load_manual_profile_form(selected)
        self.btn_delete.visible = True
        self.update()

    def _set_apn_actions_locked(self, disabled: bool):
        self.data_switch.disabled = disabled
        if disabled:
            self._sync_apn_editable_controls()
            for btn in [self.btn_set_default, self.btn_apply, self.btn_delete, self.btn_add_profile]:
                btn.disabled = True
        else:
            self._sync_data_ui()
        try:
            self.update()
        except Exception:
            pass

    def _ensure_data_disconnected(self) -> bool:
        if self.is_data_connected:
            show_toast(self.app_page, "请先关闭数据连接后再修改 APN", False)
            return False
        return True

    async def _switch_data_connection(self, target_on: bool, reason: str = "") -> bool:
        if self.is_data_connected == target_on:
            return True
        self.is_switching_data = True
        self._set_apn_actions_locked(True)
        action = "开启" if target_on else "关闭"
        show_toast(self.app_page, f"正在{action}数据连接...", True)
        try:
            ok = await self.api_client.set_data_connection(target_on)
            if ok:
                self.is_data_connected = target_on
                self.set_global_status(f"数据连接已{action}" + (f"，{reason}" if reason else ""), ft.Colors.PRIMARY)
                show_toast(self.app_page, f"数据连接已{action}", True)
            else:
                self.set_global_status(f"数据连接{action}失败", ft.Colors.ERROR)
                show_toast(self.app_page, f"数据连接{action}失败", False)
            return ok
        except Exception as ex:
            logger.error(f"APN 页面数据连接{action}异常: {ex}", exc_info=DEBUG_MODE)
            self.set_global_status(f"数据连接{action}异常", ft.Colors.ERROR)
            show_toast(self.app_page, f"数据连接{action}异常", False)
            return False
        finally:
            self._sync_data_ui()
            self.is_switching_data = False
            self._set_apn_actions_locked(False)

    async def on_data_switch_change(self, e):
        if self.is_switching_data:
            self.data_switch.value = self.is_data_connected
            self.data_switch.update()
            return

        target_on = bool(self.data_switch.value)
        self.is_switching_data = True
        self._set_apn_actions_locked(True)
        show_toast(self.app_page, f"正在{'开启' if target_on else '关闭'}数据连接...", True)
        try:
            ok = await self.api_client.set_data_connection(target_on)
            if ok:
                self.is_data_connected = target_on
                self.set_global_status(f"数据连接已{'开启' if target_on else '关闭'}", ft.Colors.PRIMARY)
                show_toast(self.app_page, f"数据连接已{'开启' if target_on else '关闭'}", True)
            else:
                self.data_switch.value = self.is_data_connected
                self.set_global_status("数据连接切换失败", ft.Colors.ERROR)
                show_toast(self.app_page, "数据连接切换失败", False)
        except Exception as ex:
            logger.error(f"APN 页面数据连接切换异常: {ex}", exc_info=DEBUG_MODE)
            self.data_switch.value = self.is_data_connected
            self.set_global_status("数据连接切换异常", ft.Colors.ERROR)
            show_toast(self.app_page, "数据连接切换异常", False)
        finally:
            self._sync_data_ui()
            self.is_switching_data = False
            self._set_apn_actions_locked(False)

    def update_config(self, res: dict):
        self.mode = res.get("apn_mode", "auto")
        self.radio_mode.value = self.mode

        # 解析并缓存【自动模式】的数据
        ui_name = str(res.get("profile_name_ui", "")).strip()
        self.auto_data = self._parse_auto_profile(res)

        # 解析并缓存【手动模式】的配置文件列表
        parsed_manual_profiles = self._parse_manual_profiles(res)
        self.raw_manual_profile_count = self._count_raw_apn_config_profiles(res)
        if self.just_saved_manual_profile and self.manual_profiles:
            parsed_names = [p.get("name") for p in parsed_manual_profiles]
            if self.selected_profile_name and self.selected_profile_name not in parsed_names:
                parsed_manual_profiles = self._merge_manual_profiles(parsed_manual_profiles, self.manual_profiles)
        if self.just_saved_manual_profile and not parsed_manual_profiles and self.manual_profiles:
            self.just_saved_manual_profile = False
            self.on_mode_change(None)
            return
        self.manual_profiles = parsed_manual_profiles
        self.just_saved_manual_profile = False
        profile_names = [p.get("name") for p in self.manual_profiles]
        current_index = str(res.get("Current_index", "") or res.get("index", "")).strip()
        current_profile_name = ""
        if current_index:
            for profile in self.manual_profiles:
                if str(profile.get("index", "")).strip() == current_index:
                    current_profile_name = str(profile.get("name", "")).strip()
                    break
        if not current_profile_name and ui_name in profile_names:
            current_profile_name = ui_name
        if self.mode == "manual":
            if current_profile_name:
                self.current_apn_name = current_profile_name
            elif self.current_apn_name not in profile_names:
                self.current_apn_name = ""
        else:
            self.current_apn_name = ui_name or self.current_apn_name
        if self.mode == "manual" and self.current_apn_name in profile_names:
            self.selected_profile_name = self.current_apn_name
        elif self.selected_profile_name not in profile_names:
            self.selected_profile_name = self.manual_profiles[0].get("name", "") if self.manual_profiles else ""

        # 更新顶部的“当前配置”文本
        current_display = self.current_apn_name if self.mode == "manual" else self.auto_data["name"]
        self.txt_current_apn.value = current_display or "--"

        # 触发 UI 渲染
        self.on_mode_change(None)

    def _split_profile_field(self, value: str) -> List[str]:
        text = str(value or "").strip()
        if not text:
            return []
        for sep in ["($)", ";", ","]:
            if sep in text:
                return [part.strip() for part in text.split(sep)]
        return [text]

    def _parse_manual_profiles(self, res: dict) -> List[Dict[str, str]]:
        config_profiles = self._parse_apn_config_profiles(res)
        if config_profiles:
            return self._filter_auto_profile(config_profiles)

        names = self._split_profile_field(
            res.get("profile_name_list", "")
        )
        apns = self._split_profile_field(
            res.get("wan_apn_list", "") or res.get("manual_apn_list", "")
        )
        pdps = self._split_profile_field(
            res.get("pdp_type_list", "")
        )
        auths = self._split_profile_field(
            res.get("ppp_auth_mode_list", "")
        )
        users = []
        pwds = []

        count = max(len(names), len(apns), len(pdps), len(auths), len(users), len(pwds), 0)
        profiles = []
        seen = set()
        for i in range(count):
            name = names[i] if i < len(names) else ""
            apn = apns[i] if i < len(apns) else ""
            if not name and not apn:
                continue
            name = name or apn
            if name in seen:
                continue
            seen.add(name)
            profiles.append({
                "name": name,
                "apn": apn,
                "pdp": self._ui_pdp_type(pdps[i]) if i < len(pdps) and pdps[i] else "IPv4v6",
                "auth": auths[i] if i < len(auths) and auths[i] else "NONE",
                "user": users[i] if i < len(users) else "",
                "pwd": pwds[i] if i < len(pwds) else "",
                "index": str(i)
            })
        return self._filter_auto_profile(profiles)

    def _count_raw_apn_config_profiles(self, res: dict) -> int:
        count = 0
        seen = set()
        preset_count = self._preset_profile_count(res)
        for i in range(20):
            if i < preset_count:
                continue
            raw = str(res.get(f"APN_config{i}", "") or "").strip()
            if not raw:
                continue
            parts = raw.split("($)")
            name = parts[0].strip() if len(parts) > 0 else ""
            apn = parts[1].strip() if len(parts) > 1 else ""
            key = name
            if not key or key in seen:
                continue
            seen.add(key)
            count += 1
        return count

    def _preset_profile_count(self, res: dict) -> int:
        try:
            return max(0, int(str(res.get("apn_num_preset", "0") or "0").strip()))
        except (TypeError, ValueError):
            return 0

    def _filter_auto_profile(self, profiles: List[Dict[str, str]]) -> List[Dict[str, str]]:
        auto_name = str(self.auto_data.get("name", "")).strip()
        auto_apn = str(self.auto_data.get("apn", "")).strip()
        filtered = []
        for profile in profiles:
            name = str(profile.get("name", "")).strip()
            apn = str(profile.get("apn", "")).strip()
            filtered.append(profile)
        return filtered

    def _parse_apn_config_profiles(self, res: dict) -> List[Dict[str, str]]:
        profiles = []
        seen = set()
        preset_count = self._preset_profile_count(res)
        for i in range(20):
            if i < preset_count:
                continue
            raw = str(res.get(f"APN_config{i}", "") or "").strip()
            ipv6_raw = str(res.get(f"ipv6_APN_config{i}", "") or "").strip()
            if not raw and not ipv6_raw:
                continue
            parts = raw.split("($)")
            ipv6_parts = ipv6_raw.split("($)") if ipv6_raw else []
            name = parts[0].strip() if len(parts) > 0 else ""
            apn = parts[1].strip() if len(parts) > 1 else ""
            ipv6_name = ipv6_parts[0].strip() if len(ipv6_parts) > 0 else ""
            ipv6_apn = ipv6_parts[1].strip() if len(ipv6_parts) > 1 else ""
            if not name and not ipv6_name:
                continue
            name = name or ipv6_name
            pdp = self._ui_pdp_type(parts[7].strip()) if len(parts) > 7 and parts[7].strip() else ""
            ipv6_pdp = self._ui_pdp_type(ipv6_parts[7].strip()) if len(ipv6_parts) > 7 and ipv6_parts[7].strip() else ""
            display_pdp = ipv6_pdp or pdp or "IPv4v6"
            display_apn = ipv6_apn if display_pdp.upper() == "IPV6" and ipv6_apn else apn or ipv6_apn
            if name in seen:
                continue
            seen.add(name)
            profiles.append({
                "name": name,
                "apn": display_apn,
                "pdp": display_pdp,
                "auth": parts[4].strip() if len(parts) > 4 and parts[4].strip() else "NONE",
                "user": parts[5].strip() if len(parts) > 5 else "",
                "pwd": parts[6].strip() if len(parts) > 6 else "",
                "index": str(i)
            })
        return profiles

    def _merge_manual_profiles(self, current: List[Dict[str, str]], incoming: List[Dict[str, str]]) -> List[Dict[str, str]]:
        merged = []
        by_name = {}
        for profile in list(current or []) + list(incoming or []):
            name = str(profile.get("name", "")).strip()
            if not name:
                continue
            if name in by_name:
                by_name[name].update({k: v for k, v in profile.items() if v not in (None, "")})
            else:
                by_name[name] = dict(profile)
                merged.append(by_name[name])
        for i, profile in enumerate(merged):
            profile["index"] = str(profile.get("index", i))
        return merged

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        self.txt_title.size = 13 if is_ultra_small else (16 if is_small else 18)
        label_size = 10 if is_ultra_small else (12 if is_small else 14)
        text_size = 11 if is_ultra_small else (13 if is_small else 15)

        self.txt_current_apn.size = text_size
        self.txt_warning.size = 10 if is_ultra_small else 12

        pad = ft.Padding(left=6, top=6, right=6, bottom=6) if is_ultra_small else (ft.Padding(left=10, top=8, right=10, bottom=8) if is_small else ft.Padding(left=12, top=10, right=12, bottom=10))

        for ctrl in [self.dropdown_profile, self.dropdown_pdp_type, self.dropdown_auth, self.input_profile_name, self.input_apn, self.input_user, self.input_pwd]:
            if hasattr(ctrl, "text_size"):
                ctrl.text_size = text_size
            if hasattr(ctrl, "content_padding"):
                ctrl.content_padding = pad

        button_height = 36 if is_ultra_small else 42
        button_text_size = 11 if is_ultra_small else (13 if is_small else 14)
        for btn in [self.btn_add_profile, self.btn_set_default, self.btn_apply, self.btn_delete]:
            btn.height = 32 if btn == self.btn_add_profile else button_height
            if btn == self.btn_add_profile:
                btn.width = 80
            else:
                btn.width = None  # 彻底解除宽度限制，自适应三等分生效
            if btn.style and btn.style.text_style:
                btn.style.text_style.size = button_text_size
        if is_ultra_small:
            self.action_row.alignment = ft.MainAxisAlignment.START
            self.action_row.spacing = 8
            self.action_row.run_spacing = 8
        else:
            self.action_row.alignment = ft.MainAxisAlignment.END
            self.action_row.spacing = 10
            self.action_row.run_spacing = 8

        self.padding = 8 if is_ultra_small else (12 if is_small else 15)
        self.border_radius = 8 if is_ultra_small else (10 if is_small else 12)
        self.content.spacing = 8 if is_ultra_small else (10 if is_small else 12)

        try:
            self.update()
        except Exception:
            pass

    async def on_add_profile(self, e):
        if self.is_data_connected and not await self._switch_data_connection(False, "可修改 APN"):
            return

        self.is_adding_profile = not self.is_adding_profile
        if self.is_adding_profile:
            self.selected_profile_name = ""
            self.loaded_profile_name = ""
            self.pending_new_profile_index = self._next_profile_index()
            self.dropdown_profile.value = None
            self._fill_profile_form(self._empty_profile(pdp="IPv4"))
        else:
            self.pending_new_profile_index = ""
            profile = self._find_manual_profile(self.selected_profile_name)
            self._fill_profile_form(profile or self._empty_profile())

        self.on_mode_change(None)
        self.update()

    async def on_set_default(self, e):
        was_connected = self.is_data_connected
        if was_connected and not await self._switch_data_connection(False, "准备设置 APN"):
            return
        if self.radio_mode.value == "manual" and not self._validate_manual_profile():
            if was_connected:
                await self._switch_data_connection(True, "APN 未修改")
            return

        show_toast(self.app_page, "正在设置默认 APN...", True)
        try:
            if self.radio_mode.value == "auto":
                ok = await self.api_client.post_cmd("APN_PROC_EX", {"apn_mode": "auto"})
            else:
                ok = await self.api_client.post_cmd("APN_PROC_EX", self._build_manual_payload())
                if ok:
                    ok = await self.api_client.post_cmd("APN_PROC_EX", self._build_set_default_payload())
        except Exception as ex:
            logger.error(f"APN 设为默认异常: {ex}", exc_info=DEBUG_MODE)
            ok = False

        if ok:
            if self.radio_mode.value == "manual":
                self._upsert_current_profile()
                self.is_adding_profile = False
                self.pending_new_profile_index = ""
                self._refresh_profile_dropdown()
                self.current_apn_name = self.selected_profile_name
                self.txt_current_apn.value = self.current_apn_name or "--"
            else:
                auto_name = str(self.auto_data.get("name", "") or "").strip()
                self.current_apn_name = auto_name
                self.txt_current_apn.value = auto_name or "--"
            self.set_global_status("APN 默认设置已应用", ft.Colors.PRIMARY)
            show_toast(self.app_page, "APN 默认设置成功", True)
            await asyncio.sleep(1)
            reconnected = await self._switch_data_connection(True, "APN 已生效")
            if reconnected and self.refresh_config:
                await self.refresh_config()
        else:
            self.set_global_status("APN 设置失败", ft.Colors.ERROR)
            show_toast(self.app_page, "APN 设置失败", False)
            await self._switch_data_connection(True, "APN 设置失败，已恢复数据连接")
        self.on_mode_change(None)
        self.update()

    async def on_apply(self, e):
        if not self._validate_manual_profile():
            return

        was_connected = self.is_data_connected
        if was_connected and not await self._switch_data_connection(False, "准备保存 APN"):
            return

        show_toast(self.app_page, "正在保存 APN 设置...", True)
        editing_current = (not self.is_adding_profile and self.selected_profile_name == self.current_apn_name)
        try:
            ok = await self.api_client.post_cmd("APN_PROC_EX", self._build_manual_payload())
            if ok and editing_current:
                ok = await self.api_client.post_cmd("APN_PROC_EX", self._build_set_default_payload())
        except Exception as ex:
            logger.error(f"APN 应用异常: {ex}", exc_info=DEBUG_MODE)
            ok = False
        if ok:
            self._upsert_current_profile()
            self.is_adding_profile = False
            self.pending_new_profile_index = ""
            self.just_saved_manual_profile = True
            self._refresh_profile_dropdown()
            if editing_current:
                self.current_apn_name = self.selected_profile_name
                self.txt_current_apn.value = self.current_apn_name or "--"
            self.set_global_status("APN 已保存", ft.Colors.PRIMARY)
            show_toast(self.app_page, "APN 保存成功", True)
            await asyncio.sleep(1)
            reconnected = await self._switch_data_connection(True, "APN 已生效")
            if reconnected and self.refresh_config:
                await self.refresh_config()
        else:
            self.set_global_status("APN 保存失败", ft.Colors.ERROR)
            show_toast(self.app_page, "APN 保存失败", False)
            await self._switch_data_connection(True, "APN 保存失败，已恢复数据连接")
        self.on_mode_change(None)
        self.update()

    async def on_delete(self, e):
        if self.is_adding_profile:
            self.is_adding_profile = False
            self.selected_profile_name = self.manual_profiles[0].get("name", "") if self.manual_profiles else ""
            self._refresh_profile_dropdown()
            self._fill_profile_form(self._empty_profile(pdp="IPv4"))
            self.on_mode_change(None)
            self.update()
            return
        if not self.selected_profile_name:
            show_toast(self.app_page, "请选择要删除的 APN 配置", False)
            return
        profile_count = self.raw_manual_profile_count or len(self.manual_profiles)
        is_last_manual_profile = profile_count <= 1

        was_connected = self.is_data_connected
        if was_connected and not await self._switch_data_connection(False, "准备删除 APN"):
            return

        show_toast(self.app_page, "正在删除 APN 设置...", True)
        profile = self._find_manual_profile(self.selected_profile_name) or {}
        try:
            ok = await self.api_client.post_cmd("APN_PROC_EX", {
                "apn_action": "delete",
                "apn_mode": "manual",
                "index": str(profile.get("index", "0"))
            })
            if ok and is_last_manual_profile:
                ok = await self.api_client.post_cmd("APN_PROC_EX", {"apn_mode": "auto"})
            elif ok and self.selected_profile_name == self.current_apn_name:
                remaining = [p for p in self.manual_profiles if p.get("name") != self.selected_profile_name]
                if remaining:
                    target = remaining[0]
                    ok = await self.api_client.post_cmd("APN_PROC_EX", {
                        "apn_mode": "manual",
                        "apn_action": "set_default",
                        "set_default_flag": "1",
                        "pdp_type": self._api_pdp_type(target.get("pdp", "IPv4v6")),
                        "index": str(target.get("index", "0"))
                    })
        except Exception as ex:
            logger.error(f"APN 删除异常: {ex}", exc_info=DEBUG_MODE)
            ok = False
        if ok:
            deleted_name = self.selected_profile_name
            self.manual_profiles = [p for p in self.manual_profiles if p.get("name") != self.selected_profile_name]
            self.selected_profile_name = self.manual_profiles[0].get("name", "") if self.manual_profiles else ""
            self._refresh_profile_dropdown()
            if not self.manual_profiles:
                self._fill_profile_form(self._empty_profile())
            if is_last_manual_profile:
                self.mode = "auto"
                self.radio_mode.value = "auto"
                auto_name = str(self.auto_data.get("name", "") or "").strip()
                self.current_apn_name = auto_name
                self.txt_current_apn.value = auto_name or "--"
            elif deleted_name == self.current_apn_name and self.manual_profiles:
                self.current_apn_name = self.manual_profiles[0].get("name", "")
                self.txt_current_apn.value = self.current_apn_name or "--"
            self.set_global_status("APN 已删除", ft.Colors.PRIMARY)
            show_toast(self.app_page, "APN 删除成功", True)
            await asyncio.sleep(1)
            reconnected = await self._switch_data_connection(True, "APN 已删除")
            if reconnected and self.refresh_config:
                await self.refresh_config()
        else:
            self.set_global_status("APN 删除失败", ft.Colors.ERROR)
            show_toast(self.app_page, "APN 删除失败", False)
            await self._switch_data_connection(True, "APN 删除失败，已恢复数据连接")
        self.on_mode_change(None)
        self.update()

    def _current_form_profile(self) -> Dict[str, str]:
        return {
            "name": str(self.input_profile_name.value or "").strip(),
            "apn": str(self.input_apn.value or "").strip(),
            "pdp": self.dropdown_pdp_type.value or "IPv4v6",
            "auth": self.dropdown_auth.value or "NONE",
            "user": str(self.input_user.value or "").strip(),
            "pwd": str(self.input_pwd.value or "").strip(),
            "index": (self.pending_new_profile_index or self._next_profile_index()) if self.is_adding_profile else str((self._find_manual_profile(self.selected_profile_name) or {}).get("index", self._next_profile_index()))
        }

    def _validate_manual_profile(self) -> bool:
        profile = self._current_form_profile()
        if not profile["name"]:
            show_toast(self.app_page, "请输入配置文件名称", False)
            return False
        if not profile["apn"]:
            show_toast(self.app_page, "请输入 APN", False)
            return False
        return True

    def _upsert_current_profile(self):
        profile = self._current_form_profile()
        replaced = False
        for i, item in enumerate(self.manual_profiles):
            same_name = item.get("name") == profile["name"]
            editing_selected = (not self.is_adding_profile and item.get("name") == self.selected_profile_name)
            if same_name or editing_selected:
                self.manual_profiles[i] = profile
                replaced = True
                break
        if not replaced:
            self.manual_profiles.append(profile)
        self.selected_profile_name = profile["name"]

    def _build_manual_payload(self):
        profile = self._current_form_profile()
        pdp = self._api_pdp_type(profile["pdp"])
        auth = profile["auth"].lower()
        payload = {
            "apn_action": "save",
            "apn_mode": "manual",
            "profile_name": profile["name"],
            "wan_dial": "*99#",
            "apn_select": "manual",
            "pdp_type": pdp,
            "pdp_select": "auto",
            "pdp_addr": "",
            "index": profile["index"]
        }
        if pdp in ("IP", "IPv4v6"):
            payload.update({
                "wan_apn": profile["apn"],
                "ppp_auth_mode": auth,
                "ppp_username": profile["user"],
                "ppp_passwd": profile["pwd"],
                "dns_mode": "auto",
                "prefer_dns_manual": "",
                "standby_dns_manual": ""
            })
        if pdp in ("IPv6", "IPv4v6"):
            payload.update({
                "ipv6_wan_apn": profile["apn"],
                "ipv6_ppp_auth_mode": auth,
                "ipv6_ppp_username": profile["user"],
                "ipv6_ppp_passwd": profile["pwd"],
                "ipv6_dns_mode": "auto",
                "ipv6_prefer_dns_manual": "",
                "ipv6_standby_dns_manual": ""
            })
        return payload
    def _build_set_default_payload(self):
        profile = self._current_form_profile()
        return {
            "apn_mode": "manual",
            "apn_action": "set_default",
            "set_default_flag": "1",
            "pdp_type": self._api_pdp_type(profile["pdp"]),
            "index": profile["index"]
        }

# ==========================================
# 主程序：应用类封装
# ==========================================

# ==========================================
# UI 组件拆分 - 防火墙卡片
# ==========================================
class FirewallCard(ft.Container):
    FEATURES = [
        ("port_filter", "端口过滤"),
        ("port_forward", "端口转发"),
        ("port_map", "端口映射"),
        ("upnp", "UPnP"),
        ("dmz", "DMZ"),
        ("system_security", "系统安全"),
    ]

    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable):
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12, visible=False)
        self.app_page = page
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.current_feature = None
        self.feature_buttons: List[ft.Control] = []
        self.background_tasks: Set[asyncio.Task] = set()  # 保存后台 Task 强引用
        self.build_ui()

    def build_ui(self):
        self.txt_title = ft.Text("防火墙", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.txt_hint = ft.Text("选择下方功能进行设置", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        feature_items = []
        for key, label in self.FEATURES:
            btn = create_button(label, on_click=self._make_feature_click(key), height=48, expand=True)
            self.feature_buttons.append(btn)
            feature_items.append(ft.Container(btn, col={"xs": 12, "sm": 6}))
        self.feature_menu = ft.ResponsiveRow(controls=feature_items, spacing=14, run_spacing=14)

        self.pf_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_pf_enable_change,
        )
        self.txt_pf_enable_label = ft.Text("MAC/IP/端口过滤", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.pf_policy = create_dropdown(
            "默认策略",
            [ft.dropdown.Option("0", "放行"), ft.dropdown.Option("1", "丢弃")],
            "0",
            expand=True,
        )
        self.pf_policy.on_change = self.on_pf_policy_change
        self.btn_pf_save = create_button("应用", on_click=self.on_save_port_filter)

        # 规则表单（仅启用后显示）
        self.txt_pf_settings_title = ft.Text("MAC/IP/端口过滤设置", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.pf_ip_type = create_dropdown(
            "IP 设置",
            [ft.dropdown.Option("ipv4", "IPv4"), ft.dropdown.Option("ipv6", "IPv6")],
            "ipv4",
            expand=True,
        )
        self.pf_ip_type.on_change = self.on_pf_ip_type_change
        self.pf_mac = create_text_field("MAC 地址", "", multiline=True, min_lines=1, max_lines=2, expand=True, hint_text="例如：00:1E:90:FF:FF:FF")
        self.pf_sip = create_text_field("源 IP 地址", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.pf_dip = create_text_field("目的 IP 地址", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.pf_protocol = create_dropdown(
            "协议",
            [
                ft.dropdown.Option("None", "全部"),
                ft.dropdown.Option("TCP", "TCP"),
                ft.dropdown.Option("UDP", "UDP"),
                ft.dropdown.Option("ICMP", "ICMP"),
            ],
            "None",
            expand=True,
        )
        self.pf_protocol.on_change = self.on_pf_protocol_change
        self.pf_action = create_dropdown(
            "操作",
            [ft.dropdown.Option("Accept", "放行"), ft.dropdown.Option("Drop", "丢弃")],
            "Drop",
            expand=True,
        )
        self.txt_pf_src_port_range = ft.Text("源端口范围 (1~65535)", size=13, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.pf_sport_start = create_text_field("源端口起", "0", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.pf_sport_end = create_text_field("源端口止", "0", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.txt_pf_dst_port_range = ft.Text("目的端口范围 (1~65535)", size=13, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.pf_dport_start = create_text_field("目的端口起", "0", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.pf_dport_end = create_text_field("目的端口止", "0", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.pf_comment = create_text_field("备注", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.btn_pf_add = create_button("应用", on_click=self.on_add_port_filter_rule)
        self.txt_pf_rules_title = ft.Text("当前过滤规则", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.pf_rules_list = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.pf_rules_empty = ft.Text("暂无过滤规则", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.btn_pf_delete = create_button("删除", on_click=self.on_delete_port_filter_rules)
        self.pf_rules: List[Dict] = []
        self.pf_rule_checks: Dict[str, ft.Checkbox] = {}
        self._pf_loading = False

        self.fw_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_fw_enable_change,
        )
        self.txt_fw_enable_label = ft.Text("启用端口转发", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.fw_ip = create_text_field("IP 地址", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.fw_port_start = create_text_field("端口起", "", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.fw_port_end = create_text_field("端口止", "", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.txt_fw_port_range = ft.Text("端口范围 (1~65535)", size=13, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.fw_protocol = create_dropdown("协议", [ft.dropdown.Option("TCP&UDP", "TCP+UDP"), ft.dropdown.Option("TCP", "TCP"), ft.dropdown.Option("UDP", "UDP")], "TCP&UDP", expand=True)
        self.fw_comment = create_text_field("备注", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.btn_fw_add = create_button("添加", on_click=self.on_add_port_forward_rule)
        self.btn_fw_delete = create_button("删除", on_click=self.on_delete_port_forward_rules)
        self.fw_rules: List[Dict] = []
        self.fw_rule_checks: Dict[int, ft.Checkbox] = {}
        self.txt_fw_rules_title = ft.Text("当前转发规则", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.fw_rules_list = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.fw_rules_empty = ft.Text("暂无转发规则", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.pm_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_pm_enable_change,
        )
        self.pm_from = create_text_field("源端口 (1~65000)", "", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.pm_ip = create_text_field("目的 IP 地址", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.pm_to = create_text_field("目的端口 (1~65000)", "", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.pm_protocol = create_dropdown("协议", [ft.dropdown.Option("TCP&UDP", "TCP+UDP"), ft.dropdown.Option("TCP", "TCP"), ft.dropdown.Option("UDP", "UDP")], "TCP&UDP", expand=True)
        self.pm_comment = create_text_field("备注", "", multiline=True, min_lines=1, max_lines=3, expand=True)
        self.btn_pm_add = create_button("添加", on_click=self.on_add_port_map_rule)
        self.txt_pm_enable_label = ft.Text("启用端口映射", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.btn_pm_delete = create_button("删除", on_click=self.on_delete_port_map_rules)
        self.pm_rules: List[Dict] = []
        self.pm_rule_checks: Dict[int, ft.Checkbox] = {}
        self.is_small_layout = False
        self.is_ultra_small_layout = False
        self.txt_pm_rules_title = ft.Text("当前映射规则", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.pm_rules_list = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.pm_rules_empty = ft.Text("暂无映射规则", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.upnp_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_upnp_enable_change,
        )
        self.txt_upnp_enable_label = ft.Text("启用 UPnP", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)

        self.dmz_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_dmz_enable_change,
        )
        self.dmz_ip = create_text_field("DMZ 主机 IP", "", visible=False, multiline=True, min_lines=1, max_lines=3, expand=True)
        self.btn_dmz_save = create_button("应用", on_click=self.on_save_dmz)
        self.btn_dmz_save.visible = False

        self.remote_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_sys_security_change,
        )
        self.ping_enable = ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=self.on_sys_security_change,
        )
        self.txt_remote_label = ft.Text("远程管理（通过 WAN 口）", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.txt_ping_label = ft.Text("从外网 PING 入", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self._sys_security_loading = False

        self.panel_port_filter = ft.Column([
            ft.Row([self.pf_enable, self.txt_pf_enable_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            self.pf_policy,
            self.btn_pf_save,
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.txt_pf_settings_title,
            self.pf_ip_type,
            self.pf_mac,
            self.pf_sip,
            self.pf_dip,
            self.pf_protocol,
            self.pf_action,
            self.txt_pf_src_port_range,
            ft.ResponsiveRow([
                ft.Container(self.pf_sport_start, col={"xs": 12, "sm": 6}),
                ft.Container(self.pf_sport_end, col={"xs": 12, "sm": 6}),
            ], spacing=8, run_spacing=8),
            self.txt_pf_dst_port_range,
            ft.ResponsiveRow([
                ft.Container(self.pf_dport_start, col={"xs": 12, "sm": 6}),
                ft.Container(self.pf_dport_end, col={"xs": 12, "sm": 6}),
            ], spacing=8, run_spacing=8),
            self.pf_comment,
            self.btn_pf_add,
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.txt_pf_rules_title,
            self.pf_rules_list,
            self.pf_rules_empty,
            self.btn_pf_delete,
        ], spacing=10, visible=False)

        self.panel_port_forward = ft.Column([
            ft.Row([self.fw_enable, self.txt_fw_enable_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.fw_ip,
            self.txt_fw_port_range,
            ft.ResponsiveRow([
                ft.Container(self.fw_port_start, col={"xs": 12, "sm": 6}),
                ft.Container(self.fw_port_end, col={"xs": 12, "sm": 6}),
            ], spacing=8, run_spacing=8),
            self.fw_protocol,
            self.fw_comment,
            self.btn_fw_add,
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.txt_fw_rules_title,
            self.fw_rules_list,
            self.fw_rules_empty,
            self.btn_fw_delete,
        ], spacing=10, visible=False)

        self.panel_port_map = ft.Column([
            ft.Row([self.pm_enable, self.txt_pm_enable_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.pm_from,
            self.pm_ip,
            self.pm_to,
            self.pm_protocol,
            self.pm_comment,
            self.btn_pm_add,
            ft.Divider(height=8, color=ft.Colors.OUTLINE_VARIANT),
            self.txt_pm_rules_title,
            self.pm_rules_list,
            self.pm_rules_empty,
            self.btn_pm_delete,
        ], spacing=10, visible=False)

        self.panel_upnp = ft.Column([
            ft.Row([self.upnp_enable, self.txt_upnp_enable_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
        ], spacing=10, visible=False)

        self.panel_dmz = ft.Column([
            ft.Row([self.dmz_enable, ft.Text("启用", color=ft.Colors.INVERSE_PRIMARY)], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            self.dmz_ip,
            self.btn_dmz_save,
        ], spacing=10, visible=False)

        self.panel_system_security = ft.Column([
            ft.Row([self.remote_enable, self.txt_remote_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
            ft.Row([self.ping_enable, self.txt_ping_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
        ], spacing=10, visible=False)

        self.detail_panel = ft.Column([
            self.panel_port_filter,
            self.panel_port_forward,
            self.panel_port_map,
            self.panel_upnp,
            self.panel_dmz,
            self.panel_system_security,
        ], spacing=0, visible=False)

        self.content = ft.Column([
            self.txt_title,
            self.txt_hint,
            ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
            self.feature_menu,
            self.detail_panel,
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _make_feature_click(self, key: str):
        async def handler(e):
            await self.show_feature(key)
        return handler

    def _hide_all_panels(self):
        for p in [
            self.panel_port_filter, self.panel_port_forward, self.panel_port_map,
            self.panel_upnp, self.panel_dmz, self.panel_system_security
        ]:
            p.visible = False

    def _to_bool_flag(self, value) -> bool:
        """设备开关字段统一解析：1/true/on/yes 视为开启"""
        return str(value).strip().lower() in {"1", "true", "on", "yes", "enable", "enabled"}

    async def sync_current_feature(self):
        """登录/重登后，如果当前正停留在防火墙功能页，则重新查询并同步开关状态"""
        if not self.visible or not self.current_feature:
            return
        await self.load_feature(self.current_feature)

    def show_menu(self):
        self.current_feature = None
        self.feature_menu.visible = True
        self.detail_panel.visible = False
        self._hide_all_panels()
        self.txt_title.value = "防火墙"
        self.txt_hint.value = "选择下方功能进行设置"
        self.txt_hint.visible = True
        try:
            self.update()
        except Exception:
            pass

    async def show_feature(self, key: str):
        self.current_feature = key
        self.feature_menu.visible = False
        self.detail_panel.visible = True
        self._hide_all_panels()
        titles = {k: n for k, n in self.FEATURES}
        self.txt_title.value = titles.get(key, "防火墙")
        self.txt_hint.visible = False
        panel_map = {
            "port_filter": self.panel_port_filter,
            "port_forward": self.panel_port_forward,
            "port_map": self.panel_port_map,
            "upnp": self.panel_upnp,
            "dmz": self.panel_dmz,
            "system_security": self.panel_system_security,
        }
        panel = panel_map.get(key)
        if panel:
            panel.visible = True
        try:
            self.update()
        except Exception:
            pass
        await self.load_feature(key)

    async def load_feature(self, key: str, silent: bool = False):
        try:
            if key == "port_filter":
                cmd = "IPPortFilterEnable,DefaultFirewallPolicy," + ",".join(
                    [f"IPPortFilterRules_{i}" for i in range(10)]
                    + [f"IPPortFilterRulesv6_{i}" for i in range(10)]
                )
                data = await self.api_client.get_cmd(cmd, multi_data=True)
                self._pf_loading = True
                try:
                    self.pf_enable.value = str(data.get("IPPortFilterEnable", "0")) == "1"
                    self.pf_policy.value = str(data.get("DefaultFirewallPolicy", "0") or "0")
                    # 默认策略 1=丢弃 -> 规则操作默认放行；0=放行 -> 规则操作默认丢弃
                    self.pf_action.value = "Accept" if self.pf_policy.value == "1" else "Drop"
                    self.pf_rules = self._parse_port_filter_rules(data)
                    self._render_port_filter_rules()
                    self.on_pf_ip_type_change()
                    self._update_port_filter_visibility()
                finally:
                    self._pf_loading = False
            elif key == "port_forward":
                cmd = "PortForwardEnable," + ",".join([f"PortForwardRules_{i}" for i in range(20)])
                data = await self.api_client.get_cmd(cmd, multi_data=True)
                self.fw_enable.value = str(data.get("PortForwardEnable", "0")) == "1"
                self.fw_rules = self._parse_port_forward_rules(data)
                self._render_port_forward_rules()
            elif key == "port_map":
                cmd = "PortMapEnable," + ",".join([f"PortMapRules_{i}" for i in range(20)])
                data = await self.api_client.get_cmd(cmd, multi_data=True)
                self.pm_enable.value = str(data.get("PortMapEnable", "0")) == "1"
                self.pm_rules = self._parse_port_map_rules(data)
                self._render_port_map_rules()
            elif key == "upnp":
                data = await self.api_client.get_cmd("upnpEnabled", multi_data=True)
                self.upnp_enable.value = str(data.get("upnpEnabled", "0")) == "1"
            elif key == "dmz":
                data = await self.api_client.get_cmd(
                    "DMZEnable,DMZIPAddress,lan_ipaddr,lan_netmask", multi_data=True
                )
                self.dmz_enable.value = str(data.get("DMZEnable", "0")) == "1"
                self.dmz_ip.value = data.get("DMZIPAddress", "") or ""
                enabled = bool(self.dmz_enable.value)
                self.dmz_ip.visible = enabled
                self.btn_dmz_save.visible = enabled
            elif key == "system_security":
                data = await self.api_client.get_cmd(
                    "RemoteManagement,WANPingFilter", multi_data=True
                )
                # 与官方一致：1=启用，0=关闭；兼容空值/布尔字符串
                self._sys_security_loading = True
                try:
                    self.remote_enable.value = self._to_bool_flag(data.get("RemoteManagement"))
                    self.ping_enable.value = self._to_bool_flag(data.get("WANPingFilter"))
                finally:
                    self._sys_security_loading = False
                logger.info(
                    "系统安全状态同步: RemoteManagement=%r -> %s, WANPingFilter=%r -> %s",
                    data.get("RemoteManagement"), self.remote_enable.value,
                    data.get("WANPingFilter"), self.ping_enable.value,
                )
            try:
                self.update()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"加载防火墙配置失败 [{key}]: {e}", exc_info=DEBUG_MODE)
            if not silent:
                self.set_global_status("防火墙配置加载失败", ft.Colors.ERROR)
                show_toast(self.app_page, "防火墙配置加载失败", False)

    def _update_port_filter_visibility(self):
        """关闭时只显示总开关；开启后显示默认策略、应用按钮和规则区"""
        enabled = bool(self.pf_enable.value)
        # 应用按钮只在开启时显示，且只用于提交默认策略
        self.pf_policy.visible = enabled
        self.btn_pf_save.visible = enabled
        for ctrl in [
            self.txt_pf_settings_title, self.pf_ip_type, self.pf_mac, self.pf_sip, self.pf_dip,
            self.pf_protocol, self.pf_action, self.pf_comment, self.btn_pf_add,
            self.txt_pf_rules_title, self.pf_rules_list, self.pf_rules_empty, self.btn_pf_delete,
            self.txt_pf_src_port_range, self.pf_sport_start, self.pf_sport_end,
            self.txt_pf_dst_port_range, self.pf_dport_start, self.pf_dport_end,
        ]:
            ctrl.visible = enabled
        if enabled:
            self.on_pf_protocol_change()
        try:
            self.update()
        except Exception:
            pass

    def on_pf_enable_change(self, e=None):
        # 默认规则操作跟随默认策略：丢弃(1)->放行规则，放行(0)->丢弃规则
        self.pf_action.value = "Accept" if str(self.pf_policy.value or "0") == "1" else "Drop"
        self._update_port_filter_visibility()
        # 开关即时提交启用/关闭；默认策略仍由“应用”按钮单独提交
        if getattr(self, "_pf_loading", False):
            return
        spawn_background_task(self, self._submit_port_filter_enable())

    def on_pf_policy_change(self, e=None):
        self.pf_action.value = "Accept" if str(self.pf_policy.value or "0") == "1" else "Drop"
        try:
            self.update()
        except Exception:
            pass

    def on_pf_ip_type_change(self, e=None):
        # 官方：IPv6 时标签为 源/目的 IPv6 地址
        is_v6 = str(self.pf_ip_type.value or "ipv4").lower() == "ipv6"
        self.pf_sip.label = "源 IPv6 地址" if is_v6 else "源 IP 地址"
        self.pf_dip.label = "目的 IPv6 地址" if is_v6 else "目的 IP 地址"
        try:
            self.update()
        except Exception:
            pass

    def on_pf_protocol_change(self, e=None):
        proto = str(self.pf_protocol.value or "None")
        need_port = proto in {"TCP", "UDP"}
        for ctrl in [
            self.txt_pf_src_port_range, self.pf_sport_start, self.pf_sport_end,
            self.txt_pf_dst_port_range, self.pf_dport_start, self.pf_dport_end,
        ]:
            ctrl.visible = bool(self.pf_enable.value) and need_port
        if need_port:
            if str(self.pf_sport_start.value or "0") == "0":
                self.pf_sport_start.value = "1"
            if str(self.pf_sport_end.value or "0") == "0":
                self.pf_sport_end.value = "65535"
            if str(self.pf_dport_start.value or "0") == "0":
                self.pf_dport_start.value = "1"
            if str(self.pf_dport_end.value or "0") == "0":
                self.pf_dport_end.value = "65535"
        else:
            self.pf_sport_start.value = "0"
            self.pf_sport_end.value = "0"
            self.pf_dport_start.value = "0"
            self.pf_dport_end.value = "0"
        try:
            self.update()
        except Exception:
            pass

    async def _submit_port_filter_enable(self):
        """开关只提交启用状态，并带上当前默认策略值（设备接口需要两个字段）"""
        try:
            enabled = bool(self.pf_enable.value)
            ok = await self.api_client.post_cmd("BASIC_SETTING", {
                "portFilterEnabled": "1" if enabled else "0",
                "defaultFirewallPolicy": self.pf_policy.value or "0",
            })
            if ok:
                show_toast(self.app_page, f"端口过滤已{'开启' if enabled else '关闭'}", True)
                await self.load_feature("port_filter", silent=True)
            else:
                show_toast(self.app_page, "端口过滤开关更新失败", False)
                await self.load_feature("port_filter", silent=True)
        except Exception as ex:
            logger.error(f"切换端口过滤开关失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "端口过滤开关更新异常", False)
            try:
                await self.load_feature("port_filter", silent=True)
            except Exception:
                pass

    async def on_save_port_filter(self, e):
        """应用按钮：仅在开启时提交默认策略"""
        try:
            if not self.pf_enable.value:
                show_toast(self.app_page, "请先开启 MAC/IP/端口过滤", False)
                return
            ok = await self.api_client.post_cmd("BASIC_SETTING", {
                "portFilterEnabled": "1",
                "defaultFirewallPolicy": self.pf_policy.value or "0",
            })
            if ok:
                self.set_global_status("默认策略已应用", ft.Colors.PRIMARY)
                show_toast(self.app_page, "默认策略应用成功", True)
                await self.load_feature("port_filter")
            else:
                self.set_global_status("默认策略应用失败", ft.Colors.ERROR)
                show_toast(self.app_page, "默认策略应用失败", False)
        except Exception as ex:
            logger.error(f"应用默认策略失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "默认策略应用异常", False)

    def _filter_action_label(self, value: str) -> str:
        v = str(value or "").strip().lower()
        if v in {"1", "accept", "filter_accept", "放行"}:
            return "放行"
        if v in {"0", "drop", "filter_drop", "丢弃"}:
            return "丢弃"
        return str(value or "--")

    def _parse_port_filter_rules(self, data: Dict) -> List[Dict]:
        rules: List[Dict] = []

        def parse_one(raw: str, index: int, device_index: int, ip_type: str):
            parts = raw.split(",")
            while len(parts) < 12:
                parts.append("")
            sip = "" if parts[0] in {"", "any/0"} else parts[0]
            dip = "" if parts[4] in {"", "any/0"} else parts[4]
            s_from, s_to = parts[2], parts[3]
            d_from, d_to = parts[6], parts[7]
            sport = "" if str(s_from) == "0" else f"{s_from} - {s_to}"
            dport = "" if str(d_from) == "0" else f"{d_from} - {d_to}"
            action_raw = parts[9]
            rules.append({
                "index": str(index),
                "device_index": str(device_index),
                "macAddress": parts[11],
                "sourceIpAddress": sip,
                "destIpAddress": dip,
                "sourcePortRange": sport or "--",
                "destPortRange": dport or "--",
                "protocol": self._filter_protocol_label(parts[8]),
                "protocol_raw": parts[8],
                "action": self._filter_action_label(action_raw),
                "action_raw": action_raw,
                "comment": parts[10],
                "ipType": ip_type,
            })

        for i in range(10):
            raw = str(data.get(f"IPPortFilterRules_{i}", "") or "").strip()
            if raw:
                parse_one(raw, i, i, "IPv4")
        for i in range(10):
            raw = str(data.get(f"IPPortFilterRulesv6_{i}", "") or "").strip()
            if raw:
                parse_one(raw, 10 + i, i, "IPv6")
        return rules

    def _filter_protocol_label(self, value: str) -> str:
        """端口过滤协议显示：对齐官方 util.js transProtocol
        数字码：1=TCP, 2=UDP, 3=TCP+UDP, 4=ICMP, 5=ALL(全部)
        提交/字符串：None/ALL->全部, TCP/UDP/ICMP
        """
        raw = str(value or "").strip()
        v = raw.upper().replace("+", "&")
        mapping = {
            # 官方 util.js: transProtocol
            "1": "TCP",
            "2": "UDP",
            "3": "TCP+UDP",
            "4": "ICMP",
            "5": "全部",
            # 提交/显示字符串（ADD 用 protocol=None|TCP|UDP|ICMP）
            "NONE": "全部",
            "NULL": "全部",
            "ALL": "全部",
            "全部": "全部",
            "TCP": "TCP",
            "UDP": "UDP",
            "ICMP": "ICMP",
            "TCP&UDP": "TCP+UDP",
            "TCP+UDP": "TCP+UDP",
            # 兼容空/异常码
            "0": "全部",
            "": "全部",
        }
        return mapping.get(v, mapping.get(raw, (raw or "--")))

    def _render_port_filter_rules(self):
        """大屏横向一行；小屏标签/内容分行显示"""
        self.pf_rule_checks = {}
        rows = []
        text_size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 13)
        item_padding = 5 if self.is_ultra_small_layout else (7 if self.is_small_layout else 10)
        item_spacing = 4 if self.is_ultra_small_layout else 8

        for rule in self.pf_rules:
            cb = create_checkbox(label="", value=False, data=str(rule["index"]))
            if getattr(cb, "label_style", None) is None:
                cb.label_style = ft.TextStyle(size=text_size, color=ft.Colors.ON_SURFACE)
            else:
                cb.label_style.size = text_size
            self.pf_rule_checks[str(rule["index"])] = cb

            mac = str(rule.get("macAddress") or "").strip() or "--"
            ip_type = str(rule.get("ipType") or "--")
            sip = str(rule.get("sourceIpAddress") or "").strip() or "--"
            dip = str(rule.get("destIpAddress") or "").strip() or "--"
            protocol = str(rule.get("protocol") or "--")
            sport = str(rule.get("sourcePortRange") or "--")
            dport = str(rule.get("destPortRange") or "--")
            action = str(rule.get("action") or "--")
            comment = str(rule.get("comment") or "").strip() or "--"

            if self.is_small_layout or self.is_ultra_small_layout:
                def _kv(label: str, value: str) -> ft.Column:
                    return ft.Column(
                        [
                            ft.Text(f"{label}：", size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    )
                info = ft.Column(
                    [
                        _kv("MAC 地址", mac),
                        _kv("IP 类型", ip_type),
                        _kv("源 IP 地址", sip),
                        _kv("目的 IP 地址", dip),
                        _kv("协议", protocol),
                        _kv("源端口范围", sport),
                        _kv("目的端口范围", dport),
                        _kv("操作", action),
                        _kv("备注", comment),
                    ],
                    spacing=2 if self.is_ultra_small_layout else 3,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                )
                item_content = ft.Column(
                    [
                        ft.Row(
                            [cb, ft.Text(f"规则 {int(rule.get('index', 0)) + 1 if str(rule.get('index', '0')).isdigit() else rule.get('index')}", size=text_size, color=ft.Colors.ON_SURFACE_VARIANT)],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        info,
                    ],
                    spacing=item_spacing,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                )
            else:
                # 大屏：与官方表格一致，横向一行
                def cell(title: str, value: str, expand: int = 1) -> ft.Container:
                    return ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(title, size=11, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False),
                                ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ],
                            spacing=2,
                        ),
                        expand=expand,
                    )
                info = ft.Row(
                    [
                        cell("MAC 地址", mac, 1),
                        cell("IP 类型", ip_type, 1),
                        cell("源 IP 地址", sip, 2),
                        cell("目的 IP 地址", dip, 2),
                        cell("协议", protocol, 1),
                        cell("源端口范围", sport, 1),
                        cell("目的端口范围", dport, 1),
                        cell("操作", action, 1),
                        cell("备注", comment, 1),
                    ],
                    spacing=item_spacing,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
                item_content = ft.Row(
                    [
                        ft.Container(cb, width=28, alignment=ft.Alignment(-1, 0)),
                        info,
                    ],
                    spacing=item_spacing,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )

            rows.append(
                ft.Container(
                    content=item_content,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=8,
                    padding=item_padding,
                )
            )

        self.pf_rules_list.controls = rows
        self.pf_rules_list.spacing = 4 if self.is_ultra_small_layout else (6 if self.is_small_layout else 8)
        self.pf_rules_empty.visible = len(rows) == 0
        self.pf_rules_empty.size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 12)
        self.txt_pf_rules_title.size = 11 if self.is_ultra_small_layout else (13 if self.is_small_layout else 15)

    async def on_add_port_filter_rule(self, e):
        try:
            if not self.pf_enable.value:
                show_toast(self.app_page, "请先启用 MAC/IP/端口过滤", False)
                return
            comment = (self.pf_comment.value or "").strip()
            if not comment:
                show_toast(self.app_page, "备注不能为空", False)
                return
            # 官方抓包：IPv4/IPv6 都走 ADD_IP_PORT_FILETER_V4V6，并带 ip_version
            ip_type = str(self.pf_ip_type.value or "ipv4").lower()
            if ip_type not in {"ipv4", "ipv6"}:
                ip_type = "ipv4"
            # MAC / IP：有填写才校验，允许留空
            mac_norm = normalize_mac(self.pf_mac.value or "")
            if mac_norm is None:
                show_toast(self.app_page, "MAC 地址格式不正确", False)
                return
            sip = (self.pf_sip.value or "").strip()
            dip = (self.pf_dip.value or "").strip()
            if sip and not is_valid_ip(sip, ip_type):
                show_toast(self.app_page, f"源 IP 地址格式不正确（需 {ip_type.upper()}）", False)
                return
            if dip and not is_valid_ip(dip, ip_type):
                show_toast(self.app_page, f"目的 IP 地址格式不正确（需 {ip_type.upper()}）", False)
                return
            d_from = (self.pf_dport_start.value or "0").strip() or "0"
            d_to = (self.pf_dport_end.value or "0").strip() or "0"
            s_from = (self.pf_sport_start.value or "0").strip() or "0"
            s_to = (self.pf_sport_end.value or "0").strip() or "0"
            for label, a, b in (
                ("目的端口", d_from, d_to),
                ("源端口", s_from, s_to),
            ):
                ok_range, err = is_valid_port_range(a, b, min_port=0, max_port=65535, allow_zero=True)
                if not ok_range:
                    show_toast(self.app_page, f"{label}{err}", False)
                    return
            params = {
                "ip_version": ip_type,
                "mac_address": mac_norm,
                "dip_address": dip,
                "sip_address": sip,
                "dFromPort": str(int(d_from)),
                "dToPort": str(int(d_to)),
                "sFromPort": str(int(s_from)),
                "sToPort": str(int(s_to)),
                "action": self.pf_action.value or "Drop",
                "protocol": self.pf_protocol.value or "None",
                "comment": comment,
            }
            goform = "ADD_IP_PORT_FILETER_V4V6"
            ok = await self.api_client.post_cmd(goform, params)
            if ok:
                self.pf_mac.value = ""
                self.pf_sip.value = ""
                self.pf_dip.value = ""
                self.pf_comment.value = ""
                self.pf_protocol.value = "None"
                self.on_pf_protocol_change()
                show_toast(self.app_page, "过滤规则已添加", True)
                await self.load_feature("port_filter")
            else:
                show_toast(self.app_page, "过滤规则添加失败", False)
        except Exception as ex:
            logger.error(f"添加端口过滤规则失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "过滤规则添加异常", False)

    async def on_delete_port_filter_rules(self, e):
        try:
            selected = [str(idx) for idx, cb in self.pf_rule_checks.items() if cb.value]
            if not selected:
                show_toast(self.app_page, "请先选择要删除的规则", False)
                return
            # 官方抓包：删除统一走 DEL_IP_PORT_FILETER_V4V6
            # delete_id=0;  delete_id_v6=0;（可为空，末尾带分号）
            rule_by_index = {str(r.get("index")): r for r in self.pf_rules}
            v4_ids = []
            v6_ids = []
            for idx in selected:
                rule = rule_by_index.get(str(idx), {})
                dev_idx = str(rule.get("device_index", ""))
                if not dev_idx:
                    continue
                if str(rule.get("ipType", "")).upper() == "IPV6":
                    v6_ids.append(dev_idx)
                else:
                    v4_ids.append(dev_idx)
            ok = await self.api_client.post_cmd("DEL_IP_PORT_FILETER_V4V6", {
                "delete_id": (";".join(v4_ids) + ";") if v4_ids else "",
                "delete_id_v6": (";".join(v6_ids) + ";") if v6_ids else "",
            })
            if ok:
                show_toast(self.app_page, "过滤规则已删除", True)
                await self.load_feature("port_filter")
            else:
                show_toast(self.app_page, "过滤规则删除失败", False)
        except Exception as ex:
            logger.error(f"删除端口过滤规则失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "过滤规则删除异常", False)

    def _parse_port_forward_rules(self, data: Dict) -> List[Dict]:
        rules = []
        for i in range(20):
            raw = str(data.get(f"PortForwardRules_{i}", "") or "").strip()
            if not raw:
                continue
            parts = raw.split(",")
            while len(parts) < 5:
                parts.append("")
            port_start = parts[1]
            port_end = parts[2]
            rules.append({
                "index": i,
                "ipAddress": parts[0],
                "portStart": port_start,
                "portEnd": port_end,
                "portRange": f"{port_start} - {port_end}" if port_start or port_end else "--",
                "protocol": self._protocol_label(parts[3]),
                "protocol_raw": parts[3],
                "comment": parts[4],
            })
        return rules

    def _render_port_forward_rules(self):
        """大屏横向；小屏勾选框独立一行，信息在下方完整显示"""
        self.fw_rule_checks = {}
        rows = []
        text_size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 13)
        item_padding = 5 if self.is_ultra_small_layout else (7 if self.is_small_layout else 10)
        item_spacing = 4 if self.is_ultra_small_layout else 8

        for rule in self.fw_rules:
            cb = create_checkbox(label="", value=False, data=str(rule["index"]))
            if getattr(cb, "label_style", None) is None:
                cb.label_style = ft.TextStyle(size=text_size, color=ft.Colors.ON_SURFACE)
            else:
                cb.label_style.size = text_size
            self.fw_rule_checks[rule["index"]] = cb

            ip_addr = str(rule.get("ipAddress") or "--")
            port_range = str(rule.get("portRange") or "--")
            protocol = str(rule.get("protocol") or "--")
            comment = str(rule.get("comment") or "").strip() or "--"

            if self.is_small_layout or self.is_ultra_small_layout:
                # 小屏：标签和内容分行显示，备注也换行
                def _kv(label: str, value: str) -> ft.Column:
                    return ft.Column(
                        [
                            ft.Text(f"{label}：", size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    )
                info = ft.Column(
                    [
                        _kv("IP 地址", ip_addr),
                        _kv("端口范围", port_range),
                        _kv("协议", protocol),
                        _kv("备注", comment),
                    ],
                    spacing=2 if self.is_ultra_small_layout else 3,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                )
                item_content = ft.Column(
                    [
                        ft.Row(
                            [cb, ft.Text(f"规则 {rule.get('index', 0) + 1}", size=text_size, color=ft.Colors.ON_SURFACE_VARIANT)],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        info,
                    ],
                    spacing=item_spacing,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                )
            else:
                def cell(title: str, value: str, expand: int = 1) -> ft.Container:
                    return ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(title, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1),
                                ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ],
                            spacing=2,
                        ),
                        expand=expand,
                    )
                info = ft.Row(
                    [
                        cell("IP 地址", ip_addr, 2),
                        cell("端口范围", port_range, 2),
                        cell("协议", protocol, 1),
                        cell("备注", comment, 1),
                    ],
                    spacing=item_spacing,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                item_content = ft.Row(
                    [
                        ft.Container(cb, width=28, alignment=ft.Alignment(-1, 0)),
                        info,
                    ],
                    spacing=item_spacing,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )

            rows.append(
                ft.Container(
                    content=item_content,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=8,
                    padding=item_padding,
                )
            )

        self.fw_rules_list.controls = rows
        self.fw_rules_list.spacing = 4 if self.is_ultra_small_layout else (6 if self.is_small_layout else 8)
        self.fw_rules_empty.visible = len(rows) == 0
        self.fw_rules_empty.size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 12)
        self.txt_fw_rules_title.size = 11 if self.is_ultra_small_layout else (13 if self.is_small_layout else 15)

    async def on_fw_enable_change(self, e=None):
        # 开关即当前状态：拨动后直接提交
        try:
            ok = await self.api_client.post_cmd("VIRTUAL_SERVER", {
                "PortForwardEnable": "1" if self.fw_enable.value else "0",
            })
            if ok:
                show_toast(self.app_page, f"端口转发已{'开启' if self.fw_enable.value else '关闭'}", True)
                await self.load_feature("port_forward")
            else:
                show_toast(self.app_page, "端口转发状态更新失败", False)
                self.fw_enable.value = not self.fw_enable.value
                try:
                    self.update()
                except Exception:
                    pass
        except Exception as ex:
            logger.error(f"切换端口转发失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "端口转发状态更新异常", False)
            self.fw_enable.value = not self.fw_enable.value
            try:
                self.update()
            except Exception:
                pass

    async def on_add_port_forward_rule(self, e):
        try:
            if not self.fw_enable.value:
                show_toast(self.app_page, "请先启用端口转发", False)
                return
            if len(self.fw_rules) >= 20:
                show_toast(self.app_page, "最多添加 20 条转发规则", False)
                return
            ip = (self.fw_ip.value or "").strip()
            if not ip:
                show_toast(self.app_page, "请填写 IP 地址", False)
                return
            if not is_valid_ipv4(ip):
                show_toast(self.app_page, "IP 地址格式不正确", False)
                return
            p_start = (self.fw_port_start.value or "").strip()
            p_end = (self.fw_port_end.value or "").strip()
            ok_range, err = is_valid_port_range(p_start, p_end, min_port=1, max_port=65535)
            if not ok_range:
                show_toast(self.app_page, err, False)
                return
            ok = await self.api_client.post_cmd("FW_FORWARD_ADD", {
                "ipAddress": ip,
                "portStart": str(int(p_start)),
                "portEnd": str(int(p_end)),
                "protocol": self.fw_protocol.value or "TCP&UDP",
                "comment": (self.fw_comment.value or "").strip(),
            })
            if ok:
                self.fw_ip.value = ""
                self.fw_port_start.value = ""
                self.fw_port_end.value = ""
                self.fw_comment.value = ""
                show_toast(self.app_page, "端口转发规则已添加", True)
                await self.load_feature("port_forward")
            else:
                show_toast(self.app_page, "端口转发规则添加失败", False)
        except Exception as ex:
            logger.error(f"添加端口转发失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "端口转发规则添加异常", False)

    async def on_delete_port_forward_rules(self, e):
        try:
            selected = [str(idx) for idx, cb in self.fw_rule_checks.items() if cb.value]
            if not selected:
                show_toast(self.app_page, "请先选择要删除的规则", False)
                return
            ok = await self.api_client.post_cmd("FW_FORWARD_DEL", {
                "delete_id": ";".join(selected) + ";",
            })
            if ok:
                show_toast(self.app_page, "转发规则已删除", True)
                await self.load_feature("port_forward")
            else:
                show_toast(self.app_page, "转发规则删除失败", False)
        except Exception as ex:
            logger.error(f"删除端口转发失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "转发规则删除异常", False)

    def _protocol_label(self, value: str) -> str:
        """设备可能返回数字码或字符串，统一显示为下拉选项文案"""
        raw = str(value or "").strip()
        v = raw.upper().replace("+", "&")
        mapping = {
            # 端口转发/映射（仅保留官方抓包确认值）
            # 提交：TCP&UDP / TCP / UDP
            # 回显：TCP => 1，UDP => 2，TCP+UDP => 3
            "1": "TCP",
            "2": "UDP",
            "3": "TCP+UDP",
            "TCP&UDP": "TCP+UDP",
            "TCP+UDP": "TCP+UDP",
            "TCP": "TCP",
            "UDP": "UDP",
        }
        return mapping.get(v, mapping.get(raw, (raw or "--")))

    def _parse_port_map_rules(self, data: Dict) -> List[Dict]:
        rules = []
        for i in range(20):
            raw = str(data.get(f"PortMapRules_{i}", "") or "").strip()
            if not raw:
                continue
            parts = raw.split(",")
            # 官方格式: destIp,sourcePort,destPort,protocol,comment
            while len(parts) < 5:
                parts.append("")
            rules.append({
                "index": i,
                "sourcePort": parts[1],
                "destIpAddress": parts[0],
                "destPort": parts[2],
                "protocol": self._protocol_label(parts[3]),
                "protocol_raw": parts[3],
                "comment": parts[4],
            })
        return rules

    def _render_port_map_rules(self):
        """大屏横向；小屏勾选框独立一行，信息在下方完整显示"""
        self.pm_rule_checks = {}
        rows = []
        text_size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 13)
        item_padding = 5 if self.is_ultra_small_layout else (7 if self.is_small_layout else 10)
        item_spacing = 4 if self.is_ultra_small_layout else 8

        for rule in self.pm_rules:
            cb = create_checkbox(label="", value=False, data=str(rule["index"]))
            if getattr(cb, "label_style", None) is None:
                cb.label_style = ft.TextStyle(size=text_size, color=ft.Colors.ON_SURFACE)
            else:
                cb.label_style.size = text_size
            self.pm_rule_checks[rule["index"]] = cb

            src_port = str(rule.get("sourcePort") or "--")
            dest_ip = str(rule.get("destIpAddress") or "--")
            dest_port = str(rule.get("destPort") or "--")
            protocol = str(rule.get("protocol") or "--")
            comment = str(rule.get("comment") or "").strip() or "--"

            if self.is_small_layout or self.is_ultra_small_layout:
                # 小屏：勾选框单独一行，信息在下面，不再和勾选框并排挤压
                # 小屏：标签和数字分行显示，避免窄屏裁切
                def _kv(label: str, value: str) -> ft.Column:
                    return ft.Column(
                        [
                            ft.Text(f"{label}：", size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    )
                info = ft.Column(
                    [
                        _kv("源端口", src_port),
                        _kv("目的IP", dest_ip),
                        _kv("目的端口", dest_port),
                        _kv("协议", protocol),
                        _kv("备注", comment),
                    ],
                    spacing=2 if self.is_ultra_small_layout else 3,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                )
                item_content = ft.Column(
                    [
                        ft.Row(
                            [cb, ft.Text(f"规则 {rule.get('index', 0) + 1}", size=text_size, color=ft.Colors.ON_SURFACE_VARIANT)],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        info,
                    ],
                    spacing=item_spacing,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                )
            else:
                # 大屏：横向分列
                def cell(title: str, value: str, expand: int = 1) -> ft.Container:
                    return ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(title, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1),
                                ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ],
                            spacing=2,
                        ),
                        expand=expand,
                    )
                info = ft.Row(
                    [
                        cell("源端口", src_port, 1),
                        cell("目的 IP 地址", dest_ip, 2),
                        cell("目的端口", dest_port, 1),
                        cell("协议", protocol, 1),
                        cell("备注", comment, 1),
                    ],
                    spacing=item_spacing,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                item_content = ft.Row(
                    [
                        ft.Container(cb, width=28, alignment=ft.Alignment(-1, 0)),
                        info,
                    ],
                    spacing=item_spacing,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )

            rows.append(
                ft.Container(
                    content=item_content,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=8,
                    padding=item_padding,
                )
            )

        self.pm_rules_list.controls = rows
        self.pm_rules_list.spacing = 4 if self.is_ultra_small_layout else (6 if self.is_small_layout else 8)
        self.pm_rules_empty.visible = len(rows) == 0
        self.pm_rules_empty.size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 12)
        self.txt_pm_rules_title.size = 11 if self.is_ultra_small_layout else (13 if self.is_small_layout else 15)


    async def on_pm_enable_change(self, e=None):
        # 官方开关独立提交：goformId=ADD_PORT_MAP + portMapEnabled
        try:
            ok = await self.api_client.post_cmd("ADD_PORT_MAP", {
                "portMapEnabled": "1" if self.pm_enable.value else "0",
            })
            if ok:
                show_toast(self.app_page, "端口映射开关已更新", True)
                await self.load_feature("port_map")
            else:
                show_toast(self.app_page, "端口映射开关更新失败", False)
                # 回滚开关显示
                self.pm_enable.value = not self.pm_enable.value
                try:
                    self.update()
                except Exception:
                    pass
        except Exception as ex:
            logger.error(f"切换端口映射开关失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "端口映射开关更新异常", False)
            self.pm_enable.value = not self.pm_enable.value
            try:
                self.update()
            except Exception:
                pass

    async def on_add_port_map_rule(self, e):
        try:
            if not self.pm_enable.value:
                show_toast(self.app_page, "请先启用端口映射", False)
                return
            if len(self.pm_rules) >= 20:
                show_toast(self.app_page, "最多添加 20 条映射规则", False)
                return
            # 官方抓包添加时固定带 portMapEnabled=1
            ip = (self.pm_ip.value or "").strip()
            if not ip:
                show_toast(self.app_page, "请填写目的 IP 地址", False)
                return
            if not is_valid_ipv4(ip):
                show_toast(self.app_page, "IP 地址格式不正确", False)
                return
            from_port = (self.pm_from.value or "").strip()
            to_port = (self.pm_to.value or "").strip()
            fp = parse_port(from_port)
            tp = parse_port(to_port)
            if fp == -1 or tp == -1 or fp is None or tp is None:
                show_toast(self.app_page, "端口格式不正确", False)
                return
            if fp < 1 or fp > 65000 or tp < 1 or tp > 65000:
                show_toast(self.app_page, "端口需在 1~65000 之间", False)
                return
            ok = await self.api_client.post_cmd("ADD_PORT_MAP", {
                "portMapEnabled": "1",
                "fromPort": str(fp),
                "ip_address": ip,
                "toPort": str(tp),
                "protocol": self.pm_protocol.value or "TCP&UDP",
                "comment": (self.pm_comment.value or "").strip(),
            })
            if ok:
                self.pm_from.value = ""
                self.pm_ip.value = ""
                self.pm_to.value = ""
                self.pm_comment.value = ""
                show_toast(self.app_page, "端口映射规则已添加", True)
                await self.load_feature("port_map")
            else:
                show_toast(self.app_page, "端口映射规则添加失败", False)
        except Exception as ex:
            logger.error(f"添加端口映射失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "端口映射规则添加异常", False)

    async def on_delete_port_map_rules(self, e):
        try:
            selected = [str(idx) for idx, cb in self.pm_rule_checks.items() if cb.value]
            if not selected:
                show_toast(self.app_page, "请先选择要删除的规则", False)
                return
            ok = await self.api_client.post_cmd("DEL_PORT_MAP", {
                "delete_id": ";".join(selected) + ";",
            })
            if ok:
                show_toast(self.app_page, "映射规则已删除", True)
                await self.load_feature("port_map")
            else:
                show_toast(self.app_page, "映射规则删除失败", False)
        except Exception as ex:
            logger.error(f"删除端口映射失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "映射规则删除异常", False)

    async def on_upnp_enable_change(self, e=None):
        # 开关即当前状态：拨动后直接提交
        try:
            ok = await self.api_client.post_cmd("UPNP_SETTING", {
                "upnp_setting_option": "1" if self.upnp_enable.value else "0",
            })
            if ok:
                show_toast(self.app_page, f"UPnP 已{'开启' if self.upnp_enable.value else '关闭'}", True)
                await self.load_feature("upnp")
            else:
                show_toast(self.app_page, "UPnP 状态更新失败", False)
                self.upnp_enable.value = not self.upnp_enable.value
                try:
                    self.update()
                except Exception:
                    pass
        except Exception as ex:
            logger.error(f"切换 UPnP 失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "UPnP 状态更新异常", False)
            self.upnp_enable.value = not self.upnp_enable.value
            try:
                self.update()
            except Exception:
                pass

    def on_dmz_enable_change(self, e=None):
        enabled = bool(self.dmz_enable.value)
        self.dmz_ip.visible = enabled
        self.btn_dmz_save.visible = enabled
        try:
            self.update()
        except Exception:
            pass
        # 关闭时直接提交；开启时显示输入框，等用户填 IP 后点应用
        if not enabled:
            spawn_background_task(self, self._save_dmz_state())

    async def _save_dmz_state(self):
        try:
            params = {"DMZEnabled": "1" if self.dmz_enable.value else "0"}
            if self.dmz_enable.value:
                ip = (self.dmz_ip.value or "").strip()
                if not ip or not is_valid_ipv4(ip):
                    show_toast(self.app_page, "DMZ 主机 IP 格式不正确", False)
                    return
                params["DMZIPAddress"] = ip
            ok = await self.api_client.post_cmd("DMZ_SETTING", params)
            if ok:
                show_toast(self.app_page, "DMZ 设置应用成功", True)
                await self.load_feature("dmz")
            else:
                show_toast(self.app_page, "DMZ 设置应用失败", False)
        except Exception as ex:
            logger.error(f"保存 DMZ 失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "DMZ 设置应用异常", False)

    async def on_save_dmz(self, e):
        if self.dmz_enable.value:
            ip = (self.dmz_ip.value or "").strip()
            if not ip:
                show_toast(self.app_page, "请先填写 DMZ 主机 IP", False)
                return
            if not is_valid_ipv4(ip):
                show_toast(self.app_page, "DMZ 主机 IP 格式不正确", False)
                return
            self.dmz_ip.value = ip
        await self._save_dmz_state()

    async def on_sys_security_change(self, e=None):
        # 开关即当前状态，拨动后直接提交
        if getattr(self, "_sys_security_loading", False):
            return
        try:
            remote = "1" if self.remote_enable.value else "0"
            ping = "1" if self.ping_enable.value else "0"
            ok = await self.api_client.post_cmd("FW_SYS", {
                "remoteManagementEnabled": remote,
                "pingFrmWANFilterEnabled": ping,
                "RemoteManagement": remote,
                "WANPingFilter": ping,
            })
            if ok:
                show_toast(self.app_page, "系统安全已更新", True)
                await self.load_feature("system_security")
            else:
                show_toast(self.app_page, "系统安全更新失败", False)
                # 失败回滚：重新读取设备状态
                await self.load_feature("system_security")
        except Exception as ex:
            logger.error(f"切换系统安全失败: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "系统安全更新异常", False)
            await self.load_feature("system_security")

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        layout_changed = self.is_small_layout != is_small or self.is_ultra_small_layout != is_ultra_small
        self.is_small_layout = is_small
        self.is_ultra_small_layout = is_ultra_small
        self.txt_title.size = 12 if is_ultra_small else (15 if is_small else 18)
        self.txt_hint.size = 9 if is_ultra_small else (11 if is_small else 12)
        self.txt_pm_rules_title.size = 11 if is_ultra_small else (13 if is_small else 15)
        self.pm_rules_empty.size = 10 if is_ultra_small else (11 if is_small else 12)
        self.txt_pm_enable_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        self.txt_fw_enable_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        if hasattr(self, "txt_pf_enable_label"):
            self.txt_pf_enable_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        self.txt_fw_port_range.size = 10 if is_ultra_small else (12 if is_small else 13)
        self.txt_fw_rules_title.size = 11 if is_ultra_small else (13 if is_small else 15)
        if hasattr(self, "txt_pf_rules_title"):
            self.txt_pf_rules_title.size = 11 if is_ultra_small else (13 if is_small else 15)
        if hasattr(self, "txt_pf_settings_title"):
            self.txt_pf_settings_title.size = 11 if is_ultra_small else (13 if is_small else 15)
        if hasattr(self, "txt_pf_src_port_range"):
            self.txt_pf_src_port_range.size = 10 if is_ultra_small else (12 if is_small else 13)
            self.txt_pf_dst_port_range.size = 10 if is_ultra_small else (12 if is_small else 13)
        self.fw_rules_empty.size = 10 if is_ultra_small else (11 if is_small else 12)
        self.txt_upnp_enable_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        self.txt_remote_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        self.txt_ping_label.size = 11 if is_ultra_small else (13 if is_small else 14)
        self.feature_menu.spacing = 6 if is_ultra_small else (10 if is_small else 14)
        self.feature_menu.run_spacing = 6 if is_ultra_small else (10 if is_small else 14)
        for item in self.feature_menu.controls:
            item.col = {"xs": 12, "sm": 12} if is_small else {"xs": 12, "sm": 6}

        # 填写项只缩小字号一档；框内文字允许自动换行，宽度撑满
        field_text_size = 10 if is_ultra_small else (12 if is_small else 14)
        field_label_size = 10 if is_ultra_small else (12 if is_small else 14)
        for ctrl in [
            self.pm_from, self.pm_ip, self.pm_to, self.pm_protocol, self.pm_comment,
            self.fw_ip, self.fw_port_start, self.fw_port_end, self.fw_protocol, self.fw_comment,
            self.pf_policy, self.pf_ip_type, self.pf_mac, self.pf_sip, self.pf_dip,
            self.pf_protocol, self.pf_action, self.pf_comment,
            self.pf_sport_start, self.pf_sport_end, self.pf_dport_start, self.pf_dport_end,
            self.dmz_ip,
        ]:
            if hasattr(ctrl, "expand"):
                ctrl.expand = True
            if hasattr(ctrl, "text_size"):
                ctrl.text_size = field_text_size
            if hasattr(ctrl, "label_style") and ctrl.label_style is not None:
                ctrl.label_style.size = field_label_size
            if hasattr(ctrl, "hint_style") and ctrl.hint_style is not None:
                ctrl.hint_style.size = field_label_size
            # 文本输入框启用自动换行，避免窄屏裁切
            if hasattr(ctrl, "multiline") and not isinstance(ctrl, ft.Dropdown):
                ctrl.multiline = True
                if hasattr(ctrl, "min_lines"):
                    ctrl.min_lines = 1
                if hasattr(ctrl, "max_lines"):
                    ctrl.max_lines = 3
        button_height = 36 if is_ultra_small else (42 if is_small else 48)
        button_text_size = 11 if is_ultra_small else (13 if is_small else 14)
        for btn in self.feature_buttons + [
            self.btn_pf_save, self.btn_pf_add, self.btn_pf_delete,
            self.btn_fw_add, self.btn_fw_delete,
            self.btn_pm_add, self.btn_pm_delete,
            self.btn_dmz_save
        ]:
            btn.height = button_height
            if btn.style and getattr(btn.style, "text_style", None):
                btn.style.text_style.size = button_text_size
        self.padding = 8 if is_ultra_small else (12 if is_small else 15)
        self.border_radius = 8 if is_ultra_small else (10 if is_small else 12)
        self.content.spacing = 8 if is_ultra_small else (10 if is_small else 12)
        # 布局变化或字号变化时重绘规则卡片
        if self.pm_rules:
            self._render_port_map_rules()
        if getattr(self, 'fw_rules', None):
            self._render_port_forward_rules()
        if getattr(self, 'pf_rules', None):
            self._render_port_filter_rules()
        try:
            self.update()
        except Exception:
            pass



class RouterCard(ft.Container):
    """路由设置：对应官方 #router_setting / adm/lan.js"""

    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable):
        super().__init__(padding=15, bgcolor=ft.Colors.SURFACE, border_radius=12, visible=False)
        self.app_page = page
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.is_small_layout = False
        self.is_ultra_small_layout = False
        self.lan_editable = False
        self.is_data_connected = True
        self.is_switching_data = False
        self._loading = False
        self.bind_mode = False  # True = MAC-IP bind subpage
        self.bind_rules = []
        self.bind_rule_checks = {}
        self.background_tasks: Set[asyncio.Task] = set()  # 保存后台 Task 强引用
        self.build_ui()

    def _make_switch(self, on_change=None) -> ft.Switch:
        return ft.Switch(
            value=False,
            active_track_color=ft.Colors.PRIMARY,
            inactive_track_color=ft.Colors.SURFACE,
            thumb_color=ft.Colors.ON_SURFACE,
            on_change=on_change,
        )

    def build_ui(self):
        self.txt_title = ft.Text("路由设置", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE)
        self.txt_hint = ft.Text("该设置仅断网可修改，应用后设备重启", size=12, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False)

        self.txt_data_label = ft.Text("数据连接", color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.data_switch = self._make_switch(on_change=self.on_data_switch_change)
        self.data_switch.value = True
        self.data_row = ft.Row(
            [self.data_switch, self.txt_data_label],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )
        self.txt_hint_top = ft.Text("该设置仅断网可修改，应用后设备重启", size=12, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False)

        self.ip_address = create_text_field("IP 地址", "", multiline=True, min_lines=1, max_lines=2, expand=True)
        self.subnet_mask = create_text_field("子网掩码", "", multiline=True, min_lines=1, max_lines=2, expand=True)
        self.dhcp_enable = self._make_switch(on_change=self.on_dhcp_toggle)
        self.txt_dhcp_label = ft.Text("DHCP服务", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.dhcp_start = create_text_field("DHCP IP池起", "", multiline=True, min_lines=1, max_lines=2, expand=True)
        self.dhcp_end = create_text_field("DHCP IP池止", "", multiline=True, min_lines=1, max_lines=2, expand=True)
        self.dhcp_lease = create_text_field("DHCP租期(小时)", "24", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.btn_lan_apply = create_button("应用", on_click=self.on_save_lan)

        self.nat_enable = self._make_switch(on_change=self.on_nat_toggle)
        self.txt_nat_label = ft.Text("NAT", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.txt_nat_tip = ft.Text("该功能仅针对Router模式生效，关闭NAT可能会导致下游设备无法上网", size=12, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False)

        self.bridge_enable = self._make_switch(on_change=self.on_bridge_toggle)
        self.txt_bridge_label = ft.Text("桥模式", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.txt_bridge_tip = ft.Text("当桥模式开启后，没有NAT功能", size=12, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False)
        self.bridge_bind = create_dropdown(
            "绑定方式",
            [
                ft.dropdown.Option("Ethernet", "以太网"),
                ft.dropdown.Option("USB", "USB"),
                ft.dropdown.Option("WIFI", "WLAN"),
            ],
            "Ethernet",
            expand=True,
        )
        self.bridge_bind.on_change = self.on_bridge_bind_change
        self.bridge_mac = create_text_field("MAC 地址", "", multiline=True, min_lines=1, max_lines=2, expand=True)
        self.btn_bridge_apply = create_button("应用", on_click=self.on_save_bridge)

        self.txt_mtu_title = ft.Text("MTU/MSS", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.mtu_value = create_text_field("MTU(比MSS至少大40)", "1500", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.mss_value = create_text_field("MSS(1260~1460)", "1460", input_filter=ft.NumbersOnlyInputFilter(), multiline=True, min_lines=1, max_lines=2, expand=True)
        self.btn_mtu_apply = create_button("应用", on_click=self.on_save_mtu)

        # MAC-IP 绑定入口与子页
        # MAC-IP 绑定：主页开关，开启后显示规则区
        self.bind_enable = self._make_switch(on_change=self.on_bind_enable_toggle)
        self.txt_bind_enable_label = ft.Text("MAC-IP绑定", color=ft.Colors.INVERSE_PRIMARY, no_wrap=False)
        self.bind_mac = create_text_field("MAC 地址", "", multiline=True, min_lines=1, max_lines=2, expand=True, hint_text="例如：00:1E:90:FF:FF:FF")
        self.bind_ip = create_text_field("IP 地址", "", multiline=True, min_lines=1, max_lines=2, expand=True, hint_text="例如：192.168.0.101")
        self.btn_bind_add = create_button("应用", on_click=self.on_add_bind_rule)
        self.txt_bind_list_title = ft.Text("当前绑定列表", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE, no_wrap=False)
        self.bind_rules_empty = ft.Text("暂无绑定规则", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.bind_rules_list = ft.Column(spacing=8)
        self.txt_bind_tip = ft.Text("需要重启设备才能使绑定或者解绑生效", size=12, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=False)
        self.btn_bind_reboot = create_button("重启", on_click=self.on_bind_reboot)
        self.btn_bind_delete = create_button("删除", on_click=self.on_delete_bind_rules)
        self.bind_form_box = ft.Column(
            [
                self.bind_mac,
                self.bind_ip,
                self.btn_bind_add,
                self.txt_bind_list_title,
                self.bind_rules_list,
                self.bind_rules_empty,
                self.txt_bind_tip,
                ft.Row([self.btn_bind_reboot, self.btn_bind_delete], wrap=True, spacing=10),
            ],
            spacing=10,
            visible=False,
        )


        self.dhcp_pool_box = ft.Column([self.dhcp_start, self.dhcp_end, self.dhcp_lease], spacing=10, visible=False)
        self.lan_fields_box = ft.Column(
            [
                self.ip_address,
                self.subnet_mask,
                ft.Row([self.dhcp_enable, self.txt_dhcp_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                self.dhcp_pool_box,
                self.btn_lan_apply,
                self.txt_hint,
            ],
            spacing=10,
        )
        self.bridge_extra_box = ft.Column([self.bridge_bind, self.bridge_mac], spacing=10, visible=False)

        self.content = ft.Column(
            [
                self.txt_title,
                ft.Divider(height=5, color=ft.Colors.OUTLINE_VARIANT),
                self.data_row,
                self.txt_hint_top,
                self.lan_fields_box,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Row([self.nat_enable, self.txt_nat_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                self.txt_nat_tip,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Row([self.bridge_enable, self.txt_bridge_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                self.txt_bridge_tip,
                self.bridge_extra_box,
                self.btn_bridge_apply,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.txt_mtu_title,
                self.mtu_value,
                self.mss_value,
                self.btn_mtu_apply,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Row([self.bind_enable, self.txt_bind_enable_label], vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                self.bind_form_box,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        self._sync_visibility()

    def _set_lan_enabled(self, enabled: bool):
        self.lan_editable = enabled
        # DHCP switch stays clickable; if online, click will disconnect data first
        self.dhcp_enable.disabled = bool(self.is_switching_data)
        for ctrl in [self.ip_address, self.subnet_mask, self.dhcp_start, self.dhcp_end, self.dhcp_lease, self.btn_lan_apply]:
            ctrl.disabled = not enabled
        self.txt_hint.value = "该设置仅断网可修改，应用后设备重启"
        self.txt_hint_top.value = "该设置仅断网可修改，应用后设备重启"
        self._sync_visibility()

    def _sync_visibility(self):
        self.dhcp_pool_box.visible = bool(self.dhcp_enable.value)
        bridge_on = bool(self.bridge_enable.value)
        self.bridge_extra_box.visible = bridge_on
        self.btn_bridge_apply.visible = bridge_on
        self.bridge_mac.visible = bool(bridge_on and str(self.bridge_bind.value or "") == "WIFI")

    def on_dhcp_toggle(self, e=None):
        # Click DHCP: if data online, disconnect first then apply toggle
        target = bool(self.dhcp_enable.value)
        if self.is_switching_data:
            self.dhcp_enable.value = not target
            self._sync_visibility()
            try:
                self.update()
            except Exception:
                pass
            return
        if self.is_data_connected:
            self.dhcp_enable.value = not target
            self._sync_visibility()
            try:
                self.update()
            except Exception:
                pass
            spawn_background_task(self, self._dhcp_toggle_after_disconnect(target))
            return
        self._sync_visibility()
        try:
            self.update()
        except Exception:
            pass

    async def _dhcp_toggle_after_disconnect(self, target: bool):
        ok = await self._switch_data_connection(False)
        if not ok:
            show_toast(self.app_page, "请先断开数据连接后再修改 DHCP", False)
            return
        self.dhcp_enable.value = target
        self._set_lan_enabled(True)
        self._sync_visibility()
        try:
            self.update()
        except Exception:
            pass
        show_toast(self.app_page, "数据已断开，可修改 DHCP 后点应用", True)

    def on_bridge_toggle(self, e=None):
        # 开关本身立即切换桥模式；开启后才显示绑定与应用
        self._sync_visibility()
        try:
            self.update()
        except Exception:
            pass
        if self.is_switching_data:
            return
        spawn_background_task(self, self._apply_bridge_enable())

    def on_bridge_bind_change(self, e=None):
        self._sync_visibility()
        try:
            self.update()
        except Exception:
            pass


    def _sync_data_ui(self):
        self.data_switch.value = self.is_data_connected
        self.data_switch.disabled = self.is_switching_data
        self._set_lan_enabled((not self.is_data_connected) and (not self.is_switching_data))

    def update_realtime(self, status: 'RealtimeStatus'):
        if self.is_switching_data:
            return
        self.is_data_connected = bool(getattr(status, "is_data_connected", False))
        self._sync_data_ui()
        try:
            self.update()
        except Exception:
            pass

    async def _switch_data_connection(self, target_on: bool) -> bool:
        if self.is_data_connected == target_on:
            return True
        self.is_switching_data = True
        self.data_switch.disabled = True
        action = "开启" if target_on else "关闭"
        show_toast(self.app_page, f"正在{action}数据连接...", True)
        try:
            ok = await self.api_client.set_data_connection(target_on)
            if ok:
                self.is_data_connected = target_on
                self.set_global_status(f"数据连接已{action}", ft.Colors.PRIMARY)
                show_toast(self.app_page, f"数据连接已{action}", True)
            else:
                self.set_global_status(f"数据连接{action}失败", ft.Colors.ERROR)
                show_toast(self.app_page, f"数据连接{action}失败", False)
            return ok
        except Exception as ex:
            logger.error(f"Router data switch {action} error: {ex}", exc_info=DEBUG_MODE)
            self.set_global_status(f"数据连接{action}异常", ft.Colors.ERROR)
            show_toast(self.app_page, f"数据连接{action}异常", False)
            return False
        finally:
            self._sync_data_ui()
            self.is_switching_data = False
            self._sync_data_ui()
            try:
                self.update()
            except Exception:
                pass

    async def on_data_switch_change(self, e=None):
        if self.is_switching_data:
            self.data_switch.value = self.is_data_connected
            try:
                self.data_switch.update()
            except Exception:
                pass
            return
        target_on = bool(self.data_switch.value)
        self.data_switch.value = self.is_data_connected
        try:
            self.data_switch.update()
        except Exception:
            pass
        ok = await self._switch_data_connection(target_on)
        if ok:
            await self.load(silent=True)
        else:
            self._sync_data_ui()
            try:
                self.update()
            except Exception:
                pass

    async def load(self, silent: bool = False):
        if self._loading:
            return
        self._loading = True
        if not silent:
            self.set_global_status("正在读取路由设置...", ft.Colors.ON_SURFACE)
        try:
            lan = await self.api_client.get_cmd(
                "lan_ipaddr,lan_netmask,mac_address,dhcpEnabled,dhcpStart,dhcpEnd,dhcpLease_hour,mtu,tcp_mss",
                multi_data=True,
            )
            nat = await self.api_client.get_cmd(
                "nat_mode,ip_passthrough_enabled,bridge_wan_port_form_enable",
                multi_data=True,
            )
            conn = {}
            try:
                conn = await self.api_client.get_cmd("ppp_status")
            except Exception:
                conn = {}
            status = str(conn.get("ppp_status", "")).lower()
            self.is_data_connected = status not in ("ppp_disconnected", "disconnected") and "disconnect" not in status
            # 官方：仅断网时可改 LAN/DHCP
            lan_editable = (not self.is_data_connected) and (not self.is_switching_data)
            self.data_switch.value = self.is_data_connected

            self.ip_address.value = str(lan.get("lan_ipaddr", "") or "")
            self.subnet_mask.value = str(lan.get("lan_netmask", "") or "")
            self.dhcp_enable.value = str(lan.get("dhcpEnabled", "0")) == "1"
            self.dhcp_start.value = str(lan.get("dhcpStart", "") or "")
            self.dhcp_end.value = str(lan.get("dhcpEnd", "") or "")
            lease = str(lan.get("dhcpLease_hour", "24") or "24")
            try:
                lease = str(int(float(lease)))
            except Exception:
                lease = "24"
            self.dhcp_lease.value = lease
            self.mtu_value.value = str(lan.get("mtu", "1500") or "1500")
            self.mss_value.value = str(lan.get("tcp_mss", "1460") or "1460")

            nat_mode = str(nat.get("nat_mode", "1"))
            self.nat_enable.value = nat_mode != "0"

            bridge_on = str(nat.get("ip_passthrough_enabled", "0")) == "1"
            self.bridge_enable.value = bridge_on
            bind_raw = str(nat.get("bridge_wan_port_form_enable", "") or "")
            parts = [p for p in bind_raw.split(",") if p != ""]
            bind_mode = "Ethernet"
            bind_mac = ""
            if len(parts) >= 2:
                bind_mode = parts[1]
            if len(parts) >= 3:
                bind_mac = parts[2]
            if bind_mode not in ("Ethernet", "USB", "WIFI"):
                bind_mode = "Ethernet"
            self.bridge_bind.value = bind_mode
            self.bridge_mac.value = bind_mac

            self._set_lan_enabled(lan_editable)
            # 同步 MAC-IP 开关与表单可见性
            try:
                st = await self.api_client.get_cmd("mac_ip_status", multi_data=True)
                self.bind_enable.value = str(st.get("mac_ip_status", "0")) == "1"
                self._sync_bind_form_visibility()
                if self.bind_enable.value:
                    await self.load_bind(silent=True)
            except Exception as bind_ex:
                logger.debug(f"sync bind status failed: {bind_ex}")

            if not silent:
                self.set_global_status("路由设置已同步", ft.Colors.PRIMARY)
            try:
                self.update()
            except Exception:
                pass
        except Exception as ex:
            logger.error(f"读取路由设置失败: {ex}", exc_info=DEBUG_MODE)
            if not silent:
                self.set_global_status("读取路由设置失败", ft.Colors.ERROR)
                show_toast(self.app_page, "读取路由设置失败", False)
        finally:
            self._loading = False

    async def sync_current(self):
        if self.visible:
            await self.load(silent=True)
            if self.bind_enable.value:
                await self.load_bind(silent=True)


    async def on_save_lan(self, e=None):
        if not self.lan_editable:
            show_toast(self.app_page, "请先断开数据网络后再修改", False)
            return
        ip = (self.ip_address.value or "").strip()
        mask = (self.subnet_mask.value or "").strip()
        dhcp_on = "1" if self.dhcp_enable.value else "0"
        start = (self.dhcp_start.value or "").strip()
        end = (self.dhcp_end.value or "").strip()
        lease = (self.dhcp_lease.value or "").strip()
        if not ip or not mask:
            show_toast(self.app_page, "请填写 IP 地址和子网掩码", False)
            return
        if dhcp_on == "1" and (not start or not end or not lease):
            show_toast(self.app_page, "请完整填写 DHCP IP池和租期", False)
            return
        self.set_global_status("正在保存路由设置...", ft.Colors.ON_SURFACE)
        try:
            params = {
                "lanIp": ip,
                "lanNetmask": mask,
                "lanDhcpType": "SERVER" if dhcp_on == "1" else "DISABLE",
                "dhcp_reboot_flag": "1",
                "mac_ip_reset": "0",
            }
            if dhcp_on == "1":
                params["dhcpStart"] = start
                params["dhcpEnd"] = end
                params["dhcpLease"] = lease
            ok = await self.api_client.post_cmd("DHCP_SETTING", params)
            if ok:
                show_toast(self.app_page, "路由设置已应用", True)
                self.set_global_status("路由设置已应用", ft.Colors.PRIMARY)
                await self.load(silent=True)
            else:
                show_toast(self.app_page, "路由设置应用失败", False)
                self.set_global_status("路由设置应用失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"路由设置应用异常: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "路由设置应用异常", False)

    async def on_nat_toggle(self, e=None):
        if getattr(self, "_nat_busy", False):
            return
        self._nat_busy = True
        # 乐观 UI：保持用户拨动后的状态，请求期间禁用开关；失败再回滚
        target_on = bool(self.nat_enable.value)
        old_val = not target_on
        self.nat_enable.disabled = True
        try:
            self.nat_enable.update()
        except Exception:
            pass
        self.set_global_status("正在更新 NAT...", ft.Colors.ON_SURFACE)
        try:
            params = {"nat_mode": "0" if not target_on else ""}
            ok = await self.api_client.post_cmd("NAT_SETTING", params)
            if ok:
                self.nat_enable.value = target_on
                show_toast(self.app_page, "NAT 已更新", True)
                self.set_global_status("NAT 已更新", ft.Colors.PRIMARY)
            else:
                self.nat_enable.value = old_val
                show_toast(self.app_page, "NAT 更新失败", False)
                self.set_global_status("NAT 更新失败", ft.Colors.ERROR)
        except Exception as ex:
            self.nat_enable.value = old_val
            logger.error(f"NAT toggle error: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "NAT 更新异常", False)
            self.set_global_status("NAT 更新异常", ft.Colors.ERROR)
        finally:
            self.nat_enable.disabled = False
            self._nat_busy = False
            try:
                self.nat_enable.update()
            except Exception:
                pass

    async def _apply_bridge_enable(self):
        if getattr(self, "_bridge_busy", False):
            return
        self._bridge_busy = True
        # 乐观 UI：保持用户拨动后的状态，请求期间禁用开关；失败再回滚
        target_on = bool(self.bridge_enable.value)
        old_val = not target_on
        action = "开启" if target_on else "关闭"
        self.bridge_enable.disabled = True
        self._sync_visibility()
        try:
            self.update()
        except Exception:
            pass
        self.set_global_status(f"正在{action}桥模式...", ft.Colors.ON_SURFACE)
        try:
            params = {"ip_passthrough_enabled": "1" if target_on else "0"}
            if target_on:
                bind = str(self.bridge_bind.value or "Ethernet")
                form_enable = f"1,{bind}"
                if bind == "WIFI":
                    mac = (self.bridge_mac.value or "").strip()
                    if not mac:
                        show_toast(self.app_page, "WLAN 绑定请填写 MAC 地址", False)
                        self.bridge_enable.value = old_val
                        return
                    form_enable = f"1,{bind},{mac}"
                params["bridge_wan_port_form_enable"] = form_enable
            ok = await self.api_client.post_cmd("BRIDGE_SWITCH_SETTING", params)
            if ok:
                self.bridge_enable.value = target_on
                show_toast(self.app_page, f"桥模式已{action}", True)
                self.set_global_status(f"桥模式已{action}", ft.Colors.PRIMARY)
                await self.load(silent=True)
            else:
                self.bridge_enable.value = old_val
                show_toast(self.app_page, f"桥模式{action}失败", False)
                self.set_global_status(f"桥模式{action}失败", ft.Colors.ERROR)
        except Exception as ex:
            self.bridge_enable.value = old_val
            logger.error(f"bridge toggle error: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, f"桥模式{action}异常", False)
            self.set_global_status(f"桥模式{action}异常", ft.Colors.ERROR)
        finally:
            self.bridge_enable.disabled = False
            self._bridge_busy = False
            self._sync_visibility()
            try:
                self.update()
            except Exception:
                pass

    async def on_save_bridge(self, e=None):
        # 应用只管理绑定方式（桥模式需已开启）
        if not self.bridge_enable.value:
            show_toast(self.app_page, "请先开启桥模式", False)
            return
        if getattr(self, "_bridge_busy", False):
            return
        self._bridge_busy = True
        self.set_global_status("正在保存绑定方式...", ft.Colors.ON_SURFACE)
        try:
            bind = str(self.bridge_bind.value or "Ethernet")
            form_enable = f"1,{bind}"
            if bind == "WIFI":
                mac = (self.bridge_mac.value or "").strip()
                if not mac:
                    show_toast(self.app_page, "WLAN 绑定请填写 MAC 地址", False)
                    return
                form_enable = f"1,{bind},{mac}"
            params = {
                "ip_passthrough_enabled": "1",
                "bridge_wan_port_form_enable": form_enable,
            }
            ok = await self.api_client.post_cmd("BRIDGE_SWITCH_SETTING", params)
            if ok:
                show_toast(self.app_page, "绑定方式已应用", True)
                self.set_global_status("绑定方式已应用", ft.Colors.PRIMARY)
                await self.load(silent=True)
            else:
                show_toast(self.app_page, "绑定方式应用失败", False)
                self.set_global_status("绑定方式应用失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"bridge bind save error: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "绑定方式应用异常", False)
            self.set_global_status("绑定方式应用异常", ft.Colors.ERROR)
        finally:
            self._bridge_busy = False

    async def on_save_mtu(self, e=None):
        mtu = (self.mtu_value.value or "").strip()
        mss = (self.mss_value.value or "").strip()
        if not mtu:
            show_toast(self.app_page, "请填写 MTU", False)
            return
        if not mss:
            show_toast(self.app_page, "请填写 MSS", False)
            return
        try:
            mtu_n = int(mtu)
            mss_n = int(mss)
        except Exception:
            show_toast(self.app_page, "MTU/MSS 请输入数字", False)
            return
        # 官方：MTU 1300~1500，MSS 1260~1460，MTU 至少比 MSS 大 40
        if mtu_n < 1300 or mtu_n > 1500:
            show_toast(self.app_page, "请输入一个介于1300和1500之间的值", False)
            return
        if mss_n < 1260 or mss_n > 1460:
            show_toast(self.app_page, "请输入一个介于1260和1460之间的值", False)
            return
        if mtu_n < mss_n + 40:
            show_toast(self.app_page, "MTU要比MSS至少大40", False)
            return
        self.set_global_status("正在保存 MTU/MSS...", ft.Colors.ON_SURFACE)
        try:
            ok = await self.api_client.post_cmd("SET_DEVICE_MTU", {"mtu": mtu, "tcp_mss": mss})
            if ok:
                show_toast(self.app_page, "MTU/MSS 已应用", True)
                self.set_global_status("MTU/MSS 已应用", ft.Colors.PRIMARY)
                await self.load(silent=True)
            else:
                show_toast(self.app_page, "MTU/MSS 应用失败", False)
                self.set_global_status("MTU/MSS 应用失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"MTU/MSS 应用异常: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "MTU/MSS 应用异常", False)


    def on_bind_enable_toggle(self, e=None):
        # 开关即时提交；开启后显示下方规则区域
        target = bool(self.bind_enable.value)
        if getattr(self, "_bind_busy", False):
            self.bind_enable.value = not target
            self._sync_bind_form_visibility()
            try:
                self.update()
            except Exception:
                pass
            return
        self.bind_enable.value = not target
        self._sync_bind_form_visibility()
        try:
            self.update()
        except Exception:
            pass
        spawn_background_task(self, self._apply_bind_enable(target))

    async def _apply_bind_enable(self, target_on: bool):
        if getattr(self, "_bind_busy", False):
            return
        self._bind_busy = True
        action = "开启" if target_on else "关闭"
        self.set_global_status(f"正在{action} MAC-IP绑定...", ft.Colors.ON_SURFACE)
        try:
            ok = await self.api_client.post_cmd(
                "SET_BIND_STATIC_ADDRESS",
                {"mac_ip_status": "1" if target_on else "0"},
            )
            if ok:
                self.bind_enable.value = target_on
                self._sync_bind_form_visibility()
                show_toast(self.app_page, f"MAC-IP绑定已{action}", True)
                self.set_global_status(f"MAC-IP绑定已{action}", ft.Colors.PRIMARY)
                if target_on:
                    await self.load_bind(silent=True)
            else:
                show_toast(self.app_page, f"MAC-IP绑定{action}失败", False)
                self.set_global_status(f"MAC-IP绑定{action}失败", ft.Colors.ERROR)
            try:
                self.update()
            except Exception:
                pass
        except Exception as ex:
            logger.error(f"bind enable toggle failed: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, f"MAC-IP绑定{action}异常", False)
            self.set_global_status(f"MAC-IP绑定{action}异常", ft.Colors.ERROR)
        finally:
            self._bind_busy = False


    def _sync_bind_form_visibility(self):
        self.bind_form_box.visible = bool(self.bind_enable.value)

    def _parse_static_addr_list(self, raw):
        rules = []
        data = raw
        if isinstance(raw, dict):
            data = raw.get("current_static_addr_list", raw.get("StaticAddressFilterRules", []))
        if data is None or data == "":
            return []
        if isinstance(data, str):
            # 兼容字符串形态
            text = data.strip()
            if not text:
                return []
            # 尝试按常见分隔拆
            parts = [p for p in text.replace("|", ";").split(";") if p.strip()]
            for idx, p in enumerate(parts):
                segs = [x.strip() for x in p.split(",")]
                if len(segs) >= 2:
                    rules.append({"index": idx, "macAddress": segs[0], "ipAddress": segs[1], "hostName": segs[2] if len(segs) > 2 else ""})
            return rules
        if isinstance(data, list):
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                rules.append({
                    "index": idx,
                    "macAddress": str(item.get("mac") or item.get("macAddress") or "").strip(),
                    "ipAddress": str(item.get("ip") or item.get("ipAddress") or "").strip(),
                    "hostName": str(item.get("hostname") or item.get("hostName") or "").strip(),
                })
        return rules

    def _render_bind_rules(self):
        """大屏横向；小屏勾选框独立一行，信息在下方完整显示（对齐端口转发）"""
        self.bind_rule_checks = {}
        self.bind_rules_list.controls.clear()
        text_size = 10 if self.is_ultra_small_layout else (11 if self.is_small_layout else 13)
        item_padding = 5 if self.is_ultra_small_layout else (7 if self.is_small_layout else 10)
        item_spacing = 4 if self.is_ultra_small_layout else 8

        if not self.bind_rules:
            self.bind_rules_empty.visible = True
            return
        self.bind_rules_empty.visible = False

        for rule in self.bind_rules:
            idx = rule.get("index", 0)
            mac = str(rule.get("macAddress") or "--")
            ip = str(rule.get("ipAddress") or "--")
            cb = create_checkbox(label="", value=False, data=mac)
            if getattr(cb, "label_style", None) is None:
                cb.label_style = ft.TextStyle(size=text_size, color=ft.Colors.ON_SURFACE)
            else:
                cb.label_style.size = text_size
            self.bind_rule_checks[mac] = cb

            if self.is_small_layout or self.is_ultra_small_layout:
                # 小屏：勾选框独立一行，MAC/IP 标签与内容分行
                def _kv(label: str, value: str) -> ft.Column:
                    return ft.Column(
                        [
                            ft.Text(f"{label}：", size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                        ],
                        spacing=1,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    )
                info = ft.Column(
                    [
                        _kv("MAC 地址", mac),
                        _kv("IP 地址", ip),
                    ],
                    spacing=2 if self.is_ultra_small_layout else 3,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                )
                item_content = ft.Column(
                    [
                        ft.Row(
                            [cb, ft.Text(f"规则 {idx + 1}", size=text_size, color=ft.Colors.ON_SURFACE_VARIANT)],
                            spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        info,
                    ],
                    spacing=item_spacing,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                )
            else:
                # 大屏：横向分列，标题在上、值在下
                def cell(title: str, value: str, expand: int = 1) -> ft.Container:
                    return ft.Container(
                        content=ft.Column(
                            [
                                ft.Text(title, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, no_wrap=True),
                                ft.Text(value, size=text_size, color=ft.Colors.ON_SURFACE, no_wrap=False),
                            ],
                            spacing=2,
                        ),
                        expand=expand,
                    )
                info = ft.Row(
                    [
                        cell("MAC 地址", mac, 2),
                        cell("IP 地址", ip, 2),
                    ],
                    spacing=item_spacing,
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                item_content = ft.Row(
                    [
                        ft.Container(cb, width=28, alignment=ft.Alignment(-1, 0)),
                        info,
                    ],
                    spacing=item_spacing,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )

            self.bind_rules_list.controls.append(
                ft.Container(
                    content=item_content,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    border_radius=8,
                    padding=item_padding,
                )
            )

    async def load_bind(self, silent: bool = False):
        if not silent:
            self.set_global_status("正在读取 MAC-IP 绑定...", ft.Colors.ON_SURFACE)
        try:
            st = await self.api_client.get_cmd("mac_ip_status", multi_data=True)
            lst = await self.api_client.get_cmd("current_static_addr_list")
            info = await self.api_client.get_cmd(
                "host_name_web,mac_addr_web,ip_addr_web,lan_ipaddr,lan_netmask",
                multi_data=True,
            )
            enabled = str(st.get("mac_ip_status", "0")) == "1"
            self.bind_enable.value = enabled
            self._sync_bind_form_visibility()
            # 默认填当前设备/示例位
            if not (self.bind_mac.value or "").strip():
                self.bind_mac.value = str(info.get("mac_addr_web", "") or "")
            if not (self.bind_ip.value or "").strip():
                self.bind_ip.value = str(info.get("ip_addr_web", "") or "")
            self.bind_rules = self._parse_static_addr_list(lst)
            self._render_bind_rules()
            if not silent:
                self.set_global_status("MAC-IP 绑定已同步", ft.Colors.PRIMARY)
            try:
                self.update()
            except Exception:
                pass
        except Exception as ex:
            logger.error(f"load MAC-IP bind failed: {ex}", exc_info=DEBUG_MODE)
            if not silent:
                show_toast(self.app_page, "MAC-IP 绑定读取失败", False)
                self.set_global_status("MAC-IP 绑定读取失败", ft.Colors.ERROR)

    async def on_add_bind_rule(self, e=None):
        if not self.bind_enable.value:
            show_toast(self.app_page, "请先启用 MAC-IP 绑定", False)
            return
        mac_raw = (self.bind_mac.value or "").strip()
        ip = (self.bind_ip.value or "").strip()
        if not mac_raw or not ip:
            show_toast(self.app_page, "请填写 MAC 和 IP 地址", False)
            return
        mac = normalize_mac(mac_raw)
        if mac is None or not mac:
            show_toast(self.app_page, "MAC 地址格式不正确", False)
            return
        if not is_valid_ipv4(ip):
            show_toast(self.app_page, "IP 地址格式不正确", False)
            return
        self.set_global_status("正在添加 MAC-IP 绑定...", ft.Colors.ON_SURFACE)
        try:
            ok = await self.api_client.post_cmd(
                "BIND_STATIC_ADDRESS_ADD",
                {"mac_address": mac, "ip_address": ip},
            )
            if ok:
                show_toast(self.app_page, "MAC-IP 绑定已添加", True)
                self.set_global_status("MAC-IP 绑定已添加", ft.Colors.PRIMARY)
                self.bind_mac.value = ""
                self.bind_ip.value = ""
                await self.load_bind(silent=True)
            else:
                show_toast(self.app_page, "MAC-IP 绑定添加失败", False)
                self.set_global_status("MAC-IP 绑定添加失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"add bind rule failed: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "MAC-IP 绑定添加异常", False)

    async def on_delete_bind_rules(self, e=None):
        selected = []
        for mac, cb in self.bind_rule_checks.items():
            if getattr(cb, "value", False):
                selected.append(mac)
        if not selected:
            show_toast(self.app_page, "请先勾选要删除的规则", False)
            return
        self.set_global_status("正在删除 MAC-IP 绑定...", ft.Colors.ON_SURFACE)
        try:
            # 官方: mac_address = selected.join(';') + ';'
            mac_param = ";".join(selected) + ";"
            ok = await self.api_client.post_cmd(
                "BIND_STATIC_ADDRESS_DEL",
                {"mac_address": mac_param},
            )
            if ok:
                show_toast(self.app_page, "MAC-IP 绑定已删除", True)
                self.set_global_status("MAC-IP 绑定已删除", ft.Colors.PRIMARY)
                await self.load_bind(silent=True)
            else:
                show_toast(self.app_page, "MAC-IP 绑定删除失败", False)
                self.set_global_status("MAC-IP 绑定删除失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"delete bind rules failed: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "MAC-IP 绑定删除异常", False)

    async def on_bind_reboot(self, e=None):
        self.set_global_status("正在重启路由器...", ft.Colors.ON_SURFACE)
        try:
            ok = await self.api_client.post_cmd("REBOOT_DEVICE")
            if ok:
                show_toast(self.app_page, "路由器正在重启", True)
                self.set_global_status("路由器正在重启", ft.Colors.PRIMARY)
            else:
                show_toast(self.app_page, "重启失败", False)
                self.set_global_status("重启失败", ft.Colors.ERROR)
        except Exception as ex:
            logger.error(f"bind reboot failed: {ex}", exc_info=DEBUG_MODE)
            show_toast(self.app_page, "重启异常", False)

    def update_size(self, is_small: bool, is_ultra_small: bool = False):
        self.is_small_layout = is_small
        self.is_ultra_small_layout = is_ultra_small
        self.txt_title.size = 12 if is_ultra_small else (15 if is_small else 18)
        if hasattr(self, "txt_mtu_title"):
            self.txt_mtu_title.size = 11 if is_ultra_small else (13 if is_small else 15)
        if hasattr(self, "txt_bind_title"):
            self.txt_bind_title.size = 12 if is_ultra_small else (15 if is_small else 18)
        self.txt_hint.size = 9 if is_ultra_small else (11 if is_small else 12)
        if hasattr(self, "txt_hint_top"):
            self.txt_hint_top.size = 9 if is_ultra_small else (11 if is_small else 12)
        # NAT/桥接/绑定提示文字字号
        tip_size = 9 if is_ultra_small else (11 if is_small else 12)
        if hasattr(self, "txt_nat_tip"):
            self.txt_nat_tip.size = tip_size
        if hasattr(self, "txt_bridge_tip"):
            self.txt_bridge_tip.size = tip_size
        if hasattr(self, "txt_bind_tip"):
            self.txt_bind_tip.size = tip_size
        for label in [self.txt_data_label, self.txt_dhcp_label, self.txt_nat_label, self.txt_bridge_label, self.txt_bind_enable_label, self.txt_bind_list_title, self.bind_rules_empty]:
            label.size = 11 if is_ultra_small else (13 if is_small else 14)
        field_text_size = 10 if is_ultra_small else (12 if is_small else 14)
        field_label_size = 10 if is_ultra_small else (12 if is_small else 14)
        for ctrl in [
            self.ip_address, self.subnet_mask, self.dhcp_start, self.dhcp_end, self.dhcp_lease,
            self.bridge_bind, self.bridge_mac, self.mtu_value, self.mss_value,
            self.bind_mac, self.bind_ip,
        ]:
            if hasattr(ctrl, "expand"):
                ctrl.expand = True
            if hasattr(ctrl, "text_size"):
                ctrl.text_size = field_text_size
            if hasattr(ctrl, "label_style") and ctrl.label_style is not None:
                ctrl.label_style.size = field_label_size
            if hasattr(ctrl, "hint_style") and ctrl.hint_style is not None:
                ctrl.hint_style.size = field_label_size
            if hasattr(ctrl, "multiline") and not isinstance(ctrl, ft.Dropdown):
                ctrl.multiline = True
                if hasattr(ctrl, "min_lines"):
                    ctrl.min_lines = 1
                if hasattr(ctrl, "max_lines"):
                    ctrl.max_lines = 3
        button_height = 36 if is_ultra_small else (42 if is_small else 48)
        button_text_size = 11 if is_ultra_small else (13 if is_small else 14)
        for btn in [self.btn_lan_apply, self.btn_bridge_apply, self.btn_mtu_apply, self.btn_bind_add, self.btn_bind_reboot, self.btn_bind_delete]:
            btn.height = button_height
            if btn.style and getattr(btn.style, "text_style", None):
                btn.style.text_style.size = button_text_size
        self.padding = 8 if is_ultra_small else (12 if is_small else 15)
        self.border_radius = 8 if is_ultra_small else (10 if is_small else 12)
        self.content.spacing = 8 if is_ultra_small else (10 if is_small else 12)
        # 布局变化或字号变化时重绘规则卡片
        if getattr(self, "bind_rules", None) is not None:
            self._render_bind_rules()
        try:
            self.update()
        except Exception:
            pass


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
        self.background_tasks: Set[asyncio.Task] = set()  # 零散后台任务的强引用集合
        
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
        self.apn_card = APNCard(self.page, self.client, set_global_status_cb=self.status_card.set_global_status, refresh_config_cb=self.refresh_all)
        self.firewall_card = FirewallCard(self.page, self.client, set_global_status_cb=self.status_card.set_global_status)
        self.router_card = RouterCard(self.page, self.client, set_global_status_cb=self.status_card.set_global_status)

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

    def show_toolbox_menu(self, e=None):
        self.toolbox_menu.visible = True
        self.toolbox_content.visible = False
        if hasattr(self, 'apn_card'):
            self.apn_card.visible = False
        if hasattr(self, 'firewall_card'):
            self.firewall_card.visible = False
            self.firewall_card.show_menu()
        if hasattr(self, 'router_card'):
            self.router_card.visible = False
        self.view_toolbox.update()

    def show_wifi_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        # 显示WiFi，隐藏重启
        self.settings_card.wifi_section.visible = True
        self.reboot_card.visible = False
        self.apn_card.visible = False
        if hasattr(self, 'firewall_card'):
            self.firewall_card.visible = False
        if hasattr(self, 'router_card'):
            self.router_card.visible = False
        self.view_toolbox.update()

    def show_reboot_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        # 隐藏WiFi，显示重启
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = True
        self.apn_card.visible = False
        if hasattr(self, 'firewall_card'):
            self.firewall_card.visible = False
        if hasattr(self, 'router_card'):
            self.router_card.visible = False
        self.view_toolbox.update()

    def show_apn_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = False
        self.apn_card.visible = True
        if hasattr(self, 'firewall_card'):
            self.firewall_card.visible = False
        if hasattr(self, 'router_card'):
            self.router_card.visible = False
        self.view_toolbox.update()

    def show_firewall_settings(self, e):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = False
        self.apn_card.visible = False
        if hasattr(self, 'firewall_card'):
            self.firewall_card.visible = True
        if hasattr(self, 'router_card'):
            self.router_card.visible = False
            # 每次进入防火墙都重新拉取当前页状态，避免官方网页改过后本地开关不刷新
            if self.firewall_card.current_feature is None:
                self.firewall_card.show_menu()
            else:
                spawn_background_task(self, self.firewall_card.show_feature(self.firewall_card.current_feature))
        self.view_toolbox.update()

    def show_router_settings(self, e=None):
        self.toolbox_menu.visible = False
        self.toolbox_content.visible = True
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = False
        self.apn_card.visible = False
        if hasattr(self, "firewall_card"):
            self.firewall_card.visible = False
        if hasattr(self, "router_card"):
            self.router_card.visible = True
            spawn_background_task(self, self.router_card.load())
        self.view_toolbox.update()
    def show_disconnected_ui(self):
        if hasattr(self, "disconnect_text"):
            self.disconnect_text.value = "未连接 WiFi"
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
            
            # 滑动距离超过 40 像素：在工具子页时左/右滑都返回上级菜单
            if abs(self.swipe_accum) > 40:
                if self.current_nav_index == 3 and self.toolbox_content.visible:
                    # 防火墙子功能 -> 防火墙6项菜单；其他工具子页 -> 工具主菜单
                    if hasattr(self, 'firewall_card') and self.firewall_card.visible and self.firewall_card.current_feature is not None:
                        self.firewall_card.show_menu()
                        self.view_toolbox.update()
                    else:
                        self.show_toolbox_menu(None)
                    self.swipe_locked = True
                    return
                # 主导航页之间：左滑下一页，右滑上一页
                if self.swipe_accum < -40 and self.current_nav_index < 3:
                    handle_nav_click(self.current_nav_index + 1)
                elif self.swipe_accum > 40 and self.current_nav_index > 0:
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
            ft.Container(self._create_tool_item(ft.Icons.CELL_TOWER, "APN 设置", self.show_apn_settings), col={"xs": 12, "sm": 6}),
            ft.Container(self._create_tool_item(ft.Icons.SECURITY, "防火墙", self.show_firewall_settings), col={"xs": 12, "sm": 6}),
            ft.Container(self._create_tool_item(ft.Icons.ROUTER, "路由设置", self.show_router_settings), col={"xs": 12, "sm": 6}),
        ]
        self.toolbox_menu = ft.ResponsiveRow(controls=self.toolbox_items, spacing=14, run_spacing=14)
        
        self.settings_card.wifi_section.visible = False
        self.reboot_card.visible = False
        self.apn_card.visible = False
        self.firewall_card.visible = False
        self.router_card.visible = False

        self.toolbox_content = ft.Column([
            self.settings_card.wifi_section,
            self.reboot_card,
            self.apn_card,
            self.firewall_card,
            self.router_card,
        ], visible=False)

        # 内部滚动容器
        self.view_toolbox_scroll = ft.Column(
            [self.toolbox_menu, self.toolbox_content],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, scroll=ft.ScrollMode.AUTO, expand=True
        )

        # 最外层容器：滚动内容，外层自身禁止滚动
        self.view_toolbox = ft.Column(
            [self.view_toolbox_scroll],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH, expand=True, visible=False
        )

        self.content_area = ft.Column(
            [self.view_network_info, self.view_network_settings, self.view_device_list, self.view_toolbox],
            expand=True
        )

        # 未连接路由器的提示界面
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
        spawn_background_task(self, self._block_device(dev))

    def on_unblock_device(self, dev: dict):
        spawn_background_task(self, self._unblock_device(dev))

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
                self.client.invalidate_device_list_cache()
                await self.fetch_realtime(force_device_lists=True)
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
                self.client.invalidate_device_list_cache()
                await self.fetch_realtime(force_device_lists=True)
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
                    # 发起 HTTP 请求前，先用 TCP 极速探活
                    is_alive = await check_router_alive(self.device_state.ip)
                    if not is_alive:
                        self.offline_count += 1
                        if self.offline_count >= OFFLINE_FAIL_THRESHOLD and self.is_connected:
                            self.is_connected = False
                            self.show_disconnected_ui()
                            self.page.update()
                        continue # 探活失败，跳过后面的请求
                    
                    await self.fetch_realtime()
                except Exception as e:
                    logger.debug(f"后台刷新异常: {e}")
                finally:
                    self.is_refreshing = False
        except asyncio.CancelledError:
            logger.info("自动刷新任务已停止")
    async def fetch_realtime(self, force_device_lists: bool = False):
        if not self.device_state.client:
            return False
        try:
            # 拿到强类型数据对象；force_device_lists 时立刻刷新设备列表
            status = await self.client.get_realtime_status(force_device_lists=force_device_lists)
            
            # 精准识别“掉线”
            # 如果核心字段（IMSI、主板温度）同时为空，说明凭证已失效
            is_kicked_out = (
                not status.imsi and 
                status.temp_mdm in ("", "--")
            )
            if is_kicked_out:
                self.offline_count += 1
                if self.offline_count < OFFLINE_FAIL_THRESHOLD:
                    logger.debug(f"疑似断开连接，等待复核: {self.offline_count}/{OFFLINE_FAIL_THRESHOLD}")
                    return False
                self.is_connected = False
                self.show_disconnected_ui()
                return False
            
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
            self.apn_card.update_realtime(status) # 将联网状态传给 APN 控制按钮显示
            if hasattr(self, 'router_card'):
                self.router_card.update_realtime(status)
            return True
        except Exception as e:
            logger.debug(f"实时刷新异常: {e}")
            
            # 断网判定处理
            self.offline_count += 1
            if self.offline_count >= OFFLINE_FAIL_THRESHOLD and self.is_connected:
                self.is_connected = False
                self.show_disconnected_ui()
            return False

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
            except Exception as ex:
                logger.error(f"读取 WiFi 覆盖范围失败: {ex}")

            try:
                # 请求多个字段必须带上 multi_data=True
                # 精简为真正有用、路由器必然返回的核心字段，防止 URL 过长报错
                apn_cmd = (
                    "apn_interface_version,"
                    "APN_config0,APN_config1,APN_config2,APN_config3,APN_config4,APN_config5,APN_config6,APN_config7,APN_config8,APN_config9,"
                    "APN_config10,APN_config11,APN_config12,APN_config13,APN_config14,APN_config15,APN_config16,APN_config17,APN_config18,APN_config19,"
                    "ipv6_APN_config0,ipv6_APN_config1,ipv6_APN_config2,ipv6_APN_config3,ipv6_APN_config4,ipv6_APN_config5,ipv6_APN_config6,ipv6_APN_config7,ipv6_APN_config8,ipv6_APN_config9,"
                    "ipv6_APN_config10,ipv6_APN_config11,ipv6_APN_config12,ipv6_APN_config13,ipv6_APN_config14,ipv6_APN_config15,ipv6_APN_config16,ipv6_APN_config17,ipv6_APN_config18,ipv6_APN_config19,"
                    "m_profile_name,profile_name,wan_dial,apn_select,pdp_type,pdp_select,pdp_addr,index,Current_index,apn_auto_config,ipv6_apn_auto_config,apn_mode,wan_apn,ppp_auth_mode,ppp_username,ppp_passwd,dns_mode,prefer_dns_manual,standby_dns_manual,"
                    "ipv6_wan_apn,ipv6_pdp_type,ipv6_ppp_auth_mode,ipv6_ppp_username,ipv6_ppp_passwd,ipv6_dns_mode,ipv6_prefer_dns_manual,ipv6_standby_dns_manual,apn_num_preset,"
                    "wan_apn_ui,profile_name_ui,pdp_type_ui,ppp_auth_mode_ui,ppp_username_ui,ppp_passwd_ui,dns_mode_ui,prefer_dns_manual_ui,standby_dns_manual_ui,"
                    "ipv6_wan_apn_ui,ipv6_ppp_auth_mode_ui,ipv6_ppp_username_ui,ipv6_ppp_passwd_ui,ipv6_dns_mode_ui,ipv6_prefer_dns_manual_ui,ipv6_standby_dns_manual_ui"
                )
                apn_res = await self.client.get_cmd(apn_cmd, multi_data=True)
                safe_apn_res = {
                    k: ("***" if "passwd" in k.lower() else v)
                    for k, v in apn_res.items()
                    if v not in (None, "", [], {}) and k not in {"result"}
                }
                logger.info(f"APN 核心字段返回: {safe_apn_res}")
                res.update(apn_res)
                probe_cmd = (
                    "apn_profile,apn_profile_list,apn_list,apn_config,apn_config_list,"
                    "apn_setting,apn_settings,apn_profile_name,profile_name_list,"
                    "wan_apn_list,pdp_type_list,ppp_auth_mode_list,manual_apn_list"
                )
                try:
                    probe_res = await self.client.get_cmd(probe_cmd, multi_data=True)
                    useful_probe = {
                        k: v for k, v in probe_res.items()
                        if v not in (None, "", [], {}) and k not in {"result"}
                    }
                    if useful_probe:
                        logger.info(f"APN 探测字段返回: {useful_probe}")
                        res.update(useful_probe)
                except Exception as probe_ex:
                    logger.debug(f"APN 探测字段请求失败: {probe_ex}")
            except Exception as ex:
                logger.error(f"APN 数据请求失败: {ex}")

            current_net_mode = str(net_res.get(API_KEY_READ, "")).strip().upper()
            
            self.reboot_card.update_config(res)
            self.settings_card.update_config(
                res, 
                sa_res.get("nr5g_sa_band_lock", ""), 
                nsa_res.get("nr5g_nsa_band_lock", ""), 
                current_net_mode
            )
            self.apn_card.update_config(res)

            dev_status = " | 开发者模式已解锁" if self.device_state.dev_unlocked else " | 开发者模式未解锁"
            self.status_card.set_global_status("数据读取成功" + dev_status, ft.Colors.PRIMARY if self.device_state.dev_unlocked else ft.Colors.ERROR)
            
            realtime_ok = False
            # 手动/全量刷新：强制拉取设备列表，不受 3s/5s 降频限制
            self.client.invalidate_device_list_cache()
            for _ in range(OFFLINE_FAIL_THRESHOLD):
                if await self.fetch_realtime(force_device_lists=True):
                    realtime_ok = True
                    break
                await asyncio.sleep(0.5)
            if not realtime_ok:
                raise RuntimeError("实时数据刷新失败")
            if e:
                show_toast(self.page, "数据刷新成功", True)
            logger.info("全量配置刷新完成")
            return True
        except Exception as ex: # 注意这里用了 ex 防止和参数 e 冲突
            logger.error(f"全量刷新异常: {ex}", exc_info=DEBUG_MODE)
            self.status_card.set_global_status("读取失败，请检查连接", ft.Colors.ERROR)
            if e:
                show_toast(self.page, "数据读取失败，请检查连接", False)
            return False

    async def on_login_success(self):
        self.login_view.visible = False
        self.main_view.visible = True
        self.page.update()

        if await self.client.set_data_connection(True):
            self.settings_card.data_switch.value = True
            self.apn_card.is_data_connected = True
            self.apn_card._sync_data_ui()
        else:
            logger.warning("登录成功，但强制开启数据连接失败或等待连接超时")

        await self.refresh_all()
        # 单设备登录场景：重新登录后按设备最新状态同步防火墙开关
        if hasattr(self, "firewall_card"):
            await self.firewall_card.sync_current_feature()
        if hasattr(self, "router_card"):
            await self.router_card.sync_current()
        self.start_auto_refresh()

    async def do_relogin(self, e=None):
        # 拦截：网络模块正在执行断开、设置或恢复连接时严禁重登
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
                data_connected = await self.client.set_data_connection(True)
                if data_connected:
                    self.settings_card.data_switch.value = True
                    self.apn_card.is_data_connected = True
                    self.apn_card._sync_data_ui()
                else:
                    logger.warning("重登成功，但强制开启数据连接失败或等待连接超时")

                verified = await self.refresh_all()
                if not verified:
                    raise RuntimeError("重登后读取设备数据失败")

                # 网页挤掉登录后重登：重新查询防火墙当前页开关状态
                if hasattr(self, "firewall_card"):
                    await self.firewall_card.sync_current_feature()
                if hasattr(self, "router_card"):
                    await self.router_card.sync_current()

                self.offline_count = 0
                self.is_connected = True
                self.show_connected_ui()

                if dev_ok:
                    self.status_card.set_global_status("重登成功，开发者模式已解锁", ft.Colors.PRIMARY)
                    show_toast(self.page, "重登成功", True)
                else:
                    self.status_card.set_global_status("重登成功，开发者模式解锁失败", ft.Colors.ERROR)
                    show_toast(self.page, "重登成功，开发者模式解锁失败", False)
                
                # 重登和全量刷新顺利完成后，重新启动后台刷新任务
                self.start_auto_refresh()
        except LoginAuthError as auth_ex:
            # 重登页不主动删本地存储密码；仅提示可能被改密/锁定
            self.status_card.set_global_status(str(auth_ex), ft.Colors.ERROR)
            show_toast(self.page, str(auth_ex), False)
        except LoginNetworkError as net_ex:
            self.status_card.set_global_status(str(net_ex), ft.Colors.ERROR)
            show_toast(self.page, str(net_ex), False)
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
            self.login_view.update_size(is_small, is_ultra_small)
        if hasattr(self, 'settings_card'):
            self.settings_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'reboot_card'):
            self.reboot_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'device_list_card'):
            self.device_list_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'apn_card'):
            self.apn_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'firewall_card'):
            self.firewall_card.update_size(is_small, is_ultra_small)
        if hasattr(self, 'router_card'):
            self.router_card.update_size(is_small, is_ultra_small)
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
            # 适当放大字号和图标:
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
