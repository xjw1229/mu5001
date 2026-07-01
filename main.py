import flet as ft
import httpx
import hashlib
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List, Set, Callable, Union

# ==========================================
# 日志配置
# 1. 输出到控制台
# 2. 日志格式包含进程号、模块名、行号，便于定位
# 3. DEBUG_MODE 开关控制调试日志输出
# 4. 避免重复日志刷屏
# ==========================================
DEBUG_MODE = False  # 调试时设为 True 或 False 可开关输出完整调试信息
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
# 全局配置
# ==========================================

# UI 全局配色方案，统一深色主题风格
@dataclass
class ColorConfig:
    BG_COLOR = "#171920"          # 页面主背景
    CARD_BG = "#40425C"           # 卡片容器背景
    INPUT_BG = "#36394F"          # 输入框/下拉框背景
    TEXT_MAIN = "#FFFFFF"         # 主要文字
    TEXT_SEC = "#A1A4B0"          # 次要文字/提示文字
    SWITCH_LABEL = "#FFF9F2"      # 开关说明文字
    ACCENT_COLOR = "#82A5E0"      # 主题强调色
    ERROR_COLOR = "#E08282"       # 错误、警告色
    DIVIDER_COLOR = "#2A2C3E"     # 分割线
    BTN_BG = "#535773"            # 普通按钮默认背景
    BTN_HOVER_BG = "#6A6F91"      # 普通按钮悬浮背景
    TOP_BTN_BG = "#82A5E0"        # 顶部按钮背景
    TOP_BTN_TEXT = "#FFFFFF"      # 顶部按钮文字颜色
    TOAST_SUCCESS_BG = "#2D4A3E"  # 成功提示背景
    TOAST_ERROR_BG = "#5C2D2D"    # 失败提示背景

# 超时与间隔配置（单位：秒）
API_TIMEOUT = 5               # 普通 API 请求超时
LOGIN_TIMEOUT = 3             # 登录相关请求超时
AUTO_REFRESH_INTERVAL = 1     # 实时数据自动刷新间隔
NET_SWITCH_DELAY = 0.4        # 网络断连/重连等待时间
LABEL_W = 75                  # 表单左侧标签统一宽度

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
@dataclass
class DeviceState:
    client: Optional[httpx.AsyncClient] = None   # httpx 异步客户端实例
    ip: str = ""                                 # 设备管理地址
    rd0: str = ""                                # 设备内部版本号
    rd1: str = ""                                # 设备固件版本号
    password: str = ""                           # 明文管理员密码
    dev_unlocked: bool = False                   # 开发者模式是否解锁

# 封装设备登录、配置读写、状态查询等所有 HTTP 交互，自动维护会话 Cookie 与 AD 鉴权计算。
class MU5001Client:
    # 初始化客户端，state 为外部共享的设备状态实例
    def __init__(self, state: DeviceState):
        self.state = state
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
        if not self.state.client:
            raise RuntimeError("未登录设备，无法执行 POST 请求")
        params = params or {}
        logger.debug(f"POST goformId={goform_id}, params={params}")
        try:
            # 重新获取 RD 并计算 AD
            rd_res = await self.get_cmd("RD")
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
            success = result in ["0", "success", "4"]
            if success:
                logger.info(f"POST 成功: {goform_id}")
            else:
                logger.warning(f"POST 返回失败: {goform_id}, result={result}")
            return success
        except Exception as e:
            logger.error(f"POST 异常: {goform_id}, {type(e).__name__}: {e}", exc_info=DEBUG_MODE)
            raise

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

    # 异步登录设备，并发获取参数优化速度
    # ip 为设备管理地址，password 为管理员明文密码
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

# 创建统一样式的主题按钮
def create_button(
    text: str,
    on_click: Callable,
    height: Optional[int] = None,
    expand: bool = False
) -> ft.Control:
    btn_style = ft.ButtonStyle(
        color=ColorConfig.TEXT_MAIN,
        bgcolor={
            "hovered": ColorConfig.BTN_HOVER_BG,
            "": ColorConfig.BTN_BG
        },
        elevation={"": 0}
    )
    BtnClass = getattr(ft, "Button", ft.ElevatedButton)
    btn = BtnClass(text, on_click=on_click, height=height, style=btn_style)
    btn.expand = expand
    return btn

