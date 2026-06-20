import flet as ft
import requests
import hashlib
from datetime import datetime

# ==========================================
# 加密工具
# ==========================================
def get_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest().lower()

def get_sha256_upper(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()

def calculate_ad(rd0, rd1, rd_value):
    step1 = get_md5(rd0 + rd1)
    return get_md5(step1 + rd_value)

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
# 主程序
# ==========================================
def main(page: ft.Page):
    page.title = "ZTE高级管家"
    page.window_width = 420
    page.window_height = 980
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.AUTO

    app_state = {
        "session": None,
        "ip": "",
        "rd0": "",
        "rd1": "",
        "password": "",
        "dev_unlocked": False
    }

    # 设备原生支持频段
    LTE_BANDS = ["1","3","4","5","7","8","12","17","34","39","40","41"]
    NR_SA_BANDS = ["1","3","28","41","78"]
    NR_NSA_BANDS = ["28","41","78"]

    lte_selected = set(LTE_BANDS)
    nr_sa_selected = set(NR_SA_BANDS)
    nr_nsa_selected = set(NR_NSA_BANDS)

    lte_checkboxes = {}
    sa_checkboxes = {}
    nsa_checkboxes = {}

    # ==============================================
    # 尺寸核心控制区 (安全兼容版)
    # ==============================================
    UI_WIDTH = 400       # 外层组件和卡片总宽度
    INNER_WIDTH = 370    # 卡片内部组件可用宽度
    CELL_WIDTH = 74      # 复选框单元格绝对宽度 (74 * 5 = 370，一行5个完美对齐)

    LABEL_W = 80         # 表单左侧标签宽度
    INPUT_W = 280        # 表单右侧输入框宽度 (80 + 280 + 10间距 = 370)

    # ==============================================
    # 严格对齐网格生成器
    # ==============================================
    def create_checkbox_grid(bands_list, prefix, selected_set, checkboxes_dict, on_change_handler):
        controls = []
        for b in bands_list:
            cb = ft.Checkbox(
                label=f"{prefix}{b}",
                value=(b in selected_set),
                data=b,
                on_change=on_change_handler,
            )
            checkboxes_dict[b] = cb
            controls.append(ft.Container(content=cb, width=CELL_WIDTH))

        rows = []
        for i in range(0, len(controls), 5):
            chunk = controls[i:i+5]
            rows.append(ft.Row(chunk, spacing=0))
        
        return ft.Column(rows, spacing=0)

    # ==============================================
    # 频段选择事件处理
    # ==============================================
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

    # ==============================================
    # 通用工具
    # ==============================================
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

    # ==============================================
    # 刷新设备数据
    # ==============================================
    def refresh_data(e=None):
        if not app_state["session"]: return
        status_text.value = "正在读取设备信息..."
        page.update()
        try:
            cmd = "battery_value,network_type,signalbar,wan_ipaddr,sysIdleTimeToSleep,lte_band_lock,nr5g_pci,nr5g_action_channel,nr5g_action_band,Z5g_rsrp,Z5g_SINR,nr5g_cell_id,pm_sensor_mdm,battery_temp,pm_sensor_pa1,reboot_schedule_enable,reboot_schedule_mode,reboot_hour1,reboot_min1,reboot_timeframe_hours1,reboot_dow,reboot_dod"
            url = f"{app_state['ip']}/goform/goform_get_cmd_process?isTest=false&cmd={cmd}&multi_data=1"
            res = app_state["session"].get(url, timeout=5).json()

            # 网络状态
            net_type = res.get('network_type', '?')
            band_5g = res.get("nr5g_action_band", "").strip()
            if band_5g:
                display_band = band_5g if band_5g.lower().startswith(('n', 'b')) else f"n{band_5g}"
                txt_network.value = f"网络: {net_type} ({display_band})"
            else:
                txt_network.value = f"网络: {net_type}"

            txt_battery.value = f"电量: {res.get('battery_value', '?')}%"
            txt_wan_ip.value = f"外网IP: {res.get('wan_ipaddr', '未分配')}"

            # 接入设备去重
            s = app_state["session"]
            ip_addr = app_state["ip"]
            wifi_ret = s.get(f"{ip_addr}/goform/goform_get_cmd_process?isTest=false&cmd=station_list").json()
            lan_ret = s.get(f"{ip_addr}/goform/goform_get_cmd_process?isTest=false&cmd=lan_station_list")
            wifi_devs = wifi_ret.get("station_list", [])
            try:
                lan_devs = lan_ret.json().get("lan_station_list", [])
            except:
                lan_devs = []
            mac_set = set()
            for dev in wifi_devs:
                mac = dev.get("mac_addr", "").strip().upper()
                if mac: mac_set.add(mac)
            for dev in lan_devs:
                mac = dev.get("mac_addr", "").strip().upper()
                if mac: mac_set.add(mac)
            txt_users.value = f"接入设备: {len(mac_set)} 台"

            # 5G 信号
            freq_5g = res.get("nr5g_action_channel", "").strip()
            raw_pci_5g = res.get("nr5g_pci", "").strip()
            try:
                pci_5g = str(int(raw_pci_5g, 16)) if raw_pci_5g else ""
            except ValueError:
                pci_5g = raw_pci_5g
            rsrp_5g = res.get("Z5g_rsrp", "").strip()
            sinr_5g = res.get("Z5g_SINR", "").strip()
            txt_5g_freq.value = f"5G 频点: {freq_5g if freq_5g else '--'}"
            txt_5g_pci.value = f"5G PCI: {pci_5g if pci_5g else '--'}"
            txt_5g_rsrp.value = f"5G 信号强度: {rsrp_5g if rsrp_5g else '--'} dBm"
            txt_5g_sinr.value = f"5G 信噪比: {sinr_5g if sinr_5g else '--'} dB"

            # 温度
            temp_bat = res.get("battery_temp", "").strip()
            temp_mdm = res.get("pm_sensor_mdm", "").strip()
            temp_pa1 = res.get("pm_sensor_pa1", "").strip()
            txt_temp_bat.value = f"电池温度: {temp_bat if temp_bat and temp_bat != '0' else '--'}℃"
            txt_temp_mdm.value = f"4G Modem: {temp_mdm if temp_mdm and temp_mdm != '0' else '--'}℃"
            txt_temp_pa.value  = f"PA: {temp_pa1 if temp_pa1 and temp_pa1 != '0' else '--'}℃"

            # 高级设置 - 休眠和锁频
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

            # 锁小区
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
            except Exception as e:
                pass

            # 定时重启读取
            try:
                rb_en = res.get("reboot_schedule_enable", "0")
                reboot_enable.value = (rb_en == "1")

                rb_mode = res.get("reboot_schedule_mode", "1")
                if rb_mode in ["1", "2"]:
                    reboot_mode.value = rb_mode

                rb_time_hr.value = res.get("reboot_hour1", "02").zfill(2)
                rb_time_min.value = res.get("reboot_min1", "00").zfill(2)
                rb_buffer.value = res.get("reboot_timeframe_hours1", "02").zfill(2)

                rb_dow = res.get("reboot_dow", "")
                selected_weeks = [w.strip() for w in rb_dow.split(",") if w.strip()]
                for cb in week_cbs:
                    cb.value = cb.data in selected_weeks

                rb_dod = res.get("reboot_dod", "1")
                if any(o.key == rb_dod for o in rb_interval.options):
                    rb_interval.value = rb_dod
            except Exception as e:
                print("解析定时重启配置异常:", e)

            txt_local_time.value = f"设备当前时间: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            status_text.value = "✅ 数据读取成功" + (" | 开发者已解锁" if app_state["dev_unlocked"] else " | ⚠️ 开发者未解锁")
            status_text.color = ft.Colors.GREEN if app_state["dev_unlocked"] else ft.Colors.ORANGE
        except Exception:
            status_text.value = "⚠️ 读取失败，请检查连接"
            status_text.color = ft.Colors.RED
        page.update()

    # ==============================================
    # 动作按钮执行
    # ==============================================
    def reboot_click(e):
        status_text.value = "🔄 正在发送重启指令..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        if execute_post("REBOOT_DEVICE", {}):
            status_text.value = "✅ 重启指令已发送，设备即将重启"
            status_text.color = ft.Colors.RED
        else:
            status_text.value = "❌ 重启失败"
            status_text.color = ft.Colors.RED
        page.update()

    def wifi_sleep_click(e):
        status_text.value = "正在保存休眠设置..."
        page.update()
        if execute_post("SET_WIFI_SLEEP_INFO", {"sysIdleTimeToSleep": wifi_sleep.value}):
            status_text.value = "✅ WiFi休眠设置已保存"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 保存失败"
            status_text.color = ft.Colors.RED
        page.update()

    def lte_band_apply(e):
        if not lte_selected:
            status_text.value = "⚠️ 请至少勾选一个4G频段"
            status_text.color = ft.Colors.RED
            page.update()
            return
        status_text.value = "下发4G频段配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        ok = execute_post("BAND_SELECT", {"is_gw_band": "0", "gw_band_mask": "0", "is_lte_band": "1", "lte_band_mask": lte_bands_to_mask(list(lte_selected))})
        if ok:
            status_text.value = "✅ 4G频段设置完成，重启生效"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ft.Colors.RED
        page.update()

    def nr_sa_apply(e):
        if not nr_sa_selected:
            status_text.value = "⚠️ 请至少勾选一个5G SA频段"
            status_text.color = ft.Colors.RED
            page.update()
            return
        status_text.value = "下发5G SA频段配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        ok = execute_post("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {"nr5g_band_mask": ",".join(sorted(nr_sa_selected, key=int)), "type": "0"})
        if ok:
            status_text.value = "✅ 5G SA频段设置完成，重启生效"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ft.Colors.RED
        page.update()

    def nr_nsa_apply(e):
        if not nr_nsa_selected:
            status_text.value = "⚠️ 请至少勾选一个5G NSA频段"
            status_text.color = ft.Colors.RED
            page.update()
            return
        status_text.value = "下发5G NSA频段配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        ok = execute_post("WAN_PERFORM_NR5G_SANSA_BAND_LOCK", {"nr5g_band_mask": ",".join(sorted(nr_nsa_selected, key=int)), "type": "1"})
        if ok:
            status_text.value = "✅ 5G NSA频段设置完成，重启生效"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 设置失败，确认开发者权限已解锁"
            status_text.color = ft.Colors.RED
        page.update()

    def cell_lock_apply(e):
        if not cell_pci.value or not cell_earfcn.value:
            status_text.value = "⚠️ 填写PCI与EARFCN"
            status_text.color = ft.Colors.RED
            page.update()
            return
        status_text.value = "下发锁小区配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        lock_val = f"{cell_pci.value.strip()},{cell_earfcn.value.strip()},{cell_band.value},{cell_scs.value}"
        ok = execute_post("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": lock_val})
        if ok:
            status_text.value = "✅ 锁小区配置下发完成，重启生效"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 锁小区失败，确认开发者权限已解锁"
            status_text.color = ft.Colors.RED
        page.update()

    def cell_unlock_click(e):
        status_text.value = "清除锁小区配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()
        if execute_post("NR5G_LOCK_CELL_SET", {"nr5g_cell_lock": "1,1,1,1"}):
            cell_pci.value = ""
            cell_earfcn.value = ""
            cell_band.value = "1"
            cell_scs.value = "15"
            status_text.value = "✅ 小区锁定已解除"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 解除失败，确认开发者权限已解锁"
            status_text.color = ft.Colors.RED
        page.update()

    # ----------------------------------------------
    # 修复版：定时重启保存逻辑
    # ----------------------------------------------
    def save_schedule_reboot(e):
        status_text.value = "下发定时重启配置..."
        status_text.color = ft.Colors.ORANGE
        page.update()

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

        # 核心修复：使用了你抓包得到的 FIX_TIME_REBOOT_SCHEDULE
        ok = execute_post("FIX_TIME_REBOOT_SCHEDULE", payload)
        if ok:
            status_text.value = "✅ 定时重启配置已保存"
            status_text.color = ft.Colors.GREEN
        else:
            status_text.value = "❌ 保存失败，请检查连接状态"
            status_text.color = ft.Colors.RED
        page.update()


    # ==============================================
    # 登录逻辑
    # ==============================================
    def login_click(e):
        ip = ip_input.value
        pwd = pwd_input.value
        if not pwd:
            login_status.value = "⚠️ 请输入密码"
            login_status.color = ft.Colors.RED
            page.update()
            return
        login_btn.disabled = True
        login_status.value = "登录中..."
        login_status.color = ft.Colors.GREY_700
        page.update()
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
                app_state.update({"session": s, "ip": ip, "rd0": rd0, "rd1": rd1, "password": pwd})
                login_status.value = "解锁开发者权限..."
                page.update()
                unlock_developer()
                login_view.visible = False
                main_view.visible = True
                refresh_data()
            else:
                login_status.value = "❌ 密码错误或账号锁定"
                login_status.color = ft.Colors.RED
        except Exception:
            login_status.value = "❌ 连接失败，检查地址"
            login_status.color = ft.Colors.RED
        login_btn.disabled = False
        page.update()

    # ==============================================
    # UI 控件构建
    # ==============================================
    title = ft.Text("ZTE 高级管家", size=32, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700)
    ip_input = ft.TextField(label="管理地址", value="http://192.168.0.1", width=UI_WIDTH)
    pwd_input = ft.TextField(label="管理员密码", password=True, can_reveal_password=True, width=UI_WIDTH)
    login_status = ft.Text("输入账号密码登录", color=ft.Colors.GREY_500)
    login_btn = ft.ElevatedButton("一键登录", on_click=login_click, width=UI_WIDTH, height=45)
    
    login_view = ft.Column(
        [ft.Container(height=40), title, ft.Container(height=20), ip_input, pwd_input, ft.Container(height=8), login_status, login_btn],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER
    )

    def build_status_row(icon, text_control):
        text_control.expand = True
        return ft.Row([
            ft.Text(icon, size=16, width=28, text_align=ft.TextAlign.CENTER),
            text_control
        ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.START)

    txt_battery = ft.Text("电量: --", size=14)
    txt_network = ft.Text("网络: --", size=14)
    txt_wan_ip  = ft.Text("外网IP: --", size=14)
    txt_users   = ft.Text("接入设备: --", size=14)

    txt_5g_freq = ft.Text("5G 频点: --", size=13, color=ft.Colors.GREY_800)
    txt_5g_pci  = ft.Text("5G PCI: --", size=13, color=ft.Colors.GREY_800)
    txt_5g_rsrp = ft.Text("5G 信号强度: --", size=13, color=ft.Colors.GREY_800)
    txt_5g_sinr = ft.Text("5G 信噪比: --", size=13, color=ft.Colors.GREY_800)

    txt_temp_bat = ft.Text("电池温度: --℃", size=13, color=ft.Colors.GREY_800)
    txt_temp_mdm = ft.Text("4G Modem: --℃", size=13, color=ft.Colors.GREY_800)
    txt_temp_pa  = ft.Text("PA: --℃", size=13, color=ft.Colors.GREY_800)

    row_battery = build_status_row("🔋", txt_battery)
    row_network = build_status_row("📶", txt_network)
    row_wan_ip  = build_status_row("🌐", txt_wan_ip)
    row_users   = build_status_row("👥", txt_users)

    row_5g_freq = build_status_row("📡", txt_5g_freq)
    row_5g_pci  = build_status_row("📍", txt_5g_pci)
    row_5g_rsrp = build_status_row("📶", txt_5g_rsrp)
    row_5g_sinr = build_status_row("⚡", txt_5g_sinr)
    
    temp_col_content = ft.Column([txt_temp_bat, txt_temp_mdm, txt_temp_pa], spacing=4)
    row_temps = build_status_row("🌡️", temp_col_content)
    
    status_text = ft.Text("", color=ft.Colors.RED)
    
    status_card = ft.Container(
        content=ft.Column([
            row_battery, row_network, row_wan_ip, row_users, 
            ft.Divider(height=5),
            row_5g_freq, row_5g_pci, row_5g_rsrp, row_5g_sinr, 
            ft.Divider(height=5),
            row_temps,
            ft.Divider(height=8), status_text
        ], spacing=6),
        padding=15, bgcolor=ft.Colors.BLUE_50, border_radius=10, width=UI_WIDTH
    )

    # ----------------------------------------------
    # ⏱️ 定时重启卡片构建 (无脑暴力显示版，彻底兼容老版本 Flet)
    # ----------------------------------------------
    txt_local_time = ft.Text("设备当前时间: --", size=12, color=ft.Colors.GREY_600)
    reboot_enable = ft.Switch(label="启用定时重启功能", value=False)
    
    reboot_mode = ft.Dropdown(
        label="重启模式 (选择后请填写下方对应的配置)",
        options=[ft.dropdown.Option("1", "1 - 按周自动重启"), ft.dropdown.Option("2", "2 - 按间隔天数")],
        value="1",
        width=INNER_WIDTH
    )

    rb_time_hr = ft.TextField(label="时", width=70, value="02")
    rb_time_min = ft.TextField(label="分", width=70, value="00")
    rb_buffer = ft.TextField(label="缓冲时间", width=90, value="02")
    row_time = ft.Row([rb_time_hr, ft.Text(":", size=20, weight=ft.FontWeight.BOLD), rb_time_min, rb_buffer], spacing=10)

    # 暴力将星期拆分为两行，防止被挤出屏幕
    week_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    week_cbs = [ft.Checkbox(label=w, value=False, data=str(i+1)) for i, w in enumerate(week_days)]
    row_weeks_1 = ft.Row(week_cbs[:4], spacing=0)
    row_weeks_2 = ft.Row(week_cbs[4:], spacing=0)

    rb_interval = ft.Dropdown(label="间隔天数", options=[ft.dropdown.Option(str(i), str(i)) for i in range(1, 31)], value="1", width=120)

    btn_save_reboot = ft.ElevatedButton("保存重启规则", on_click=save_schedule_reboot, width=INNER_WIDTH)

    reboot_card = ft.Container(
        content=ft.Column([
            ft.Text("⏱️ 定时重启规则", size=18, weight=ft.FontWeight.BOLD),
            txt_local_time,
            ft.Divider(height=5),
            reboot_enable,
            row_time,
            reboot_mode,
            ft.Divider(height=5),
            
            # 不再隐藏任何组件，全部常驻显示！通过文字提示用户
            ft.Text("🔹 选项A: 按周触发 (仅在重启模式选 1 时生效)", size=13, color=ft.Colors.BLUE_700, weight=ft.FontWeight.BOLD),
            row_weeks_1,
            row_weeks_2,
            
            ft.Container(height=5),
            
            ft.Text("🔹 选项B: 间隔触发 (仅在重启模式选 2 时生效)", size=13, color=ft.Colors.ORANGE_700, weight=ft.FontWeight.BOLD),
            rb_interval,
            
            ft.Container(height=10),
            btn_save_reboot
        ], spacing=10),
        padding=15, bgcolor=ft.Colors.GREY_100, border_radius=10, width=UI_WIDTH
    )

    # ----------------------------------------------
    # 原有的高级设置卡片
    # ----------------------------------------------
    wifi_sleep = ft.Dropdown(label="WiFi空闲休眠", width=INNER_WIDTH, options=[
        ft.dropdown.Option("0", "永不休眠"), ft.dropdown.Option("5", "5分钟"),
        ft.dropdown.Option("10", "10分钟"), ft.dropdown.Option("20", "20分钟"),
        ft.dropdown.Option("30", "30分钟"), ft.dropdown.Option("60", "1小时"),
        ft.dropdown.Option("120", "2小时"),
    ], value="10")
    btn_wifi_sleep = ft.ElevatedButton("保存休眠设置", on_click=wifi_sleep_click, width=INNER_WIDTH)

    lte_grid = create_checkbox_grid(LTE_BANDS, "B", lte_selected, lte_checkboxes, lte_checkbox_change)
    sa_grid = create_checkbox_grid(NR_SA_BANDS, "N", nr_sa_selected, sa_checkboxes, sa_checkbox_change)
    nsa_grid = create_checkbox_grid(NR_NSA_BANDS, "N", nr_nsa_selected, nsa_checkboxes, nsa_checkbox_change)

    btn_lte_apply = ft.ElevatedButton("应用 4G 锁频段", on_click=lte_band_apply, width=INNER_WIDTH)
    btn_sa_apply = ft.ElevatedButton("应用 5G SA 锁频段", on_click=nr_sa_apply, width=INNER_WIDTH)
    btn_nsa_apply = ft.ElevatedButton("应用 5G NSA 锁频段", on_click=nr_nsa_apply, width=INNER_WIDTH)

    cell_pci = ft.TextField(width=INPUT_W)
    row_pci = ft.Row([
        ft.Row([ft.Text("PCI"), ft.Text("*", color=ft.Colors.RED)], spacing=2, width=LABEL_W),
        cell_pci
    ], spacing=10)

    cell_earfcn = ft.TextField(width=INPUT_W)
    row_earfcn = ft.Row([
        ft.Row([ft.Text("EARFCN"), ft.Text("*", color=ft.Colors.RED)], spacing=2, width=LABEL_W),
        cell_earfcn
    ], spacing=10)

    cell_band = ft.Dropdown(width=INPUT_W, options=[
        ft.dropdown.Option("1", "频段 1"), ft.dropdown.Option("3", "频段 3"),
        ft.dropdown.Option("28", "频段 28"), ft.dropdown.Option("41", "频段 41"),
        ft.dropdown.Option("78", "频段 78"),
    ], value="1")
    row_band = ft.Row([ft.Text("BAND", width=LABEL_W), cell_band], spacing=10)

    cell_scs = ft.Dropdown(width=INPUT_W, options=[
        ft.dropdown.Option("15", "15KHz"), ft.dropdown.Option("30", "30KHz"), ft.dropdown.Option("60", "60KHz"),
    ], value="15")
    row_scs = ft.Row([ft.Text("SCS", width=LABEL_W), cell_scs], spacing=10)

    cell_tip = ft.Text("设备重启后生效", size=13, color=ft.Colors.GREY_700, width=INNER_WIDTH, text_align="center")
    
    btn_cell_apply = ft.ElevatedButton("应用锁小区", on_click=cell_lock_apply, width=INNER_WIDTH, height=45)
    btn_cell_unlock = ft.ElevatedButton("清除锁定", on_click=cell_unlock_click, width=180, height=45, color=ft.Colors.ORANGE)
    btn_cell_reboot = ft.ElevatedButton("重启设备", on_click=reboot_click, width=180, height=45, color=ft.Colors.RED)

    btn_refresh = ft.ElevatedButton("刷新设备数据", icon=ft.Icons.REFRESH, on_click=refresh_data, width=195)
    btn_reboot_top = ft.ElevatedButton("重启设备", icon=ft.Icons.POWER_SETTINGS_NEW, color=ft.Colors.RED, on_click=reboot_click)

    setting_card = ft.Container(
        content=ft.Column([
            ft.Text("⚙️ 高级网络设置", size=18, weight=ft.FontWeight.BOLD),
            ft.Divider(height=10),
            ft.Text("📶 WiFi省电休眠", weight=ft.FontWeight.BOLD),
            wifi_sleep, btn_wifi_sleep,
            ft.Container(height=15),

            ft.Text("📡 网络频段锁定", weight=ft.FontWeight.BOLD),
            ft.Divider(height=5),

            ft.Text("🔹 4G LTE 频段", size=13, weight=ft.FontWeight.W_500),
            lte_grid, btn_lte_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G SA 频段", size=13, weight=ft.FontWeight.W_500),
            sa_grid, btn_sa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G NSA 频段", size=13, weight=ft.FontWeight.W_500),
            nsa_grid, btn_nsa_apply,
            ft.Container(height=10),

            ft.Text("🔹 5G 锁定小区", size=14, weight=ft.FontWeight.BOLD),
            ft.Divider(height=5),
            row_pci,
            row_earfcn,
            row_band,
            row_scs,
            cell_tip,
            btn_cell_apply,
            ft.Row([btn_cell_unlock, btn_cell_reboot], spacing=10),
        ], spacing=12),
        padding=15, bgcolor=ft.Colors.GREY_100, border_radius=10, width=UI_WIDTH
    )

    main_view = ft.Column(
        [
            ft.Container(height=20),
            ft.Text("📊 设备状态", size=24, weight=ft.FontWeight.BOLD),
            status_card,
            ft.Row([btn_refresh, btn_reboot_top], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            ft.Container(height=10),
            
            reboot_card,
            ft.Container(height=10),
            
            setting_card,
            ft.Container(height=30)
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        visible=False
    )

    page.add(login_view, main_view)

ft.app(target=main)
