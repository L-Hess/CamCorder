from threading import Thread
from queue import Queue
import time
import cmd


class InteractiveShell(cmd.Cmd, Thread):
    prompt = '>'
    def __init__(self, cam):
        self.cam = cam
        Thread.__init__(self)
        cmd.Cmd.__init__(self)

    def run(self):
        self.cmdloop('Good day!')

    def do_greet(self, line):
        print('Hello')

    def do_fps(self, line):
        print(self.cam.fps)

class DummyCorder:
    def __init__(self):
        self.fps = 30

    def loop(self):
        while True:
            time.sleep(0.03)

if __name__ == '__main__':
    cam = DummyCorder()
    sh = InteractiveShell(cam)
    sh.daemon = True
    sh.start()

    while True:
        time.sleep(1)