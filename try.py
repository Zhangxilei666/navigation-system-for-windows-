import sys
import serial
import serial.tools.list_ports
import threading
import time
import numpy as np
from datetime import datetime
from collections import deque
import struct
import folium
import tempfile
import os

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from folium.plugins import MarkerCluster, MiniMap, Fullscreen, LocateControl
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
import pyqtgraph.opengl as gl
import math
from geographiclib.geodesic import Geodesic

# ==================== 卫星地图部件（使用国内可用地图）====================

class SatelliteMapWidget(QWidget):
    """卫星地图显示部件（使用国内可访问地图）"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.map = None
        self.marker = None
        self.trajectory_points = []
        self.temp_file = None
        self.current_heading = 0
        self.init_map(29.8192, 106.4272, 15)  # 西南大学初始位置
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # 控制按钮
        control_container = QWidget()
        control_layout = QHBoxLayout(control_container)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        # 地图类型选择 - 使用国内可访问的地图
        control_layout.addWidget(QLabel('地图类型:'))
        self.map_type_combo = QComboBox()
        self.map_type_combo.addItems([
            '高德街道图',
            '高德卫星图',
            'OpenStreetMap',
            '天地图街道',
            '腾讯街道图'
        ])
        self.map_type_combo.setCurrentText('高德街道图')
        self.map_type_combo.setMaximumWidth(130)
        control_layout.addWidget(self.map_type_combo)
        
        # 操作按钮
        self.zoom_in_btn = QPushButton('+')
        self.zoom_in_btn.setMaximumWidth(35)
        self.zoom_out_btn = QPushButton('-')
        self.zoom_out_btn.setMaximumWidth(35)
        self.fit_btn = QPushButton('适应视图')
        self.fit_btn.setMinimumWidth(70)
        self.clear_btn = QPushButton('清空轨迹')
        self.clear_btn.setMinimumWidth(70)
        self.export_btn = QPushButton('导出地图')
        self.export_btn.setMinimumWidth(70)
        
        control_layout.addWidget(self.zoom_in_btn)
        control_layout.addWidget(self.zoom_out_btn)
        control_layout.addWidget(self.fit_btn)
        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.export_btn)
        control_layout.addStretch()
        
        layout.addWidget(control_container)
        
        # Web视图用于显示地图
        self.web_view = QWebEngineView()
        
        # 设置用户代理，兼容在线地图
        self.web_view.page().profile().setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 启用本地存储
        self.web_view.page().profile().setPersistentCookiesPolicy(
            QWebEngineProfile.AllowPersistentCookies
        )
        
        layout.addWidget(self.web_view)
        
        # 连接信号
        self.map_type_combo.currentTextChanged.connect(self.change_map_type)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.fit_btn.clicked.connect(self.fit_view)
        self.clear_btn.clicked.connect(self.clear_trajectory)
        self.export_btn.clicked.connect(self.export_map)
        
    def init_map(self, lat=29.8192, lon=106.4272, zoom=15):
        """初始化地图 - 使用西南大学作为初始位置"""
        # 获取地图类型配置
        map_type = self.map_type_combo.currentText() if hasattr(self, 'map_type_combo') else '高德街道图'
        
        # 定义国内可用的地图瓦片
        tiles_config = {
            '高德街道图': {
                'tiles': 'https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
                'attr': '高德地图',
                'max_zoom': 18
            },
            '高德卫星图': {
                'tiles': 'https://webst01.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
                'attr': '高德地图',
                'max_zoom': 18
            },
            'OpenStreetMap': {
                'tiles': 'OpenStreetMap',
                'attr': '© OpenStreetMap contributors',
                'max_zoom': 19
            },
            '天地图街道': {
                'tiles': 'https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=您的密钥',
                'attr': '天地图',
                'max_zoom': 18
            },
            '腾讯街道图': {
                'tiles': 'https://rt0.map.gtimg.com/realtimerender?z={z}&x={x}&y={y}&type=vector&style=0',
                'attr': '腾讯地图',
                'max_zoom': 18
            }
        }
        
        config = tiles_config.get(map_type, tiles_config['高德街道图'])
        
        # 创建地图
        self.map = folium.Map(
            location=[lat, lon],
            zoom_start=zoom,
            control_scale=True,
            tiles=config['tiles'] if map_type not in ['OpenStreetMap'] else config['tiles'],
            attr=config['attr'],
            max_zoom=config.get('max_zoom', 18)
        )
        
        # 添加插件
        minimap = MiniMap()
        self.map.add_child(minimap)
        
        fullscreen = Fullscreen()
        self.map.add_child(fullscreen)
        
        locate = LocateControl()
        self.map.add_child(locate)
        
        # 创建标记集群
        self.marker_cluster = MarkerCluster().add_to(self.map)
        
        # 添加西南大学标记
        swu_marker = folium.Marker(
            location=[29.8192, 106.4272],
            popup='西南大学<br>重庆市北碚区',
            icon=folium.Icon(color='blue', icon='university', prefix='fa')
        ).add_to(self.map)
        
        # 保存到临时文件并加载
        self.refresh_map()
        
    def refresh_map(self):
        """刷新地图显示"""
        if self.map is None:
            return
            
        try:
            # 保存到临时HTML文件
            if self.temp_file and os.path.exists(self.temp_file):
                try:
                    os.remove(self.temp_file)
                except:
                    pass
                    
            # 创建新的临时文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                self.temp_file = f.name
                # 获取HTML内容并添加必要的CSS和JavaScript
                html_content = self.map._repr_html_()
                
                # 添加自定义JavaScript用于更新位置和航向
                custom_js = """
                <script>
                // 添加自定义函数来更新位置标记
                function updatePosition(lat, lng, heading, speed) {
                    if (window.currentMarker) {
                        window.map.removeLayer(window.currentMarker);
                    }
                    
                    // 创建带航向的标记
                    var icon = L.divIcon({
                        html: '<div style="transform: rotate(' + heading + 'deg); color: red; font-size: 24px;">➤</div>',
                        iconSize: [30, 30],
                        iconAnchor: [15, 15],
                        className: 'custom-arrow-marker'
                    });
                    
                    window.currentMarker = L.marker([lat, lng], {icon: icon}).addTo(window.map);
                    
                    // 添加弹窗信息
                    var popupContent = '<b>当前位置</b><br>' +
                                       '纬度: ' + lat.toFixed(6) + '<br>' +
                                       '经度: ' + lng.toFixed(6) + '<br>' +
                                       '航向: ' + heading.toFixed(1) + '°<br>' +
                                       '速度: ' + speed.toFixed(1) + ' m/s<br>' +
                                       '时间: ' + new Date().toLocaleTimeString();
                    window.currentMarker.bindPopup(popupContent);
                    
                    // 自动弹窗
                    window.currentMarker.openPopup();
                    
                    // 将视图移动到新位置
                    window.map.setView([lat, lng], window.map.getZoom());
                }
                
                // 添加轨迹线
                function updateTrajectory(points) {
                    if (window.trajectoryLine) {
                        window.map.removeLayer(window.trajectoryLine);
                    }
                    
                    if (points.length > 1) {
                        window.trajectoryLine = L.polyline(points, {
                            color: 'blue',
                            weight: 3,
                            opacity: 0.7
                        }).addTo(window.map);
                    }
                }
                
                // 添加农田路径
                function updateFarmPath(points) {
                    if (window.farmPathLine) {
                        window.map.removeLayer(window.farmPathLine);
                    }
                    
                    if (points.length > 1) {
                        window.farmPathLine = L.polyline(points, {
                            color: 'green',
                            weight: 4,
                            opacity: 0.8,
                            dashArray: '5, 10'
                        }).addTo(window.map);
                        
                        // 添加起点和终点标记
                        if (window.startMarker) window.map.removeLayer(window.startMarker);
                        if (window.endMarker) window.map.removeLayer(window.endMarker);
                        
                        if (points.length >= 2) {
                            window.startMarker = L.marker(points[0], {
                                icon: L.divIcon({
                                    html: '<div style="color: green; font-size: 20px;">▶</div>',
                                    iconSize: [20, 20]
                                })
                            }).addTo(window.map).bindPopup('起点');
                            
                            window.endMarker = L.marker(points[points.length-1], {
                                icon: L.divIcon({
                                    html: '<div style="color: red; font-size: 20px;">■</div>',
                                    iconSize: [20, 20]
                                })
                            }).addTo(window.map).bindPopup('终点');
                        }
                    }
                }
                </script>
                """
                
                # 确保地图占满整个容器
                html_content = html_content.replace(
                    '<style>',
                    '''<style>
                    html, body {
                        width: 100%;
                        height: 100%;
                        margin: 0;
                        padding: 0;
                        overflow: hidden;
                    }
                    #map {
                        width: 100% !important;
                        height: 100% !important;
                    }
                    .custom-arrow-marker {
                        background: transparent !important;
                        border: none !important;
                    }
                    '''
                )
                
                # 将JavaScript添加到HTML中
                html_content = html_content.replace('</body>', custom_js + '</body>')
                
                # 添加初始化JavaScript变量
                init_js = """
                <script>
                // 初始化全局变量
                window.map = map;
                window.currentMarker = null;
                window.trajectoryLine = null;
                window.farmPathLine = null;
                window.startMarker = null;
                window.endMarker = null;
                </script>
                """
                html_content = html_content.replace('<script>', init_js + '<script>', 1)
                
                f.write(html_content)
            
            # 加载HTML文件
            file_url = QUrl.fromLocalFile(self.temp_file)
            self.web_view.setUrl(file_url)
            
        except Exception as e:
            print(f"刷新地图时出错: {e}")
            # 显示错误信息
            error_html = f'''
            <html>
            <head>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        margin: 20px;
                        padding: 20px;
                        background-color: #f9f9f9;
                        color: #333;
                    }}
                    .error-container {{
                        border: 1px solid #ccc;
                        padding: 20px;
                        border-radius: 5px;
                        background-color: white;
                    }}
                    .error-title {{
                        color: #d9534f;
                        margin-bottom: 10px;
                    }}
                </style>
            </head>
            <body>
                <div class="error-container">
                    <h2 class="error-title">地图加载失败</h2>
                    <p><strong>错误信息:</strong> {str(e)}</p>
                    <p><strong>建议:</strong></p>
                    <ul>
                        <li>检查网络连接</li>
                        <li>尝试使用不同的地图类型</li>
                        <li>重启应用程序</li>
                    </ul>
                </div>
            </body>
            </html>
            '''
            self.web_view.setHtml(error_html)
            
    def update_position(self, lat, lon, heading=0, speed=0):
        """更新位置标记"""
        if self.map is None or lat == 0 or lon == 0:
            return
            
        try:
            # 保存当前航向
            self.current_heading = heading
            
            # 添加轨迹点
            self.trajectory_points.append([lat, lon])
            
            # 通过JavaScript更新位置和轨迹
            js_code = f"""
            updatePosition({lat}, {lon}, {heading}, {speed});
            """
            
            if len(self.trajectory_points) > 1:
                # 将轨迹点转换为JavaScript数组格式
                traj_js = "[" + ",".join([f"[{p[0]},{p[1]}]" for p in self.trajectory_points]) + "]"
                js_code += f"""
                updateTrajectory({traj_js});
                """
            
            # 执行JavaScript
            self.web_view.page().runJavaScript(js_code)
            
        except Exception as e:
            print(f"更新地图位置时出错: {e}")
            
    def add_farm_path(self, path_points):
        """添加农田路径"""
        if not path_points or self.map is None:
            return
            
        try:
            # 将路径点转换为纬度,经度格式
            locations = [[lat, lon] for lon, lat in path_points]
            
            # 通过JavaScript更新农田路径
            path_js = "[" + ",".join([f"[{p[0]},{p[1]}]" for p in locations]) + "]"
            js_code = f"""
            updateFarmPath({path_js});
            """
            
            self.web_view.page().runJavaScript(js_code)
        except Exception as e:
            print(f"添加农田路径时出错: {e}")
        
    def change_map_type(self, map_type):
        """更改地图类型"""
        if self.map is None:
            return
            
        try:
            # 保存当前的轨迹点和农田路径
            saved_trajectory = self.trajectory_points.copy()
            
            # 重新初始化地图
            if self.trajectory_points:
                last_point = self.trajectory_points[-1]
                self.init_map(last_point[0], last_point[1], self.map.options.get('zoom', 15))
            else:
                self.init_map(29.8192, 106.4272, 15)  # 西南大学
                
            # 恢复轨迹点
            self.trajectory_points = saved_trajectory
            
            # 如果有轨迹点，重新绘制轨迹
            if len(self.trajectory_points) > 1:
                traj_js = "[" + ",".join([f"[{p[0]},{p[1]}]" for p in self.trajectory_points]) + "]"
                self.web_view.page().runJavaScript(f"updateTrajectory({traj_js});")
                
            # 重新添加农田路径（如果存在）
            if hasattr(self, 'farm_path_line') and self.farm_path_line:
                # 这里需要保存农田路径数据，代码中需要实现
                pass
                
        except Exception as e:
            print(f"切换地图类型时出错: {e}")
            QMessageBox.warning(self, "地图加载失败", 
                              f"加载{map_type}失败，请检查网络连接或尝试其他地图类型。错误: {str(e)}")
            self.map_type_combo.setCurrentText('高德街道图')
            
    def zoom_in(self):
        """放大"""
        try:
            self.web_view.page().runJavaScript("map.setZoom(map.getZoom() + 1);")
        except Exception as e:
            print(f"放大时出错: {e}")
            
    def zoom_out(self):
        """缩小"""
        try:
            self.web_view.page().runJavaScript("map.setZoom(map.getZoom() - 1);")
        except Exception as e:
            print(f"缩小时出错: {e}")
            
    def fit_view(self):
        """适应视图到所有标记"""
        if not self.trajectory_points:
            return
            
        try:
            # 计算边界
            lats = [p[0] for p in self.trajectory_points]
            lons = [p[1] for p in self.trajectory_points]
            
            if lats and lons:
                bounds = [[min(lats), min(lons)], [max(lats), max(lons)]]
                
                # 通过JavaScript设置视图
                js_code = f"""
                var bounds = L.latLngBounds(
                    [{bounds[0][0]}, {bounds[0][1]}],
                    [{bounds[1][0]}, {bounds[1][1]}]
                );
                map.fitBounds(bounds, {{padding: [20, 20]}});
                """
                self.web_view.page().runJavaScript(js_code)
        except Exception as e:
            print(f"适应视图时出错: {e}")
            
    def clear_trajectory(self):
        """清空轨迹"""
        self.trajectory_points = []
        
        # 通过JavaScript清除轨迹
        try:
            self.web_view.page().runJavaScript("""
            if (window.trajectoryLine) {
                window.map.removeLayer(window.trajectoryLine);
                window.trajectoryLine = null;
            }
            if (window.currentMarker) {
                window.map.removeLayer(window.currentMarker);
                window.currentMarker = null;
            }
            """)
        except Exception as e:
            print(f"清除轨迹时出错: {e}")
            
    def export_map(self):
        """导出地图为HTML文件"""
        if not self.map:
            return
            
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "保存地图", f"satellite_map_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html", 
                "HTML文件 (*.html);;所有文件 (*)"
            )
            
            if file_path:
                self.map.save(file_path)
                QMessageBox.information(self, "成功", f"地图已保存到: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存地图失败: {str(e)}")
            
    def closeEvent(self, event):
        """清理临时文件"""
        try:
            if self.temp_file and os.path.exists(self.temp_file):
                os.remove(self.temp_file)
        except:
            pass
        super().closeEvent(event)

# ==================== 数据解析类 ====================

class G60_Parser:
    """G60 GPS/BDS模块数据解析器 (NMEA0183协议)"""
    
    def __init__(self):
        self.latitude = 0.0
        self.longitude = 0.0
        self.altitude = 0.0
        self.speed = 0.0
        self.course = 0.0
        self.satellites = 0
        self.hdop = 0.0
        self.fix_quality = 0
        self.utc_time = ""
        self.date = ""
        self.valid = False
        self.raw_data = ""
        self.satellite_system = ""  # 卫星系统：GPS, BDS, GNSS
        self.bds_satellites = 0    # 北斗卫星数
        
    def parse_nmea(self, data):
        """解析NMEA语句"""
        try:
            if not data.startswith('$'):
                return False
                
            self.raw_data = data.strip()
            parts = data.strip().split(',')
            sentence_type = parts[0]
            
            # 识别卫星系统
            if sentence_type.startswith('$BD'):
                self.satellite_system = "BDS"
            elif sentence_type.startswith('$GP'):
                self.satellite_system = "GPS"
            elif sentence_type.startswith('$GN'):
                self.satellite_system = "GNSS"
            else:
                self.satellite_system = "Unknown"
            
            # 解析GGA语句 (支持GPS/BDS/GNSS)
            if sentence_type in ['$GNGGA', '$GPGGA', '$BDGGA']:
                # GGA - GPS/BDS定位数据
                if len(parts) >= 10:
                    # UTC时间
                    if parts[1]:
                        self.utc_time = parts[1][:2] + ":" + parts[1][2:4] + ":" + parts[1][4:6]
                    
                    # 纬度
                    if parts[2] and parts[3]:
                        lat = float(parts[2])
                        lat_deg = int(lat / 100)
                        lat_min = lat - lat_deg * 100
                        self.latitude = lat_deg + lat_min / 60
                        if parts[3] == 'S':
                            self.latitude = -self.latitude
                    
                    # 经度
                    if parts[4] and parts[5]:
                        lon = float(parts[4])
                        lon_deg = int(lon / 100)
                        lon_min = lon - lon_deg * 100
                        self.longitude = lon_deg + lon_min / 60
                        if parts[5] == 'W':
                            self.longitude = -self.longitude
                    
                    # 定位质量
                    if parts[6]:
                        self.fix_quality = int(parts[6])
                        self.valid = (self.fix_quality > 0)
                    
                    # 卫星数
                    if parts[7]:
                        self.satellites = int(parts[7])
                    
                    # HDOP
                    if parts[8]:
                        self.hdop = float(parts[8])
                    
                    # 海拔
                    if parts[9]:
                        self.altitude = float(parts[9])
                    
                    return True
                    
            # 解析RMC语句 (支持GPS/BDS/GNSS)
            elif sentence_type in ['$GNRMC', '$GPRMC', '$BDRMC']:
                # RMC - 推荐最小定位信息
                if len(parts) >= 10 and parts[2] == 'A':  # 数据有效
                    # 纬度
                    if parts[3] and parts[4]:
                        lat = float(parts[3])
                        lat_deg = int(lat / 100)
                        lat_min = lat - lat_deg * 100
                        self.latitude = lat_deg + lat_min / 60
                        if parts[4] == 'S':
                            self.latitude = -self.latitude
                    
                    # 经度
                    if parts[5] and parts[6]:
                        lon = float(parts[5])
                        lon_deg = int(lon / 100)
                        lon_min = lon - lon_deg * 100
                        self.longitude = lon_deg + lon_min / 60
                        if parts[6] == 'W':
                            self.longitude = -self.longitude
                    
                    # 速度（节转换为米/秒）
                    if parts[7]:
                        self.speed = float(parts[7]) * 0.514444
                    
                    # 航向
                    if parts[8]:
                        self.course = float(parts[8])
                    
                    # 日期
                    if parts[9]:
                        self.date = parts[9]
                    
                    self.valid = True
                    return True
                    
            # 解析北斗特有的GSA语句
            elif sentence_type == '$BDGSA':
                # GSA - 精度因子和活动卫星
                if len(parts) >= 18:
                    # 解析北斗使用的卫星
                    self.bds_satellites = len([p for p in parts[3:15] if p and int(p) > 0])
                    return True
                    
            # 解析北斗GSV语句
            elif sentence_type == '$BDGSV':
                # GSV - 卫星状态信息
                # 可以解析可见北斗卫星的详细信息
                return True
                    
        except Exception as e:
            print(f"G60解析错误: {e}")
            
        return False

class H30_Parser:
    """H30惯导模块数据解析器 (Yesense协议)"""
    
    def __init__(self):
        # 姿态数据
        self.roll = 0.0      # 横滚角
        self.pitch = 0.0     # 俯仰角
        self.yaw = 0.0       # 航向角
        # 角速度
        self.gyro_x = 0.0
        self.gyro_y = 0.0
        self.gyro_z = 0.0
        # 加速度
        self.acc_x = 0.0
        self.acc_y = 0.0
        self.acc_z = 0.0
        # 磁场
        self.mag_x = 0.0
        self.mag_y = 0.0
        self.mag_z = 0.0
        # 其他
        self.temperature = 0.0
        self.timestamp = 0
        self.valid = False
        self.raw_data = b''
        
        self.data_buffer = bytearray()
        
    def parse_yesense(self, data):
        """解析Yesense协议数据"""
        self.data_buffer.extend(data)
        
        while len(self.data_buffer) >= 7:  # 最小帧长度
            # 查找帧头 0x59, 0x53
            try:
                start_idx = self.data_buffer.find(b'\x59\x53')
                if start_idx == -1:
                    self.data_buffer.clear()
                    break
                    
                if start_idx > 0:
                    self.data_buffer = self.data_buffer[start_idx:]
                    
                if len(self.data_buffer) < 7:
                    break
                    
                # 解析帧长度
                data_len = self.data_buffer[4]
                frame_len = 7 + data_len  # 帧头2+TID2+长度1+数据+校验2
                
                if len(self.data_buffer) < frame_len:
                    break
                    
                # 获取完整帧
                frame = self.data_buffer[:frame_len]
                self.data_buffer = self.data_buffer[frame_len:]
                
                # 计算校验和
                ck1, ck2 = self.calculate_checksum(frame[2:-2])
                if ck1 != frame[-2] or ck2 != frame[-1]:
                    continue  # 校验失败
                
                # 解析数据域
                data_field = frame[5:-2]
                self.parse_data_field(data_field)
                
            except Exception as e:
                print(f"H30解析错误: {e}")
                break
                
    def calculate_checksum(self, data):
        """计算Yesense协议校验和"""
        ck1 = 0
        ck2 = 0
        for byte in data:
            ck1 = (ck1 + byte) & 0xFF
            ck2 = (ck2 + ck1) & 0xFF
        return ck1, ck2
        
    def parse_data_field(self, data):
        """解析数据域"""
        idx = 0
        while idx < len(data):
            if idx + 1 >= len(data):
                break
                
            data_id = data[idx]
            data_len = data[idx + 1]
            
            if idx + 2 + data_len > len(data):
                break
                
            data_bytes = data[idx + 2:idx + 2 + data_len]
            
            # 解析不同类型的數據
            if data_id == 0x01:  # IMU温度
                if data_len == 2:
                    self.temperature = struct.unpack('<h', data_bytes)[0] * 0.01
                    
            elif data_id == 0x10:  # 加速度
                if data_len == 12:
                    self.acc_x = struct.unpack('<i', data_bytes[0:4])[0] * 0.000001
                    self.acc_y = struct.unpack('<i', data_bytes[4:8])[0] * 0.000001
                    self.acc_z = struct.unpack('<i', data_bytes[8:12])[0] * 0.000001
                    
            elif data_id == 0x20:  # 角速度
                if data_len == 12:
                    self.gyro_x = struct.unpack('<i', data_bytes[0:4])[0] * 0.000001
                    self.gyro_y = struct.unpack('<i', data_bytes[4:8])[0] * 0.000001
                    self.gyro_z = struct.unpack('<i', data_bytes[8:12])[0] * 0.000001
                    
            elif data_id == 0x40:  # 欧拉角
                if data_len == 12:
                    self.pitch = struct.unpack('<i', data_bytes[0:4])[0] * 0.000001
                    self.roll = struct.unpack('<i', data_bytes[4:8])[0] * 0.000001
                    self.yaw = struct.unpack('<i', data_bytes[8:12])[0] * 0.000001
                    self.valid = True
                    
            elif data_id == 0x41:  # 四元数
                if data_len == 16:
                    # 四元数数据，可以用于更精确的姿态计算
                    pass
                    
            idx += 2 + data_len

# ==================== 串口通信线程 ====================

class SerialThread(QThread):
    """串口通信线程"""
    
    data_received = pyqtSignal(str, object)  # 设备类型, 数据
    
    def __init__(self, device_type, port, baudrate):
        super().__init__()
        self.device_type = device_type  # 'G60' 或 'H30'
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False
        self.parser = G60_Parser() if device_type == 'G60' else H30_Parser()
        
    def run(self):
        """线程主循环"""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1
            )
            self.running = True
            
            while self.running:
                if self.device_type == 'G60':
                    # G60使用文本模式读取
                    if self.serial.in_waiting:
                        try:
                            line = self.serial.readline().decode('ascii', errors='ignore')
                            if line and self.parser.parse_nmea(line):
                                self.data_received.emit('G60', self.parser)
                        except:
                            pass
                else:
                    # H30使用二进制模式读取
                    if self.serial.in_waiting:
                        try:
                            data = self.serial.read(self.serial.in_waiting)
                            self.parser.parse_yesense(data)
                            if self.parser.valid:
                                self.data_received.emit('H30', self.parser)
                        except:
                            pass
                
                time.sleep(0.001)  # 短暂休眠，避免占用太多CPU
                
        except Exception as e:
            print(f"串口错误: {e}")
            self.data_received.emit('ERROR', str(e))
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()
                
    def stop(self):
        """停止线程"""
        self.running = False
        self.wait()

# ==================== 3D姿态显示部件 ====================

class AttitudeIndicator3D(QWidget):
    """3D姿态指示器"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        
        # 创建3D视图
        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.setCameraPosition(distance=5)
        
        # 创建坐标系
        self.create_axes()
        
        # 创建履带底盘模型
        self.create_tracked_vehicle()
        
        # 添加参考网格
        grid = gl.GLGridItem()
        grid.setSize(4, 4, 1)
        grid.setSpacing(0.5, 0.5, 0.5)
        self.gl_widget.addItem(grid)
        
        layout.addWidget(self.gl_widget)
        
    def create_axes(self):
        """创建坐标轴"""
        # 使用标准的GLAxisItem，但进行一些自定义
        axis = gl.GLAxisItem()
        axis.setSize(2, 2, 2)
        
        # 修改轴的颜色和宽度
        axis_lines = axis.children()
        if axis_lines:
            # X轴 (红色)
            if len(axis_lines) > 0:
                axis_lines[0].setData(color=pg.mkColor(255, 0, 0), width=3)
            
            # Y轴 (绿色)
            if len(axis_lines) > 1:
                axis_lines[1].setData(color=pg.mkColor(0, 255, 0), width=3)
            
            # Z轴 (蓝色)
            if len(axis_lines) > 2:
                axis_lines[2].setData(color=pg.mkColor(0, 0, 255), width=3)
        
        self.gl_widget.addItem(axis)
        
        # 添加轴标签（使用GLTextItem）
        # X轴标签
        x_label = gl.GLTextItem(pos=(2.2, 0, 0), text='X', color=(1, 0, 0, 1), font=QtGui.QFont('Arial', 12))
        self.gl_widget.addItem(x_label)
        
        # Y轴标签
        y_label = gl.GLTextItem(pos=(0, 2.2, 0), text='Y', color=(0, 1, 0, 1), font=QtGui.QFont('Arial', 12))
        self.gl_widget.addItem(y_label)
        
        # Z轴标签
        z_label = gl.GLTextItem(pos=(0, 0, 2.2), text='Z', color=(0, 0, 1, 1), font=QtGui.QFont('Arial', 12))
        self.gl_widget.addItem(z_label)
        
        # 添加轴名称标签
        x_name = gl.GLTextItem(pos=(1.0, -0.3, -0.3), text='Roll', color=(0.8, 0.8, 0.8, 0.8), font=QtGui.QFont('Arial', 10))
        self.gl_widget.addItem(x_name)
        
        y_name = gl.GLTextItem(pos=(-0.3, 1.0, -0.3), text='Pitch', color=(0.8, 0.8, 0.8, 0.8), font=QtGui.QFont('Arial', 10))
        self.gl_widget.addItem(y_name)
        
        z_name = gl.GLTextItem(pos=(-0.3, -0.3, 1.0), text='Yaw', color=(0.8, 0.8, 0.8, 0.8), font=QtGui.QFont('Arial', 10))
        self.gl_widget.addItem(z_name)
        
    def create_tracked_vehicle(self):
        """创建履带底盘粗略模型"""
        # 车身主体 (长方体，长边沿X轴方向)
        verts_body = np.array([
            [-0.8, -0.4, -0.1],  # 0: 左后下
            [0.8, -0.4, -0.1],   # 1: 右后下
            [0.8, 0.4, -0.1],    # 2: 右前下
            [-0.8, 0.4, -0.1],   # 3: 左前下
            [-0.8, -0.4, 0.2],   # 4: 左后上
            [0.8, -0.4, 0.2],    # 5: 右后上
            [0.8, 0.4, 0.2],     # 6: 右前上
            [-0.8, 0.4, 0.2]     # 7: 左前上
        ])
        
        faces_body = np.array([
            [0, 1, 2], [0, 2, 3],  # 底面
            [4, 5, 6], [4, 6, 7],  # 顶面
            [0, 1, 5], [0, 5, 4],  # 后面
            [1, 2, 6], [1, 6, 5],  # 右面
            [2, 3, 7], [2, 7, 6],  # 前面
            [3, 0, 4], [3, 4, 7]   # 左面
        ])
        
        colors_body = np.array([
            [0.5, 0.5, 0.5, 0.8], [0.5, 0.5, 0.5, 0.8],  # 灰色面
            [0.5, 0.5, 0.5, 0.8], [0.5, 0.5, 0.5, 0.8],  # 灰色面
            [0.3, 0.3, 0.3, 0.8], [0.3, 0.3, 0.3, 0.8],  # 深灰色面
            [0.3, 0.3, 0.3, 0.8], [0.3, 0.3, 0.3, 0.8],  # 深灰色面
            [0.7, 0.7, 0.7, 0.8], [0.7, 0.7, 0.7, 0.8],  # 浅灰色面
            [0.7, 0.7, 0.7, 0.8], [0.7, 0.7, 0.7, 0.8]   # 浅灰色面
        ])
        
        self.body = gl.GLMeshItem(
            vertexes=verts_body,
            faces=faces_body,
            faceColors=colors_body,
            smooth=False,
            glOptions='opaque'
        )
        self.gl_widget.addItem(self.body)
        
        # 左履带 (扁长方体)
        verts_left_track = np.array([
            [-0.9, -0.5, -0.15],  # 0: 左后下
            [0.9, -0.5, -0.15],   # 1: 右后下
            [0.9, -0.4, -0.15],   # 2: 右前下
            [-0.9, -0.4, -0.15],  # 3: 左前下
            [-0.9, -0.5, -0.05],  # 4: 左后上
            [0.9, -0.5, -0.05],   # 5: 右后上
            [0.9, -0.4, -0.05],   # 6: 右前上
            [-0.9, -0.4, -0.05]   # 7: 左前上
        ])
        
        faces_left_track = np.array([
            [0, 1, 2], [0, 2, 3],  # 底面
            [4, 5, 6], [4, 6, 7],  # 顶面
            [0, 1, 5], [0, 5, 4],  # 后面
            [1, 2, 6], [1, 6, 5],  # 右面
            [2, 3, 7], [2, 7, 6],  # 前面
            [3, 0, 4], [3, 4, 7]   # 左面
        ])
        
        colors_left_track = np.array([
            [0.2, 0.2, 0.2, 1.0], [0.2, 0.2, 0.2, 1.0],  # 黑色面
            [0.2, 0.2, 0.2, 1.0], [0.2, 0.2, 0.2, 1.0],  # 黑色面
            [0.1, 0.1, 0.1, 1.0], [0.1, 0.1, 0.1, 1.0],  # 深黑色面
            [0.1, 0.1, 0.1, 1.0], [0.1, 0.1, 0.1, 1.0],  # 深黑色面
            [0.3, 0.3, 0.3, 1.0], [0.3, 0.3, 0.3, 1.0],  # 灰色面
            [0.3, 0.3, 0.3, 1.0], [0.3, 0.3, 0.3, 1.0]   # 灰色面
        ])
        
        self.left_track = gl.GLMeshItem(
            vertexes=verts_left_track,
            faces=faces_left_track,
            faceColors=colors_left_track,
            smooth=False,
            glOptions='opaque'
        )
        self.gl_widget.addItem(self.left_track)
        
        # 右履带 (扁长方体)
        verts_right_track = np.array([
            [-0.9, 0.4, -0.15],   # 0: 左后下
            [0.9, 0.4, -0.15],    # 1: 右后下
            [0.9, 0.5, -0.15],    # 2: 右前下
            [-0.9, 0.5, -0.15],   # 3: 左前下
            [-0.9, 0.4, -0.05],   # 4: 左后上
            [0.9, 0.4, -0.05],    # 5: 右后上
            [0.9, 0.5, -0.05],    # 6: 右前上
            [-0.9, 0.5, -0.05]    # 7: 左前上
        ])
        
        faces_right_track = faces_left_track.copy()
        colors_right_track = colors_left_track.copy()
        
        self.right_track = gl.GLMeshItem(
            vertexes=verts_right_track,
            faces=faces_right_track,
            faceColors=colors_right_track,
            smooth=False,
            glOptions='opaque'
        )
        self.gl_widget.addItem(self.right_track)
        
    def update_attitude(self, roll, pitch, yaw):
        """更新姿态显示"""
        # 转换为弧度
        roll_rad = math.radians(roll)
        pitch_rad = math.radians(pitch)
        yaw_rad = math.radians(yaw)
        
        # 重置变换
        self.body.resetTransform()
        self.left_track.resetTransform()
        self.right_track.resetTransform()
        
        # 应用旋转（按ZYX顺序）
        self.body.rotate(yaw_rad * 180 / math.pi, 0, 0, 1, local=True)
        self.body.rotate(pitch_rad * 180 / math.pi, 1, 0, 0, local=True)
        self.body.rotate(roll_rad * 180 / math.pi, 0, 1, 0, local=True)
        
        self.left_track.rotate(yaw_rad * 180 / math.pi, 0, 0, 1, local=True)
        self.left_track.rotate(pitch_rad * 180 / math.pi, 1, 0, 0, local=True)
        self.left_track.rotate(roll_rad * 180 / math.pi, 0, 1, 0, local=True)
        
        self.right_track.rotate(yaw_rad * 180 / math.pi, 0, 0, 1, local=True)
        self.right_track.rotate(pitch_rad * 180 / math.pi, 1, 0, 0, local=True)
        self.right_track.rotate(roll_rad * 180 / math.pi, 0, 1, 0, local=True)

