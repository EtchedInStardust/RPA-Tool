# RPA_Tool V2.0.0
"""
RPA (Robotic Process Automation) Tool
Supports image recognition, OCR text recognition, mouse and keyboard simulation for automation
Version: 2.0.0
Author: EtchedInStardust(星尘蚀刻)
"""

import os
import sys
import json
import threading
import argparse
import time
import cv2
import numpy as np
import concurrent.futures
import pyautogui
import pyperclip
from pynput import mouse, keyboard
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QLineEdit, QScrollArea,
    QFileDialog, QTextEdit, QMessageBox, QFrame, QTextBrowser
)
from PySide6.QtCore import Qt, QThread, Signal, QEvent
from PySide6.QtGui import QShortcut, QKeySequence

# ==================== Global Configuration Constants ====================
VERSION = "2.0.0"  # Software version
DEFAULT_CONFIDENCE = 0.78  # Default confidence for image recognition
OCR_LANGUAGES = ['ch_sim', 'en']  # Languages supported by OCR
OCR_TIMEOUT = 8  # OCR recognition timeout (seconds)
IMAGE_FIND_RETRY = 3  # Number of retries for image finding

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

pyautogui.FAILSAFE = True  # Enable pyautogui failsafe mechanism (move mouse to top-left corner to terminate)

    def _load_image(path):
        """
        Load image file
        Args:
            path: Image file path
        Returns:
            Image in numpy array format, None if failed
        """
    try:
        if not os.path.exists(path):
            print(f"[WARN] 图像路径不存在: {path}")
            return None
        img_array = np.fromfile(path, dtype=np.uint8)
        if img_array.size == 0:
            print(f"[WARN] 图像文件为空: {path}")
            return None
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[WARN] 无法解码图像: {path}")
        return img
    except Exception as e:
        print(f"[ERROR] 加载图像失败: {path}, 错误: {e}")
        return None

def find_image(img_path, region=None, confidence=DEFAULT_CONFIDENCE):
    """
    Find specified image on screen
    Args:
        img_path: Image path to find
        region: Search region (x, y, width, height), None means full screen
        confidence: Matching confidence (0-1)
    Returns:
        Center coordinates (x, y) if found, None if not found
    """
    template = _load_image(img_path)
    if template is None:
        print(f"[WARN] 无法加载图像: {img_path}")
        return None

    for i in range(IMAGE_FIND_RETRY):
        loc = pyautogui.locateCenterOnScreen(
            template,
            confidence=confidence,
            region=region
        )
        if loc:
            return loc
        if i < IMAGE_FIND_RETRY - 1:
            time.sleep(0.1)
    return None

def parse_region(text):
    """
    Parse region string
    Args:
        text: String in format "x,y,width,height"
    Returns:
        Tuple (x, y, width, height) if parsed successfully, None if failed
    """
    if not text or not isinstance(text, str):
        return None
    try:
        parts = list(map(int, text.split(",")))
        if len(parts) == 4 and all(p >= 0 for p in parts):
            return tuple(parts)
    except (ValueError, AttributeError):
        pass
    return None

class VarContext:
    """
    Variable context manager
    Used to store and resolve variables during task execution
    """
    def __init__(self):
        self.vars = {}
        
    def resolve(self, text):
        if not isinstance(text, str):
            return text
        import re
        pattern = re.compile(r'\{\{(\w+)\}\}')
        def replacer(match):
            key = match.group(1)
            return str(self.vars.get(key, match.group(0)))
        return pattern.sub(replacer, text)

_REGISTRY = {}  # Instruction type registry

def register(cmd_type):
    """
    指令注册装饰器
    Args:
        cmd_type: 指令类型编号
    Returns:
        装饰器函数
    """
    def decorator(cls):
        _REGISTRY[cmd_type] = cls
        return cls
    return decorator

def get_instruction(cmd_type):
    """
    根据指令类型获取对应的指令类
    Args:
        cmd_type: 指令类型编号
    Returns:
        指令类或None
    """
    return _REGISTRY.get(cmd_type)

class Instruction:
    """
    指令基类
    所有具体指令类都应继承此类并实现execute方法
    """
    def execute(self, ctx, executor, task, log):
        """
        执行指令
        Args:
            ctx: 变量上下文
            executor: 执行器
            task: 任务配置
            log: 日志函数
        """
        raise NotImplementedError()
    
    def skip_to_end(self, tasks, idx):
        """
        跳转到结束位置（用于条件判断等）
        """
        return idx + 1

def _move_and_act(loc, action, duration, executor):
    """
    可中断的匀速移动并执行动作
    Args:
        loc: 目标位置
        action: 要执行的动作函数
        duration: 移动持续时间（秒）
        executor: 执行器（用于检查是否中断）
    """
    dur = max(0.0, float(duration))
    if dur > 0 and executor.is_running:
        steps = max(10, min(100, int(dur * 60)))  # 60 steps per second, max 100 steps
        step_dur = dur / steps
        start_x, start_y = pyautogui.position()
        dx = (loc.x - start_x) / steps
        dy = (loc.y - start_y) / steps
        
        for i in range(steps):
            if not executor.is_running:
                return
            pyautogui.moveTo(start_x + dx * (i + 1), 
                           start_y + dy * (i + 1), 
                           duration=step_dur)
        if not executor.is_running:
            return
    if executor.is_running:
        action()

def _find_and_move(ctx, task, action, executor):
    """
    找图 + 匀速移动 + 执行动作
    Args:
        ctx: 变量上下文
        task: 任务配置
        action: 要执行的动作函数
        executor: 执行器
    """
    img = ctx.resolve(task.get("value"))
    region = task.get("region")
    loc = find_image(img, region)
    if loc:
        dur = task.get("duration", 0)
        _move_and_act(loc, action, dur, executor)

@register(1)
class ClickInstruction(Instruction):
    """单击指令 - 找到图像后单击"""
    def execute(self, ctx, executor, task, log):
        _find_and_move(ctx, task, lambda: pyautogui.click(), executor)

@register(2)
class DoubleClickInstruction(Instruction):
    """双击指令 - 找到图像后双击"""
    def execute(self, ctx, executor, task, log):
        _find_and_move(ctx, task, lambda: pyautogui.doubleClick(), executor)

@register(3)
class RightClickInstruction(Instruction):
    """右键单击指令 - 找到图像后右键单击"""
    def execute(self, ctx, executor, task, log):
        _find_and_move(ctx, task, lambda: pyautogui.rightClick(), executor)

@register(4)
class HoverInstruction(Instruction):
    """悬停指令 - 移动到图像位置"""
    def execute(self, ctx, executor, task, log):
        img = ctx.resolve(task.get("value", ""))
        region = task.get("region")
        loc = find_image(img, region)
        if loc:
            dur = max(0.0, float(task.get("duration", 0.2)))
            pyautogui.moveTo(loc.x, loc.y, duration=dur)

@register(5)
class InputInstruction(Instruction):
    """输入指令 - 模拟键盘输入文本"""
    def execute(self, ctx, executor, task, log):
        text = ctx.resolve(task.get("value", ""))
        dur = max(0.0, float(task.get("duration", 0)))

        if dur > 0 and len(text) > 0:
            # Uniform input mode: calculate interval for each character based on duration
            interval = dur / len(text)
            slice_time = interval / 10.0

            for ch in text:
                if not executor.is_running:
                    break
                pyautogui.write(ch)
                for _ in range(10):
                    if not executor.is_running:
                        return
                    time.sleep(slice_time)
        else:
            # Fast input mode: use clipboard to paste
            if executor.is_running:
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")

@register(6)
class HotkeyInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pyautogui.hotkey(*[k.strip() for k in ctx.resolve(task.get("value", "")).lower().split("+")])

@register(7)
class KeyPressInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pyautogui.press(ctx.resolve(task.get("value", "")).lower())

@register(8)
class SleepInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        t = float(ctx.resolve(task.get("value", 0)))
        time.sleep(t)

@register(9)
class ScrollInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pyautogui.scroll(int(ctx.resolve(task.get("value", 0))))