# 在页面底部弹出浮动提示条
def show_toast(page: ft.Page, msg: str, success: bool = True) -> None:
    bg = ColorConfig.TOAST_SUCCESS_BG if success else ColorConfig.TOAST_ERROR_BG
    for c in list(page.overlay):
        if isinstance(c, ft.SnackBar):
            page.overlay.remove(c)
            
    snack = ft.SnackBar(
        content=ft.Text(msg, color=ColorConfig.TEXT_MAIN, weight=ft.FontWeight.BOLD),
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
        self.sec_style = ft.TextStyle(color=ColorConfig.TEXT_SEC)
        
        self.ip_input = ft.TextField(
            label="管理地址", value=DEFAULT_IP,
            color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
            border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
            label_style=self.sec_style, hint_style=self.sec_style
        )
        self.pwd_input = ft.TextField(
            label="管理员密码", password=True, can_reveal_password=True, value="",
            color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
            border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
            label_style=self.sec_style, hint_style=self.sec_style
        )
        self.remember_cb = ft.Checkbox(
            label="记住密码", value=False,
            label_style=ft.TextStyle(color=ColorConfig.TEXT_SEC),
            fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
            check_color=ColorConfig.BG_COLOR
        )
        self.login_status = ft.Text("输入账号密码登录", color=ColorConfig.TEXT_SEC, text_align=ft.TextAlign.CENTER)
        self.login_btn = create_button("登录", on_click=self.do_login, height=45)
        self.content = ft.Column(
            [
                ft.Container(height=40),
                ft.Text("MU5001", size=32, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN, text_align=ft.TextAlign.CENTER),
                ft.Container(height=20),
                self.ip_input, self.pwd_input, self.remember_cb,
                ft.Container(height=8),
                self.login_status, self.login_btn
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
        )

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
            self.login_status.color = ColorConfig.ERROR_COLOR
            self.update()
            return
        self.login_btn.disabled = True
        self.login_status.value = "正在验证登录..."
        self.login_status.color = ColorConfig.TEXT_SEC
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
                        
                self.login_status.value = "解锁开发者权限..."
                self.update()
                await self.api_client.unlock_developer()
                show_toast(self.app_page, "登录成功", True)
                await self.on_login_success()
            else:
                await self.clear_credentials_and_reset(is_error=True)
                self.login_status.value = "密码错误或账号锁定"
                self.login_status.color = ColorConfig.ERROR_COLOR
                show_toast(self.app_page, "密码错误或账号锁定", False)
        except Exception:
            await self.clear_credentials_and_reset(is_error=True)
            self.login_status.value = "连接失败，请检查地址和网络"
            self.login_status.color = ColorConfig.ERROR_COLOR
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
            self.login_status.color = ColorConfig.TEXT_SEC
        self.update()

# ==========================================
# UI 组件拆分 - 状态卡片
# ==========================================
class StatusCard(ft.Container):
    def __init__(self):
        super().__init__(padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12)
        self.is_small = False  # 记录当前是否为小屏幕

        # 1. 基础网络信息
        self.txt_provider = ft.Text("运营商: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_battery = ft.Text("电量: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_network = ft.Text("网络: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_conn_time = ft.Text("连接时长: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_wan_ip = ft.Text("WAN IP: --", size=14, color=ColorConfig.TEXT_MAIN)
        
        # 2. 流量与设备信息
        self.txt_users = ft.Text("接入设备: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_tx_speed = ft.Text("上传速度: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_rx_speed = ft.Text("下载速度: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_traffic_rt = ft.Text("本次流量: --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_traffic_mo = ft.Text("当月流量: --", size=14, color=ColorConfig.TEXT_MAIN)
        
        # 3. 射频信息
        self.txt_freq = ft.Text("ARFCN (小区频点): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_pci = ft.Text("PCI (物理小区标识): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_ecellid = ft.Text("eCellID (小区编号): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_rsrp = ft.Text("RSRP (信号强度): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_rsrq = ft.Text("RSRQ (信号质量): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_sinr = ft.Text("SINR (信噪比): --", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_rssi = ft.Text("RSSI (接收总功率): --", size=14, color=ColorConfig.TEXT_MAIN)
        
        # 4. 温度与状态
        self.txt_temp_bat = ft.Text("电池温度: --℃", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_temp_mdm = ft.Text("4G Modem: --℃", size=14, color=ColorConfig.TEXT_MAIN)
        self.txt_temp_pa = ft.Text("PA: --℃", size=14, color=ColorConfig.TEXT_MAIN)
        self.status_text = ft.Text("", color=ColorConfig.TEXT_MAIN)
        
        # 重新排版
        self.content = ft.Column([
            self.txt_provider, self.txt_battery, self.txt_network, self.txt_conn_time, self.txt_wan_ip,
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            self.txt_tx_speed, self.txt_rx_speed, self.txt_traffic_rt, self.txt_traffic_mo, self.txt_users,
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            self.txt_freq, self.txt_pci, self.txt_ecellid, self.txt_rsrp, self.txt_rsrq, self.txt_sinr, self.txt_rssi,
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            self.txt_temp_bat, self.txt_temp_mdm, self.txt_temp_pa,
            ft.Divider(height=8, color=ColorConfig.DIVIDER_COLOR),
            self.status_text
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def set_global_status(self, text: str, color: str):
        self.status_text.value = text
        self.status_text.color = color
        self.update()

    def update_realtime(self, res: dict, macs_count: Optional[int] = None):
        # 动态换行：小屏强制换行防抖动，大屏保持正常空格并排
        sep = "\n" if self.is_small else " "

        # 设备状态与网络信息
        net_type = res.get('network_type', '?')
        net_type_upper = net_type.upper()
        lte_band = str(res.get('wan_active_band', '')).strip()
        nr_band = str(res.get('nr5g_action_band', '')).strip()
        is_5g = any(k in net_type_upper for k in ['5G', 'SA', 'NSA'])
        band = nr_band if (is_5g and nr_band) else lte_band
        
        provider = str(res.get('network_provider', '')).upper()
        self.txt_provider.value = f"运营商:{sep}{provider or '--'}"
        
        bat = str(res.get('battery_value', '?'))
        charge = "充电中" if str(res.get('battery_charging', '')) in ['1', '2'] else "未充电"
        self.txt_battery.value = f"电量:{sep}{bat}% ({charge})"
        self.txt_network.value = f"网络:{sep}{net_type} ({band})" if band else f"网络:{sep}{net_type}"
        self.txt_wan_ip.value = f"WAN IP:{sep}{res.get('wan_ipaddr', '未分配')}"
        
        try:
            conn_time = int(res.get("realtime_time", 0))
            hours, rem = divmod(conn_time, 3600)
            minutes, seconds = divmod(rem, 60)
            self.txt_conn_time.value = f"连接时长:{sep}{hours:02d}:{minutes:02d}:{seconds:02d}"
        except Exception:
            self.txt_conn_time.value = f"连接时长:{sep}--"

        # 流量与设备信息
        self.txt_tx_speed.value = f"上传速度:{sep}{format_bytes(res.get('realtime_tx_thrpt', 0))}/s"
        self.txt_rx_speed.value = f"下载速度:{sep}{format_bytes(res.get('realtime_rx_thrpt', 0))}/s"
        rt_total = safe_float(res.get("realtime_tx_bytes")) + safe_float(res.get("realtime_rx_bytes"))
        mo_total = safe_float(res.get("monthly_tx_bytes")) + safe_float(res.get("monthly_rx_bytes"))
        self.txt_traffic_rt.value = f"本次流量:{sep}{format_bytes(rt_total)}"
        self.txt_traffic_mo.value = f"当月流量:{sep}{format_bytes(mo_total)}"
        
        if macs_count is not None:
            self.txt_users.value = f"接入设备:{sep}{macs_count} 台"

        # 射频信号参数
        freq_5g = str(res.get("nr5g_action_channel", "") or res.get("nr5g_arfcn", "") or res.get("Z5g_arfcn", "")).strip()
        freq_4g = str(res.get("wan_active_channel", "")).strip()
        self.txt_freq.value = f"ARFCN (小区频点):{sep}{freq_5g or freq_4g or '--'}"
        
        #十六进制转十进制
        def parse_hex(raw):
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
        
        pci_5g_raw = res.get("nr5g_pci", "") or res.get("Z5g_pci", "")
        pci_4g_raw = res.get("lte_pci", "")
        display_pci_5g = parse_hex(pci_5g_raw)
        display_pci_4g = parse_hex(pci_4g_raw)
        self.txt_pci.value = f"PCI (物理小区标识):{sep}{display_pci_5g or display_pci_4g or '--'}"

        rsrp_5g = str(res.get('Z5g_rsrp', '') or res.get('nr5g_rsrp', '')).strip()
        rsrp_4g = str(res.get('lte_rsrp', '')).strip()
        self.txt_rsrp.value = f"RSRP (信号强度):{sep}{rsrp_5g or rsrp_4g or '--'} dBm"

        rsrq_5g = str(res.get('Z5g_rsrq', '') or res.get('nr5g_rsrq', '')).strip()
        rsrq_4g = str(res.get('lte_rsrq', '')).strip()
        self.txt_rsrq.value = f"RSRQ (信号质量):{sep}{rsrq_5g or rsrq_4g or '--'} dB"

        sinr_5g = str(res.get('Z5g_SINR', '') or res.get('Z5g_sinr', '') or res.get('nr5g_sinr', '')).strip()
        sinr_4g = str(res.get('lte_snr', '') or res.get('lte_sinr', '')).strip()
        self.txt_sinr.value = f"SINR (信噪比):{sep}{sinr_5g or sinr_4g or '--'} dB"

        rssi_5g = str(res.get('Z5g_rssi', '') or res.get('nr5g_rssi', '')).strip()
        rssi_4g = str(res.get('lte_rssi', '')).strip()
        self.txt_rssi.value = f"RSSI (接收总功率):{sep}{rssi_5g or rssi_4g or '--'} dBm"

        # 核心解算 eCellID (小区编号)
        raw_5g_val = str(res.get("nr5g_cell_id", "")).strip()
        if not raw_5g_val or raw_5g_val == "0":
            raw_5g_val = str(res.get("Z5g_Cell_ID", "")).strip()
        raw_4g_val = str(res.get("cell_id", "")).strip()

        mcc_mnc_raw = str(res.get('mcc_mnc', '')).strip()
        mcc_mnc = normalize_plmn(mcc_mnc_raw)
        provider = str(res.get('network_provider', '')).upper()

        # 位宽判断：优先 mcc_mnc，兜底 provider
        is_14bit_provider = False
        cmcc_plmns = {"46000", "46002", "46004", "46007", "46008", "46015"} 
        cu_ct_plmns = {"46001", "46003", "46006", "46009", "46011"}

        if mcc_mnc in cmcc_plmns:
            is_14bit_provider = True
        elif mcc_mnc in cu_ct_plmns:
            is_14bit_provider = False
        else:
            cmcc_keys = {"移动", "MOBILE", "CMCC", "广电", "CBN", "中移", "CHINA MOBILE"}
            if any(k in provider for k in cmcc_keys):
                is_14bit_provider = True

        nr_cell_bits = 14 if is_14bit_provider else 12
        net_type_upper = str(res.get('network_type', '')).upper()
        is_5g = any(k in net_type_upper for k in ['5G', 'SA', 'NSA'])

        # 解算输出 eCellID (小区编号)
        if is_5g and raw_5g_val and raw_5g_val != "0":
            dec_val = parse_cell_id(raw_5g_val)
            # dec_val <= 0 统一视为无效：包含空串返0、解析失败返-1、真实值为0三种情况
            if dec_val > 0:
                MAX_NCI = (1 << 36) - 1
                # 强行截取低36位作为 NCI，过滤掉 PLMN 前缀的 NCGI 长数值
                nci_val = dec_val & MAX_NCI 
                gnb_id = nci_val >> nr_cell_bits
                cell_id = nci_val & ((1 << nr_cell_bits) - 1)
                self.txt_ecellid.value = f"eCellID (小区编号):{sep}{gnb_id}-{cell_id}"
            else:
                # 解析失败或值无效，显示原始文本
                self.txt_ecellid.value = f"eCellID (小区编号):{sep}{raw_5g_val}"
        else:
            if raw_4g_val and raw_4g_val != "0":
                ecell_dec = parse_cell_id(raw_4g_val)
                if ecell_dec > 0:
                    MAX_ECI = (1 << 28) - 1
                    # 强行截取低28位作为 ECI，过滤掉 PLMN 前缀的 CGI 长数值
                    eci_val = ecell_dec & MAX_ECI
                    enb_id = eci_val >> 8
                    local_cell = eci_val & 0xFF
                    self.txt_ecellid.value = f"eCellID (小区编号):{sep}{enb_id}-{local_cell}"
                else:
                    self.txt_ecellid.value = f"eCellID (小区编号):{sep}{raw_4g_val}"
            else:
                self.txt_ecellid.value = f"eCellID (小区编号):{sep}--"

        # 温度信息
        self.txt_temp_bat.value = f"电池温度:{sep}{res.get('battery_temp', '--')}℃"
        self.txt_temp_mdm.value = f"4G Modem:{sep}{res.get('pm_sensor_mdm', '--')}℃"
        self.txt_temp_pa.value = f"PA:{sep}{res.get('pm_sensor_pa1', '--')}℃"
        
        self.update()

# ==========================================
# UI 组件拆分 - 定时重启卡片
# ==========================================
class RebootCard(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable):
        super().__init__(padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12)
        self.app_page = page
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.sec_style = ft.TextStyle(color=ColorConfig.TEXT_SEC)

        self.txt_local_time = ft.Text("设备当前时间: --", size=12, color=ColorConfig.TEXT_SEC)    
        # 定时重启功能绑定 on_change 事件
        self.reboot_enable = ft.Switch(
            value=False,
            active_track_color=ColorConfig.ACCENT_COLOR, inactive_track_color=ColorConfig.BG_COLOR,
            thumb_color=ColorConfig.TEXT_MAIN,
            on_change=self.on_reboot_switch_change
        )
        self.reboot_hint = ft.Text("提示：时:0~23 | 分:0~59 | 缓冲时间:1~6", size=12, color=ColorConfig.TEXT_SEC)
        self.reboot_mode = ft.Dropdown(
            label="重启模式",
            options=[ft.dropdown.Option("1", "1 - 按周自动重启"), ft.dropdown.Option("2", "2 - 按间隔天数")], 
            value="1", color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
            label_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        
        self.rb_time_hr = ft.TextField(
            label="时", expand=1, value="02", input_filter=ft.NumbersOnlyInputFilter(),
            color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, hint_style=self.sec_style,
            border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        self.rb_time_min = ft.TextField(
            label="分", expand=1, value="00", input_filter=ft.NumbersOnlyInputFilter(),
            color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, hint_style=self.sec_style,
            border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        self.rb_buffer = ft.TextField(
            label="缓冲时间", expand=1, value="02", input_filter=ft.NumbersOnlyInputFilter(),
            color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, hint_style=self.sec_style,
            border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        
        self.week_cbs = [
            ft.Checkbox(
                label=w, value=False, data=str(i+1), on_change=self.on_week_change,
                label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN),
                fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
                check_color=ColorConfig.BG_COLOR
            ) for i, w in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
        ]
        self.rb_interval = ft.Dropdown(
            label="间隔天数",
            options=[ft.dropdown.Option(str(i), str(i)) for i in range(1, 31)],
            value="1", menu_height=300, color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
            label_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        self.btn_save_reboot = create_button("保存重启规则", on_click=self.on_save_reboot)
        
        # 创建一个用来动态切换排版的容器
        self.colon = ft.Text(":", size=20, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN)
        self.time_container = ft.Container()
        
        # 判断屏幕大小
        is_small = page.width < 340 if page.width > 0 else False 
        
        # 如果是小屏，直接让它竖着排 (Column)
        if is_small:
            self.time_container.content = ft.Column(
                [self.rb_time_hr, self.rb_time_min, self.rb_buffer],
                spacing=5
            )
            # 关掉横向自动拉伸，防止在小屏幕上变形
            self.rb_time_hr.expand = False
            self.rb_time_min.expand = False
            self.rb_buffer.expand = False
            
        # 3. 如果是大屏，就正常横着排 (Row)
        else:
            self.time_container.content = ft.Row(
                [self.rb_time_hr, self.rb_time_min, self.rb_buffer], 
                spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER
            )

        row_weeks = ft.Row(controls=[ft.Container(content=cb, width=75, padding=0, margin=0) for cb in self.week_cbs], wrap=True, spacing=10, run_spacing=5)

        self.content = ft.Column([
            ft.Text("定时重启规则", size=18, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            self.txt_local_time, ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            ft.Row([self.reboot_enable, ft.Text("定时重启", color=ColorConfig.SWITCH_LABEL)], vertical_alignment=ft.CrossAxisAlignment.CENTER), 
            self.reboot_hint, 
            
            self.time_container,  # 动态容器
            
            self.reboot_mode,
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            ft.Text("选项1: 按周触发（仅选 1 生效）", size=13, color=ColorConfig.TEXT_SEC, weight=ft.FontWeight.BOLD),
            row_weeks, ft.Container(height=5),
            ft.Text("选项2: 间隔触发（仅选 2 生效）", size=13, color=ColorConfig.TEXT_SEC, weight=ft.FontWeight.BOLD),
            self.rb_interval, ft.Container(height=10), self.btn_save_reboot
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

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

    # 提取公共的获取 payload 逻辑，供拨动开关和点击保存按钮共用
    def _get_reboot_payload(self):
        weeks = ",".join([cb.data for cb in self.week_cbs if cb.value])
        return {
            "reboot_schedule_enable": "1" if self.reboot_enable.value else "0",
            "reboot_schedule_mode": self.reboot_mode.value,
            "reboot_hour1": self.rb_time_hr.value.zfill(2),
            "reboot_hour2": self.rb_time_hr.value.zfill(2),
            "reboot_min1": self.rb_time_min.value.zfill(2),
            "reboot_min2": self.rb_time_min.value.zfill(2),
            "reboot_timeframe_hours1": self.rb_buffer.value.zfill(2),
            "reboot_timeframe_hours2": self.rb_buffer.value.zfill(2),
            "reboot_dow": weeks,
            "reboot_dod": self.rb_interval.value
        }

    # 拨动定时重启开关直接生效
    async def on_reboot_switch_change(self, e):
        is_on = self.reboot_enable.value
        show_toast(self.app_page, f"正在{'开启' if is_on else '关闭'}定时重启...", True)
        payload = self._get_reboot_payload()
        try:
            if await self.api_client.post_cmd("FIX_TIME_REBOOT_SCHEDULE", payload):
                self.set_global_status(f"定时重启已{'开启' if is_on else '关闭'}", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, f"定时重启已{'开启' if is_on else '关闭'}", True)
            else:
                self.set_global_status("定时重启状态切换失败", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "状态切换失败", False)
                self.reboot_enable.value = not is_on
        except Exception:
            self.set_global_status("定时重启状态切换异常", ColorConfig.ERROR_COLOR)
            show_toast(self.app_page, "状态切换异常", False)
            self.reboot_enable.value = not is_on
        self.update()

    # 保存重启规则
    async def on_save_reboot(self, e):
        payload = self._get_reboot_payload()
        try:
            if await self.api_client.post_cmd("FIX_TIME_REBOOT_SCHEDULE", payload):
                self.set_global_status("定时重启配置已保存", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "定时重启配置保存成功", True)
            else:
                self.set_global_status("保存失败，请检查连接状态", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "定时重启配置保存失败", False)
        except Exception:
            self.set_global_status("保存失败", ColorConfig.ERROR_COLOR)
        self.update()

# ==========================================
# UI 组件拆分 - 高级设置卡片
# ==========================================
class SettingsCard(ft.Container):
    def __init__(self, page: ft.Page, client: MU5001Client, set_global_status_cb: Callable, on_reboot_cb: Callable):
        super().__init__(padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12)
        self.app_page = page 
        self.api_client = client
        self.set_global_status = set_global_status_cb
        self.on_reboot_device = on_reboot_cb
        self.sec_style = ft.TextStyle(color=ColorConfig.TEXT_SEC)
        self.lte_selected: Set[str] = set(LTE_BANDS)
        self.nr_sa_selected: Set[str] = set(NR_SA_BANDS)
        self.nr_nsa_selected: Set[str] = set(NR_NSA_BANDS)
        self.lte_cbs: Dict[str, ft.Checkbox] = {}
        self.sa_cbs: Dict[str, ft.Checkbox] = {}
        self.nsa_cbs: Dict[str, ft.Checkbox] = {}
        self.net_mode_cbs: Dict[str, ft.Checkbox] = {}
        self.is_switching_data = False
        self.build_ui()

    def _create_checkbox_grid(self, bands: List[str], prefix: str, selected: Set[str], cb_map: Dict[str, ft.Checkbox], on_change: Callable) -> ft.Row:
        controls = []
        for b in bands:
            cb = ft.Checkbox(
                label=f"{prefix}{b}", value=b in selected, data=b, on_change=on_change,
                label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN),
                fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
                check_color=ColorConfig.BG_COLOR
            )
            cb_map[b] = cb
            controls.append(ft.Container(content=cb, width=72, padding=0, margin=0))
        return ft.Row(controls, wrap=True, spacing=5, run_spacing=0)

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

    def build_ui(self):
        # WiFi 休眠
        self.wifi_sleep = ft.Dropdown(
            label="WiFi 空闲休眠",
            options=[ft.dropdown.Option(str(k), v) for k, v in [("0", "永不休眠"), ("5", "5 分钟"), ("10", "10 分钟"), ("20", "20 分钟"), ("30", "30 分钟"), ("60", "1 小时"), ("120", "2 小时")]],
            value="10", color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
            label_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR
        )
        btn_wifi_sleep = create_button("保存休眠设置", on_click=self.on_wifi_sleep_save)
        
        # 数据连接开关
        self.data_switch = ft.Switch(
            value=True,
            active_track_color=ColorConfig.ACCENT_COLOR,
            inactive_track_color=ColorConfig.BG_COLOR,
            thumb_color=ColorConfig.TEXT_MAIN,
            on_change=self.on_data_switch_change
        )
        
        # 网络模式
        net_mode_controls = []
        for name in NET_CONFIG.keys():
            cb = ft.Checkbox(
                label=name, value=(name == "5G/4G/3G"), on_change=self.on_net_mode_change,
                label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN), fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR}, check_color=ColorConfig.BG_COLOR
            )
            self.net_mode_cbs[name] = cb
            net_mode_controls.append(ft.Container(content=cb, width=120, padding=0, margin=0))
        net_mode_grid = ft.Row(controls=net_mode_controls, wrap=True, spacing=10, run_spacing=5)
        btn_net_mode_apply = create_button("应用网络锁定", on_click=self.on_apply_net_mode)
        
        # 频段选择
        lte_grid = self._create_checkbox_grid(LTE_BANDS, "B", self.lte_selected, self.lte_cbs, self.on_lte_change)
        sa_grid = self._create_checkbox_grid(NR_SA_BANDS, "N", self.nr_sa_selected, self.sa_cbs, self.on_sa_change)
        nsa_grid = self._create_checkbox_grid(NR_NSA_BANDS, "N", self.nr_nsa_selected, self.nsa_cbs, self.on_nsa_change)
        btn_lte_apply = create_button("应用 4G 锁频段", on_click=self.on_apply_lte)
        btn_sa_apply = create_button("应用 5G SA 锁频段", on_click=self.on_apply_sa)
        btn_nsa_apply = create_button("应用 5G NSA 锁频段", on_click=self.on_apply_nsa)
        
        # 锁小区表单
        self.cell_pci = ft.TextField(expand=True, color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, hint_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR, input_filter=ft.NumbersOnlyInputFilter())
        self.cell_earfcn = ft.TextField(expand=True, color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, hint_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR, input_filter=ft.NumbersOnlyInputFilter())
        self.cell_band = ft.Dropdown(expand=True, options=[ft.dropdown.Option(b, str(b)) for b in ["1", "3", "28", "41", "78"]], value="1", color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR)
        self.cell_scs = ft.Dropdown(expand=True, options=[ft.dropdown.Option(s, f"{s}KHz") for s in ["15", "30", "60"]], value="15", color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG, label_style=self.sec_style, border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR)
        # 动态标签：锁小区显示 (大屏使用)
        self.lbl_pci_side = ft.Text("PCI", color=ColorConfig.TEXT_MAIN, width=LABEL_W)
        self.lbl_earfcn_side = ft.Text("ARFCN", color=ColorConfig.TEXT_MAIN, width=LABEL_W)
        self.lbl_band_side = ft.Text("BAND", color=ColorConfig.TEXT_MAIN, width=LABEL_W)
        self.lbl_scs_side = ft.Text("SCS", color=ColorConfig.TEXT_MAIN, width=LABEL_W)

        # 动态标签：锁小区显示 (小屏使用)
        self.lbl_pci_top = ft.Text("PCI", color=ColorConfig.TEXT_MAIN, visible=False)
        self.lbl_earfcn_top = ft.Text("ARFCN", color=ColorConfig.TEXT_MAIN, visible=False)
        self.lbl_band_top = ft.Text("BAND", color=ColorConfig.TEXT_MAIN, visible=False)
        self.lbl_scs_top = ft.Text("SCS", color=ColorConfig.TEXT_MAIN, visible=False)

        # 构建支持动态切换的结构：外层是列 (Column)，内层是行 (Row)
        row_pci = ft.Column([self.lbl_pci_top, ft.Row([self.lbl_pci_side, self.cell_pci], spacing=10)], spacing=2)
        row_earfcn = ft.Column([self.lbl_earfcn_top, ft.Row([self.lbl_earfcn_side, self.cell_earfcn], spacing=10)], spacing=2)
        row_band = ft.Column([self.lbl_band_top, ft.Row([self.lbl_band_side, self.cell_band], spacing=10)], spacing=2)
        row_scs = ft.Column([self.lbl_scs_top, ft.Row([self.lbl_scs_side, self.cell_scs], spacing=10)], spacing=2)
        cell_tip = ft.Text("设备重启后生效", size=13, color=ColorConfig.TEXT_SEC, text_align=ft.TextAlign.CENTER)
        
        btn_cell_apply = create_button("应用锁小区", on_click=self.on_cell_lock)
        btn_cell_unlock = create_button("清除锁定", on_click=self.on_cell_unlock, expand=True)
        btn_cell_reboot = create_button("重启设备", on_click=self.on_reboot_device, expand=True)

        self.content = ft.Column([
            ft.Text("高级网络设置", size=18, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            ft.Divider(height=10, color=ColorConfig.DIVIDER_COLOR),
            ft.Text("WiFi 省电休眠", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            self.wifi_sleep, btn_wifi_sleep, ft.Container(height=15),
            
            # 网络模式锁定，数据连接开关
            ft.Text("网络模式锁定", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            ft.Row([self.data_switch, ft.Text("数据连接", color=ColorConfig.SWITCH_LABEL)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            net_mode_grid, btn_net_mode_apply, ft.Container(height=15),
            
            ft.Column([
                ft.Text("网络频段锁定", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
                ft.Text("每项至少保留一个频段", size=12, color=ColorConfig.TEXT_SEC)
            ], spacing=2),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            ft.Text("4G LTE 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            lte_grid, btn_lte_apply, ft.Container(height=10),
            ft.Text("5G SA 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            sa_grid, btn_sa_apply, ft.Container(height=10),
            ft.Text("5G NSA 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            nsa_grid, btn_nsa_apply, ft.Container(height=10),
            ft.Text("5G 锁定小区", size=14, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            row_pci, row_earfcn, row_band, row_scs, cell_tip, btn_cell_apply,
            ft.Row([btn_cell_unlock, btn_cell_reboot], spacing=10),
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

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
            if len(parts) >= 4:
                self.cell_pci.value = parts[0].strip()
                self.cell_earfcn.value = parts[1].strip()
                if any(o.key == parts[2].strip() for o in self.cell_band.options): self.cell_band.value = parts[2].strip()
                if any(o.key == parts[3].strip() for o in self.cell_scs.options): self.cell_scs.value = parts[3].strip()
        else:
            self.cell_pci.value = ""
            self.cell_earfcn.value = ""
            self.cell_band.value = "1"
            self.cell_scs.value = "15"
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

   # 界面交互代码
    async def on_data_switch_change(self, e):
        self.is_switching_data = True
        is_on = self.data_switch.value
        show_toast(self.app_page, f"正在{'开启' if is_on else '关闭'}数据连接...", True)
        try:
            cmd = "CONNECT_NETWORK" if is_on else "DISCONNECT_NETWORK"
            ok = await self.api_client.post_cmd(cmd, {"notCallback": "true"})
            if ok:
                self.set_global_status(f"数据连接已{'开启' if is_on else '关闭'}", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, f"数据已{'开启' if is_on else '关闭'}", True)
            else:
                self.set_global_status("数据状态切换失败", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "数据状态切换失败", False)
                self.data_switch.value = not is_on
        except Exception:
            self.set_global_status("数据状态切换异常", ColorConfig.ERROR_COLOR)
            show_toast(self.app_page, "数据状态切换异常", False)
            self.data_switch.value = not is_on
        finally:
            self.is_switching_data = False
            self.update()

    async def on_wifi_sleep_save(self, e):
        try:
            if await self.api_client.post_cmd("SET_WIFI_SLEEP_INFO", {"sysIdleTimeToSleep": self.wifi_sleep.value}):
                self.set_global_status("WiFi 休眠设置已保存", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "WiFi 休眠设置保存成功", True)
            else:
                self.set_global_status("保存失败", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "WiFi 休眠设置保存失败", False)
        except Exception:
            self.set_global_status("保存失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_apply_lte(self, e):
        if not self.lte_selected:
            show_toast(self.app_page, "请至少勾选一个 4G 频段", False)
            return
        try:
            ok = await self.api_client.post_cmd("BAND_SELECT", {
                "is_gw_band": "0", "gw_band_mask": "0",
                "is_lte_band": "1", "lte_band_mask": lte_bands_to_mask(list(self.lte_selected))
            })
            if ok:
                self.set_global_status("4G 频段设置完成", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "4G 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者权限已解锁", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "4G 频段设置失败，请确认开发者权限", False)
        except Exception:
            self.set_global_status("设置失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_apply_sa(self, e):
        if not self.nr_sa_selected:
            show_toast(self.app_page, "请至少勾选一个 5G SA 频段", False)
            return
        try:
            ok = await self.api_client.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
                "nr5g_band_mask": ",".join(sorted(self.nr_sa_selected, key=int)), "type": "0"
            })
            if ok:
                self.set_global_status("5G SA 频段设置完成", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "5G SA 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者权限已解锁", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "5G SA 频段设置失败，请确认开发者权限", False)
        except Exception:
            self.set_global_status("设置失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_apply_nsa(self, e):
        if not self.nr_nsa_selected:
            show_toast(self.app_page, "请至少勾选一个 5G NSA 频段", False)
            return
        try:
            ok = await self.api_client.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
                "nr5g_band_mask": ",".join(sorted(self.nr_nsa_selected, key=int)), "type": "1"
            })
            if ok:
                self.set_global_status("5G NSA 频段设置完成", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "5G NSA 频段设置成功", True)
            else:
                self.set_global_status("设置失败，请确认开发者权限已解锁", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "5G NSA 频段设置失败，请确认开发者权限", False)
        except Exception:
            self.set_global_status("设置失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_cell_lock(self, e):
        if not self.cell_pci.value or not self.cell_earfcn.value:
            show_toast(self.app_page, "请填写 PCI 与 ARFCN", False)
            return
        lock_val = f"{self.cell_pci.value.strip()},{self.cell_earfcn.value.strip()},{self.cell_band.value},{self.cell_scs.value}"
        try:
            if await self.api_client.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": lock_val}):
                self.set_global_status("锁小区配置下发完成", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "锁小区成功", True)
            else:
                self.set_global_status("锁小区失败，请确认开发者权限已解锁", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "锁小区失败，请确认开发者权限", False)
        except Exception:
            self.set_global_status("锁小区失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_cell_unlock(self, e):
        try:
            if await self.api_client.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": "1,1,1,1"}):
                self.cell_pci.value = ""
                self.cell_earfcn.value = ""
                self.cell_band.value = "1"
                self.cell_scs.value = "15"
                self.set_global_status("小区锁定已解除", ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, "小区锁定已解除", True)
            else:
                self.set_global_status("解除失败，请确认开发者权限已解锁", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "解除锁定失败", False)
        except Exception:
            self.set_global_status("解除失败", ColorConfig.ERROR_COLOR)
        self.update()

    async def on_apply_net_mode(self, e):
        selected_val = "WL_AND_5G"
        for name, cb in self.net_mode_cbs.items():
            if cb.value:
                selected_val = NET_CONFIG[name]["write_val"]
                break
        show_toast(self.app_page, "正在下发网络锁定配置...", True)
        try:
            # 记录切换前的数据连接状态，以决定切换完后是否自动重连
            was_connected = self.data_switch.value

            # 先断开数据连接
            await self.api_client.post_cmd("DISCONNECT_NETWORK", {"notCallback": "true"})
            await asyncio.sleep(NET_SWITCH_DELAY)
            
            # 写入网络模式配置
            ok_set = await self.api_client.post_cmd("SET_BEARER_PREFERENCE", {API_KEY_WRITE: selected_val})
            
            # 已连接时重连网络
            if was_connected:
                await asyncio.sleep(NET_SWITCH_DELAY)
                ok_connect = await self.api_client.post_cmd("CONNECT_NETWORK", {"notCallback": "true"})
                success = ok_set and ok_connect
            else:
                success = ok_set

            if success:
                if was_connected:
                    status_msg = "网络模式切换成功（请等待 5 秒后刷新状态）"
                    toast_msg = "网络切换成功，再次切换需等待 5 秒"
                else:
                    status_msg = "网络模式配置已下发，需手动重连生效"
                    toast_msg = "配置已保存，未改动数据连接状态"
                self.set_global_status(status_msg, ColorConfig.ACCENT_COLOR)
                show_toast(self.app_page, toast_msg, True)
            else:
                self.set_global_status("设置失败（配置未生效或操作期间被挤下线）", ColorConfig.ERROR_COLOR)
                show_toast(self.app_page, "网络切换失败（可能被挤下线）", False)
        except httpx.RequestError:
            self.set_global_status("网络连接异常", ColorConfig.ERROR_COLOR)
            show_toast(self.app_page, "网络连接异常", False)
        except Exception:
            self.set_global_status("设置失败", ColorConfig.ERROR_COLOR)
            show_toast(self.app_page, "网络切换失败", False)
        self.update()

# ==========================================
# 主程序：UI 构建 + 业务逻辑
# ==========================================
# Flet 应用主入口，负责页面初始化、状态管理、UI 构建与事件绑定
async def main(page: ft.Page):
    logger.info("应用启动，初始化主页面")
    # 页面基础设置
    page.theme = ft.Theme(font_family="Source Han Sans SC, Noto Sans SC, Microsoft YaHei, sans-serif")
    page.title = "MU5001"
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = ColorConfig.BG_COLOR
    # 全局状态
    device_state = DeviceState()
    client = MU5001Client(device_state)

    # 使用 SharedPreferences 加载方案
    prefs = None
    try:
        prefs = ft.SharedPreferences()
    except Exception as e:
        logger.warning(f"SharedPreferences 初始化失败: {e}")
        
    auto_refresh_task: Optional[asyncio.Task] = None

    # 操作事件：设备重启（传递给相关组件）
    async def on_reboot_device(e):
        show_toast(page, "正在发送重启指令...", True)
        try:
            if await client.post_cmd("REBOOT_DEVICE"):
                status_card.set_global_status("重启指令已发送，设备即将重启", ColorConfig.ACCENT_COLOR)
                show_toast(page, "设备即将重启", True)
            else:
                status_card.set_global_status("重启失败", ColorConfig.ERROR_COLOR)
                show_toast(page, "设备重启失败", False)
        except Exception:
            status_card.set_global_status("重启失败", ColorConfig.ERROR_COLOR)
            show_toast(page, "设备重启失败", False)

    # 初始化 UI 组件
    login_view = LoginView(page, client, prefs, on_login_success=lambda: on_login_success_handler())
    status_card = StatusCard()
    reboot_card = RebootCard(page, client, set_global_status_cb=status_card.set_global_status)
    settings_card = SettingsCard(page, client, set_global_status_cb=status_card.set_global_status, on_reboot_cb=on_reboot_device)
    
    # 自动刷新任务
    # 启动后台自动刷新任务，保证单例运行
    def start_auto_refresh():
        nonlocal auto_refresh_task
        if auto_refresh_task and not auto_refresh_task.done():
            auto_refresh_task.cancel()
        is_refreshing = False
        async def worker():
            nonlocal is_refreshing
            try:
                while True:
                    await asyncio.sleep(AUTO_REFRESH_INTERVAL)
                    if not (device_state.client and main_view.visible):
                        continue
                    if is_refreshing:
                        continue
                    is_refreshing = True
                    try:
                        await fetch_realtime()
                    except Exception as e:
                        logger.debug(f"后台刷新异常: {e}")
                    finally:
                        is_refreshing = False
            except asyncio.CancelledError:
                logger.info("自动刷新任务已停止")
        auto_refresh_task = asyncio.create_task(worker())
        logger.info("自动刷新任务已启动")

    # 数据读取（异步） 
    # 拉取实时运行状态并更新 UI
    async def fetch_realtime():
        if not device_state.client:
            return
        try:
            cmd = (
                "battery_value,battery_charging,network_type,wan_ipaddr,Z5g_rsrp,Z5g_SINR,"
                "nr5g_pci,nr5g_action_channel,pm_sensor_mdm,battery_temp,pm_sensor_pa1,"
                "realtime_tx_thrpt,realtime_rx_thrpt,realtime_tx_bytes,realtime_rx_bytes,"
                "monthly_tx_bytes,monthly_rx_bytes,wan_active_band,nr5g_action_band,"
                "wan_active_channel,lte_pci,lte_rsrp,lte_snr,cell_id,Z5g_Cell_ID,"
                "nr5g_cell_id,network_provider,realtime_time,lte_rsrq,Z5g_rsrq,lte_rssi,"
                "Z5g_rssi,nr5g_rssi,ppp_status"
            )
            res = await client.get_cmd(cmd, multi_data=True)
            
            # 接入设备数（MAC 去重）
            macs_count = None
            try:
                wifi_res = await client.get_cmd("station_list")
                lan_res = await client.get_cmd("lan_station_list")
                macs = {
                    d.get("mac_addr", "").strip().upper()
                    for d in wifi_res.get("station_list", []) + lan_res.get("lan_station_list", [])
                    if d.get("mac_addr")
                }
                macs_count = len(macs)
            except Exception:
                pass

            reboot_card.update_time_display()
            status_card.update_realtime(res, macs_count)
            settings_card.update_realtime(res)
        except Exception as e:
            logger.debug(f"实时刷新异常: {e}")

    # 全量读取设备配置并同步到 UI
    async def refresh_all(e=None):
        if not device_state.client:
            return
        status_card.set_global_status("正在读取设备信息...", ColorConfig.TEXT_MAIN)
        try:
            cmd = (
                "sysIdleTimeToSleep,lte_band_lock,nr5g_sa_band_lock,nr5g_nsa_band_lock,"
                "nr5g_cell_lock,reboot_schedule_enable,reboot_schedule_mode,reboot_hour1,"
                "reboot_min1,reboot_timeframe_hours1,reboot_dow,reboot_dod"
            )
            res = await client.get_cmd(cmd, multi_data=True)
            sa_res = await client.get_cmd("nr5g_sa_band_lock")
            nsa_res = await client.get_cmd("nr5g_nsa_band_lock")
            net_res = await client.get_cmd(API_KEY_READ)
            current_net_mode = str(net_res.get(API_KEY_READ, "")).strip().upper()
            # 将数据分发给各个组件进行状态更新
            reboot_card.update_config(res)
            settings_card.update_config(
                res, 
                sa_res.get("nr5g_sa_band_lock", ""), 
                nsa_res.get("nr5g_nsa_band_lock", ""), 
                current_net_mode
            )
            # 状态提示
            dev_status = " | 开发者已解锁" if device_state.dev_unlocked else " | 开发者未解锁"
            status_card.set_global_status("数据读取成功" + dev_status, ColorConfig.ACCENT_COLOR if device_state.dev_unlocked else ColorConfig.ERROR_COLOR)
            await fetch_realtime()
            if e:
                show_toast(page, "数据刷新成功", True)
            logger.info("全量配置刷新完成")
        except Exception:
            status_card.set_global_status("读取失败，请检查连接", ColorConfig.ERROR_COLOR)
            if e:
                show_toast(page, "数据读取失败，请检查连接", False)

    # 核心操作执行逻辑（登录/退出/刷新）
    async def on_login_success_handler():
        login_view.visible = False
        main_view.visible = True
        page.update()
        await refresh_all()
        start_auto_refresh()

    async def do_relogin(e):
        if not device_state.ip or not device_state.password:
            show_toast(page, "本地无缓存密码，请重启 APP", False)
            return
        show_toast(page, "正在重登...", True)
        try:
            success = await client.login(device_state.ip, device_state.password)
            if success:
                dev_ok = await client.unlock_developer()
                
                # 重登成功后，默认发送打开数据连接指令
                try:
                    await client.post_cmd("CONNECT_NETWORK", {"notCallback": "true"})
                    settings_card.data_switch.value = True
                    settings_card.update()
                except Exception as conn_err:
                    logger.warning(f"重登后自动开启数据连接失败: {conn_err}")
                # ======================================================

                if dev_ok:
                    status_card.set_global_status("重登成功并已解锁开发者权限", ColorConfig.ACCENT_COLOR)
                    show_toast(page, "重登成功，开发者解锁成功，已尝试开启数据", True)
                else:
                    status_card.set_global_status("重登成功，开发者解锁失败", ColorConfig.ERROR_COLOR)
                    show_toast(page, "重登成功，但开发者解锁失败", False)
                await refresh_all()
            else:
                status_card.set_global_status("重新登录失败，可能密码已修改或被锁定", ColorConfig.ERROR_COLOR)
                show_toast(page, "重登失败", False)
        except Exception:
            status_card.set_global_status("重登连接失败，请检查网络", ColorConfig.ERROR_COLOR)
            show_toast(page, "连接失败，请检查网络", False)

    async def do_logout(e):
        await client.close()
        nonlocal auto_refresh_task
        if auto_refresh_task and not auto_refresh_task.done():
            auto_refresh_task.cancel()
            auto_refresh_task = None
        device_state.dev_unlocked = False
        await login_view.clear_credentials_and_reset()
        main_view.visible = False
        login_view.visible = True
        show_toast(page, "已安全退出登录", True)
        page.update()

    # ==========================================
    # 主视图 (吸顶布局) 
    # ==========================================
    logout_btn = create_button("退出", on_click=do_logout, height=36)
    logout_btn.style.bgcolor = ColorConfig.TOP_BTN_BG
    logout_btn.style.color = ColorConfig.TOP_BTN_TEXT
    
    relogin_btn = create_button("重登", on_click=do_relogin, height=36)
    relogin_btn.style.bgcolor = ColorConfig.TOP_BTN_BG
    relogin_btn.style.color = ColorConfig.TOP_BTN_TEXT

    header_text = ft.Text(
        "设备状态", 
        size=20, 
        weight=ft.FontWeight.BOLD, 
        text_align=ft.TextAlign.CENTER, 
        expand=True, 
        color=ColorConfig.TEXT_MAIN,
        no_wrap=True,                     
        max_lines=1,                      
        overflow=ft.TextOverflow.ELLIPSIS 
    )

    sticky_header = ft.Container(
        content=ft.Row(
            [logout_btn, header_text, relogin_btn],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER
        )
    )

    btn_refresh = create_button("刷新数据", on_click=refresh_all, expand=True)
    btn_reboot_top = create_button("重启设备", on_click=on_reboot_device, expand=True)

    # 可滑动的内容区域
    scrollable_content = ft.Column(
        [
            status_card,
            ft.Row([btn_refresh, btn_reboot_top], spacing=10),
            ft.Container(height=10),
            reboot_card,
            ft.Container(height=10),
            settings_card,
            ft.Container(height=30)
        ],
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        scroll=ft.ScrollMode.AUTO,
        expand=True 
    )

    # 提取占位容器为变量，方便后续暴力压缩
    top_spacer = ft.Container(height=25)
    header_gap = ft.Container(height=10)

    main_view = ft.Container(
        padding=15,  
        expand=True,
        visible=False,
        content=ft.Column(
            [
                top_spacer,              
                sticky_header,           
                header_gap,
                scrollable_content       
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=0,
            expand=True 
        )
    )

    # ==========================================
    # 全局响应式缩放方案
    # ==========================================
    _orig_states = {}

    def on_page_resize(e):
        if page.width <= 0: 
            return

        #缩放临界值 340dp
        is_small = page.width < 340
        
        # 小屏状态同步给 StatusCard
        status_card.is_small = is_small
        
        # 缩放基准调整为 360dp
        scale = max(0.6, page.width / 360) if is_small else 1.0

        def scale_node(ctrl):
            if not ctrl: return
            
            cid = id(ctrl)
            if cid not in _orig_states:
                _orig_states[cid] = {}
            state = _orig_states[cid]

            # 1. 纯文本
            if isinstance(ctrl, ft.Text):
                if "size" not in state: state["size"] = ctrl.size or 14
                ctrl.size = max(11, int(state["size"] * scale))

            # 2. 输入框和下拉菜单
            elif isinstance(ctrl, (ft.TextField, ft.Dropdown)):
                if "text_size" not in state: state["text_size"] = ctrl.text_size or 14
                ctrl.text_size = int(state["text_size"] * scale)
                
                if hasattr(ctrl, "label_style") and ctrl.label_style:
                    lid = id(ctrl.label_style)
                    if lid not in _orig_states: _orig_states[lid] = {"size": ctrl.label_style.size or 14}
                    ctrl.label_style.size = max(10, int(_orig_states[lid]["size"] * scale))
                
                # 动态简化标签，防止拥挤
                if getattr(ctrl, "label", "") in ["缓冲时间", "缓冲"]:
                    # 只有宽度小于 340 才简化为"缓冲"，实机保持"缓冲时间"
                    ctrl.label = "缓冲" if is_small else "缓冲时间"
                    
                ctrl.content_padding = None 

            # 3. 按钮
            elif type(ctrl).__name__ in ["Button", "ElevatedButton"]:
                if not ctrl.style: ctrl.style = ft.ButtonStyle()
                if not ctrl.style.text_style: ctrl.style.text_style = ft.TextStyle()
                
                if "btn_text_size" not in state: state["btn_text_size"] = ctrl.style.text_style.size or 14
                if "height" not in state: state["height"] = ctrl.height
                
                ctrl.style.text_style.size = max(12, int(state["btn_text_size"] * scale))
                ctrl.style.padding = None 
                
                if state["height"]:
                    ctrl.height = max(36, int(state["height"] * scale)) if is_small else state["height"]

            # 4. 单选框和开关
            elif isinstance(ctrl, (ft.Checkbox, ft.Switch)):
                if "scale" not in state: state["scale"] = ctrl.scale or 1.0
                ctrl.scale = state["scale"] * scale

            # 5. 容器
            elif isinstance(ctrl, ft.Container):
                if "padding" not in state: state["padding"] = ctrl.padding
                if isinstance(state["padding"], (int, float)):
                    ctrl.padding = max(4, int(state["padding"] * scale)) if is_small else state["padding"]
                
                if "height" not in state: state["height"] = ctrl.height
                if isinstance(state["height"], (int, float)) and state["height"] > 0:
                     ctrl.height = int(state["height"] * scale) if is_small else state["height"]

            # 6. 排版布局
            elif isinstance(ctrl, (ft.Row, ft.Column)):
                if "spacing" not in state: state["spacing"] = ctrl.spacing or 10
                ctrl.spacing = max(2, int(state["spacing"] * scale)) if is_small else state["spacing"]

            # --- 递归套娃执行 ---
            if hasattr(ctrl, "content") and ctrl.content:
                scale_node(ctrl.content)
            if hasattr(ctrl, "controls") and ctrl.controls:
                for child in ctrl.controls:
                    scale_node(child)

        # 启动全局扫描
        for view in page.controls:
            scale_node(view)

        # ==========================================================           
        # 强制接管外围和顶部边距 
        # ==========================================================
        top_spacer.height = 0 if is_small else 25      
        header_gap.height = 2 if is_small else 10      
        main_view.padding = 2 if is_small else 15      
        
        # 动态控制锁小区表单标签 (保留大屏左右，小屏上下的布局)
        settings_card.lbl_pci_side.visible = not is_small
        settings_card.lbl_pci_top.visible = is_small
        settings_card.lbl_earfcn_side.visible = not is_small
        settings_card.lbl_earfcn_top.visible = is_small
        settings_card.lbl_band_side.visible = not is_small
        settings_card.lbl_band_top.visible = is_small
        settings_card.lbl_scs_side.visible = not is_small
        settings_card.lbl_scs_top.visible = is_small

        # ==========================================================
        # 动态控制定时重启排版 (仅在 340 以下的情况才换行)
        # ==========================================================
        current_is_col = isinstance(reboot_card.time_container.content, ft.Column)
        
        if is_small and not current_is_col:
            # 极限小屏 (< 340)：取消 expand，改为竖排 Column
            reboot_card.rb_time_hr.expand = False
            reboot_card.rb_time_min.expand = False
            reboot_card.rb_buffer.expand = False
            reboot_card.time_container.content = ft.Column(
                [reboot_card.rb_time_hr, reboot_card.rb_time_min, reboot_card.rb_buffer],
                spacing=5
            )
        elif not is_small and current_is_col:
            # 正常 (>= 340)：恢复完美的横排 Row 
            reboot_card.rb_time_hr.expand = 1
            reboot_card.rb_time_min.expand = 1
            reboot_card.rb_buffer.expand = 1
            reboot_card.time_container.content = ft.Row(
                [reboot_card.rb_time_hr, reboot_card.rb_time_min, reboot_card.rb_buffer],
                spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER
            )

        # ==========================================================
        # 顶部吸顶栏小屏时防溢出
        # ==========================================================
        if is_small:
            if logout_btn.style: logout_btn.style.padding = ft.Padding.symmetric(horizontal=8, vertical=0)
            if relogin_btn.style: relogin_btn.style.padding = ft.Padding.symmetric(horizontal=8, vertical=0)
            logout_btn.height = 26
            relogin_btn.height = 26
            if logout_btn.style.text_style: logout_btn.style.text_style.size = 12
            if relogin_btn.style.text_style: relogin_btn.style.text_style.size = 12
            header_text.visible = False if page.width < 260 else True
        else:
            if logout_btn.style: logout_btn.style.padding = None
            if relogin_btn.style: relogin_btn.style.padding = None
            logout_btn.height = 36
            relogin_btn.height = 36
            if logout_btn.style.text_style: logout_btn.style.text_style.size = 14
            if relogin_btn.style.text_style: relogin_btn.style.text_style.size = 14
            header_text.visible = True

        page.update()

    # 绑定监听
    page.on_resize = on_page_resize

    # 监听退出事件
    def on_disconnect(e):
        if auto_refresh_task and not auto_refresh_task.done():
            auto_refresh_task.cancel()
    page.on_disconnect = on_disconnect

    # 直接添加到 page 中，page 会准确计算 expand=True 的高度
    page.add(login_view, main_view)
    # 手动触发一次响应式排版
    if page.width > 0:
        on_page_resize(None)
    page.update()
    # 读取登录信息，尝试自动登录
    await login_view.init_from_storage()

if __name__ == "__main__":
    ft.run(main)