# ==================== 导航地图部件 ====================

class NavigationMap(QWidget):
    """导航地图显示部件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.trajectory = deque(maxlen=1000)  # 存储轨迹点
        self.current_pos = (0, 0)
        self.current_heading = 0.0  # 当前航向角（度）
        self.arrow_points = None
        self.start_pos = None  # 起点
        self.end_pos = None    # 终点
        self.path = []         # 路径点
        self.farm_path = []    # 农田路径
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # 创建绘图部件
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '纬度')
        self.plot_widget.setLabel('bottom', '经度')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setAspectLocked(True)
        
        # 轨迹线
        self.trajectory_plot = self.plot_widget.plot([], [], pen=pg.mkPen(color='b', width=2))
        
        # 当前位置点（红色圆点）
        self.position_plot = self.plot_widget.plot([], [], 
                                                  pen=None, 
                                                  symbol='o',
                                                  symbolSize=8,
                                                  symbolBrush='r')
        
        # 方向箭头（使用三角形表示方向）
        self.arrow_plot = self.plot_widget.plot([], [], 
                                               pen=pg.mkPen(color='g', width=2))
        
        # 方向箭头头部（三角形）
        self.arrow_head_plot = self.plot_widget.plot([], [], 
                                                    pen=None,
                                                    symbol='t',
                                                    symbolSize=15,
                                                    symbolBrush='g',
                                                    symbolPen='g')
        
        # 路径
        self.path_plot = self.plot_widget.plot([], [], 
                                              pen=pg.mkPen(color='purple', width=3, style=QtCore.Qt.DashLine))
        
        # 农田路径
        self.farm_path_plot = self.plot_widget.plot([], [], 
                                                   pen=pg.mkPen(color='orange', width=4))
        
        # 添加缩放控件
        self.zoom_in_btn = QPushButton('+')
        self.zoom_in_btn.setMaximumWidth(35)
        self.zoom_out_btn = QPushButton('-')
        self.zoom_out_btn.setMaximumWidth(35)
        self.clear_all_btn = QPushButton('清空地图')
        self.clear_all_btn.setMinimumWidth(75)
        self.export_btn = QPushButton('导出轨迹')
        self.export_btn.setMinimumWidth(75)
        self.fit_view_btn = QPushButton('适应视图')
        self.fit_view_btn.setMinimumWidth(75)
        
        control_layout = QHBoxLayout()
        control_layout.addWidget(self.zoom_in_btn)
        control_layout.addWidget(self.zoom_out_btn)
        control_layout.addWidget(self.fit_view_btn)
        control_layout.addWidget(self.clear_all_btn)
        control_layout.addWidget(self.export_btn)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        layout.addWidget(self.plot_widget)
        
        # 连接信号
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.fit_view_btn.clicked.connect(self.auto_zoom_to_fit)
        self.clear_all_btn.clicked.connect(self.clear_all)
        self.export_btn.clicked.connect(self.export_trajectory)
        
        # 初始化箭头点
        self.init_arrow_points()
        
        # 设置初始视图范围（西南大学周边区域）
        self.plot_widget.setXRange(106.41, 106.45)  # 经度范围
        self.plot_widget.setYRange(29.81, 29.83)    # 纬度范围
        
    def init_arrow_points(self):
        """初始化箭头形状的点"""
        # 箭头尺寸（经纬度偏移量）
        arrow_length = 0.0005  # 大约50米
        arrow_width = 0.0002   # 大约20米
        
        # 箭头主体（从尾部到头部）
        self.arrow_body_points = np.array([
            [0, -arrow_length],  # 尾部
            [0, 0]              # 头部
        ])
        
        # 箭头头部（三角形）
        self.arrow_head_points = np.array([
            [0, 0],                     # 箭头尖端
            [-arrow_width/2, -arrow_length/2],  # 左后点
            [arrow_width/2, -arrow_length/2],   # 右后点
            [0, 0]                     # 回到尖端
        ])
        
    def rotate_points(self, points, heading):
        """根据航向角旋转点集"""
        # 将度转换为弧度
        angle = math.radians(heading)
        
        # 旋转矩阵
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        # 旋转点
        rotated_points = []
        for point in points:
            x_rot = point[0] * cos_a - point[1] * sin_a
            y_rot = point[0] * sin_a + point[1] * cos_a
            rotated_points.append([x_rot, y_rot])
        
        return np.array(rotated_points)
        
    def update_position_and_heading(self, lat, lon, heading=0.0):
        """更新位置和航向"""
        if lat != 0 and lon != 0:
            self.current_pos = (lon, lat)
            self.current_heading = heading
            
            # 添加到轨迹
            self.trajectory.append((lon, lat, heading))
            
            # 更新轨迹
            if len(self.trajectory) > 1:
                lons, lats, _ = zip(*self.trajectory)
                self.trajectory_plot.setData(lons, lats)
            
            # 更新当前位置点
            self.position_plot.setData([lon], [lat])
            
            # 更新方向箭头
            rotated_body = self.rotate_points(self.arrow_body_points, heading)
            rotated_head = self.rotate_points(self.arrow_head_points, heading)
            
            # 箭头主体
            arrow_body_lons = rotated_body[:, 0] + lon
            arrow_body_lats = rotated_body[:, 1] + lat
            self.arrow_plot.setData(arrow_body_lons, arrow_body_lats)
            
            # 箭头头部
            arrow_head_lons = rotated_head[:, 0] + lon
            arrow_head_lats = rotated_head[:, 1] + lat
            self.arrow_head_plot.setData(arrow_head_lons, arrow_head_lats)
            
            # 自动调整视图范围
            if len(self.trajectory) > 1:
                min_lon = min(lons)
                max_lon = max(lons)
                min_lat = min(lats)
                max_lat = max(lats)
                
                # 添加一些边距
                lon_range = max(max_lon - min_lon, 0.0001)
                lat_range = max(max_lat - min_lat, 0.0001)
                
                self.plot_widget.setXRange(min_lon - lon_range*0.1, max_lon + lon_range*0.1)
                self.plot_widget.setYRange(min_lat - lat_range*0.1, max_lat + lat_range*0.1)
    
    def auto_zoom_to_fit(self):
        """自动调整视图范围以包含所有数据"""
        all_lons = []
        all_lats = []
        
        # 轨迹点
        if self.trajectory:
            lons, lats, _ = zip(*self.trajectory)
            all_lons.extend(lons)
            all_lats.extend(lats)
        
        # 农田路径点
        if self.farm_path:
            lons, lats = zip(*self.farm_path)
            all_lons.extend(lons)
            all_lats.extend(lats)
        
        # 当前位置
        if self.current_pos != (0, 0):
            all_lons.append(self.current_pos[0])
            all_lats.append(self.current_pos[1])
        
        if all_lons and all_lats:
            min_lon = min(all_lons)
            max_lon = max(all_lons)
            min_lat = min(all_lats)
            max_lat = max(all_lats)
            
            # 添加边距
            lon_margin = max((max_lon - min_lon) * 0.1, 0.0005)
            lat_margin = max((max_lat - min_lat) * 0.1, 0.0005)
            
            self.plot_widget.setXRange(min_lon - lon_margin, max_lon + lon_margin)
            self.plot_widget.setYRange(min_lat - lat_margin, max_lat + lat_margin)
            self.plot_widget.repaint()
    
    def set_farm_path(self, path_points):
        """设置农田路径点"""
        self.farm_path = path_points
        if path_points:
            lons, lats = zip(*path_points)
            self.farm_path_plot.setData(lons, lats)
            self.plot_widget.repaint()
    
    def set_path(self, path_points):
        """设置路径点"""
        self.path = path_points
        if path_points:
            lons, lats = zip(*path_points)
            self.path_plot.setData(lons, lats)
            self.plot_widget.repaint()
    
    def zoom_in(self):
        """放大"""
        self.plot_widget.getViewBox().scaleBy((0.8, 0.8))
    
    def zoom_out(self):
        """缩小"""
        self.plot_widget.getViewBox().scaleBy((1.25, 1.25))
    
    def clear_all(self):
        """一键清空地图所有内容"""
        self.trajectory.clear()
        self.trajectory_plot.setData([], [])
        self.position_plot.setData([], [])
        self.arrow_plot.setData([], [])
        self.arrow_head_plot.setData([], [])
        self.path_plot.setData([], [])
        self.farm_path_plot.setData([], [])
        self.path = []
        self.farm_path = []
        self.plot_widget.repaint()
    
    def export_trajectory(self):
        """导出轨迹到文件"""
        if not self.trajectory:
            QMessageBox.warning(self, "警告", "没有轨迹数据可以导出")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存轨迹数据", "", "CSV文件 (*.csv);;所有文件 (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write("经度,纬度,航向角\n")
                    for lon, lat, heading in self.trajectory:
                        f.write(f"{lon},{lat},{heading}\n")
                QMessageBox.information(self, "成功", f"轨迹数据已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")

# ==================== 导航控制部件 ====================

class NavigationControl(QWidget):
    """导航控制部件"""
    
    def __init__(self, nav_map, serial_port=None):
        super().__init__()
        self.nav_map = nav_map
        self.serial_port = serial_port
        self.farm_path = []  # 农田路径数据
        self.init_ui()
        
    def init_ui(self):
        # 创建主布局
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 农田导航参数设置
        farm_group = QGroupBox('农田导航设置')
        farm_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        farm_layout = QGridLayout(farm_group)
        farm_layout.setSpacing(3)
        
        # 参数输入区域
        param_grid = QGridLayout()
        param_grid.setSpacing(3)
        param_grid.setColumnStretch(1, 1)  # 第二列可拉伸
        
        # 直线长度设置
        param_grid.addWidget(QLabel('长度(m):'), 0, 0, Qt.AlignRight)
        self.straight_length_input = QLineEdit('100')
        self.straight_length_input.setPlaceholderText("直线长度")
        param_grid.addWidget(self.straight_length_input, 0, 1)
        
        # 直线间距设置
        param_grid.addWidget(QLabel('间距(m):'), 1, 0, Qt.AlignRight)
        self.line_spacing_input = QLineEdit('20')
        self.line_spacing_input.setPlaceholderText("直线间距")
        param_grid.addWidget(self.line_spacing_input, 1, 1)
        
        # 转弯半径设置
        param_grid.addWidget(QLabel('半径(m):'), 2, 0, Qt.AlignRight)
        self.turn_radius_input = QLineEdit('10')
        self.turn_radius_input.setPlaceholderText("转弯半径")
        param_grid.addWidget(self.turn_radius_input, 2, 1)
        
        # 行数设置
        param_grid.addWidget(QLabel('行数:'), 3, 0, Qt.AlignRight)
        self.num_lines_input = QLineEdit('5')
        self.num_lines_input.setPlaceholderText("行数")
        param_grid.addWidget(self.num_lines_input, 3, 1)
        
        # 路径方向选择
        param_grid.addWidget(QLabel('方向:'), 4, 0, Qt.AlignRight)
        self.path_direction_combo = QComboBox()
        self.path_direction_combo.addItems(['蛇形遍历', '闭合矩形'])
        self.path_direction_combo.setCurrentText('蛇形遍历')
        param_grid.addWidget(self.path_direction_combo, 4, 1)
        
        farm_layout.addLayout(param_grid, 0, 0, 1, 2)
        
        # 农田路径按钮
        farm_button_layout = QHBoxLayout()
        farm_button_layout.setSpacing(3)
        
        self.generate_farm_path_btn = QPushButton('生成路径')
        self.generate_farm_path_btn.setMinimumHeight(30)
        self.generate_farm_path_btn.clicked.connect(self.generate_farm_path)
        farm_button_layout.addWidget(self.generate_farm_path_btn)
        
        self.clear_farm_path_btn = QPushButton('清空路径')
        self.clear_farm_path_btn.setMinimumHeight(30)
        self.clear_farm_path_btn.clicked.connect(self.clear_farm_path)
        farm_button_layout.addWidget(self.clear_farm_path_btn)
        
        farm_layout.addLayout(farm_button_layout, 1, 0, 1, 2)
        
        layout.addWidget(farm_group)
        
        # 控制端口设置
        control_group = QGroupBox('控制端口设置')
        control_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        control_layout = QGridLayout(control_group)
        control_layout.setSpacing(3)
        
        # COM端口选择
        control_layout.addWidget(QLabel('COM端口:'), 0, 0, Qt.AlignRight)
        self.control_port_combo = QComboBox()
        self.refresh_ports()
        self.control_port_combo.setEditable(True)
        control_layout.addWidget(self.control_port_combo, 0, 1)
        
        # 波特率设置
        control_layout.addWidget(QLabel('波特率:'), 1, 0, Qt.AlignRight)
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(['4800', '9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600'])
        self.baudrate_combo.setCurrentText('9600')
        control_layout.addWidget(self.baudrate_combo, 1, 1)
        
        # 控制端口按钮
        control_button_layout = QHBoxLayout()
        control_button_layout.setSpacing(3)
        
        self.connect_control_btn = QPushButton('连接端口')
        self.connect_control_btn.setMinimumHeight(30)
        self.connect_control_btn.clicked.connect(self.connect_control_port)
        control_button_layout.addWidget(self.connect_control_btn)
        
        self.refresh_com_btn = QPushButton('刷新端口')
        self.refresh_com_btn.setMinimumHeight(30)
        self.refresh_com_btn.clicked.connect(self.refresh_ports)
        control_button_layout.addWidget(self.refresh_com_btn)
        
        control_layout.addLayout(control_button_layout, 2, 0, 1, 2)
        
        layout.addWidget(control_group)
        
        # 导航控制按钮容器
        nav_button_container = QWidget()
        nav_button_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        nav_button_layout = QHBoxLayout(nav_button_container)
        nav_button_layout.setSpacing(5)
        nav_button_layout.setContentsMargins(0, 5, 0, 0)
        
        self.start_nav_btn = QPushButton('开始导航')
        self.start_nav_btn.setMinimumHeight(35)
        self.start_nav_btn.clicked.connect(self.start_navigation)
        nav_button_layout.addWidget(self.start_nav_btn)
        
        self.stop_nav_btn = QPushButton('停止导航')
        self.stop_nav_btn.setMinimumHeight(35)
        self.stop_nav_btn.clicked.connect(self.stop_navigation)
        nav_button_layout.addWidget(self.stop_nav_btn)
        
        layout.addWidget(nav_button_container)
        
        # 状态显示
        self.nav_status = QLabel('状态: 等待设置路径')
        self.nav_status.setWordWrap(True)
        self.nav_status.setMinimumHeight(40)
        self.nav_status.setAlignment(Qt.AlignTop)
        self.nav_status.setStyleSheet("QLabel { background-color: #f0f0f0; border: 1px solid #ccc; padding: 3px; border-radius: 3px; font-size: 9pt; }")
        layout.addWidget(self.nav_status)
        
        # 设置最小尺寸
        self.setMinimumWidth(350)
        
    def refresh_ports(self):
        """刷新可用串口列表"""
        # 获取所有可能的COM端口
        ports = []
        
        # 首先获取系统检测到的串口
        detected_ports = serial.tools.list_ports.comports()
        detected_port_names = [port.device for port in detected_ports]
        ports.extend(detected_port_names)
        
        # 添加常见的虚拟串口和可能的串口
        common_ports = [f'COM{i}' for i in range(1, 33)]  # COM1到COM32
        for port in common_ports:
            if port not in ports:
                ports.append(port)
        
        # 添加Linux/Mac兼容的串口名（如果需要）
        if sys.platform.startswith('linux'):
            import glob
            linux_ports = glob.glob('/dev/tty[A-Za-z]*')
            for port in linux_ports:
                if port not in ports:
                    ports.append(port)
        elif sys.platform.startswith('darwin'):
            import glob
            mac_ports = glob.glob('/dev/tty.*')
            for port in mac_ports:
                if port not in ports:
                    ports.append(port)
        
        # 更新下拉列表
        self.control_port_combo.clear()
        self.control_port_combo.addItems(ports)
    
    def generate_farm_path(self):
        """生成农田路径"""
        try:
            # 获取参数
            straight_length = float(self.straight_length_input.text())
            line_spacing = float(self.line_spacing_input.text())
            turn_radius = float(self.turn_radius_input.text())
            num_lines = int(self.num_lines_input.text())
            
            if straight_length <= 0 or line_spacing <= 0 or turn_radius <= 0 or num_lines <= 0:
                QMessageBox.warning(self, '警告', '参数必须大于0')
                return
            
            # 获取当前位置和航向
            if not hasattr(self.nav_map, 'current_pos') or self.nav_map.current_pos == (0, 0):
                QMessageBox.warning(self, '警告', '请先获取当前位置')
                return
            
            start_lon, start_lat = self.nav_map.current_pos
            heading = self.nav_map.current_heading
            
            # 根据选择的路径方向生成路径
            path_type = self.path_direction_combo.currentText()
            
            if path_type == '蛇形遍历':
                path_points = self.calculate_snake_path(start_lat, start_lon, heading, 
                                                       straight_length, line_spacing, turn_radius, num_lines)
            else:  # 闭合矩形
                path_points = self.calculate_rectangle_path(start_lat, start_lon, heading, 
                                                           straight_length, line_spacing, turn_radius, num_lines)
            
            if not path_points:
                QMessageBox.warning(self, '警告', '路径生成失败')
                return
            
            # 设置到地图并自动缩放
            self.nav_map.set_farm_path(path_points)
            self.nav_map.auto_zoom_to_fit()  # 添加自动缩放
            
            # 保存农田路径
            self.farm_path = path_points
            
            self.nav_status.setText(f'农田路径已生成: {len(path_points)}个点 ({path_type})')
            
            # 显示路径范围信息
            if path_points:
                min_lon = min(lon for lon, lat in path_points)
                max_lon = max(lon for lon, lat in path_points)
                min_lat = min(lat for lon, lat in path_points)
                max_lat = max(lat for lon, lat in path_points)
                print(f"路径范围: 经度[{min_lon:.6f}, {max_lon:.6f}], 纬度[{min_lat:.6f}, {max_lat:.6f}]")
            
        except ValueError:
            QMessageBox.warning(self, '警告', '请输入有效的数字参数')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'生成路径失败: {str(e)}')
    
    def calculate_snake_path(self, start_lat, start_lon, heading, straight_length, 
                            line_spacing, turn_radius, num_lines):
        """计算蛇形遍历路径 - 真正的蛇形行走（一行一行的遍历）"""
        print(f"开始生成蛇形遍历路径: 起点({start_lat}, {start_lon}), 航向{heading}°, 长度{straight_length}m, {num_lines}行")
        
        path_points = []
        current_lat, current_lon = start_lat, start_lon
        
        # 添加起点
        path_points.append((current_lon, current_lat))
        
        for i in range(num_lines):
            # 当前行的方向：偶数行沿原始方向，奇数行沿相反方向
            current_heading = heading if i % 2 == 0 else (heading + 180) % 360
            
            # 前进直线
            geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading, straight_length)
            end_lat, end_lon = geod['lat2'], geod['lon2']
            
            # 采样直线上的点（每10米一个点）
            steps = max(2, int(straight_length / 10))
            for j in range(1, steps + 1):
                dist = straight_length * j / steps
                geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading, dist)
                path_points.append((geod['lon2'], geod['lat2']))
            
            current_lat, current_lon = end_lat, end_lon
            
            # 如果不是最后一行，添加跨行转弯
            if i < num_lines - 1:
                # 计算转弯方向：偶数行向右转，奇数行向左转
                if i % 2 == 0:  # 偶数行：右转->前进间距->右转
                    # 第一段右转90度
                    turn_steps = 8  # 转弯分段数
                    turn_angle = 90  # 右转
                    turn_length = turn_radius * math.pi / 2  # 90度弧长
                    
                    for k in range(1, turn_steps + 1):
                        angle = current_heading + (turn_angle * k / turn_steps)
                        geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                        path_points.append((geod['lon2'], geod['lat2']))
                        current_lat, current_lon = geod['lat2'], geod['lon2']
                    
                    # 沿垂直方向前进间距（到下一行的起点）
                    geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading + 90, line_spacing)
                    path_points.append((geod['lon2'], geod['lat2']))
                    current_lat, current_lon = geod['lat2'], geod['lon2']
                    
                    # 第二段右转90度（方向变为与原始方向相反）
                    for k in range(1, turn_steps + 1):
                        angle = current_heading + 90 + (turn_angle * k / turn_steps)
                        geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                        path_points.append((geod['lon2'], geod['lat2']))
                        current_lat, current_lon = geod['lat2'], geod['lon2']
                        
                else:  # 奇数行：左转->前进间距->左转
                    # 第一段左转90度
                    turn_steps = 8
                    turn_angle = -90  # 左转
                    turn_length = turn_radius * math.pi / 2  # 90度弧长
                    
                    for k in range(1, turn_steps + 1):
                        angle = current_heading + (turn_angle * k / turn_steps)
                        geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                        path_points.append((geod['lon2'], geod['lat2']))
                        current_lat, current_lon = geod['lat2'], geod['lon2']
                    
                    # 沿垂直方向前进间距（到下一行的起点）
                    geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading - 90, line_spacing)
                    path_points.append((geod['lon2'], geod['lat2']))
                    current_lat, current_lon = geod['lat2'], geod['lon2']
                    
                    # 第二段左转90度（方向变为与原始方向相同）
                    for k in range(1, turn_steps + 1):
                        angle = current_heading - 90 + (turn_angle * k / turn_steps)
                        geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                        path_points.append((geod['lon2'], geod['lat2']))
                        current_lat, current_lon = geod['lat2'], geod['lon2']
        
        print(f"蛇形遍历路径生成完成: {len(path_points)}个点")
        return path_points
    
    def calculate_rectangle_path(self, start_lat, start_lon, heading, straight_length, 
                               line_spacing, turn_radius, num_lines):
        """计算闭合矩形路径（备用方案）"""
        print(f"开始生成闭合矩形路径: 起点({start_lat}, {start_lon}), 航向{heading}°, 长度{straight_length}m, {num_lines}行")
        
        path_points = []
        current_lat, current_lon = start_lat, start_lon
        
        # 添加起点
        path_points.append((current_lon, current_lat))
        
        for i in range(num_lines):
            # 当前行的方向：始终沿原始方向
            current_heading = heading
            
            # 前进直线
            geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading, straight_length)
            end_lat, end_lon = geod['lat2'], geod['lon2']
            
            # 采样直线上的点
            steps = max(2, int(straight_length / 10))
            for j in range(1, steps + 1):
                dist = straight_length * j / steps
                geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading, dist)
                path_points.append((geod['lon2'], geod['lat2']))
            
            current_lat, current_lon = end_lat, end_lon
            
            # 如果不是最后一行，添加U形转弯
            if i < num_lines - 1:
                # 第一段转弯（180度）
                turn_steps = 10
                turn_angle = 180
                turn_length = turn_radius * math.pi  # 180度弧长
                
                for k in range(1, turn_steps + 1):
                    angle = current_heading + (turn_angle * k / turn_steps)
                    geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                    path_points.append((geod['lon2'], geod['lat2']))
                    current_lat, current_lon = geod['lat2'], geod['lon2']
                
                # 沿垂直方向前进间距
                geod = Geodesic.WGS84.Direct(current_lat, current_lon, current_heading + 90, line_spacing)
                path_points.append((geod['lon2'], geod['lat2']))
                current_lat, current_lon = geod['lat2'], geod['lon2']
                
                # 第二段转弯（再转180度，回到原方向）
                for k in range(1, turn_steps + 1):
                    angle = current_heading + 180 + (180 * k / turn_steps)
                    geod = Geodesic.WGS84.Direct(current_lat, current_lon, angle, turn_length/turn_steps)
                    path_points.append((geod['lon2'], geod['lat2']))
                    current_lat, current_lon = geod['lat2'], geod['lon2']
        
        print(f"闭合矩形路径生成完成: {len(path_points)}个点")
        return path_points
    
    def clear_farm_path(self):
        """清空农田路径"""
        self.nav_map.set_farm_path([])
        self.nav_status.setText('农田路径已清空')
        self.farm_path = []
    
    def start_navigation(self):
        """开始导航"""
        if not self.nav_map.farm_path:
            QMessageBox.warning(self, '警告', '请先生成农田路径')
            return
            
        # 开始发送控制指令到串口
        self.nav_status.setText('导航中...')
        
        # 发送控制指令到串口
        if self.serial_port and self.serial_port.is_open:
            self.send_navigation_commands()
    
    def send_navigation_commands(self):
        """发送导航控制指令到串口"""
        if not self.serial_port or not self.serial_port.is_open:
            self.nav_status.setText('控制端口未连接')
            return
            
        # 简单的控制指令：前进
        try:
            self.serial_port.write(b'1')  # 前进指令
            self.nav_status.setText('发送指令: 前进')
        except Exception as e:
            self.nav_status.setText(f'发送指令失败: {e}')
    
    def stop_navigation(self):
        """停止导航"""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(b'0')  # 停止指令
            except:
                pass
        self.nav_status.setText('导航已停止')
    
    def connect_control_port(self):
        """连接控制端口"""
        port = self.control_port_combo.currentText()
        if not port:
            QMessageBox.warning(self, '警告', '请选择串口')
            return
            
        # 首先尝试解析自定义波特率
        baudrate = int(self.baudrate_combo.currentText())
        
        try:
            # 连接串口
            self.serial_port = serial.Serial(port=port, baudrate=baudrate, timeout=1)
            self.connect_control_btn.setText('断开端口')
            self.connect_control_btn.clicked.disconnect()
            self.connect_control_btn.clicked.connect(self.disconnect_control_port)
            self.nav_status.setText(f'控制端口已连接: {port}@{baudrate}')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'连接控制端口失败: {str(e)}')
    
    def disconnect_control_port(self):
        """断开控制端口"""
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.connect_control_btn.setText('连接端口')
        self.connect_control_btn.clicked.disconnect()
        self.connect_control_btn.clicked.connect(self.connect_control_port)
        self.nav_status.setText('控制端口已断开')

# ==================== 紧凑型模块信息显示 ====================

class CompactG60InfoWidget(QGroupBox):
    """紧凑型G60模块信息显示"""
    
    def __init__(self):
        super().__init__("G60 GPS/BDS模块信息")
        self.init_ui()
        
    def init_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(5, 10, 5, 5)
        
        # 卫星系统
        layout.addWidget(QLabel('系统:'), 0, 0)
        self.system_label = QLabel('未知')
        self.system_label.setStyleSheet("font-weight: bold; color: blue;")
        layout.addWidget(self.system_label, 0, 1)
        
        # 位置信息
        layout.addWidget(QLabel('纬度:'), 1, 0)
        self.lat_label = QLabel('0.000000°')
        self.lat_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lat_label, 1, 1)
        
        layout.addWidget(QLabel('经度:'), 2, 0)
        self.lon_label = QLabel('0.000000°')
        self.lon_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lon_label, 2, 1)
        
        layout.addWidget(QLabel('海拔:'), 3, 0)
        self.alt_label = QLabel('0.0 m')
        layout.addWidget(self.alt_label, 3, 1)
        
        layout.addWidget(QLabel('速度:'), 4, 0)
        self.speed_label = QLabel('0.0 m/s')
        layout.addWidget(self.speed_label, 4, 1)
        
        layout.addWidget(QLabel('航向:'), 5, 0)
        self.course_label = QLabel('0.0°')
        layout.addWidget(self.course_label, 5, 1)
        
        layout.addWidget(QLabel('卫星:'), 6, 0)
        self.satellites_label = QLabel('0')
        layout.addWidget(self.satellites_label, 6, 1)
        
        # 北斗卫星数
        layout.addWidget(QLabel('北斗:'), 7, 0)
        self.bds_satellites_label = QLabel('0')
        self.bds_satellites_label.setStyleSheet("color: green; font-weight: bold;")
        layout.addWidget(self.bds_satellites_label, 7, 1)
        
        layout.addWidget(QLabel('HDOP:'), 8, 0)
        self.hdop_label = QLabel('0.0')
        layout.addWidget(self.hdop_label, 8, 1)
        
        layout.addWidget(QLabel('时间:'), 9, 0)
        self.time_label = QLabel('00:00:00')
        layout.addWidget(self.time_label, 9, 1)
        
        layout.addWidget(QLabel('状态:'), 10, 0)
        self.fix_label = QLabel('无定位')
        self.fix_label.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(self.fix_label, 10, 1)
        
        layout.addWidget(QLabel('统计:'), 11, 0)
        self.stats_label = QLabel('0 包/秒')
        layout.addWidget(self.stats_label, 11, 1)
        
        # 设置所有标签字体大小
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                widget.setFont(QFont('Arial', 9))
                
    def update_data(self, data):
        """更新显示数据"""
        if not data:
            return
            
        self.lat_label.setText(f'{data.latitude:.6f}°')
        self.lon_label.setText(f'{data.longitude:.6f}°')
        self.alt_label.setText(f'{data.altitude:.1f} m')
        self.speed_label.setText(f'{data.speed:.1f} m/s')
        self.course_label.setText(f'{data.course:.1f}°')
        self.satellites_label.setText(f'{data.satellites}')
        self.hdop_label.setText(f'{data.hdop:.1f}')
        self.time_label.setText(data.utc_time)
        
        # 更新卫星系统显示
        self.system_label.setText(data.satellite_system)
        
        # 更新北斗卫星数
        self.bds_satellites_label.setText(f'{data.bds_satellites}')
        
        # 更新定位状态
        if data.fix_quality == 0:
            self.fix_label.setText('无定位')
            self.fix_label.setStyleSheet("color: red; font-weight: bold;")
        elif data.fix_quality == 1:
            self.fix_label.setText('单点定位')
            self.fix_label.setStyleSheet("color: orange; font-weight: bold;")
        elif data.fix_quality == 2:
            self.fix_label.setText('差分定位')
            self.fix_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.fix_label.setText(f'定位({data.fix_quality})')
            self.fix_label.setStyleSheet("color: blue; font-weight: bold;")
            
    def update_stats(self, rate):
        """更新统计信息"""
        self.stats_label.setText(f'{rate:.1f} 包/秒')

class CompactH30InfoWidget(QGroupBox):
    """紧凑型H30模块信息显示"""
    
    def __init__(self):
        super().__init__("H30惯导模块信息")
        self.init_ui()
        
    def init_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(5, 10, 5, 5)
        
        # 姿态信息
        layout.addWidget(QLabel('横滚:'), 0, 0)
        self.roll_label = QLabel('0.00°')
        self.roll_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.roll_label, 0, 1)
        
        layout.addWidget(QLabel('俯仰:'), 1, 0)
        self.pitch_label = QLabel('0.00°')
        self.pitch_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.pitch_label, 1, 1)
        
        layout.addWidget(QLabel('航向:'), 2, 0)
        self.yaw_label = QLabel('0.00°')
        self.yaw_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.yaw_label, 2, 1)
        
        # 角速度
        layout.addWidget(QLabel('角速X:'), 3, 0)
        self.gyro_x_label = QLabel('0.00°/s')
        layout.addWidget(self.gyro_x_label, 3, 1)
        
        layout.addWidget(QLabel('角速Y:'), 4, 0)
        self.gyro_y_label = QLabel('0.00°/s')
        layout.addWidget(self.gyro_y_label, 4, 1)
        
        layout.addWidget(QLabel('角速Z:'), 5, 0)
        self.gyro_z_label = QLabel('0.00°/s')
        layout.addWidget(self.gyro_z_label, 5, 1)
        
        # 加速度
        layout.addWidget(QLabel('加速度X:'), 6, 0)
        self.acc_x_label = QLabel('0.00 m/s²')
        layout.addWidget(self.acc_x_label, 6, 1)
        
        layout.addWidget(QLabel('加速度Y:'), 7, 0)
        self.acc_y_label = QLabel('0.00 m/s²')
        layout.addWidget(self.acc_y_label, 7, 1)
        
        layout.addWidget(QLabel('加速度Z:'), 8, 0)
        self.acc_z_label = QLabel('0.00 m/s²')
        layout.addWidget(self.acc_z_label, 8, 1)
        
        # 温度
        layout.addWidget(QLabel('温度:'), 9, 0)
        self.temp_label = QLabel('0.0°C')
        layout.addWidget(self.temp_label, 9, 1)
        
        # 数据统计
        layout.addWidget(QLabel('速率:'), 10, 0)
        self.rate_label = QLabel('0 Hz')
        layout.addWidget(self.rate_label, 10, 1)
        
        layout.addWidget(QLabel('状态:'), 11, 0)
        self.status_label = QLabel('未连接')
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(self.status_label, 11, 1)
        
        # 设置所有标签字体大小
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                widget.setFont(QFont('Arial', 9))
                
    def update_data(self, data):
        """更新显示数据"""
        if not data:
            return
            
        self.roll_label.setText(f'{data.roll:.2f}°')
        self.pitch_label.setText(f'{data.pitch:.2f}°')
        self.yaw_label.setText(f'{data.yaw:.2f}°')
        self.gyro_x_label.setText(f'{data.gyro_x:.2f}°/s')
        self.gyro_y_label.setText(f'{data.gyro_y:.2f}°/s')
        self.gyro_z_label.setText(f'{data.gyro_z:.2f}°/s')
        self.acc_x_label.setText(f'{data.acc_x:.2f} m/s²')
        self.acc_y_label.setText(f'{data.acc_y:.2f} m/s²')
        self.acc_z_label.setText(f'{data.acc_z:.2f} m/s²')
        self.temp_label.setText(f'{data.temperature:.1f}°C')
        self.status_label.setText('正常')
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        
    def update_stats(self, rate):
        """更新统计信息"""
        self.rate_label.setText(f'{rate:.1f} Hz')

# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.g60_thread = None
        self.h30_thread = None
        self.control_serial = None
        self.g60_data_count = 0
        self.h30_data_count = 0
        self.last_update_time = time.time()
        self.recording = False
        self.recorded_data = []
        self.map_update_counter = 0  # 地图更新计数器
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle('H30惯导 & G60定位 履带底盘运动控制系统（支持北斗卫星导航）')
        self.setGeometry(100, 100, 1900, 1050)
        
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 顶部控制面板
        control_panel = self.create_control_panel()
        main_layout.addLayout(control_panel)
        
        # 中间主显示区域 - 使用网格布局
        middle_container = QWidget()
        middle_layout = QGridLayout(middle_container)
        middle_layout.setSpacing(5)
        
        # 左侧：模块信息显示
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setSpacing(5)
        
        # G60模块信息
        self.g60_info = CompactG60InfoWidget()
        self.g60_info.setMaximumHeight(300)
        info_layout.addWidget(self.g60_info)
        
        # H30模块信息
        self.h30_info = CompactH30InfoWidget()
        self.h30_info.setMaximumHeight(300)
        info_layout.addWidget(self.h30_info)
        
        info_layout.addStretch()
        middle_layout.addWidget(info_container, 0, 0, 2, 1)  # 占2行1列
        
        # 中间上：2D导航地图
        self.nav_map = NavigationMap()
        middle_layout.addWidget(self.nav_map, 0, 1)
        
        # 中间下：卫星地图
        self.satellite_map = SatelliteMapWidget()
        middle_layout.addWidget(self.satellite_map, 1, 1)
        
        # 右侧：3D姿态和导航控制
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(5)
        
        # 3D姿态显示
        self.attitude_3d = AttitudeIndicator3D()
        right_layout.addWidget(self.attitude_3d)
        
        # 导航控制面板
        self.nav_control = NavigationControl(self.nav_map, self.control_serial)
        right_layout.addWidget(self.nav_control)
        
        middle_layout.addWidget(right_container, 0, 2, 2, 1)  # 占2行1列
        
        # 设置列宽比例
        middle_layout.setColumnStretch(0, 1)  # 模块信息
        middle_layout.setColumnStretch(1, 3)  # 地图
        middle_layout.setColumnStretch(2, 1)  # 3D姿态和导航控制
        
        # 设置行高比例
        middle_layout.setRowStretch(0, 1)  # 2D地图
        middle_layout.setRowStretch(1, 1)  # 卫星地图
        
        main_layout.addWidget(middle_container, 1)
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage('就绪')
        
        # 刷新串口列表（在所有控件创建完成后）
        self.refresh_ports()
        
        # 定时器更新UI
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(100)  # 10Hz更新
        
    def create_control_panel(self):
        """创建控制面板"""
        layout = QHBoxLayout()
        layout.setSpacing(5)
        
        # G60控制组
        g60_group = QGroupBox('G60 GPS/BDS模块')
        g60_layout = QGridLayout(g60_group)
        g60_layout.setSpacing(3)
        
        # 串口选择
        g60_layout.addWidget(QLabel('端口:'), 0, 0)
        self.g60_port_combo = QComboBox()
        self.g60_port_combo.setEditable(True)
        self.g60_port_combo.setMaximumWidth(120)
        g60_layout.addWidget(self.g60_port_combo, 0, 1)
        
        # 波特率选择
        g60_layout.addWidget(QLabel('波特率:'), 1, 0)
        self.g60_baud_combo = QComboBox()
        self.g60_baud_combo.addItems([
            '4800', '9600', '14400', '19200', '38400', 
            '56000', '57600', '115200', '128000', '230400',
            '256000', '460800', '921600'
        ])
        self.g60_baud_combo.setCurrentText('9600')
        self.g60_baud_combo.setMaximumWidth(120)
        g60_layout.addWidget(self.g60_baud_combo, 1, 1)
        
        # 连接按钮
        self.g60_connect_btn = QPushButton('连接')
        self.g60_connect_btn.setMinimumWidth(80)
        self.g60_connect_btn.clicked.connect(self.toggle_g60_connection)
        g60_layout.addWidget(self.g60_connect_btn, 2, 0, 1, 2)
        
        # 状态指示灯
        self.g60_status_led = QLabel()
        self.g60_status_led.setFixedSize(15, 15)
        self.g60_status_led.setStyleSheet("background-color: gray; border-radius: 7px;")
        g60_layout.addWidget(QLabel('状态:'), 3, 0)
        g60_layout.addWidget(self.g60_status_led, 3, 1)
        
        g60_group.setLayout(g60_layout)
        layout.addWidget(g60_group)
        
        # H30控制组
        h30_group = QGroupBox('H30惯导模块')
        h30_layout = QGridLayout(h30_group)
        h30_layout.setSpacing(3)
        
        # 串口选择
        h30_layout.addWidget(QLabel('端口:'), 0, 0)
        self.h30_port_combo = QComboBox()
        self.h30_port_combo.setEditable(True)
        self.h30_port_combo.setMaximumWidth(120)
        h30_layout.addWidget(self.h30_port_combo, 0, 1)
        
        # 波特率选择
        h30_layout.addWidget(QLabel('波特率:'), 1, 0)
        self.h30_baud_combo = QComboBox()
        self.h30_baud_combo.addItems([
            '4800', '9600', '14400', '19200', '38400', 
            '56000', '57600', '115200', '128000', '230400',
            '256000', '460800', '921600'
        ])
        self.h30_baud_combo.setCurrentText('460800')
        self.h30_baud_combo.setMaximumWidth(120)
        h30_layout.addWidget(self.h30_baud_combo, 1, 1)
        
        # 连接按钮
        self.h30_connect_btn = QPushButton('连接')
        self.h30_connect_btn.setMinimumWidth(80)
        self.h30_connect_btn.clicked.connect(self.toggle_h30_connection)
        h30_layout.addWidget(self.h30_connect_btn, 2, 0, 1, 2)
        
        # 状态指示灯
        self.h30_status_led = QLabel()
        self.h30_status_led.setFixedSize(15, 15)
        self.h30_status_led.setStyleSheet("background-color: gray; border-radius: 7px;")
        h30_layout.addWidget(QLabel('状态:'), 3, 0)
        h30_layout.addWidget(self.h30_status_led, 3, 1)
        
        h30_group.setLayout(h30_layout)
        layout.addWidget(h30_group)
        
        # 控制按钮组
        button_group = QGroupBox('系统控制')
        button_layout = QHBoxLayout(button_group)
        button_layout.setSpacing(5)
        
        # 刷新按钮
        refresh_btn = QPushButton('刷新串口')
        refresh_btn.setMinimumWidth(90)
        refresh_btn.clicked.connect(self.refresh_ports)
        button_layout.addWidget(refresh_btn)
        
        # 配置按钮
        config_btn = QPushButton('配置')
        config_btn.setMinimumWidth(70)
        config_btn.clicked.connect(self.show_config_dialog)
        button_layout.addWidget(config_btn)
        
        # 数据记录按钮
        self.record_btn = QPushButton('开始记录')
        self.record_btn.setCheckable(True)
        self.record_btn.setMinimumWidth(90)
        self.record_btn.clicked.connect(self.toggle_recording)
        button_layout.addWidget(self.record_btn)
        
        layout.addWidget(button_group)
        
        layout.addStretch()
        
        return layout
    
    def refresh_ports(self):
        """刷新串口列表"""
        # 获取所有可能的COM端口
        ports = []
        
        # 首先获取系统检测到的串口
        detected_ports = serial.tools.list_ports.comports()
        detected_port_names = [port.device for port in detected_ports]
        ports.extend(detected_port_names)
        
        # 添加常见的虚拟串口和可能的串口
        common_ports = [f'COM{i}' for i in range(1, 33)]  # COM1到COM32
        for port in common_ports:
            if port not in ports:
                ports.append(port)
        
        # 添加Linux/Mac兼容的串口名
        if sys.platform.startswith('linux'):
            import glob
            linux_ports = glob.glob('/dev/tty[A-Za-z]*')
            for port in linux_ports:
                if port not in ports:
                    ports.append(port)
        elif sys.platform.startswith('darwin'):
            import glob
            mac_ports = glob.glob('/dev/tty.*')
            for port in mac_ports:
                if port not in ports:
                    ports.append(port)
        
        # 保存当前选择
        current_g60 = self.g60_port_combo.currentText() if self.g60_port_combo.currentText() in ports else None
        current_h30 = self.h30_port_combo.currentText() if self.h30_port_combo.currentText() in ports else None
        
        # 清空并重新填充
        self.g60_port_combo.clear()
        self.h30_port_combo.clear()
        self.nav_control.control_port_combo.clear()
        
        self.g60_port_combo.addItems(ports)
        self.h30_port_combo.addItems(ports)
        self.nav_control.control_port_combo.addItems(ports)
        
        # 恢复选择或设置默认
        if ports:
            if current_g60:
                self.g60_port_combo.setCurrentText(current_g60)
            else:
                self.g60_port_combo.setCurrentText(ports[0])
                
            if current_h30:
                self.h30_port_combo.setCurrentText(current_h30)
            elif len(ports) > 1:
                self.h30_port_combo.setCurrentText(ports[1])
            else:
                self.h30_port_combo.setCurrentText(ports[0])
    
    def toggle_g60_connection(self):
        """切换G60连接状态"""
        if self.g60_thread and self.g60_thread.running:
            self.disconnect_g60()
        else:
            self.connect_g60()
    
    def toggle_h30_connection(self):
        """切换H30连接状态"""
        if self.h30_thread and self.h30_thread.running:
            self.disconnect_h30()
        else:
            self.connect_h30()
    
    def connect_g60(self):
        """连接G60"""
        port = self.g60_port_combo.currentText()
        baudrate = int(self.g60_baud_combo.currentText())
        
        if not port:
            QMessageBox.warning(self, '警告', '请选择串口')
            return
        
        try:
            self.g60_thread = SerialThread('G60', port, baudrate)
            self.g60_thread.data_received.connect(self.on_g60_data)
            self.g60_thread.start()
            
            self.g60_connect_btn.setText('断开')
            self.g60_connect_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
            self.g60_status_led.setStyleSheet("background-color: green; border-radius: 7px;")
            self.status_bar.showMessage(f'G60已连接: {port}@{baudrate}')
            
        except Exception as e:
            QMessageBox.critical(self, '错误', f'连接失败: {str(e)}')
    
    def disconnect_g60(self):
        """断开G60"""
        if self.g60_thread:
            self.g60_thread.stop()
            self.g60_thread = None
            
            self.g60_connect_btn.setText('连接')
            self.g60_connect_btn.setStyleSheet("")
            self.g60_status_led.setStyleSheet("background-color: gray; border-radius: 7px;")
            self.status_bar.showMessage('G60已断开')
    
    def connect_h30(self):
        """连接H30"""
        port = self.h30_port_combo.currentText()
        baudrate = int(self.h30_baud_combo.currentText())
        
        if not port:
            QMessageBox.warning(self, '警告', '请选择串口')
            return
        
        try:
            self.h30_thread = SerialThread('H30', port, baudrate)
            self.h30_thread.data_received.connect(self.on_h30_data)
            self.h30_thread.start()
            
            self.h30_connect_btn.setText('断开')
            self.h30_connect_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
            self.h30_status_led.setStyleSheet("background-color: green; border-radius: 7px;")
            self.status_bar.showMessage(f'H30已连接: {port}@{baudrate}')
            
        except Exception as e:
            QMessageBox.critical(self, '错误', f'连接失败: {str(e)}')
    
    def disconnect_h30(self):
        """断开H30"""
        if self.h30_thread:
            self.h30_thread.stop()
            self.h30_thread = None
            
            self.h30_connect_btn.setText('连接')
            self.h30_connect_btn.setStyleSheet("")
            self.h30_status_led.setStyleSheet("background-color: gray; border-radius: 7px;")
            self.status_bar.showMessage('H30已断开')
    
    def on_g60_data(self, device_type, data):
        """处理G60数据"""
        if device_type == 'G60':
            # 数据统计
            self.g60_data_count += 1
            
            # 更新紧凑型G60信息显示
            self.g60_info.update_data(data)
            
            # 获取航向角（优先使用H30，如果没有则使用G60的course）
            heading = data.course
            if self.h30_thread and self.h30_thread.running:
                # 如果有H30，使用H30的yaw作为航向
                heading = self.h30_thread.parser.yaw
            
            # 更新地图（降低更新频率，每3次更新一次）
            if data.valid and data.latitude != 0 and data.longitude != 0:
                self.map_update_counter += 1
                if self.map_update_counter % 3 == 0:  # 每3次更新一次地图
                    self.nav_map.update_position_and_heading(data.latitude, data.longitude, heading)
                    self.map_update_counter = 0
                
                # 更新卫星地图
                if self.map_update_counter % 5 == 0:
                    self.satellite_map.update_position(
                        data.latitude, 
                        data.longitude, 
                        heading, 
                        data.speed
                    )
                    
                    # 如果有农田路径，也更新到卫星地图
                    if hasattr(self.nav_control, 'farm_path') and self.nav_control.farm_path:
                        self.satellite_map.add_farm_path(self.nav_control.farm_path)
                
            # 记录数据
            if self.recording:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                self.recorded_data.append({
                    'timestamp': timestamp,
                    'device': 'G60',
                    'satellite_system': data.satellite_system,
                    'latitude': data.latitude,
                    'longitude': data.longitude,
                    'altitude': data.altitude,
                    'speed': data.speed,
                    'course': data.course,
                    'satellites': data.satellites,
                    'bds_satellites': data.bds_satellites,
                    'hdop': data.hdop,
                    'fix_quality': data.fix_quality
                })
                
        elif device_type == 'ERROR':
            self.status_bar.showMessage(f'G60错误: {data}')
            self.disconnect_g60()
    
    def on_h30_data(self, device_type, data):
        """处理H30数据"""
        if device_type == 'H30':
            # 数据统计
            self.h30_data_count += 1
            
            # 更新紧凑型H30信息显示
            self.h30_info.update_data(data)
            
            # 更新3D姿态
            self.attitude_3d.update_attitude(data.roll, data.pitch, data.yaw)
            
            # 记录数据
            if self.recording:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                self.recorded_data.append({
                    'timestamp': timestamp,
                    'device': 'H30',
                    'roll': data.roll,
                    'pitch': data.pitch,
                    'yaw': data.yaw,
                    'gyro_x': data.gyro_x,
                    'gyro_y': data.gyro_y,
                    'gyro_z': data.gyro_z,
                    'acc_x': data.acc_x,
                    'acc_y': data.acc_y,
                    'acc_z': data.acc_z,
                    'temperature': data.temperature
                })
            
        elif device_type == 'ERROR':
            self.status_bar.showMessage(f'H30错误: {data}')
            self.disconnect_h30()
    
    def update_status(self):
        """更新状态信息"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 计算数据速率
        current_time_sec = time.time()
        elapsed = current_time_sec - self.last_update_time
        
        if elapsed >= 1.0:
            g60_rate = self.g60_data_count / elapsed
            h30_rate = self.h30_data_count / elapsed
            
            # 更新信息显示
            self.g60_info.update_stats(g60_rate)
            self.h30_info.update_stats(h30_rate)
            
            self.g60_data_count = 0
            self.h30_data_count = 0
            self.last_update_time = current_time_sec
    
    def toggle_recording(self):
        """切换数据记录状态"""
        self.recording = not self.recording
        
        if self.recording:
            self.record_btn.setText('停止记录')
            self.record_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
            self.recorded_data = []  # 清空之前的数据
            self.status_bar.showMessage('开始记录数据')
        else:
            self.record_btn.setText('开始记录')
            self.record_btn.setStyleSheet("")
            
            # 保存记录的数据
            if self.recorded_data:
                self.save_recorded_data()
            else:
                self.status_bar.showMessage('记录已停止，无数据')
    
    def save_recorded_data(self):
        """保存记录的数据"""
        if not self.recorded_data:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存记录数据", f"nav_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", 
            "CSV文件 (*.csv);;所有文件 (*)"
        )
        
        if file_path:
            try:
                # 分离G60和H30数据
                g60_data = [d for d in self.recorded_data if d['device'] == 'G60']
                h30_data = [d for d in self.recorded_data if d['device'] == 'H30']
                
                # 写入CSV文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    # 写入G60数据
                    if g60_data:
                        f.write("=== GPS/BDS数据 (G60) ===\n")
                        f.write("时间戳,卫星系统,纬度,经度,海拔(m),速度(m/s),航向(°),卫星总数,北斗卫星数,HDOP,定位质量\n")
                        for item in g60_data:
                            f.write(f"{item['timestamp']},{item['satellite_system']},{item['latitude']},{item['longitude']},"
                                   f"{item['altitude']},{item['speed']},{item['course']},"
                                   f"{item['satellites']},{item['bds_satellites']},{item['hdop']},{item['fix_quality']}\n")
                        f.write("\n")
                    
                    # 写入H30数据
                    if h30_data:
                        f.write("=== 惯导数据 (H30) ===\n")
                        f.write("时间戳,横滚角(°),俯仰角(°),航向角(°),角速度X(°/s),角速度Y(°/s),角速度Z(°/s),"
                               "加速度X(m/s²),加速度Y(m/s²),加速度Z(m/s²),温度(°C)\n")
                        for item in h30_data:
                            f.write(f"{item['timestamp']},{item['roll']},{item['pitch']},{item['yaw']},"
                                   f"{item['gyro_x']},{item['gyro_y']},{item['gyro_z']},"
                                   f"{item['acc_x']},{item['acc_y']},{item['acc_z']},{item['temperature']}\n")
                
                QMessageBox.information(self, "成功", f"数据已保存到: {file_path}\nG60数据: {len(g60_data)}条\nH30数据: {len(h30_data)}条")
                self.status_bar.showMessage(f'数据已保存: {file_path}')
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
    
    def show_config_dialog(self):
        """显示配置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle('系统配置')
        dialog.setFixedSize(400, 350)
        
        layout = QVBoxLayout(dialog)
        
        # 地图设置
        map_group = QGroupBox('地图设置')
        map_layout = QGridLayout()
        
        map_layout.addWidget(QLabel('轨迹最大点数:'), 0, 0)
        max_points_spin = QSpinBox()
        max_points_spin.setRange(100, 10000)
        max_points_spin.setValue(1000)
        max_points_spin.valueChanged.connect(lambda v: setattr(self.nav_map.trajectory, 'maxlen', v))
        map_layout.addWidget(max_points_spin, 0, 1)
        
        map_layout.addWidget(QLabel('地图更新频率:'), 1, 0)
        update_freq_combo = QComboBox()
        update_freq_combo.addItems(['每次更新', '每2次更新', '每3次更新', '每5次更新'])
        update_freq_combo.setCurrentText('每3次更新')
        update_freq_combo.currentTextChanged.connect(self.change_map_update_freq)
        map_layout.addWidget(update_freq_combo, 1, 1)
        
        map_group.setLayout(map_layout)
        layout.addWidget(map_group)
        
        # 显示设置
        display_group = QGroupBox('显示设置')
        display_layout = QVBoxLayout()
        
        auto_zoom_cb = QCheckBox('自动缩放地图')
        auto_zoom_cb.setChecked(True)
        display_layout.addWidget(auto_zoom_cb)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.exec_()
    
    def change_map_update_freq(self, text):
        """改变地图更新频率"""
        if text == '每次更新':
            self.map_update_counter = 0
        elif text == '每2次更新':
            self.map_update_counter = 0
        elif text == '每3次更新':
            self.map_update_counter = 0
        elif text == '每5次更新':
            self.map_update_counter = 0
    
    def closeEvent(self, event):
        """关闭事件"""
        # 停止记录
        if self.recording:
            self.toggle_recording()
        
        # 断开设备连接
        self.disconnect_g60()
        self.disconnect_h30()
        if self.control_serial and self.control_serial.is_open:
            self.control_serial.close()
        
        # 停止定时器
        self.timer.stop()
        
        # 清理卫星地图临时文件
        if hasattr(self, 'satellite_map'):
            self.satellite_map.closeEvent(event)
        
        # 确认关闭
        reply = QMessageBox.question(self, '确认退出', '确定要退出程序吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()

# ==================== 主程序 ====================

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置应用程序样式
    app.setStyleSheet("""
        QMainWindow {
            background-color: #f5f5f5;
        }
        QGroupBox {
            font-weight: bold;
            border: 2px solid #cccccc;
            border-radius: 5px;
            margin-top: 5px;
            padding-top: 8px;
            font-size: 10pt;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }
        QPushButton {
            background-color: #4a86e8;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 10pt;
        }
        QPushButton:hover {
            background-color: #3a76d8;
        }
        QPushButton:pressed {
            background-color: #2a66c8;
        }
        QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
            padding: 4px;
            border: 1px solid #cccccc;
            border-radius: 3px;
            font-size: 9pt;
        }
        QLabel {
            font-size: 9pt;
        }
    """)
    
    # 设置应用程序图标和名称
    app.setApplicationName('H30 & G60 导航系统（支持北斗卫星导航）')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()