@register(10)
class ScreenshotInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        import os
        path = str(ctx.resolve(task.get("value", "")))
        if not path:
            fn = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        elif os.path.isdir(path):
            fn = os.path.join(path, f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")
        else:
            fn = path
            if not fn.endswith((".png", ".jpg", ".bmp")):
                fn += ".png"
        dirname = os.path.dirname(fn)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        pyautogui.screenshot(fn)

@register(11)
class OCRInstruction(Instruction):
    """
    OCR识别指令 - 使用EasyOCR进行屏幕文字识别
    类属性:
        _reader_cache: OCR读取器缓存（单例模式）
        _reader_lock: 线程锁（保证线程安全）
        _lang_list_cache: OCR支持的语言列表
        _thread_pool: OCR线程池（最多2个线程）
    """
    _reader_cache = None
    _reader_lock = threading.Lock()
    _lang_list_cache = OCR_LANGUAGES
    _thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="OCRWorker")

    def execute(self, ctx, executor, task, log):
        """
        Execute OCR recognition
        Process:
        1. Check if EasyOCR is available
        2. Capture screen area (full screen or specified region)
        3. Execute OCR recognition in thread pool (avoid blocking main thread)
        4. Wait for OCR result (with timeout)
        5. Save recognition result to variable context
        """
        if not EASYOCR_AVAILABLE:
            log("OCR not available: easyocr not installed")
            return
            
        var_name = task.get("var", "ocr_result")  # Variable name to save OCR result
        region = task.get("region")  # Recognition region
        
        try:
            # Capture screen
            img = pyautogui.screenshot(region=parse_region(region)) if region else pyautogui.screenshot()
            img_np = np.array(img)  # Convert to numpy array
            
            result_container = {"result": ""}  # Used to pass results between threads
            
            def ocr_thread_func():
                """
                OCR recognition thread function
                Uses singleton pattern for OCR reader to avoid repeated initialization
                """
                try:
                    with OCRInstruction._reader_lock:
                        if OCRInstruction._reader_cache is None:
                            # First use, initialize OCR reader
                            OCRInstruction._reader_cache = easyocr.Reader(
                                OCRInstruction._lang_list_cache, 
                                gpu=False,  # Don't use GPU
                                verbose=False  # Don't output detailed logs
                            )
                    reader = OCRInstruction._reader_cache
                    result = reader.readtext(img_np, detail=0, paragraph=True)  # Execute OCR recognition
                    result_container["result"] = "".join(result)  # Merge recognition results
                except Exception as e:
                    result_container["result"] = f"OCR thread exception: {str(e)}"
            
            # Submit OCR task to thread pool
            future = OCRInstruction._thread_pool.submit(ocr_thread_func)
            try:
                future.result(timeout=OCR_TIMEOUT)  # Wait for OCR result with timeout
                ctx.vars[var_name] = result_container["result"]  # Save result to variable context
                log(f"OCR recognition completed, result length: {len(result_container['result'])}")
            except concurrent.futures.TimeoutError:
                log("OCR execution timeout (8 seconds)")
                ctx.vars[var_name] = "OCR timeout"
                future.cancel()
            except Exception as e:
                log(f"OCR failed: {str(e)}")
                ctx.vars[var_name] = result_container.get("result", "")
            finally:
                if not future.done():
                    future.cancel()  # Ensure future is cancelled
                    
        except Exception as e:
            log(f"OCR 截图失败: {str(e)}")
            ctx.vars[var_name] = ""

@register(12)
class IfInstruction(Instruction):
    """
    If judgment instruction - Supports image, OCR, and variable condition judgment
    Condition formats:
    - img:path/to/image.png - Check if image exists on screen
    - ocr:text_to_find - Check if text exists on screen (using OCR)
    - var:expression - Evaluate variable expression (e.g., var:x > 5)
    """
    _lang_list_cache = OCR_LANGUAGES
    _reader_cache = None
    _reader_lock = threading.Lock()
    
    def execute(self, ctx, executor, task, log):
        cond = ctx.resolve(task.get("value", ""))
        region = task.get("region")
        ok = False
        
        if cond.startswith("img:"):
            ok = find_image(cond[4:], region) is not None
        elif cond.startswith("ocr:"):
            if not EASYOCR_AVAILABLE:
                log("OCR not available: easyocr not installed")
                ok = False
            else:
                try:
                    with IfInstruction._reader_lock:
                        if not hasattr(IfInstruction, '_reader_cache'):
                            IfInstruction._reader_cache = easyocr.Reader(IfInstruction._lang_list_cache, gpu=False)
                    reader = IfInstruction._reader_cache
                    img = pyautogui.screenshot(region=parse_region(region)) if region else pyautogui.screenshot()
                    text = "".join([r[1] for r in reader.readtext(np.array(img))])
                    ok = cond[4:] in text
                except Exception as e:
                    log(f"OCR judgment failed: {e}")
                    ok = False
        elif cond.startswith("var:"):
            expr = cond[4:]
            try:
                import ast
                import operator
                
                ops = {
                    ast.Eq: operator.eq,
                    ast.NotEq: operator.ne,
                    ast.Lt: operator.lt,
                    ast.LtE: operator.le,
                    ast.Gt: operator.gt,
                    ast.GtE: operator.ge,
                }
                
                node = ast.parse(expr, mode='eval')
                
                def _eval(node):
                    if isinstance(node, ast.Constant):
                        return node.value
                    elif isinstance(node, ast.Num):
                        return node.n
                    elif isinstance(node, ast.NameConstant):
                        return node.value
                    elif isinstance(node, ast.Name):
                        if node.id in ctx.vars:
                            val = ctx.vars[node.id]
                            # Only allow basic types
                            if isinstance(val, (int, float, str, bool)):
                                return val
                            raise ValueError(f"变量 {node.id} 类型不支持")
                        raise NameError(f"变量 '{node.id}' 未定义")
                    elif isinstance(node, ast.Compare):
                        left = _eval(node.left)
                        for op, comparator in zip(node.ops, node.comparators):
                            right = _eval(comparator)
                            op_type = type(op)
                            if op_type not in ops:
                                raise ValueError(f"不支持的比较操作符: {op_type}")
                            if not ops[op_type](left, right):
                                return False
                            left = right
                        return True
                    elif isinstance(node, ast.BoolOp):
                        if isinstance(node.op, ast.And):
                            for value in node.values:
                                if not _eval(value):
                                    return False
                            return True
                        elif isinstance(node.op, ast.Or):
                            for value in node.values:
                                if _eval(value):
                                    return True
                            return False
                    elif isinstance(node, ast.UnaryOp):
                        if isinstance(node.op, ast.Not):
                            return not _eval(node.operand)
                        else:
                            raise ValueError("不支持的一元操作符")
                    else:
                        raise ValueError(f"不支持的表达式类型: {type(node)}")
                
                ok = _eval(node.body)
            except Exception as e:
                log(f"条件表达式解析失败: {e}")
                ok = False
                
        executor._condition_pass = ok

@register(13)
class ElseInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        executor._condition_pass = not executor._condition_pass

@register(14)
class EndIfInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        executor._condition_pass = True

@register(15)
class RepeatStartInstruction(Instruction):
    def skip_to_end(self, tasks, idx):
        return idx + 1

@register(16)
class RepeatEndInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pass

@register(17)
class IfImageExistsInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pass

@register(18)
class IfImageNotExistsInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pass

@register(19)
class ConditionEndInstruction(Instruction):
    def execute(self, ctx, executor, task, log):
        pass

