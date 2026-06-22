# 中兴 MU5001 第三方控制面板

基于 Python 与 Flet 框架编写的轻量级、可视化的中兴 MU5001 随身 WiFi 管理面板。支持免密缓存、自动解锁开发者选项，让你更直观地监控设备状态并进行高级网络配置。

## 📱 界面预览

<p align="center">
  <table>
    <tr>
      <td align="center">
        <img src="https://github.com/user-attachments/assets/13299051-7b7f-4c0b-aa14-47fc8a49088e" width="150" alt="界面预览 1"/><br/>
        <sub>登录界面</sub>
      </td>
      <td align="center">
        <img src="https://github.com/user-attachments/assets/ab538b7f-15ee-4c11-b0b8-8d37cc6c9b5a" width="180" alt="界面预览 2"/><br/>
        <sub>状态监控面板
      </td>
      <td align="center">
        <img src="https://github.com/user-attachments/assets/adb658ee-e61b-4de2-8174-3bba602213fd" width="180" alt="界面预览 3"/><br/>
        <sub>定时重启设置</sub>
      </td>
      <td align="center">
        <img src="https://github.com/user-attachments/assets/b47ab5eb-4c48-4a72-afb3-846a71b67cde" width="180" alt="界面预览 4"/><br/>
        <sub>网络锁频</sub>
      </td>
      <td align="center">
        <img src="https://github.com/user-attachments/assets/7047e542-494e-4b54-8b5c-4b32d5b66114" width="180" alt="界面预览 5"/><br/>
        <sub>基站锁定</sub>
      </td>
    </tr>
  </table>
</p>

##  核心功能

### 实时状态监控
* **网络与流量**：实时监控上传/下载网速、本次与当月流量消耗情况。
* **设备健康度**：直观展示电池电量、充电状态，以及设备内部核心温度（电池、4G Modem、PA）。
* **信号质量仪**：显示 4G/5G 信号参数，包括所在频点、PCI、信号强度 (RSRP) 与信噪比 (SINR)。
* **终端统计**：一键查看当前局域网内的接入设备总数。

### 高级网络设置 (自动解锁开发者选项)
* **频段锁定**：支持自定义勾选并应用 4G LTE、5G SA、5G NSA 频段。
* **基站锁定**：支持强制锁定指定的小区基站（自定义 PCI、EARFCN、Band 与 SCS）。

### 自动化功能
* **定时重启**：支持按周循环或按间隔天数配置设备的自动重启时间。
* **休眠助手**：支持设置 WiFi 空闲状态时自动休眠时间。

## 如何运行

本项目基于 Python，请确保你的环境中已安装 Python 3.x，并安装必要的依赖库。

### 1. 安装依赖 (仅首次运行需要)

```bash
pip install flet requests
```

### 2. 启动面板

```bash
python main.py
```
## 下载预编译版本 (推荐)

如果你不想配置 Python 环境，可以直接下载已经编译好的 App 文件：

1. 前往本仓库的 [Actions](https://github.com/xjw1229/mu5001/actions) 页面。
2. 找到最新一次构建成功（打绿勾 ✅）的记录。
   *(注：如果最新一次更新只修改了说明文档，可能不会生成安装包，请往下找构建成功的记录)*
3. 点进该记录，在页面最下方的 `Artifacts` 区域下载压缩包，解压后即可安装。

**更新注意事项：**
由于自动编译的签名变化，如果在覆盖安装时遇到“签名冲突”或“应用未安装”的提示，**请先卸载旧版本，再进行安装**。
