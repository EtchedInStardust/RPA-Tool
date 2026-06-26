\# RPA Tool V2.0.0



本项目为RPA（机器人流程自动化）工具，由本人独立编写并免费发布。



\## 特别说明

\- 本工具未直接复制任何他人的源码；

\- 未包含任何商业收费功能；

\- 所有实现均为个人学习与重写结果；

\- 本软件永久免费，无任何隐藏收费；

\- 基于 MIT License 发布。



\## 核心功能

\- 鼠标/键盘操作录制与回放；

\- 图像识别定位与点击；

\- OCR 文字识别与提取；

\- 命令行（CLI）/ API 双模式执行；

\- 循环/条件分支任务编排。



\## 安装

1\. 确保已安装 Python 3.8 及以上版本；

2\. 克隆仓库或下载源代码；

3\. 进入项目目录，安装依赖：

bash

pip install -r requirements.txt

纯文本

\## 使用方法

\### GUI 模式（推荐新手）

bash

python rpa\_tool.py

纯文本

\### CLI 模式（执行 JSON 任务）

bash

python rpa\_tool.py --task your\_task.json

纯文本

\### API 模式（供其他程序调用）

bash

python rpa\_tool.py --api --api-port 8000

纯文本

首次启动会自动生成 Token，调用时需携带 `Authorization: Bearer <token>`。



\## 第三方依赖

本软件使用了以下开源项目，版权归原作者所有：

\- PySide6 (LGPL v3)

\- PyAutoGUI (BSD)

\- pynput (LGPL v3)

\- OpenCV (Apache 2.0 / BSD)

\- EasyOCR (Apache 2.0)

\- PyTorch (BSD)

\- NumPy (BSD)



第三方组件的许可证条款详见 `THIRD\_PARTY\_LICENSES.txt`。



\## 作者

\- GitHub: \[EtchedInStardust](https://github.com/EtchedInStardust)

\- 中文名: 星尘蚀刻

\- B 站: \[@星尘蚀刻](https://space.bilibili.com/277913532?spm\_id\_from=333.1007.0.0)

\- QQ: 3536924169



\## 反馈与支持

使用问题或 BUG 反馈可通过以下渠道联系：

\- B 站私信：\[@星尘蚀刻](https://space.bilibili.com/277913532?spm\_id\_from=333.1007.0.0)

\- QQ：3536924169



\## 当前版本

V2.0.0