class Executor:
    """
    Task executor - Manages task execution, step mode, and condition handling
    """
    def __init__(self):
        self.is_running = True
        self._condition_pass = True
        self.step_mode = False
        self.step_event = threading.Event()
        self._lock = threading.Lock()  # Add thread safety lock
        
    def stop(self):
        with self._lock:
            self.is_running = False
            self.step_event.set()
            self._condition_pass = True
        
    def set_step_mode(self, enable=True):
        with self._lock:
            self.step_mode = enable
            if not enable:
                self.step_event.set()
            
    def wait_step(self):
        self.step_event.clear()
        while self.is_running and not self.step_event.is_set():
            self.step_event.wait(timeout=0.1)
            
    def _find_end(self, task_list, start_idx, start_type, end_type):
        depth = 1
        i = start_idx + 1
        while i < len(task_list):
            ct = task_list[i].get("type")
            if ct == start_type:
                depth += 1
            elif ct == end_type:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return len(task_list) - 1
        
    def run_tasks(self, tasks, vars=None, loop=False, log=print):
        import time as _time
        import threading
        start_time = _time.time()
        max_runtime = 3600
        log(f"[Executor][TID:{threading.get_ident()}] loop={loop}")
        ctx = VarContext()
        if vars:
            ctx.vars.update(vars)
            
        stack = [(tasks, 0, 1)]
        while stack and self.is_running:
            if _time.time() - start_time > max_runtime:
                log("Execution timeout, force stop")
                self.is_running = False
                break
            if not self.is_running:
                break

            task_list, idx, max_repeat = stack[-1]

            # Loop mode optimization: avoid repeated stack frame creation
            if idx >= len(task_list):
                stack.pop()
                if not stack:
                    if loop and self.is_running:
                        # Reset to initial state instead of recreating
                        stack.append((tasks, 0, 1))
                        ctx = VarContext()
                        if vars:
                            ctx.vars.update(vars)
                        self._condition_pass = True
                    continue
                continue

            task = task_list[idx]
            t = task.get("type")
            stack[-1] = (task_list, idx + 1, max_repeat)
            
            inst = get_instruction(t)
            if not inst:
                log(f"未知指令: {t}")
                continue
                
            if not self._condition_pass and t not in (12, 13, 14):
                end = self._find_end(task_list, idx - 1, 12, 14)
                stack[-1] = (task_list, end + 1, max_repeat)
                continue
                
            if t == 13:
                if self._condition_pass:
                    end = self._find_end(task_list, idx - 1, 13, 14)
                    stack[-1] = (task_list, end + 1, max_repeat)
                continue
                
            if t == 14:
                continue
                
            if t == 15:
                end = self._find_end(task_list, idx - 1, 15, 16)
                cnt = int(task.get("repeat", task.get("value", 1)))
                if cnt < 0:
                    stack.append((task_list[idx:end], 0, -1))
                else:
                    stack.append((task_list[idx:end], 0, cnt))
                continue
                
            if t == 16:
                continue
                
            if t == 17:
                end = self._find_end(task_list, idx - 1, 17, 19)
                img = ctx.resolve(task.get("value", ""))
                region = task.get("region")
                if find_image(img, region) is not None:
                    stack.append((task_list[idx:end], 0, 1))
                continue
                
            if t == 18:
                end = self._find_end(task_list, idx - 1, 18, 19)
                img = ctx.resolve(task.get("value", ""))
                region = task.get("region")
                if find_image(img, region) is None:
                    stack.append((task_list[idx:end], 0, 1))
                continue
                
            if t == 19:
                continue
                
            if self.step_mode:
                self.wait_step()
                
            try:
                inst.execute(ctx, self, task, log)
            except Exception as e:
                log(f"执行失败，任务终止: {e}")
                self.is_running = False
                break
                
        self.is_running = False

class MouseRecordEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.User + 1)
    
    def __init__(self, x, y, button):
        super().__init__(MouseRecordEvent.EVENT_TYPE)
        self.x = x
        self.y = y
        self.button = button

class KeyboardRecordEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.User + 2)
    
    def __init__(self, keys):
        super().__init__(KeyboardRecordEvent.EVENT_TYPE)
        self.keys = keys

class WorkerThread(QThread):
    log_signal = Signal(str)
    finished_signal = Signal()
    
    def __init__(self, engine, tasks, loop, vars=None):
        super().__init__()
        self.engine = engine
        self.tasks = tasks
        self.loop = loop
        self.vars = vars or {}
        
    def run(self):
        def _log(msg):
            self.log_signal.emit(f"[{time.strftime('%H:%M:%S')}] {msg}")
        self.engine.run_tasks(self.tasks, self.vars, self.loop, _log)
        self.finished_signal.emit()

KEY_MAP = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt",
    "shift_l": "shift", "shift_r": "shift",
}

CMD_TYPES_REV = {
    1: "左键单击", 2: "左键双击", 3: "右键单击",
    4: "鼠标悬停", 5: "输入文本", 6: "系统按键",
    7: "单独按键", 8: "等待", 9: "滚轮", 10: "截图保存",
    11: "OCR 识别", 12: "IF 条件", 13: "ELSE",
    14: "END IF", 15: "重复执行开始", 16: "重复执行结束",
    17: "如果图片存在", 18: "如果图片不存在", 19: "条件结束"
}

CMD_TYPES = {v: k for k, v in CMD_TYPES_REV.items()}
IMAGE_TYPES = [1, 2, 3, 4, 11, 12, 13, 14, 17, 18]
DURATION_SUPPORTED = {1, 2, 3, 4, 5}

def normalize_key(k):
    return KEY_MAP.get(k, k)

class TaskRow(QFrame):
    def __init__(self, layout, delete_cb, up_cb, down_cb, pick_cb):
        super().__init__()
        self.pick_cb = pick_cb
        self.setFrameShape(QFrame.StyledPanel)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 2, 4, 2)
        main_layout.setSpacing(2)
        
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        
        self.type = QComboBox()
        self.type.addItems(CMD_TYPES.keys())
        self.type.setFixedWidth(100)
        row1.addWidget(self.type)
        
        self.value = QLineEdit()
        self.value.setPlaceholderText("参数")
        row1.addWidget(self.value, 1)
        
        self.file_btn = QPushButton("选择")
        self.file_btn.setFixedWidth(60)
        self.file_btn.clicked.connect(self.select)
        row1.addWidget(self.file_btn)
        
        main_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        
        self.retry_label = QLabel("重试:")
        self.retry_label.setFixedWidth(40)
        row2.addWidget(self.retry_label)
        
        self.retry = QLineEdit("1")
        self.retry.setFixedWidth(50)
        row2.addWidget(self.retry)
        
        row2.addSpacing(10)
        
        self.region_label = QLabel("范围:")
        self.region_label.setFixedWidth(40)
        row2.addWidget(self.region_label)
        
        self.region = QLineEdit()
        self.region.setPlaceholderText("识别范围")
        self.region.setFixedWidth(120)
        row2.addWidget(self.region)
        
        self.pick_btn = QPushButton("取点")
        self.pick_btn.setFixedWidth(50)
        self.pick_btn.clicked.connect(self.on_pick)
        row2.addWidget(self.pick_btn)
        
        row2.addSpacing(10)
        
        self.duration_label = QLabel("时间:")
        self.duration_label.setFixedWidth(40)
        row2.addWidget(self.duration_label)
        
        self.duration = QLineEdit()
        self.duration.setPlaceholderText("秒")
        self.duration.setFixedWidth(50)
        row2.addWidget(self.duration)
        
        row2.addStretch()
        
        self.up_btn = QPushButton("↑")
        self.up_btn.setFixedWidth(30)
        self.up_btn.clicked.connect(lambda: up_cb(self))
        row2.addWidget(self.up_btn)
        
        self.down_btn = QPushButton("↓")
        self.down_btn.setFixedWidth(30)
        self.down_btn.clicked.connect(lambda: down_cb(self))
        row2.addWidget(self.down_btn)
        
        self.del_btn = QPushButton("X")
        self.del_btn.setFixedWidth(30)
        self.del_btn.clicked.connect(lambda: delete_cb(self))
        row2.addWidget(self.del_btn)
        
        main_layout.addLayout(row2)
        
        layout.addWidget(self)
        self.type.currentTextChanged.connect(self.update_ui)
        self.update_ui(self.type.currentText())
        self.setAcceptDrops(True)
        
    def update_ui(self, t):
        ct = CMD_TYPES[t]

        # Basic control visibility
        is_image_cmd = ct in IMAGE_TYPES
        self.retry_label.setVisible(is_image_cmd)
        if ct == 11:
            self.retry.setVisible(False)
            self.retry_label.setVisible(False)

        # Region selection related
        needs_region = ct in {1,2,3,4,11,12,17,18}
        self.region.setVisible(needs_region)
        self.region_label.setVisible(needs_region)
        self.pick_btn.setVisible(needs_region)

        # Duration related
        needs_duration = ct in DURATION_SUPPORTED
        self.duration.setVisible(needs_duration)
        self.duration_label.setVisible(needs_duration)

        # Command specific settings
        self._configure_for_command(ct)
        self.setAcceptDrops(True)

    def _configure_for_command(self, ct):
        """Configure UI details based on command type"""
        configs = {
            11: {"btn_text": "选择图片", "placeholder": "变量名"},
            12: {"btn_text": "选择", "placeholder": "条件 (img:/ocr:/var:)"},
            9: {"btn_text": "选择目录", "placeholder": "目录路径"},
            17: {"btn_text": "选择图片", "placeholder": "图片路径"},
            18: {"btn_text": "选择图片", "placeholder": "图片路径"},
        }

        default_config = {"btn_text": "选择图片", "placeholder": "参数"}
        config = configs.get(ct, default_config)

        self.file_btn.setText(config["btn_text"])
        self.value.setPlaceholderText(config["placeholder"])

        if ct == 11:
            self.file_btn.setVisible(False)
            self.file_btn.clicked.disconnect()
            self.file_btn.clicked.connect(self.select_for_ocr)
        else:
            self.file_btn.clicked.disconnect()
            self.file_btn.clicked.connect(self.select)

    def select_for_ocr(self):
        """OCR指令的特殊文件选择：选择图片用于OCR识别"""
        f, _ = QFileDialog.getOpenFileName(self, "选择OCR识别图片", "", "图片 (*.png *.jpg *.bmp)")
        if f:
            self.value.setText(f)
            
    def select(self):
        ct = CMD_TYPES[self.type.currentText()]
        if ct == 9:
            d = QFileDialog.getExistingDirectory(self, "选择目录")
            if d:
                self.value.setText(d)
        elif ct == 11:
            # OCR instruction's value is variable name, no need to select file
            pass
        else:
            f, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.bmp)")
            if f:
                self.value.setText(f)

    def on_pick(self):
        if self.pick_cb:
            self.pick_cb(self)

    def get_data(self):
        ct = CMD_TYPES[self.type.currentText()]
        d = {
            "type": ct,
            "retry": int(self.retry.text() or 1),
        }
        
        dur_text = self.duration.text().strip()
        if dur_text and ct in DURATION_SUPPORTED:
            try:
                dur_val = float(dur_text)
                if dur_val >= 0:
                    d["duration"] = round(dur_val, 3)  # Keep 3 decimal places to avoid floating-point precision issues
            except ValueError:
                pass
        
        if ct == 11:
            d["var"] = self.value.text().strip() or "ocr_result"
        elif ct == 12:
            d["value"] = self.value.text().strip()
        elif ct not in (13, 14, 16, 19):
            v = self.value.text()
            if v:
                d["value"] = v
        reg_text = self.region.text().strip()
        if reg_text:
            try:
                parts = list(map(int, reg_text.split(",")))
                if len(parts) == 4 and all(p >= 0 for p in parts):
                    d["region"] = reg_text
            except ValueError:
                pass
        return d

class RPAWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RPA 自动化")
        self.resize(900, 600)
        
        self.engine = Executor()
        self.rows = []
        self.worker = None
        self.shortcut = None
        
        self.recording = False
        self.mouse_listener = None
        self.keyboard_listener = None
        self.record_img_dir = "record_imgs"
        os.makedirs(self.record_img_dir, exist_ok=True)
        self.keyboard_state = set()
        self.last_record_time = {}

        # API server related attributes
        self.api_thread = None
        self.api_running = False
        self.api_port = 8000
        self.api_token = ""
        
        c = QWidget()
        self.setCentralWidget(c)
        
        main_layout = QHBoxLayout(c)
        
        sidebar = QFrame()
        sidebar.setFixedWidth(120)
        sidebar.setFrameShape(QFrame.StyledPanel)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setSpacing(6)
        side_layout.setContentsMargins(6, 6, 6, 6)
        
        btn_height = 28
        
        self.add_btn = QPushButton("+ 指令")
        self.add_btn.setMinimumHeight(btn_height)
        self.add_btn.clicked.connect(self.add_row)
        side_layout.addWidget(self.add_btn)
        
        self.save_btn = QPushButton("保存")
        self.save_btn.setMinimumHeight(btn_height)
        self.save_btn.clicked.connect(self.save)
        side_layout.addWidget(self.save_btn)
        
        self.load_btn = QPushButton("加载")
        self.load_btn.setMinimumHeight(btn_height)
        self.load_btn.clicked.connect(self.load)
        side_layout.addWidget(self.load_btn)
        
        self.record_btn = QPushButton("录制")
        self.record_btn.setMinimumHeight(btn_height)
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self.toggle_record)
        side_layout.addWidget(self.record_btn)
        
        self.help_btn = QPushButton("说明书")
        self.help_btn.setMinimumHeight(btn_height)
        self.help_btn.clicked.connect(self.show_help)
        side_layout.addWidget(self.help_btn)
        
        side_layout.addStretch()
        
        self.loop_label = QLabel("执行模式:")
        side_layout.addWidget(self.loop_label)
        
        self.loop = QComboBox()
        self.loop.addItems(["执行一次", "循环执行"])
        side_layout.addWidget(self.loop)
        
        self.start_btn = QPushButton("开始")
        self.start_btn.setMinimumHeight(btn_height)
        self.start_btn.clicked.connect(self.start_task)
        side_layout.addWidget(self.start_btn)
        
        self.step_btn = QPushButton("单步")
        self.step_btn.setMinimumHeight(btn_height)
        self.step_btn.clicked.connect(self.step_task)
        side_layout.addWidget(self.step_btn)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setMinimumHeight(btn_height)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_task)
        side_layout.addWidget(self.stop_btn)

        # API control area
        side_layout.addStretch()
        side_layout.addWidget(QLabel("API 服务:"))

        self.api_start_btn = QPushButton("启动 API")
        self.api_start_btn.setMinimumHeight(btn_height)
        self.api_start_btn.clicked.connect(self.start_api)
        side_layout.addWidget(self.api_start_btn)

        self.api_stop_btn = QPushButton("停止 API")
        self.api_stop_btn.setMinimumHeight(btn_height)
        self.api_stop_btn.setEnabled(False)
        self.api_stop_btn.clicked.connect(self.stop_api)
        side_layout.addWidget(self.api_stop_btn)

        self.api_status_label = QLabel("未运行")
        self.api_status_label.setStyleSheet("color: gray; font-size: 10px;")
        side_layout.addWidget(self.api_status_label)

        self.api_port_label = QLabel("端口: --")
        self.api_port_label.setStyleSheet("font-size: 10px;")
        side_layout.addWidget(self.api_port_label)

        self.api_token_label = QLabel("Token: --")
        self.api_token_label.setStyleSheet("font-size: 10px;")
        self.api_token_label.setWordWrap(True)
        side_layout.addWidget(self.api_token_label)
        
        main_layout.addWidget(sidebar)
        
        right_area = QVBoxLayout()
        
        self.scroll = QScrollArea()
        self.container = QWidget()
        self.task_layout = QVBoxLayout(self.container)
        self.task_layout.addStretch()
        self.scroll.setWidget(self.container)
        self.scroll.setWidgetResizable(True)
        right_area.addWidget(self.scroll, 1)
        
        self.log_label = QLabel("日志")
        right_area.addWidget(self.log_label)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(120)
        right_area.addWidget(self.log_area)
        
        main_layout.addLayout(right_area, 1)
        
    def toggle_record(self):
        self.recording = self.record_btn.isChecked()

        if self.recording:
            self.record_btn.setText("停止录制")
            self.start_btn.setEnabled(False)
            self.log("录制开始（鼠标 + 键盘）")

            try:
                # Ensure previous listeners are stopped
                self._stop_record_listeners()

                self.mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
                self.mouse_listener.start()

                self.keyboard_listener = keyboard.Listener(
                    on_press=self.on_key_press,
                    on_release=self.on_key_release
                )
                self.keyboard_listener.start()
            except Exception as e:
                self.log(f"录制启动失败: {e}")
                self.record_btn.setChecked(False)
                self.recording = False
                self.record_btn.setText("录制")
                self.start_btn.setEnabled(True)
                self._stop_record_listeners()
        else:
            self._stop_record_listeners()
            self.record_btn.setText("录制")
            self.start_btn.setEnabled(True)
            self.log("录制结束")
            
    def _stop_record_listeners(self):
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        self.keyboard_state.clear()
        
    def on_mouse_click(self, x, y, button, pressed):
        if not self.recording or not pressed:
            return
        btn = "left" if str(button) == "Button.left" else "right"
        QApplication.postEvent(self, MouseRecordEvent(x, y, btn))
        
    def on_key_press(self, key):
        if not self.recording:
            return
        try:
            if hasattr(key, 'char') and key.char is not None:
                k = key.char
            else:
                k = str(key).replace("Key.", "")
                k = normalize_key(k)
            if k not in self.keyboard_state:
                self.keyboard_state.add(k)
                QApplication.postEvent(self, KeyboardRecordEvent(self.keyboard_state.copy()))
        except AttributeError:
            pass
            
    def on_key_release(self, key):
        try:
            if hasattr(key, 'char') and key.char is not None:
                k = key.char
            else:
                k = normalize_key(str(key).replace("Key.", ""))
            self.keyboard_state.discard(k)
        except AttributeError:
            pass
        
    def record_click(self, x, y, button):
        now = time.time()
        if now - self.last_record_time.get(button, 0) < 0.3:
            return
        self.last_record_time[button] = now
        
        ts = time.strftime("%Y%m%d_%H%M%S")
        img_name = f"click_{ts}_{x}_{y}.png"
        img_path = os.path.join(self.record_img_dir, img_name)
        
        half_size = 30
        screen_w, screen_h = pyautogui.size()
        x1 = max(0, x - half_size)
        y1 = max(0, y - half_size)
        x2 = min(screen_w - 1, x + half_size)  # Prevent out of bounds
        y2 = min(screen_h - 1, y + half_size)
        w = max(1, x2 - x1)  # Ensure width is at least 1
        h = max(1, y2 - y1)  # Ensure height is at least 1
        
        if w <= 0 or h <= 0:
            self.log("截图区域无效，跳过录制")
            return
            
        try:
            pyautogui.screenshot(img_path, region=(x1, y1, w, h))
            cmd_type = 1 if button == "left" else 3
            self.add_row({
                "type": cmd_type,
                "value": img_path,
                "retry": 1,
            })
            self.log(f"录制 {button} 点击 -> {img_path}")
        except Exception as e:
            self.log(f"截图失败: {e}")
        
    def record_keyboard(self, keys):
        current_time = time.time()
        if hasattr(self, '_last_key_record') and current_time - self._last_key_record < 0.1:
            return
        self._last_key_record = current_time
        
        if not keys:
            return
        keys = sorted(keys)
        modifiers = {"ctrl", "alt", "shift", "win"}
        filtered_keys = [k for k in keys if k not in modifiers]

        if len(filtered_keys) > 1 or any(k in ("ctrl", "alt", "shift") for k in filtered_keys):
            combo = "+".join(filtered_keys)
            self.add_row({
                "type": 6,
                "value": combo,
                "retry": 1,
            })
            self.log(f"录制组合键: {combo}")
        elif filtered_keys and filtered_keys[0] in ("enter", "tab", "space", "esc", "backspace"):
            self.add_row({
                "type": 7,
                "value": filtered_keys[0],
                "retry": 1,
            })
            self.log(f"录制单独按键: {filtered_keys[0]}")
            
    def event(self, event):
        if event.type() == MouseRecordEvent.EVENT_TYPE:
            self.record_click(event.x, event.y, event.button)
            return True
        elif event.type() == KeyboardRecordEvent.EVENT_TYPE:
            self.record_keyboard(event.keys)
            return True
        return super().event(event)
        
    def add_row(self, data=None):
        if self.task_layout.count() > 0:
            item = self.task_layout.takeAt(self.task_layout.count() - 1)
            if item and item.widget():
                item.widget().deleteLater()
                
        r = TaskRow(self.task_layout, self.delete_row,
                    self.move_up, self.move_down, self.pick_region)
        if data:
            r.type.setCurrentText(CMD_TYPES_REV[data["type"]])
            if "value" in data:
                r.value.setText(str(data["value"]))
            r.retry.setText(str(data.get("retry", 1)))
            r.region.setText(data.get("region", "") if data.get("region") else "")
            dur = data.get("duration", 0)
            if dur and float(dur) > 0:
                r.duration.setText(str(dur))
        self.rows.append(r)
        self.task_layout.addWidget(r)
        self.task_layout.addStretch()
        
    def delete_row(self, r):
        if r in self.rows:
            self.rows.remove(r)
        r.deleteLater()
        self.rebuild()
        
    def move_up(self, r):
        i = self.rows.index(r)
        if i > 0:
            self.rows[i], self.rows[i-1] = self.rows[i-1], self.rows[i]
            self.rebuild()
            
    def move_down(self, r):
        i = self.rows.index(r)
        if i < len(self.rows) - 1:
            self.rows[i], self.rows[i+1] = self.rows[i+1], self.rows[i]
            self.rebuild()
            
    def rebuild(self):
        while self.task_layout.count():
            item = self.task_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for r in self.rows:
            self.task_layout.addWidget(r)
        self.task_layout.addStretch()
        
    def pick_region(self, row):
        self.log("取点工具启动：按 1 取左上角，按 2 取右下角，按 Q 退出")

        was_recording = self.recording
        if was_recording:
            self.record_btn.setChecked(False)
            self.toggle_record()

        self.showMinimized()
        QApplication.processEvents()  # Ensure window state update

        pt1 = None
        pt2 = None

        def on_press(key):
            nonlocal pt1, pt2
            try:
                if hasattr(key, 'char'):
                    char = key.char.lower() if key.char else None
                    if char == '1':
                        pt1 = pyautogui.position()
                        self.log(f"左上角: ({pt1.x}, {pt1.y})")
                    elif char == '2':
                        pt2 = pyautogui.position()
                        self.log(f"右下角: ({pt2.x}, {pt2.y})")
                    elif char in ('q', 'esc'):  # Support ESC to exit
                        return False
            except Exception as e:
                self.log(f"取点按键处理异常: {e}")
                return False

        try:
            with keyboard.Listener(on_press=on_press) as listener:
                listener.join()
        except Exception as e:
            self.log(f"取点工具异常: {e}")
        finally:
            self.showNormal()
            QApplication.processEvents()

            if was_recording:
                self.record_btn.setChecked(True)
                self.toggle_record()

            if pt1 and pt2:
                x = min(pt1.x, pt2.x)
                y = min(pt1.y, pt2.y)
                w = abs(pt2.x - pt1.x)
                h = abs(pt2.y - pt1.y)
                if w > 0 and h > 0:
                    region_text = f"{x},{y},{w},{h}"
                    row.region.setText(region_text)
                    self.log(f"区域已设置: {region_text}")
                else:
                    self.log("无效的矩形区域")
            else:
                self.log("取点取消")
            
    def save(self):
        d = [r.get_data() for r in self.rows]
        f, _ = QFileDialog.getSaveFileName(self, "保存", "", "JSON (*.json)")
        if f:
            # Ensure file extension
            if not f.lower().endswith('.json'):
                f += '.json'
            try:
                save_data = {
                    "version": VERSION,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "tasks": d
                }
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(save_data, fp, indent=4, ensure_ascii=False)
                self.log(f"保存成功: {f}")
            except PermissionError:
                self.log(f"保存失败: 无写入权限 {f}")
                QMessageBox.warning(self, "保存失败", "无文件写入权限")
            except Exception as e:
                self.log(f"保存失败: {e}")
                QMessageBox.warning(self, "保存失败", f"无法保存文件: {str(e)}")
                
    def load(self):
        f, _ = QFileDialog.getOpenFileName(self, "加载", "", "JSON (*.json)")
        if not f:
            return
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            # Version check
            version = data.get("version", "未知")
            if version != VERSION:
                self.log(f"警告：加载的文件版本({version})与当前版本({VERSION})不一致，可能存在兼容性问题")

            tasks_data = data.get("tasks", [])
            if not isinstance(tasks_data, list):
                raise ValueError("无效的任务数据格式")

            for r in self.rows:
                r.deleteLater()
            self.rows.clear()

            for t in tasks_data:
                # Compatible with old version fields
                t.setdefault("value", "")
                t.setdefault("retry", 1)
                t.setdefault("duration", 0)
                t.setdefault("region", "")
                self.add_row(t)
            self.log(f"加载成功: {f} (版本: {version})")
        except json.JSONDecodeError:
            self.log(f"加载失败: JSON格式错误")
            QMessageBox.warning(self, "加载失败", "文件格式错误，不是有效的JSON文件")
        except Exception as e:
            self.log(f"加载失败: {e}")
            QMessageBox.warning(self, "加载失败", f"无法加载文件: {str(e)}")

    def start_task(self):
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.log("警告：已有任务正在运行，请先停止")
            return

        self.engine = Executor()
        self.engine.set_step_mode(False)
        tasks = [r.get_data() for r in self.rows]
        if not tasks:
            self.log("无任务可执行")
            return

        self.log_area.clear()
        self.start_btn.setEnabled(False)
        self.step_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.worker = WorkerThread(self.engine, tasks, self.loop.currentIndex() == 1)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_finish)
        self.shortcut = QShortcut(QKeySequence("F8"), self)
        self.shortcut.activated.connect(self.engine.stop)
        self.worker.start()
        self.showMinimized()
        
    def step_task(self):
        if not self.engine.step_mode:
            self.engine = Executor()
            tasks = [r.get_data() for r in self.rows]
            if not tasks:
                return
            self.log_area.clear()
            self.start_btn.setEnabled(False)
            self.step_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.engine.set_step_mode(True)
            self.worker = WorkerThread(self.engine, tasks, False)
            self.worker.log_signal.connect(self.log)
            self.worker.finished_signal.connect(self.on_finish)
            self.shortcut = QShortcut(QKeySequence("F8"), self)
            self.shortcut.activated.connect(self.engine.stop)
            self.worker.start()
        self.engine.step_event.set()
        self.showMinimized()
        
    def stop_task(self):
        self.engine.stop()

    def start_api(self):
        """启动 API 服务器"""
        if self.api_running:
            self.log("API 服务器已在运行")
            return

        # Check if API is available
        if not API_AVAILABLE:
            self.log("API 模块不可用，请安装 fastapi 和 uvicorn")
            self.log("运行命令: pip install fastapi uvicorn python-multipart")
            return

        try:
            # Generate Token (if not already generated)
            if not self.api_token:
                import secrets
                self.api_token = secrets.token_urlsafe(32)

            # Create configuration
            config = {
                "host": "127.0.0.1",
                "port": self.api_port,
                "token": self.api_token,
                "default_timeout": 30,
                "debug": False
            }

            # Create and start API server thread
            self.api_thread = ApiServerThread(config)
            self.api_thread.start()

            # Update status
            self.api_running = True
            self.api_start_btn.setEnabled(False)
            self.api_stop_btn.setEnabled(True)
            self.api_status_label.setText("运行中")
            self.api_status_label.setStyleSheet("color: green; font-size: 10px;")
            self.api_port_label.setText(f"端口: {self.api_port}")
            self.api_token_label.setText(f"Token: {self.api_token[:20]}...")

            self.log(f"API 服务器启动成功，端口: {self.api_port}")
            self.log(f"Token: {self.api_token}")

        except Exception as e:
            self.log(f"启动 API 服务器失败: {e}")
            import traceback
            self.log(traceback.format_exc())

    def stop_api(self):
        """停止 API 服务器"""
        if not self.api_running or not self.api_thread:
            self.log("API 服务器未运行")
            return

        try:
            # Stop API server
            self.api_thread.stop()
            self.api_thread.join(timeout=5)

            # Update status
            self.api_running = False
            self.api_start_btn.setEnabled(True)
            self.api_stop_btn.setEnabled(False)
            self.api_status_label.setText("未运行")
            self.api_status_label.setStyleSheet("color: gray; font-size: 10px;")

            self.log("API 服务器已停止")

        except Exception as e:
            self.log(f"停止 API 服务器失败: {e}")

    def on_finish(self):
        self.start_btn.setEnabled(True)
        self.step_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.engine.set_step_mode(False)
        if self.shortcut:
            self.shortcut.deleteLater()
            self.shortcut = None
        self._stop_record_listeners()
        self.showNormal()
        
    def log(self, m):
        self.log_area.append(m)
        
    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("RPA 自动化 - 使用说明书")
        dialog.resize(700, 520)
        
        layout = QVBoxLayout(dialog)
        
        text_browser = QTextBrowser(dialog)
        text_browser.setLineWrapMode(QTextBrowser.WidgetWidth)
        text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        text_browser.setPlainText(
            "RPA 自动化工具 使用说明书（完整通俗版）\n"
            "=================================================\n\n"
            "一、这是什么软件\n\n"
            "这是一个用来自动控制电脑的软件。\n"
            "你只需要告诉它点哪里、输入什么、什么时候做什么，\n"
            "它就可以代替你重复地点鼠标、敲键盘。\n\n"
            "不需要写程序，也不需要懂英文，\n"
            "只要会认字和数数就能用。\n\n"
            "新功能：支持 API 接口，可以让其他程序调用本软件的功能。\n\n"
            "二、软件界面说明\n\n"
            "软件打开后，主要分为三个部分：\n\n"
            "1. 左侧控制栏\n"
            "这里有一排按钮，常用的有：\n"
            "  • + 指令：添加一个新的操作步骤\n"
            "  • 保存：把你设置好的步骤存成一个文件\n"
            "  • 加载：打开之前保存好的步骤文件\n"
            "  • 录制：自动记录你的鼠标和键盘操作\n"
            "  • 开始：让电脑开始自动执行\n"
            "  • 停止：立刻停止所有操作\n"
            "  • 启动 API：启动 API 服务器（新增）\n"
            "  • 停止 API：停止 API 服务器（新增）\n\n"
            "2. 中间指令列表区\n"
            "这里是你添加的所有操作步骤，\n"
            "每一行就是一个指令。\n"
            "你可以添加很多行，从上到下依次执行。\n\n"
            "3. 底部日志区\n"
            "这里会显示软件执行的过程，\n"
            "比如什么时候开始了、做了什么、有没有出错。\n\n"
            "4. API 服务状态区（新增）\n"
            "在左侧控制栏底部，显示 API 服务的状态：\n"
            "  • API 服务：显示是否运行\n"
            "  • 端口：显示 API 监听的端口号\n"
            "  • Token：显示认证令牌（用于 API 调用）\n\n"
            "三、最常用的几种指令\n\n"
            "下面这些是平时最常用的，记住这几个就够用了。\n\n"
            "1. 左键单击\n"
            "作用：在屏幕上找一张图片，找到后点一下鼠标左键。\n"
            "使用方法：\n"
            "  点击 + 指令\n"
            "  选择 左键单击\n"
            "  点击 选择图片，从电脑里选一张截图\n\n"
            "2. 右键单击\n"
            "作用和左键单击一样，只不过点的是鼠标右键。\n\n"
            "3. 输入文本\n"
            "作用：自动输入一段文字。\n"
            "例子：\n"
            "  输入文本 你好\n"
            "  电脑就会自动输入：你好\n\n"
            "4. 等待\n"
            "作用：让电脑暂停几秒钟。\n"
            "例子：\n"
            "  等待 2\n"
            "  意思是让电脑等 2 秒再继续。\n\n"
            "5. 滚轮\n"
            "作用：滚动鼠标滚轮。\n"
            "例子：\n"
            "  滚轮 1   向上滚\n"
            "  滚轮 -1  向下滚\n\n"
            "6. OCR 识别\n"
            "作用：让电脑从屏幕里识别文字。\n"
            "使用方法：\n"
            "  选择 OCR 识别\n"
            "  在参数框里填一个名字，比如 text\n"
            "  执行后，你可以用 {{text}} 代表识别出来的内容。\n\n"
            "7. IF 条件\n"
            "作用：如果满足条件就做一件事，不满足就做另一件事。\n"
            "例子：\n"
            "  IF 条件 img:成功.png\n"
            "      输入文本 成功了\n"
            "  ELSE\n"
            "      输入文本 失败了\n"
            "  END IF\n"
            "意思是：\n"
            "  如果屏幕上看到了 成功.png，就输入 成功了，\n"
            "  否则就输入 失败了。\n\n"
            "四、怎么让电脑自动操作\n\n"
            "方法一：手动添加（最稳妥）\n"
            "1. 点击 + 指令\n"
            "2. 选择一个操作类型\n"
            "3. 填写对应的参数\n"
            "4. 重复以上步骤，直到把所有步骤都加完\n\n"
            "方法二：录制（最快）\n"
            "1. 点击 录制\n"
            "2. 用鼠标去点屏幕上的按钮\n"
            "3. 用键盘按需要的快捷键\n"
            "4. 点击 停止录制\n"
            "软件会自动帮你生成刚才的操作步骤。\n\n"
            "五、单步执行是什么\n\n"
            "单步执行就是让电脑一次只做一步。\n\n"
            "使用方法：\n"
            "1. 点击一次 单步执行\n"
            "   电脑只执行第一条指令\n"
            "2. 再点一次\n"
            "   电脑执行第二条指令\n\n"
            "这个功能非常适合用来检查步骤有没有问题。\n\n"
            "六、如何保存和重复使用\n\n"
            "1. 点击 保存\n"
            "2. 选择一个文件夹，起一个文件名\n"
            "以后只要点击 加载，选择这个文件，\n"
            "之前设置好的所有步骤就会重新出现。\n\n"
            "七、API 接口功能（新增）\n\n"
            "API 功能可以让其他程序（如 AI Agent）调用本软件的功能。\n\n"
            "启用方法：\n"
            "1. 确保已安装依赖：pip install fastapi uvicorn python-multipart\n"
            "2. 在软件界面点击 启动 API 按钮\n"
            "3. 查看底部状态，会显示端口和 Token\n"
            "4. 将 Token 复制到调用方的配置中\n\n"
            "支持的 API 操作：\n"
            "  • click：找图点击\n"
            "  • input：输入文本\n"
            "  • screenshot：截图保存\n"
            "  • ocr：OCR 识别\n"
            "  • wait：等待指定秒数\n"
            "  • find_image：找图\n"
            "  • key_press：按键\n"
            "  • mouse_click：鼠标点击\n"
            "  • scroll：滚动\n"
            "  • drag：拖拽\n"
            "  • execute_json：执行 JSON 配置文件\n\n"
            "调用示例（需要 Token 认证）：\n"
            "  curl -X POST http://127.0.0.1:8000/api/rpa/run \\\n"
            "    -H \"Authorization: Bearer <你的token>\" \\\n"
            "    -H \"Content-Type: application/json\" \\\n"
            "    -d '{\"action\": \"click\", \"target\": \"button.png\"}'\n\n"
            "注意事项：\n"
            "  • API 服务器和调用方必须在同一台机器上\n"
            "  • 因为 RPA 需要操作桌面，必须有图形界面\n"
            "  • 默认超时时间：30 秒\n"
            "  • Token 在首次启动时自动生成，请妥善保管\n\n"
            "八、常见问题\n\n"
            "问：为什么点不了？\n"
            "答：可能是图片不清楚，或者屏幕分辨率变了。\n"
            "解决方法：重新截图，或者用 取点 功能限定搜索范围。\n\n"
            "问：如何紧急停止？\n"
            "答：按键盘上的 F8，或者点击 停止 按钮。\n\n"
            "问：API 功能用不了？\n"
            "答：请确保已安装 fastapi 和 uvicorn，运行命令：\n"
            "  pip install fastapi uvicorn python-multipart\n\n"
            "九、重要注意事项\n\n"
            "在执行自动化任务的时候：\n"
            "1. 千万不要动鼠标\n"
            "2. 千万不要敲键盘\n"
            "3. 不要切换窗口\n\n"
            "否则电脑会点错地方，导致操作失败。\n\n"
            "使用 API 功能时：\n"
            "1. 确保屏幕不被锁定\n"
            "2. 确保 RPA 工具正在运行\n"
            "3. 确保 API 服务器已启动\n\n"
            "十、一句话总结\n\n"
            "这是一个你教一遍，它做一万遍的工具。\n"
            "像写做菜步骤一样，一步一步教它就行。\n\n"
            "新功能：现在还可以通过 API 接口，\n"
            "让 AI Agent 自动调用它！"
        )
        layout.addWidget(text_browser)
        
        close_btn = QPushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec()
        
    def closeEvent(self, event):
        # Stop API server
        if self.api_running and self.api_thread:
            self.log("Stopping API server...")
            self.stop_api()
            self.api_thread.join(timeout=5)

        # Stop all background operations
        self._stop_record_listeners()

        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self.engine.stop()
            self.worker.wait(2000)  # Wait 2 seconds
            if self.worker.isRunning():
                self.log("Force terminate worker thread")
                self.worker.terminate()
                self.worker.wait()

        # Cleanup OCR thread pool
        if hasattr(OCRInstruction, '_thread_pool'):
            try:
                OCRInstruction._thread_pool.shutdown(wait=True, timeout=3.0)
            except Exception as e:
                self.log(f"OCR thread pool shutdown exception: {e}")

        # Cleanup temporary files
        try:
            if os.path.exists(self.record_img_dir):
                import shutil
                shutil.rmtree(self.record_img_dir, ignore_errors=True)
        except Exception as e:
            self.log(f"Cleanup temporary files failed: {e}")

        # Release shortcut keys
        if hasattr(self, 'shortcut') and self.shortcut:
            self.shortcut.deleteLater()

        self.log("Program exited normally")
        super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    w = RPAWindow()
    w.show()
    sys.exit(app.exec())

