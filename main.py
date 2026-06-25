import flet as ft
import requests
import hashlib
from datetime import datetime
import asyncio

# ==========================================
# 解密工具
# ==========================================
def get_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest().lower()

def get_sha256_upper(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()

def calculate_ad(rd0, rd1, rd_value):
    step1 = get_md5(rd0 + rd1)
    return get_md5(step1 + rd_value)

def format_bytes(size):
    try:
        size = float(size)
    except (ValueError, TypeError):
        return "0 B"
    if size <= 0: return "0 B"
    power_labels = ['B', 'KB', 'MB', 'GB', 'TB']
    n = 0
    while size >= 1024 and n < len(power_labels) - 1:
        size /= 1024
        n += 1
    return f"{size:.2f} {power_labels[n]}"

# ==========================================
# 频段掩码工具
# ==========================================
def lte_bands_to_mask(bands):
    mask = 0
    for b in bands:
        mask |= 1 << (int(b) - 1)
    return f"0x{mask:010x}"

def mask_to_lte_bands(mask_str):
    try:
        mask = int(mask_str, 16)
    except:
        return []
    bands = []
    for i in range(64):
        if mask & (1 << i):
            bands.append(str(i + 1))
    return bands

# ==========================================
# 主程序 (异步)
# ==========================================
async def main(page: ft.Page):
    # ==========================================
    # 全局配色变量
    # ==========================================
    BG_COLOR = "#171920"         # 底层颜色：用作页面背景、未勾选框底色、功能开关底色
    CARD_BG = "#40425C"          # 容器卡片底色
    INPUT_BG = "#36394F"         # 输入框/下拉菜单底色
    
    TEXT_MAIN = "#FFFFFF"        # 主文字、按键文字：纯白
    TEXT_SEC = "#A1A4B0"         # 辅助说明小字、边框：浅灰
    ACCENT_COLOR = "#82A5E0"     # 可点击交互、滑轨激活色、勾选框选中色：淡蓝
    ERROR_COLOR = "#E08282"      # 警告/错误：柔和红
    DIVIDER_COLOR = "#2A2C3E"    # 分割线色
  
    BTN_BG = "#535773"           # 按键常显色：比卡片稍亮，实现常显凸起感
    BTN_HOVER_BG = "#6A6F91"     # 按键悬浮色：比常显稍亮，提供滑过反馈
    
    FAB_BG = "#82A5E0"           # 悬浮按钮背景色：淡蓝
    FAB_ICON = "#FFFFFF"         # 悬浮按钮图标色：纯白
    
    TOAST_SUCCESS_BG = "#2D4A3E" # 成功提示背景色：暗绿
    TOAST_ERROR_BG = "#5C2D2D"   # 错误/警告提示背景色：暗红

    # 设置全局字体：思源黑体
    page.theme = ft.Theme(font_family="Source Han Sans SC, Noto Sans SC, Microsoft YaHei, sans-serif")
    page.title = "MU5001"
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_COLOR

    # 启用 Flet 持久化存储服务
    prefs = ft.SharedPreferences()

    app_state = {
        "session": None,
        "ip": "",
        "rd0": "",
        "rd1": "",
        "password": "",
        "dev_unlocked": False
    }

    LTE_BANDS = ["1","3","4","5","7","8","12","17","34","39","40","41"]
    NR_SA_BANDS = ["1","3","28","41","78"]
    NR_NSA_BANDS = ["28","41","78"]

    lte_selected = set(LTE_BANDS)
    nr_sa_selected = set(NR_SA_BANDS)
    nr_nsa_selected = set(NR_NSA_BANDS)

    lte_checkboxes = {}
    sa_checkboxes = {}
    nsa_checkboxes = {}

    API_KEY_WRITE = "BearerPreference"
    API_KEY_READ  = "net_select"

    NET_CONFIG = {
        "5G/4G/3G": {"write_val": "WL_AND_5G",     "read_val": "WL_AND_5G"},
        "NSA":      {"write_val": "LTE_AND_5G",    "read_val": "LTE_AND_5G"},
        "SA":       {"write_val": "Only_5G",       "read_val": "ONLY_5G"}, 
        "4G/3G":    {"write_val": "WCDMA_AND_LTE", "read_val": "WCDMA_AND_LTE"},
        "4G":       {"write_val": "Only_LTE",      "read_val": "ONLY_LTE"},
        "3G":       {"write_val": "Only_WCDMA",    "read_val": "ONLY_WCDMA"}
    }
    
    net_mode_checkboxes = {}
    LABEL_W = 75 

    # ==========================================
    # 统一样式构建函数
    # ==========================================
   
    def create_button(text, on_click, height=None, color=TEXT_MAIN, bgcolor=BTN_BG, icon=None, expand=False):
        btn_style = ft.ButtonStyle(
            color=color,
            bgcolor={
                "hovered": BTN_HOVER_BG,       # 鼠标悬浮变色
                "": bgcolor                    # 默认常显颜色
            },
            elevation={"": 0}                  # 保持扁平化设计，不要阴影
        )

        BtnClass = getattr(ft, "Button", ft.ElevatedButton) 
        btn = BtnClass(text, on_click=on_click, height=height, icon=icon, style=btn_style)
        btn.expand = expand
        return btn

    def create_checkbox_grid(bands_list, prefix, selected_set, checkboxes_dict, on_change_handler):
        controls = []
        for b in bands_list:
            cb = ft.Checkbox(
                label=f"{prefix}{b}",
                value=(b in selected_set),
                data=b,
                on_change=on_change_handler,
                label_style=ft.TextStyle(color=TEXT_MAIN),
                fill_color={"selected": ACCENT_COLOR, "": BG_COLOR}, # 选中淡蓝，未选中底层黑
                check_color=BG_COLOR # 对勾颜色为底层黑，清晰度极高
            )
            checkboxes_dict[b] = cb
            controls.append(ft.Container(content=cb, width=72, padding=0, margin=0))
        return ft.Row(controls, wrap=True, spacing=5, run_spacing=0)

    def lte_checkbox_change(e):
        band_id = e.control.data
        if e.control.value: lte_selected.add(band_id)
        elif band_id in lte_selected: lte_selected.remove(band_id)

    def sa_checkbox_change(e):
        band_id = e.control.data
        if e.control.value: nr_sa_selected.add(band_id)
        elif band_id in nr_sa_selected: nr_sa_selected.remove(band_id)

    def nsa_checkbox_change(e):
        band_id = e.control.data
        if e.control.value: nr_nsa_selected.add(band_id)
        elif band_id in nr_nsa_selected: nr_nsa_selected.remove(band_id)

    def net_mode_change(e):
        if e.control.value:
            for name, cb in net_mode_checkboxes.items():
                if cb != e.control:
                    cb.value = False
        else:
            e.control.value = True
        page.update()

    def show_toast(msg, is_success=True):
        bg_color = TOAST_SUCCESS_BG if is_success else TOAST_ERROR_BG
        icon = "✅ " if is_success else "❌ "
        snack = ft.SnackBar(
            content=ft.Text(f"{icon}{msg}", color=TEXT_MAIN, weight=ft.FontWeight.BOLD),
            bgcolor=bg_color,
            duration=5000,
            behavior=ft.SnackBarBehavior.FLOATING
        )
        page.overlay.append(snack)
        snack.open = True
        page.update()

    def get_latest_ld():
        try:
            res = app_state["session"].get(f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd=LD").json()
            return res.get("LD", "")
        except: return ""

    def execute_post(goform_id, params):
        try:
            session = app_state["session"]
            ip = app_state["ip"]
            rd = session.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=RD").json().get("RD", "")
            ad = calculate_ad(app_state["rd0"], app_state["rd1"], rd)
            payload = {"isTest": "false", "goformId": goform_id, "AD": ad}
            payload.update(params)
            resp = session.post(f"{ip}/goform/goform_set_cmd_process", data=payload, timeout=5)
            return str(resp.json().get("result", "")).strip() in ["0", "success", "4"]
        except Exception: return False

    def unlock_developer():
        pwd_encrypted = get_sha256_upper(get_sha256_upper(app_state["password"]) + get_latest_ld())
        if execute_post("DEVELOPER_OPTION_LOGIN", {"password": pwd_encrypted}):
            app_state["dev_unlocked"] = True
            return True
        return False

    def refresh_data(e=None):
        if not app_state["session"]: return
        status_text.value = "正在读取设备信息..."
        status_text.color = TEXT_MAIN
        page.update()
        try:
            cmd = "sysIdleTimeToSleep,lte_band_lock,nr5g_sa_band_lock,nr5g_nsa_band_lock,nr5g_cell_lock,reboot_schedule_enable,reboot_schedule_mode,reboot_hour1,reboot_min1,reboot_timeframe_hours1,reboot_dow,reboot_dod"
            url = f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd={cmd}&multi_data=1"
            res = app_state["session"].get(url, timeout=5).json()

            val = res.get("sysIdleTimeToSleep", "10")
            if val in [o.key for o in wifi_sleep.options]: wifi_sleep.value = val

            mask = res.get("lte_band_lock", "")
            if mask:
                lte_selected.clear()
                lte_selected.update(mask_to_lte_bands(mask))
            for b, cb in lte_checkboxes.items(): cb.value = (b in lte_selected)

            try:
                sa = app_state["session"].get(f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd=nr5g_sa_band_lock").json().get("nr5g_sa_band_lock", "")
                if sa:
                    nr_sa_selected.clear()
                    nr_sa_selected.update([b.strip() for b in sa.split(",") if b.strip()])
            except: pass
            for b, cb in sa_checkboxes.items(): cb.value = (b in nr_sa_selected)

            try:
                nsa = app_state["session"].get(f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd=nr5g_nsa_band_lock").json().get("nr5g_nsa_band_lock", "")
                if nsa:
                    nr_nsa_selected.clear()
                    nr_nsa_selected.update([b.strip() for b in nsa.split(",") if b.strip()])
            except: pass
            for b, cb in nsa_checkboxes.items(): cb.value = (b in nr_nsa_selected)

            try:
                cell_lock_res = app_state["session"].get(f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd=nr5g_cell_lock").json()
                cell_lock_val = cell_lock_res.get("nr5g_cell_lock", "")
                if cell_lock_val and cell_lock_val not in ["1,1,1,1"]:
                    parts = cell_lock_val.split(",")
                    if len(parts) >= 4:
                        cell_pci.value = parts[0].strip()
                        cell_earfcn.value = parts[1].strip()
                        band = parts[2].strip()
                        scs_val = parts[3].strip()
                        if any(o.key == band for o in cell_band.options): cell_band.value = band
                        if any(o.key == scs_val for o in cell_scs.options): cell_scs.value = scs_val
                else:
                    cell_pci.value = ""
                    cell_earfcn.value = ""
                    cell_band.value = "1"
                    cell_scs.value = "15"
            except Exception as e_inner: pass

            try:
                rb_en = res.get("reboot_schedule_enable", "0")
                reboot_enable.value = (rb_en == "1")
                rb_mode = res.get("reboot_schedule_mode", "1")
                if rb_mode in ["1", "2"]: reboot_mode.value = rb_mode
                rb_time_hr.value = res.get("reboot_hour1", "02").zfill(2)
                rb_time_min.value = res.get("reboot_min1", "00").zfill(2)
                rb_buffer.value = res.get("reboot_timeframe_hours1", "02").zfill(2)
                rb_dow = res.get("reboot_dow", "")
                selected_weeks = [w.strip() for w in rb_dow.split(",") if w.strip()]
                for cb in week_cbs: cb.value = cb.data in selected_weeks
                rb_dod = res.get("reboot_dod", "1")
                if any(o.key == rb_dod for o in rb_interval.options): rb_interval.value = rb_dod
            except Exception as e_inner: pass

            try:
                net_url = f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd={API_KEY_READ}"
                net_res = app_state["session"].get(net_url, timeout=3).json()
                current_bearer = str(net_res.get(API_KEY_READ, "")).strip().upper()

                if current_bearer:
                    matched = False
                    for name, config in NET_CONFIG.items():
                        if current_bearer == config["read_val"].upper():
                            for cb in net_mode_checkboxes.values(): cb.value = False
                            net_mode_checkboxes[name].value = True
                            matched = True
                            break
                    if not matched:
                        for cb in net_mode_checkboxes.values(): cb.value = False
                        net_mode_checkboxes["5G/4G/3G"].value = True
            except Exception as e_inner:
                pass

            status_text.value = "✅ 数据读取成功" + (" | 开发者已解锁" if app_state["dev_unlocked"] else " | ⚠️ 开发者未解锁")
            status_text.color = ACCENT_COLOR if app_state["dev_unlocked"] else ERROR_COLOR
            
            fetch_realtime_stats()
            if e: show_toast("数据刷新成功，请确保已登录", True)
        except Exception:
            status_text.value = "⚠️ 读取失败，请检查连接"
            status_text.color = ERROR_COLOR
            if e: show_toast("数据读取失败，请检查连接", False)
            page.update()

    def fetch_realtime_stats():
        if not app_state["session"]: return
        try:
            cmd = "battery_value,battery_charging,network_type,wan_ipaddr,Z5g_rsrp,Z5g_SINR,nr5g_pci,nr5g_action_channel,pm_sensor_mdm,battery_temp,pm_sensor_pa1,realtime_tx_thrpt,realtime_rx_thrpt,realtime_tx_bytes,realtime_rx_bytes,monthly_tx_bytes,monthly_rx_bytes,wan_active_band,nr5g_action_band,wan_active_channel,lte_pci,lte_rsrp,lte_snr"
            url = f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd={cmd}&multi_data=1"
            res = app_state["session"].get(url, timeout=2).json()

            net_type = res.get('network_type', '?')
            lte_band = str(res.get('wan_active_band', '')).strip()
            nr_band = str(res.get('nr5g_action_band', '')).strip()

            band_display = ""
            if '5G' in net_type.upper() or 'SA' in net_type.upper() or 'NSA' in net_type.upper():
                band_display = nr_band if nr_band else lte_band
            else:
                band_display = lte_band
                
            if band_display:
                txt_network.value = f"网络: {net_type} ({band_display})"
            else:
                txt_network.value = f"网络: {net_type}"
            
            battery_val = str(res.get('battery_value', '?'))
            charging_flag = str(res.get('battery_charging', ''))
            charge_str = "充电中" if charging_flag in ['1', '2'] else "未充电"
            txt_battery.value = f"电量: {battery_val}% ({charge_str})"
            
            txt_wan_ip.value = f"WAN IP: {res.get('wan_ipaddr', '未分配')}"

            tx_speed = res.get("realtime_tx_thrpt", 0)
            rx_speed = res.get("realtime_rx_thrpt", 0)
            txt_tx_speed.value = f"上传速度: {format_bytes(tx_speed)}/s"
            txt_rx_speed.value = f"下载速度: {format_bytes(rx_speed)}/s"

            rt_tx_bytes = float(res.get("realtime_tx_bytes", 0))
            rt_rx_bytes = float(res.get("realtime_rx_bytes", 0))
            mo_tx_bytes = float(res.get("monthly_tx_bytes", 0))
            mo_rx_bytes = float(res.get("monthly_rx_bytes", 0))
            txt_traffic_rt.value = f"本次流量: {format_bytes(rt_tx_bytes + rt_rx_bytes)}"
            txt_traffic_mo.value = f"当月流量: {format_bytes(mo_tx_bytes + mo_rx_bytes)}"

            freq_5g = str(res.get("nr5g_action_channel", "")).strip()
            freq_4g = str(res.get("wan_active_channel", "")).strip()
            freq_val = freq_5g if freq_5g else freq_4g
            
            raw_pci_5g = str(res.get("nr5g_pci", "")).strip()
            raw_pci_4g = str(res.get("lte_pci", "")).strip()
            
            try: pci_5g = str(int(raw_pci_5g, 16)) if raw_pci_5g else ""
            except: pci_5g = raw_pci_5g
            try: pci_4g = str(int(raw_pci_4g, 16)) if raw_pci_4g else ""
            except: pci_4g = raw_pci_4g
            
            pci_val = pci_5g if pci_5g else pci_4g
            
            rsrp_5g = str(res.get('Z5g_rsrp', '')).strip()
            rsrp_4g = str(res.get('lte_rsrp', '')).strip()
            rsrp_val = rsrp_5g if rsrp_5g else rsrp_4g
            
            sinr_5g = str(res.get('Z5g_SINR', '')).strip()
            sinr_4g = str(res.get('lte_snr', '')).strip()
            sinr_val = sinr_5g if sinr_5g else sinr_4g

            txt_freq.value = f"频点: {freq_val if freq_val else '--'}"
            txt_pci.value = f"PCI: {pci_val if pci_val else '--'}"
            txt_rsrp.value = f"信号强度: {rsrp_val if rsrp_val else '--'} dBm"
            txt_sinr.value = f"信噪比: {sinr_val if sinr_val else '--'} dB"

            txt_temp_bat.value = f"电池温度: {res.get('battery_temp', '--')}℃"
            txt_temp_mdm.value = f"4G Modem: {res.get('pm_sensor_mdm', '--')}℃"
            txt_temp_pa.value = f"PA: {res.get('pm_sensor_pa1', '--')}℃"

            try:
                s = app_state["session"]
                ip_addr = app_state["ip"]
                wifi_ret = s.get(f"{ip_addr}/goform/goform_get_cmd_process?isTest=false&cmd=station_list", timeout=2).json()
                lan_ret = s.get(f"{ip_addr}/goform/goform_get_cmd_process?isTest=false&cmd=lan_station_list", timeout=2)
                
                wifi_devs = wifi_ret.get("station_list", [])
                try: lan_devs = lan_ret.json().get("lan_station_list", [])
                except: lan_devs = []
                
                mac_set = set()
                for dev in wifi_devs:
                    mac = dev.get("mac_addr", "").strip().upper()
                    if mac: mac_set.add(mac)
                for dev in lan_devs:
                    mac = dev.get("mac_addr", "").strip().upper()
                    if mac: mac_set.add(mac)
                txt_users.value = f"接入设备: {len(mac_set)} 台"
            except Exception:
                pass 

            txt_local_time.value = f"设备当前时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            page.update()
        except Exception:
            pass 

    async def auto_refresh_task():
        while True:
            await asyncio.sleep(1)
            if app_state["session"] and main_view.visible:
                await asyncio.to_thread(fetch_realtime_stats)

    def reboot_click(e):
        show_toast("正在发送重启指令...", True)
        if execute_post("REBOOT_DEVICE", {}):
            status_text.value = "✅ 重启指令已发送，设备即将重启"
            status_text.color = ACCENT_COLOR
            show_toast("设备即将重启", True)
        else:
            status_text.value = "❌ 重启失败"
            status_text.color = ERROR_COLOR
            show_toast("设备重启失败", False)
        page.update()

    def wifi_sleep_click(e):
        if execute_post("SET_WIFI_SLEEP_INFO", {"sysIdleTimeToSleep": wifi_sleep.value}):
            status_text.value = "✅ WiFi休眠设置已保存"
            status_text.color = ACCENT_COLOR
            show_toast("WiFi休眠设置保存成功", True)
        else:
            status_text.value = "❌ 保存失败"
            status_text.color = ERROR_COLOR
            show_toast("WiFi休眠设置保存失败", False)
        page.update()

    async def apply_net_mode(e):
        selected_write_val = "WL_AND_5G"
        for name, cb in net_mode_checkboxes.items():
            if cb.value:
                selected_write_val = NET_CONFIG[name]["write_val"]
                break
                
        show_toast("正在下发网络锁定配置...", True)
        execute_post("DISCONNECT_NETWORK", {"notCallback": "true"})
        await asyncio.sleep(0.4) 
      
        ok_set = execute_post("SET_BEARER_PREFERENCE", {API_KEY_WRITE: selected_write_val})
        await asyncio.sleep(0.4) 
        
        ok_connect = execute_post("CONNECT_NETWORK", {"notCallback": "true"})
        
        if ok_set and ok_connect:
            status_text.value = "✅ 网络模式切换成功 (请等待5秒后刷新状态)"
            status_text.color = ACCENT_COLOR
            show_toast("网络切换成功，再次切换需等待5秒", True)
        else:
            status_text.value = "❌ 设置失败 (配置未生效或操作期间被挤下线)"
            status_text.color = ERROR_COLOR
            show_toast("网络切换失败 (可能被挤下线)", False)
        page.update()

    def lte_band_apply(e):
        if not lte_selected:
            show_toast("⚠️ 请至少勾选一个4G频段", False)
            return
        
        ok = execute_post("BAND_SELECT", {"is_gw_band": "0", "gw_band_mask": "0", "is_lte_band": "1", "lte_band_mask": lte_bands_to_mask(list(lte_selected))})
        if ok:
            status_text.value = "✅ 4G频段设置完成"
            status_text.color = ACCENT_COLOR
            show_toast("4G频段设置成功", True)
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ERROR_COLOR
            show_toast("4G频段设置失败，请确认开发者权限", False)
        page.update()

    def nr_sa_apply(e):
        if not nr_sa_selected:
            show_toast("⚠️ 请至少勾选一个5G SA频段", False)
            return
            
        ok = execute_post("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {"nr5g_band_mask": ",".join(sorted(nr_sa_selected, key=int)), "type": "0"})
        if ok:
            status_text.value = "✅ 5G SA频段设置完成"
            status_text.color = ACCENT_COLOR
            show_toast("5G SA频段设置成功", True)
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ERROR_COLOR
            show_toast("5G SA频段设置失败，请确认开发者权限", False)
        page.update()

    def nr_nsa_apply(e):
        if not nr_nsa_selected:
            show_toast("⚠️ 请至少勾选一个5G NSA频段", False)
            return
            
        ok = execute_post("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {"nr5g_band_mask": ",".join(sorted(nr_nsa_selected, key=int)), "type": "1"})
        if ok:
            status_text.value = "✅ 5G NSA频段设置完成"
            status_text.color = ACCENT_COLOR
            show_toast("5G NSA频段设置成功", True)
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ERROR_COLOR
            show_toast("5G NSA频段设置失败，请确认开发者权限", False)
        page.update()

    def cell_lock_apply(e):
        if not cell_pci.value or not cell_earfcn.value:
            show_toast("⚠️ 请填写PCI与EARFCN", False)
            return
            
        lock_val = f"{cell_pci.value.strip()},{cell_earfcn.value.strip()},{cell_band.value},{cell_scs.value}"
        ok = execute_post("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": lock_val})
        if ok:
            status_text.value = "✅ 锁小区配置下发完成"
            status_text.color = ACCENT_COLOR
            show_toast("锁小区成功", True)
        else:
            status_text.value = "❌ 锁小区失败，确认开发者权限已解锁"
            status_text.color = ERROR_COLOR
            show_toast("锁小区失败，请确认开发者权限", False)
        page.update()

    def cell_unlock_click(e):
        if execute_post("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": "1,1,1,1"}):
            cell_pci.value = ""
            cell_earfcn.value = ""
            cell_band.value = "1"
            cell_scs.value = "15"
            status_text.value = "✅ 小区锁定已解除"
            status_text.color = ACCENT_COLOR
            show_toast("小区锁定已解除", True)
        else:
            status_text.value = "❌ 解除失败，确认开发者权限已解锁"
            status_text.color = ERROR_COLOR
            show_toast("解除锁定失败", False)
        page.update()

    def save_schedule_reboot(e):
        weeks = ",".join([cb.data for cb in week_cbs if cb.value])
        hr = rb_time_hr.value.zfill(2)
        mn = rb_time_min.value.zfill(2)
        buf = rb_buffer.value.zfill(2)

        payload = {
            "reboot_schedule_enable": "1" if reboot_enable.value else "0",
            "reboot_schedule_mode": reboot_mode.value, 
            "reboot_hour1": hr,
            "reboot_hour2": hr, 
            "reboot_min1": mn,
            "reboot_min2": mn,
            "reboot_timeframe_hours1": buf,
            "reboot_timeframe_hours2": buf,
            "reboot_dow": weeks,
            "reboot_dod": rb_interval.value
        }

        if execute_post("FIX_TIME_REBOOT_SCHEDULE", payload):
            status_text.value = "✅ 定时重启配置已保存"
            status_text.color = ACCENT_COLOR
            show_toast("定时重启配置保存成功，请确保已开启功能", True)
        else:
            status_text.value = "❌ 保存失败，请检查连接状态"
            status_text.color = ERROR_COLOR
            show_toast("定时重启配置保存失败", False)
        page.update()

    # ==============================================
    # 登录逻辑
    # ==============================================
    async def login_click(e=None):
        ip = ip_input.value
        pwd = pwd_input.value
        if not pwd:
            login_status.value = "⚠️ 请输入密码"
            login_status.color = ERROR_COLOR
            page.update()
            return
            
        login_btn.disabled = True
        login_status.value = "正在验证登录..."
        login_status.color = TEXT_SEC
        page.update()
        
        await asyncio.sleep(0.01) 
        
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": f"{ip}/index.html"})
            s.get(f"{ip}/index.html", timeout=3)
            ver = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=Language,cr_version,wa_inner_version&multi_data=1").json()
            rd0 = ver.get("wa_inner_version", "")
            rd1 = ver.get("cr_version", "")
            ld_login = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=LD").json().get("LD", "")
            rd_val = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=RD").json()["RD"]
            pwd_enc = get_sha256_upper(get_sha256_upper(pwd) + ld_login)
            res = s.post(f"{ip}/goform/goform_set_cmd_process", data={
                "isTest": "false", "goformId": "LOGIN", "password": pwd_enc, "AD": calculate_ad(rd0, rd1, rd_val)
            }).json()
            
            if str(res.get("result", "")) in ["0", "4"]:
                if prefs:
                    try:
                        if hasattr(prefs, "set_async"):
                            await prefs.set_async("saved_ip", ip)
                            await prefs.set_async("saved_pwd", pwd)
                        else:
                            await prefs.set("saved_ip", ip)
                            await prefs.set("saved_pwd", pwd)
                    except Exception: pass
                    
                app_state.update({"session": s, "ip": ip, "rd0": rd0, "rd1": rd1, "password": pwd})
                login_status.value = "解锁开发者权限..."
                page.update()
                unlock_developer()
                login_view.visible = False
                main_view.visible = True
                
                # 登录后显示重登按钮
                fab_container.visible = True
                
                await asyncio.to_thread(refresh_data)
                show_toast("登录成功", True)
            else:
                if prefs:
                    try:
                        if hasattr(prefs, "remove_async"):
                            await prefs.remove_async("saved_ip")
                            await prefs.remove_async("saved_pwd")
                        else:
                            await prefs.remove("saved_ip")
                            await prefs.remove("saved_pwd")
                    except Exception: pass
                remember_cb.value = False
                pwd_input.value = "" 
                login_status.value = "❌ 密码错误或账号锁定"
                login_status.color = ERROR_COLOR
                show_toast("密码错误或账号锁定", False)
        except Exception:
            if prefs:
                try:
                    if hasattr(prefs, "remove_async"):
                        await prefs.remove_async("saved_ip")
                        await prefs.remove_async("saved_pwd")
                    else:
                        await prefs.remove("saved_ip")
                        await prefs.remove("saved_pwd")
                except Exception: pass
            remember_cb.value = False
            login_status.value = "❌ 连接失败，请检查地址和网络"
            login_status.color = ERROR_COLOR
            show_toast("连接失败，请检查地址和网络", False)
            
        login_btn.disabled = False
        page.update()

    async def relogin_click(e=None):
        if not app_state["ip"] or not app_state["password"]:
            show_toast("本地无缓存密码，请重启APP", False)
            return
            
        show_toast("正在重登...", True)
        await asyncio.sleep(0.01) 
        
        ip = app_state["ip"]
        pwd = app_state["password"]
        
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": f"{ip}/index.html"})
            s.get(f"{ip}/index.html", timeout=3)
            ver = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=Language,cr_version,wa_inner_version&multi_data=1").json()
            rd0 = ver.get("wa_inner_version", "")
            rd1 = ver.get("cr_version", "")
            ld_login = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=LD").json().get("LD", "")
            rd_val = s.get(f"{ip}/goform/goform_get_cmd_process?isTest=false&cmd=RD").json()["RD"]
            pwd_enc = get_sha256_upper(get_sha256_upper(pwd) + ld_login)
            res = s.post(f"{ip}/goform/goform_set_cmd_process", data={
                "isTest": "false", "goformId": "LOGIN", "password": pwd_enc, "AD": calculate_ad(rd0, rd1, rd_val)
            }).json()
            
            if str(res.get("result", "")) in ["0", "4"]:
                app_state.update({"session": s, "rd0": rd0, "rd1": rd1})
                if unlock_developer():
                    status_text.value = "✅ 重登成功并已解锁开发者权限"
                    status_text.color = ACCENT_COLOR
                    show_toast("重登成功，开发者解锁成功", True)
                else:
                    status_text.value = "⚠️ 重登成功，开发者解锁失败"
                    status_text.color = ERROR_COLOR
                    show_toast("重登成功，开发者解锁失败", False)
                await asyncio.to_thread(refresh_data)
            else:
                status_text.value = "❌ 重新登录失败，可能密码已修改或被锁定"
                status_text.color = ERROR_COLOR
                show_toast("重登失败", False)
        except Exception:
            status_text.value = "❌ 重登连接失败，请检查网络"
            status_text.color = ERROR_COLOR
            show_toast("连接失败，请检查网络", False)
            
        page.update()

    # ==============================================
    # UI 控件构建
    # ==============================================
    sec_style = ft.TextStyle(color=TEXT_SEC)

    title = ft.Text("MU5001", size=32, weight=ft.FontWeight.BOLD, color=TEXT_MAIN, text_align=ft.TextAlign.CENTER)
    
    saved_ip = ""
    saved_pwd = ""
    try:
        if hasattr(prefs, "get_async"):
            saved_ip = await prefs.get_async("saved_ip")
            saved_pwd = await prefs.get_async("saved_pwd")
        else:
            saved_ip = await prefs.get("saved_ip")
            saved_pwd = await prefs.get("saved_pwd")
    except Exception: pass
    
    ip_input = ft.TextField(label="管理地址", value=saved_ip if saved_ip else "http://192.168.0.1", color=TEXT_MAIN, bgcolor=INPUT_BG, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR, label_style=sec_style, hint_style=sec_style)
    pwd_input = ft.TextField(label="管理员密码", password=True, can_reveal_password=True, value=saved_pwd if saved_pwd else "", color=TEXT_MAIN, bgcolor=INPUT_BG, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR, label_style=sec_style, hint_style=sec_style)
    
    remember_cb = ft.Checkbox(
        label="记住密码并自动登录", 
        value=bool(saved_pwd), 
        label_style=ft.TextStyle(color=TEXT_SEC), 
        fill_color={"selected": ACCENT_COLOR, "": BG_COLOR},
        check_color=BG_COLOR
    ) 
    
    login_status = ft.Text("输入账号密码登录", color=TEXT_SEC, text_align=ft.TextAlign.CENTER)
    
    login_btn = create_button("一键登录", on_click=login_click, height=45)
    
    login_view = ft.Container(
        padding=15,
        expand=True,
        content=ft.Column(
            [
                ft.Container(height=40), 
                title, 
                ft.Container(height=20), 
                ip_input, 
                pwd_input, 
                remember_cb,
                ft.Container(height=8), 
                login_status, 
                login_btn
            ],
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO,
        )
    )

    def build_status_row(icon, text_control):
        text_control.expand = True
        return ft.Row([
            ft.Text(icon, size=16, width=28, text_align=ft.TextAlign.CENTER, color=ACCENT_COLOR),
            text_control
        ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.START)

    txt_battery = ft.Text("电量: --", size=14, color=TEXT_MAIN)
    txt_network = ft.Text("网络: --", size=14, color=TEXT_MAIN)
    txt_wan_ip  = ft.Text("WAN IP: --", size=14, color=TEXT_MAIN)
    txt_users   = ft.Text("接入设备: --", size=14, color=TEXT_MAIN)

    txt_tx_speed = ft.Text("上传速度: --", size=14, color=TEXT_MAIN)
    txt_rx_speed = ft.Text("下载速度: --", size=14, color=TEXT_MAIN)
    txt_traffic_rt = ft.Text("本次流量: --", size=14, color=TEXT_MAIN)
    txt_traffic_mo = ft.Text("当月流量: --", size=14, color=TEXT_MAIN)

    col_speed = ft.Column([txt_tx_speed, txt_rx_speed], spacing=4)
    row_speed = build_status_row("🚀", col_speed)

    col_traffic = ft.Column([txt_traffic_rt, txt_traffic_mo], spacing=4)
    row_traffic = build_status_row("📊", col_traffic)

    txt_freq = ft.Text("频点: --", size=13, color=TEXT_MAIN)
    txt_pci  = ft.Text("PCI: --", size=13, color=TEXT_MAIN)
    txt_rsrp = ft.Text("信号强度: --", size=13, color=TEXT_MAIN)
    txt_sinr = ft.Text("信噪比: --", size=13, color=TEXT_MAIN)

    txt_temp_bat = ft.Text("电池温度: --℃", size=13, color=TEXT_MAIN)
    txt_temp_mdm = ft.Text("4G Modem: --℃", size=13, color=TEXT_MAIN)
    txt_temp_pa  = ft.Text("PA: --℃", size=13, color=TEXT_MAIN)

    row_battery = build_status_row("🔋", txt_battery)
    row_network = build_status_row("📶", txt_network)
    row_wan_ip  = build_status_row("🌐", txt_wan_ip)
    row_users   = build_status_row("👥", txt_users)

    row_freq = build_status_row("📡", txt_freq)
    row_pci  = build_status_row("📍", txt_pci)
    row_rsrp = build_status_row("📶", txt_rsrp)
    row_sinr = build_status_row("⚡", txt_sinr)
    
    temp_col_content = ft.Column([txt_temp_bat, txt_temp_mdm, txt_temp_pa], spacing=4)
    row_temps = build_status_row("🌡️", temp_col_content)
    
    status_text = ft.Text("", color=TEXT_MAIN)
    
    status_card = ft.Container(
        content=ft.Column([
            row_battery, row_network, row_wan_ip, row_users, 
            ft.Divider(height=5, color=DIVIDER_COLOR),
            row_speed, row_traffic,
            ft.Divider(height=5, color=DIVIDER_COLOR),
            row_freq, row_pci, row_rsrp, row_sinr, 
            ft.Divider(height=5, color=DIVIDER_COLOR),
            row_temps,
            ft.Divider(height=8, color=DIVIDER_COLOR), status_text
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=CARD_BG, border_radius=12
    )

    txt_local_time = ft.Text("设备当前时间: --", size=12, color=TEXT_SEC)
    
    reboot_enable = ft.Switch(
        label="启用定时重启功能", 
        value=False, 
        active_track_color=ACCENT_COLOR, 
        inactive_track_color=BG_COLOR, 
        thumb_color=TEXT_MAIN
    )
    
    reboot_mode = ft.Dropdown(
        label="重启模式 (选择后请填写下方对应的配置)",
        options=[ft.dropdown.Option("1", "1 - 按周自动重启"), ft.dropdown.Option("2", "2 - 按间隔天数")],
        value="1",
        color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR
    )

    rb_time_hr = ft.TextField(label="时", expand=1, value="02", color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, hint_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR)
    rb_time_min = ft.TextField(label="分", expand=1, value="00", color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, hint_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR)
    rb_buffer = ft.TextField(label="缓冲时间", expand=1, value="02", color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, hint_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR)
    row_time = ft.Row([rb_time_hr, ft.Text(":", size=20, weight=ft.FontWeight.BOLD, color=TEXT_MAIN), rb_time_min, rb_buffer], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # === 单选逻辑 ===
    def on_week_cb_change(e):
        for cb in week_cbs:
    # 只要是当前被点击的框，强制打勾；其他的强制取消
            cb.value = (cb == e.control)
        page.update()

    week_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    week_cbs = [
        ft.Checkbox(
            label=w, 
            value=False, 
            data=str(i+1), 
            on_change=on_week_cb_change,  # 绑定上面的单选事件
            label_style=ft.TextStyle(color=TEXT_MAIN), 
            fill_color={"selected": ACCENT_COLOR, "": BG_COLOR},
            check_color=BG_COLOR
        ) for i, w in enumerate(week_days)
    ]
    
    row_weeks = ft.ResponsiveRow(
        controls=[
            ft.Container(content=cb, col={"xs": 4, "sm": 3, "md": 2}, padding=0, margin=0) for cb in week_cbs
        ],
        run_spacing=0, spacing=0
    )

    rb_interval = ft.Dropdown(
        label="间隔天数", 
        options=[ft.dropdown.Option(str(i), str(i)) for i in range(1, 31)], #最大设置30天
        value="1", 
        menu_height=300, #限制选择项长度
        color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR
    )
    
    btn_save_reboot = create_button("保存重启规则", on_click=save_schedule_reboot)

    reboot_card = ft.Container(
        content=ft.Column([
            ft.Text("⏱️ 定时重启规则", size=18, weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
            txt_local_time,
            ft.Divider(height=5, color=DIVIDER_COLOR),
            reboot_enable,
            row_time,
            reboot_mode,
            ft.Divider(height=5, color=DIVIDER_COLOR),
            ft.Text("🔹 选项1: 按周触发 (仅在重启模式选 1 时生效)", size=13, color=TEXT_SEC, weight=ft.FontWeight.BOLD),
            row_weeks,
            ft.Container(height=5),
            ft.Text("🔹 选项2: 间隔触发 (仅在重启模式选 2 时生效)", size=13, color=TEXT_SEC, weight=ft.FontWeight.BOLD),
            rb_interval,
            ft.Container(height=10),
            btn_save_reboot
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=CARD_BG, border_radius=12
    )

    wifi_sleep = ft.Dropdown(
        label="WiFi空闲休眠", 
        options=[
            ft.dropdown.Option("0", "永不休眠"), ft.dropdown.Option("5", "5分钟"),
            ft.dropdown.Option("10", "10分钟"), ft.dropdown.Option("20", "20分钟"),
            ft.dropdown.Option("30", "30分钟"), ft.dropdown.Option("60", "1小时"),
            ft.dropdown.Option("120", "2小时"),
        ], 
        value="10",
        color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR
    )
    btn_wifi_sleep = create_button("保存休眠设置", on_click=wifi_sleep_click)

    net_mode_controls = []
    for name in NET_CONFIG.keys():
        cb = ft.Checkbox(
            label=name, 
            value=(name == "5G/4G/3G"), 
            on_change=net_mode_change, 
            label_style=ft.TextStyle(color=TEXT_MAIN), 
            fill_color={"selected": ACCENT_COLOR, "": BG_COLOR},
            check_color=BG_COLOR
        )
        net_mode_checkboxes[name] = cb
        net_mode_controls.append(ft.Container(content=cb, col={"xs": 6, "sm": 4, "md": 3}, padding=0, margin=0))

    net_mode_grid = ft.ResponsiveRow(net_mode_controls, run_spacing=0, spacing=0)
    btn_net_mode_apply = create_button("应用网络锁定", on_click=apply_net_mode)

    lte_grid = create_checkbox_grid(LTE_BANDS, "B", lte_selected, lte_checkboxes, lte_checkbox_change)
    sa_grid = create_checkbox_grid(NR_SA_BANDS, "N", nr_sa_selected, sa_checkboxes, sa_checkbox_change)
    nsa_grid = create_checkbox_grid(NR_NSA_BANDS, "N", nr_nsa_selected, nsa_checkboxes, nsa_checkbox_change)

    btn_lte_apply = create_button("应用 4G 锁频段", on_click=lte_band_apply)
    btn_sa_apply = create_button("应用 5G SA 锁频段", on_click=nr_sa_apply)
    btn_nsa_apply = create_button("应用 5G NSA 锁频段", on_click=nr_nsa_apply)

    cell_pci = ft.TextField(expand=True, color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, hint_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR)
    row_pci = ft.Row([ft.Row([ft.Text("PCI", color=TEXT_MAIN), ft.Text("*", color=ACCENT_COLOR)], spacing=2, width=LABEL_W), cell_pci], spacing=10)

    cell_earfcn = ft.TextField(expand=True, color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, hint_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR)
    row_earfcn = ft.Row([ft.Row([ft.Text("EARFCN", color=TEXT_MAIN), ft.Text("*", color=ACCENT_COLOR)], spacing=2, width=LABEL_W), cell_earfcn], spacing=10)

    cell_band = ft.Dropdown(
        expand=True, 
        options=[
            ft.dropdown.Option("1", "频段 1"), ft.dropdown.Option("3", "频段 3"),
            ft.dropdown.Option("28", "频段 28"), ft.dropdown.Option("41", "频段 41"),
            ft.dropdown.Option("78", "频段 78"),
        ], 
        value="1",
        color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR
    )
    row_band = ft.Row([ft.Text("BAND", width=LABEL_W, color=TEXT_MAIN), cell_band], spacing=10)

    cell_scs = ft.Dropdown(
        expand=True, 
        options=[
            ft.dropdown.Option("15", "15KHz"), ft.dropdown.Option("30", "30KHz"), ft.dropdown.Option("60", "60KHz"),
        ], 
        value="15",
        color=TEXT_MAIN, bgcolor=INPUT_BG, label_style=sec_style, border_color=TEXT_SEC, focused_border_color=ACCENT_COLOR
    )
    row_scs = ft.Row([ft.Text("SCS", width=LABEL_W, color=TEXT_MAIN), cell_scs], spacing=10)

    cell_tip = ft.Text("设备重启后生效", size=13, color=TEXT_SEC, text_align=ft.TextAlign.CENTER)
    
    btn_cell_apply = create_button("应用锁小区", on_click=cell_lock_apply, height=45)
    btn_cell_unlock = create_button("清除锁定", on_click=cell_unlock_click, height=45, expand=True)
    btn_cell_reboot = create_button("重启设备", on_click=reboot_click, height=45, expand=True)

    btn_refresh = create_button("刷新数据", on_click=refresh_data, icon=ft.Icons.REFRESH, expand=True)
    btn_reboot_top = create_button("重启设备", on_click=reboot_click, icon=ft.Icons.POWER_SETTINGS_NEW, expand=True)

    setting_card = ft.Container(
        content=ft.Column([
            ft.Text("⚙️ 高级网络设置", size=18, weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
            ft.Divider(height=10, color=DIVIDER_COLOR),
            ft.Text("📶 WiFi省电休眠", weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
            wifi_sleep, btn_wifi_sleep,
            ft.Container(height=15),

            ft.Text("🌐 网络模式锁定", weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
            net_mode_grid, 
            btn_net_mode_apply,
            ft.Container(height=15),

            ft.Row([
                ft.Text("📡 网络频段锁定", weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
                ft.Text("(每项至少保留一个频段)", size=12, color=TEXT_SEC)
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=5, color=DIVIDER_COLOR),

            ft.Text("🔹 4G LTE 频段", size=13, weight=ft.FontWeight.W_500, color=TEXT_MAIN),
            lte_grid, btn_lte_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G SA 频段", size=13, weight=ft.FontWeight.W_500, color=TEXT_MAIN),
            sa_grid, btn_sa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G NSA 频段", size=13, weight=ft.FontWeight.W_500, color=TEXT_MAIN),
            nsa_grid, btn_nsa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G 锁定小区", size=14, weight=ft.FontWeight.BOLD, color=TEXT_MAIN),
            ft.Divider(height=5, color=DIVIDER_COLOR),
            row_pci,
            row_earfcn,
            row_band,
            row_scs,
            cell_tip,
            btn_cell_apply,
            ft.Row([btn_cell_unlock, btn_cell_reboot], spacing=10),
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=15, bgcolor=CARD_BG, border_radius=12
    )

    title_row = ft.Row(
        [
            ft.Text("📊 设备状态", size=24, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER, expand=True, color=TEXT_MAIN),
        ],
        alignment=ft.MainAxisAlignment.CENTER,
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

    # ==============================================
    # 侧边栏式悬浮按钮 (贴边停靠，点击/划出展开)
    # ==============================================
    fab_state = {"expanded": False, "task": None}

    async def expand_fab():
        if fab_state["expanded"]: return
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
        if not fab_state["expanded"]: return
        fab_state["expanded"] = False
        fab_inner.width = 24
        fab_icon.name = ft.Icons.CHEVRON_LEFT
        fab_icon.size = 20
        page.update()

    async def handle_fab_click(e):
        if not fab_state["expanded"]:
            await expand_fab()
        else:
            await collapse_fab()
            await relogin_click(e)

    async def handle_pan_update(e: ft.DragUpdateEvent):
        try:
            dx = e.local_delta.x
        except AttributeError:
            dx = getattr(e, "delta_x", 0)
            
        if dx < -2 and not fab_state["expanded"]:
            await expand_fab()
        elif dx > 2 and fab_state["expanded"]:
            await collapse_fab()

    fab_icon = ft.Icon(ft.Icons.CHEVRON_LEFT, color=FAB_ICON, size=20)

    fab_inner = ft.Container(
        content=fab_icon,
        alignment=ft.Alignment(0, 0),
        width=24, 
        height=48, 
        bgcolor=FAB_BG,
        border_radius=ft.BorderRadius(top_left=24, top_right=0, bottom_left=24, bottom_right=0),
        animate=ft.Animation(250, "decelerate"),
        on_click=handle_fab_click,
    )

    fab_gesture = ft.GestureDetector(
        on_pan_update=handle_pan_update,
        content=fab_inner
    )

    fab_container = ft.Container(
        content=fab_gesture,
        right=0,  
        top=25,   
        visible=False 
    )

    root_stack = ft.Stack(
        controls=[
            login_view,
            main_view,
            fab_container
        ],
        expand=True
    )

    page.add(root_stack)
    asyncio.create_task(auto_refresh_task())

    if saved_pwd and saved_ip:
        await login_click(None)

ft.run(main)
