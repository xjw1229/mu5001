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
DEBUG_MODE = False # 调试时设为 True或False 可开关输出完整调试信息
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
    ACCENT_COLOR = "#82A5E0"      # 主题强调色
    ERROR_COLOR = "#E08282"       # 错误、警告色
    DIVIDER_COLOR = "#2A2C3E"     # 分割线
    BTN_BG = "#535773"            # 普通按钮默认背景
    BTN_HOVER_BG = "#6A6F91"      # 普通按钮悬浮背景
    FAB_BG = "#82A5E0"            # 悬浮按钮背景
    FAB_ICON = "#FFFFFF"          # 悬浮按钮图标
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
DEFAULT_IP = "http://192.168.0.1"
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
    client: Optional[httpx.AsyncClient] = None  # httpx 异步客户端实例
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

        client = httpx.AsyncClient(http2=False, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"{ip}/index.html"
        })

        try:
            # 访问首页建立会话
            await client.get(f"{ip}/index.html", timeout=LOGIN_TIMEOUT)

            # 并发获取三个关键参数
            req_ver = client.get(
                f"{ip}/goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "Language,cr_version,wa_inner_version", "multi_data": "1"},
                timeout=LOGIN_TIMEOUT
            )
            req_ld = client.get(
                f"{ip}/goform/goform_get_cmd_process",
                params={"isTest": "false", "cmd": "LD"},
                timeout=LOGIN_TIMEOUT
            )
            req_rd = client.get(
                f"{ip}/goform/goform_get_cmd_process",
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

            # 计算密码与 AD 并登录
            pwd_enc = get_sha256_upper(get_sha256_upper(password) + ld)
            login_resp = await client.post(
                f"{ip}/goform/goform_set_cmd_process",
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
                self.state.ip = ip
                self.state.rd0 = rd0
                self.state.rd1 = rd1
                self.state.password = password
                logger.info(f"登录成功: {ip}")
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
    icon: Optional[str] = None,
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
    btn = BtnClass(text, on_click=on_click, height=height, icon=icon, style=btn_style)
    btn.expand = expand
    return btn

# 创建频段选择复选框网格
def create_checkbox_grid(
    bands: List[str],
    prefix: str,
    selected: Set[str],
    cb_map: Dict[str, ft.Checkbox],
    on_change: Callable
) -> ft.Row:
    controls = []
    for b in bands:
        cb = ft.Checkbox(
            label=f"{prefix}{b}",
            value=b in selected,
            data=b,
            on_change=on_change,
            label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN),
            fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
            check_color=ColorConfig.BG_COLOR
        )
        cb_map[b] = cb
        controls.append(ft.Container(content=cb, width=72, padding=0, margin=0))
    return ft.Row(controls, wrap=True, spacing=5, run_spacing=0)

# 在页面底部弹出浮动提示条
def show_toast(page: ft.Page, msg: str, success: bool = True) -> None:
    bg = ColorConfig.TOAST_SUCCESS_BG if success else ColorConfig.TOAST_ERROR_BG
    icon = "✅ " if success else "❌ "

    for c in list(page.overlay):
        if isinstance(c, ft.SnackBar):
            page.overlay.remove(c)
    
    snack = ft.SnackBar(
        content=ft.Text(f"{icon}{msg}", color=ColorConfig.TEXT_MAIN, weight=ft.FontWeight.BOLD),
        bgcolor=bg,
        duration=3000, 
        behavior=ft.SnackBarBehavior.FLOATING
    )
    
    page.overlay.append(snack)
    snack.open = True
    page.update()

# 构建「图标 + 内容」的标准状态行
def build_status_row(icon: str, content: ft.Control) -> ft.Row:
    content.expand = True
    return ft.Row(
        [
            ft.Text(icon, size=16, width=28, text_align=ft.TextAlign.CENTER, color=ColorConfig.ACCENT_COLOR),
            content
        ],
        spacing=5,
        vertical_alignment=ft.CrossAxisAlignment.START
    )

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
    prefs = ft.SharedPreferences()
    sec_style = ft.TextStyle(color=ColorConfig.TEXT_SEC)

    # 频段选中状态
    lte_selected: Set[str] = set(LTE_BANDS)
    nr_sa_selected: Set[str] = set(NR_SA_BANDS)
    nr_nsa_selected: Set[str] = set(NR_NSA_BANDS)
    lte_cbs: Dict[str, ft.Checkbox] = {}
    sa_cbs: Dict[str, ft.Checkbox] = {}
    nsa_cbs: Dict[str, ft.Checkbox] = {}
    net_mode_cbs: Dict[str, ft.Checkbox] = {}
    auto_refresh_task: Optional[asyncio.Task] = None

    #  复选框事件（纯 UI，同步）
    def on_lte_change(e):
        b = e.control.data
        if e.control.value:
            lte_selected.add(b)
        elif b in lte_selected:
            lte_selected.remove(b)

    def on_sa_change(e):
        b = e.control.data
        if e.control.value:
            nr_sa_selected.add(b)
        elif b in nr_sa_selected:
            nr_sa_selected.remove(b)

    def on_nsa_change(e):
        b = e.control.data
        if e.control.value:
            nr_nsa_selected.add(b)
        elif b in nr_nsa_selected:
            nr_nsa_selected.remove(b)

    # 网络模式单选：保证有且仅有一个选中
    def on_net_mode_change(e):
        if e.control.value:
            for cb in net_mode_cbs.values():
                if cb is not e.control:
                    cb.value = False
        else:
            e.control.value = True
        page.update()

    # 星期单选：保证仅选中一天
    def on_week_change(e):
        for cb in week_cbs:
            cb.value = (cb is e.control)
        page.update()

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
                "wan_active_channel,lte_pci,lte_rsrp,lte_snr"
            )
            res = await client.get_cmd(cmd, multi_data=True)

            # 网络与频段
            net_type = res.get('network_type', '?')
            lte_band = str(res.get('wan_active_band', '')).strip()
            nr_band = str(res.get('nr5g_action_band', '')).strip()
            is_5g = any(k in net_type.upper() for k in ['5G', 'SA', 'NSA'])
            band = nr_band if (is_5g and nr_band) else lte_band
            txt_network.value = f"网络: {net_type} ({band})" if band else f"网络: {net_type}"

            # 电池信息
            bat = str(res.get('battery_value', '?'))
            charge = "充电中" if str(res.get('battery_charging', '')) in ['1', '2'] else "未充电"
            txt_battery.value = f"电量: {bat}% ({charge})"

            # 基础网络信息
            txt_wan_ip.value = f"WAN IP: {res.get('wan_ipaddr', '未分配')}"
            txt_tx_speed.value = f"上传速度: {format_bytes(res.get('realtime_tx_thrpt', 0))}/s"
            txt_rx_speed.value = f"下载速度: {format_bytes(res.get('realtime_rx_thrpt', 0))}/s"

            rt_total = float(res.get("realtime_tx_bytes", 0)) + float(res.get("realtime_rx_bytes", 0))
            mo_total = float(res.get("monthly_tx_bytes", 0)) + float(res.get("monthly_rx_bytes", 0))
            txt_traffic_rt.value = f"本次流量: {format_bytes(rt_total)}"
            txt_traffic_mo.value = f"当月流量: {format_bytes(mo_total)}"

            # 射频信息
            freq_5g = str(res.get("nr5g_action_channel", "")).strip()
            freq_4g = str(res.get("wan_active_channel", "")).strip()
            txt_freq.value = f"频点: {freq_5g or freq_4g or '--'}"

            # PCI（物理小区标识）
            def parse_pci(raw):
                try:
                    return str(int(raw.strip(), 16)) if raw.strip() else ""
                except Exception:
                    return raw.strip()

            pci_5g = parse_pci(str(res.get("nr5g_pci", "")))
            pci_4g = parse_pci(str(res.get("lte_pci", "")))
            txt_pci.value = f"PCI: {pci_5g or pci_4g or '--'}"

            rsrp_5g = str(res.get('Z5g_rsrp', '')).strip()
            rsrp_4g = str(res.get('lte_rsrp', '')).strip()
            txt_rsrp.value = f"信号强度: {rsrp_5g or rsrp_4g or '--'} dBm"

            sinr_5g = str(res.get('Z5g_SINR', '')).strip()
            sinr_4g = str(res.get('lte_snr', '')).strip()
            txt_sinr.value = f"信噪比: {sinr_5g or sinr_4g or '--'} dB"

            # 温度
            txt_temp_bat.value = f"电池温度: {res.get('battery_temp', '--')}℃"
            txt_temp_mdm.value = f"4G Modem: {res.get('pm_sensor_mdm', '--')}℃"
            txt_temp_pa.value = f"PA: {res.get('pm_sensor_pa1', '--')}℃"

            # 接入设备数（MAC 去重）
            try:
                wifi_res = await client.get_cmd("station_list")
                lan_res = await client.get_cmd("lan_station_list")
                macs = {
                    d.get("mac_addr", "").strip().upper()
                    for d in wifi_res.get("station_list", []) + lan_res.get("lan_station_list", [])
                    if d.get("mac_addr")
                }
                txt_users.value = f"接入设备: {len(macs)} 台"
            except Exception:
                pass

            txt_local_time.value = f"设备当前时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            page.update()
        except Exception as e:
            logger.debug(f"实时刷新异常: {e}")

    # 全量读取设备配置并同步到 UI
    async def refresh_all(e=None):
        if not device_state.client:
            return
        status_text.value = "正在读取设备信息..."
        status_text.color = ColorConfig.TEXT_MAIN
        page.update()

        try:
            cmd = (
                "sysIdleTimeToSleep,lte_band_lock,nr5g_sa_band_lock,nr5g_nsa_band_lock,"
                "nr5g_cell_lock,reboot_schedule_enable,reboot_schedule_mode,reboot_hour1,"
                "reboot_min1,reboot_timeframe_hours1,reboot_dow,reboot_dod"
            )
            res = await client.get_cmd(cmd, multi_data=True)

            # WiFi 休眠
            sleep_val = res.get("sysIdleTimeToSleep", "10")
            if any(o.key == sleep_val for o in wifi_sleep.options):
                wifi_sleep.value = sleep_val

            # LTE 频段
            mask = res.get("lte_band_lock", "")
            if mask:
                lte_selected.clear()
                lte_selected.update(mask_to_lte_bands(mask))
            for b, cb in lte_cbs.items():
                cb.value = b in lte_selected

            # 5G SA 频段
            sa_res = await client.get_cmd("nr5g_sa_band_lock")
            sa_raw = sa_res.get("nr5g_sa_band_lock", "")
            if sa_raw:
                nr_sa_selected.clear()
                nr_sa_selected.update([b.strip() for b in sa_raw.split(",") if b.strip()])
            for b, cb in sa_cbs.items():
                cb.value = b in nr_sa_selected

            # 5G NSA 频段
            nsa_res = await client.get_cmd("nr5g_nsa_band_lock")
            nsa_raw = nsa_res.get("nr5g_nsa_band_lock", "")
            if nsa_raw:
                nr_nsa_selected.clear()
                nr_nsa_selected.update([b.strip() for b in nsa_raw.split(",") if b.strip()])
            for b, cb in nsa_cbs.items():
                cb.value = b in nr_nsa_selected

            # 锁小区配置
            cell_val = res.get("nr5g_cell_lock", "")
            if cell_val and cell_val != "1,1,1,1":
                parts = cell_val.split(",")
                if len(parts) >= 4:
                    cell_pci.value = parts[0].strip()
                    cell_earfcn.value = parts[1].strip()
                    if any(o.key == parts[2].strip() for o in cell_band.options):
                        cell_band.value = parts[2].strip()
                    if any(o.key == parts[3].strip() for o in cell_scs.options):
                        cell_scs.value = parts[3].strip()
            else:
                cell_pci.value = ""
                cell_earfcn.value = ""
                cell_band.value = "1"
                cell_scs.value = "15"

            # 定时重启配置
            reboot_enable.value = res.get("reboot_schedule_enable", "0") == "1"
            rb_mode = res.get("reboot_schedule_mode", "1")
            if rb_mode in ["1", "2"]:
                reboot_mode.value = rb_mode
            rb_time_hr.value = res.get("reboot_hour1", "02").zfill(2)
            rb_time_min.value = res.get("reboot_min1", "00").zfill(2)
            rb_buffer.value = res.get("reboot_timeframe_hours1", "02").zfill(2)

            weeks = [w.strip() for w in res.get("reboot_dow", "").split(",") if w.strip()]
            for cb in week_cbs:
                cb.value = cb.data in weeks

            dod = res.get("reboot_dod", "1")
            if any(o.key == dod for o in rb_interval.options):
                rb_interval.value = dod

            # 网络模式配置
            net_res = await client.get_cmd(API_KEY_READ)
            current = str(net_res.get(API_KEY_READ, "")).strip().upper()
            matched = False
            for name, cfg in NET_CONFIG.items():
                if current == cfg["read_val"].upper():
                    for cb in net_mode_cbs.values():
                        cb.value = False
                    net_mode_cbs[name].value = True
                    matched = True
                    break
            if not matched:
                for cb in net_mode_cbs.values():
                    cb.value = False
                net_mode_cbs["5G/4G/3G"].value = True

            # 状态提示
            dev_status = " | 开发者已解锁" if device_state.dev_unlocked else " | ⚠️ 开发者未解锁"
            status_text.value = "✅ 数据读取成功" + dev_status
            status_text.color = ColorConfig.ACCENT_COLOR if device_state.dev_unlocked else ColorConfig.ERROR_COLOR

            await fetch_realtime()
            if e:
                show_toast(page, "数据刷新成功", True)
            logger.info("全量配置刷新完成")

        except Exception:
            status_text.value = "⚠️ 读取失败，请检查连接"
            status_text.color = ColorConfig.ERROR_COLOR
            if e:
                show_toast(page, "数据读取失败，请检查连接", False)
            page.update()

    # 操作事件（异步）
    async def on_reboot(e):
        show_toast(page, "正在发送重启指令...", True)
        try:
            if await client.post_cmd("REBOOT_DEVICE"):
                status_text.value = "✅ 重启指令已发送，设备即将重启"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "设备即将重启", True)
            else:
                status_text.value = "❌ 重启失败"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "设备重启失败", False)
        except Exception:
            status_text.value = "❌ 重启失败"
            status_text.color = ColorConfig.ERROR_COLOR
            show_toast(page, "设备重启失败", False)
        page.update()

    async def on_wifi_sleep_save(e):
        try:
            if await client.post_cmd("SET_WIFI_SLEEP_INFO", {"sysIdleTimeToSleep": wifi_sleep.value}):
                status_text.value = "✅ WiFi 休眠设置已保存"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "WiFi 休眠设置保存成功", True)
            else:
                status_text.value = "❌ 保存失败"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "WiFi 休眠设置保存失败", False)
        except Exception:
            status_text.value = "❌ 保存失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_apply_lte(e):
        if not lte_selected:
            show_toast(page, "⚠️ 请至少勾选一个 4G 频段", False)
            return
        try:
            ok = await client.post_cmd("BAND_SELECT", {
                "is_gw_band": "0", "gw_band_mask": "0",
                "is_lte_band": "1", "lte_band_mask": lte_bands_to_mask(list(lte_selected))
            })
            if ok:
                status_text.value = "✅ 4G 频段设置完成"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "4G 频段设置成功", True)
            else:
                status_text.value = "❌ 设置失败，请确认开发者权限已解锁"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "4G 频段设置失败，请确认开发者权限", False)
        except Exception:
            status_text.value = "❌ 设置失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_apply_sa(e):
        if not nr_sa_selected:
            show_toast(page, "⚠️ 请至少勾选一个 5G SA 频段", False)
            return
        try:
            ok = await client.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
                "nr5g_band_mask": ",".join(sorted(nr_sa_selected, key=int)),
                "type": "0"
            })
            if ok:
                status_text.value = "✅ 5G SA 频段设置完成"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "5G SA 频段设置成功", True)
            else:
                status_text.value = "❌ 设置失败，请确认开发者权限已解锁"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "5G SA 频段设置失败，请确认开发者权限", False)
        except Exception:
            status_text.value = "❌ 设置失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_apply_nsa(e):
        if not nr_nsa_selected:
            show_toast(page, "⚠️ 请至少勾选一个 5G NSA 频段", False)
            return
        try:
            ok = await client.post_cmd("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {
                "nr5g_band_mask": ",".join(sorted(nr_nsa_selected, key=int)),
                "type": "1"
            })
            if ok:
                status_text.value = "✅ 5G NSA 频段设置完成"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "5G NSA 频段设置成功", True)
            else:
                status_text.value = "❌ 设置失败，请确认开发者权限已解锁"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "5G NSA 频段设置失败，请确认开发者权限", False)
        except Exception:
            status_text.value = "❌ 设置失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_cell_lock(e):
        if not cell_pci.value or not cell_earfcn.value:
            show_toast(page, "⚠️ 请填写 PCI 与 EARFCN", False)
            return
        lock_val = f"{cell_pci.value.strip()},{cell_earfcn.value.strip()},{cell_band.value},{cell_scs.value}"
        try:
            if await client.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": lock_val}):
                status_text.value = "✅ 锁小区配置下发完成"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "锁小区成功", True)
            else:
                status_text.value = "❌ 锁小区失败，请确认开发者权限已解锁"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "锁小区失败，请确认开发者权限", False)
        except Exception:
            status_text.value = "❌ 锁小区失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_cell_unlock(e):
        try:
            if await client.post_cmd("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": "1,1,1,1"}):
                cell_pci.value = ""
                cell_earfcn.value = ""
                cell_band.value = "1"
                cell_scs.value = "15"
                status_text.value = "✅ 小区锁定已解除"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "小区锁定已解除", True)
            else:
                status_text.value = "❌ 解除失败，请确认开发者权限已解锁"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "解除锁定失败", False)
        except Exception:
            status_text.value = "❌ 解除失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_save_reboot(e):
        weeks = ",".join([cb.data for cb in week_cbs if cb.value])
        payload = {
            "reboot_schedule_enable": "1" if reboot_enable.value else "0",
            "reboot_schedule_mode": reboot_mode.value,
            "reboot_hour1": rb_time_hr.value.zfill(2),
            "reboot_hour2": rb_time_hr.value.zfill(2),
            "reboot_min1": rb_time_min.value.zfill(2),
            "reboot_min2": rb_time_min.value.zfill(2),
            "reboot_timeframe_hours1": rb_buffer.value.zfill(2),
            "reboot_timeframe_hours2": rb_buffer.value.zfill(2),
            "reboot_dow": weeks,
            "reboot_dod": rb_interval.value
        }
        try:
            if await client.post_cmd("FIX_TIME_REBOOT_SCHEDULE", payload):
                status_text.value = "✅ 定时重启配置已保存"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "定时重启配置保存成功，请确保已开启功能", True)
            else:
                status_text.value = "❌ 保存失败，请检查连接状态"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "定时重启配置保存失败，请确保已开启功能", False)
        except Exception:
            status_text.value = "❌ 保存失败"
            status_text.color = ColorConfig.ERROR_COLOR
        page.update()

    async def on_apply_net_mode(e):
        selected_val = "WL_AND_5G"
        for name, cb in net_mode_cbs.items():
            if cb.value:
                selected_val = NET_CONFIG[name]["write_val"]
                break

        show_toast(page, "正在下发网络锁定配置...", True)
        try:
            await client.post_cmd("DISCONNECT_NETWORK", {"notCallback": "true"})
            await asyncio.sleep(NET_SWITCH_DELAY)

            ok_set = await client.post_cmd("SET_BEARER_PREFERENCE", {API_KEY_WRITE: selected_val})
            await asyncio.sleep(NET_SWITCH_DELAY)

            ok_connect = await client.post_cmd("CONNECT_NETWORK", {"notCallback": "true"})

            if ok_set and ok_connect:
                status_text.value = "✅ 网络模式切换成功（请等待 5 秒后刷新状态）"
                status_text.color = ColorConfig.ACCENT_COLOR
                show_toast(page, "网络切换成功，再次切换需等待 5 秒", True)
            else:
                status_text.value = "❌ 设置失败（配置未生效或操作期间被挤下线）"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "网络切换失败（可能被挤下线）", False)
        except httpx.RequestError:
            status_text.value = "❌ 网络连接异常"
            status_text.color = ColorConfig.ERROR_COLOR
            show_toast(page, "网络连接异常", False)
        except Exception:
            status_text.value = "❌ 设置失败"
            status_text.color = ColorConfig.ERROR_COLOR
            show_toast(page, "网络切换失败", False)
        page.update()

    # 登录 / 重登 / 登出
    async def do_login(e=None):
        ip = ip_input.value
        pwd = pwd_input.value
        if not pwd:
            login_status.value = "⚠️ 请输入密码"
            login_status.color = ColorConfig.ERROR_COLOR
            page.update()
            return

        login_btn.disabled = True
        login_status.value = "正在验证登录..."
        login_status.color = ColorConfig.TEXT_SEC
        page.update()
        await asyncio.sleep(0.05)

        try:
            success = await client.login(ip, pwd)
            if success:
                # 保存凭据
                if remember_cb.value and prefs:
                    try:
                        if hasattr(prefs, "set_async"):
                            await prefs.set_async("saved_ip", ip)
                            await prefs.set_async("saved_pwd", pwd)
                        else:
                            await prefs.set("saved_ip", ip)
                            await prefs.set("saved_pwd", pwd)
                    except Exception:
                        pass

                login_status.value = "解锁开发者权限..."
                page.update()
                await client.unlock_developer()

                login_view.visible = False
                main_view.visible = True
                fab_container.visible = True

                await refresh_all()
                show_toast(page, "登录成功", True)
                start_auto_refresh()
            else:
                # 失败则清除保存的凭据
                if prefs:
                    try:
                        if hasattr(prefs, "remove_async"):
                            await prefs.remove_async("saved_ip")
                            await prefs.remove_async("saved_pwd")
                        else:
                            await prefs.remove("saved_ip")
                            await prefs.remove("saved_pwd")
                    except Exception:
                        pass
                remember_cb.value = False
                pwd_input.value = ""
                login_status.value = "❌ 密码错误或账号锁定"
                login_status.color = ColorConfig.ERROR_COLOR
                show_toast(page, "密码错误或账号锁定", False)
        except Exception:
            if prefs:
                try:
                    if hasattr(prefs, "remove_async"):
                        await prefs.remove_async("saved_ip")
                        await prefs.remove_async("saved_pwd")
                    else:
                        await prefs.remove("saved_ip")
                        await prefs.remove("saved_pwd")
                except Exception:
                    pass
            remember_cb.value = False
            login_status.value = "❌ 连接失败，请检查地址和网络"
            login_status.color = ColorConfig.ERROR_COLOR
            show_toast(page, "连接失败，请检查地址和网络", False)

        login_btn.disabled = False
        page.update()

    async def do_relogin(e):
        if not device_state.ip or not device_state.password:
            show_toast(page, "本地无缓存密码，请重启 APP", False)
            return
        show_toast(page, "正在重登...", True)
        try:
            success = await client.login(device_state.ip, device_state.password)
            if success:
                dev_ok = await client.unlock_developer()
                if dev_ok:
                    status_text.value = "✅ 重登成功并已解锁开发者权限"
                    status_text.color = ColorConfig.ACCENT_COLOR
                    show_toast(page, "重登成功，开发者解锁成功", True)
                else:
                    status_text.value = "⚠️ 重登成功，开发者解锁失败"
                    status_text.color = ColorConfig.ERROR_COLOR
                    show_toast(page, "重登成功，开发者解锁失败", False)
                await refresh_all()
            else:
                status_text.value = "❌ 重新登录失败，可能密码已修改或被锁定"
                status_text.color = ColorConfig.ERROR_COLOR
                show_toast(page, "重登失败", False)
        except Exception:
            status_text.value = "❌ 重登连接失败，请检查网络"
            status_text.color = ColorConfig.ERROR_COLOR
            show_toast(page, "连接失败，请检查网络", False)
        page.update()

    async def do_logout(e):
        await client.close()

        nonlocal auto_refresh_task
        if auto_refresh_task and not auto_refresh_task.done():
            auto_refresh_task.cancel()
            auto_refresh_task = None

        device_state.dev_unlocked = False

        # 清除保存的凭据
        if prefs:
            try:
                if hasattr(prefs, "remove_async"):
                    await prefs.remove_async("saved_ip")
                    await prefs.remove_async("saved_pwd")
                else:
                    await prefs.remove("saved_ip")
                    await prefs.remove("saved_pwd")
            except Exception:
                pass

        remember_cb.value = False
        pwd_input.value = ""
        login_status.value = "已退出登录，请重新验证"
        login_status.color = ColorConfig.TEXT_SEC
        main_view.visible = False
        fab_container.visible = False
        login_view.visible = True
        show_toast(page, "已安全退出登录", True)
        page.update()

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

    # 悬浮按钮逻辑
    fab_state = {"expanded": False, "task": None}

    async def expand_fab():
        if fab_state["expanded"]:
            return
        fab_state["expanded"] = True
        fab_inner.width = 60
        fab_icon.name = ft.Icons.SWITCH_ACCOUNT
        fab_icon.size = 24
        page.update()

        if fab_state["task"]:
            fab_state["task"].cancel()

        async def auto_collapse():
            try:
                await asyncio.sleep(3)
                await collapse_fab()
            except asyncio.CancelledError:
                pass

        fab_state["task"] = asyncio.create_task(auto_collapse())

    async def collapse_fab():
        if not fab_state["expanded"]:
            return
        fab_state["expanded"] = False
        fab_inner.width = 24
        fab_icon.name = ft.Icons.CHEVRON_LEFT
        fab_icon.size = 20
        page.update()

    async def on_fab_click(e):
        if not fab_state["expanded"]:
            await expand_fab()
        else:
            await collapse_fab()
            await do_relogin(e)

    async def on_fab_pan(e):
        dx = getattr(e.local_delta, 'x', 0) if hasattr(e, 'local_delta') else getattr(e, 'delta_x', 0)
        if dx < -2 and not fab_state["expanded"]:
            await expand_fab()
        elif dx > 2 and fab_state["expanded"]:
            await collapse_fab()

    # ==========================================
    # UI 构建 - 登录页
    # ==========================================
    saved_ip = DEFAULT_IP
    saved_pwd = ""
    try:
        if hasattr(prefs, "get_async"):
            saved_ip = await prefs.get_async("saved_ip") or DEFAULT_IP
            saved_pwd = await prefs.get_async("saved_pwd") or ""
        else:
            saved_ip = await prefs.get("saved_ip") or DEFAULT_IP
            saved_pwd = await prefs.get("saved_pwd") or ""
    except Exception:
        pass

    ip_input = ft.TextField(
        label="管理地址", value=saved_ip,
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        label_style=sec_style, hint_style=sec_style
    )
    pwd_input = ft.TextField(
        label="管理员密码", password=True, can_reveal_password=True, value=saved_pwd,
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        label_style=sec_style, hint_style=sec_style
    )
    remember_cb = ft.Checkbox(
        label="记住密码并自动登录", value=bool(saved_pwd),
        label_style=ft.TextStyle(color=ColorConfig.TEXT_SEC),
        fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
        check_color=ColorConfig.BG_COLOR
    )
    login_status = ft.Text("输入账号密码登录", color=ColorConfig.TEXT_SEC, text_align=ft.TextAlign.CENTER)
    login_btn = create_button("一键登录", on_click=do_login, height=45)

    login_view = ft.Container(
        padding=15,
        expand=True,
        content=ft.Column(
            [
                ft.Container(height=40),
                ft.Text("MU5001", size=32, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN, text_align=ft.TextAlign.CENTER),
                ft.Container(height=20),
                ip_input, pwd_input, remember_cb,
                ft.Container(height=8),
                login_status, login_btn
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
        )
    )

    # ==========================================
    # UI 构建 - 状态卡片
    # ==========================================
    txt_battery = ft.Text("电量: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_network = ft.Text("网络: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_wan_ip = ft.Text("WAN IP: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_users = ft.Text("接入设备: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_tx_speed = ft.Text("上传速度: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_rx_speed = ft.Text("下载速度: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_traffic_rt = ft.Text("本次流量: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_traffic_mo = ft.Text("当月流量: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_freq = ft.Text("频点: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_pci = ft.Text("PCI: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_rsrp = ft.Text("信号强度: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_sinr = ft.Text("信噪比: --", size=14, color=ColorConfig.TEXT_MAIN)
    txt_temp_bat = ft.Text("电池温度: --℃", size=14, color=ColorConfig.TEXT_MAIN)
    txt_temp_mdm = ft.Text("4G Modem: --℃", size=14, color=ColorConfig.TEXT_MAIN)
    txt_temp_pa = ft.Text("PA: --℃", size=14, color=ColorConfig.TEXT_MAIN)
    status_text = ft.Text("", color=ColorConfig.TEXT_MAIN)

    status_card = ft.Container(
        content=ft.Column([
            build_status_row("🔋", txt_battery),
            build_status_row("📶", txt_network),
            build_status_row("🌐", txt_wan_ip),
            build_status_row("👥", txt_users),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            build_status_row("🚀", ft.Column([txt_tx_speed, txt_rx_speed], spacing=4)),
            build_status_row("📊", ft.Column([txt_traffic_rt, txt_traffic_mo], spacing=4)),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            build_status_row("📡", txt_freq),
            build_status_row("📍", txt_pci),
            build_status_row("📶", txt_rsrp),
            build_status_row("⚡", txt_sinr),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            build_status_row("🌡️", ft.Column([txt_temp_bat, txt_temp_mdm, txt_temp_pa], spacing=4)),
            ft.Divider(height=8, color=ColorConfig.DIVIDER_COLOR),
            status_text
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12
    )

    # ==========================================
    # UI 构建 - 定时重启卡片
    # ==========================================
    txt_local_time = ft.Text("设备当前时间: --", size=12, color=ColorConfig.TEXT_SEC)    
    reboot_enable = ft.Switch(
        label="启用定时重启功能", value=False,
        active_track_color=ColorConfig.ACCENT_COLOR,
        inactive_track_color=ColorConfig.BG_COLOR,
        thumb_color=ColorConfig.TEXT_MAIN
    )
    reboot_hint = ft.Text("提示：时:0~23 | 分:0~59 | 缓冲时间:1~6", size=12, color=ColorConfig.TEXT_SEC)
    reboot_mode = ft.Dropdown(
        label="重启模式",
        options=[
            ft.dropdown.Option("1", "1 - 按周自动重启"),
            ft.dropdown.Option("2", "2 - 按间隔天数")
        ], 
        value="1",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, border_color=ColorConfig.TEXT_SEC,
        focused_border_color=ColorConfig.ACCENT_COLOR
    )
    rb_time_hr = ft.TextField(
        label="时", expand=1, value="02",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, hint_style=sec_style,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        # 新增限制
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    rb_time_min = ft.TextField(
        label="分", expand=1, value="00",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, hint_style=sec_style,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        # 新增限制
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    rb_buffer = ft.TextField(
        label="缓冲时间", expand=1, value="02",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, hint_style=sec_style,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        # 新增限制
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    row_time = ft.Row(
        [rb_time_hr, ft.Text(":", size=20, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN), rb_time_min, rb_buffer],
        spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER
    )

    week_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    week_cbs = [
        ft.Checkbox(
            label=w, value=False, data=str(i+1), on_change=on_week_change,
            label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN),
            fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
            check_color=ColorConfig.BG_COLOR
        ) for i, w in enumerate(week_days)
    ]
    row_weeks = ft.ResponsiveRow(
        controls=[
            ft.Container(content=cb, col={"xs": 4, "sm": 3, "md": 2}, padding=0, margin=0)
            for cb in week_cbs
        ],
        run_spacing=0, spacing=0
    )

    rb_interval = ft.Dropdown(
        label="间隔天数",
        options=[ft.dropdown.Option(str(i), str(i)) for i in range(1, 31)],
        value="1", menu_height=300,
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, border_color=ColorConfig.TEXT_SEC,
        focused_border_color=ColorConfig.ACCENT_COLOR
    )
    btn_save_reboot = create_button("保存重启规则", on_click=on_save_reboot)

    reboot_card = ft.Container(
        content=ft.Column([
            ft.Text("⏱️ 定时重启规则", size=18, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            txt_local_time,
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            reboot_enable, reboot_hint,row_time, reboot_mode, 
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            ft.Text("🔹 选项1: 按周触发（仅选 1 生效）", size=13, color=ColorConfig.TEXT_SEC, weight=ft.FontWeight.BOLD),
            row_weeks,
            ft.Container(height=5),
            ft.Text("🔹 选项2: 间隔触发（仅选 2 生效）", size=13, color=ColorConfig.TEXT_SEC, weight=ft.FontWeight.BOLD),
            rb_interval,
            ft.Container(height=10),
            btn_save_reboot
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12
    )

    # ==========================================
    # UI 构建 - 高级设置卡片
    # ==========================================
    wifi_sleep = ft.Dropdown(
        label="WiFi 空闲休眠",
        options=[
            ft.dropdown.Option("0", "永不休眠"),
            ft.dropdown.Option("5", "5 分钟"),
            ft.dropdown.Option("10", "10 分钟"),
            ft.dropdown.Option("20", "20 分钟"),
            ft.dropdown.Option("30", "30 分钟"),
            ft.dropdown.Option("60", "1 小时"),
            ft.dropdown.Option("120", "2 小时"),
        ],
        value="10",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, border_color=ColorConfig.TEXT_SEC,
        focused_border_color=ColorConfig.ACCENT_COLOR
    )
    btn_wifi_sleep = create_button("保存休眠设置", on_click=on_wifi_sleep_save)

    # 网络模式网格
    net_mode_controls = []
    for name in NET_CONFIG.keys():
        cb = ft.Checkbox(
            label=name, value=(name == "5G/4G/3G"), on_change=on_net_mode_change,
            label_style=ft.TextStyle(color=ColorConfig.TEXT_MAIN),
            fill_color={"selected": ColorConfig.ACCENT_COLOR, "": ColorConfig.BG_COLOR},
            check_color=ColorConfig.BG_COLOR
        )
        net_mode_cbs[name] = cb
        net_mode_controls.append(
            ft.Container(content=cb, col={"xs": 6, "sm": 4, "md": 3}, padding=0, margin=0)
        )
    net_mode_grid = ft.ResponsiveRow(net_mode_controls, run_spacing=0, spacing=0)
    btn_net_mode_apply = create_button("应用网络锁定", on_click=on_apply_net_mode)

    # 频段网格
    lte_grid = create_checkbox_grid(LTE_BANDS, "B", lte_selected, lte_cbs, on_lte_change)
    sa_grid = create_checkbox_grid(NR_SA_BANDS, "N", nr_sa_selected, sa_cbs, on_sa_change)
    nsa_grid = create_checkbox_grid(NR_NSA_BANDS, "N", nr_nsa_selected, nsa_cbs, on_nsa_change)

    btn_lte_apply = create_button("应用 4G 锁频段", on_click=on_apply_lte)
    btn_sa_apply = create_button("应用 5G SA 锁频段", on_click=on_apply_sa)
    btn_nsa_apply = create_button("应用 5G NSA 锁频段", on_click=on_apply_nsa)

    # 锁小区表单
    cell_pci = ft.TextField(
        expand=True, color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, hint_style=sec_style,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        # ====== 新增以下两行限制 ======
        input_filter=ft.NumbersOnlyInputFilter(),  # 强制只能输入数字
    )
    row_pci = ft.Row([
        ft.Row([ft.Text("PCI", color=ColorConfig.TEXT_MAIN), ft.Text("*", color=ColorConfig.ACCENT_COLOR)], spacing=2, width=LABEL_W),
        cell_pci
    ], spacing=10)

    cell_earfcn = ft.TextField(
        expand=True, color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, hint_style=sec_style,
        border_color=ColorConfig.TEXT_SEC, focused_border_color=ColorConfig.ACCENT_COLOR,
        # ====== 新增以下两行限制 ======
        input_filter=ft.NumbersOnlyInputFilter(),  # 强制只能输入数字
    )
    row_earfcn = ft.Row([
        ft.Row([ft.Text("EARFCN", color=ColorConfig.TEXT_MAIN), ft.Text("*", color=ColorConfig.ACCENT_COLOR)], spacing=2, width=LABEL_W),
        cell_earfcn
    ], spacing=10)

    cell_band = ft.Dropdown(
        expand=True,
        options=[
            ft.dropdown.Option("1", "频段 1"),
            ft.dropdown.Option("3", "频段 3"),
            ft.dropdown.Option("28", "频段 28"),
            ft.dropdown.Option("41", "频段 41"),
            ft.dropdown.Option("78", "频段 78"),
        ],
        value="1",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, border_color=ColorConfig.TEXT_SEC,
        focused_border_color=ColorConfig.ACCENT_COLOR
    )
    row_band = ft.Row([ft.Text("BAND", width=LABEL_W, color=ColorConfig.TEXT_MAIN), cell_band], spacing=10)

    cell_scs = ft.Dropdown(
        expand=True,
        options=[
            ft.dropdown.Option("15", "15KHz"),
            ft.dropdown.Option("30", "30KHz"),
            ft.dropdown.Option("60", "60KHz"),
        ],
        value="15",
        color=ColorConfig.TEXT_MAIN, bgcolor=ColorConfig.INPUT_BG,
        label_style=sec_style, border_color=ColorConfig.TEXT_SEC,
        focused_border_color=ColorConfig.ACCENT_COLOR
    )
    row_scs = ft.Row([ft.Text("SCS", width=LABEL_W, color=ColorConfig.TEXT_MAIN), cell_scs], spacing=10)

    cell_tip = ft.Text("设备重启后生效", size=13, color=ColorConfig.TEXT_SEC, text_align=ft.TextAlign.CENTER)
    btn_cell_apply = create_button("应用锁小区", on_click=on_cell_lock, height=45)
    btn_cell_unlock = create_button("清除锁定", on_click=on_cell_unlock, height=45, expand=True)
    btn_cell_reboot = create_button("重启设备", on_click=on_reboot, height=45, expand=True)

    btn_refresh = create_button("刷新数据", on_click=refresh_all, icon=ft.Icons.REFRESH, expand=True)
    btn_reboot_top = create_button("重启设备", on_click=on_reboot, icon=ft.Icons.POWER_SETTINGS_NEW, expand=True)

    setting_card = ft.Container(
        content=ft.Column([
            ft.Text("⚙️ 高级网络设置", size=18, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            ft.Divider(height=10, color=ColorConfig.DIVIDER_COLOR),

            ft.Text("📶 WiFi 省电休眠", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            wifi_sleep, btn_wifi_sleep,
            ft.Container(height=15),

            ft.Text("🌐 网络模式锁定", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            net_mode_grid, btn_net_mode_apply,
            ft.Container(height=15),

            ft.Row([
                ft.Text("📡 网络频段锁定", weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
                ft.Text("（每项至少保留一个频段）", size=12, color=ColorConfig.TEXT_SEC)
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),

            ft.Text("🔹 4G LTE 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            lte_grid, btn_lte_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G SA 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            sa_grid, btn_sa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G NSA 频段", size=13, weight=ft.FontWeight.W_500, color=ColorConfig.TEXT_MAIN),
            nsa_grid, btn_nsa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G 锁定小区", size=14, weight=ft.FontWeight.BOLD, color=ColorConfig.TEXT_MAIN),
            ft.Divider(height=5, color=ColorConfig.DIVIDER_COLOR),
            row_pci, row_earfcn, row_band, row_scs,
            cell_tip, btn_cell_apply,
            ft.Row([btn_cell_unlock, btn_cell_reboot], spacing=10),
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=ColorConfig.CARD_BG, border_radius=12
    )

    # ==========================================
    # 主视图与悬浮按钮
    # ==========================================
    logout_btn = create_button("退出", on_click=do_logout, height=36)
    logout_btn.style.bgcolor = ColorConfig.FAB_BG
    logout_btn.style.color = ColorConfig.FAB_ICON

    title_row = ft.Row(
        [
            logout_btn,
            ft.Text("设备状态", size=24, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, expand=True, color=ColorConfig.TEXT_MAIN),
            ft.Container(width=80)
        ],
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.CENTER
    )

    main_view = ft.Container(
        padding=15,
        expand=True,
        visible=False,
        content=ft.Column(
            [
                ft.Container(height=10),
                title_row,
                status_card,
                ft.Row([btn_refresh, btn_reboot_top], spacing=10),
                ft.Container(height=10),
                reboot_card,
                ft.Container(height=10),
                setting_card,
                ft.Container(height=30)
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
        )
    )

    fab_icon = ft.Icon(ft.Icons.CHEVRON_LEFT, color=ColorConfig.FAB_ICON, size=20)
    fab_inner = ft.Container(
        content=fab_icon,
        alignment=ft.Alignment(0, 0),
        width=24, height=48,
        bgcolor=ColorConfig.FAB_BG,
        border_radius=ft.BorderRadius(top_left=24, top_right=0, bottom_left=24, bottom_right=0),
        animate=ft.Animation(250, "decelerate"),
        on_click=on_fab_click,
    )
    fab_gesture = ft.GestureDetector(
        on_pan_update=on_fab_pan,
        content=fab_inner
    )
    fab_container = ft.Container(
        content=fab_gesture,
        right=0,
        top=25,
        visible=False
    )

    root_stack = ft.Stack(
        controls=[login_view, main_view, fab_container],
        expand=True
    )
    page.add(root_stack)

    # 记住密码自动登录
    if saved_pwd and saved_ip:
        await do_login(None)

if __name__ == "__main__":
    ft.run(main)