def run_cli(json_file):
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        engine = Executor()
        print(f"[{time.strftime('%H:%M:%S')}] [INFO] 开始执行任务: {json_file}")
        engine.run_tasks(
            cfg.get("tasks", []),
            cfg.get("vars", {}),
            cfg.get("loop", False),
            lambda msg: print(f"[{time.strftime('%H:%M:%S')}] {msg}")
        )
        print("[INFO] 任务执行完成")
    except FileNotFoundError:
        print(f"[ERROR] 文件不存在: {json_file}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"[ERROR] JSON格式错误: {json_file}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("[INFO] 用户中断执行")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] 执行失败: {e}")
        sys.exit(1)

# ============================================================================
# API Service Module (Optional, requires fastapi and uvicorn)
# ============================================================================

# Try to import FastAPI related modules
try:
    from pydantic import BaseModel, Field
    from fastapi import FastAPI, HTTPException, Depends, Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    from typing import Optional, Dict, Any

    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False
    BaseModel = None
    Field = None
    FastAPI = None
    HTTPException = None
    Depends = None
    Request = None
    JSONResponse = None
    CORSMiddleware = None
    uvicorn = None


if API_AVAILABLE:
    # ============================================================================
    # Pydantic Data Models
    # ============================================================================

    class RpaRunRequest(BaseModel):
        """RPA 执行请求模型"""
        action: str = Field(..., description="要执行的操作，如：click、input、screenshot、ocr、wait、find_image、key_press、mouse_click")
        target: str = Field("", description="操作对象，如：图片路径、网址、文件路径、文本内容")
        params: Optional[Dict[str, Any]] = Field(default={}, description="其他可选参数")

    class RpaRunResponse(BaseModel):
        """RPA 执行响应模型"""
        success: bool = Field(..., description="执行是否成功")
        message: str = Field(..., description="执行结果描述")
        data: Optional[Any] = Field(None, description="返回数据")
        execution_time: float = Field(..., description="执行耗时（秒）")

    class ApiConfig(BaseModel):
        """API 配置模型"""
        host: str = "127.0.0.1"
        port: int = 8000
        token: str = ""
        default_timeout: int = 30
        debug: bool = False

    # ============================================================================
    # Token Authentication Dependency
    # ============================================================================

    def create_auth_dependency(token: str):
        """创建认证依赖"""
        def verify_token(request: Request):
            auth_header = request.headers.get("Authorization")
            if not auth_header:
                raise HTTPException(status_code=401, detail="缺少 Authorization 请求头")

            parts = auth_header.split()
            if len(parts) != 2 or parts[0].lower() != "bearer":
                raise HTTPException(status_code=401, detail="Invalid authorization header format")

            if parts[1] != token:
                raise HTTPException(status_code=401, detail="Invalid token")

            return parts[1]

        return verify_token

    # ============================================================================
    # Action Handler Class
    # ============================================================================

    class ActionHandler:
        """处理 RPA action 映射和执行"""

        def __init__(self, config: dict):
            self.config = config
            self.default_timeout = config.get("default_timeout", 30)

        def handle(self, req: RpaRunRequest) -> dict:
            """处理 RPA 执行请求"""
            start_time = time.time()

            try:
                # Get timeout parameter
                timeout = req.params.get("timeout", self.default_timeout)

                # Map action to corresponding RPA function
                result = None

                if req.action == "click":
                    result = self._handle_click(req, timeout)
                elif req.action == "input":
                    result = self._handle_input(req, timeout)
                elif req.action == "screenshot":
                    result = self._handle_screenshot(req, timeout)
                elif req.action == "ocr":
                    result = self._handle_ocr(req, timeout)
                elif req.action == "wait":
                    result = self._handle_wait(req, timeout)
                elif req.action == "find_image":
                    result = self._handle_find_image(req, timeout)
                elif req.action == "key_press":
                    result = self._handle_key_press(req, timeout)
                elif req.action == "mouse_click":
                    result = self._handle_mouse_click(req, timeout)
                elif req.action == "scroll":
                    result = self._handle_scroll(req, timeout)
                elif req.action == "drag":
                    result = self._handle_drag(req, timeout)
                elif req.action == "execute_json":
                    result = self._handle_execute_json(req, timeout)
                else:
                    return {
                        "success": False,
                        "message": f"未知的 action: {req.action}",
                        "data": None,
                        "execution_time": time.time() - start_time
                    }

                return {
                    "success": True,
                    "message": "执行成功",
                    "data": result,
                    "execution_time": time.time() - start_time
                }

            except Exception as e:
                error_msg = f"执行失败: {str(e)}"
                if self.config.get("debug"):
                    error_msg += f"\n{traceback.format_exc()}"

                return {
                    "success": False,
                    "message": error_msg,
                    "data": None,
                    "execution_time": time.time() - start_time
                }

        def _handle_click(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理点击操作"""
            import pyautogui

            target = req.target
            params = req.params

            # If target is image path, find image and click
            if target and (target.endswith('.png') or target.endswith('.jpg') or os.path.exists(target)):
                region = params.get("region")
                confidence = params.get("confidence", 0.78)

                loc = find_image(target, region, confidence)
                if loc is None:
                    return {"clicked": False, "reason": "Image not found"}
                try:
                    pyautogui.click(loc)
                    return {"clicked": True, "position": {"x": loc[0], "y": loc[1]}}
                except Exception as e:
                    return {"clicked": False, "reason": f"Click failed: {str(e)}"}
            else:
                # Otherwise click by coordinates
                x = params.get("x", 0)
                y = params.get("y", 0)
                button = params.get("button", "left")

                try:
                    pyautogui.click(x=x, y=y, button=button)
                    return {"clicked": True, "position": {"x": x, "y": y}}
                except Exception as e:
                    return {"clicked": False, "reason": f"Click failed: {str(e)}"}

        def _handle_input(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理输入操作"""
            import pyautogui

            text = req.target
            params = req.params

            interval = params.get("interval", 0.01)

            if params.get("clear_first", False):
                pyautogui.hotkey('ctrl', 'a')
                time.sleep(0.1)

            pyautogui.write(text, interval=interval)
            return {"input": True, "text": text}

        def _handle_screenshot(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理截图操作"""
            import pyautogui

            target = req.target or f"screenshot_{int(time.time())}.png"
            params = req.params

            region = params.get("region")  # [x, y, width, height]

            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()

            screenshot.save(target)
            return {"saved": True, "path": target}

        def _handle_ocr(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理 OCR 识别操作"""
            target = req.target
            params = req.params
            if not EASYOCR_AVAILABLE:
                return {"result": "", "error": "EasyOCR未安装"}
            try:
                ocr_inst = OCRInstruction()
                task = {
                    "value": target,
                    "region": params.get("region"),
                    "language": params.get("language", "ch_sim"),
                    "confidence": params.get("confidence", 0.5)
                }
                logs = []
                def log(msg):
                    logs.append(msg)
                ctx = VarContext()
                ocr_inst.execute(ctx, None, task, log)
                result_var = params.get("result_var", "ocr_result")
                result = ctx.vars.get(result_var, "")
                return {"result": result, "logs": logs}
            except Exception as e:
                return {"result": "", "error": str(e), "logs": logs if 'logs' in locals() else []}

        def _handle_wait(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理等待操作"""
            seconds = float(req.target or req.params.get("seconds", 1))
            time.sleep(min(seconds, timeout))
            return {"waited": True, "seconds": seconds}

        def _handle_find_image(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理找图操作"""
            target = req.target
            params = req.params

            region = params.get("region")
            confidence = params.get("confidence", 0.78)

            loc = find_image(target, region, confidence)
            if loc is None:
                return {"found": False, "position": None}

            return {"found": True, "position": {"x": loc[0], "y": loc[1]}}

        def _handle_key_press(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理按键操作"""
            import pyautogui

            keys = req.target
            params = req.params

            if params.get("hotkey", False):
                key_list = [k.strip() for k in keys.split('+')]
                pyautogui.hotkey(*key_list)
            else:
                pyautogui.press(keys)

            return {"pressed": True, "keys": keys}

        def _handle_mouse_click(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理鼠标点击操作"""
            import pyautogui

            params = req.params
            x = params.get("x")
            y = params.get("y")
            button = params.get("button", "left")
            clicks = params.get("clicks", 1)

            if x is not None and y is not None:
                pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            else:
                pyautogui.click(button=button, clicks=clicks)

            return {"clicked": True, "button": button, "clicks": clicks}

        def _handle_scroll(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理滚动操作"""
            import pyautogui

            params = req.params
            clicks = params.get("clicks", 10)
            direction = params.get("direction", "down")

            if direction == "down":
                pyautogui.scroll(-clicks)
            else:
                pyautogui.scroll(clicks)

            return {"scrolled": True, "clicks": clicks, "direction": direction}

        def _handle_drag(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理拖拽操作"""
            import pyautogui

            params = req.params
            start_x = params.get("start_x", 0)
            start_y = params.get("start_y", 0)
            end_x = params.get("end_x", 0)
            end_y = params.get("end_y", 0)
            duration = params.get("duration", 0.5)

            pyautogui.drag(start_x, start_y, end_x, end_y, duration=duration)
            return {"dragged": True, "from": {"x": start_x, "y": start_y}, "to": {"x": end_x, "y": end_y}}

        def _handle_execute_json(self, req: RpaRunRequest, timeout: int) -> dict:
            """处理执行 JSON 配置文件操作"""
            target = req.target
            params = req.params

            # Load JSON configuration
            with open(target, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # Create executor
            engine = Executor()

            # Capture logs
            logs = []
            def log(msg):
                logs.append(msg)

            # Execute tasks
            engine.run_tasks(
                cfg.get("tasks", []),
                cfg.get("vars", {}),
                cfg.get("loop", False),
                log
            )

            return {"executed": True, "logs": logs}

    # ============================================================================
    # FastAPI Application Creation Function
    # ============================================================================

    def create_app(config: dict):
        """创建 FastAPI 应用"""

        app = FastAPI(
            title="RPA_Tool API",
            description="RPA_Tool HTTP API 接口",
            version=VERSION
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Create authentication dependency
        token = config.get("token", "")
        authenticate = create_auth_dependency(token)

        # Create Action Handler
        handler = ActionHandler(config)

        # ========================================================================
        # External API (requires authentication)
        # ========================================================================

        @app.post("/api/rpa/run", response_model=RpaRunResponse, dependencies=[Depends(authenticate)])
        async def run_rpa(req: RpaRunRequest):
            """
            统一 RPA 执行入口

            - **action**: 要执行的操作
            - **target**: 操作对象
            - **params**: 其他可选参数
            """
            result = handler.handle(req)
            return RpaRunResponse(**result)

        # ========================================================================
        # Internal Debug API (no authentication required, for local debugging only)
        # ========================================================================

        @app.get("/internal/tasks")
        async def list_tasks():
            """List all available actions"""
            actions = [
                "click", "input", "screenshot", "ocr", "wait",
                "find_image", "key_press", "mouse_click", "scroll",
                "drag", "execute_json"
            ]
            return {"actions": actions}

        @app.get("/internal/health")
        async def health_check():
            """Health check"""
            return {"status": "ok", "version": VERSION}

        @app.get("/internal/config")
        async def get_config(_token: str = Depends(authenticate)):
            """Get current configuration (requires authentication)"""
            # Hide token
            safe_config = config.copy()
            safe_config["token"] = "***hidden***"
            return safe_config

        return app

    # ============================================================================
    # API Server Thread Class
    # ============================================================================

    class ApiServerThread(threading.Thread):
        """API server thread"""

        def __init__(self, config: dict):
            super().__init__(daemon=True)
            self.config = config
            self.app = None
            self.server = None
            self.running = False

        def run(self):
            """运行 API 服务器"""
            self.running = True

            # Create FastAPI application
            self.app = create_app(self.config)

            # Configure uvicorn
            config = uvicorn.Config(
                self.app,
                host=self.config.get("host", "127.0.0.1"),
                port=self.config.get("port", 8000),
                log_level="info" if self.config.get("debug") else "warning",
                loop="asyncio"
            )
            self.server = uvicorn.Server(config)
            self.server.install_signal_handlers = lambda: None

            # Start server
            print(f"[API] Starting server: http://{self.config.get('host', '127.0.0.1')}:{self.config.get('port', 8000)}")
            print(f"[API] Token: {self.config.get('token', '')}")
            self.server.run()

        def stop(self):
            """Stop API server"""
            if self.server:
                print("[API] Stopping server...")
                self.server.should_exit = True
                self.running = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='RPA Automation Tool')
    parser.add_argument('--task', type=str, help='JSON task file path')
    parser.add_argument('--api', action='store_true', help='Start API server')
    parser.add_argument('--api-port', type=int, default=8000, help='API server port')
    args = parser.parse_args()

    if args.api:
        # Run API server independently
        if not API_AVAILABLE:
            print("[ERROR] FastAPI or uvicorn not installed, please run: pip install fastapi uvicorn")
            sys.exit(1)

        # Generate Token
        import secrets
        token = secrets.token_urlsafe(32)

        config = {
            "host": "127.0.0.1",
            "port": args.api_port,
            "token": token,
            "default_timeout": 30,
            "debug": False
        }

        print(f"[INFO] Token: {token}")
        print(f"[INFO] 监听地址: http://127.0.0.1:{args.api_port}")

        server_thread = ApiServerThread(config)
        server_thread.start()

        try:
            server_thread.join()
        except KeyboardInterrupt:
            print("\n[INFO] 收到中断信号，停止服务器...")
            server_thread.stop()
    elif args.task:
        run_cli(args.task)
    else:
        main()