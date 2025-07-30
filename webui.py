from dotenv import load_dotenv
load_dotenv()

import argparse
import sys
import contextlib
import logging
import asyncio
import threading
import websockets
from src.webui.interface import theme_map, create_ui

websocket_clients = set()
websocket_loop = None  # ✅ 全局事件循环引用

# ✅ 安全的调试输出
def debug(msg):
    sys.__stdout__.write(f"{msg}\n")
    sys.__stdout__.flush()

# ✅ WebSocket 客户端处理器
async def websocket_handler(websocket):
    websocket_clients.add(websocket)
    debug(f"[WS] 客户端已连接，当前连接数: {len(websocket_clients)}")
    try:
        async for _ in websocket:
            pass
    except Exception as e:
        debug(f"[WS] 接收消息异常: {e}")
    finally:
        websocket_clients.remove(websocket)
        debug(f"[WS] 客户端断开连接，剩余连接数: {len(websocket_clients)}")

# ✅ WebSocket 服务主循环
async def websocket_server():
    global websocket_loop
    websocket_loop = asyncio.get_running_loop()
    debug("[WS] 启动 WebSocket 服务：ws://0.0.0.0:7789")
    async with websockets.serve(websocket_handler, "0.0.0.0", 7789, ping_interval=None):
        await asyncio.Future()

def start_websocket_server():
    asyncio.run(websocket_server())

# ✅ 广播日志消息
def broadcast_log_message(message):
    if not websocket_clients:
        debug(f"[WS] 无客户端连接，跳过广播：{message}")
        return

    debug(f"[WS] 广播消息：{message}，连接数: {len(websocket_clients)}")
    send_tasks = []
    for ws in websocket_clients.copy():
        try:
            send_tasks.append(ws.send(message))
        except Exception as e:
            debug(f"[WS] 过滤 ws 失败: {e}")

    if send_tasks and websocket_loop:
        try:
            future = asyncio.run_coroutine_threadsafe(
                asyncio.gather(*send_tasks, return_exceptions=True),
                websocket_loop
            )
            future.result()
        except Exception as e:
            debug(f"[WS] 广播 handler 异常: {e}")

# ✅ 标准输出流拦截（用于捕获 print 和第三方输出）
class TeeLoggerStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream
        self._buffer = ""

    def write(self, message):
        self.original_stream.write(message)
        self.original_stream.flush()
        self._buffer += message
        if "\n" in self._buffer:
            lines = self._buffer.split("\n")
            for line in lines[:-1]:
                if line.strip():
                    broadcast_log_message(line.strip())
            self._buffer = lines[-1]

    def flush(self):
        self.original_stream.flush()

    def isatty(self):
        return self.original_stream.isatty()

    def close(self):
        pass  # 无文件写入

# ✅ logging handler → 广播
class BroadcastingHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            broadcast_log_message(msg)
        except Exception as e:
            debug(f"[WS] 广播 handler 异常: {e}")

# ✅ 清除所有已有 handler 并附加广播 handler（防止重复）
def attach_handler_to_all_loggers(*handlers):
    # 清理所有 logger 的已有 handler
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).handlers.clear()
    logging.getLogger().handlers.clear()

    # 添加 handler 并关闭向上传播
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    loggers.append(logging.getLogger())
    for logger in loggers:
        for handler in handlers:
            if handler not in logger.handlers:
                logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False  # ✅ 禁止传播，防止重复广播

# ✅ 启动 Gradio WebUI
def main():
    parser = argparse.ArgumentParser(description="Gradio WebUI for Browser Agent")
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="IP address to bind to")
    parser.add_argument("--port", type=int, default=7788, help="Port to listen on")
    parser.add_argument("--theme", type=str, default="Ocean", choices=theme_map.keys(), help="Theme to use for the UI")
    args = parser.parse_args()

    debug(f"[INFO] 启动 WebUI 服务：http://{args.ip}:{args.port}")
    demo = create_ui(theme_name=args.theme)
    demo.queue().launch(server_name=args.ip, server_port=args.port)

# ✅ 主程序入口
if __name__ == '__main__':
    debug("[MAIN] 启动 WebSocket 线程...")
    threading.Thread(target=start_websocket_server, daemon=True).start()

    tee_stdout = TeeLoggerStream(sys.stdout)
    tee_stderr = TeeLoggerStream(sys.stderr)

    broadcast_handler = BroadcastingHandler()
    broadcast_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))

    attach_handler_to_all_loggers(broadcast_handler)

    with contextlib.redirect_stdout(tee_stdout), contextlib.redirect_stderr(tee_stderr):
        main()
