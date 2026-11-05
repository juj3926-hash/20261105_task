"""수업용 TCP 모의 장치. 실제 PLC·로봇 프로토콜이 아니다."""
import json
import socket
import socketserver
import threading
import time

HOST = "127.0.0.1"
PORT_A, PORT_B = 9101, 9102


class Device:
    def __init__(self, name, delay):
        self.name, self.delay = name, delay
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.output = self.target = 0
            self.started = self.due = None
            self.mode = "normal"
            self.requests = 0
            self.history = []

    def _tick(self):
        if self.due is not None and time.monotonic() >= self.due:
            self.output = self.target
            self.history.append(("complete", self.output, time.monotonic()))
            self.started = self.due = None

    def snapshot(self):
        with self.lock:
            self._tick()
            progress = 1.0 if self.due is None else min(1.0, (time.monotonic() - self.started) / self.delay)
            return {"name": self.name, "output": self.output, "busy": self.due is not None,
                    "target": self.target, "progress": progress, "mode": self.mode,
                    "delay": self.delay, "requests": self.requests}

    def set_mode(self, mode):
        if mode not in ("normal", "silent"):
            raise ValueError("모드 오류")
        with self.lock:
            self.mode = mode

    def handle(self, command):
        with self.lock:
            self._tick()
            self.requests += 1
            if self.mode == "silent":
                return None  # 이 모형에서만 요청 미실행·무응답을 함께 재현한다.
            if command == "status":
                return {"ok": True, "output": self.output, "busy": self.due is not None, "target": self.target}
            if command not in ("on", "off"):
                return {"ok": False, "error": "unknown command"}
            target = int(command == "on")
            self.history.append(("command", target, time.monotonic()))
            if not (self.due is not None and self.target == target):
                self.target = target
                if self.output == target:
                    self.started = self.due = None
                else:
                    self.started = time.monotonic()
                    self.due = self.started + self.delay
            return {"ok": True, "accepted": True}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3.0)
        try:
            line = self.rfile.readline(4097)
            if not line or len(line) > 4096 or not line.endswith(b"\n"):
                return
            try:
                request = json.loads(line.decode("utf-8"))
                if not isinstance(request, dict) or not isinstance(request.get("command"), str):
                    raise ValueError("command 문자열 필요")
                response = self.server.device.handle(request["command"])
            except (ValueError, UnicodeError):
                response = {"ok": False, "error": "invalid request"}
            if response is None:
                self.connection.recv(1)  # client가 timeout 뒤 닫으면 즉시 끝난다.
                return
            self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
        except (OSError, ValueError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class DeviceServers:
    """모의 장치는 제어용 asyncio loop와 다른 스레드에서 요청을 처리한다."""
    def __init__(self, ports=(PORT_A, PORT_B), delays=(2.0, 4.0)):
        self.devices = [Device("A", delays[0]), Device("B", delays[1])]
        self.servers = []
        self.threads = []
        try:
            for port, device in zip(ports, self.devices):
                server = Server((HOST, port), Handler)
                server.device = device
                self.servers.append(server)
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            self.close()
            raise
        self.ports = tuple(server.server_address[1] for server in self.servers)

    def close(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
